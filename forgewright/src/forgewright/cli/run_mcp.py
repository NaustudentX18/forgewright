"""``forgewright mcp`` — dispatcher for MCP server / client operations.

Subcommands:

* ``serve`` — start the FastMCP server (stdio or streamable-http).
* ``connect`` — connect to a remote MCP server, list its tools, exit.
* ``install <name>`` — resolve a server from the public MCP registry and
  write ``~/.config/forgewright/mcp.json``.
* ``ls`` / ``trust`` — placeholders for v0.2.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from forgewright.logger import logger
from forgewright.mcp.client import MCPClient, MCPServerConfig, MCPTransport
from forgewright.mcp.registry import install_server

console = Console()

__all__ = ["mcp_command"]


def mcp_command(
    action: str = typer.Argument(
        ...,
        help="Sub-action: serve | connect | ls | install | trust.",
    ),
    server_name: str | None = typer.Argument(
        None,
        help="Registry server name for `install` (e.g. postgres, ai.adeu/adeu).",
    ),
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport for serve (stdio|streamable-http) or connect.",
    ),
    server_id: str = typer.Option(
        "local",
        "--server-id",
        help="Logical server id (used as the namespacing prefix).",
    ),
    command: str | None = typer.Option(
        None,
        "--command",
        "-c",
        help="Command to spawn for stdio transport.",
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        help="URL for streamable-http / sse transport.",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="TCP port for the streamable-http server.",
    ),
) -> None:
    """Run MCP server / client operations."""
    if action == "serve":
        from forgewright.mcp.server import serve

        serve(transport=transport, port=port)
        return

    if action == "connect":
        asyncio.run(_connect_and_list(server_id, transport, command, url))
        return

    if action == "install":
        asyncio.run(_run_install(server_name))
        return

    if action in ("ls", "trust"):
        console.print("[yellow]Not implemented in v0.1 (lands in v0.2)[/yellow]")
        raise typer.Exit(0)

    console.print(f"[red]Unknown action: {action}[/red]")
    raise typer.Exit(2)


async def _run_install(server_name: str | None) -> None:
    """Fetch the registry, resolve the server, write or print install config."""
    if not server_name:
        console.print(
            "[red]`install` requires a server name "
            "(e.g. `forgewright mcp install postgres`)[/red]"
        )
        raise typer.Exit(2)

    result = await install_server(server_name)
    if result is None:
        console.print(f"[red]No registry server matched {server_name!r}[/red]")
        raise typer.Exit(1)

    if result.instructions and not result.toml_section:
        console.print(f"[yellow]{result.instructions}[/yellow]")
        raise typer.Exit(1)

    console.print(
        f"[green]✓[/green] Resolved [cyan]{result.registry_name}[/cyan] "
        f"as [bold]mcp.servers.{result.server_id}[/bold]"
    )
    if result.wrote_config and result.config_path:
        console.print(f"[green]✓[/green] Wrote {result.config_path}")
    console.print()
    console.print(result.toml_section)
    if result.instructions:
        console.print()
        console.print(f"[dim]{result.instructions}[/dim]")


async def _connect_and_list(
    server_id: str,
    transport: str,
    command: str | None,
    url: str | None,
) -> None:
    """Build a config + client, list tools, and print them in a table."""
    try:
        transport_enum = MCPTransport(transport)
    except ValueError:
        console.print(f"[red]Unknown transport: {transport}[/red]")
        raise typer.Exit(2) from None

    if transport_enum == MCPTransport.STDIO and not command:
        console.print("[red]stdio transport requires --command / -c[/red]")
        raise typer.Exit(2)
    if transport_enum in (MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE) and not url:
        console.print(f"[red]{transport} transport requires --url / -u[/red]")
        raise typer.Exit(2)

    cfg = MCPServerConfig(
        server_id=server_id,
        transport=transport_enum,
        command=command,
        url=url,
    )
    client = MCPClient(cfg)
    try:
        await client.connect()
        specs = await client.list_tools()
    except Exception as exc:
        logger.exception("mcp.cli.connect_failed")
        console.print(f"[red]Failed to connect / list tools: {exc}[/red]")
        raise typer.Exit(1) from None
    finally:
        await client.close()

    table = Table(title=f"Tools on '{server_id}' ({transport_enum.value})")
    table.add_column("Namespaced name", style="cyan", no_wrap=True)
    table.add_column("Upstream name", style="green")
    table.add_column("Description")

    for spec in specs:
        from forgewright.tool.registry import ToolRegistry

        namespaced = ToolRegistry.namespaced_name(server_id, spec.name)
        table.add_row(namespaced, spec.name, spec.description or "")
    console.print(table)
