"""BrowserUseTool — drive a headless Chromium via Playwright.

The tool owns a single :class:`BrowserContext` and a single :class:`Page`,
both created lazily on first use. ``playwright`` is imported inside
``_ensure_browser`` so the tool can be imported (and the rest of the project
can start) even when the optional ``[browser]`` extra is not installed; in
that case ``_run`` returns a clear error ``ToolResult`` rather than crashing.

All actions operate on the current page (the most recently navigated URL).
The browser instance persists across calls within one agent session; it is
the caller's responsibility to invoke :meth:`close` on cleanup (the agent
loop does this on ``FINISHED`` / ``ERROR`` / ``Ctrl+C``).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["BrowserUseTool"]


# Truncate large text payloads so a single tool call cannot blow up the
# model's context window.
_MAX_TEXT_CHARS = 50_000

# Viewport used when the BrowserContext is first created. 1280x800 is a
# common laptop size and avoids mobile-specific rendering paths.
_VIEWPORT: Any = {"width": 1280, "height": 800}

# A plausible desktop Chrome UA — helps avoid the most aggressive anti-bot
# blocks (we are not stealth-bypassing anything; this is a polite UA).
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Default per-call navigation timeout (ms) — overridden by BaseTool's outer
# `timeout_s` (60s for this tool) so the cap is generous.
_GOTO_TIMEOUT_MS = 30_000

# Per-action click timeout (ms) — clicks on a missing element should fail
# fast and bubble up an error, not hang for 30s.
_CLICK_TIMEOUT_MS = 10_000

# Screenshot encoding/quality — JPEG is much smaller than PNG and the
# quality loss is invisible at 70 for the agent's purposes.
_SCREENSHOT_TYPE: Literal["jpeg"] = "jpeg"
_SCREENSHOT_QUALITY = 70


class BrowserUseTool(BaseTool):
    """Drive a headless Chromium browser via the Playwright async API.

    The supported actions are: ``navigate``, ``click``, ``type``,
    ``screenshot``, ``extract`` (readability-style accessibility snapshot),
    ``get_title``, ``get_html``, and ``close``.
    """

    name: ClassVar[str] = "browser"
    description: ClassVar[str] = (
        "Drive a headless Chromium browser. Actions: navigate, click, type, "
        "screenshot, extract (readability snapshot), get_title, get_html, close."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "navigate",
                    "click",
                    "type",
                    "screenshot",
                    "extract",
                    "get_title",
                    "get_html",
                    "close",
                ],
            },
            "url": {
                "type": ["string", "null"],
                "description": "URL for action='navigate'.",
            },
            "selector": {
                "type": ["string", "null"],
                "description": "CSS selector for click/type.",
            },
            "text": {
                "type": ["string", "null"],
                "description": "Text to type for action='type'.",
            },
            "full_page": {
                "type": "boolean",
                "default": False,
                "description": "For screenshot: capture the full scrollable page.",
            },
            "max_chars": {
                "type": "integer",
                "default": 50_000,
                "description": "For get_html: truncate at this many characters.",
            },
        },
        "required": ["action"],
    }
    timeout_s: ClassVar[int] = 60  # navigation can be slow
    returns_image: ClassVar[bool] = True  # screenshot action carries base64 image

    def __init__(self, headless: bool = True) -> None:
        """Set up the tool with a deferred browser launch."""
        super().__init__()
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def _run(  # type: ignore[override]
        self,
        *,
        action: str,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        full_page: bool = False,
        max_chars: int = 50_000,
    ) -> ToolResult:
        """Dispatch a single browser action. See ``args_schema`` for the inputs."""
        try:
            if action == "navigate":
                return await self._action_navigate(url=url)
            if action == "click":
                return await self._action_click(selector=selector)
            if action == "type":
                return await self._action_type(selector=selector, text=text)
            if action == "screenshot":
                return await self._action_screenshot(full_page=full_page)
            if action == "extract":
                return await self._action_extract()
            if action == "get_title":
                return await self._action_get_title()
            if action == "get_html":
                return await self._action_get_html(max_chars=max_chars)
            if action == "close":
                await self.close()
                return ToolResult(output="Browser closed")
        except RuntimeError as exc:
            # Surfaced by `_ensure_browser` when playwright is missing or
            # the browser fails to launch. `BaseTool.__call__` would also
            # catch this; we intercept here so the message stays tidy.
            logger.warning("browser.runtime_error action={} err={}", action, exc)
            return ToolResult(is_error=True, error=str(exc))
        except Exception:
            # The base class wraps unexpected exceptions in a ToolResult, but
            # we re-raise so it can attach the call count + stack info.
            logger.exception("browser.error action={}", action)
            raise

        # Defensive: the JSON schema's enum should have rejected this already.
        return ToolResult(is_error=True, error=f"Unknown action: {action!r}")

    # -- Internal: ensure a live browser ----------------------------------

    async def _ensure_browser(self) -> Page:
        """Lazily launch the browser and create a context + page on first use."""
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright not installed. Install with: uv pip install 'forgewright[browser]' "
                "and run: playwright install chromium"
            ) from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport=_VIEWPORT,
            user_agent=_USER_AGENT,
        )
        self._page = await self._context.new_page()
        logger.info("browser.launched headless={}", self._headless)
        return self._page

    # -- Internal: per-action handlers ------------------------------------

    async def _require_page(self) -> Page:
        """Return the current page or raise a clear error.

        The JSON schema can't tell us whether the user has called
        ``navigate`` yet, so we surface a friendly message at the tool
        boundary instead of letting ``AttributeError`` escape.
        """
        if self._page is None:
            raise RuntimeError("No page is open yet. Call action='navigate' with a URL first.")
        return self._page

    async def _action_navigate(self, *, url: str | None) -> ToolResult:
        """Open a URL. Reuses the existing page if one is already open."""
        if not url:
            return ToolResult(is_error=True, error="action='navigate' requires a 'url' argument.")
        page = await self._ensure_browser()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
        title = await page.title()
        status = response.status if response is not None else 0
        return ToolResult(output=f"Navigated to {url} (title='{title}', status={status})")

    async def _action_click(self, *, selector: str | None) -> ToolResult:
        """Click a single element matched by CSS selector."""
        if not selector:
            return ToolResult(is_error=True, error="action='click' requires a 'selector' argument.")
        page = await self._require_page()
        await page.click(selector, timeout=_CLICK_TIMEOUT_MS)
        return ToolResult(output=f"Clicked {selector}")

    async def _action_type(self, *, selector: str | None, text: str | None) -> ToolResult:
        """Fill an input. ``page.fill`` replaces any existing value."""
        if not selector:
            return ToolResult(is_error=True, error="action='type' requires a 'selector' argument.")
        if text is None:
            return ToolResult(is_error=True, error="action='type' requires a 'text' argument.")
        page = await self._require_page()
        await page.fill(selector, text)
        return ToolResult(output=f"Typed {len(text)} chars into {selector}")

    async def _action_screenshot(self, *, full_page: bool) -> ToolResult:
        """Take a JPEG screenshot; return its base64 form for the multimodal path."""
        page = await self._require_page()
        image_bytes = await page.screenshot(
            full_page=full_page, type=_SCREENSHOT_TYPE, quality=_SCREENSHOT_QUALITY
        )
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return ToolResult(
            output=f"Screenshot taken ({len(image_bytes)} bytes)",
            base64_image=b64,
        )

    async def _action_extract(self) -> ToolResult:
        """Return a compact accessibility snapshot of the current page.

        Uses Playwright's aria snapshot (``page.aria_snapshot``) instead of
        scraping ``document.body.innerText``, which misses structure and blows
        up token use on JS-heavy sites. Older Playwright builds fall back to
        the deprecated ``page.accessibility.snapshot()`` JSON tree.
        """
        page = await self._require_page()
        text = await _extract_page_text(page)
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "\n... [truncated]"
        return ToolResult(output=text)

    async def _action_get_title(self) -> ToolResult:
        """Return the current page's ``<title>``."""
        page = await self._require_page()
        return ToolResult(output=await page.title())

    async def _action_get_html(self, *, max_chars: int) -> ToolResult:
        """Return the current page's full HTML, optionally truncated."""
        page = await self._require_page()
        html = await page.content()
        if len(html) > max_chars:
            html = html[:max_chars] + "\n... [truncated]"
        return ToolResult(output=html)

    # -- Lifecycle --------------------------------------------------------

    async def close(self) -> None:
        """Close the browser and clear all internal state. Idempotent."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning("browser.close_failed err={}", exc)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.warning("browser.playwright_stop_failed err={}", exc)
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        logger.info("browser.closed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _extract_page_text(page: Any) -> str:
    """Return LLM-readable page text from Playwright's accessibility APIs."""
    aria_snapshot = getattr(page, "aria_snapshot", None)
    if callable(aria_snapshot):
        # Playwright 1.49+: `accessibility.snapshot()` was removed in favor of
        # YAML-like aria snapshots. `mode="ai"` includes element refs for tools.
        return cast(str, await page.aria_snapshot(mode="ai"))

    accessibility = getattr(page, "accessibility", None)
    if accessibility is None:
        raise RuntimeError(
            "Playwright page exposes neither aria_snapshot nor accessibility.snapshot"
        )
    snapshot_fn = accessibility.snapshot
    snapshot_obj = snapshot_fn()
    if hasattr(snapshot_obj, "__await__"):
        snapshot_obj = await snapshot_obj
    return _render_snapshot(snapshot_obj or {})


def _render_snapshot(node: Any, depth: int = 0) -> str:
    """Render a Playwright accessibility node tree as compact indented text.

    One node per line. Indentation is 2 spaces per level. The format is
    ``name: role [value]`` — ``value`` is only shown when it's not empty.
    Designed to be pasted into a model prompt: short, structured, and
    free of the visual noise Playwright's raw JSON includes.
    """
    lines: list[str] = []
    _walk(node, depth, lines)
    return "\n".join(lines)


def _walk(node: Any, depth: int, lines: list[str]) -> None:
    """Recursively flatten the accessibility tree into ``lines``."""
    if not isinstance(node, dict):
        return
    name = str(node.get("name") or "").strip()
    role = str(node.get("role") or "").strip()
    value = node.get("value")
    indent = "  " * depth
    if name or role:
        if value is not None and str(value).strip():
            lines.append(f"{indent}{name}: {role} [{value}]")
        else:
            lines.append(f"{indent}{name}: {role}")
    for child in node.get("children", []) or []:
        _walk(child, depth + 1, lines)


# Type-check-only imports keep the runtime `from playwright.async_api`
# out of the module-level import graph so projects without the extra
# installed can still import the rest of forgewright.
if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright
