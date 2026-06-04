"""Tests for the Textual TUI scaffold."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from forgewright.tui.app import ForgewrightTuiApp
from forgewright.tui.sse import parse_sse_chunk


def test_forgewright_tui_app_imports() -> None:
    """The TUI app class is importable when ``textual`` is installed."""
    assert ForgewrightTuiApp.TITLE == "forgewright"


def test_parse_sse_chunk_final() -> None:
    """SSE chunk parsing matches the web client's event blocks."""
    chunk = 'event: final\ndata: {"content": "done"}\n'
    parsed = parse_sse_chunk(chunk)
    assert parsed == ("final", {"content": "done"})
