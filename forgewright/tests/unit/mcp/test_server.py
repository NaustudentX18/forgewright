"""Tests for ``forgewright.mcp.server.serve()``.

The FastMCP class is mocked so we can pin down which transport the
server is launched with, and that the four local tools are registered
as FastMCP tools (via ``BaseTool.as_fastmcp_tool``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from forgewright.mcp.server import serve


@pytest.fixture
def patched_fastmcp() -> tuple[MagicMock, MagicMock]:
    """Patch ``fastmcp.FastMCP`` and return (FastMCP_ctor, instance)."""
    with patch("fastmcp.FastMCP") as FastMCP:
        instance = MagicMock(name="FastMCP_instance")
        FastMCP.return_value = instance
        yield FastMCP, instance


def test_serve_stdio_calls_run_with_stdio_transport(patched_fastmcp: tuple) -> None:
    """``serve('stdio')`` calls ``FastMCP.run(transport='stdio')``."""
    _FastMCP, instance = patched_fastmcp
    serve(transport="stdio", port=8000)

    # The four local tools were registered. The name is on the
    # adapter function's ``__name__`` (set by ``as_fastmcp_tool``),
    # not on a kwarg — FastMCP 3 takes a single positional callable.
    add_tool_calls = instance.add_tool.call_args_list
    assert len(add_tool_calls) == 4
    registered_names = {getattr(c.args[0], "__name__", None) for c in add_tool_calls}
    # Names are the BaseTool.name values.
    assert {"bash", "str_replace_editor", "browser", "terminate"}.issubset(registered_names)

    # The server was started in stdio mode.
    instance.run.assert_called_once_with(transport="stdio")


def test_serve_streamable_http_passes_port(patched_fastmcp: tuple) -> None:
    """``serve('streamable-http', port=9000)`` passes the port to run()."""
    _FastMCP, instance = patched_fastmcp
    serve(transport="streamable-http", port=9000)

    instance.run.assert_called_once_with(transport="streamable-http", port=9000)


def test_serve_uses_local_tools(patched_fastmcp: tuple) -> None:
    """The server registers Bash, StrReplaceEditor, BrowserUseTool, TerminateTool."""
    _FastMCP, instance = patched_fastmcp
    serve(transport="stdio")
    add_tool_calls = instance.add_tool.call_args_list
    # Each call has a single positional argument: the adapter function.
    for call in add_tool_calls:
        assert len(call.args) == 1
        adapter = call.args[0]
        # The adapter is callable (as_fastmcp_tool returns an async function).
        assert callable(adapter)
        # Its __name__ is the BaseTool.name value.
        assert getattr(adapter, "__name__", None)


def test_serve_defaults_to_stdio(patched_fastmcp: tuple) -> None:
    """Default transport is ``stdio``; default port is 8000."""
    _FastMCP, instance = patched_fastmcp
    serve()
    instance.run.assert_called_once_with(transport="stdio")
