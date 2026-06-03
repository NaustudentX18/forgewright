"""Tests for the Pydantic schema models."""

from __future__ import annotations

import pytest
from forgewright.schema import (
    AssistantTurn,
    ChatMessage,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from pydantic import ValidationError


def test_chat_message_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="hi", bogus="field")  # type: ignore[call-arg]


def test_chat_message_valid_roles() -> None:
    for role in ("system", "user", "assistant", "tool"):
        m = ChatMessage(role=role, content="x")
        assert m.role == role


def test_chat_message_invalid_role_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="wizard", content="x")  # type: ignore[arg-type]


def test_tool_call_name_length_bounds() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="1", name="", args={})
    with pytest.raises(ValidationError):
        ToolCall(id="1", name="x" * 100, args={})


def test_tool_result_default() -> None:
    r = ToolResult()
    assert r.output == ""
    assert r.error is None
    assert r.is_error is False
    assert r.base64_image is None


def test_assistant_turn_defaults() -> None:
    t = AssistantTurn()
    assert t.content == ""
    assert t.tool_calls == []


def test_tool_spec_minimal() -> None:
    s = ToolSpec(name="x", description="y", args_schema={})
    assert s.name == "x"
    assert s.args_schema == {}
