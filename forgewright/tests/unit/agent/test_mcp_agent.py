"""Tests for the MCPAgent sub-agent (Phase 7 stub)."""

from __future__ import annotations

from typing import Any

import pytest
from forgewright.agent import AgentState, Manus, MCPAgent
from forgewright.mcp import _MCPToolSpec, make_proxy
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolCall,
)
from forgewright.tool import StrReplaceEditor, TerminateTool


class ScriptedMCPLLM:
    """LLM stub: scripted ``AssistantTurn`` queue.

    Mirrors the pattern used in test_manus / test_browser_agent so
    MCPAgent looks and behaves like its sibling sub-agents.
    """

    def __init__(self, script: list[AssistantTurn] | None = None) -> None:
        if script is None:
            script = [
                AssistantTurn(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="t1",
                            name="terminate",
                            args={"reason": "ok"},
                        )
                    ],
                ),
            ]
        self._script = list(script)
        self._i = 0

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, ChatMessage):
            return item
        return ChatMessage(role="assistant", content=str(item))

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[Any],
        **kw: Any,
    ) -> AssistantTurn:
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, AssistantTurn):
            return item
        return AssistantTurn(content=str(item), tool_calls=[])

    def stream(self, messages: list[ChatMessage], **kw: Any):
        async def _gen():
            yield ""

        return _gen()

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        return 0

    def max_context_tokens(self) -> int:
        return 200_000

    def supports_tool_calling(self) -> bool:
        return True

    def usage(self) -> TokenUsage:
        return TokenUsage()


# ---------- structural tests ----------


def test_mcp_agent_is_manus_subclass() -> None:
    """MCPAgent must inherit from Manus so it picks up the same wiring."""
    assert issubclass(MCPAgent, Manus)
    agent = MCPAgent(llm=ScriptedMCPLLM(), max_steps=2)
    assert isinstance(agent, Manus)


def test_mcp_agent_default_tool_set() -> None:
    """Default tools are exactly: StrReplaceEditor, TerminateTool."""
    agent = MCPAgent(llm=ScriptedMCPLLM(), max_steps=2)
    expected = sorted({StrReplaceEditor().name, TerminateTool().name})
    assert agent.tools.names() == expected
    assert len(agent.tools) == 2


def test_mcp_agent_class_attributes() -> None:
    """``DEFAULT_PROMPT`` is ``"mcp"`` and the right tools are in ``DEFAULT_TOOLS``."""
    assert MCPAgent.DEFAULT_PROMPT == "mcp"
    assert StrReplaceEditor in MCPAgent.DEFAULT_TOOLS
    assert TerminateTool in MCPAgent.DEFAULT_TOOLS
    # Local-shell / network / human-loop tools are deliberately out of scope.
    from forgewright.tool import AskHumanTool, BashTool, PythonExecuteTool, WebSearchTool

    assert BashTool not in MCPAgent.DEFAULT_TOOLS
    assert PythonExecuteTool not in MCPAgent.DEFAULT_TOOLS
    assert WebSearchTool not in MCPAgent.DEFAULT_TOOLS
    assert AskHumanTool not in MCPAgent.DEFAULT_TOOLS


def test_mcp_agent_system_prompt_loaded() -> None:
    """The first memory message is the MCP persona prompt from ``prompts/mcp.md``."""
    agent = MCPAgent(llm=ScriptedMCPLLM(), max_steps=2)
    first = agent.memory.snapshot()[0]
    assert first.role == "system"
    content = first.content
    # Stable substrings from mcp.md.
    assert "MCP" in content
    assert "TASK_COMPLETE" in content
    # The runtime tools-inventory tail from Manus.__init__ is appended.
    assert "Currently available tools" in content


# ---------- add_mcp_tools hook ----------


def test_add_mcp_tools_method_exists_and_is_callable() -> None:
    """The runtime extension hook is present and takes a tuple of tool classes."""
    assert hasattr(MCPAgent, "add_mcp_tools")
    assert callable(MCPAgent.add_mcp_tools)


def test_add_mcp_tools_extends_collection() -> None:
    """Calling the hook rebuilds the ToolCollection with the union of tool classes."""
    agent = MCPAgent(llm=ScriptedMCPLLM(), max_steps=2)
    initial = set(agent.tools.names())
    assert initial == {StrReplaceEditor().name, TerminateTool().name}

    ProxyCls = make_proxy(
        "fs",
        _MCPToolSpec(
            name="read_file",
            description="Read a file from the remote filesystem.",
            args_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    )
    agent.add_mcp_tools((ProxyCls,))

    names = set(agent.tools.names())
    assert names == initial | {"fs__read_file"}
    assert len(agent.tools) == 3
    # The new proxy tool is reachable by its namespaced name.
    assert agent.tools.get("fs__read_file") is not None
    assert agent.tools.get("fs__read_file").name == "fs__read_file"


# ---------- end-to-end run ----------


@pytest.mark.asyncio
async def test_mcp_agent_runs_to_finished() -> None:
    """A scripted LLM that immediately terminates should finish in <=4 steps."""
    agent = MCPAgent(llm=ScriptedMCPLLM(), max_steps=4)
    result = await agent.run("summarise the available MCP tools")

    assert result.state == AgentState.FINISHED
    assert result.step_count <= 4
