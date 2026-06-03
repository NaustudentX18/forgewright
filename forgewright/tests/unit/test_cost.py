"""Tests for :mod:`forgewright.cost`.

Covers the static ``cost_for`` helper (including the unknown-model
fallback) and the :class:`CostTracker` accumulator.
"""

from __future__ import annotations

import pytest
from forgewright.cost import (
    PRICING_PER_MILLION,
    CostTracker,
    cost_for,
)

# --------------------------------------------------------------------------- #
# cost_for
# --------------------------------------------------------------------------- #


def test_cost_for_sonnet_input_only() -> None:
    """Sonnet: 1M input tokens = $3.00."""
    assert cost_for("anthropic/claude-sonnet-4-6", 1_000_000, 0) == 3.0


def test_cost_for_sonnet_output_only() -> None:
    """Sonnet: 1M output tokens = $15.00."""
    assert cost_for("anthropic/claude-sonnet-4-6", 0, 1_000_000) == 15.0


def test_cost_for_sonnet_mixed() -> None:
    """Sonnet: 500k input + 250k output = $1.50 + $3.75 = $5.25."""
    assert cost_for("anthropic/claude-sonnet-4-6", 500_000, 250_000) == pytest.approx(5.25)


def test_cost_for_unknown_model_returns_zero() -> None:
    """Unknown models resolve to the zero-pricing default."""
    assert cost_for("unknown-model", 1_000_000, 0) == 0.0
    assert cost_for("unknown-model", 0, 1_000_000) == 0.0


def test_cost_for_stub_model_is_free() -> None:
    """The stub provider's cost is always zero."""
    assert cost_for("stub/stub-model", 10_000_000, 10_000_000) == 0.0


def test_cost_for_opus_uses_opus_pricing() -> None:
    """Opus is more expensive than Sonnet — sanity check the table."""
    sonnet = cost_for("anthropic/claude-sonnet-4-6", 1_000_000, 1_000_000)
    opus = cost_for("anthropic/claude-opus-4-7", 1_000_000, 1_000_000)
    assert opus > sonnet
    # Spot-check the exact values from the pricing table.
    assert opus == pytest.approx(15.0 + 75.0)


def test_pricing_table_has_default_row() -> None:
    """The pricing table always carries a ``_default`` zero row."""
    assert "_default" in PRICING_PER_MILLION
    assert PRICING_PER_MILLION["_default"]["input"] == 0.0
    assert PRICING_PER_MILLION["_default"]["output"] == 0.0


# --------------------------------------------------------------------------- #
# CostTracker
# --------------------------------------------------------------------------- #


def test_tracker_starts_at_zero() -> None:
    """A fresh tracker reports a zero total and zero breakdown."""
    tracker = CostTracker(model="anthropic/claude-sonnet-4-6")
    assert tracker.total() == 0.0
    breakdown = tracker.breakdown()
    assert breakdown["input"] == 0.0
    assert breakdown["output"] == 0.0
    assert breakdown["total"] == 0.0


def test_tracker_record_accumulates() -> None:
    """``record()`` adds the new usage to the running totals."""
    tracker = CostTracker(model="anthropic/claude-sonnet-4-6")
    tracker.record(input_tokens=1_000_000, output_tokens=0)
    assert tracker.total() == pytest.approx(3.0)
    tracker.record(input_tokens=0, output_tokens=1_000_000)
    assert tracker.total() == pytest.approx(3.0 + 15.0)


def test_tracker_breakdown_separates_input_and_output() -> None:
    """``breakdown()`` reports input and output as separate fields."""
    tracker = CostTracker(model="anthropic/claude-sonnet-4-6")
    tracker.record(input_tokens=1_000_000, output_tokens=1_000_000)
    bd = tracker.breakdown()
    assert bd["input"] == pytest.approx(3.0)
    assert bd["output"] == pytest.approx(15.0)
    assert bd["total"] == pytest.approx(3.0 + 15.0)


def test_tracker_total_after_multiple_records() -> None:
    """Multiple ``record()`` calls sum into ``total()``."""
    tracker = CostTracker(model="anthropic/claude-sonnet-4-6")
    for _ in range(3):
        tracker.record(input_tokens=100_000, output_tokens=50_000)
    expected = 3 * (0.1 * 3.0 + 0.05 * 15.0)
    assert tracker.total() == pytest.approx(expected)


def test_tracker_tokens_returns_counts() -> None:
    """``tokens()`` exposes the raw input/output token counts."""
    tracker = CostTracker(model="stub/stub-model")
    tracker.record(input_tokens=42, output_tokens=7)
    tokens = tracker.tokens()
    assert tokens == {"input": 42, "output": 7}


def test_tracker_clamps_negative_inputs() -> None:
    """Negative input/output values are clamped to zero (defensive)."""
    tracker = CostTracker(model="anthropic/claude-sonnet-4-6")
    tracker.record(input_tokens=-100, output_tokens=-50)
    assert tracker.total() == 0.0
    tracker.record(input_tokens=1_000_000, output_tokens=0)
    # The negative record should not have moved the baseline.
    assert tracker.total() == pytest.approx(3.0)


def test_tracker_model_property() -> None:
    """The ``model`` property returns the model passed to the constructor."""
    tracker = CostTracker(model="anthropic/claude-opus-4-7")
    assert tracker.model == "anthropic/claude-opus-4-7"


def test_tracker_breakdown_keys() -> None:
    """``breakdown()`` returns the documented key set."""
    tracker = CostTracker(model="stub/stub-model")
    bd = tracker.breakdown()
    assert set(bd.keys()) == {"input", "output", "total"}
