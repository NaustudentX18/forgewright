"""Minimal client for the public MCP server registry.

The official registry at ``https://registry.modelcontextprotocol.io``
publishes a JSON document of well-known MCP servers. This module fetches
the document, resolves a server by name, and can write a TOML snippet to
``~/.config/forgewright/mcp.json`` for ``forgewright mcp install``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forgewright.logger import logger
from forgewright.security.trust import toml_quote

__all__ = [
    "REGISTRY_URL",
    "MCP_CONFIG_PATH",
    "InstallResult",
    "find_server_entry",
    "format_mcp_server_toml",
    "install_server",
    "list_known_servers",
    "resolve_install",
    "upsert_mcp_config",
]


REGISTRY_URL: str = "https://registry.modelcontextprotocol.io/v0/servers"
MCP_CONFIG_PATH: Path = Path.home() / ".config" / "forgewright" / "mcp.json"

# Short names from docs / RESEARCH.md when the public registry has no entry yet.
KNOWN_SERVER_ALIASES: dict[str, dict[str, Any]] = {
    "postgres": {
        "name": "io.modelcontextprotocol/postgres",
        "description": "PostgreSQL — read-only SQL (Anthropic reference server).",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@modelcontextprotocol/server-postgres",
                "transport": {"type": "stdio"},
            }
        ],
    },
    "filesystem": {
        "name": "io.modelcontextprotocol/filesystem",
        "description": "Filesystem — sandboxed local file operations.",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@modelcontextprotocol/server-filesystem",
                "transport": {"type": "stdio"},
            }
        ],
    },
    "github": {
        "name": "io.modelcontextprotocol/github",
        "description": "GitHub — issues, PRs, and code search.",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@modelcontextprotocol/server-github",
                "transport": {"type": "stdio"},
            }
        ],
    },
    "fetch": {
        "name": "io.modelcontextprotocol/fetch",
        "description": "Fetch — retrieve URLs and return markdown.",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@modelcontextprotocol/server-fetch",
                "transport": {"type": "stdio"},
            }
        ],
    },
    "sequential-thinking": {
        "name": "io.modelcontextprotocol/sequential-thinking",
        "description": "Sequential Thinking — structured planning chain.",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@modelcontextprotocol/server-sequential-thinking",
                "transport": {"type": "stdio"},
            }
        ],
    },
}


@dataclass(frozen=True)
class InstallResult:
    """Outcome of ``install_server``."""

    server_id: str
    registry_name: str
    toml_section: str
    instructions: str | None = None
    wrote_config: bool = False
    config_path: Path | None = None


def _normalize_registry_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten registry v0 list items to a single server dict + metadata."""
    if "server" in item:
        server = item["server"]
        if not isinstance(server, dict):
            return {}
        meta = item.get("_meta")
        if isinstance(meta, dict):
            server = {**server, "_meta": meta}
        return server
    return item


