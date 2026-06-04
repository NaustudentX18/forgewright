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
    context_tokens_default: int = 128_000
    drop_params: bool = True


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


def _default_pricing_table() -> str:
    return str(Path.home() / ".config" / "forgewright" / "pricing.json")


class CostConfig(BaseModel):
    """Token cost tracking + per-session caps (H2.3)."""

    pricing_table: str = Field(default_factory=_default_pricing_table)
    # Per-session USD cap. ``float("inf")`` (the default) disables the cap;
    # a value of 0 is treated identically — there is no "free call" budget.
    max_usd_per_session: float = float("inf")
    # Per-session iteration cap. ``0`` disables the cap; a positive value
    # is enforced before every LLM call.
    max_iterations_per_session: int = 0


class ToolsConfig(BaseModel):
    """Cross-tool limits."""

    max_output_chars: int = 50_000


class AgentConfig(BaseModel):
    """Agent-level defaults (memory, etc)."""

    memory_max_messages: int = 200


class FlowConfig(BaseModel):
    """PlanningFlow step + timeout budgets."""

    max_total_steps: int = 50
    per_agent_max_steps: int = 25
    timeout_s: int = 600


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
    cost: CostConfig = Field(default_factory=CostConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    flow: FlowConfig = Field(default_factory=FlowConfig)
    max_steps: int = 8
    workspace: str = "./workspace"
    logs: str = "./logs"
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings instance."""
    return Settings()


__all__ = [
    "AgentConfig",
    "CostConfig",
    "FlowConfig",
    "LLMConfig",
    "SandboxConfig",
    "SecurityConfig",
    "Settings",
    "ToolsConfig",
    "get_settings",
]
