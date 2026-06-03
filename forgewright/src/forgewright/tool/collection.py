"""ToolCollection — routes tool calls by name and aggregates provider specs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["ToolCollection"]


class ToolCollection:
    """An ordered, name-indexed container for BaseTool instances.

    The agent loop dispatches every tool call through `call(name, **kwargs)`.
    Lookups are by short `name` (no namespace prefix at this layer — that
    is the registry's job).
    """

    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        """Initialize with an optional initial list of tools."""
        self._tools: dict[str, BaseTool] = {}
        if tools:
            for tool in tools:
                self.add(tool)

    def add(self, tool: BaseTool) -> None:
        """Register a tool, keyed by `tool.name` (overwrites on collision)."""
        if tool.name in self._tools:
            logger.warning("tool.overwrite name={}", tool.name)
        self._tools[tool.name] = tool

    def remove(self, name: str) -> None:
        """Remove a tool by name. Silently no-op if absent."""
        self._tools.pop(name, None)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[BaseTool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> BaseTool | None:
        """Return the tool registered under `name`, or None."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Return a sorted list of registered tool names."""
        return sorted(self._tools)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Aggregate every tool as an OpenAI function-calling spec."""
        return [t.to_openai_tool() for t in self._tools.values()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Aggregate every tool as an Anthropic tool-use spec."""
        return [t.to_anthropic_tool() for t in self._tools.values()]

    async def call(self, name: str, **kwargs: Any) -> ToolResult:
        """Dispatch a call to the tool registered under `name`."""
        tool = self._tools.get(name)
        if tool is None:
            available = self.names()
            logger.warning("tool.unknown name={} available={}", name, available)
            return ToolResult(
                is_error=True,
                error=f"Unknown tool: {name}. Available: {available}",
            )
        return await tool(**kwargs)
