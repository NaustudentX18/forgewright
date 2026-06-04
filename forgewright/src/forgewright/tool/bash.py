"""BashTool — run a shell command via subprocess.

The denylist is enforced before execution. Commands whose first token is
a member of ``SAFE_BUILTINS`` are passed through without ceremony;
everything else is checked against ``DANGEROUS_PATTERNS``.

Phase 10 wires the :class:`ApprovalFlow`: after the denylist passes,
the tool consults the :class:`TrustRegistry` and skips the prompt for
commands already on the user's allowlist. The flow is injected via
:meth:`set_approval` (the CLI / agent harness is responsible for the
wiring — see ``cli.trust`` and the Manus agent bootstrap).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, ClassVar

from forgewright.config import get_settings
from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.security.approval import ApprovalDecision, ApprovalFlow
from forgewright.security.denylist import check_command
from forgewright.security.trust import TrustRegistry
from forgewright.tool.base import BaseTool

__all__ = ["BashTool"]


def _max_output_chars() -> int:
    """Per-stream truncation cap, sourced from Settings."""
    return get_settings().tools.max_output_chars


def _shell_executable() -> str:
    """Resolve a stable shell executable for subprocess execution."""
    return shutil.which("sh") or "/bin/sh"


class BashTool(BaseTool):
    """Run a shell command. Dangerous commands are hard-blocked."""

    name: ClassVar[str] = "bash"
    description: ClassVar[str] = (
        "Run a shell command. DANGEROUS commands (rm -rf /, curl|sh, kill 1, "
        "mkfs, etc.) are hard-blocked by the denylist. Safe builtins "
        "(ls, cat, grep, git status, pytest, etc.) run without confirmation."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "The shell command to run."},
            "cwd": {"type": "string", "description": "Working directory."},
            "timeout_s": {
                "type": "integer",
                "default": 30,
                "description": "Per-call timeout in seconds.",
            },
            "env": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Extra env vars to merge into the environment.",
            },
        },
        "required": ["cmd"],
    }
    timeout_s: ClassVar[int] = 30  # outer BaseTool timeout; per-call can be lower

    def __init__(self) -> None:
        super().__init__()
        # Optional Phase-10 approval wiring. ``None`` means the tool
        # runs the legacy "denylist-only" path so existing tests and
        # callers keep working without changes.
        self._approval: ApprovalFlow | None = None
        self._trust: TrustRegistry | None = None

    def set_approval(self, approval: ApprovalFlow, trust: TrustRegistry) -> None:
        """Inject the approval flow + trust registry.

        Called by the CLI / Manus agent bootstrap. After this call the
        tool's flow becomes: denylist → trust allowlist → approval
        prompt → execute.
        """
        self._approval = approval
        self._trust = trust

    async def _run(  # type: ignore[override]
        self,
        *,
        cmd: str,
        cwd: str | None = None,
        timeout_s: int = 30,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        """Validate, spawn, and capture a shell command."""
        # 1. Denylist check.
        match = check_command(cmd)
        if match is not None:
            logger.warning(
                "bash.denied pattern={} desc={} cmd={}",
                match.pattern,
                match.description,
                cmd[:200],
            )
            return ToolResult(
                is_error=True,
                error=(
                    f"Refused: {match.description} "
                    f"(matched: {match.pattern}; saw: {match.matched_text!r})"
                ),
            )

        # 1b. Approval flow (Phase 10). If an ApprovalFlow is wired in
        # AND the command is not on the trust allowlist, ask the user.
        if self._approval is not None and not self._approval.should_approve(cmd):
            result = await self._approval.request_approval(cmd)
            if result.decision not in (
                ApprovalDecision.YES,
                ApprovalDecision.ALWAYS,
                ApprovalDecision.SESSION,
            ):
                logger.info("bash.user_denied cmd={} decision={}", cmd[:120], result.decision.value)
                return ToolResult(
                    is_error=True,
                    error=f"User denied command: {cmd[:80]}",
                )

        # 2. Build the subprocess environment.
        proc_env: dict[str, str] | None = None
        if env:
            proc_env = {**os.environ, **env}

        # 3. Spawn the shell. Use synchronous subprocess.run with its
        # own timeout instead of asyncio subprocess helpers: in some
        # uv-managed environments the async child watcher can hang
        # after a child exits. This blocks the tool coroutine while the
        # command runs, but preserves the public per-call timeout.
        try:
            proc = subprocess.run(
                [_shell_executable(), "-c", cmd],
                capture_output=True,
                cwd=cwd,
                env=proc_env,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                is_error=True,
                error=f"Command timed out after {timeout_s}s: {cmd[:100]}",
            )
        except Exception as exc:
            logger.warning("bash.spawn_failed cmd={} err={}", cmd[:200], exc)
            return ToolResult(
                is_error=True,
                error=f"Failed to spawn: {type(exc).__name__}: {exc}",
            )

        # 4. Decode captured output.
        stdout_b = proc.stdout or b""
        stderr_b = proc.stderr or b""
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        exit_code = proc.returncode

        # 5. Truncate at the configured cap (per stream).
        cap = _max_output_chars()
        truncated_parts: list[str] = []
        if len(stdout) > cap:
            stdout = stdout[:cap] + (f"\n... [truncated {len(stdout_b) - cap} chars]")
            truncated_parts.append("stdout truncated")
        if len(stderr) > cap:
            stderr = stderr[:cap] + (f"\n... [truncated {len(stderr_b) - cap} chars]")
            truncated_parts.append("stderr truncated")
        truncation_note = f" ({'; '.join(truncated_parts)})" if truncated_parts else ""

        # 6. Assemble the body.
        body = f"$ {cmd}\nexit: {exit_code}{truncation_note}"
        if stdout:
            body += f"\nstdout:\n{stdout}"
        if stderr:
            body += f"\nstderr:\n{stderr}"

        return ToolResult(
            output=body,
            error=None if exit_code == 0 else f"exit {exit_code}",
            is_error=exit_code != 0,
        )
