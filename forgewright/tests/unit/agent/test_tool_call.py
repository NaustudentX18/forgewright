"""Tests for the ToolCallAgent native function-calling loop."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from forgewright.agent import AgentState, ToolCallAgent
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from forgewright.tool import BaseTool, TerminateTool, ToolCollection
from forgewright.tool.bash import BashTool


class _Echo(BaseTool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "echo back the input"
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    }
    call_log: ClassVar[list[dict[str, Any]]] = []

    async def _run(self, **kwargs: Any) -> ToolResult:
        type(self).call_log.append(dict(kwargs))
        return ToolResult(output=f"echo:{kwargs.get('msg', '')}")


class ScriptedToolLLM:
    """Scripted LLM that returns a queued `AssistantTurn` from `ask_tool`."""

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


@pytest.mark.asyncio
async def test_tool_call_dispatches_single_call() -> None:
    _Echo.call_log.clear()
    tools = ToolCollection([_Echo(), BashTool()])
    llm = ScriptedToolLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[ToolCall(id="1", name="echo", args={"msg": "hi"})],
            ),
            AssistantTurn(content="done TASK_COMPLETE"),
        ]
    )
    agent = ToolCallAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("say hi")

    assert _Echo.call_log == [{"msg": "hi"}]
    assert result.state == AgentState.FINISHED
    # The tool message must include the tool_call_id and the tool name.
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert any(m.tool_call_id == "1" and m.name == "echo" for m in tool_msgs)


@pytest.mark.asyncio
async def test_tool_call_dispatches_multiple_concurrently() -> None:
    """Two tool calls in one turn should both run (gather)."""
    _Echo.call_log.clear()
    tools = ToolCollection([_Echo(), BashTool()])
    llm = ScriptedToolLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[
                    ToolCall(id="1", name="echo", args={"msg": "one"}),
                    ToolCall(id="2", name="echo", args={"msg": "two"}),
                ],
            ),
            AssistantTurn(content="done TASK_COMPLETE"),
        ]
    )
    agent = ToolCallAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("say both")

    assert sorted(c["msg"] for c in _Echo.call_log) == ["one", "two"]
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert {m.tool_call_id for m in tool_msgs} == {"1", "2"}


@pytest.mark.asyncio
async def test_tool_call_finishes_on_no_tool_call() -> None:
    """A no-tool-call response that contains TASK_COMPLETE finishes the loop."""
    tools = ToolCollection([BashTool()])
    llm = ScriptedToolLLM([AssistantTurn(content="All done. TASK_COMPLETE", tool_calls=[])])
    agent = ToolCallAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("ping")

    assert result.state == AgentState.FINISHED
    assert result.step_count == 1


@pytest.mark.asyncio
async def test_tool_call_finishes_on_terminate() -> None:
    tools = ToolCollection([TerminateTool()])
    llm = ScriptedToolLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="terminate",
                        args={"reason": "byeee"},
                    )
                ],
            )
        ]
    )
    agent = ToolCallAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("stop")

    assert result.state == AgentState.FINISHED
    assert result.step_count == 1
    tool_msg = next(m for m in result.messages if m.role == "tool")
    assert "Terminated: byeee" in tool_msg.content


@pytest.mark.asyncio
async def test_tool_call_appends_observations_with_ids() -> None:
    _Echo.call_log.clear()
    tools = ToolCollection([_Echo()])
    llm = ScriptedToolLLM(
        [
            AssistantTurn(
                content="",
                tool_calls=[ToolCall(id="abc", name="echo", args={"msg": "x"})],
            ),
            AssistantTurn(content="TASK_COMPLETE", tool_calls=[]),
        ]
    )
    agent = ToolCallAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("go")

    tool_msg = next(m for m in result.messages if m.role == "tool")
    assert tool_msg.tool_call_id == "abc"
    assert tool_msg.name == "echo"
    assert "echo:x" in tool_msg.content


def test_tool_call_spec_provider_anthropic_shape() -> None:
    """`tool_spec_provider='anthropic'` should call `to_anthropic_tools()`."""
    tools = ToolCollection([_Echo(), TerminateTool()])
    agent = ToolCallAgent(
        llm=ScriptedToolLLM([]),
        tools=tools,
        tool_spec_provider="anthropic",
    )
    specs = agent._tool_specs()
    # Anthropic shape: flat dict with `name`, `description`, `input_schema`.
    assert all("input_schema" in s for s in specs)
    assert all("function" not in s for s in specs)
    by_name = {s["name"] for s in specs}
    assert by_name == {"echo", "terminate"}


def test_tool_call_spec_provider_openai_shape_default() -> None:
    tools = ToolCollection([_Echo(), TerminateTool()])
    agent = ToolCallAgent(llm=ScriptedToolLLM([]), tools=tools)
    specs = agent._tool_specs()
    # OpenAI shape: `{"type": "function", "function": {...}}`.
    assert all(s.get("type") == "function" for s in specs)
    assert all("function" in s for s in specs)
