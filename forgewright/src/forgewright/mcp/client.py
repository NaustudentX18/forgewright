"""``MCPClient`` — long-lived connection to a single MCP server.

Wraps the official ``mcp`` SDK to discover and call tools on a remote
MCP server. Three transports are supported:

* ``stdio`` — spawn a subprocess and speak JSON-RPC over stdin/stdout.
* ``streamable-http`` — modern HTTP transport (the new default).
* ``sse`` — legacy HTTP+SSE transport. Emits a ``DeprecationWarning``
  on use; will be removed once the upstream ``mcp`` SDK drops it.

Connections are lazy: ``__init__`` does not spawn anything. Call
``connect()`` (or ``discover_proxies()``) before ``list_tools()`` /
``call_tool()``. The same client should be reused for many calls; spawn
one per server and keep it alive for the agent's lifetime.
"""

from __future__ import annotations

import base64
import warnings
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from forgewright.logger import logger
from forgewright.mcp.proxy import _MCPToolSpec
from forgewright.schema import ToolResult

__all__ = ["MCPClient", "MCPServerConfig", "MCPTransport"]


class MCPTransport(StrEnum):
    """Supported MCP transports.

    The string values match the wire identifiers used by the official
    ``mcp`` SDK and the public registry, so configs can be loaded
    directly from a TOML file without translation.
    """

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"
    SSE = "sse"  # deprecated; warn on use


@dataclass
class MCPServerConfig:
    """Connection parameters for one MCP server.

    For ``stdio`` transports ``command`` is required and ``args`` /
    ``env`` are optional. For ``streamable-http`` and ``sse``,
    ``url`` is required. The factory does **not** validate this — it
    is enforced at ``connect()`` time so a partially-populated config
    (e.g. one loaded from a config file) can be inspected first.
    """

    server_id: str
    transport: MCPTransport
    command: str | None = None  # stdio
    args: list[str] = field(default_factory=list)  # stdio
    env: dict[str, str] = field(default_factory=dict)  # stdio
    url: str | None = None  # streamable-http / sse


