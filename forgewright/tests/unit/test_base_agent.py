"""Tests for BaseAgent and the Manus subclass."""

from __future__ import annotations

import pytest
from forgewright.agent import AgentState, BaseAgent, Manus
from forgewright.llm import LLM
from forgewright.llm.stub import StubBackend
from forgewright.schema import ChatMessage


@pytest.mark.asyncio
async def test_base_agent_runs_to_finished() -> None:
    llm = StubBackend()
    agent = BaseAgent(llm=llm, max_steps=3)
    result = await agent.run("hello")

    assert result.state == AgentState.FINISHED
    assert result.step_count >= 1
    assert result.output  # non-empty
    assert "TASK_COMPLETE" in result.output or "Hello" in result.output


@pytest.mark.asyncio
async def test_base_agent_respects_max_steps() -> None:
    """An agent that never says TASK_COMPLETE should still terminate at max_steps."""

    class NeverFinishes(LLM):  # type: ignore[misc]
        async def ask(self, messages, **kw):
            return ChatMessage(role="assistant", content="still going")

        async def ask_tool(self, messages, tools, **kw):
            from forgewright.schema import AssistantTurn

            return AssistantTurn(content="still going")

        def stream(self, messages, **kw):
            async def _gen():
                yield "still going"

            return _gen()

        def count_tokens(self, messages):
            return 0

        def max_context_tokens(self):
            return 200_000

        def supports_tool_calling(self):
            return False

        def usage(self):
            from forgewright.schema import TokenUsage

            return TokenUsage()

    agent = BaseAgent(llm=NeverFinishes(), max_steps=2)
    result = await agent.run("go")
    assert result.state == AgentState.FINISHED
    assert result.step_count == 2


@pytest.mark.asyncio
async def test_manus_prepends_system_prompt() -> None:
    llm = StubBackend()
    agent = Manus(llm=llm, max_steps=2)
    result = await agent.run("say hi")
    assert result.state == AgentState.FINISHED
    messages = result.messages
    assert messages[0].role == "system"
    assert "Manus" in messages[0].content
