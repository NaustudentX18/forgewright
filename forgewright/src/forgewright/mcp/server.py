"""``serve()`` — expose the local forgewright tools over MCP via FastMCP.

The same set of tools the agent uses locally (Bash, file editor,
browser, terminate) is published as an MCP server so external agents
(``mcp`` CLI, Claude Desktop, etc.) can call them.

Two transports:

* ``stdio`` — JSON-RPC over the process's stdin/stdout. Used when the
  client spawns forgewright as a subprocess.
* ``streamable-http`` — modern HTTP transport. Listens on a port; the
  client posts JSON-RPC over HTTP.
"""

from __future__ import annotations

from typing import Any

from forgewright.logger import logger

__all__ = ["serve"]


def serve(transport: str = "stdio", port: int = 8000) -> None:
    """Start the FastMCP server. Blocks until the client disconnects.

    ``transport`` is one of ``"stdio"`` or ``"streamable-http"``. The
    ``port`` argument is only used for the HTTP transport; it's the
    TCP port the server binds to.

    Local tools are registered through
    :meth:`forgewright.tool.base.BaseTool.as_fastmcp_tool`, which
    builds a FastMCP-compatible async adapter. FastMCP introspects
    the adapter's signature to build the JSON schema for the
    tool's arguments, so the on-the-wire schema matches what the
    tool actually accepts.
    """
    # Imports are local so importing this module doesn't require the
    # mcp extra to be installed.
    from fastmcp import FastMCP

    from forgewright.tool import BashTool, BrowserUseTool, StrReplaceEditor, TerminateTool

    mcp = FastMCP(
        "forgewright-local",
        instructions="Local forgewright tools exposed over MCP.",
    )

    # Register the four standard local tools. Each tool class is a
    # BaseTool subclass; we instantiate once and reuse the instance.
    # ``as_fastmcp_tool()`` returns an async function whose
    # ``__name__`` is set to the tool's name, so FastMCP picks up the
    # right name automatically.
    for tool_cls in (BashTool, StrReplaceEditor, BrowserUseTool, TerminateTool):
        instance: Any = tool_cls()
        mcp.add_tool(instance.as_fastmcp_tool())

    logger.info(
        "mcp.server.start transport={} port={}",
        transport,
        port,
    )
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # FastMCP accepts the port as a kwarg for the http transport.
        mcp.run(transport="streamable-http", port=port)
