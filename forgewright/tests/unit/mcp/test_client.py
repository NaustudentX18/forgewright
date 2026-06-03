"""Tests for ``MCPClient`` — the real stdio/streamable-http/SSE client.

The mcp SDK is mocked so these tests run without any network or
subprocess. The contract we pin down:

* ``MCPClient.__init__`` is lazy (no subprocess is spawned).
* ``list_tools()`` translates ``mcp.types.Tool`` -> ``_MCPToolSpec``.
* ``call_tool()`` translates ``mcp.types.CallToolResult`` -> ``ToolResult``.
* ``close()`` is idempotent and survives a second call.
"""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from forgewright.mcp.client import MCPClient, MCPServerConfig, MCPTransport
from forgewright.mcp.proxy import _MCPToolSpec
from forgewright.schema import ToolResult

# --- helpers -------------------------------------------------------------


def _text_block(text: str) -> MagicMock:
    """Build a mock content block of type ``text``."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _image_block(data_b64: str, mime: str = "image/png") -> MagicMock:
    """Build a mock content block of type ``image``."""
    block = MagicMock()
    block.type = "image"
    block.data = data_b64
    block.mimeType = mime
    return block


def _list_tools_result(*tools: dict[str, Any]) -> MagicMock:
    """Build a mock ``mcp.types.ListToolsResult``."""
    result = MagicMock()
    tool_mocks = []
    for t in tools:
        tm = MagicMock()
        tm.name = t["name"]
        tm.description = t.get("description")
        tm.inputSchema = t.get("inputSchema", {"type": "object", "properties": {}})
        tool_mocks.append(tm)
    result.tools = tool_mocks
    return result


def _call_tool_result(
    *content: MagicMock,
    is_error: bool = False,
) -> MagicMock:
    """Build a mock ``mcp.types.CallToolResult``."""
    result = MagicMock()
    result.content = list(content)
    result.isError = is_error
    return result


def _make_client(
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
    server_id: str = "fs",
    **kwargs: Any,
) -> MCPClient:
    cfg = MCPServerConfig(server_id=server_id, transport=transport, **kwargs)
    return MCPClient(cfg)


# --- config validation ---------------------------------------------------


def test_server_config_stdio_requires_command() -> None:
    """A stdio config without ``command`` fails at connect() time."""
    import asyncio

    client = _make_client(MCPTransport.STDIO, command=None)
    assert client.config.command is None
    # The error message should name the missing field. Call the
    # private connect helper directly so we don't need a mock session.
    with pytest.raises(ValueError, match="command"):
        asyncio.run(client._connect_stdio())


def test_server_config_streamable_http_requires_url() -> None:
    """A streamable-http config without ``url`` fails at connect() time."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url=None)
    import asyncio

    with pytest.raises(ValueError, match="url"):
        asyncio.run(client._connect_streamable_http())


def test_server_config_sse_requires_url() -> None:
    """A legacy sse config without ``url`` fails at connect() time."""
    client = _make_client(MCPTransport.SSE, url=None)
    import asyncio

    with pytest.raises(ValueError, match="url"):
        asyncio.run(client._connect_sse())


# --- lazy connect --------------------------------------------------------


def test_client_init_does_not_connect() -> None:
    """``__init__`` must not spawn a subprocess or open a socket."""
    with (
        patch("mcp.client.stdio.stdio_client") as stdio,
        patch("mcp.client.streamable_http.streamablehttp_client") as http,
        patch("mcp.client.sse.sse_client") as sse,
    ):
        # stdio variant
        MCPClient(
            MCPServerConfig(
                server_id="fs",
                transport=MCPTransport.STDIO,
                command="echo",
            )
        )
        # http variant
        MCPClient(
            MCPServerConfig(
                server_id="fs",
                transport=MCPTransport.STREAMABLE_HTTP,
                url="http://x",
            )
        )
        # sse variant
        MCPClient(
            MCPServerConfig(
                server_id="fs",
                transport=MCPTransport.SSE,
                url="http://x",
            )
        )
        stdio.assert_not_called()
        http.assert_not_called()
        sse.assert_not_called()


