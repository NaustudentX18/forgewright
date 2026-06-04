"""PythonExecuteTool — run a Python snippet via subprocess or Docker."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any, ClassVar

from forgewright.config import get_settings
from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["PythonExecuteTool"]


# Header shown in the tool result to make the source visible to the model.
_RESULT_HEADER = "python3 -c <code>"


def _max_output_chars() -> int:
    """Per-stream truncation cap, sourced from Settings."""
    return get_settings().tools.max_output_chars


def _format_output(stdout: str, stderr: str, exit_code: int) -> str:
    """Assemble the body of a `ToolResult.output` from a captured run."""
    cap = _max_output_chars()
    truncated_parts: list[str] = []
    if len(stdout) > cap:
        stdout = stdout[:cap] + "\n... [truncated]"
        truncated_parts.append("stdout truncated")
    if len(stderr) > cap:
        stderr = stderr[:cap] + "\n... [truncated]"
        truncated_parts.append("stderr truncated")
    note = f" ({'; '.join(truncated_parts)})" if truncated_parts else ""
    body = f"$ {_RESULT_HEADER}\nexit: {exit_code}{note}"
    if stdout:
        body += f"\nstdout:\n{stdout}"
    if stderr:
        body += f"\nstderr:\n{stderr}"
    return body


class PythonExecuteTool(BaseTool):
    """Run a Python snippet and return its stdout/stderr."""

    name: ClassVar[str] = "python_execute"
    description: ClassVar[str] = (
        "Run a Python snippet and return its stdout/stderr. "
        "By default runs in a subprocess with a timeout. "
        "Set mode='docker' for hard-sandboxed execution (requires [sandbox] extra)."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python code to execute."},
            "timeout_s": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 300,
                "description": "Per-call timeout in seconds.",
            },
            "mode": {
                "type": "string",
                "enum": ["subprocess", "docker"],
                "default": "subprocess",
                "description": "Execution backend.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the spawned process.",
            },
        },
        "required": ["code"],
    }
    timeout_s: ClassVar[int] = 30  # outer BaseTool cap; per-call timeout_s is lower

    async def _run(  # type: ignore[override]
        self,
        *,
        code: str,
        timeout_s: int = 5,
        mode: str = "subprocess",
        cwd: str | None = None,
    ) -> ToolResult:
        """Dispatch to the chosen backend."""
        if mode == "subprocess":
            return await self._run_subprocess(code, timeout_s, cwd)
        if mode == "docker":
            return await self._run_docker(code, timeout_s)
        return ToolResult(is_error=True, error=f"Unknown mode: {mode}")

    async def _run_subprocess(self, code: str, timeout_s: int, cwd: str | None) -> ToolResult:
        """Run Python in a subprocess; kill it on timeout."""
        try:
            # Keep this synchronous inside the async tool wrapper. In
            # uv-managed test/runtime environments, asyncio subprocess
            # and asyncio.to_thread child execution can hang even when
            # the same subprocess.run call completes immediately.
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                cwd=cwd,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("python_execute.timeout timeout_s={} cwd={}", timeout_s, cwd)
            return ToolResult(
                is_error=True,
                error=f"TimeoutError: python execution exceeded {timeout_s}s",
            )
        except FileNotFoundError as exc:
            logger.warning("python_execute.spawn_failed err={}", exc)
            return ToolResult(is_error=True, error=f"python3 not found on PATH: {exc}")
        except Exception as exc:  # broad: never crash the agent loop
            logger.warning("python_execute.spawn_failed err={}", exc)
            return ToolResult(is_error=True, error=f"Failed to spawn: {type(exc).__name__}: {exc}")

        stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        exit_code = proc.returncode
        return ToolResult(
            output=_format_output(stdout, stderr, exit_code),
            error=None if exit_code == 0 else f"exit {exit_code}",
            is_error=exit_code != 0,
        )

    async def _run_docker(self, code: str, timeout_s: int) -> ToolResult:
        """Run `python3 -c <code>` in an ephemeral Docker container.

        This is a stub: Phase 10 owns the real `Sandbox` Protocol that
        replaces this method. The limits encoded below are the spec's
        defaults for the DockerSandbox backend (see ARCHITECTURE.md §8).
        """
        try:
            import docker
            from docker.errors import APIError, ContainerError
        except ImportError:
            return ToolResult(
                is_error=True,
                error=(
                    "docker mode requires the [sandbox] extra. "
                    "Install with: uv pip install 'forgewright[sandbox]'"
                ),
            )

        def _run_container() -> tuple[int, str, str]:
            """Blocking Docker call run inside `asyncio.to_thread`."""
            client = docker.from_env()
            try:
                output = client.containers.run(
                    image="python:3.12-slim",
                    command=["python3", "-c", code],
                    mem_limit="512m",
                    pids_limit=256,
                    network_mode="none",
                    read_only=True,
                    cap_drop=["ALL"],
                    user="nobody",
                    working_dir="/tmp",
                    remove=True,
                    stdout=True,
                    stderr=True,
                )
            except ContainerError as exc:
                # docker.errors.ContainerError only carries `stderr`; stdout is
                # in `exc.container` logs when `stdout=True` is passed.
                stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
                stdout = ""
                if getattr(exc, "container", None) is not None:
                    try:
                        stdout = exc.container.logs(stdout=True, stderr=False).decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        stdout = ""
                return exc.exit_status, stdout, stderr
            except APIError as exc:
                return 1, "", f"docker API error: {exc}"
            return 0, output.decode("utf-8", errors="replace"), ""

        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run_container), timeout=timeout_s
            )
        except TimeoutError:
            logger.warning("python_execute.docker_timeout timeout_s={}", timeout_s)
            return ToolResult(
                is_error=True,
                error=f"TimeoutError: docker execution exceeded {timeout_s}s",
            )

        return ToolResult(
            output=_format_output(stdout, stderr, exit_code),
            error=None if exit_code == 0 else f"exit {exit_code}",
            is_error=exit_code != 0,
        )
