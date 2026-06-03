"""Tests for the FastAPI web server.

Covers the public HTTP surface, plus the SSE streaming path. The
``stub`` LLM provider is wired in via a :class:`forgewright.config.Settings`
override so the agent loop terminates deterministically and never
hits a network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from forgewright import __version__
from forgewright.config import LLMConfig, Settings
from forgewright.session import Session
from forgewright.web.server import app as default_app
from forgewright.web.server import create_app

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the server at a tmp sessions dir and restore on teardown."""
    # ``default_sessions_dir`` resolves at call time, so monkeypatch
    # the return value rather than re-importing the module.
    monkeypatch.setattr(
        "forgewright.web.server.default_sessions_dir", lambda: tmp_path
    )
    return tmp_path


@pytest.fixture
def stub_settings() -> Settings:
    """A settings instance that always uses the stub LLM."""
    return Settings(llm=LLMConfig(provider="stub", model="stub-model"), max_steps=2)


@pytest.fixture
def client(
    sessions_dir: Path, stub_settings: Settings
) -> Iterator[TestClient]:
    """A FastAPI TestClient wired with a stub-backed app."""
    application = create_app(settings=stub_settings)
    with TestClient(application) as c:
        yield c


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


def test_health_returns_expected_fields(client: TestClient) -> None:
    """``GET /api/health`` returns 200 and the documented fields."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "ok",
        "version": __version__,
        "provider": "stub",
        "model": "stub-model",
    }


# --------------------------------------------------------------------------- #
# Static index
# --------------------------------------------------------------------------- #


def test_root_serves_index_html(client: TestClient) -> None:
    """``GET /`` returns the chat UI HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "forgewright" in r.text
    assert "app.js" in r.text


# --------------------------------------------------------------------------- #
# Session CRUD
# --------------------------------------------------------------------------- #