# --- list_tools ----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_spec_list() -> None:
    """A mocked session with two tools yields two ``_MCPToolSpec`` entries."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    client._session = AsyncMock()
    client._session.list_tools.return_value = _list_tools_result(
        {
            "name": "read_file",
            "description": "Read a file from the remote filesystem.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write a file.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
        },
    )

    specs = await client.list_tools()

    assert len(specs) == 2
    assert all(isinstance(s, _MCPToolSpec) for s in specs)
    assert specs[0].name == "read_file"
    assert specs[0].description == "Read a file from the remote filesystem."
    assert specs[0].args_schema == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    assert specs[1].name == "write_file"


@pytest.mark.asyncio
async def test_list_tools_falls_back_to_empty_schema_when_none() -> None:
    """A tool with no inputSchema still gets a valid (empty) schema."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    client._session = AsyncMock()
    client._session.list_tools.return_value = _list_tools_result(
        {"name": "ping", "description": "Ping.", "inputSchema": None},
    )

    specs = await client.list_tools()
    assert len(specs) == 1
    assert specs[0].args_schema == {"type": "object", "properties": {}}


# --- call_tool -----------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_concatenates_text_blocks() -> None:
    """Text content blocks are joined with newlines into ``ToolResult.output``."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    client._session = AsyncMock()
    client._session.call_tool.return_value = _call_tool_result(
        _text_block("line 1"),
        _text_block("line 2"),
    )

    result = await client.call_tool("read_file", {"path": "x"})

    assert isinstance(result, ToolResult)
    assert result.output == "line 1\nline 2"
    assert result.is_error is False
    # The session was called with the right name + arguments.
    client._session.call_tool.assert_awaited_once_with("read_file", arguments={"path": "x"})


@pytest.mark.asyncio
async def test_call_tool_marks_error_when_iserror_true() -> None:
    """``result.isError == True`` becomes ``ToolResult.is_error == True``."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    client._session = AsyncMock()
    client._session.call_tool.return_value = _call_tool_result(
        _text_block("boom"),
        is_error=True,
    )

    result = await client.call_tool("read_file", {"path": "/nope"})

    assert result.is_error is True
    # We still capture the text so the agent can see what went wrong.
    assert result.output == "boom"


@pytest.mark.asyncio
async def test_call_tool_captures_image_block_as_base64() -> None:
    """An ``image`` content block is exposed via ``ToolResult.base64_image``."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    client._session = AsyncMock()
    client._session.call_tool.return_value = _call_tool_result(
        _text_block("Here is the screenshot:"),
        _image_block("aGVsbG8=", mime="image/png"),
    )

    result = await client.call_tool("screenshot", {"url": "http://x"})

    assert result.base64_image is not None
    assert result.base64_image.startswith("data:image/png;base64,aGVsbG8=")
    assert result.output == "Here is the screenshot:"


# --- close / lifecycle ---------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    """Calling ``close()`` twice must not raise."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    session = AsyncMock()
    transport = MagicMock()
    client._session = session
    client._transport_cm = transport
    client._closed = False

    await client.close()
    await client.close()  # must not raise

    # The session/transport were closed once, not twice.
    assert session.__aexit__.await_count == 1
    assert transport.__aexit__.await_count == 1
    assert client._session is None
    assert client._transport_cm is None
    assert client._closed is True


@pytest.mark.asyncio
async def test_close_is_safe_when_never_connected() -> None:
    """A client that was never connected can still be closed."""
    client = _make_client(MCPTransport.STREAMABLE_HTTP, url="http://example/mcp")
    await client.close()  # must not raise
    assert client._closed is True


# --- sse deprecation -----------------------------------------------------


@pytest.mark.asyncio
async def test_sse_transport_emits_deprecation_warning() -> None:
    """Using ``MCPTransport.SSE`` issues a ``DeprecationWarning``."""
    client = _make_client(MCPTransport.SSE, url="http://example/sse")
    with patch("mcp.client.sse.sse_client") as sse:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        cm.__aexit__ = AsyncMock(return_value=None)
        sse.return_value = cm
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await client._connect_sse()
        assert any(issubclass(w.category, DeprecationWarning) for w in caught), (
            "Expected a DeprecationWarning when using the SSE transport"
        )
