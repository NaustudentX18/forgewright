"""Tests for the Manus orchestrator (composition of ToolCallAgent + tools + prompt)."""

from __future__ import annotations

from typing import Any

import pytest
from forgewright.agent import AgentState, Manus
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


class ScriptedManusLLM:
    """LLM that returns a single tool call followed by a TASK_COMPLETE turn."""

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
                AssistantTurn(content="ok TASK_COMPLETE"),
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
        tools: list,
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


def test_manus_default_tool_set() -> None:
    """Manus exposes the 6 v0.1 standard tools."""
    m = Manus(llm=ScriptedManusLLM(), max_steps=2)
    assert m.tools.names() == sorted(
        {
            BashTool().name,
            StrReplaceEditor().name,
            PythonExecuteTool().name,
            WebSearchTool().name,
            AskHumanTool().name,
            TerminateTool().name,
        }
    )
    assert len(m.tools) == 6


def test_manus_system_prompt_loaded() -> None:
    """The first memory message is the Manus system prompt from prompts/manus.md."""
    m = Manus(llm=ScriptedManusLLM(), max_steps=2)
    assert m.memory is not None
    first = m.memory.snapshot()[0]
    assert first.role == "system"
    # The prompt mentions Manus and the available tools; check a stable
    # substring that the .md file is expected to include.
    assert "Manus" in first.content
    assert "TASK_COMPLETE" in first.content


@pytest.mark.asyncio
async def test_manus_uses_tool_call_agent_behavior() -> None:
    """Scripted stub LLM: one tool call, then TASK_COMPLETE -> FINISHED in <=2 steps."""
    m = Manus(llm=ScriptedManusLLM(), max_steps=4)
    result = await m.run("hi")
    assert result.state == AgentState.FINISHED
    assert result.step_count <= 2