async def list_known_servers() -> list[dict[str, Any]]:
    """Fetch the public MCP server registry. Returns ``[]`` on any error."""
    try:
        import httpx
    except ImportError:
        logger.warning("mcp.registry.httpx_missing")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(REGISTRY_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("mcp.registry.fetch_failed err={}", exc)
        return []

    if not isinstance(data, dict):
        logger.warning("mcp.registry.unexpected_shape type={}", type(data).__name__)
        return []

    raw_servers = data.get("servers", [])
    if not isinstance(raw_servers, list):
        logger.warning("mcp.registry.servers_not_list type={}", type(raw_servers).__name__)
        return []

    out: list[dict[str, Any]] = []
    for item in raw_servers:
        if isinstance(item, dict):
            normalized = _normalize_registry_item(item)
            if normalized:
                out.append(normalized)
    return out


def _is_latest(server: dict[str, Any]) -> bool:
    meta = server.get("_meta")
    if not isinstance(meta, dict):
        return True
    official = meta.get("io.modelcontextprotocol.registry/official")
    if not isinstance(official, dict):
        return True
    return official.get("isLatest", True) is not False


def _name_matches(server: dict[str, Any], query: str) -> bool:
    q = query.lower().strip()
    name = str(server.get("name") or "").lower()
    title = str(server.get("title") or "").lower()
    if not name and not title:
        return False
    if q == name or q == title:
        return True
    if name.endswith(f"/{q}") or name.endswith(f".{q}"):
        return True
    if q in name or q in title:
        return True
    short = name.rsplit("/", 1)[-1]
    return q == short


def find_server_entry(servers: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    """Resolve a registry server dict by short name, title, or full name."""
    q = query.lower().strip()
    if q in KNOWN_SERVER_ALIASES:
        return dict(KNOWN_SERVER_ALIASES[q])

    latest = [s for s in servers if _is_latest(s)]
    pool = latest if latest else servers

    exact = [s for s in pool if _name_matches(s, q)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        exact.sort(key=lambda s: str(s.get("name") or ""))
        return exact[0]
    return None


def _default_server_id(query: str, server: dict[str, Any]) -> str:
    q = query.lower().strip()
    if q in KNOWN_SERVER_ALIASES:
        return q
    name = str(server.get("name") or q)
    return name.rsplit("/", 1)[-1] or q


def _package_stdio_command(pkg: dict[str, Any]) -> tuple[str, list[str]] | None:
    registry_type = str(pkg.get("registryType") or "").lower()
    identifier = str(pkg.get("identifier") or "").strip()
    version = pkg.get("version")
    if not identifier:
        return None

    if registry_type == "npm":
        spec = identifier
        if version:
            spec = f"{identifier}@{version}"
        return "npx", ["-y", spec]

    if registry_type == "pypi":
        spec = identifier
        if version:
            spec = f"{identifier}=={version}"
        return "uvx", [spec]

    return None


def resolve_install(query: str, server: dict[str, Any]) -> InstallResult:
    """Build TOML + optional manual steps for one registry server dict."""
    server_id = _default_server_id(query, server)
    registry_name = str(server.get("name") or server_id)
    description = str(server.get("description") or "").strip()

    packages = server.get("packages")
    if isinstance(packages, list) and packages:
        pkg = packages[0]
        if not isinstance(pkg, dict):
            pkg = {}
        registry_type = str(pkg.get("registryType") or "").lower()
        if registry_type == "oci":
            ident = pkg.get("identifier", "")
            msg = (
                f"Registry lists an OCI image for {registry_name!r}.\n"
                f"  docker pull {ident}\n"
                f"  Then add a stdio transport that runs the container, or use the publisher docs."
            )
            return InstallResult(
                server_id=server_id,
                registry_name=registry_name,
                toml_section="",
                instructions=msg,
            )

        stdio = _package_stdio_command(pkg)
        if stdio is None:
            return InstallResult(
                server_id=server_id,
                registry_name=registry_name,
                toml_section="",
                instructions=(
                    f"Unsupported package type {registry_type!r} for {registry_name!r}. "
                    "See the server page in the MCP registry for manual setup."
                ),
            )

        command, args = stdio
        env_lines: list[str] = []
        for var in pkg.get("environmentVariables") or []:
            if not isinstance(var, dict):
                continue
            var_name = var.get("name")
            if not var_name:
                continue
            hint = str(var.get("description") or "set in your environment")
            env_lines.append(f"# {var_name}: {hint}")

        section = format_mcp_server_toml(
            server_id,
            transport="stdio",
            command=command,
            args=args,
            env_comment_lines=env_lines,
        )
        if description:
            section = f"# {description}\n{section}"
        return InstallResult(
            server_id=server_id,
            registry_name=registry_name,
            toml_section=section,
        )

    remotes = server.get("remotes")
    if isinstance(remotes, list) and remotes:
        remote = remotes[0] if isinstance(remotes[0], dict) else {}
        url = remote.get("url")
        transport = str(remote.get("type") or "streamable-http")
        if not url:
            return InstallResult(
                server_id=server_id,
                registry_name=registry_name,
                toml_section="",
                instructions=f"Registry entry {registry_name!r} has no remote URL.",
            )
        section = format_mcp_server_toml(
            server_id,
            transport=transport,
            url=str(url),
        )
        headers = remote.get("headers")
        if isinstance(headers, list) and headers:
            section += "\n# Remote requires auth headers — set auth_token_env in config."
        if description:
            section = f"# {description}\n{section}"
        return InstallResult(
            server_id=server_id,
            registry_name=registry_name,
            toml_section=section,
        )

    return InstallResult(
        server_id=server_id,
        registry_name=registry_name,
        toml_section="",
        instructions=(
            f"No installable package or remote URL found for {registry_name!r}. "
            "Open the MCP registry entry for publisher setup steps."
        ),
    )


def format_mcp_server_toml(
    server_id: str,
    *,
    transport: str,
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    env_comment_lines: list[str] | None = None,
) -> str:
    """Render one ``[mcp.servers.<id>]`` block as TOML text."""
    lines: list[str] = [f"[mcp.servers.{server_id}]"]
    lines.append(f"transport = {toml_quote(transport)}")
    if command:
        lines.append(f"command = {toml_quote(command)}")
    if args:
        rendered = ", ".join(toml_quote(a) for a in args)
        lines.append(f"args = [{rendered}]")
    if url:
        lines.append(f"url = {toml_quote(url)}")
    if env_comment_lines:
        lines.extend(env_comment_lines)
    return "\n".join(lines)


def upsert_mcp_config(path: Path, server_id: str, section: str) -> None:
    """Create or replace one server block in the MCP config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"[mcp.servers.{server_id}]"
    if not path.exists():
        path.write_text(
            "# MCP servers — installed via `forgewright mcp install`\n\n" + section.strip() + "\n",
            encoding="utf-8",
        )
        return

    text = path.read_text(encoding="utf-8")
    block_re = re.compile(
        rf"^\[mcp\.servers\.{re.escape(server_id)}\][^\[]*",
        re.MULTILINE,
    )
    if block_re.search(text):
        text = block_re.sub(section.strip() + "\n\n", text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + section.strip() + "\n"
    path.write_text(text, encoding="utf-8")


async def install_server(
    name: str,
    *,
    config_path: Path | None = None,
    write_config: bool = True,
) -> InstallResult | None:
    """Fetch registry, resolve ``name``, optionally write ``mcp.json``."""
    servers = await list_known_servers()
    entry = find_server_entry(servers, name)
    if entry is None:
        return None

    result = resolve_install(name, entry)
    if result.instructions and not result.toml_section:
        return result

    if write_config and result.toml_section:
        path = config_path or MCP_CONFIG_PATH
        upsert_mcp_config(path, result.server_id, result.toml_section)
        return InstallResult(
            server_id=result.server_id,
            registry_name=result.registry_name,
            toml_section=result.toml_section,
            instructions=result.instructions,
            wrote_config=True,
            config_path=path,
        )
    return result
