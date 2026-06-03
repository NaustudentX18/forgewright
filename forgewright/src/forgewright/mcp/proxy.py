"""``MCPToolProxy`` — wraps a remote MCP tool so it looks like a local ``BaseTool``.

Phase 7 shipped a stub: ``make_proxy(server_id, spec)`` returns a
``BaseTool`` subclass whose ``name``/``description``/``args_schema`` are
the spec's values. Calling it raised ``NotImplementedError`` from
``_run``; ``BaseTool.__call__`` caught that and wrapped it in a
``ToolResult(is_error=True)``.

Phase 8 wires the real ``MCPClient`` into the proxy. The factory now
takes an optional ``client`` keyword; when supplied, the proxy
forwards every call to ``client.call_tool(spec.name, kwargs)``. The
stub error path is preserved for callers that haven't connected yet
(e.g. tests, dry-runs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool
from forgewright.tool.registry import ToolRegistry

__all__ = ["MCPToolProxy", "_MCPToolSpec", "discover_proxies", "make_proxy"]


@dataclass(frozen=True)
class _MCPToolSpec:
    """Lightweight spec for a remote MCP tool (subset of the full MCP ``Tool`` type).

    The full MCP spec carries server metadata, an ``outputSchema``, JSON
    Schema extras, and other fields. The proxy only needs the three values
    that map onto ``BaseTool``'s contract.
    """

    name: str
    description: str
    args_schema: dict[str, Any]


class MCPToolProxy(BaseTool):
    """Wraps a remote MCP tool so it looks identical to a local ``BaseTool``.

    Namespacing (``<server_id>__<tool_name>``) is enforced at the
    registry layer (``ToolRegistry.namespaced_name``); the proxy itself
    just exposes the already-namespaced name via its class attributes.

    The proxy holds a reference to an :class:`MCPClient`; ``_run``
    forwards every call to ``client.call_tool(spec.name, kwargs)``. If
    no client is attached (e.g. the proxy was built standalone for
    tests), ``_run`` raises ``NotImplementedError`` and ``BaseTool``
    wraps it in a clean error ``ToolResult``.
    """

    name: ClassVar[str] = "mcp__unset"
    description: ClassVar[str] = "MCP proxy stub. Pass client= to make_proxy for live calls."
    args_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    requires: ClassVar[list[str]] = ["mcp"]

    async def _run(self, **kwargs: Any) -> ToolResult:
        """Forward to the MCP client, or raise when no client is attached.

        The instance attribute ``_namespaced_name`` is set by
        :func:`make_proxy` after the class is built, so the error
        message names the actual tool (not the placeholder).
        """
        namespaced = getattr(self, "_namespaced_name", self.name)
        client = getattr(self, "_client", None)
        if client is None:
            raise NotImplementedError(
                f"MCPToolProxy({namespaced}): no client attached (Phase 8). "
                "Pass client= to make_proxy() or call discover_proxies()."
            )
        # _spec is set by the subclass's __init__ (see make_proxy).
        spec: _MCPToolSpec = self._spec  # type: ignore[attr-defined]
        result: ToolResult = await client.call_tool(spec.name, kwargs)
        return result


def make_proxy(
    server_id: str,
    spec: _MCPToolSpec,
    client: Any | None = None,
) -> type[MCPToolProxy]:
    """Factory: return a fresh ``BaseTool`` subclass with the spec's fields bound.

    ``BaseTool.name`` is a ``ClassVar`` so the cleanest way to set it
    per tool is to build a one-off subclass. The caller instantiates
    the returned class to get a usable tool::

        ProxyCls = make_proxy("fs", spec, client=my_client)
        tool = ProxyCls()
        await tool(path="foo.txt")

    ``client`` is optional both at the factory level and at the
    constructor level. The factory value is the default; passing
    ``client=`` to the constructor overrides it. If neither is set,
    the proxy is in stub mode and its ``_run`` raises
    ``NotImplementedError`` (Phase-7 behavior preserved).
    """
    namespaced = ToolRegistry.namespaced_name(server_id, spec.name)
    # Capture the factory's client in a closure default so it survives
    # the subclass's __init__ signature.
    default_client = client

    class _Proxy(MCPToolProxy):
        # Shadows the parent ClassVars with the spec's values.
        name: ClassVar[str] = namespaced
        description: ClassVar[str] = spec.description
        args_schema: ClassVar[dict[str, Any]] = spec.args_schema

        def __init__(self, client: Any | None = None) -> None:
            super().__init__()
            # Keep references for the runtime path and for diagnostics
            # (the error message in _run reads _namespaced_name).
            self._server_id = server_id
            self._spec = spec
            self._namespaced_name = namespaced
            # Live client; falls back to the factory's default.
            # None on both means the proxy is in stub mode.
            self._client = client if client is not None else default_client

    # Re-bind the qualified name so error messages read more usefully.
    _Proxy.__qualname__ = f"MCPToolProxy[{namespaced}]"
    _Proxy.__name__ = f"MCPToolProxy_{namespaced}"
    return _Proxy


async def discover_proxies(client: Any) -> list[type[MCPToolProxy]]:
    """Connect to ``client``, list its tools, and return one proxy class per tool.

    Convenience for the agent bootstrap path::

        cfg = MCPServerConfig(server_id="fs", transport=MCPTransport.STDIO, ...)
        async with MCPClient(cfg) as c:
            proxies = await discover_proxies(c)
        agent.add_mcp_tools(tuple(proxies))

    Each returned class is a fresh ``MCPToolProxy`` subclass bound to
    its spec and to the (already-connected) client. The connection is
    left open; the caller owns ``close()`` (or uses ``async with`` on
    the client to scope it).
    """
    # Lazy import to avoid a hard dep on the client module — and to
    # keep the proxy module importable on systems without the mcp extra.
    from forgewright.mcp.client import MCPClient

    if not isinstance(client, MCPClient) and (
        not hasattr(client, "connect") or not hasattr(client, "list_tools")
    ):
        raise TypeError(f"discover_proxies: expected MCPClient, got {type(client).__name__}")
    await client.connect()
    specs = await client.list_tools()
    proxies = [make_proxy(client.config.server_id, spec, client) for spec in specs]
    logger.info(
        "mcp.discover_proxies server_id={} count={}",
        client.config.server_id,
        len(proxies),
    )
    return proxies
