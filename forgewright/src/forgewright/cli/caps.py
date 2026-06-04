"""Shared CLI helpers for H2.3 per-session LLM caps."""

from __future__ import annotations

import math

from forgewright.config import Settings
from forgewright.llm import LLM, LLMBackend, MeteredLLM

__all__ = ["resolve_session_caps", "wrap_llm_with_caps"]


def resolve_session_caps(
    settings: Settings,
    *,
    max_cost: float | None = None,
    max_iterations: int | None = None,
) -> tuple[float, int]:
    """Resolve per-session caps with CLI flags taking precedence."""
    cap_usd = (
        float(max_cost)
        if max_cost is not None
        else settings.cost.max_usd_per_session
    )
    cap_iter = (
        int(max_iterations)
        if max_iterations is not None
        else settings.cost.max_iterations_per_session
    )
    return cap_usd, cap_iter


def wrap_llm_with_caps(
    backend: LLMBackend,
    *,
    max_usd: float,
    max_iterations: int,
) -> LLM:
    """Return ``backend`` wrapped in ``MeteredLLM`` when either cap is enabled."""
    if max_iterations > 0 or (max_usd > 0 and math.isfinite(max_usd)):
        return MeteredLLM(
            backend,
            max_usd=max_usd,
            max_iterations=max_iterations,
        )
    return backend
