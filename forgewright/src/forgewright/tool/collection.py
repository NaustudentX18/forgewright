"""ToolCollection — routes tool calls by name and aggregates provider specs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

if TYPE_CHECKING:
    from forgewright.workspace import Workspace

__all__ = ["ToolCollection"]


class ToolCollection:
    """An ordered, name-indexed container for BaseTool instances.

    The agent loop dispatches every tool call through `call(name, **kwargs)`.
    Lookups are by short `name` (no namespace prefix at this layer — that
    is the registry's job).

    An optional :class:`Workspace` can be threaded through the collection
    to workspace-aware tools (currently :class:`StrReplaceEditor`):
    writes by those tools then land inside the workspace, not the local
    CWD. The wiring is a no-op for tools that do not expose a
    ``workspace`` attribute, so existing tools keep working unchanged.
    """

    def __init__(
        self,
        tools: list[BaseTool] | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        """Initialize with an optional initial list of tools and workspace."""
        self._tools: dict[str, BaseTool] = {}
        self.workspace: Workspace | None = workspace
        if tools:
            for tool in tools:
                self.add(tool)

    def add(self, tool: BaseTool) -> None:
        """Register a tool, keyed by `tool.name` (overwrites on collision)."""
        if tool.name in self._tools:
            logger.warning("tool.overwrite name={}", tool.name)
        self._tools[tool.name] = tool
        self._apply_workspace(tool)

    def set_workspace(self, workspace: Workspace | None) -> None:
        """Set the workspace and re-apply it to every registered tool."""
        self.workspace = workspace
        for tool in self._tools.values():
            self._apply_workspace(tool)

    def _apply_workspace(self, tool: BaseTool) -> None:
        """Hand the workspace to a tool that opts in via a ``workspace`` attribute."""
        if self.workspace is None:
            return
        if hasattr(tool, "workspace"):
            tool.workspace = self.workspace

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
        # Re-apply the workspace in case it was set after the tool was added.
        self._apply_workspace(tool)
        return await tool(**kwargs)
