"""TerminateTool — the 1-line tool the agent calls to stop cleanly."""

from __future__ import annotations

from typing import Any, ClassVar

from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["TerminateTool"]


class TerminateTool(BaseTool):
    """Stops the agent loop with a final reason string."""

    name: ClassVar[str] = "terminate"
    description: ClassVar[str] = (
        "Stop the agent loop with a final reason. Always call this when the task is complete."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the agent is stopping."},
        },
        "required": ["reason"],
    }
    timeout_s: ClassVar[int] = 5

    async def _run(self, *, reason: str) -> ToolResult:  # type: ignore[override]
        """Return a `Terminated: <reason>` result."""
        return ToolResult(output=f"Terminated: {reason}")
