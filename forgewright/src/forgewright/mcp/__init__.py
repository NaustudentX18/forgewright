"""MCP (Model Context Protocol) integration package.

Phase 7 shipped the ``MCPToolProxy`` stub. Phase 8 adds the real client
(``MCPClient``) supporting stdio, streamable-http, and legacy SSE, the
``FastMCP`` server (``serve()``) that exposes the local tools, the
proxy factory's live mode (``discover_proxies``), and a thin registry
client (``list_known_servers``).
"""

from __future__ import annotations

from forgewright.mcp.client import MCPClient, MCPServerConfig, MCPTransport
from forgewright.mcp.proxy import MCPToolProxy, _MCPToolSpec, discover_proxies, make_proxy
from forgewright.mcp.registry import list_known_servers
from forgewright.mcp.server import serve

__all__ = [
    "MCPClient",
    "MCPServerConfig",
    "MCPToolProxy",
    "MCPTransport",
    "_MCPToolSpec",
    "discover_proxies",
    "list_known_servers",
    "make_proxy",
    "serve",
]
