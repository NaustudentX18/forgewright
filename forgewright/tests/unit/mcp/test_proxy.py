"""Tests for the Phase 7 ``MCPToolProxy`` stub.

The full proxy talks to a real MCP client session; that lands in
Phase 8. These tests pin down the Phase-7 contract: ``make_proxy``
returns a ``BaseTool`` subclass bound to the spec, the namespacing is
correct, and invoking the stub surfaces a clean ``ToolResult(is_error=...)``
that names Phase 8.
"""

from __future__ import annotations

from typing import Any

import pytest
from forgewright.mcp import MCPToolProxy, _MCPToolSpec, make_proxy
from forgewright.mcp.proxy import ToolRegistry
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool


def _make_spec(
    name: str = "read_file",
    description: str = "Read a file from the remote filesystem.",
    args_schema: dict[str, Any] | None = None,
) -> _MCPToolSpec:
    """Build a representative spec for tests."""
    if args_schema is None:
        args_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    return _MCPToolSpec(name=name, description=description, args_schema=args_schema)


# ---------- structural tests ----------


def test_make_proxy_class_is_base_tool_subclass() -> None:
    """The class returned by ``make_proxy`` is a ``BaseTool`` + ``MCPToolProxy`` subclass."""
    ProxyCls = make_proxy("fs", _make_spec())
    assert isinstance(ProxyCls, type)
    assert issubclass(ProxyCls, BaseTool)
    assert issubclass(ProxyCls, MCPToolProxy)


def test_make_proxy_class_name_is_namespaced() -> None:
    """Class ``name`` is ``<server_id>__<tool_name>`` (the registry's namespace format)."""
    spec = _make_spec(name="read_file")
    ProxyCls = make_proxy("fs", spec)
    assert ProxyCls.name == "fs__read_file"
    # And matches the registry helper exactly — no hand-rolled separator.
    assert ProxyCls.name == ToolRegistry.namespaced_name("fs", "read_file")


def test_make_proxy_class_description_matches_spec() -> None:
    """Class ``description`` is the spec's description verbatim."""
    desc = "List issues in a GitHub repo."
    ProxyCls = make_proxy("github", _make_spec(name="list_issues", description=desc))
    assert ProxyCls.description == desc


def test_make_proxy_class_args_schema_matches_spec() -> None:
    """Class ``args_schema`` is the spec's schema dict (same object, not a copy)."""
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    spec = _make_spec(name="search", args_schema=schema)
    ProxyCls = make_proxy("web", spec)
    assert ProxyCls.args_schema is schema


def test_make_proxy_two_specs_produce_distinct_classes() -> None:
    """Each call to ``make_proxy`` builds a fresh subclass — no global cache bleed."""
    A = make_proxy("fs", _make_spec(name="read"))
    B = make_proxy("fs", _make_spec(name="write"))
    assert A is not B
    assert A.name == "fs__read"
    assert B.name == "fs__write"


def test_spec_is_frozen_dataclass() -> None:
    """``_MCPToolSpec`` is immutable so the proxy's view of it can't drift mid-call."""
    spec = _make_spec()
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "mutated"  # type: ignore[misc]


# ---------- runtime tests: how the proxy behaves as a BaseTool ----------


def test_proxy_instance_has_namespaced_name() -> None:
    """After instantiation, the tool is keyed by the namespaced name in collections."""
    ProxyCls = make_proxy("fs", _make_spec())
    tool = ProxyCls()
    assert tool.name == "fs__read_file"
    # The instance also stashes the server id and spec for Phase 8.
    assert tool._server_id == "fs"
    assert tool._spec.name == "read_file"
    assert tool._namespaced_name == "fs__read_file"


def test_proxy_to_openai_tool_uses_namespaced_name() -> None:
    """The OpenAI wire spec uses the namespaced name + spec's schema."""
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    ProxyCls = make_proxy(
        "fs",
        _make_spec(
            name="read_file",
            description="Read a file",
            args_schema=schema,
        ),
    )
    spec = ProxyCls().to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "fs__read_file"
    assert spec["function"]["description"] == "Read a file"
    assert spec["function"]["parameters"] is schema


def test_proxy_to_anthropic_tool_uses_namespaced_name() -> None:
    """The Anthropic wire spec uses the namespaced name + spec's schema."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }
    ProxyCls = make_proxy(
        "calc",
        _make_spec(
            name="add",
            description="Add two numbers.",
            args_schema=schema,
        ),
    )
    spec = ProxyCls().to_anthropic_tool()
    assert spec["name"] == "calc__add"
    assert spec["description"] == "Add two numbers."
    assert spec["input_schema"] is schema


@pytest.mark.asyncio
async def test_proxy_call_returns_error_result_with_phase_8_message() -> None:
    """Calling the stub surfaces ``ToolResult(is_error=True)`` whose message names Phase 8.

    The stub's ``_run`` raises ``NotImplementedError``; ``BaseTool.__call__``
    catches it and wraps it. The error must name Phase 8 so the agent can
    tell the difference between "real MCP server is down" and "this code
    path isn't implemented yet".
    """
    ProxyCls = make_proxy("fs", _make_spec())
    tool = ProxyCls()
    result = await tool(path="foo.txt")  # any kwargs are fine; the validator passes them

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.error is not None
    assert "Phase 8" in result.error
    # The namespaced name is included so the message is self-locating.
    assert "fs__read_file" in result.error


@pytest.mark.asyncio
async def test_proxy_call_validates_args_against_schema() -> None:
    """BaseTool's arg validation still runs; missing required args are caught first."""
    ProxyCls = make_proxy("fs", _make_spec())  # requires 'path'
    tool = ProxyCls()
    result = await tool()  # missing 'path'

    assert result.is_error is True
    assert result.error is not None
    assert "Invalid args" in result.error
    assert "path" in result.error
