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


def test_memory_max_messages_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H0.8d: Memory reads its maxlen from Settings.agent.memory_max_messages."""
    from forgewright.agent import Memory
    from forgewright.config import Settings

    custom = Settings(agent={"memory_max_messages": 5})  # type: ignore[arg-type]
    monkeypatch.setattr("forgewright.agent.base.get_settings", lambda: custom)
    mem = Memory()
    # Append 8 messages; deque(maxlen=5) keeps the last 5 only.
    for i in range(8):
        mem.append(ChatMessage(role="user", content=f"m{i}"))
    assert len(mem) == 5
    snapshot = mem.snapshot()
    assert snapshot[0].content == "m3"
    assert snapshot[-1].content == "m7"


def test_memory_explicit_max_messages_wins_over_settings() -> None:
    """H0.8d: an explicit max_messages argument to Memory() still wins
    (caller-driven override; Settings is the default)."""
    from forgewright.agent import Memory

    mem = Memory(max_messages=3)
    for i in range(5):
        mem.append(ChatMessage(role="user", content=f"m{i}"))
    assert len(mem) == 3
