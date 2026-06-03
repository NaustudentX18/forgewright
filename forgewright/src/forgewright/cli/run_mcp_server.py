"""``forgewright mcp-serve`` — thin shortcut for ``forgewright mcp serve``.

Kept as its own entry point so power users can wire the server into a
shell alias or systemd unit without going through the dispatcher.
"""

from __future__ import annotations

__all__ = ["mcp_serve_command"]


def mcp_serve_command(transport: str = "stdio", port: int = 8000) -> None:
    """Shortcut for ``forgewright mcp serve``."""
    # Imported lazily so the ``mcp`` extra is only required when the
    # user actually runs the server.
    from forgewright.mcp.server import serve

    serve(transport=transport, port=port)
