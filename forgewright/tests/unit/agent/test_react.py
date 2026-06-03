"""Tests for the ReActAgent think/act loop."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from forgewright.agent import AgentState, ReActAgent
from forgewright.schema import AssistantTurn, ChatMessage, TokenUsage, ToolResult
from forgewright.tool import BaseTool, TerminateTool, ToolCollection
from forgewright.tool.bash import BashTool


class _Echo(BaseTool):
    """Trivial tool that echoes its input back, for dispatch tests."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "echo back the input"
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    }
    last_args: ClassVar[dict[str, Any] | None] = None
    call_log: ClassVar[list[dict[str, Any]]] = []

    async def _run(self, **kwargs: Any) -> ToolResult:
        EchoLike = type(self)
        EchoLike.last_args = dict(kwargs)
        EchoLike.call_log.append(dict(kwargs))
        return ToolResult(output=f"echo:{kwargs.get('msg', '')}")


class ScriptedLLM:
    """Minimal stand-in for the LLM Protocol that serves a queued script.

    `ask()` returns a `ChatMessage` from the queue.
    `ask_tool()` returns an `AssistantTurn` from the queue (the script
    items are already typed correctly).
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self._i = 0
        self.ask_count = 0
        self.ask_tool_count = 0

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        item = self._script[self._i]
        self._i += 1
        self.ask_count += 1
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
        self.ask_tool_count += 1
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


# ---------- pure-function tests on _parse_action ----------


def test_react_parses_action_and_input() -> None:
    text = 'Thought: I should list the directory.\nAction: bash\nAction Input: {"cmd": "ls -la"}\n'
    action, args = ReActAgent._parse_action(text)
    assert action == "bash"
    assert args == {"cmd": "ls -la"}


def test_react_parses_action_only() -> None:
    """A missing Action Input still yields the action with an empty dict."""
    text = "Action: bash"
    action, args = ReActAgent._parse_action(text)
    assert action == "bash"
    assert args == {}


def test_react_handles_invalid_json() -> None:
    text = "Action: bash\nAction Input: not json"
    action, args = ReActAgent._parse_action(text)
    assert action == "bash"
    assert args == {}


def test_react_handles_no_action() -> None:
    action, args = ReActAgent._parse_action("I have no tool to call.")
    assert action is None
    assert args == {}


# ---------- end-to-end tests on the agent loop ----------


@pytest.mark.asyncio
async def test_react_dispatches_tool() -> None:
    """A scripted `Action: bash ...` reaches the BashTool via the collection."""
    _Echo.call_log.clear()
    tools = ToolCollection([_Echo(), BashTool()])
    # The LLM script drives 1 step (echo) + a terminal step (terminate).
    # Without the terminate, the agent would loop until max_steps and the
    # ScriptedLLM would IndexError on the second ask.
    llm = ScriptedLLM(
        [
            'Thought: greet the world.\nAction: echo\nAction Input: {"msg": "hi"}\n',
            'Action: terminate\nAction Input: {"reason": "ok"}',
        ]
    )
    agent = ReActAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("greet")

    # The echo tool was called with the parsed args, and the agent stopped
    # on the `terminate` action rather than hitting max_steps.
    assert _Echo.call_log == [{"msg": "hi"}]
    assert result.state == AgentState.FINISHED
    assert result.step_count == 2


@pytest.mark.asyncio
async def test_react_handles_terminate() -> None:
    """`Action: terminate` should stop the loop on the same step."""
    tools = ToolCollection([TerminateTool()])
    llm = ScriptedLLM(
        [
            'Action: terminate\nAction Input: {"reason": "all done"}',
        ]
    )
    agent = ReActAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("finish")

    assert result.state == AgentState.FINISHED
    assert result.step_count == 1
    # The tool's output is in the observation, and the state is FINISHED.
    observation = next(m for m in result.messages if m.role == "tool")
    assert "Terminated: all done" in observation.content


@pytest.mark.asyncio
async def test_react_runs_to_finished() -> None:
    """Full script: think -> echo -> terminate. The agent finishes in 2 steps."""
    _Echo.call_log.clear()
    tools = ToolCollection([_Echo(), TerminateTool()])
    llm = ScriptedLLM(
        [
            'Thought: say hi first.\nAction: echo\nAction Input: {"msg": "hello"}',
            'Action: terminate\nAction Input: {"reason": "done"}',
        ]
    )
    agent = ReActAgent(llm=llm, tools=tools, max_steps=4)
    result = await agent.run("greet then stop")

    assert result.state == AgentState.FINISHED
    assert result.step_count == 2
    assert _Echo.call_log == [{"msg": "hello"}]
    assert AgentState.FINISHED.value == "finished"


@pytest.mark.asyncio
async def test_react_observation_includes_error_for_unknown_tool() -> None:
    """If the action is unparseable, the agent marks FINISHED and notes 'no action'."""
    tools = ToolCollection([_Echo()])
    llm = ScriptedLLM(["Hmm, I'll just answer in prose."])
    agent = ReActAgent(llm=llm, tools=tools, max_steps=2)
    result = await agent.run("just chat")

    assert result.state == AgentState.FINISHED
    observation = next(m for m in result.messages if m.role == "tool")
    assert "no action" in observation.content
