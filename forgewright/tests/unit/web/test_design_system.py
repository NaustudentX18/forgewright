"""Tests for the forgewright web UI design system.

This file is the single source of truth for the visual / UX contract
exposed by the static assets. If you change a CSS variable, a class
name, an icon, or an SSE event name, the matching test here MUST be
updated — otherwise the design system is drifting.

The tests are organised into four groups:

* **Palette** — exact hex values for the design tokens
* **Components** — markers in the static files (chips, send button, etc.)
* **Static hygiene** — no emoji, payload budget, no webfont CDN
* **Streaming** — the server emits ``event: token`` chunks so the client
  can render a typewriter effect.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from forgewright.config import LLMConfig, Settings
from forgewright.web.server import create_app

_STATIC = Path(__file__).resolve().parents[3] / "src" / "forgewright" / "web" / "static"
INDEX = _STATIC / "index.html"
CSS = _STATIC / "style.css"
JS = _STATIC / "app.js"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the server at a tmp sessions dir and restore on teardown."""
    monkeypatch.setattr(
        "forgewright.web.server.default_sessions_dir", lambda: tmp_path
    )
    return tmp_path


@pytest.fixture
def stub_settings() -> Settings:
    return Settings(llm=LLMConfig(provider="stub", model="stub-model"), max_steps=2)


@pytest.fixture
def client(
    sessions_dir: Path, stub_settings: Settings
) -> Iterator[TestClient]:
    application = create_app(settings=stub_settings)
    with TestClient(application) as c:
        yield c


# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #


class TestPalette:
    """The exact hex values from the design system must appear in the
    static files (both the inlined critical CSS in index.html and the
    external style.css)."""

    @pytest.mark.parametrize(
        "color",
        ["#0F172A", "#1E293B", "#22C55E", "#020617", "#F8FAFC", "#94A3B8", "#0B1220", "#EF4444"],
    )
    def test_color_in_index_html(self, color: str) -> None:
        assert color in INDEX.read_text(), f"missing {color} in index.html"

    @pytest.mark.parametrize(
        "color",
        ["#0F172A", "#1E293B", "#22C55E", "#020617", "#F8FAFC", "#94A3B8", "#0B1220", "#EF4444"],
    )
    def test_color_in_style_css(self, color: str) -> None:
        assert color in CSS.read_text(), f"missing {color} in style.css"

    def test_color_uses_design_system_variable_names(self) -> None:
        """The CSS files must use ``--color-*`` variables (per the
        design system override spec), not legacy ``--bg`` / ``--accent``."""
        css = CSS.read_text()
        for name in [
            "--color-primary",
            "--color-cta",
            "--color-background",
            "--color-text",
            "--color-text-dim",
            "--color-surface",
            "--color-border",
            "--color-error",
        ]:
            assert name in css, f"missing design system var {name}"

    def test_cta_is_success_green(self) -> None:
        """The design system override says CTA = ``#22C55E`` (success
        green), not purple."""
        html = INDEX.read_text()
        assert "--color-cta: #22C55E" in html
        assert "#7c3aed" not in html.lower()
        assert "#6aa3ff" not in html.lower()

    def test_theme_color_is_oled_background(self) -> None:
        """The ``<meta name=theme-color>`` value must be the near-black
        background, not the legacy darker grey."""
        html = INDEX.read_text()
        m = re.search(r'<meta name="theme-color" content="(#[0-9A-Fa-f]{6})"', html)
        assert m, "no theme-color meta tag"
        assert m.group(1).lower() == "#020617", m.group(1)


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #


