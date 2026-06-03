"""Tests for the Phase-8 ``MCPToolProxy`` (live mode with a real client).

Phase 7's tests in ``test_proxy.py`` cover the structural / stub-mode
contract. This file covers the *live* path: the proxy forwards calls
to a real ``MCPClient`` and converts the result back to ``ToolResult``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from forgewright.mcp.client import MCPClient, MCPServerConfig, MCPTransport
from forgewright.mcp.proxy import (
    MCPToolProxy,
    _MCPToolSpec,
    discover_proxies,
    make_proxy,
)
from forgewright.schema import ToolResult


def _spec(
    name: str = "read_file",
    description: str = "Read a file.",
    args_schema: dict[str, Any] | None = None,
) -> _MCPToolSpec:
    if args_schema is None:
        args_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    return _MCPToolSpec(name=name, description=description, args_schema=args_schema)


def _mock_client(server_id: str = "fs") -> MCPClient:
    """Build an MCPClient with a mock session attached (no real connection)."""
    client = MCPClient(
        MCPServerConfig(
            server_id=server_id,
            transport=MCPTransport.STREAMABLE_HTTP,
            url="http://example/mcp",
        )
    )
    client._session = AsyncMock()
    return client


# ---------- factory: live mode ----------


def test_make_proxy_with_client_yields_namespaced_class() -> None:
    """``make_proxy(server_id, spec, client=...)`` returns a namespaced class."""
    client = _mock_client("fs")
    ProxyCls = make_proxy("fs", _spec(name="read_file"), client=client)

    assert issubclass(ProxyCls, MCPToolProxy)
    # Name follows the registry's namespace format.
    assert ProxyCls.name == "fs__read_file"
    assert ProxyCls.description == "Read a file."


def test_make_proxy_instance_stores_client() -> None:
    """Instantiating the class preserves the client reference for ``_run``."""
    client = _mock_client("fs")
    ProxyCls = make_proxy("fs", _spec(), client=client)
    instance = ProxyCls()
    assert instance._client is client
    # Diagnostics attributes are still populated.
    assert instance._server_id == "fs"
    assert instance._spec.name == "read_file"
    assert instance._namespaced_name == "fs__read_file"


# ---------- forward to client ----------


@pytest.mark.asyncio
async def test_proxy_call_invokes_client_call_tool() -> None:
    """Calling the proxy routes to ``client.call_tool(spec.name, kwargs)``."""
    client = _mock_client("fs")
    client._session.call_tool.return_value = MagicMock(content=[_text_block("ok")], isError=False)

    ProxyCls = make_proxy("fs", _spec(name="read_file"), client=client)
    tool = ProxyCls()
    result = await tool(path="foo.txt")

    client._session.call_tool.assert_awaited_once_with("read_file", arguments={"path": "foo.txt"})
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_proxy_call_returns_tool_result_with_output() -> None:
    """A successful ``call_tool`` translates the text content into ``output``."""
    client = _mock_client("fs")
    client._session.call_tool.return_value = MagicMock(
        content=[_text_block("first\n"), _text_block("second")], isError=False
    )

    ProxyCls = make_proxy("fs", _spec(name="read_file"), client=client)
    tool = ProxyCls()
    result = await tool(path="x")

    assert result.output == "first\n\nsecond"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_proxy_call_wraps_call_tool_exception() -> None:
    """If the client raises, ``BaseTool.__call__`` wraps it in an error result."""
    client = _mock_client("fs")
    client._session.call_tool.side_effect = ConnectionError("server down")

    ProxyCls = make_proxy("fs", _spec(name="read_file"), client=client)
    tool = ProxyCls()
    result = await tool(path="x")

    assert result.is_error is True
    assert result.error is not None
    assert "ConnectionError" in result.error
    assert "server down" in result.error


@pytest.mark.asyncio
async def test_proxy_call_without_client_raises_not_implemented() -> None:
    """A stub-mode proxy (client=None) still raises NotImplementedError."""
    ProxyCls = make_proxy("fs", _spec(), client=None)
    tool = ProxyCls()
    result = await tool(path="x")
    assert result.is_error is True
    assert "NotImplementedError" in (result.error or "")


# ---------- discover_proxies ----------


@pytest.mark.asyncio
async def test_discover_proxies_returns_one_class_per_tool() -> None:
    """``discover_proxies`` connects, lists tools, returns a proxy class each."""
    client = _mock_client("fs")
    # Stub the actual connect() so it doesn't try to open a transport.
    client.connect = AsyncMock()  # type: ignore[method-assign]
    client._session.list_tools.return_value = MagicMock(
        tools=[
            _tool_obj("read_file", "Read a file."),
            _tool_obj("write_file", "Write a file."),
        ]
    )

    proxies = await discover_proxies(client)

    assert len(proxies) == 2
    assert [p.name for p in proxies] == ["fs__read_file", "fs__write_file"]
    # Each is a fresh BaseTool subclass bound to the same client.
    for p in proxies:
        assert issubclass(p, MCPToolProxy)
        instance = p()
        assert instance._client is client


# ---------- helpers ----------


def _text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_obj(name: str, description: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = {"type": "object", "properties": {}}
    return t
