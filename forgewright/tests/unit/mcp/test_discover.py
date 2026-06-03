"""Tests for ``forgewright.mcp.proxy.discover_proxies``.

This file is dedicated to the discovery helper (a thin wrapper that
connects, lists, and builds proxies) so its tests stay separate from
the per-tool proxy tests in ``test_proxy_real.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from forgewright.mcp.client import MCPClient, MCPServerConfig, MCPTransport
from forgewright.mcp.proxy import MCPToolProxy, discover_proxies


def _make_mock_client(server_id: str = "fs") -> MCPClient:
    """Build a mock-backed MCPClient that won't try to open a real transport."""
    client = MCPClient(
        MCPServerConfig(
            server_id=server_id,
            transport=MCPTransport.STREAMABLE_HTTP,
            url="http://example/mcp",
        )
    )
    # Stub the lifecycle so we don't need to mock stdio/streamable.
    client._session = AsyncMock()
    # discover_proxies calls client.connect() first; replace it with an
    # AsyncMock so it returns immediately.
    client.connect = AsyncMock()  # type: ignore[method-assign]
    return client


def _tool_obj(name: str, description: str = "") -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = {"type": "object", "properties": {}}
    return t


@pytest.mark.asyncio
async def test_discover_proxies_returns_one_proxy_per_tool() -> None:
    """For a server exposing two tools, ``discover_proxies`` returns two classes."""
    client = _make_mock_client("fs")
    client._session.list_tools.return_value = MagicMock(
        tools=[
            _tool_obj("read_file", "Read a file."),
            _tool_obj("write_file", "Write a file."),
        ]
    )

    proxies = await discover_proxies(client)

    assert len(proxies) == 2
    assert all(isinstance(p, type) and issubclass(p, MCPToolProxy) for p in proxies)
    # Each is namespaced with the server id.
    assert [p.name for p in proxies] == ["fs__read_file", "fs__write_file"]


@pytest.mark.asyncio
async def test_discover_proxies_connects_then_lists() -> None:
    """``connect()`` is called before ``list_tools()``."""
    client = _make_mock_client("fs")
    client._session.list_tools.return_value = MagicMock(tools=[])

    await discover_proxies(client)

    # connect() and list_tools() were both called.
    client.connect.assert_awaited_once()  # type: ignore[attr-defined]
    client._session.list_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_proxies_empty_when_server_exposes_no_tools() -> None:
    """A server with no tools returns an empty list of proxies."""
    client = _make_mock_client("fs")
    client._session.list_tools.return_value = MagicMock(tools=[])

    proxies = await discover_proxies(client)
    assert proxies == []
