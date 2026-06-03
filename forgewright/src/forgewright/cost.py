"""Per-session token cost tracking.

Uses a static pricing table (USD per 1M tokens) for the providers
forgewright supports out of the box. Unknown models fall back to the
``_default`` row of zeroes so the tracker never raises on a new
model name. The table is intentionally rough — for v0.1 it just
gives the user a ballpark; precise per-provider pricing lands in
v0.2 (when the dashboard recipe in ``docs/`` is wired up).
"""

from __future__ import annotations

__all__ = ["PRICING_PER_MILLION", "CostTracker", "cost_for"]


# Approximate pricing per 1M tokens (USD, as of 2026-06; update in v0.2).
PRICING_PER_MILLION: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "anthropic/claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "openai/gpt-5": {"input": 5.0, "output": 20.0},
    "openai/gpt-4o": {"input": 2.5, "output": 10.0},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 5.0},
    "stub/stub-model": {"input": 0.0, "output": 0.0},
    "_default": {"input": 0.0, "output": 0.0},
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost of ``input_tokens`` + ``output_tokens`` for ``model``.

    Unknown models resolve to the ``_default`` row, which is all zeros,
    so the function never raises. The arithmetic is per-million tokens.
    """
    pricing = PRICING_PER_MILLION.get(model, PRICING_PER_MILLION["_default"])
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing[
        "output"
    ]


class CostTracker:
    """Accumulates token cost over a session.

    The LLM's own :meth:`LLM.usage` is the source of truth for token
    counts; the tracker is a pure accumulator. A new
    :class:`CostTracker` is cheap — just pass it the model name once
    and call :meth:`record` after every LLM call.
    """

    def __init__(self, model: str) -> None:
        self._model: str = model
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    @property
    def model(self) -> str:
        """The model name this tracker prices against."""
        return self._model

    def record(self, input_tokens: int, output_tokens: int) -> None:
        """Add a usage record to the running totals.

        Negative inputs are clamped to zero; this keeps a buggy
        backend from driving the cumulative cost into a negative
        number that the user has to puzzle over.
        """
        self._input_tokens += max(0, int(input_tokens))
        self._output_tokens += max(0, int(output_tokens))

    def total(self) -> float:
        """Return the running USD cost."""
        return cost_for(self._model, self._input_tokens, self._output_tokens)

    def breakdown(self) -> dict[str, float]:
        """Return ``{"input", "output", "total"}`` as USD floats.

        The input and output cells are the per-direction subtotals;
        ``total`` is their sum (and is the same value as
        :meth:`total`). The shape is dict-of-floats so it round-trips
        cleanly to JSON for the session file.
        """
        pricing = PRICING_PER_MILLION.get(self._model, PRICING_PER_MILLION["_default"])
        input_cost = (self._input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self._output_tokens / 1_000_000) * pricing["output"]
        return {
            "input": input_cost,
            "output": output_cost,
            "total": input_cost + output_cost,
        }

    def tokens(self) -> dict[str, int]:
        """Return ``{"input", "output"}`` token counts (raw, not cost)."""
        return {"input": self._input_tokens, "output": self._output_tokens}


# Exposed for tests so they can pin the row count.
PRICING_ROW_COUNT: int = 6
