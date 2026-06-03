"""Tests for the BrowserAgent sub-agent."""

from __future__ import annotations

from typing import Any

import pytest
from forgewright.agent import AgentState, BrowserAgent, Manus
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolCall,
)
from forgewright.tool import (
    AskHumanTool,
    BashTool,
    BrowserUseTool,
    PythonExecuteTool,
    StrReplaceEditor,
    TerminateTool,
    WebSearchTool,
)


class ScriptedLLM:
    """Scripted LLM stub. Mirrors the pattern used in test_manus / test_tool_call."""

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


def test_browser_agent_is_manus_subclass() -> None:
    """BrowserAgent must inherit from Manus so it picks up the wiring."""
    assert issubclass(BrowserAgent, Manus)
    agent = BrowserAgent(llm=ScriptedLLM(), max_steps=2)
    assert isinstance(agent, Manus)


def test_browser_agent_default_tool_set() -> None:
    """The default tool set is exactly: BrowserUseTool, AskHumanTool, TerminateTool."""
    agent = BrowserAgent(llm=ScriptedLLM(), max_steps=2)
    expected = sorted(
        {
            BrowserUseTool().name,
            AskHumanTool().name,
            TerminateTool().name,
        }
    )
    assert agent.tools.names() == expected
    assert len(agent.tools) == 3


def test_browser_agent_excludes_heavy_tools() -> None:
    """Bash / PythonExecute / StrReplaceEditor / WebSearch / DataVisualization
    must NOT be in the tool set. The browser sub-agent has no business
    shelling out or running code.
    """
    agent = BrowserAgent(llm=ScriptedLLM(), max_steps=2)
    names = set(agent.tools.names())
    forbidden = {
        BashTool().name,
        PythonExecuteTool().name,
        StrReplaceEditor().name,
        WebSearchTool().name,
    }
    # The spec mentions DataVisualization; it isn't built yet, but we
    # assert the principle: only the three allowed tools are present.
    assert names.isdisjoint(forbidden)
    # Sanity: the 3 allowed tools ARE present.
    assert {BrowserUseTool().name, AskHumanTool().name, TerminateTool().name} <= names


def test_browser_agent_system_prompt_loaded() -> None:
    """The first memory message is the browser persona prompt from browser.md."""
    agent = BrowserAgent(llm=ScriptedLLM(), max_steps=2)
    first = agent.memory.snapshot()[0]
    assert first.role == "system"
    # Stable substrings from browser.md.
    assert "browser" in first.content.lower()
    assert "TASK_COMPLETE" in first.content
    # The tools inventory tail from Manus.__init__ should also be present.
    assert "Currently available tools" in first.content


def test_browser_agent_class_attributes_point_to_correct_names() -> None:
    """DEFAULT_PROMPT must be the file stem 'browser' (not 'manus')."""
    assert BrowserAgent.DEFAULT_PROMPT == "browser"
    assert BrowserUseTool in BrowserAgent.DEFAULT_TOOLS
    assert AskHumanTool in BrowserAgent.DEFAULT_TOOLS
    assert TerminateTool in BrowserAgent.DEFAULT_TOOLS
    # Bash / PythonExecute / etc. must not appear in the class-level tuple.
    assert BashTool not in BrowserAgent.DEFAULT_TOOLS
    assert PythonExecuteTool not in BrowserAgent.DEFAULT_TOOLS


# ---------- end-to-end run ----------


@pytest.mark.asyncio
async def test_browser_agent_runs_to_finished() -> None:
    """A scripted LLM that immediately terminates should finish in 1 step."""
    agent = BrowserAgent(llm=ScriptedLLM(), max_steps=4)
    result = await agent.run("open example.com and report the title")

    assert result.state == AgentState.FINISHED
    # The terminate call should finish the agent on step 1.
    assert result.step_count <= 4


@pytest.mark.asyncio
async def test_browser_agent_browser_call_dispatched() -> None:
    """A scripted browser -> terminate run finishes with the browser tool called."""
    # Use a minimal stub BrowserUseTool-like that records its calls? No —
    # the real BrowserUseTool's _ensure_browser will fail without
    # playwright, but its result still goes through ToolCollection.call
    # which intercepts the error. So we just assert termination, not the
    # call log, to keep this test offline-friendly.
    script = [
        AssistantTurn(
            content="",
            tool_calls=[
                ToolCall(
                    id="b1",
                    name="browser",
                    args={"action": "navigate", "url": "https://example.com"},
                )
            ],
        ),
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
    agent = BrowserAgent(llm=ScriptedLLM(script), max_steps=4)
    result = await agent.run("check example.com title")

    assert result.state == AgentState.FINISHED
    # The first step dispatched the browser call (which may have errored
    # offline); the second terminated. State should be FINISHED in <=2 steps.
    assert result.step_count <= 2
    # Memory should have a tool message for the browser call (b1).
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert any(m.tool_call_id == "b1" and m.name == "browser" for m in tool_msgs)
