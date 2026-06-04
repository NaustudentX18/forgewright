"""``MeteredLLM`` — per-session cost/iteration cap wrapper (H2.3).

Wraps any :class:`LLMBackend` so every :meth:`ask` / :meth:`ask_tool`
call goes through a pre-call cap check and a post-call counter bump.
The cap is enforced **before** the LLM is invoked, so a runaway loop
can be reined in on the very next iteration rather than racking up
usage against an already-exhausted budget.

The wrapper does not own the LLM's :attr:`usage` counter — the inner
backend is the single source of truth for token counts (matching the
existing :class:`forgewright.cost.CostTracker` contract). On each
post-call bump, the running USD cost is re-computed from the inner
backend's cumulative :meth:`usage` via :func:`forgewright.cost.cost_for`.

Free-tier models (``provider/model`` is ``"stub/..."`` or has a model
name beginning with ``"free"``)
do **not** increment cost or iteration counters. Their cost is
permanently zero in the pricing table, so a cost cap cannot fire on
them; skipping the iteration counter too keeps the cap a no-op for
test scaffolding and free local models.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from typing import Any

from forgewright.cost import (
    CostLimitReached,
    IterationLimitReached,
    cost_for,
)
from forgewright.llm.base import LLMBackend
from forgewright.logger import logger
from forgewright.schema import AssistantTurn, ChatMessage, ToolSpec

__all__ = ["MeteredLLM"]


def _is_free_tier(model_id: str) -> bool:
    """Return True for free-tier model ids.

    The check is on the full ``provider/model`` string so an
    ``"openai/free-eval"`` model is treated the same as a stub.
    """
    provider, _, model = model_id.partition("/")
    return provider in {"stub", "free"} or model.startswith("free")


class MeteredLLM:
    """LLM wrapper that enforces per-session cost + iteration caps.

    Parameters
    ----------
    inner
        The underlying LLM backend whose ``ask`` / ``ask_tool`` calls
        we gate.
    max_usd
        Per-session USD cap. ``float("inf")`` (the default) disables
        the cap. A value of 0 is also treated as "unlimited" — there
        is no implicit "one free call" budget.
    max_iterations
        Per-session LLM-call cap. ``0`` (the default) disables the
        cap.

    The wrapper exposes :attr:`iterations` and :attr:`cost_so_far` as
    read-only counters for diagnostics and tests. It does **not**
    re-implement streaming, count_tokens, or supports_tool_calling —
    those delegate to the inner backend so behaviour stays identical
    to the un-wrapped path.
    """

    def __init__(
        self,
        inner: LLMBackend,
        *,
        max_usd: float = float("inf"),
        max_iterations: int = 0,
    ) -> None:
        self._inner: LLMBackend = inner
        self._max_usd: float = (
            float("inf") if float(max_usd) <= 0 else float(max_usd)
        )
        self._max_iterations: int = max(0, int(max_iterations))
        self._iterations: int = 0
        self._cost_so_far: float = 0.0
        # Cache the model id once; it never changes for a given backend.
        self._model_id: str = f"{inner.config.provider}/{inner.config.model}"

    # ------------------------------------------------------------------ #
    # Pass-through properties
    # ------------------------------------------------------------------ #

    @property
    def inner(self) -> LLMBackend:
        """The wrapped LLM backend."""
        return self._inner

    @property
    def config(self):  # type: ignore[no-untyped-def]
        """Pass-through to the inner backend's config."""
        return self._inner.config

    @property
    def model_id(self) -> str:
        """The full ``provider/model`` id used for pricing."""
        return self._model_id

    @property
    def is_free_tier(self) -> bool:
        """True when the model id is treated as free (no counter bumps)."""
        return _is_free_tier(self._model_id)

    @property
    def max_usd(self) -> float:
        """The configured USD cap (``inf`` means unlimited)."""
        return self._max_usd

    @property
    def max_iterations(self) -> int:
        """The configured iteration cap (``0`` means unlimited)."""
        return self._max_iterations

    @property
    def iterations(self) -> int:
        """Number of successful (non-erroring) LLM calls so far."""
        return self._iterations

    @property
    def cost_so_far(self) -> float:
        """Running USD cost, recomputed from the inner LLM's usage."""
        return self._cost_so_far

    # ------------------------------------------------------------------ #
    # LLM protocol pass-throughs
    # ------------------------------------------------------------------ #

    def usage(self):  # type: ignore[no-untyped-def]
        """Pass-through to the inner backend's :meth:`usage`."""
        return self._inner.usage()

    def max_context_tokens(self) -> int:
        return self._inner.max_context_tokens()

    def supports_tool_calling(self) -> bool:
        return self._inner.supports_tool_calling()

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        return self._inner.count_tokens(messages)

    def stream(
        self, messages: list[ChatMessage], **kw: Any
    ) -> AsyncIterator[str]:
        return self._inner.stream(messages, **kw)

    # ------------------------------------------------------------------ #
    # Gated calls
    # ------------------------------------------------------------------ #

    def _check_pre_call(self) -> None:
        """Raise if either cap has been hit.

        Called **before** every ``ask`` / ``ask_tool`` so the LLM is
        never invoked against an already-exhausted budget.
        """
        if self._max_iterations > 0 and self._iterations >= self._max_iterations:
            raise IterationLimitReached(
                f"iteration cap {self._max_iterations} reached "
                f"(iterations={self._iterations})",
                iterations=self._iterations,
                cap=self._max_iterations,
            )
        if math.isfinite(self._max_usd) and self._cost_so_far >= self._max_usd:
            raise CostLimitReached(
                f"cost cap ${self._max_usd:.4f} reached "
                f"(cost=${self._cost_so_far:.4f})",
                cost=self._cost_so_far,
                cap=self._max_usd,
            )

    def _bump_post_call(self) -> None:
        """Recompute cost + increment iterations after a successful call.

        No-ops for free-tier models so neither cap can fire on a
        perpetually-zero-cost model.
        """
        if self.is_free_tier:
            return
        self._iterations += 1
        usage = self._inner.usage()
        self._cost_so_far = cost_for(
            self._model_id, usage.input_tokens, usage.output_tokens
        )

    async def ask(self, messages: list[ChatMessage], **kw: Any) -> ChatMessage:
        self._check_pre_call()
        try:
            response = await self._inner.ask(messages, **kw)
        except Exception as exc:
            # Errors do not consume the budget — let them propagate.
            logger.warning(
                "metered.ask.error model={} err={!r}", self._model_id, exc
            )
            raise
        self._bump_post_call()
        return response

    async def ask_tool(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        **kw: Any,
    ) -> AssistantTurn:
        self._check_pre_call()
        try:
            response = await self._inner.ask_tool(messages, tools, **kw)
        except Exception as exc:
            logger.warning(
                "metered.ask_tool.error model={} err={!r}", self._model_id, exc
            )
            raise
        self._bump_post_call()
        return response
