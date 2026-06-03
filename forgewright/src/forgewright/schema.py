"""Pydantic models for messages, tool calls, and tool results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """A single message in the agent's conversation history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None  # for tool messages


class ToolCall(BaseModel):
    """A structured tool invocation requested by the model."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The return value of a tool invocation."""

    model_config = ConfigDict(extra="forbid")

    output: str = ""
    error: str | None = None
    system: str | None = None
    base64_image: str | None = None
    is_error: bool = False


class AssistantTurn(BaseModel):
    """A full assistant response: content + any tool calls."""

    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """A tool's public schema, sent to the model as a function-calling spec."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str
    args_schema: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Per-call and cumulative token accounting."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


__all__ = [
    "AssistantTurn",
    "ChatMessage",
    "TokenUsage",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
]
