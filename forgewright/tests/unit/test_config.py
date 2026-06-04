"""Tests for the config layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from forgewright.config import LLMConfig, Settings, get_settings


def test_llm_config_defaults() -> None:
    cfg = LLMConfig()
    assert cfg.provider == "stub"
    assert cfg.model == "stub-model"
    assert cfg.max_tokens == 4096


def test_settings_singleton() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b


def test_settings_extra_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown keys should not raise — pydantic-settings is forgiving by default."""
    monkeypatch.setenv("FORGEWRIGHT_UNKNOWN_KEY", "foo")
    settings = Settings()
    assert settings.llm.provider in {
        "stub",
        "openai",
        "anthropic",
        "google",
        "azure",
        "bedrock",
        "ollama",
        "openrouter",
    }


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGEWRIGHT_MAX_STEPS", "42")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        settings = get_settings()
        assert settings.max_steps == 42
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_settings_paths_use_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        settings = get_settings()
        # Should resolve to something under the fake HOME.
        assert str(tmp_path) in settings.security.audit_log
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# H0.8a-f: new sub-configs and defaults
# --------------------------------------------------------------------------- #


def test_llm_config_has_context_tokens_default() -> None:
    """H0.8a: Settings.llm.context_tokens_default exists with a sane default."""
    assert LLMConfig().context_tokens_default == 128_000


def test_llm_config_has_drop_params() -> None:
    """H0.8f: LLMConfig.drop_params defaults to True (safety net)."""
    assert LLMConfig().drop_params is True
    assert LLMConfig(drop_params=False).drop_params is False


def test_settings_cost_pricing_table_default() -> None:
    """H0.8b: Settings.cost.pricing_table defaults to
    ~/.config/forgewright/pricing.json."""
    from forgewright.config import Settings

    s = Settings()
    assert s.cost.pricing_table.endswith("pricing.json")
    assert ".config" in s.cost.pricing_table


def test_settings_tools_max_output_chars() -> None:
    """H0.8c: Settings.tools.max_output_chars defaults to 50_000."""
    from forgewright.config import Settings

    s = Settings()
    assert s.tools.max_output_chars == 50_000


def test_settings_agent_memory_max_messages() -> None:
    """H0.8d: Settings.agent.memory_max_messages defaults to 200."""
    from forgewright.config import Settings

    s = Settings()
    assert s.agent.memory_max_messages == 200


def test_settings_flow_defaults() -> None:
    """H0.8e: Settings.flow has the three budget knobs with documented defaults."""
    from forgewright.config import Settings

    s = Settings()
    assert s.flow.max_total_steps == 50
    assert s.flow.per_agent_max_steps == 25
    assert s.flow.timeout_s == 600
