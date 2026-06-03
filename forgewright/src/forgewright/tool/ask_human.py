"""AskHumanTool — interactive Rich prompt for blocking on user input."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, ClassVar

from rich.prompt import Prompt

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["AskHumanTool"]


def _prompt(question: str, default: Any) -> str:
    """Thin wrapper around `Prompt.ask` for `asyncio.to_thread`."""
    return Prompt.ask(question, default=default)


class AskHumanTool(BaseTool):
    """Ask the user a question and wait for their reply."""

    name: ClassVar[str] = "ask_human"
    description: ClassVar[str] = (
        "Ask the user a question and wait for their reply. "
        "Use when blocked or needing clarification."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "default": {
                "type": "string",
                "description": "Default answer if user just hits enter.",
            },
        },
        "required": ["question"],
    }
    timeout_s: ClassVar[int] = 300  # 5 min for a human reply

    async def _run(self, *, question: str, default: str | None = None) -> ToolResult:  # type: ignore[override]
        """Prompt the user. In non-TTY contexts (CI), short-circuit with an error."""
        if not sys.stdin.isatty():
            logger.info("ask_human.non_tty question={}", question)
            return ToolResult(
                is_error=True,
                error="No human available (non-interactive).",
            )
        # Run the blocking Rich prompt off the event loop via a small wrapper
        # to keep the signature simple and mypy happy.
        answer: str = await asyncio.to_thread(_prompt, question, default)
        return ToolResult(output=answer)