class MCPClient:
    """A long-lived connection to one MCP server. Lazy connect.

    Typical usage::

        cfg = MCPServerConfig(server_id="fs", transport=MCPTransport.STDIO,
                              command="uvx", args=["mcp-server-fs"])
        client = MCPClient(cfg)
        await client.connect()
        specs = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "x"})

    The client is reusable: call ``list_tools()`` / ``call_tool()`` as
    often as you like. Call ``close()`` (idempotent) to release the
    transport and the session.
    """

    # Stashed on the class so tests / inspection code can introspect
    # which transport a given client was built for without re-parsing.
    config: MCPServerConfig

    def __init__(self, config: MCPServerConfig) -> None:
        """Store the config; do not connect yet."""
        self.config = config
        # Populated by connect(); left None until then.
        self._session: Any = None
        self._transport_cm: Any = None
        self._closed: bool = False

    # ---------- connection lifecycle ----------

    async def connect(self) -> None:
        """Open the transport and initialize the MCP session.

        Safe to call once. A second call after ``close()`` will reopen
        the connection. The SDK modules are imported lazily so this
        module can be imported even on systems where ``mcp`` is not
        installed (the ``[mcp]`` extra is opt-in).
        """
        if self._session is not None and not self._closed:
            return

        transport = self.config.transport
        if transport == MCPTransport.STDIO:
            await self._connect_stdio()
        elif transport == MCPTransport.STREAMABLE_HTTP:
            await self._connect_streamable_http()
        elif transport == MCPTransport.SSE:
            await self._connect_sse()
        else:
            raise ValueError(f"Unknown MCP transport: {transport!r}")

        # Initialize the session. The MCP spec requires this before
        # any other RPC; list_tools / call_tool both assume it.
        await self._session.initialize()
        self._closed = False
        logger.info(
            "mcp.client.connected server_id={} transport={}",
            self.config.server_id,
            transport.value,
        )

    async def _connect_stdio(self) -> None:
        """Spawn a subprocess and wrap it in a ClientSession."""
        if not self.config.command:
            raise ValueError(
                f"MCPServerConfig(server_id={self.config.server_id!r}): "
                "stdio transport requires 'command'."
            )
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from mcp import ClientSession

        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=dict(self.config.env) or None,
        )
        # stdio_client is an asynccontextmanager that yields (read, write).
        self._transport_cm = stdio_client(params)
        read, write = await self._transport_cm.__aenter__()
        self._session = ClientSession(read, write)

    async def _connect_streamable_http(self) -> None:
        """Connect over HTTP using the modern Streamable HTTP transport."""
        if not self.config.url:
            raise ValueError(
                f"MCPServerConfig(server_id={self.config.server_id!r}): "
                "streamable-http transport requires 'url'."
            )
        from mcp.client.streamable_http import streamablehttp_client

        from mcp import ClientSession

        self._transport_cm = streamablehttp_client(self.config.url)
        # streamablehttp_client yields (read, write, get_session_id_callback).
        read, write, _get_sid = await self._transport_cm.__aenter__()
        self._session = ClientSession(read, write)

    async def _connect_sse(self) -> None:
        """Connect over the legacy SSE transport. Warns on use."""
        warnings.warn(
            "MCPTransport.SSE is deprecated; use MCPTransport.STREAMABLE_HTTP instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.config.url:
            raise ValueError(
                f"MCPServerConfig(server_id={self.config.server_id!r}): "
                "sse transport requires 'url'."
            )
        from mcp.client.sse import sse_client

        from mcp import ClientSession

        self._transport_cm = sse_client(self.config.url)
        read, write = await self._transport_cm.__aenter__()
        self._session = ClientSession(read, write)

    async def close(self) -> None:
        """Tear down the session and the transport. Idempotent."""
        if self._closed:
            return
        self._closed = True
        # Close the session first (drains in-flight requests), then the
        # transport context manager.
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "mcp.client.session_close_failed server_id={} err={}",
                    self.config.server_id,
                    exc,
                )
            self._session = None
        if self._transport_cm is not None:
            try:
                await self._transport_cm.__aexit__(None, None, None)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "mcp.client.transport_close_failed server_id={} err={}",
                    self.config.server_id,
                    exc,
                )
            self._transport_cm = None
        logger.info("mcp.client.closed server_id={}", self.config.server_id)

    # ---------- RPCs ----------

    async def list_tools(self) -> list[_MCPToolSpec]:
        """Discover the server's tools and render each as a ``_MCPToolSpec``.

        ``Tool.inputSchema`` is the JSON Schema for the tool's arguments.
        The MCP SDK types this as ``dict[str, Any]``; we pass it through
        unchanged so the proxy can hand it to ``BaseTool``'s validator.
        """
        if self._session is None:
            raise RuntimeError(
                f"MCPClient(server_id={self.config.server_id!r}): call connect() first."
            )
        result = await self._session.list_tools()
        return [
            _MCPToolSpec(
                name=tool.name,
                description=tool.description or "",
                args_schema=tool.inputSchema or {"type": "object", "properties": {}},
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a remote tool and convert the result to ``ToolResult``.

        Conversion rules (see ARCHITECTURE.md §6.4):
        * Concatenate every ``text`` content block with newlines into
          ``ToolResult.output``.
        * The first ``image`` content block is base64-encoded into
          ``ToolResult.base64_image`` (subsequent images are ignored —
          ``ToolResult`` holds one).
        * ``CallToolResult.isError`` -> ``ToolResult.is_error``.
        """
        if self._session is None:
            raise RuntimeError(
                f"MCPClient(server_id={self.config.server_id!r}): call connect() first."
            )
        result = await self._session.call_tool(name, arguments=arguments)

        # Collect text content blocks. Anything that doesn't have a
        # ``type == "text"`` attribute (e.g. resource links) is skipped.
        text_chunks: list[str] = []
        base64_image: str | None = None
        for block in result.content:
            # The MCP SDK uses Pydantic discriminated unions; checking
            # the literal ``type`` field is the most robust way to
            # discriminate across SDK versions.
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_chunks.append(getattr(block, "text", "") or "")
            elif block_type == "image" and base64_image is None:
                data = getattr(block, "data", None)
                mime = getattr(block, "mimeType", "") or ""
                if data:
                    # The MCP spec already base64-encodes the image data;
                    # re-encoding a base64 string is a no-op idempotent
                    # step and gives us a defensive guarantee for older
                    # servers that sent raw bytes.
                    try:
                        base64.b64decode(data, validate=True)
                        base64_image = f"data:{mime};base64,{data}" if mime else data
                    except Exception:
                        base64_image = base64.b64encode(data.encode("utf-8")).decode("ascii")

        return ToolResult(
            output="\n".join(text_chunks),
            is_error=bool(getattr(result, "isError", False)),
            base64_image=base64_image,
        )
