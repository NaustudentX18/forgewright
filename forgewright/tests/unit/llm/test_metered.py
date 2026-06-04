"""Tests for the per-session cost caps (H2.3).

Covers the ``MeteredLLM`` wrapper, the typed
``CostLimitReached`` / ``IterationLimitReached`` exceptions, and the
agent loop's behaviour when a cap is hit. Together these verify the
critical shape from ``docs/V0.3_TODO_LIST.md``:

- Pre-call hook checks accumulated cost **before** the LLM call.
- Post-call hook increments after the LLM responds.
- Free-tier models (``stub``/``free`` prefix) do **not** increment.
- Error responses do **not** increment.
- The agent loop surfaces the cap as a typed final state
  (``cost_limit_reached`` / ``iteration_limit_reached``) on the
  :class:`AgentResult`, not as a ``RuntimeError``.
"""

from __future__ import annotations

import pytest
from forgewright.agent import AgentState, Manus
from forgewright.config import LLMConfig
from forgewright.cost import CostLimitReached, IterationLimitReached
from forgewright.llm import LLMBackend, MeteredLLM, StubBackend
from forgewright.schema import AssistantTurn, ChatMessage, ToolSpec

# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #


class CountingBackend(LLMBackend):
    """An LLM backend that reports a fixed USD cost per call.

    Each call bumps the inherited ``TokenUsage`` so the wrapper's
    post-call cost recompute sees non-zero cost. The total cost per
    call is ``(input_per_call / 1M) * 3.0 + (output_per_call / 1M) * 15.0``
    against the Sonnet 4.6 pricing row in the default table.
    """

    def __init__(
        self,
        *,
        input_per_call: int = 0,
        output_per_call: int = 1000,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        super().__init__(LLMConfig(provider="anthropic", model=model))
        self._input_per_call = input_per_call
        self._output_per_call = output_per_call
        self.call_count = 0

    async def ask(self, messages, **kw):  # type: ignore[no-untyped-def, override]
        self.call_count += 1
        self._usage.input_tokens += self._input_per_call
        self._usage.output_tokens += self._output_per_call
        return ChatMessage(role="assistant", content="ok")

    async def ask_tool(self, messages, tools, **kw):  # type: ignore[no-untyped-def, override]
        self.call_count += 1
        self._usage.input_tokens += self._input_per_call
        self._usage.output_tokens += self._output_per_call
        return AssistantTurn(content="ok", tool_calls=[])

    def supports_tool_calling(self) -> bool:
        return True


class ErrorBackend(LLMBackend):
    """An LLM backend that always raises from ask_tool."""

    def __init__(self) -> None:
        super().__init__(LLMConfig(provider="anthropic", model="claude-sonnet-4-6"))
        self.call_count = 0

    async def ask(self, messages, **kw):  # type: ignore[no-untyped-def, override]
        self.call_count += 1
        raise RuntimeError("simulated LLM error")

    async def ask_tool(self, messages, tools, **kw):  # type: ignore[no-untyped-def, override]
        self.call_count += 1
        raise RuntimeError("simulated LLM error")

    def supports_tool_calling(self) -> bool:
        return True


def _empty_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hi")]


def _empty_tools() -> list[ToolSpec]:
    return []


# --------------------------------------------------------------------------- #
# Cost cap (pre-call)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cost_cap_fires_pre_call() -> None:
    """``max_usd=0.001`` with a real-pricing model must stop at the cap.

    The inner backend reports $0.015 of cost per call. After the first
    successful call the running cost exceeds the cap, so the **second**
    call's pre-call check must raise ``CostLimitReached`` before the
    LLM is invoked.
    """
    inner = CountingBackend(output_per_call=1000)
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=0)

    # First call: pre-call (0 < 0.001) passes, post-call cost = $0.015.
    await metered.ask_tool(_empty_messages(), _empty_tools())
    assert metered.cost_so_far > 0.001
    assert inner.call_count == 1

    # Second call: pre-call check must raise before the LLM is invoked.
    with pytest.raises(CostLimitReached) as exc_info:
        await metered.ask_tool(_empty_messages(), _empty_tools())
    assert exc_info.value.cap == pytest.approx(0.001)
    assert exc_info.value.cost > 0.001
    # The LLM was not invoked a second time.
    assert inner.call_count == 1


@pytest.mark.asyncio
async def test_cost_cap_default_is_unlimited() -> None:
    """No cap configured → no exceptions, no surprises."""
    inner = CountingBackend(output_per_call=1000)
    metered = MeteredLLM(inner)  # all defaults
    for _ in range(5):
        await metered.ask_tool(_empty_messages(), _empty_tools())
    assert inner.call_count == 5
    assert metered.iterations == 5
    assert metered.cost_so_far == pytest.approx(0.075)  # 5 calls at $0.015


@pytest.mark.asyncio
async def test_zero_cost_cap_is_unlimited_even_with_iteration_cap() -> None:
    """``max_usd=0`` must not trip before the first paid call."""
    inner = CountingBackend(output_per_call=1000)
    metered = MeteredLLM(inner, max_usd=0, max_iterations=2)

    await metered.ask_tool(_empty_messages(), _empty_tools())

    assert inner.call_count == 1
    assert metered.max_usd == float("inf")
    assert metered.iterations == 1


# --------------------------------------------------------------------------- #
# Iteration cap (pre-call)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_iteration_cap_fires_independently() -> None:
    """``max_iterations=2`` must allow exactly 2 calls then raise."""
    inner = CountingBackend(output_per_call=100)
    metered = MeteredLLM(inner, max_usd=float("inf"), max_iterations=2)

    await metered.ask_tool(_empty_messages(), _empty_tools())
    await metered.ask_tool(_empty_messages(), _empty_tools())
    assert inner.call_count == 2
    assert metered.iterations == 2

    with pytest.raises(IterationLimitReached) as exc_info:
        await metered.ask_tool(_empty_messages(), _empty_tools())
    assert exc_info.value.iterations == 2
    assert exc_info.value.cap == 2
    # The third call did not reach the inner LLM.
    assert inner.call_count == 2


