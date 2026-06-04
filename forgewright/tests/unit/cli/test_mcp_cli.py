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


# ---------- registry install (v0.2) ----------


def test_mcp_install_requires_server_name() -> None:
    """``forgewright mcp install`` without a name exits 2."""
    result = runner.invoke(app, ["mcp", "install"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "install" in out.lower()


def test_mcp_install_unknown_server_exits_1() -> None:
    """Unknown server name exits 1 when the registry has no match."""
    import httpx
    import respx
    from forgewright.mcp.registry import REGISTRY_URL

    with respx.mock:
        respx.get(REGISTRY_URL).mock(
            return_value=httpx.Response(200, json={"servers": [], "metadata": {}})
        )
        result = runner.invoke(app, ["mcp", "install", "no-such-server-xyz"])
    assert result.exit_code == 1
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "no-such-server-xyz" in out


def test_mcp_install_postgres_writes_config(tmp_path, monkeypatch) -> None:
    """``forgewright mcp install postgres`` writes stdio npx config via alias."""
    import httpx
    import respx
    from forgewright.mcp.registry import REGISTRY_URL

    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr(
        "forgewright.mcp.registry.MCP_CONFIG_PATH",
        config_path,
    )

    with respx.mock:
        respx.get(REGISTRY_URL).mock(
            return_value=httpx.Response(200, json={"servers": [], "metadata": {}})
        )
        result = runner.invoke(app, ["mcp", "install", "postgres"])

    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "mcp.servers.postgres" in out
    assert "server-postgres" in out
    assert config_path.exists()
    written = config_path.read_text()
    assert "[mcp.servers.postgres]" in written
    assert "npx" in written


def test_mcp_install_from_registry_mock(tmp_path, monkeypatch) -> None:
    """Install resolves a nested registry entry over HTTP (respx)."""
    import httpx
    import respx
    from forgewright.mcp.registry import REGISTRY_URL

    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr(
        "forgewright.mcp.registry.MCP_CONFIG_PATH",
        config_path,
    )
    payload = {
        "servers": [
            {
                "server": {
                    "name": "ai.adeu/adeu",
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@adeu/mcp-server",
                            "version": "1.7.1",
                            "transport": {"type": "stdio"},
                        }
                    ],
                },
                "_meta": {
                    "io.modelcontextprotocol.registry/official": {"isLatest": True},
                },
            }
        ],
        "metadata": {},
    }

    with respx.mock:
        respx.get(REGISTRY_URL).mock(return_value=httpx.Response(200, json=payload))
        result = runner.invoke(app, ["mcp", "install", "adeu"])

    assert result.exit_code == 0
    out = (result.stdout or "") + (getattr(result, "stderr", None) or "")
    assert "@adeu/mcp-server@1.7.1" in out
    assert "[mcp.servers.adeu]" in config_path.read_text()


# ---------- stub-mode subcommands ----------


def test_mcp_ls_prints_v02_stub_message() -> None:
    """``forgewright mcp ls`` prints the v0.2 stub message and exits 0."""
    result = runner.invoke(app, ["mcp", "ls"])
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
