"""Manus — the top-level general-purpose agent."""

from __future__ import annotations

from typing import ClassVar

from forgewright.agent.prompts import load_prompt
from forgewright.agent.tool_call import ToolCallAgent
from forgewright.llm import LLM
from forgewright.tool import (
    AskHumanTool,
    BashTool,
    PythonExecuteTool,
    StrReplaceEditor,
    TerminateTool,
    ToolCollection,
    WebSearchTool,
)
from forgewright.tool.base import BaseTool

__all__ = ["Manus"]


class Manus(ToolCallAgent):
    """The general-purpose orchestrator. Default tool set + system prompt.

    Subclasses (DataAnalysis, BrowserAgent, MCPAgent) override `DEFAULT_TOOLS`
    and `DEFAULT_PROMPT` to specialize.
    """

    DEFAULT_TOOLS: ClassVar[tuple[type[BaseTool], ...]] = (
        BashTool,
        StrReplaceEditor,
        PythonExecuteTool,
        WebSearchTool,
        AskHumanTool,
        TerminateTool,
    )
    DEFAULT_PROMPT: ClassVar[str] = "manus"

    def __init__(self, llm: LLM, max_steps: int = 8) -> None:
        tools = ToolCollection([cls() for cls in self.DEFAULT_TOOLS])
        prompt = load_prompt(self.DEFAULT_PROMPT) + self._tools_inventory(tools)
        super().__init__(
            llm=llm,
            tools=tools,
            max_steps=max_steps,
            system_prompt=prompt,
        )

    @staticmethod
    def _tools_inventory(tools: ToolCollection) -> str:
        """Append a 'Currently available tools' line so the prompt stays honest."""
        names = ", ".join(tools.names())
        return f"\n\nCurrently available tools: {names}."
