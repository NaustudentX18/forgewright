"""Tests for the BrowserUseTool.

These tests never launch a real Chromium — the CI matrix does not have the
playwright browser binaries installed. We mock the page and the browser
context using :class:`unittest.mock.AsyncMock` and inject them into the
tool's private attributes; that covers the action handlers end-to-end.

The lazy import and the no-page-yet error path are also covered without
a real browser. An optional ``@pytest.mark.integration`` test is included
that actually navigates to ``https://example.com``; it is skipped in the
default test run.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from forgewright.schema import ToolResult
from forgewright.tool.browser import BrowserUseTool, _render_snapshot

# -- Module-level fixtures -------------------------------------------------


def _make_tool() -> BrowserUseTool:
    """Build a BrowserUseTool without launching a browser."""
    return BrowserUseTool(headless=True)


def _inject_mock_page(tool: BrowserUseTool) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    """Inject fake page + browser + context into ``tool`` and return them.

    Returns ``(page, browser, context)`` so individual tests can configure
    the specific return values they need.
    """
    page = AsyncMock(name="page")
    browser = AsyncMock(name="browser")
    context = AsyncMock(name="context")

    page.aria_snapshot = AsyncMock(
        return_value='- heading "Example Domain" [level=1] [ref=e1]'
    )

    # page.goto returns a response-like object with a `.status` attribute.
    response = MagicMock(name="response")
    response.status = 200
    page.goto = AsyncMock(return_value=response)
    page.title = AsyncMock(return_value="Example Domain")
    page.content = AsyncMock(return_value="<html><body>hi</body></html>")
    page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    page.click = AsyncMock(return_value=None)
    page.fill = AsyncMock(return_value=None)

    tool._page = page
    tool._browser = browser
    tool._context = context
    tool._playwright = MagicMock(name="playwright")
    return page, browser, context


# -- Schema & metadata -----------------------------------------------------


def test_metadata() -> None:
    tool = _make_tool()
    assert tool.name == "browser"
    assert "navigate" in tool.description
    assert tool.timeout_s == 60
    assert tool.returns_image is True


def test_action_enum() -> None:
    tool = _make_tool()
    actions = set(tool.args_schema["properties"]["action"]["enum"])
    assert actions == {
        "navigate",
        "click",
        "type",
        "screenshot",
        "extract",
        "get_title",
        "get_html",
        "close",
    }


def test_required_field() -> None:
    tool = _make_tool()
    assert tool.args_schema["required"] == ["action"]


def test_openai_spec() -> None:
    tool = _make_tool()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "browser"
    assert "navigate" in spec["function"]["parameters"]["properties"]["action"]["enum"]


def test_anthropic_spec() -> None:
    tool = _make_tool()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "browser"
    enum = spec["input_schema"]["properties"]["action"]["enum"]
    assert "screenshot" in enum


def test_headless_flag_is_remembered() -> None:
    tool = BrowserUseTool(headless=False)
    assert tool._headless is False  # type: ignore[attr-defined]


# -- Lazy import + state-machine errors ------------------------------------


@pytest.mark.asyncio
async def test_lazy_import_error_returns_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """If `playwright` is missing, the tool must return a clear error, not crash."""
    tool = _make_tool()
    # Remove the module from sys.modules so the `from playwright.async_api`
    # import inside `_ensure_browser` raises ImportError.
    monkeypatch.setitem(sys.modules, "playwright", None)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)  # type: ignore[arg-type]

    result = await tool(action="navigate", url="https://example.com")
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "playwright" in (result.error or "").lower()
    # The browser is never launched in this branch.
    assert tool._browser is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_title_without_navigate_returns_error() -> None:
    """Calling get_title before any navigate should not crash with AttributeError."""
    tool = _make_tool()
    result = await tool(action="get_title")
    assert result.is_error is True
    assert "navigate" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_click_without_navigate_returns_error() -> None:
    tool = _make_tool()
    result = await tool(action="click", selector="a.link")
    assert result.is_error is True
    assert "navigate" in (result.error or "").lower()


# -- Action handlers with a mocked page ------------------------------------


@pytest.mark.asyncio
async def test_navigate_calls_goto_and_returns_status() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)

    result = await tool(action="navigate", url="https://example.com")
    assert result.is_error is False
    assert "Navigated to https://example.com" in (result.output or "")
    assert "title='Example Domain'" in (result.output or "")
    assert "status=200" in (result.output or "")
    page.goto.assert_awaited_once()
    args, kwargs = page.goto.call_args
    assert args[0] == "https://example.com"
    assert kwargs.get("wait_until") == "domcontentloaded"
    assert kwargs.get("timeout") == 30_000


@pytest.mark.asyncio
async def test_navigate_missing_url_returns_error() -> None:
    tool = _make_tool()
    _inject_mock_page(tool)
    result = await tool(action="navigate", url=None)
    assert result.is_error is True
    assert "url" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_get_title_returns_page_title() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    result = await tool(action="get_title")
    assert result.is_error is False
    assert result.output == "Example Domain"
    page.title.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_calls_page_click_with_selector() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    result = await tool(action="click", selector="a.link")
    assert result.is_error is False
    assert "Clicked a.link" in (result.output or "")
    args, kwargs = page.click.call_args
    assert args[0] == "a.link"
    assert kwargs.get("timeout") == 10_000


@pytest.mark.asyncio
async def test_click_missing_selector_returns_error() -> None:
    tool = _make_tool()
    _inject_mock_page(tool)
    result = await tool(action="click", selector=None)
    assert result.is_error is True
    assert "selector" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_type_calls_page_fill() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    result = await tool(action="type", selector="#q", text="hello world")
    assert result.is_error is False
    assert "Typed 11 chars into #q" in (result.output or "")
    args, kwargs = page.fill.call_args
    assert args[0] == "#q"
    assert args[1] == "hello world"
    # We never use `kwargs` for `fill`, but assert its absence for clarity.
    assert "timeout" not in kwargs


@pytest.mark.asyncio
async def test_type_missing_text_returns_error() -> None:
    tool = _make_tool()
    _inject_mock_page(tool)
    result = await tool(action="type", selector="#q", text=None)
    assert result.is_error is True
    assert "text" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_screenshot_returns_base64_image() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    result = await tool(action="screenshot")
    assert result.is_error is False
    assert result.base64_image is not None
    # The base64 string should round-trip back to our fake bytes.
    assert base64.b64decode(result.base64_image) == b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    assert "19 bytes" in (result.output or "")

    # The screenshot must have been requested as JPEG with quality 70.
    _args, kwargs = page.screenshot.call_args
    assert kwargs.get("type") == "jpeg"
    assert kwargs.get("quality") == 70
    assert kwargs.get("full_page") is False  # default


@pytest.mark.asyncio
async def test_screenshot_full_page_propagates() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    result = await tool(action="screenshot", full_page=True)
    assert result.is_error is False
    kwargs = page.screenshot.call_args.kwargs
    assert kwargs.get("full_page") is True


@pytest.mark.asyncio
async def test_extract_uses_aria_snapshot() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    page.aria_snapshot = AsyncMock(
        return_value=(
            '- generic [ref=e2]:\n'
            '  - heading "Example Domain" [level=1] [ref=e3]\n'
            '  - link "Learn more" [ref=e6]'
        )
    )

    result = await tool(action="extract")
    assert result.is_error is False
    text = result.output or ""
    assert 'heading "Example Domain"' in text
    assert 'link "Learn more"' in text
    page.aria_snapshot.assert_awaited_once_with(mode="ai")
    page.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_extract_truncates_oversized_snapshot() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    page.aria_snapshot = AsyncMock(return_value="x" * 60_000)

    result = await tool(action="extract")
    assert result.is_error is False
    text = result.output or ""
    assert "[truncated]" in text
    assert len(text) < 60_000


@pytest.mark.asyncio
async def test_extract_legacy_accessibility_snapshot() -> None:
    """Older Playwright: JSON tree via accessibility.snapshot()."""

    class _LegacyPage:
        def __init__(self) -> None:
            accessibility = MagicMock(name="accessibility")
            accessibility.snapshot = MagicMock(
                return_value={
                    "name": "root",
                    "role": "WebArea",
                    "children": [
                        {"name": "Example Domain", "role": "heading", "children": []}
                    ],
                }
            )
            self.accessibility = accessibility

    tool = _make_tool()
    page = _LegacyPage()
    tool._page = page  # type: ignore[assignment]
    tool._browser = MagicMock(name="browser")
    tool._context = MagicMock(name="context")
    tool._playwright = MagicMock(name="playwright")

    result = await tool(action="extract")
    assert result.is_error is False
    text = result.output or ""
    assert "root: WebArea" in text
    assert "  Example Domain: heading" in text
    page.accessibility.snapshot.assert_called_once()


def test_render_snapshot_formats_tree() -> None:
    text = _render_snapshot(
        {
            "name": "root",
            "role": "WebArea",
            "children": [{"name": "Learn more", "role": "link", "children": []}],
        }
    )
    assert "root: WebArea" in text
    assert "  Learn more: link" in text


@pytest.mark.asyncio
async def test_get_html_returns_full_content() -> None:
    tool = _make_tool()
    _page, _, _ = _inject_mock_page(tool)
    result = await tool(action="get_html")
    assert result.is_error is False
    assert result.output == "<html><body>hi</body></html>"


@pytest.mark.asyncio
async def test_get_html_truncates_when_oversized() -> None:
    tool = _make_tool()
    page, _, _ = _inject_mock_page(tool)
    page.content = AsyncMock(return_value="y" * 1000)
    result = await tool(action="get_html", max_chars=100)
    assert result.is_error is False
    assert "[truncated]" in (result.output or "")
    assert (result.output or "").startswith("y" * 100)


# -- close() lifecycle -----------------------------------------------------


@pytest.mark.asyncio
async def test_close_shuts_down_browser_and_clears_state() -> None:
    tool = _make_tool()
    _, browser, _ = _inject_mock_page(tool)

    await tool.close()
    browser.close.assert_awaited_once()
    assert tool._browser is None  # type: ignore[attr-defined]
    assert tool._context is None  # type: ignore[attr-defined]
    assert tool._page is None  # type: ignore[attr-defined]
    assert tool._playwright is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    tool = _make_tool()
    _, browser, _ = _inject_mock_page(tool)
    await tool.close()
    # Second call must not raise even though everything is already None.
    await tool.close()
    # `browser.close` was still only called once.
    assert browser.close.await_count == 1


@pytest.mark.asyncio
async def test_close_via_action() -> None:
    """`action='close'` should route through `tool.close()` and return success."""
    tool = _make_tool()
    _, browser, _ = _inject_mock_page(tool)
    result = await tool(action="close")
    assert result.is_error is False
    assert result.output == "Browser closed"
    browser.close.assert_awaited_once()


# -- Optional live integration test ----------------------------------------
#
# Marked slow + integration so it never runs in the default `pytest -q`. Run
# it explicitly with:  uv run pytest -m integration tests/unit/tool/test_browser.py


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_browser_live_example_com() -> None:
    """Actually drive a real Chromium to example.com and grab the title.

    Skipped unless a Playwright-managed Chromium binary is on disk. The CI
    matrix does not run ``playwright install`` and would otherwise fail.
    Marked ``integration`` + ``slow`` so it can be selected explicitly with
    ``pytest -m integration`` when a real browser is available.
    """
    if not _has_playwright_chromium():
        pytest.skip("playwright chromium not installed; run `playwright install chromium`.")
    tool = BrowserUseTool(headless=True)
    try:
        nav = await tool(action="navigate", url="https://example.com")
        assert nav.is_error is False, nav.error
        title = await tool(action="get_title")
        assert title.is_error is False, title.error
        assert "Example" in (title.output or "")
    finally:
        await tool.close()


def _has_playwright_chromium() -> bool:
    """Return True if a Playwright-managed Chromium binary is on disk.

    We probe the actual files Playwright looks for at launch time, not just
    whether *some* chromium is on the system path — a stray ``/usr/bin/chromium``
    is not enough to run the bundled tool.
    """
    cache = Path.home() / ".cache" / "ms-playwright"
    if not cache.is_dir():
        return False
    for parent in cache.glob("chromium*"):
        # Newer playwright versions ship a separate "headless_shell" binary
        # for headless mode; older ones use the full "chrome" binary.
        if (parent / "chrome-linux" / "headless_shell").is_file():
            return True
        if (parent / "chrome-linux" / "chrome").is_file():
            return True
    return False


# -- Extra assertions: returns_image + class metadata ---------------------


def test_returns_image_classvar() -> None:
    """The tool advertises that it can return images (for the screenshot action)."""
    assert BrowserUseTool.returns_image is True


def test_module_all_exports_browser_use_tool() -> None:
    from forgewright.tool import BrowserUseTool as _Exported

    assert _Exported is BrowserUseTool
