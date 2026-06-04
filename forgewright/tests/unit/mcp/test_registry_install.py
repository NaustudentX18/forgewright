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
