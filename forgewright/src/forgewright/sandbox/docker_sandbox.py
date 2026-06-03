"""`DockerSandbox` — hard-sandboxed code execution via the Docker SDK.

The Docker SDK is imported lazily so the module (and the rest of the
package) loads even when ``docker`` is not installed. The first call to
``_ensure_client`` will raise a friendly :class:`RuntimeError` pointing
the user at the ``[sandbox]`` extra.

Security defaults (overridable via constructor kwargs):

* ``mem_limit="512m"`` — hard memory cap.
* ``pids_limit=256`` — fork-bomb mitigation.
* ``network_mode="none"`` — no network at all.
* ``read_only=True`` — root FS is read-only; container can't persist.
* ``cap_drop=["ALL"]`` — drop every Linux capability.
* ``user="nobody"`` — run as an unprivileged uid.
* ``working_dir="/tmp"`` — default cwd for ``run``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import tarfile
import time
from pathlib import Path
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.sandbox._base import SandboxResult, SandboxStatus

__all__ = ["DockerSandbox"]


def _make_tar_bytes(content: bytes, arcname: str) -> bytes:
    """Build a tar archive in memory containing a single file ``arcname``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        info = tarfile.TarInfo(name=arcname)
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _extract_file_from_tar(tar_bytes: bytes, arcname: str) -> bytes:
    """Extract ``arcname`` from a tar archive and return its bytes."""
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r") as tar:
        member = tar.getmember(arcname)
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"tar member {arcname!r} is not a regular file")
        return extracted.read()


def sh_quote(s: str) -> str:
    """Quote ``s`` for use in a POSIX shell single-quoted argument."""
    return "'" + s.replace("'", "'\\''") + "'"


class DockerSandbox:
    """Run shell commands in ephemeral, hard-sandboxed Docker containers."""

    name: ClassVar[str] = "docker"

    def __init__(
        self,
        image: str = "python:3.12-slim",
        mem_limit: str = "512m",
        pids_limit: int = 256,
        network_mode: str = "none",
        read_only: bool = True,
        cap_drop: list[str] | None = None,
        user: str = "nobody",
        working_dir: str = "/tmp",
    ) -> None:
        self.image = image
        self.mem_limit = mem_limit
        self.pids_limit = pids_limit
        self.network_mode = network_mode
        self.read_only = read_only
        self.cap_drop = cap_drop or ["ALL"]
        self.user = user
        self.working_dir = working_dir
        self._client: Any = None

    # ---------- client lifecycle ----------

    def _ensure_client(self) -> Any:
        """Lazily import the docker SDK and build a client from env."""
        if self._client is not None:
            return self._client
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError(
                "docker SDK not installed. Install with: uv pip install 'forgewright[sandbox]'"
            ) from exc
        self._client = docker.from_env()
        return self._client

    def _container_kwargs(self, *, working_dir: str) -> dict[str, Any]:
        """Return the kwargs shared by every ``containers.run`` call."""
        return {
            "mem_limit": self.mem_limit,
            "pids_limit": self.pids_limit,
            "network_mode": self.network_mode,
            "read_only": self.read_only,
            "cap_drop": list(self.cap_drop),
            "user": self.user,
            "working_dir": working_dir,
        }

    # ---------- run ----------

    async def run(
        self,
        cmd: str,
        *,
        timeout_s: int = 30,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run ``sh -c <cmd>`` in a one-shot container and capture its output."""
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return SandboxResult(stdout="", stderr=str(exc), exit_code=1, duration_s=0.0)

        start = time.monotonic()
        kw = self._container_kwargs(working_dir=cwd or self.working_dir)
        try:
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    client.containers.run,
                    self.image,
                    command=["sh", "-c", cmd],
                    stdout=True,
                    stderr=True,
                    remove=True,
                    detach=False,
                    environment=env,
                    **kw,
                ),
                timeout=timeout_s,
            )
        except TimeoutError:
            logger.warning("docker.timeout cmd={!r} timeout_s={}", cmd, timeout_s)
            return SandboxResult(
                stdout="",
                stderr="",
                exit_code=-1,
                duration_s=time.monotonic() - start,
                timed_out=True,
            )
        except Exception as exc:
            logger.exception("docker.run_error cmd={!r}", cmd)
            return SandboxResult(
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration_s=time.monotonic() - start,
            )
        stdout = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out)
        return SandboxResult(
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration_s=time.monotonic() - start,
        )

    # ---------- write / read ----------

    async def write(self, path: str | Path, content: str | bytes) -> None:
        """Write ``content`` to ``path`` inside a one-shot container."""
        client = self._ensure_client()
        p = Path(path)
        arcname = p.name
        tar_bytes = _make_tar_bytes(
            content.encode("utf-8") if isinstance(content, str) else content,
            arcname=arcname,
        )
        kw = self._container_kwargs(working_dir=str(p.parent))

        def _do() -> None:
            c = client.containers.run(
                self.image,
                command=[
                    "sh",
                    "-c",
                    "tar -xf - && mv " + arcname + " " + arcname + ".done || true",
                ],
                user="root",  # tar extraction needs write perms in the read_only FS
                working_dir=str(p.parent),
                remove=True,
                detach=True,
                **kw,
            )
            try:
                # put_archive expects (path, data) where data is tar bytes.
                c.put_archive(str(p.parent), tar_bytes)
                c.wait(timeout=30)
            finally:
                with contextlib.suppress(Exception):  # best-effort cleanup
                    c.remove(force=True)

        await asyncio.to_thread(_do)

    async def read(self, path: str | Path) -> str:
        """Read ``path`` from a one-shot container and return its text content."""
        client = self._ensure_client()
        p = Path(path)
        kw = self._container_kwargs(working_dir=str(p.parent))

        def _do() -> bytes:
            c = client.containers.run(
                self.image,
                command=["sh", "-c", f"tar -cf - {sh_quote(str(p.name))}"],
                working_dir=str(p.parent),
                remove=True,
                detach=False,
                **kw,
            )
            if not isinstance(c, bytes):
                raise RuntimeError(f"unexpected tar output type: {type(c).__name__}")
            return c

        raw = await asyncio.to_thread(_do)
        try:
            return _extract_file_from_tar(raw, str(p.name)).decode("utf-8", errors="replace")
        except (KeyError, FileNotFoundError) as exc:
            raise FileNotFoundError(f"{path} not found in container") from exc

    # ---------- cleanup + health ----------

    async def cleanup(self) -> None:
        """No-op — every ``run`` uses ``remove=True`` so containers don't accumulate."""

    def doctor(self) -> SandboxStatus:
        """Probe the docker daemon and return a status snapshot."""
        try:
            client = self._ensure_client()
            client.ping()  # may raise on a stopped daemon
        except RuntimeError as exc:
            return SandboxStatus(name=self.name, available=False, reason=str(exc), details={})
        except Exception as exc:
            return SandboxStatus(
                name=self.name,
                available=False,
                reason=f"{type(exc).__name__}: {exc}",
                details={},
            )
        return SandboxStatus(
            name=self.name,
            available=True,
            reason="ok",
            details={
                "image": self.image,
                "mem_limit": self.mem_limit,
                "pids_limit": self.pids_limit,
                "network_mode": self.network_mode,
                "read_only": self.read_only,
                "cap_drop": list(self.cap_drop),
                "user": self.user,
                "working_dir": self.working_dir,
            },
        )
