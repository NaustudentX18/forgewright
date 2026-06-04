"""``forgewright tui`` — Textual terminal UI for the web chat API."""

from __future__ import annotations

__all__ = ["tui_command"]


def tui_command(
    url: str = "http://127.0.0.1:8787",
) -> None:
    """Launch the Textual TUI connected to a running ``forgewright web`` server.

    Parameters
    ----------
    url
        Base URL of the web API (default matches ``forgewright web`` port
        ``8787`` on loopback).
    """
    try:
        from textual.app import App  # noqa: F401 — validates extra
    except ImportError as exc:  # pragma: no cover — install path
        raise SystemExit(
            "The TUI requires the [tui] extra.\n"
            "Install it with:  uv pip install 'forgewright[tui]'\n"
            f"(underlying error: {exc})"
        ) from None

    from forgewright.tui.app import ForgewrightTuiApp

    ForgewrightTuiApp(base_url=url).run()
