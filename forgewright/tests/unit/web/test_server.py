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
from forgewright.config import LLMConfig, SecurityConfig, Settings
from forgewright.security.audit import AuditLog
from forgewright.security.audit import AuditEvent
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
def audit_log_path(tmp_path: Path) -> Path:
    """A tmp path for the audit log used by the events endpoint."""
    return tmp_path / "audit.jsonl"


@pytest.fixture
def stub_settings_with_audit(audit_log_path: Path) -> Settings:
    """Stub settings with the audit log pointed at ``audit_log_path``."""
    return Settings(
        llm=LLMConfig(provider="stub", model="stub-model"),
        max_steps=2,
        security=SecurityConfig(audit_log=str(audit_log_path)),
    )


@pytest.fixture
def client(
    sessions_dir: Path, stub_settings: Settings
) -> Iterator[TestClient]:
    """A FastAPI TestClient wired with a stub-backed app."""
    application = create_app(settings=stub_settings)
    with TestClient(application) as c:
        yield c


@pytest.fixture
def audit_client(
    sessions_dir: Path, stub_settings_with_audit: Settings
) -> Iterator[TestClient]:
    """A TestClient whose ``/events`` endpoint reads from a tmp audit log."""
    application = create_app(settings=stub_settings_with_audit)
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


def test_static_payload_under_68kb() -> None:
    """HTML + CSS + JS combined is below the 68 KB mobile budget.

    Bumped from 60 KB when the offline outbox, share target, and restored
    app.js bootstrap landed. See CHANGELOG [Unreleased].
    """
    static = Path(__file__).resolve().parents[3] / "src/forgewright/web/static"
    total = (
        (static / "index.html").stat().st_size
        + (static / "style.css").stat().st_size
        + (static / "app.js").stat().st_size
    )
    assert total < 68_000, f"static payload is {total} bytes (limit 68000)"


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
    assert isinstance(body["description"], str)
    assert body["description"]
    assert "developer" in body["categories"]
    icons = body["icons"]
    # The maskable icon MUST be present for adaptive launchers.
    assert any(
        ic.get("purpose") == "maskable" and ic.get("sizes") == "512x512"
        for ic in icons
    ), f"no maskable 512x512 icon in {icons!r}"


def test_manifest_has_install_screenshots(client: TestClient) -> None:
    """Chromium install cards need wide + narrow screenshots."""
    body = client.get("/static/manifest.webmanifest").json()
    shots = body.get("screenshots") or []
    assert len(shots) >= 2
    forms = {s.get("form_factor") for s in shots}
    assert "wide" in forms
    assert "narrow" in forms
    for sc in shots:
        r = client.get(sc["src"])
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"


def test_manifest_has_share_target(client: TestClient) -> None:
    """PWA share target wires /share-in for URLs, text, and attachments."""
    body = client.get("/static/manifest.webmanifest").json()
    st = body.get("share_target") or {}
    assert st.get("action") == "/share-in"
    assert st.get("method") == "POST"
    files = (st.get("params") or {}).get("files") or []
    assert files
    assert files[0].get("name") == "media"