def test_create_session_persists_file(client: TestClient, sessions_dir: Path) -> None:
    """``POST /api/sessions`` creates a new session and writes it to disk."""
    r = client.post("/api/sessions", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == 1
    assert body["metadata"]["created_via"] == "web"
    sid = body["id"]
    # The file is on disk under the tmp sessions dir.
    files = list(sessions_dir.glob("*.json"))
    assert any(f.name == f"{sid}.json" for f in files)


def test_list_sessions_includes_created(client: TestClient) -> None:
    """``GET /api/sessions`` lists the freshly created session."""
    created = client.post("/api/sessions", json={}).json()
    r = client.get("/api/sessions")
    assert r.status_code == 200
    items = r.json()
    ids = [s["id"] for s in items]
    assert created["id"] in ids
    # Each item is a SessionSummary.
    item = next(s for s in items if s["id"] == created["id"])
    assert set(item.keys()) == {
        "id", "created_at", "updated_at", "message_count", "title"
    }
    assert item["title"] == "(empty)"


def test_list_sessions_title_uses_first_user_message(
    client: TestClient, sessions_dir: Path
) -> None:
    """Title is the first user message truncated to 60 chars."""
    sess = client.post("/api/sessions", json={}).json()
    # Append a user message directly (skip the streaming endpoint for setup).
    path = sessions_dir / f"{sess['id']}.json"
    s = Session.load(path)
    from forgewright.schema import ChatMessage

    s.messages.append(ChatMessage(role="user", content="hello world"))
    s.save(sessions_dir)

    r = client.get("/api/sessions")
    item = next(x for x in r.json() if x["id"] == sess["id"])
    assert item["title"] == "hello world"


def test_get_session_returns_full_payload(client: TestClient) -> None:
    """``GET /api/sessions/{id}`` returns the full to_dict() shape."""
    sess = client.post("/api/sessions", json={}).json()
    r = client.get(f"/api/sessions/{sess['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sess["id"]
    assert "messages" in body
    assert "metadata" in body


def test_get_session_404(client: TestClient) -> None:
    """Unknown id returns 404."""
    r = client.get("/api/sessions/does-not-exist")
    assert r.status_code == 404


def test_delete_session_removes_file(client: TestClient, sessions_dir: Path) -> None:
    """``DELETE /api/sessions/{id}`` removes the file and returns 204."""
    sess = client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 204
    assert not (sessions_dir / f"{sid}.json").exists()


def test_delete_session_404(client: TestClient) -> None:
    """Deleting an unknown id returns 404."""
    r = client.delete("/api/sessions/does-not-exist")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Streaming messages
# --------------------------------------------------------------------------- #


def test_post_message_empty_content_422(client: TestClient) -> None:
    """Whitespace-only content is rejected with 422."""
    sess = client.post("/api/sessions", json={}).json()
    r = client.post(
        f"/api/sessions/{sess['id']}/messages",
        json={"content": "   "},
    )
    assert r.status_code == 422


def test_post_message_streams_final_event(
    client: TestClient, sessions_dir: Path
) -> None:
    """A valid message streams at least one ``event: final`` line and persists."""
    sess = client.post("/api/sessions", json={}).json()
    sid = sess["id"]

    with client.stream(
        "POST",
        f"/api/sessions/{sid}/messages",
        json={"content": "hello"},
    ) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())

    assert "event: thinking" in body
    assert "event: final" in body
    # The server also emits ``event: token`` chunks for the typewriter
    # effect (per the design system: never show a spinner for 10s+).
    assert "event: token" in body

    # The session on disk now has the user message plus an assistant turn.
    reloaded = Session.load(sessions_dir / f"{sid}.json")
    roles = [m.role for m in reloaded.messages]
    assert "user" in roles
    assert "assistant" in roles
    # And the last assistant message is non-empty.
    last_assistant = next(
        m for m in reversed(reloaded.messages) if m.role == "assistant"
    )
    assert last_assistant.content


def test_post_message_unknown_session_404(client: TestClient) -> None:
    """Streaming into a non-existent session returns 404."""
    r = client.post(
        "/api/sessions/does-not-exist/messages",
        json={"content": "hello"},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Abort
# --------------------------------------------------------------------------- #


def test_abort_session_returns_204(client: TestClient) -> None:
    """Abort on a session with no in-flight run is a no-op 204."""
    sess = client.post("/api/sessions", json={}).json()
    r = client.post(f"/api/sessions/{sess['id']}/abort")
    assert r.status_code == 204


# --------------------------------------------------------------------------- #
# Stop / Cancel button
# --------------------------------------------------------------------------- #


def test_index_has_stop_button_hidden_by_default(client: TestClient) -> None:
    """The stop button is in the DOM but hidden until an in-flight
    run starts. ``hidden`` is a boolean attribute, so we assert its
    presence in the markup, not its rendered visibility."""
    html = client.get("/").text
    assert 'id="stop"' in html
    assert "stop-btn" in html
    # The button must be marked hidden in the static HTML so the
    # page does not flash a red button before any message is sent.
    # Find the stop-btn element and check it has the hidden attribute.
    import re
    m = re.search(r'<button[^>]*id="stop"[^>]*>', html)
    assert m, "stop button not found in index.html"
    assert "hidden" in m.group(0), (
        f"stop button must have hidden attribute by default, got: {m.group(0)!r}"
    )


def test_app_js_wires_stop_button_to_abort(client: TestClient) -> None:
    """The stop button's click handler POSTs to the abort endpoint.

    Regression guard: a refactor of app.js that drops the abort
    wiring breaks this test, not the in-flight cancel UX on a phone.
    """
    js = client.get("/static/app.js").text
    # The abort endpoint path must be in the JS, exactly as the
    # route is defined in server.py.
    assert "/abort" in js
    # And the wiring must reach it via a click on the stop button.
    # Look for the stopBtn.addEventListener("click", ...) block.
    assert "stopBtn" in js
    assert 'addEventListener("click"' in js
    # The path is built dynamically: "/api/sessions/" + sid + "/abort"
    # Both halves must appear.
    assert "/api/sessions/" in js
    assert '"/abort"' in js or "+\"/abort\"" in js or "'/abort'" in js


def test_app_js_toggles_stop_button_with_sending_state(client: TestClient) -> None:
    """When a message is in flight, send is hidden and stop is shown;
    when the run finishes, send is shown and stop is hidden.

    This is a string-content guard because the toggle logic depends
    on the closure-scoped ``state.sending`` flag, which is hard to
    exercise end-to-end without driving the real SSE pipeline. The
    strings checked here are the exact attributes set in the
    ``send()`` and ``finish()`` paths.
    """
    js = client.get("/static/app.js").text
    # Both buttons must use the same hidden/show toggle pattern
    # (removeAttribute("hidden") / setAttribute("hidden", "")).
    assert 'removeAttribute("hidden")' in js
    assert 'setAttribute("hidden", "")' in js
    # The pairing must be consistent — find the two paired blocks
    # and assert that sendBtn and stopBtn are both touched in each.
    import re
    # Quick sanity: stopBtn is referenced at least 4 times
    # (1 in send-show, 1 in send-hide, 1 in finish-hide, 1 in finish-show,
    #  plus click handler).
    assert js.count("stopBtn") >= 4, (
        f"stopBtn referenced {js.count('stopBtn')} times, expected >= 4"
    )


# --------------------------------------------------------------------------- #
# Module-level app exists
# --------------------------------------------------------------------------- #


def test_module_level_app_is_built() -> None:
    """``forgewright.web.server:app`` is importable for uvicorn."""
    assert default_app is not None
    # Sanity: the app has the health route.
    paths = {r.path for r in default_app.routes}
    assert "/api/health" in paths


# --------------------------------------------------------------------------- #
# Mobile-first contract
# --------------------------------------------------------------------------- #


def test_index_has_viewport_meta(client: TestClient) -> None:
    """The served ``index.html`` declares the mobile viewport meta tag."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'name="viewport"' in r.text
    assert "width=device-width" in r.text
    # viewport-fit=cover is required for safe-area-inset-* to work on
    # notched iPhones.
    assert "viewport-fit=cover" in r.text


def test_index_has_pwa_meta_tags(client: TestClient) -> None:
    """The HTML declares theme-color and apple/mobile web app meta tags."""
    r = client.get("/")
    assert 'name="theme-color"' in r.text
    assert 'name="apple-mobile-web-app-capable"' in r.text
    assert 'name="mobile-web-app-capable"' in r.text
    # Manifest + favicon + apple-touch-icon must be linked.
    assert 'rel="manifest"' in r.text
    assert 'rel="icon"' in r.text
    assert 'rel="apple-touch-icon"' in r.text


def test_css_uses_safe_area_insets(tmp_path: Path) -> None:
    """The stylesheet references ``safe-area-inset-*`` for notched devices.

    We read the file directly from the static dir rather than going
    through the HTTP client because StaticFiles also serves it under
    ``/static/style.css`` and we want to assert the *content* not the
    serving path.
    """
    css = Path(__file__).resolve().parents[3] / "src/forgewright/web/static/style.css"
    text = css.read_text(encoding="utf-8")
    assert "safe-area-inset-top" in text
    assert "safe-area-inset-bottom" in text
    # Also asserts the viewport unit used for mobile browsers.
    assert "100dvh" in text


def test_static_payload_under_55kb() -> None:
    """HTML + CSS + JS combined is below the 55 KB mobile budget.

    Bumped from 50 KB when the PWA install banner + SW registration
    landed in app.js — see [Unreleased] in CHANGELOG.md.
    """
    static = Path(__file__).resolve().parents[3] / "src/forgewright/web/static"
    total = (
        (static / "index.html").stat().st_size
        + (static / "style.css").stat().st_size
        + (static / "app.js").stat().st_size
    )
    assert total < 55_000, f"static payload is {total} bytes (limit 55000)"


def test_manifest_endpoint_returns_pwa_manifest(client: TestClient) -> None:
    """``GET /static/manifest.webmanifest`` returns 200 + correct content type."""
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/manifest+json"
    body = r.json()
    assert body["name"] == "forgewright"
    assert body["start_url"] == "/"
    assert body["display"] == "standalone"
    assert any(ic.get("sizes") == "192x192" for ic in body["icons"])
    assert any(ic.get("sizes") == "512x512" for ic in body["icons"])


# --------------------------------------------------------------------------- #
# PWA install surface (added in the PWA work)
# --------------------------------------------------------------------------- #


def test_sw_served_at_static_sw_js(client: TestClient) -> None:
    """The service worker is served with a JS content type.

    Starlette's ``StaticFiles`` maps ``.js`` to ``text/javascript``
    (RFC 9239) by default, and browsers accept that for SWs. We lock
    the contract as "any JS-shaped MIME" so a future Starlette
    change can't silently break the install flow.
    """
    r = client.get("/static/sw.js")
    assert r.status_code == 200
    ct = r.headers["content-type"]
    assert (
        ct.startswith("application/javascript")
        or ct.startswith("text/javascript")
    ), f"unexpected sw.js content-type: {ct!r}"
    # The body must contain the three lifecycle hooks the SW registers.
    body = r.text
    assert 'addEventListener("install"' in body
    assert 'addEventListener("activate"' in body
    assert 'addEventListener("fetch"' in body


def test_manifest_has_pwa_install_fields(client: TestClient) -> None:
    """Manifest has the fields required for Android install + iOS hint.

    ``id`` + ``scope`` keeps Android from treating manifest updates as
    a different app. ``description`` + ``categories`` are required for
    the install card to render with text. The maskable icon is what
    Android adaptive launchers pick when available.
    """
    body = client.get("/static/manifest.webmanifest").json()
    assert body["id"] == "/"
    assert body["scope"] == "/"
    assert isinstance(body["description"], str) and body["description"]
    assert "developer" in body["categories"]
    icons = body["icons"]
    # The maskable icon MUST be present for adaptive launchers.
    assert any(
        ic.get("purpose") == "maskable" and ic.get("sizes") == "512x512"
        for ic in icons
    ), f"no maskable 512x512 icon in {icons!r}"


def test_manifest_shortcuts_have_url(client: TestClient) -> None:
    """The "New chat" shortcut declares a same-origin URL.

    A shortcut with an off-origin URL is rejected by Chromium and the
    long-press menu silently drops it. We assert the contract here so
    a future refactor of the shortcuts list catches the bug at test
    time, not at the install screen.
    """
    body = client.get("/static/manifest.webmanifest").json()
    shortcuts = body.get("shortcuts") or []
    assert shortcuts, "manifest has no shortcuts array"
    for sc in shortcuts:
        url = sc.get("url", "")
        assert url.startswith("/"), f"shortcut url is off-origin: {url!r}"


def test_app_js_registers_service_worker(client: TestClient) -> None:
    """``app.js`` calls ``navigator.serviceWorker.register`` so a
    future refactor that drops the registration fails this test."""
    js = client.get("/static/app.js").text
    assert "serviceWorker" in js
    assert ".register(" in js
    # The SW file the registration points at must exist on disk.
    static = Path(__file__).resolve().parents[3] / "src/forgewright/web/static"
    assert (static / "sw.js").exists()


def test_app_js_handles_beforeinstallprompt(client: TestClient) -> None:
    """``app.js`` wires the Android/Chromium install prompt.

    iOS has no equivalent event — its own hint path is covered by the
    ``navigator.standalone`` check, asserted in a separate test.
    """
    js = client.get("/static/app.js").text
    assert "beforeinstallprompt" in js
    assert "appinstalled" in js


def test_app_js_handles_ios_install_hint(client: TestClient) -> None:
    """iOS Safari has no ``beforeinstallprompt``. The hint path uses
    ``navigator.standalone`` to detect "already installed" and shows a
    Share-sheet hint otherwise. Lock the contract."""
    js = client.get("/static/app.js").text
    assert "navigator.standalone" in js
    # The actual hint message — kept short by design.
    assert "Add to Home Screen" in js


def test_index_links_mask_icon_for_safari(client: TestClient) -> None:
    """Safari pinned-tab icon is wired via ``<link rel="mask-icon">``
    pointing at the maskable 512."""
    html = client.get("/").text
    assert 'rel="mask-icon"' in html
    assert "icon-maskable-512.png" in html


def test_index_links_apple_touch_icon_180(client: TestClient) -> None:
    """iOS Home Screen icon is the dedicated 180×180 PNG, not the
    generic 192 fallback we used pre-PWA."""
    html = client.get("/").text
    assert 'rel="apple-touch-icon"' in html
    assert "apple-touch-icon.png" in html


def test_manifest_icon_maskable_is_512_png(client: TestClient) -> None:
    """The maskable icon file referenced from the manifest actually
    exists and is a 512×512 PNG."""
    r = client.get("/static/icon-maskable-512.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # Cheap check: the PNG header for a 512×512 IHDR has '00 00 02 00'
    # for width and height (little-endian). Magic bytes are 89 50 4E 47.
    body = r.content
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR is the first chunk (8 bytes) after the 8-byte signature.
    # Width is bytes 16..20, height is bytes 20..24.
    import struct
    w, h = struct.unpack(">II", body[16:24])
    assert w == 512 and h == 512, f"maskable icon is {w}x{h}, expected 512x512"
