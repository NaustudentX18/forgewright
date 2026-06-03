"""Tests for the DataAnalysis sub-agent (Python + viz + file editing)."""

from __future__ import annotations

from typing import Any

import pytest
from forgewright.agent import AgentState, DataAnalysis, Manus, ToolCallAgent
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolCall,
)
from forgewright.tool import (
    DataVisualization,
    PythonExecuteTool,
    StrReplaceEditor,
    TerminateTool,
)

# --------------------------------------------------------------------------- #
# Scripted LLM                                                                 #
# --------------------------------------------------------------------------- #


class ScriptedDataAnalysisLLM:
    """A minimal scripted LLM that returns queued `AssistantTurn` objects."""

    def __init__(self, script: list[AssistantTurn]) -> None:
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


# --------------------------------------------------------------------------- #
# Defaults                                                                     #
# --------------------------------------------------------------------------- #


def test_data_analysis_default_tool_set() -> None:
    """DataAnalysis exposes exactly the 4-tool data-analysis set."""
    agent = DataAnalysis(llm=ScriptedDataAnalysisLLM([]), max_steps=2)
    assert len(agent.tools) == 4
    expected = sorted(
        {
            PythonExecuteTool().name,
            StrReplaceEditor().name,
            DataVisualization().name,
            TerminateTool().name,
        }
    )
    assert agent.tools.names() == expected


def test_data_analysis_tools_include_required_names() -> None:
    """The four expected tool names are all present in the collection."""
    agent = DataAnalysis(llm=ScriptedDataAnalysisLLM([]), max_steps=2)
    names = set(agent.tools.names())
    assert {"python_execute", "str_replace_editor", "data_visualization", "terminate"} <= names


def test_data_analysis_excludes_orchestrator_tools() -> None:
    """Bash, WebSearch, and AskHuman are intentionally NOT in the tool set."""
    agent = DataAnalysis(llm=ScriptedDataAnalysisLLM([]), max_steps=2)
    names = set(agent.tools.names())
    assert "bash" not in names
    assert "web_search" not in names
    assert "ask_human" not in names


def test_data_analysis_inherits_from_manus() -> None:
    """DataAnalysis is a Manus subclass, so it's also a ToolCallAgent/BaseAgent."""
    agent = DataAnalysis(llm=ScriptedDataAnalysisLLM([]), max_steps=2)
    assert isinstance(agent, Manus)
    assert isinstance(agent, ToolCallAgent)


# --------------------------------------------------------------------------- #
# Prompt                                                                       #
# --------------------------------------------------------------------------- #


def test_data_analysis_system_prompt_loaded() -> None:
    """The first memory message is the data-analysis prompt from prompts/data_analysis.md."""
    agent = DataAnalysis(llm=ScriptedDataAnalysisLLM([]), max_steps=2)
    first = agent.memory.snapshot()[0]
    assert first.role == "system"
    # The prompt must reference data analysis and the tools available.
    lower = first.content.lower()
    assert "data" in lower
    assert "analysis" in lower
    # The injected tools inventory line is appended (Manus does this).
    assert "Currently available tools" in first.content
    # And the literal completion token is mentioned.
    assert "TASK_COMPLETE" in first.content


# --------------------------------------------------------------------------- #
# End-to-end runs                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_data_analysis_terminates_in_few_steps() -> None:
    """A simple 'tool call -> TASK_COMPLETE' script finishes in <=4 steps."""
    llm = ScriptedDataAnalysisLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="terminate",
                        args={"reason": "done"},
                    )
                ],
            ),
            AssistantTurn(content="ok TASK_COMPLETE"),
        ]
    )
    agent = DataAnalysis(llm=llm, max_steps=4)
    result = await agent.run("analyze something")

    assert result.state == AgentState.FINISHED
    assert result.step_count <= 4


@pytest.mark.asyncio
async def test_data_analysis_dispatches_data_visualization_call() -> None:
    """A scripted `data_visualization` tool call is dispatched and observed."""
    spec = {
        "data": {"values": [{"x": 1, "y": 2}, {"x": 2, "y": 3}]},
        "mark": "point",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    llm = ScriptedDataAnalysisLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[
                    ToolCall(
                        id="viz1",
                        name="data_visualization",
                        args={"spec": spec, "format": "html"},
                    )
                ],
            ),
            AssistantTurn(content="Chart rendered. TASK_COMPLETE"),
        ]
    )
    agent = DataAnalysis(llm=llm, max_steps=4)
    result = await agent.run("chart it")

    assert result.state == AgentState.FINISHED
    # A `tool` message with the matching id and name should appear in memory.
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    viz_msg = next(m for m in tool_msgs if m.name == "data_visualization")
    assert viz_msg.tool_call_id == "viz1"
    # The tool should have produced real HTML (Altair is installed in CI).
    assert "vega" in viz_msg.content.lower() or "<html" in viz_msg.content.lower()
