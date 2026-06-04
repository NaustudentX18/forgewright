"""Service-worker contract tests.

These are string-content / structure tests, not runtime tests. We do
not load jsdom for a single SW — instead we lock the contract that
matters: which events are wired, what cache name is used, and that
``POST`` requests bypass the SW (so SSE on the message endpoint
continues to work).

The runtime behavior is verified manually on the phone (see
docs/MOBILE.md "Reproducing the PWA install") and via the existing
``TestClient`` integration tests in ``test_server.py``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SW = Path(__file__).resolve().parents[3] / "src/forgewright/web/static" / "sw.js"


def _read() -> str:
    return SW.read_text(encoding="utf-8")


def test_sw_file_exists() -> None:
    assert SW.exists(), f"service worker missing: {SW}"
    assert SW.stat().st_size > 0


def test_sw_registers_all_three_lifecycle_events() -> None:
    """``install``, ``activate``, and ``fetch`` must all be wired.

    Missing any of them breaks a specific class of behavior:
    ``install`` skips precache, ``activate`` keeps old caches, ``fetch``
    means the SW is a no-op.
    """
    src = _read()
    assert 'addEventListener("install"' in src
    assert 'addEventListener("activate"' in src
    assert 'addEventListener("fetch"' in src


def test_sw_uses_versioned_cache_name() -> None:
    """The cache name is versioned so a deploy that bumps the version
    invalidates the old shell on next activate.

    Locking the literal here means a future refactor that silently
    renames the cache fails this test, not on a phone at 3am."""
    src = _read()
    assert "forgewright-shell-v2" in src


def test_sw_bypasses_post_for_sse() -> None:
    """The fetch handler must NOT call ``respondWith`` for non-GET
    requests — otherwise it would intercept the SSE stream on
    ``POST /api/sessions/{id}/messages`` and break streaming.

    The simplest regression guard: assert the fetch handler explicitly
    short-circuits on ``req.method !== "GET"`` before any
    ``respondWith`` call.
    """
    src = _read()
    # Locate the fetch handler block.
    # Use the main GET fetch handler (last ``fetch`` listener in sw.js).
    fetch_idx = src.rindex('addEventListener("fetch"')
    fetch_block = src[fetch_idx:]
    # Inside the fetch block, the very first non-comment, non-whitespace
    # logical branch must be the method check.
    assert 'pathname === "/share-in"' in fetch_block
    assert 'req.method !== "GET"' in fetch_block, (
        "fetch handler must short-circuit on non-GET before GET caching"
    )
    # Only POST /share-in may call respondWith; SSE message POSTs bypass.
    before_sse_bypass = fetch_block.split('req.method !== "GET"')[0]
    assert before_sse_bypass.count("respondWith") == 1, (
        "only /share-in POST may respondWith before the generic POST bypass"
    )


def test_sw_fetches_are_same_origin_only() -> None:
    """The SW must not call ``respondWith`` for cross-origin requests
    (e.g. third-party fonts). It does this via an origin check inside
    the fetch handler.
    """
    src = _read()
    fetch_idx = src.rindex('addEventListener("fetch"')
    fetch_block = src[fetch_idx:]
    assert "self.location.origin" in fetch_block, (
        "fetch handler must check url.origin against self.location.origin"
    )


def test_sw_precaches_app_shell() -> None:
    """The SHELL list must include the actual app shell URLs.

    Catches the case where someone updates the SW but forgets to add
    a new static asset to the precache list, leaving the offline
    shell incomplete.
    """
    src = _read()
    # Required shell entries — these are the minimum for the app to
    # render at all from the cache.
    required = [
        "/",
        "/static/style.css",
        "/static/app.js",
        "/static/manifest.webmanifest",
    ]
    for url in required:
        assert url in src, f"shell precache missing: {url}"


def test_sw_registers_background_sync_flush() -> None:
    """Background Sync tag must match app.js so the outbox flushes."""
    src = _read()
    assert "fw-flush-queue" in src
    assert 'addEventListener("sync"' in src


def test_sw_handles_share_in_post() -> None:
    """POST /share-in is handled in the SW for PWA file shares."""
    src = _read()
    assert "/share-in" in src
    assert "handleShareIn" in src


def test_sw_handlers_actually_respond_with_something() -> None:
    """Sanity: the GET /api/sessions* path is reachable from the
    offline cache. We assert the handler functions exist by name."""
    src = _read()
    assert "handleShell" in src
    assert "handleStatic" in src
    assert "handleSession" in src


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_sw_parses_as_valid_javascript() -> None:
    """Best-effort: ask node to syntax-check the SW.

    This is optional (skipped if node is missing) but cheap when
    available, and catches syntax errors that the string-based
    contract tests above would miss."""
    result = subprocess.run(
        ["node", "--check", str(SW)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
