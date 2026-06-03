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
