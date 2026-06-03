"""Configuration via Pydantic Settings (env + dotenv; TOML is read in v0.1 Phase 1)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """LLM provider + model selection."""

    provider: Literal[
        "stub", "openai", "anthropic", "google", "azure", "bedrock", "ollama", "openrouter"
    ] = "stub"
    model: str = "stub-model"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 1.0


class SandboxConfig(BaseModel):
    """Sandbox backend selection and limits."""

    backend: Literal["subprocess", "docker", "gvisor"] = "subprocess"
    mem_limit: str = "512m"
    pids_limit: int = 256
    network_mode: str = "none"
    image: str = "python:3.12-slim"
    timeout_s: int = 30


def _default_audit_log() -> str:
    return str(Path.home() / ".local" / "share" / "forgewright" / "audit.jsonl")


def _default_trust() -> str:
    return str(Path.home() / ".config" / "forgewright" / "trust.toml")


class SecurityConfig(BaseModel):
    """Default-deny + audit + trust."""

    permission_mode: Literal["default", "acceptEdits", "plan", "auto", "dontAsk", "bypass"] = (
        "default"
    )
    audit_log: str = Field(default_factory=_default_audit_log)
    trust: str = Field(default_factory=_default_trust)


class Settings(BaseSettings):
    """Top-level configuration, loaded once as a thread-safe singleton."""

    model_config = SettingsConfigDict(
        env_prefix="FORGEWRIGHT_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    max_steps: int = 8
    workspace: str = "./workspace"
    logs: str = "./logs"
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings instance."""
    return Settings()


__all__ = ["LLMConfig", "SandboxConfig", "SecurityConfig", "Settings", "get_settings"]
