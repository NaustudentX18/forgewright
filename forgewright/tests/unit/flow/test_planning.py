"""Tests for the PlanningFlow orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from forgewright.agent import (
    AgentState,
    BrowserAgent,
    DataAnalysis,
    Manus,
    MCPAgent,
)
from forgewright.flow import FlowResult, PlanningFlow
from forgewright.flow.planning_tool import PlanningTool, StepStatus
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolCall,
)
from forgewright.tool import (
    AskHumanTool,
    BashTool,
    PythonExecuteTool,
    StrReplaceEditor,
    TerminateTool,
    WebSearchTool,
)

# --------------------------------------------------------------------------- #
# Scripted LLM
# --------------------------------------------------------------------------- #


class ScriptedLLM:
    """A reusable scripted LLM that returns queued responses.

    Each ``ask`` / ``ask_tool`` call returns the next item from
    ``ask_script`` / ``tool_script``; when a script is exhausted, the
    last item is returned (so agents that loop a few times after
    finishing still terminate cleanly).
    """

    def __init__(
        self,
        ask_script: list[str | ChatMessage] | None = None,
        tool_script: list[AssistantTurn] | None = None,
    ) -> None:
        self._ask_script: list[ChatMessage] = []
        for item in ask_script or []:
            if isinstance(item, ChatMessage):
                self._ask_script.append(item)
            else:
                self._ask_script.append(ChatMessage(role="assistant", content=str(item)))
        self._tool_script: list[AssistantTurn] = list(tool_script or [])
        self._ask_i = 0
        self._tool_i = 0
        self.ask_count = 0
        self.tool_count = 0
        self.last_ask_messages: list[ChatMessage] = []

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        self.ask_count += 1
        self.last_ask_messages = list(messages)
        if not self._ask_script:
            return ChatMessage(role="assistant", content="TASK_COMPLETE")
        idx = min(self._ask_i, len(self._ask_script) - 1)
        self._ask_i += 1
        return self._ask_script[idx]

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[Any],
        **kw: Any,
    ) -> AssistantTurn:
        self.tool_count += 1
        if not self._tool_script:
            return AssistantTurn(content="TASK_COMPLETE", tool_calls=[])
        idx = min(self._tool_i, len(self._tool_script) - 1)
        self._tool_i += 1
        return self._tool_script[idx]

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


# Standard "agent immediately terminates" script: a single `terminate`
# tool call followed by a TASK_COMPLETE text reply.
def _terminate_script() -> list[AssistantTurn]:
    return [
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


def _ok_text_script() -> list[str | ChatMessage]:
    return ["TASK_COMPLETE"]


# --------------------------------------------------------------------------- #
# Structural / metadata
# --------------------------------------------------------------------------- #


def test_planning_flow_default_agents() -> None:
    """DEFAULT_AGENTS includes the four Phase 7 sub-agents."""
    assert set(PlanningFlow.DEFAULT_AGENTS) == {
        "manus",
        "data_analysis",
        "browser_agent",
        "mcp_agent",
    }
    assert PlanningFlow.DEFAULT_AGENTS["manus"] is Manus
    assert PlanningFlow.DEFAULT_AGENTS["data_analysis"] is DataAnalysis
    assert PlanningFlow.DEFAULT_AGENTS["browser_agent"] is BrowserAgent
    assert PlanningFlow.DEFAULT_AGENTS["mcp_agent"] is MCPAgent


def test_planning_flow_init_starts_with_empty_tool() -> None:
    """A fresh PlanningFlow owns a fresh, empty PlanningTool."""
    flow = PlanningFlow(llm=ScriptedLLM(), max_total_steps=2)
    assert isinstance(flow.planning_tool, PlanningTool)
    assert flow.planning_tool.steps == {}


# --------------------------------------------------------------------------- #
# Decomposition
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_decompose_parses_json_fence() -> None:
    """The decomposition parser extracts a list from a ````json`` fence."""
    payload = (
        "Here's the plan:\n"
        "```json\n"
        '[{"title": "A", "description": "do A", "agent": "manus"}, '
        '{"title": "B", "description": "do B", "agent": "data_analysis"}]\n'
        "```\n"
    )
    parsed = PlanningFlow._parse_step_list(payload)
    assert parsed is not None
    assert len(parsed) == 2
    assert parsed[0]["title"] == "A"
    assert parsed[0]["agent"] == "manus"
    assert parsed[1]["agent"] == "data_analysis"


@pytest.mark.asyncio
async def test_decompose_parses_bare_array() -> None:
    """The parser also handles a bare top-level JSON array."""
    payload = '[{"title": "A", "description": "d", "agent": "manus"}]'
    parsed = PlanningFlow._parse_step_list(payload)
    assert parsed is not None
    assert parsed[0]["title"] == "A"


@pytest.mark.asyncio
async def test_decompose_falls_back_on_garbage() -> None:
    """Non-JSON input yields `None` so the flow can fall back."""
    assert PlanningFlow._parse_step_list("no json here at all") is None
    assert PlanningFlow._parse_step_list("") is None
    # Wrong root type.
    assert PlanningFlow._parse_step_list('{"foo": 1}') is None


@pytest.mark.asyncio
async def test_decompose_filters_invalid_items() -> None:
    """Items missing keys are dropped; the list must not be empty afterwards."""
    payload = (
        '[{"title": "OK", "description": "d", "agent": "manus"}, {"title": "Bad"}, "not an object"]'
    )
    parsed = PlanningFlow._parse_step_list(payload)
    assert parsed is not None
    assert len(parsed) == 1
    assert parsed[0]["title"] == "OK"


@pytest.mark.asyncio
async def test_decompose_calls_llm_and_registers_steps() -> None:
    """A 2-step plan returned by the LLM is registered on the planning tool."""
    payload = (
        "```json\n"
        '[{"title": "Research", "description": "search", "agent": "manus"}, '
        '{"title": "Plot", "description": "chart it", "agent": "data_analysis"}]\n'
        "```"
    )
    llm = ScriptedLLM(ask_script=[payload])
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    # Drive only decomposition; do not execute sub-agents here.
    raw = await flow._decompose("do thing")
    assert len(raw) == 2
    assert raw[0]["agent"] == "manus"
    assert raw[1]["agent"] == "data_analysis"


# --------------------------------------------------------------------------- #
# End-to-end run()
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_flow_runs_two_step_plan_end_to_end() -> None:
    """A 2-step plan runs end-to-end and produces 2 completed steps."""
    plan_json = (
        "```json\n"
        '[{"title": "Research", "description": "look it up", "agent": "manus"}, '
        '{"title": "Plot", "description": "chart it", "agent": "data_analysis"}]\n'
        "```"
    )
    # Decomposition call -> the plan. Per-agent calls: a terminate tool
    # call and a TASK_COMPLETE text reply.
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    result = await flow.run("do the thing")

    assert isinstance(result, FlowResult)
    assert result.total_step_count == 2
    assert all(s.status == StepStatus.COMPLETED for s in result.steps)
    # The 2 steps are s1 + s2.
    assert [s.id for s in result.steps] == ["s1", "s2"]
    assert result.state == AgentState.FINISHED


@pytest.mark.asyncio
async def test_flow_routes_to_the_right_agent_class() -> None:
    """Each step is executed by the agent class named in the plan."""
    plan_json = (
        "```json\n"
        '[{"title": "A", "description": "x", "agent": "data_analysis"}, '
        '{"title": "B", "description": "y", "agent": "browser_agent"}]\n'
        "```"
    )
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    seen_classes: list[type[Manus]] = []

    real_build = PlanningFlow._build_agent

    def spy_build(self: PlanningFlow, cls: type[Manus], description: str) -> Manus:
        seen_classes.append(cls)
        return real_build(self, cls, description)

    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    flow._build_agent = spy_build.__get__(flow, type(flow))  # type: ignore[method-assign]
    await flow.run("thing")

    assert seen_classes == [DataAnalysis, BrowserAgent]


@pytest.mark.asyncio
async def test_flow_runs_steps_in_order() -> None:
    """Steps are executed in the order returned by the planner."""
    plan_json = (
        "```json\n"
        '[{"title": "First", "description": "1", "agent": "manus"}, '
        '{"title": "Second", "description": "2", "agent": "manus"}, '
        '{"title": "Third", "description": "3", "agent": "manus"}]\n'
        "```"
    )
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    call_order: list[str] = []

    real_run_step = PlanningFlow._run_step

    async def spy_run_step(self: PlanningFlow, step, description: str):  # type: ignore[no-untyped-def]
        call_order.append(step.id)
        return await real_run_step(self, step, description)

    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=6)
    flow._run_step = spy_run_step.__get__(flow, type(flow))  # type: ignore[method-assign]
    await flow.run("thing")
    assert call_order == ["s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_flow_falls_back_to_manus_on_parse_failure() -> None:
    """If the LLM returns garbage, the flow still runs (as a single Manus step)."""
    llm = ScriptedLLM(
        ask_script=["no json here at all, just words"],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    result = await flow.run("thing")
    assert result.total_step_count == 1
    assert result.steps[0].agent == "manus"
    assert result.steps[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_flow_unknown_agent_falls_back_to_manus() -> None:
    """An unknown agent name in a step defaults to Manus."""
    plan_json = (
        '```json\n[{"title": "Mystery", "description": "do it", "agent": "no_such_agent"}]\n```'
    )
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    seen: list[type[Manus]] = []
    real_build = PlanningFlow._build_agent

    def spy_build(self: PlanningFlow, cls: type[Manus], description: str) -> Manus:
        seen.append(cls)
        return real_build(self, cls, description)

    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    flow._build_agent = spy_build.__get__(flow, type(flow))  # type: ignore[method-assign]
    result = await flow.run("thing")
    assert seen == [Manus]
    assert result.steps[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_flow_blocked_step_does_not_halt_flow() -> None:
    """A blocked sub-agent step is recorded, then the flow continues."""
    plan_json = (
        "```json\n"
        '[{"title": "A", "description": "first", "agent": "manus"}, '
        '{"title": "B", "description": "second", "agent": "manus"}]\n'
        "```"
    )

    # Per-agent scripts: step 1 returns a ToolResult that errors; step 2
    # terminates normally. The scripted LLM can't easily raise, so we
    # patch `_run_step` to simulate an error on the first call.
    real_run_step = PlanningFlow._run_step
    call_log: list[str] = []

    async def selective_run_step(  # type: ignore[no-untyped-def]
        self: PlanningFlow,
        step,
        description: str,
    ):
        call_log.append(step.id)
        if step.id == "s1":
            return step, AgentState.ERROR, ""
        return await real_run_step(self, step, description)

    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    flow._run_step = selective_run_step.__get__(flow, type(flow))  # type: ignore[method-assign]
    result = await flow.run("thing")

    # Both steps ran (call_log has both ids).
    assert call_log == ["s1", "s2"]
    # s1 is blocked, s2 is completed.
    by_id = {s.id: s for s in result.steps}
    assert by_id["s1"].status == StepStatus.BLOCKED
    assert by_id["s2"].status == StepStatus.COMPLETED
    # Overall state is ERROR because one sub-agent errored.
    assert result.state == AgentState.ERROR


@pytest.mark.asyncio
async def test_flow_enforces_wall_clock_timeout() -> None:
    """A sub-agent that sleeps longer than the timeout is aborted."""
    plan_json = '```json\n[{"title": "Slow", "description": "wait", "agent": "manus"}]\n```'
    llm = ScriptedLLM(ask_script=[plan_json])

    async def slow_run_step(self, step, description):  # type: ignore[no-untyped-def]
        # Sleep well past the flow's timeout.
        await asyncio.sleep(2.0)
        return step, AgentState.FINISHED, "should never get here"

    flow = PlanningFlow(
        llm=llm,
        per_agent_max_steps=2,
        max_total_steps=2,
        timeout_s=0.1,
    )
    flow._run_step = slow_run_step.__get__(flow, type(flow))  # type: ignore[method-assign]
    result = await flow.run("thing")

    assert result.state == AgentState.ERROR
    assert "timed out" in result.output.lower()
    # The step is recorded as blocked.
    assert result.steps[0].status == StepStatus.BLOCKED


@pytest.mark.asyncio
async def test_flow_result_carries_step_metadata() -> None:
    """The FlowResult exposes the final step list and per-step statuses."""
    plan_json = '```json\n[{"title": "Only", "description": "single", "agent": "manus"}]\n```'
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=2)
    result = await flow.run("thing")

    assert isinstance(result, FlowResult)
    assert result.total_step_count == 1
    assert result.steps[0].id == "s1"
    assert result.steps[0].title == "Only"
    # A markdown report can be rendered.
    md = result.to_markdown()
    assert "| s1 | Only | manus | completed |" in md


@pytest.mark.asyncio
async def test_flow_caps_total_step_count() -> None:
    """A plan with more than `max_total_steps` is truncated to that cap."""
    plan_json = (
        "```json\n"
        + (
            "["
            + ", ".join(
                f'{{"title": "S{i}", "description": "d{i}", "agent": "manus"}}' for i in range(5)
            )
            + "]"
        )
        + "\n```"
    )
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=3)
    result = await flow.run("thing")
    # Only 3 of the 5 proposed steps were registered.
    assert result.total_step_count == 3


@pytest.mark.asyncio
async def test_sub_agent_includes_planning_tool() -> None:
    """The tool collection handed to a sub-agent contains the `planning` tool."""
    plan_json = '```json\n[{"title": "A", "description": "do A", "agent": "manus"}]\n```'
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    seen_collections: list[set[str]] = []
    real_build = PlanningFlow._build_agent

    def spy_build(self: PlanningFlow, cls: type[Manus], description: str) -> Manus:
        agent = real_build(self, cls, description)
        seen_collections.append(set(agent.tools.names()))
        return agent

    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=2)
    flow._build_agent = spy_build.__get__(flow, type(flow))  # type: ignore[method-assign]
    await flow.run("thing")

    # The manus tool set plus the planning tool.
    assert seen_collections, "expected at least one agent build"
    names = seen_collections[0]
    expected_default = {
        BashTool().name,
        StrReplaceEditor().name,
        PythonExecuteTool().name,
        WebSearchTool().name,
        AskHumanTool().name,
        TerminateTool().name,
    }
    assert expected_default <= names
    assert "planning" in names


@pytest.mark.asyncio
async def test_planning_tool_shared_across_sub_agents() -> None:
    """The same PlanningTool instance is used by every sub-agent in a flow."""
    plan_json = (
        "```json\n"
        '[{"title": "A", "description": "1", "agent": "manus"}, '
        '{"title": "B", "description": "2", "agent": "data_analysis"}]\n'
        "```"
    )
    llm = ScriptedLLM(
        ask_script=[plan_json],
        tool_script=_terminate_script(),
    )
    seen_planning_tools: list[PlanningTool] = []
    real_build = PlanningFlow._build_agent

    def spy_build(self: PlanningFlow, cls: type[Manus], description: str) -> Manus:
        agent = real_build(self, cls, description)
        planning = agent.tools.get("planning")
        assert planning is not None
        seen_planning_tools.append(planning)  # type: ignore[arg-type]
        return agent

    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=4)
    flow._build_agent = spy_build.__get__(flow, type(flow))  # type: ignore[method-assign]
    await flow.run("thing")

    assert len(seen_planning_tools) == 2
    # Both sub-agents got the SAME planning tool instance.
    assert seen_planning_tools[0] is seen_planning_tools[1]
    # ... and it is the flow's own.
    assert seen_planning_tools[0] is flow.planning_tool


@pytest.mark.asyncio
async def test_flow_handles_empty_decomposition() -> None:
    """If the LLM returns an empty list (after filtering), the flow falls back."""
    # This LLM emits "[]" — a valid empty array.
    llm = ScriptedLLM(
        ask_script=["```json\n[]\n```"],
        tool_script=_terminate_script(),
    )
    flow = PlanningFlow(llm=llm, per_agent_max_steps=2, max_total_steps=2)
    result = await flow.run("thing")
    # Empty array parses to nothing; we get the single-step fallback.
    assert result.total_step_count == 1
    assert result.steps[0].agent == "manus"
