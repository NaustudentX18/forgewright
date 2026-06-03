"""Tests for the ``forgewright mcp ...`` CLI dispatcher.

Uses ``typer.testing.CliRunner`` to invoke the root app and assert
exit codes / help text.
"""

from __future__ import annotations

from unittest.mock import patch

from forgewright.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


# ---------- help / discovery ----------


def test_mcp_help_lists_subcommands() -> None:
    """``forgewright mcp --help`` shows the action argument + options."""
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    # The Typer-rendered help should mention the action argument.
    assert "serve" in out
    assert "connect" in out


def test_mcp_serve_help_shows_transport_option() -> None:
    """``forgewright mcp serve --help`` shows the transport option."""
    result = runner.invoke(app, ["mcp", "serve", "--help"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "--transport" in out
    assert "--port" in out


def test_mcp_serve_shortcut_help() -> None:
    """``forgewright mcp-serve --help`` works (the shortcut is registered)."""
    result = runner.invoke(app, ["mcp-serve", "--help"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "--transport" in out


# ---------- stub-mode subcommands ----------


def test_mcp_ls_prints_v02_stub_message() -> None:
    """``forgewright mcp ls`` prints the v0.2 stub message and exits 0."""
    result = runner.invoke(app, ["mcp", "ls"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "v0.2" in out


def test_mcp_install_prints_v02_stub_message() -> None:
    """``forgewright mcp install`` is also a v0.2 stub."""
    result = runner.invoke(app, ["mcp", "install"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "v0.2" in out


def test_mcp_trust_prints_v02_stub_message() -> None:
    """``forgewright mcp trust`` is also a v0.2 stub."""
    result = runner.invoke(app, ["mcp", "trust"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "v0.2" in out


# ---------- error handling ----------


def test_mcp_unknown_action_exits_2() -> None:
    """An unknown sub-action returns exit code 2."""
    result = runner.invoke(app, ["mcp", "badaction"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "badaction" in out


def test_mcp_connect_without_url_or_command_exits_2() -> None:
    """``mcp connect`` with neither ``--command`` nor ``--url`` exits 2."""
    result = runner.invoke(app, ["mcp", "connect"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    # Should mention at least one of the missing fields.
    assert "command" in out or "url" in out


# ---------- dispatch to serve ----------


def test_mcp_serve_invokes_server_serve() -> None:
    """``forgewright mcp serve`` calls ``forgewright.mcp.server.serve``."""
    with patch("forgewright.mcp.server.serve") as serve_mock:
        result = runner.invoke(app, ["mcp", "serve", "--port", "9001"])
    assert result.exit_code == 0
    serve_mock.assert_called_once()
    # The port was forwarded.
    kwargs = serve_mock.call_args.kwargs
    assert kwargs.get("port") == 9001
    # Transport defaults to stdio.
    assert kwargs.get("transport") == "stdio"