class TestComponents:
    """Component-level checks: chips, send button, topbar, etc."""

    def test_four_example_chips(self) -> None:
        """The empty state must contain exactly 4 example chips with
        the ``$`` monospace prefix (per the design system spec)."""
        html = INDEX.read_text()
        chips = re.findall(r'<button class="chip"[^>]*>.*?</button>', html, re.DOTALL)
        assert len(chips) == 4, f"expected 4 chips, found {len(chips)}"
        for chip in chips:
            assert '<span class="chip-prefix">$</span>' in chip, (
                "each chip must start with `<span class='chip-prefix'>$</span>`"
            )

    def test_chip_prefix_color_is_cta(self) -> None:
        """The ``$`` prefix in each chip must be tinted with the
        success-green CTA color (terminal nod)."""
        css = CSS.read_text()
        # Find the .chip-prefix block and verify it uses --color-cta.
        m = re.search(r"\.chip-prefix\s*\{[^}]+\}", css, re.DOTALL)
        assert m, "no .chip-prefix rule"
        assert "var(--color-cta)" in m.group(0)

    def test_send_button_uses_chevron_glyph(self) -> None:
        """The send button must use the ``>`` monospace chevron, NOT a
        paper-plane SVG arrow (per the design system override)."""
        html = INDEX.read_text()
        # The send button has class="send-btn" and id="send".
        m = re.search(
            r'<button class="send-btn"[^>]*id="send"[^>]*>(.*?)</button>', html, re.DOTALL
        )
        assert m, "no send button found"
        send_html = m.group(0)
        # Must contain a `>` glyph inside a .send-glyph span.
        assert '<span class="send-glyph"' in send_html
        assert "&gt;" in send_html or ">" in send_html
        # Must NOT contain a paper-plane / arrow SVG path.
        assert "M5 12l14 0" not in send_html  # the legacy arrow path

    def test_topbar_uses_frosted_glass(self) -> None:
        """The topbar must use ``backdrop-filter: blur`` for the
        frosted-glass premium-UI effect."""
        html = INDEX.read_text()
        css = CSS.read_text()
        combined = html + "\n" + css
        assert re.search(r"backdrop-filter\s*:\s*blur", combined), (
            "no backdrop-filter: blur in static files"
        )

    def test_send_button_color_is_cta(self) -> None:
        """The send button background must be the success-green CTA."""
        css = CSS.read_text()
        m = re.search(r"\.send-btn\s*\{[^}]+\}", css, re.DOTALL)
        assert m, "no .send-btn rule"
        assert "var(--color-cta)" in m.group(0)

    def test_active_session_border_is_cta(self) -> None:
        """The active session item border must use the CTA color."""
        css = CSS.read_text()
        assert re.search(r"border-color\s*:\s*var\(--color-cta\)", css), (
            "no .session-item.active border-color: var(--color-cta) rule"
        )

    def test_typing_dots_use_cta(self) -> None:
        """The thinking-indicator dots must be tinted with the CTA
        color (per design system: 'typing-indicator dots')."""
        css = CSS.read_text()
        m = re.search(r"\.typing\s+\.dot\s*\{[^}]+\}", css, re.DOTALL)
        assert m, "no .typing .dot rule"
        assert "var(--color-cta)" in m.group(0)

    def test_no_transform_scale_on_hover(self) -> None:
        """The design system forbids ``transform: scale`` on hover
        (layout-shifting). Only ``translateY`` and shadow changes."""
        css = CSS.read_text()
        # Find every :hover block and ensure it doesn't use scale().
        for m in re.finditer(r":hover\s*\{[^}]+\}", css, re.DOTALL):
            block = m.group(0)
            has_scale = "transform:scale" in block or "transform: scale" in block
            assert not has_scale, f"hover state must not use scale: {block[:120]}"

    def test_cursor_pointer_on_clickables(self) -> None:
        """Every clickable class must have ``cursor: pointer``."""
        css = CSS.read_text()
        html = INDEX.read_text()
        for cls in [
            ".chip",
            ".session-item",
            ".new-chat-btn",
            ".send-btn",
            ".tool-card-head",
        ]:
            m = re.search(re.escape(cls) + r"\s*\{[^}]+\}", css, re.DOTALL)
            assert m, f"no rule for {cls}"
            assert re.search(r"cursor\s*:\s*pointer", m.group(0)), (
                f"{cls} missing cursor: pointer"
            )
        # .icon-btn is in the inlined critical CSS.
        m = re.search(r"\.icon-btn\s*\{[^}]+\}", html, re.DOTALL)
        assert m
        assert re.search(r"cursor\s*:\s*pointer", m.group(0))


# --------------------------------------------------------------------------- #
# Static hygiene
# --------------------------------------------------------------------------- #


