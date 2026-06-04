"""Tests for ``forgewright.mcp.registry.list_known_servers``.

The public registry at registry.modelcontextprotocol.io is fetched
with ``httpx``. We mock ``httpx`` so no network traffic happens.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from forgewright.mcp.registry import REGISTRY_URL, list_known_servers


@pytest.mark.asyncio
async def test_list_known_servers_returns_empty_on_network_error() -> None:
    """A network failure surfaces as ``[]`` (with a warning logged)."""
    with patch("httpx.AsyncClient") as Client:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(side_effect=ConnectionError("boom"))
        ctx.__aexit__ = AsyncMock(return_value=None)
        Client.return_value = ctx

        result = await list_known_servers()

    assert result == []


@pytest.mark.asyncio
async def test_list_known_servers_returns_servers_on_success() -> None:
    """A 200 with the expected JSON shape returns the ``servers`` list."""
    fake_servers = [
        {"name": "fs", "description": "Filesystem server."},
        {"name": "github", "description": "GitHub server."},
    ]
    with patch("httpx.AsyncClient") as Client:
        ctx = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"servers": fake_servers, "metadata": {}}
        get = AsyncMock(return_value=response)
        ctx.get = get
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        Client.return_value = ctx

        result = await list_known_servers()

    assert result == fake_servers
    # The right URL was hit.
    get.assert_awaited_once_with(REGISTRY_URL)


@pytest.mark.asyncio
async def test_list_known_servers_handles_http_error() -> None:
    """An HTTP 5xx response (raise_for_status throws) returns ``[]``."""
    with patch("httpx.AsyncClient") as Client:
        ctx = MagicMock()
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("500 Server Error")
        get = AsyncMock(return_value=response)
        ctx.get = get
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        Client.return_value = ctx

        result = await list_known_servers()

    assert result == []


@pytest.mark.asyncio
async def test_list_known_servers_normalizes_nested_entries() -> None:
    """Registry v0 wraps each server in a ``server`` + ``_meta`` envelope."""
    nested = {
        "name": "ai.adeu/adeu",
        "packages": [{"registryType": "npm", "identifier": "@adeu/mcp-server"}],
    }
    with patch("httpx.AsyncClient") as Client:
        ctx = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "servers": [{"server": nested, "_meta": {}}],
            "metadata": {},
        }
        ctx.get = AsyncMock(return_value=response)
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        Client.return_value = ctx

        result = await list_known_servers()

    assert len(result) == 1
    assert result[0]["name"] == "ai.adeu/adeu"


@pytest.mark.asyncio
async def test_list_known_servers_handles_unexpected_shape() -> None:
    """A non-dict response body returns ``[]`` (defensive)."""
    with patch("httpx.AsyncClient") as Client:
        ctx = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = ["not", "a", "dict"]
        ctx.get = AsyncMock(return_value=response)
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        Client.return_value = ctx

        result = await list_known_servers()

    assert result == []
