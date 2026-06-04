"""Tests for shared CLI cap helpers."""

from __future__ import annotations

from forgewright.cli.caps import resolve_session_caps, wrap_llm_with_caps
from forgewright.config import CostConfig, LLMConfig, Settings
from forgewright.llm import MeteredLLM, StubBackend


def test_resolve_session_caps_uses_settings_defaults() -> None:
    settings = Settings(
        llm=LLMConfig(provider="stub", model="stub-model"),
        cost=CostConfig(max_usd_per_session=1.25, max_iterations_per_session=7),
    )

    assert resolve_session_caps(settings) == (1.25, 7)


def test_resolve_session_caps_cli_flags_win() -> None:
    settings = Settings(
        llm=LLMConfig(provider="stub", model="stub-model"),
        cost=CostConfig(max_usd_per_session=1.25, max_iterations_per_session=7),
    )

    assert resolve_session_caps(settings, max_cost=0, max_iterations=0) == (0.0, 0)


def test_wrap_llm_with_caps_skips_unlimited_caps() -> None:
    backend = StubBackend()

    assert wrap_llm_with_caps(backend, max_usd=0, max_iterations=0) is backend
    assert wrap_llm_with_caps(backend, max_usd=float("inf"), max_iterations=0) is backend


def test_wrap_llm_with_caps_wraps_when_iteration_cap_enabled() -> None:
    backend = StubBackend()

    wrapped = wrap_llm_with_caps(backend, max_usd=0, max_iterations=2)

    assert isinstance(wrapped, MeteredLLM)
    assert wrapped.max_usd == float("inf")
    assert wrapped.max_iterations == 2