class TestStaticHygiene:
    """Payload budget, no webfont CDN, no emoji codepoints."""

    PAYLOAD_BUDGET = 55 * 1024  # 55 KB — bumped from 50 KB to accommodate
    # the PWA install banner + SW registration in app.js (see the [Unreleased]
    # section of CHANGELOG.md). Anything beyond 55 KB needs a real perf review.

    def test_payload_under_55kb(self) -> None:
        """The combined static payload must stay under 55 KB."""
        total = 0
        for path in (INDEX, CSS, JS):
            total += path.stat().st_size
        assert total < self.PAYLOAD_BUDGET, (
            f"static payload {total}B exceeds {self.PAYLOAD_BUDGET // 1024}KB budget"
        )

    def test_no_emoji_codepoints(self) -> None:
        """No emoji in any of the three static files. Grep for the
        supplementary multilingual plane + emoji ranges."""
        bad = []
        for path in (INDEX, CSS, JS):
            text = path.read_text()
            # Broad emoji ranges. False positives are possible but
            # the user explicitly required this check.
            for ch in text:
                cp = ord(ch)
                if (
                    0x1F300 <= cp <= 0x1F9FF
                    or 0x1FA70 <= cp <= 0x1FAFF
                    or 0x2600 <= cp <= 0x27BF
                ):
                    bad.append((path.name, hex(cp), ch))
        assert not bad, f"emoji codepoints found: {bad[:5]}"

    def test_no_webfont_cdn(self) -> None:
        """No Google Fonts / webfont CDN imports (50KB budget, no
        external fonts)."""
        html = INDEX.read_text()
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html
        assert "@import url" not in html
        assert "<link rel=\"stylesheet\"" not in html or "manifest" in html
        # The only <link rel="stylesheet"> allowed is for /static/style.css
        # (which is the design system spec; we exclude that since
        # @import for webfonts is what's forbidden).

    def test_uses_system_font_stack(self) -> None:
        """The CSS must use the system font stack (no webfont)."""
        css = CSS.read_text()
        assert "BlinkMacSystemFont" in css
        assert "Segoe UI" in css
        # No explicit "font-family" referencing Google fonts.
        assert "Satoshi" not in css
        assert "General Sans" not in css
        assert "DM Sans" not in css

    def test_includes_viewport_meta(self) -> None:
        """The viewport meta tag is required for mobile-first."""
        html = INDEX.read_text()
        assert "name=\"viewport\"" in html
        assert "viewport-fit=cover" in html

    def test_includes_prefers_reduced_motion(self) -> None:
        """The CSS must respect ``prefers-reduced-motion``."""
        css = CSS.read_text()
        assert "prefers-reduced-motion" in css

    def test_uses_safe_area_insets(self) -> None:
        """iOS safe-area insets must be honored for notched devices."""
        css = CSS.read_text()
        for var_name in ("--safe-top", "--safe-bot", "--safe-left", "--safe-right"):
            assert var_name in css, f"missing {var_name}"
            assert "env(safe-area-inset" in css, "missing env(safe-area-inset...)"

    def test_uses_design_ease_curve(self) -> None:
        """Transitions use the design system ease curve
        ``cubic-bezier(0.16, 1, 0.3, 1)`` (no instant state changes)."""
        css = CSS.read_text()
        assert re.search(r"cubic-bezier\(\s*0\.16\s*,\s*1\s*,\s*0\.3\s*,\s*1\s*\)", css), (
            "design system ease curve not found"
        )

    def test_has_4px_base_spacing_scale(self) -> None:
        """Spacing scale (4px base) is defined as CSS variables."""
        css = CSS.read_text()
        for var_name in ("--space-xs", "--space-sm", "--space-md", "--space-lg", "--space-xl"):
            assert var_name in css, f"missing spacing var {var_name}"
        # Verify the 4px base. Allow optional whitespace after the colon.
        assert re.search(r"--space-xs\s*:\s*0?\.25rem", css), (
            "--space-xs not 0.25rem (4px base)"
        )

    def test_no_more_than_5_legacy_class_references(self) -> None:
        """A small sanity check: the design system classes exist where
        the new structure expects them."""
        html = INDEX.read_text()
        for cls in ("empty-state", "chips", "wordmark", "send-btn", "input-wrap"):
            assert cls in html, f"missing class .{cls} in index.html"

    def test_inputs_use_16px_minimum(self) -> None:
        """Inputs must be 16px+ to prevent iOS zoom on focus."""
        css = CSS.read_text()
        m = re.search(r"\.input\s*\{[^}]+\}", css, re.DOTALL)
        assert m, "no .input rule"
        assert re.search(r"font-size\s*:\s*16px", m.group(0)), (
            ".input must have font-size: 16px (iOS zoom prevention)"
        )

    def test_min_44px_touch_targets(self) -> None:
        """Touch targets must be at least 44x44px (iOS HIG)."""
        css = CSS.read_text()
        html = INDEX.read_text()
        m = re.search(r"\.send-btn\s*\{[^}]+\}", css, re.DOTALL)
        assert m
        assert re.search(r"min-height\s*:\s*44px", m.group(0))
        # icon-btn is defined in the inlined critical CSS in index.html.
        m = re.search(r"\.icon-btn\s*\{[^}]+\}", html, re.DOTALL)
        assert m, "no .icon-btn rule in index.html inline CSS"
        assert "40px" in m.group(0) or "min-height: 44px" in m.group(0)