@pytest.mark.asyncio
async def test_iteration_cap_does_not_fire_for_free_tier() -> None:
    """Free-tier models never increment → iteration cap is a no-op."""
    # StubBackend starts with "stub/" in the model id.
    inner = StubBackend()
    metered = MeteredLLM(inner, max_usd=float("inf"), max_iterations=2)

    for _ in range(5):
        await metered.ask_tool(_empty_messages(), _empty_tools())

    assert metered.iterations == 0  # free tier never increments


# --------------------------------------------------------------------------- #
# Free-tier models
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_free_tier_model_does_not_increment() -> None:
    """A stub-prefix model id never bumps cost or iteration counters.

    The test runs three LLM calls against the cap; the counters
    remain at their starting values.
    """
    inner = StubBackend()
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=2)

    # StubBackend.ask() bumps its internal counter; ask_tool() does
    # not. We exercise ask() here so the post-call bump is verifiable.
    await metered.ask(_empty_messages())
    await metered.ask(_empty_messages())
    await metered.ask(_empty_messages())

    assert metered.iterations == 0
    assert metered.cost_so_far == 0.0
    assert metered.is_free_tier is True
    # No cap fires for free-tier — the cap is structurally irrelevant.
    assert inner._call_count == 3  # internal counter on StubBackend


@pytest.mark.asyncio
async def test_free_tier_model_with_free_prefix_does_not_increment() -> None:
    """A ``provider='free'`` model is also treated as free-tier."""
    inner = StubBackend()  # uses provider='stub'/'model'='stub-model'
    # Force a model id that starts with "free/" for the pricing check.
    inner._config.provider = "free"  # type: ignore[assignment]
    inner._config.model = "preview"  # type: ignore[assignment]
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=2)

    await metered.ask_tool(_empty_messages(), _empty_tools())
    assert metered.cost_so_far == 0.0
    assert metered.iterations == 0


@pytest.mark.asyncio
async def test_free_tier_model_with_provider_prefix_does_not_increment() -> None:
    """A model id like ``openai/free-eval`` is also free-tier."""
    inner = StubBackend()
    inner._config.provider = "openai"  # type: ignore[assignment]
    inner._config.model = "free-eval"  # type: ignore[assignment]
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=1)

    await metered.ask_tool(_empty_messages(), _empty_tools())
    await metered.ask_tool(_empty_messages(), _empty_tools())

    assert metered.model_id == "openai/free-eval"
    assert metered.is_free_tier is True
    assert metered.cost_so_far == 0.0
    assert metered.iterations == 0


# --------------------------------------------------------------------------- #
# Error responses
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_error_response_does_not_increment() -> None:
    """An exception from the inner LLM must not consume the budget.

    The wrapper must propagate the error unchanged and leave both
    counters at zero.
    """
    inner = ErrorBackend()
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=2)

    with pytest.raises(RuntimeError, match="simulated LLM error"):
        await metered.ask_tool(_empty_messages(), _empty_tools())

    assert metered.iterations == 0
    assert metered.cost_so_far == 0.0
    # ask() also does not increment on error.
    with pytest.raises(RuntimeError, match="simulated LLM error"):
        await metered.ask(_empty_messages())
    assert metered.iterations == 0


# --------------------------------------------------------------------------- #
# Agent loop integration: typed final state (not a RuntimeError)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cost_limit_reached_typed_state() -> None:
    """The agent loop must surface a typed ``cost_limit_reached`` state.

    Hitting the cost cap from inside the agent loop returns an
    :class:`AgentResult` whose ``state`` is
    :class:`AgentState.COST_LIMIT_REACHED` and whose ``final_state`` is
    the documented string. No ``RuntimeError`` is raised.
    """
    inner = CountingBackend(output_per_call=1000)
    metered = MeteredLLM(inner, max_usd=0.001, max_iterations=0)
    agent = Manus(llm=metered, max_steps=10)  # type: ignore[arg-type]

    result = await agent.run("hello")

    assert result.state == AgentState.COST_LIMIT_REACHED
    assert result.final_state == "cost_limit_reached"
    # Sanity: the cap fires as a typed final state, not an exception.
    assert not isinstance(result.state, type(RuntimeError()))


@pytest.mark.asyncio
async def test_iteration_limit_reached_typed_state() -> None:
    """The agent loop must surface a typed ``iteration_limit_reached`` state."""
    inner = CountingBackend(output_per_call=100)
    metered = MeteredLLM(inner, max_usd=float("inf"), max_iterations=2)
    agent = Manus(llm=metered, max_steps=10)  # type: ignore[arg-type]

    result = await agent.run("hello")

    assert result.state == AgentState.ITERATION_LIMIT_REACHED
    assert result.final_state == "iteration_limit_reached"
    # Exactly 2 LLM calls succeeded before the cap fired on the third.
    assert inner.call_count == 2
    # The step counter includes the third iteration that raised (the
    # pre-call check fired *during* the step), so it advances past
    # the cap.
    assert result.step_count >= 2


@pytest.mark.asyncio
async def test_agent_runs_normally_when_caps_disabled() -> None:
    """No cap → agent reaches FINISHED as it did before H2.3."""
    inner = StubBackend()
    metered = MeteredLLM(inner)  # all defaults — caps disabled
    agent = Manus(llm=metered, max_steps=4)  # type: ignore[arg-type]

    result = await agent.run("hello")

    assert result.state == AgentState.FINISHED
    assert result.final_state is None
