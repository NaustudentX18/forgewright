"""Minimal client for the public MCP server registry.

The official registry at ``https://registry.modelcontextprotocol.io``
publishes a JSON document of well-known MCP servers. This module is a
thin wrapper around ``httpx``: it fetches the document and returns the
``servers`` array. On any network or parse error it logs a warning and
returns an empty list — the agent and CLI should keep working with the
locally-configured servers even if the registry is unreachable.
"""

from __future__ import annotations

from typing import Any

from forgewright.logger import logger

__all__ = ["REGISTRY_URL", "list_known_servers"]


REGISTRY_URL: str = "https://registry.modelcontextprotocol.io/v0/servers"


async def list_known_servers() -> list[dict[str, Any]]:
    """Fetch the public MCP server registry. Returns ``[]`` on any error.

    The registry's response shape is ``{"servers": [...], "metadata": {...}}``.
    We return just the ``servers`` list. Each entry is an opaque dict;
    callers that need to display them should look up the schema in the
    MCP registry docs. Failures are silent (logged at WARNING) so the
    agent doesn't crash when the registry is offline.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("mcp.registry.httpx_missing")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(REGISTRY_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("mcp.registry.fetch_failed err={}", exc)
        return []

    if not isinstance(data, dict):
        logger.warning("mcp.registry.unexpected_shape type={}", type(data).__name__)
        return []

    servers = data.get("servers", [])
    if not isinstance(servers, list):
        logger.warning("mcp.registry.servers_not_list type={}", type(servers).__name__)
        return []
    return servers
