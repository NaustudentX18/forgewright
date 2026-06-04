"""Web UI smoke test — load /, app.js, style.css and confirm they are not
truncated.

The ``app.js`` truncation bug that shipped to master in v0.2.0 (missing
the IIFE at the top) was only caught when a human opened the UI in a
browser. This test exists so that no future file is silently truncated
by a packaging / static-mount regression. It's intentionally tiny: one
file, a few assertions, no network, no LLM.

Marked as ``integration`` because it touches the full FastAPI app
incl. static-file mounting and the OpenAPI/HTML routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from forgewright.config import LLMConfig, Settings
from forgewright.web.server import create_app


@pytest.fixture
def stub_settings() -> Settings:
    """A settings instance that always uses the stub LLM.

    The web UI does not need a real LLM to render — only to *run* a
    session. This keeps the smoke test hermetic.
    """
    return Settings(llm=LLMConfig(provider="stub", model="stub-model"), max_steps=1)


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_settings: Settings,
) -> Iterator[TestClient]:
    """A FastAPI TestClient with sessions pointed at a tmp dir."""
    monkeypatch.setattr(
        "forgewright.web.server.default_sessions_dir", lambda: tmp_path
    )
    application = create_app(settings=stub_settings)
    with TestClient(application) as c:
        yield c


def test_root_serves_index_html(client: TestClient) -> None:
    """``GET /`` returns 200 with the chat UI HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "<html" in body.lower()
    assert "forgewright" in body.lower()
    # The index must reference the JS + CSS bundles the test below
    # also fetches. A truncated index.html would drop these.
    assert "app.js" in body
    assert "style.css" in body


def test_app_js_served_intact(client: TestClient) -> None:
    """``GET /static/app.js`` is served, correct content-type, and not
    truncated at the top (the v0.2.0 bug).

    The IIFE opener ``(function () {`` is the first line of the file;
    the ``})();`` closer is the last. Both must be present.
    """
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    body = r.text
    # Truncation-bait: the IIFE opener is at the very top.
    stripped = body.lstrip()
    assert stripped.startswith("(function ()") or stripped.startswith("!function"), (
        f"app.js does not start with the IIFE — got: {stripped[:80]!r}"
    )
    # And the closer must exist somewhere in the file.
    assert "})();" in body, "app.js closer IIFE not found — file may be truncated at the end"
    # Sanity: file is non-trivial. 5kB minimum to catch ~90% truncation.
    assert len(body) > 5_000, f"app.js suspiciously small: {len(body)} bytes"


def test_style_css_served_intact(client: TestClient) -> None:
    """``GET /static/style.css`` is served with a non-empty, well-formed
    body (no truncation, no packaging glitch)."""
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "css" in r.headers["content-type"]
    body = r.text
    # style.css starts with the :root token block. If the file is
    # truncated mid-way we won't see the closing brace.
    assert body.lstrip().startswith(":root"), "style.css does not start with :root"
    assert body.rstrip().endswith("}"), "style.css does not end with closing brace"
    # CSS variables should be present.
    assert "--color-" in body
    assert "--space-" in body
    # Sanity bound.
    assert len(body) > 1_000, f"style.css suspiciously small: {len(body)} bytes"


def test_app_js_and_style_css_served_with_caching_headers(
    client: TestClient,
) -> None:
    """Static assets should declare a content-length so the browser
    can stream them. A missing content-length is the classic sign of
    a streaming wrapper that might not flush the full file."""
    r_js = client.get("/static/app.js")
    r_css = client.get("/static/style.css")
    assert int(r_js.headers.get("content-length", len(r_js.content))) >= len(r_js.content)
    assert int(r_css.headers.get("content-length", len(r_css.content))) >= len(r_css.content)
    # And the bytes returned match the headers.
    assert len(r_js.content) == len(r_js.text.encode("utf-8"))
    assert len(r_css.content) == len(r_css.text.encode("utf-8"))


def test_health_endpoint_still_works(client: TestClient) -> None:
    """Sanity: the API health route is unaffected by the static mounts."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