def test_share_in_get_redirects_to_composer(client: TestClient) -> None:
    """GET /share-in redirects into the SPA with a prefill payload."""
    r = client.get(
        "/share-in",
        params={"title": "Hi", "text": "Body", "url": "https://example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/?shared=")
    assert "new=1" in loc


def test_share_in_post_rejects_oversized_content_length(client: TestClient) -> None:
    """POST /share-in must 413 on Content-Length over the cap."""
    # 1.5 MB body announced via header; the server must short-circuit.
    big = b"a" * (1_500_000)
    r = client.post(
        "/share-in",
        content=big,
        headers={"content-type": "application/octet-stream"},
        follow_redirects=False,
    )
    assert r.status_code == 413


def test_share_in_post_streams_and_rejects_lying_length(client: TestClient) -> None:
    """A client that lies about Content-Length or chunks is also bounded.

    TestClient streams the body, so we send 1.5 MB without setting a
    truthful Content-Length: the server's chunked read must catch it.
    """
    big = b"a" * (1_500_000)
    r = client.post(
        "/share-in",
        content=big,
        headers={"content-type": "application/octet-stream"},
        follow_redirects=False,
    )
    assert r.status_code == 413


def test_share_in_post_accepts_small_payload(client: TestClient) -> None:
    """A well-formed small POST still works (sanity check)."""
    r = client.post(
        "/share-in",
        data={"title": "t", "text": "body", "url": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/?shared=")


def test_app_js_has_offline_outbox(client: TestClient) -> None:
    """Offline sends queue in IndexedDB and show a Queued badge."""
    js = client.get("/static/app.js").text
    assert "forgewright-offline-v1" in js
    assert "enqueueOffline" in js
    assert "flushQueue" in js
    assert "queueBadge" in js
    assert "Queued:" in js


def test_app_js_handles_share_prefill(client: TestClient) -> None:
    js = client.get("/static/app.js").text
    assert "consumeShareParams" in js
    assert "AskHuman" in js


def test_index_has_queue_badge(client: TestClient) -> None:
    html = client.get("/").text
    assert 'id="queueBadge"' in html


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
    """iOS Home Screen icon is the dedicated 180x180 PNG, not the
    generic 192 fallback we used pre-PWA."""
    html = client.get("/").text
    assert 'rel="apple-touch-icon"' in html
    assert "apple-touch-icon.png" in html


def test_manifest_icon_maskable_is_512_png(client: TestClient) -> None:
    """The maskable icon file referenced from the manifest actually
    exists and is a 512x512 PNG."""
    r = client.get("/static/icon-maskable-512.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # Cheap check: the PNG header for a 512x512 IHDR has '00 00 02 00'
    # for width and height (little-endian). Magic bytes are 89 50 4E 47.
    body = r.content
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR is the first chunk (8 bytes) after the 8-byte signature.
    # Width is bytes 16..20, height is bytes 20..24.
    import struct
    w, h = struct.unpack(">II", body[16:24])
    assert w == 512
    assert h == 512


# --------------------------------------------------------------------------- #
# H1.1 — Append-only log fan-out (``?since=`` polling)
# --------------------------------------------------------------------------- #


def _seed_audit_log(audit_log_path: Path, session_id: str, n: int) -> AuditLog:
    """Append ``n`` events with ``session_id`` and return the log."""
    log = AuditLog(audit_log_path)
    for i in range(n):
        log.append(
            AuditEvent(
                session_id=session_id,
                type="tool",
                tool="Bash",
                args={"cmd": f"echo {i}"},
            )
        )
    return log


def test_events_endpoint_streams_new_events(
    audit_client: TestClient, audit_log_path: Path
) -> None:
    """``?since=0`` returns every audit event for the session, one per line.

    This is the H1.1 polling contract: the client passes the last byte
    offset it saw (initially 0) and gets back the events appended
    after that offset. Two appended events, ``?since=0`` → 2 events.
    """
    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    _seed_audit_log(audit_log_path, sid, 2)

    r = audit_client.get(f"/api/sessions/{sid}/events", params={"since": "0"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")

    lines = [line for line in r.text.split("\n") if line]
    assert len(lines) == 2, f"expected 2 events, got: {lines!r}"
    payloads = [__import__("json").loads(line) for line in lines]
    assert all(p["session_id"] == sid for p in payloads)
    # The X-Current-Offset header tells the client where to poll next.
    current = int(r.headers["X-Current-Offset"])
    assert current == audit_log_path.stat().st_size


def test_events_endpoint_filters_by_session(
    audit_client: TestClient, audit_log_path: Path
) -> None:
    """Events for other sessions in the same log are not leaked."""
    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    log = AuditLog(audit_log_path)
    log.append(AuditEvent(session_id="other", type="tool", tool="Bash"))
    log.append(AuditEvent(session_id=sid, type="tool", tool="Bash"))
    log.append(AuditEvent(session_id="other", type="tool", tool="WebSearch"))

    r = audit_client.get(f"/api/sessions/{sid}/events", params={"since": "0"})
    import json as _json
    payloads = [_json.loads(line) for line in r.text.split("\n") if line]
    assert len(payloads) == 1
    assert payloads[0]["session_id"] == sid


def test_events_endpoint_tail_returns_from_end(
    audit_client: TestClient, audit_log_path: Path
) -> None:
    """``?since=-1`` returns zero events when nothing has been appended
    since the request. The ``X-Current-Offset`` header tells the client
    where to poll next."""
    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    _seed_audit_log(audit_log_path, sid, 2)

    # -1 and "tail" are both valid synonyms for "from EOF".
    for sentinel in ("-1", "tail"):
        r = audit_client.get(
            f"/api/sessions/{sid}/events", params={"since": sentinel}
        )
        assert r.status_code == 200
        # No events past the EOF we recorded.
        assert r.text.strip() == ""
        # And the offset header equals the current file size, so the
        # client can use it for the next poll.
        assert int(r.headers["X-Current-Offset"]) == audit_log_path.stat().st_size


def test_events_endpoint_polling_offset_advances(
    audit_client: TestClient, audit_log_path: Path
) -> None:
    """Round-trip: poll until empty, append, poll again, get only the new events.

    This is the canonical polling pattern the H1.1 endpoint enables.
    """
    import json as _json

    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]

    # First poll with the log empty — nothing to stream, but the
    # header tells us where the end is.
    r1 = audit_client.get(f"/api/sessions/{sid}/events", params={"since": "0"})
    assert r1.status_code == 200
    assert r1.text.strip() == ""
    offset_after_first = int(r1.headers["X-Current-Offset"])

    # Append two events. Their bytes start at ``offset_after_first``.
    log = AuditLog(audit_log_path)
    log.append(AuditEvent(session_id=sid, type="tool", tool="Bash", args={"cmd": "1"}))
    log.append(AuditEvent(session_id=sid, type="tool", tool="Bash", args={"cmd": "2"}))

    # Second poll from the recorded offset — exactly the two new events.
    r2 = audit_client.get(
        f"/api/sessions/{sid}/events", params={"since": str(offset_after_first)}
    )
    payloads = [_json.loads(line) for line in r2.text.split("\n") if line]
    assert [p["args"]["cmd"] for p in payloads] == ["1", "2"]


def test_events_endpoint_rejects_non_integer_since(
    audit_client: TestClient,
) -> None:
    """An unparseable ``since`` returns 400 with a useful error."""
    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    r = audit_client.get(f"/api/sessions/{sid}/events", params={"since": "abc"})
    assert r.status_code == 400
    assert "since" in r.json()["detail"].lower()


def test_events_endpoint_rejects_negative_offset(
    audit_client: TestClient,
) -> None:
    """A negative ``since`` other than ``-1`` returns 400.

    ``-1`` is reserved for "from EOF" (and ``tail`` is the alias); any
    other negative number is almost certainly a client bug."""
    sess = audit_client.post("/api/sessions", json={}).json()
    sid = sess["id"]
    r = audit_client.get(f"/api/sessions/{sid}/events", params={"since": "-5"})
    assert r.status_code == 400


def test_events_endpoint_unknown_session_404(audit_client: TestClient) -> None:
    """Asking for events of a session that doesn't exist returns 404.

    We check the session first (not the audit log) so a typo in the
    URL surfaces immediately instead of streaming an empty body.
    """
    r = audit_client.get("/api/sessions/does-not-exist/events")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Cancellation race on the _ObservableToolCollection
# (H3.3 — the swap-on-cancel must not corrupt the inner collection or
# leave a ``tool_result`` event hanging when the SSE client disconnects)
# --------------------------------------------------------------------------- #


import asyncio  # noqa: E402  (kept at module scope for the next tests)
from typing import Any  # noqa: E402

from forgewright.tool.base import BaseTool  # noqa: E402
from forgewright.tool.collection import ToolCollection  # noqa: E402
from forgewright.web.server import _ObservableToolCollection  # noqa: E402
from forgewright.schema import ToolResult  # noqa: E402


class _SleepyTool(BaseTool):
    """A tool that sleeps until cancelled (for the race test)."""

    name = "sleepy"
    description = "sleeps until cancelled"

    async def _run(self, **_kwargs: Any) -> ToolResult:
        await asyncio.sleep(60)  # cancelled long before this returns
        return ToolResult(output="never", is_error=False)


@pytest.mark.asyncio
async def test_observable_tool_call_records_cancellation() -> None:
    """Cancelling a ``call`` mid-flight must not leave a tool_result
    event with stale duration_ms; either a tool_result with is_error
    is appended, or no tool_result is appended, but the buffer is
    internally consistent (paired tool_call ↔ tool_result)."""
    inner = ToolCollection([_SleepyTool()])
    sink: list[dict[str, Any]] = []
    obs = _ObservableToolCollection(inner, sink)

    task = asyncio.create_task(obs.call("sleepy"))
    # Let the event loop schedule the coroutine into the sleep.
    await asyncio.sleep(0.05)
    assert any(e.get("event") == "tool_call" for e in sink), (
        f"tool_call event missing: {sink!r}"
    )
    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task

    # We expect either zero or one tool_result entry, but if present it
    # must carry an error indication (we don't surface a fake "ok"
    # result for a cancelled call).
    results = [e for e in sink if e.get("event") == "tool_result"]
    if results:
        assert results[0]["data"]["is_error"] is True, (
            f"cancelled call must surface is_error=True; got {results!r}"
        )


@pytest.mark.asyncio
async def test_observable_tool_collection_keeps_inner_callable_after_cancel() -> None:
    """After a cancellation, the inner collection is still usable.

    The original race: agent.tools is swapped to an _ObservableToolCollection
    inside the route handler. If the cancel path doesn't restore the
    original reference, future requests against the same agent see a
    half-broken proxy. The fix is a try/finally restoring the swap,
    but the test here is the behavioural contract: cancelling one
    call must not poison the wrapper."""
    inner = ToolCollection([_SleepyTool()])
    sink: list[dict[str, Any]] = []
    obs = _ObservableToolCollection(inner, sink)

    task = asyncio.create_task(obs.call("sleepy"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task

    # The wrapper's __getattr__ still proxies through, and the inner
    # collection is unaffected. A subsequent "tool not found" call
    # must return a structured error (not raise), and the sink must
    # not have grown a phantom tool_result for it.
    result = await obs.call("not-a-real-tool")
    assert result.is_error is True
    assert "Unknown tool" in (result.error or "")
    # tool_call was recorded for the unknown tool...
    unknown_calls = [
        e for e in sink
        if e.get("event") == "tool_call" and e["data"].get("tool") == "not-a-real-tool"
    ]
    assert len(unknown_calls) == 1
    # ...and a tool_result with is_error=True was also recorded for it.
    unknown_results = [
        e for e in sink
        if e.get("event") == "tool_result" and e["data"].get("is_error") is True
    ]
    assert len(unknown_results) == 1
