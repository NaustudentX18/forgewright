"""ToolRegistry — name tracking with optional namespacing and allowlist."""

from __future__ import annotations

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """Tracks tool names with optional namespacing and allowlist enforcement.

    The MCP proxy in Phase 8 uses this to enforce that only allowlisted
    remote tools are invokable, and to prevent one MCP server from
    shadowing another via the `<server_id>__<tool_name>` namespace.
    """

    SEPARATOR: str = "__"

    def __init__(self, allowlist: list[str] | None = None) -> None:
        """Initialize with an optional allowlist of namespaced tool names."""
        self._allowlist: set[str] | None = set(allowlist) if allowlist is not None else None
        self._names: set[str] = set()

    def register(self, name: str, namespace: str | None = None) -> str:
        """Register a tool, returning the namespaced name actually stored."""
        full = self.namespaced_name(namespace, name)
        self._names.add(full)
        return full

    def unregister(self, name: str, namespace: str | None = None) -> None:
        """Remove a tool by (namespace, name); silently no-op if absent."""
        self._names.discard(self.namespaced_name(namespace, name))

    @staticmethod
    def namespaced_name(namespace: str | None, name: str) -> str:
        """Render `<namespace>__<name>` when a namespace is given, else `<name>`."""
        if namespace:
            return f"{namespace}{ToolRegistry.SEPARATOR}{name}"
        return name

    def is_allowed(self, namespaced_name: str) -> bool:
        """Return True if `namespaced_name` is allowed (always allowed when no allowlist)."""
        if self._allowlist is None:
            return True
        return namespaced_name in self._allowlist

    def __contains__(self, namespaced_name: str) -> bool:
        return namespaced_name in self._names

    def __len__(self) -> int:
        return len(self._names)

    def names(self) -> list[str]:
        """Return a sorted list of registered namespaced tool names."""
        return sorted(self._names)
