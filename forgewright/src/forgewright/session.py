"""Session — persisted REPL state.

A session is a JSON file under ``~/.local/share/forgewright/sessions/``
(one file per session, named ``<id>.json``). The on-disk schema is
intentionally minimal so v0.1 can round-trip without committing to the
full event log from ``docs/RESEARCH.md`` Appendix A. That richer
schema lands in a follow-up agent; the structure here is designed to
be backwards-compatible (additive ``metadata`` and ``events`` fields).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.schema import ChatMessage

__all__ = ["Session", "default_sessions_dir", "now_iso"]


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix.

    Example: ``2026-06-02T12:34:56Z``.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_sessions_dir() -> Path:
    """Return the default directory for persisted sessions.

    Falls back to ``~/.local/share/forgewright/sessions`` because
    :class:`forgewright.config.Settings` has no ``data_dir`` field in
    v0.1; when one lands we should switch this to read it.
    """
    return Path.home() / ".local" / "share" / "forgewright" / "sessions"


@dataclass
class Session:
    """A persisted REPL session.

    Attributes
    ----------
    id
        A stable identifier; written to ``<id>.json`` on disk. Defaults
        to a random uuid4 hex string so two sessions opened in the
        same millisecond don't collide.
    created_at, updated_at
        ISO-8601 UTC timestamps. ``updated_at`` is bumped on every
        successful ``save()`` call (callers may set it manually
        between saves to reflect in-memory edits).
    messages
        The conversation history. Each item is a
        :class:`forgewright.schema.ChatMessage` and round-trips via
        Pydantic v2's ``model_dump`` / ``model_validate``.
    metadata
        Free-form bag. Conventionally carries ``model``,
        ``max_steps``, ``agent_class``, ``total_input_tokens``,
        ``total_output_tokens``, etc. Unknown keys are preserved
        on load.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    id: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ``ChatMessage`` is a Pydantic model; ``field`` doesn't
        # coerce, so callers may pass dicts. Normalise here.
        self.messages = [
            m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m)
            for m in self.messages
        ]

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict representation."""
        return {
            "schema_version": self.SCHEMA_VERSION,
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.model_dump() for m in self.messages],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        """Build a :class:`Session` from its dict form."""
        return cls(
            id=d["id"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            messages=[ChatMessage.model_validate(m) for m in d.get("messages", [])],
            metadata=dict(d.get("metadata", {})),
        )

    # ------------------------------------------------------------------ #
    # Disk I/O
    # ------------------------------------------------------------------ #

    def save(self, sessions_dir: str | Path) -> Path:
        """Write this session to ``sessions_dir/<id>.json``.

        Creates ``sessions_dir`` (and any parents) if missing. Bumps
        ``updated_at`` to "now" before writing.
        """
        d = Path(sessions_dir)
        d.mkdir(parents=True, exist_ok=True)
        self.updated_at = now_iso()
        path = d / f"{self.id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        logger.debug("session.save id={} path={}", self.id, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> Session:
        """Read a session from a JSON file path."""
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def list_recent(cls, sessions_dir: str | Path, limit: int = 10) -> list[Session]:
        """Return the ``limit`` most recently updated sessions, newest first.

        Silently skips files that fail to parse so a single corrupt
        session doesn't break the whole listing.
        """
        d = Path(sessions_dir)
        if not d.exists():
            return []
        sessions: list[Session] = []
        for f in d.glob("*.json"):
            try:
                sessions.append(cls.load(f))
            except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
                logger.warning("session.list_recent.skip path={} err={}", f, exc)
                continue
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    # ------------------------------------------------------------------ #
    # Factories
    # ------------------------------------------------------------------ #

    @classmethod
    def new(cls, metadata: dict[str, Any] | None = None) -> Session:
        """Build a brand-new session with random id and current timestamps."""
        ts = now_iso()
        return cls(
            id=uuid.uuid4().hex,
            created_at=ts,
            updated_at=ts,
            messages=[],
            metadata=dict(metadata or {}),
        )

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        """Return the number of messages in the session."""
        return len(self.messages)

    def asdict(self) -> dict[str, Any]:
        """``dataclasses.asdict`` view — useful for debugging.

        Note: nested ``ChatMessage`` instances are converted to dicts
        here, which is different from :meth:`to_dict` (which uses
        ``model_dump`` and respects field aliases).
        """
        return asdict(self)