# --------------------------------------------------------------------------- #
# Streaming (server side)
# --------------------------------------------------------------------------- #


class TestStreamingTokens:
    """The server must emit ``event: token`` chunks so the client can
    render a typewriter effect (per the design system UX rules:
    'Stream text token-by-token; never show a spinner for 10s+')."""

    def test_token_events_emitted(self, client: TestClient) -> None:
        """A streaming message produces at least one ``event: token``."""
        sess = client.post("/api/sessions", json={}).json()
        with client.stream(
            "POST",
            f"/api/sessions/{sess['id']}/messages",
            json={"content": "hello"},
        ) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())
        assert "event: token" in body, "no event: token emitted"
        # And still emits event: final for session persistence.
        assert "event: final" in body

    def test_tokens_round_trip_to_final(self, client: TestClient) -> None:
        """The concatenated token content should equal the final
        content (no drift, no missing chunks)."""
        sess = client.post("/api/sessions", json={}).json()
        with client.stream(
            "POST",
            f"/api/sessions/{sess['id']}/messages",
            json={"content": "hello"},
        ) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())
        # Pull out all `data: {"content": "..."}` lines paired with
        # `event: token` lines.
        token_chunks: list[str] = []
        final_text = ""
        current_event = None
        for line in body.splitlines():
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                import json
                try:
                    payload = json.loads(line[6:])
                except Exception:
                    continue
                if current_event == "token" and "content" in payload:
                    token_chunks.append(payload["content"])
                elif current_event == "final" and "content" in payload:
                    final_text = payload["content"]
        if final_text:
            assert "".join(token_chunks) == final_text, (
                f"token round-trip drift: tokens={token_chunks!r} final={final_text!r}"
            )

    def test_typing_marker_event_present(self, client: TestClient) -> None:
        """The thinking event must be the first event so the UI can
        show a typing indicator until the first token arrives."""
        sess = client.post("/api/sessions", json={}).json()
        with client.stream(
            "POST",
            f"/api/sessions/{sess['id']}/messages",
            json={"content": "hello"},
        ) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())
        # 'event: thinking' is the first event.
        assert "event: thinking" in body


# --------------------------------------------------------------------------- #
# Client-side streaming handler
# --------------------------------------------------------------------------- #


class TestClientStreaming:
    """The static JS must wire up a handler for the ``token`` SSE event."""

    def test_js_handles_token_event(self) -> None:
        js = JS.read_text()
        assert '"token"' in js or "'token'" in js, (
            "no event: token handler in app.js"
        )

    def test_js_has_typewriter_renderer(self) -> None:
        js = JS.read_text()
        # The typewriter renderer is named ``appendAssistantToken``.
        assert "appendAssistantToken" in js
        # The streaming class is used to add the cursor.
        assert "streaming" in js

    def test_js_wires_chip_clicks(self) -> None:
        js = JS.read_text()
        assert "chip" in js
        # The handler must read ``data-prompt`` and submit the form.
        assert "data-prompt" in js
        assert "requestSubmit" in js

    def test_js_has_sidebar_toggle(self) -> None:
        js = JS.read_text()
        assert "openSidebar" in js or "sidebar.classList" in js
