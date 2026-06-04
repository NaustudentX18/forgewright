"""Tests for MCP registry install resolution (no network)."""

from __future__ import annotations

from pathlib import Path

from forgewright.mcp.registry import (
    find_server_entry,
    format_mcp_server_toml,
    resolve_install,
    upsert_mcp_config,
)


def test_find_server_entry_known_alias() -> None:
    entry = find_server_entry([], "postgres")
    assert entry is not None
    assert "server-postgres" in str(entry.get("packages", [{}])[0].get("identifier", ""))


def test_find_server_entry_by_registry_name() -> None:
    servers = [
        {
            "name": "ai.adeu/adeu",
            "description": "Automated DOCX Redlining Engine",
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@adeu/mcp-server",
                    "version": "1.7.1",
                    "transport": {"type": "stdio"},
                }
            ],
            "_meta": {
                "io.modelcontextprotocol.registry/official": {"isLatest": True},
            },
        }
    ]
    entry = find_server_entry(servers, "adeu")
    assert entry is not None
    assert entry["name"] == "ai.adeu/adeu"


def test_resolve_install_npm_stdio() -> None:
    server = {
        "name": "ai.adeu/adeu",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@adeu/mcp-server",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ],
    }
    result = resolve_install("adeu", server)
    assert "transport = \"stdio\"" in result.toml_section
    assert "npx" in result.toml_section
    assert "@adeu/mcp-server@1.0.0" in result.toml_section


def test_resolve_install_remote_http() -> None:
    server = {
        "name": "ac.tandem/docs-mcp",
        "remotes": [{"type": "streamable-http", "url": "https://tandem.ac/mcp"}],
    }
    result = resolve_install("docs-mcp", server)
    assert "streamable-http" in result.toml_section
    assert "https://tandem.ac/mcp" in result.toml_section


def test_upsert_mcp_config_creates_and_replaces(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    section = format_mcp_server_toml(
        "postgres",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
    )
    upsert_mcp_config(path, "postgres", section)
    text = path.read_text()
    assert "[mcp.servers.postgres]" in text

    section2 = format_mcp_server_toml(
        "postgres",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/db"],
    )
    upsert_mcp_config(path, "postgres", section2)
    text2 = path.read_text()
    assert "postgresql://localhost/db" in text2
    assert text2.count("[mcp.servers.postgres]") == 1


def test_default_server_id_safe_against_injection() -> None:
    """A user-supplied query with TOML-significant characters is sanitised."""
    from forgewright.mcp.registry import _default_server_id

    bad = '"; INJECTED = 1'
    result = _default_server_id(bad, {"name": bad})
    # Must not contain spaces, quotes, or '='.
    assert " " not in result
    assert '"' not in result
    assert "=" not in result
    # Must be a valid TOML section key.
    import re as _re

    assert _re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", result)


def test_default_server_id_handles_empty_and_dash() -> None:
    """An empty or dash-only result falls back to a safe form."""
    from forgewright.mcp.registry import _default_server_id

    # All-stripped inputs collapse to the ``server`` sentinel.
    assert _default_server_id("!!!", {"name": ""}) == "server"
    assert _default_server_id("---", {"name": "---"}) == "server"
    # Input that starts with a digit is fine (matches the pattern).
    assert _default_server_id("7zip", {"name": "7zip"}) == "7zip"


def test_resolve_install_sanitises_description() -> None:
    """Newlines in a description must not break out of the comment line."""
    import tomllib

    server = {
        "name": "io.example/evil",
        "description": "evil\n[mcp.servers.pwned]\ncommand = \"x\"",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/evil",
                "transport": {"type": "stdio"},
            }
        ],
    }
    result = resolve_install("evil", server)
    # No raw newlines survived into the rendered TOML block, so a
    # downstream ``tomllib.loads`` succeeds and only the legitimate
    # ``[mcp.servers.evil]`` table is present (no ``pwned`` table).
    assert "\n[mcp.servers.pwned]" not in result.toml_section
    parsed = tomllib.loads(result.toml_section)
    assert "mcp" in parsed
    assert "servers" in parsed["mcp"]
    assert "evil" in parsed["mcp"]["servers"]
    assert "pwned" not in parsed["mcp"]["servers"]
