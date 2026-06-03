"""``MCPAgent`` — the MCP-aware sub-agent.

A focused ``Manus`` subclass that defaults to file editing + termination
and grows a live set of MCP proxy tools at runtime via
:meth:`add_mcp_tools`. The persona prompt is loaded from
``agent/prompts/mcp.md``.
"""

from __future__ import annotations

from typing import ClassVar

from forgewright.agent.manus import Manus
from forgewright.tool import StrReplaceEditor, TerminateTool
from forgewright.tool.base import BaseTool
from forgewright.tool.collection import ToolCollection

__all__ = ["MCPAgent"]


class MCPAgent(Manus):
    """MCP-aware sub-agent. Default tool set is just file editing + terminate.

    Remote MCP tools are added at runtime via :meth:`add_mcp_tools`. The
    ``__init__`` is inherited from :class:`Manus`, which already reads
    ``self.DEFAULT_TOOLS`` and ``self.DEFAULT_PROMPT`` to assemble the
    initial tool collection and load the persona prompt.

    The default set deliberately omits ``BashTool``, ``PythonExecuteTool``,
    and ``WebSearchTool``: the MCP sub-agent's job is to call remote
    tools, not to run code locally. The orchestrator owns those.
    """

    DEFAULT_TOOLS: ClassVar[tuple[type[BaseTool], ...]] = (
        StrReplaceEditor,
        TerminateTool,
    )
    DEFAULT_PROMPT: ClassVar[str] = "mcp"

    def add_mcp_tools(self, tool_classes: tuple[type[BaseTool], ...]) -> None:
        """Add MCP tool classes to this agent's collection at runtime.

        Phase 7: rebuilds the ``ToolCollection`` with ``DEFAULT_TOOLS``
        unioned with ``tool_classes``. This is enough to wire the agent
        stack; no MCP client is actually opened.

        Phase 8: the factory will also receive a live ``ClientSession``,
        and ``_run`` on the proxy will dispatch over the wire. The
        call signature here stays the same — pass a tuple of proxy
        classes produced by :func:`forgewright.mcp.make_proxy`.
        """
        combined = self.DEFAULT_TOOLS + tool_classes
        self.tools = ToolCollection([cls() for cls in combined])
