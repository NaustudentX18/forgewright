"""`SubprocessSandbox` — the default backend, no isolation.

Use only for trusted code. There are no memory / FS / network limits; the
agent has the user's full permissions. The only safety net is a
per-call timeout and a clean kill on expiry.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import ClassVar

from forgewright.logger import logger
from forgewright.sandbox._base import SandboxResult, SandboxStatus

__all__ = ["SubprocessSandbox"]


class SubprocessSandbox:
    """Run shell commands via synchronous subprocess plumbing."""

    name: ClassVar[str] = "subprocess"

    async def run(
        self,
        cmd: str,
        *,
        timeout_s: int = 30,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Spawn ``cmd`` in a child process and capture its output.

        On timeout the child is killed and a ``SandboxResult`` with
        ``timed_out=True`` and ``exit_code=-1`` is returned.
        """
        logger.debug("subprocess.run cmd={!r} cwd={} timeout={}", cmd, cwd, timeout_s)
        start = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            stdout_b, stderr_b = proc.communicate()
            logger.warning("subprocess.timeout cmd={!r} timeout_s={}", cmd, timeout_s)
            return SandboxResult(
                stdout="",
                stderr="",
                exit_code=-1,
                duration_s=time.monotonic() - start,
                timed_out=True,
            )
        return SandboxResult(
            stdout=(stdout_b or b"").decode("utf-8", errors="replace"),
            stderr=(stderr_b or b"").decode("utf-8", errors="replace"),
            exit_code=proc.returncode,
            duration_s=time.monotonic() - start,
        )

    async def write(self, path: str | Path, content: str | bytes) -> None:
        """Write ``content`` to ``path``, creating parent dirs as needed."""
        p = Path(path)
        # Keep filesystem work synchronous. This method is already a
        # short local operation, and asyncio.to_thread can hang in the
        # uv-managed runtime used by tests on this host.
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)

    async def read(self, path: str | Path) -> str:
        """Read ``path`` as text (UTF-8)."""
        return Path(path).read_text()

    async def cleanup(self) -> None:
        """No-op — subprocesses are short-lived and self-cleaning."""

    def doctor(self) -> SandboxStatus:
        """Subprocess is always available on the host."""
        return SandboxStatus(name=self.name, available=True, reason="ok", details={})
