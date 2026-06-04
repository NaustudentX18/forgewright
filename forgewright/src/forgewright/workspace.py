"""Workspace — the shared file surface for multi-agent collaboration.

A :class:`Workspace` is a typed file surface that multiple agents can
read and write through. It also exposes a polling-based :meth:`watch`
so a sub-agent can discover edits made by a previous sub-agent without
an explicit ``StrReplaceEditor`` round-trip.

The base class defines a small, deliberately narrow surface — enough
for file-based multi-agent collaboration, no more. Concrete
implementations (``LocalWorkspace``, future ``DockerWorkspace`` /
``RemoteSSHWorkspace``) swap the storage backend without changing
call sites.

The local implementation uses a background polling thread instead of
inotify/FSEvents so the same code runs unchanged on Linux, macOS, and
Windows. The polling interval is 1 s; missed events are acceptable
(per the spec).
"""

from __future__ import annotations

import contextlib
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

__all__ = ["LocalWorkspace", "Workspace"]


# Event types fired by :meth:`LocalWorkspace.watch`.
WATCH_EVENT_CREATED = "created"
WATCH_EVENT_MODIFIED = "modified"
WATCH_EVENT_DELETED = "deleted"

# Default polling interval for ``LocalWorkspace.watch``.
_DEFAULT_POLL_INTERVAL_S = 1.0


class Workspace(ABC):
    """The shared file surface for multi-agent collaboration.

    Concrete subclasses (e.g. :class:`LocalWorkspace`) back the surface
    with real storage. The :class:`forgewright.tool.ToolCollection`
    threads a :class:`Workspace` through to workspace-aware tools
    (e.g. :class:`StrReplaceEditor`) so writes land inside the
    workspace, not the local CWD.
    """

    @property
    @abstractmethod
    def root(self) -> Path:
        """The root directory all relative paths resolve against."""
        ...

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Return the file at ``path`` as raw bytes."""
        ...

    @abstractmethod
    def write(self, path: str, data: bytes) -> None:
        """Write ``data`` to ``path``, creating parents as needed."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if ``path`` exists in the workspace."""
        ...

    @abstractmethod
    def list_dir(self, path: str) -> list[str]:
        """Return the immediate child names of ``path``.

        Names are returned without a path prefix. An empty list means
        the directory is empty (or does not exist).
        """
        ...

    @abstractmethod
    def watch(self, callback: Callable[[str, str], None]) -> None:
        """Register ``callback`` for file-change events.

        The callback is invoked as ``callback(event_type, path)`` where
        ``event_type`` is one of ``"created"``, ``"modified"``, or
        ``"deleted"``, and ``path`` is a workspace-relative path.

        Implementations are best-effort: missed events are OK,
        duplicates are OK, ordering is not guaranteed. The callback
        runs on a background thread; it is the caller's responsibility
        to marshal back to the main thread if needed.
        """
        ...


class LocalWorkspace(Workspace):
    """A :class:`Workspace` backed by a local directory on the filesystem.

    The directory is created on construction if it does not exist.
    All paths handed to :meth:`read` / :meth:`write` / etc. are
    resolved against this root; an attempt to escape the root via
    ``..`` raises :class:`ValueError`.
    """

    def __init__(self, root: str | Path) -> None:
        """Bind this workspace to ``root`` and ensure the directory exists."""
        self._root: Path = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """The resolved root directory."""
        return self._root

    # ------------------------------------------------------------------ #
    # Path resolution
    # ------------------------------------------------------------------ #

    def _resolve(self, path: str) -> Path:
        """Resolve ``path`` against the workspace root, blocking escapes."""
        p = (self.root / path).resolve()
        try:
            p.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"Path '{path}' escapes workspace root '{self.root}'"
            ) from exc
        return p

    # ------------------------------------------------------------------ #
    # Workspace surface
    # ------------------------------------------------------------------ #

    def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def write(self, path: str, data: bytes) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def list_dir(self, path: str) -> list[str]:
        p = self._resolve(path)
        if not p.exists():
            return []
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {p}")
        return sorted(child.name for child in p.iterdir())

    def watch(self, callback: Callable[[str, str], None]) -> None:
        """Poll the workspace root every second; fire ``callback`` on changes.

        Spawns a daemon thread. The callback is invoked from that
        thread. The thread cannot be stopped (it lives for the
        process's lifetime); this is acceptable for the v0.3 use case
        where a :class:`LocalWorkspace` is typically a process-scoped
        object.
        """
        _PollingWatcher(self.root, callback).start()


class _PollingWatcher:
    """Background poller that detects file changes under a root directory.

    Maintains a ``{relpath: (mtime_ns, size)}`` snapshot; on each tick
    it computes a fresh snapshot and diffs against the previous one to
    emit ``created`` / ``modified`` / ``deleted`` events.

    The thread sleeps in a single ``Event.wait`` call so a future
    ``stop()`` would be responsive; the current API does not expose
    ``stop`` because the workspace owns the watcher for its lifetime.
    """

    def __init__(
        self,
        root: Path,
        callback: Callable[[str, str], None],
        interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._root = root
        self._callback = callback
        self._interval_s = interval_s
        self._stop_event = threading.Event()
        self._snapshot: dict[str, tuple[int, int]] | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"workspace-watcher[{root.name}]",
            daemon=True,
        )

    def start(self) -> None:
        """Spawn the polling thread (idempotent)."""
        if self._thread.is_alive():
            return
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            if self._stop_event.wait(self._interval_s):
                return

    def _tick(self) -> None:
        """One polling iteration: snapshot, diff against the previous."""
        try:
            current = self._scan()
        except OSError:
            # The root may have been deleted/moved; skip this tick.
            return
        previous = self._snapshot
        self._snapshot = current
        if previous is None:
            # First tick: this is the baseline. No events.
            return
        for path, sig in current.items():
            if path not in previous:
                self._safe_callback(WATCH_EVENT_CREATED, path)
            elif previous[path] != sig:
                self._safe_callback(WATCH_EVENT_MODIFIED, path)
        for path in previous:
            if path not in current:
                self._safe_callback(WATCH_EVENT_DELETED, path)

    def _scan(self) -> dict[str, tuple[int, int]]:
        """Build a ``{relpath: (mtime_ns, size)}`` snapshot of all files."""
        out: dict[str, tuple[int, int]] = {}
        for p in self._root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(self._root))
                stat = p.stat()
            except OSError:
                continue
            out[rel] = (stat.st_mtime_ns, stat.st_size)
        return out

    def _safe_callback(self, event_type: str, path: str) -> None:
        """Invoke the user callback, swallowing any exception it raises."""
        with contextlib.suppress(Exception):  # a buggy callback must not kill the watcher
            self._callback(event_type, path)
