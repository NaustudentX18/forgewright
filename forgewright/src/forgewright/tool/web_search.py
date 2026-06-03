"""WebSearchTool — chain of search engines (Google -> DuckDuckGo -> Baidu -> Bing)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["SearchResult", "WebSearchTool"]


# A plausible desktop User-Agent. Real UAs are not strictly required for the engines
# we target, but they help avoid the most aggressive blocks.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Per-request HTTP timeout. We *also* have the tool-level `timeout_s` watchdog in
# BaseTool, but a per-engine cap keeps a single slow engine from eating the budget.
_HTTP_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class SearchResult:
    """A single normalised search result."""

    title: str
    url: str
    snippet: str


def _trim(text: str, limit: int = 400) -> str:
    """Collapse whitespace and truncate to a reasonable snippet length."""
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _href_str(value: Any) -> str:
    """Coerce a BeautifulSoup attribute value (str | list[str] | None) to a flat str."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _format_results(results: list[SearchResult]) -> str:
    """Render a list of results as a numbered markdown block."""
    if not results:
        return ""
    parts: list[str] = []
    for idx, item in enumerate(results, start=1):
        parts.append(f"{idx}. **{item.title}**\n   URL: {item.url}\n   Snippet: {item.snippet}")
    return "\n\n".join(parts)


async def _fetch_html(url: str) -> str:
    """GET `url` with a realistic UA, return the response text. Raises on any error."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


# ---------------------------------------------------------------------------
# Engine parsers
# ---------------------------------------------------------------------------
# Each parser is intentionally defensive: search engines change their HTML
# constantly, and a strict parser would crash on the smallest tweak. The
# contract is "return what you can; never raise".


def _parse_duckduckgo_html(html_text: str, num_results: int) -> list[SearchResult]:
    """Parse the HTML DuckDuckGo returns from the `/html/` endpoint."""
    soup = BeautifulSoup(html_text, "lxml")
    results: list[SearchResult] = []

    # Modern structure: each result lives in a div with class containing "result".
    for container in soup.find_all("div", class_=lambda c: bool(c) and "result" in c.split()):
        # Title + URL: first anchor with an absolute http(s) href.
        link = container.find("a", href=lambda h: bool(h) and h.startswith("http"))
        if link is None:
            # Fallback: any anchor in the container.
            link = container.find("a", href=True)
        if link is None:
            continue

        href = _href_str(link.get("href", ""))
        # DuckDuckGo wraps outbound links in a redirect. Try to unwrap the `uddg=` param.
        if "uddg=" in href:
            try:
                query = parse_qs(urlparse(href).query)
                candidate = _href_str(query.get("uddg", [href])[0])
                if candidate.startswith("http"):
                    href = candidate
            except Exception:
                href = unquote(href)

        title = _trim(link.get_text(" ", strip=True))
        if not title:
            # Try an h2/h3 child of the link.
            heading = link.find(["h2", "h3"])
            if heading is not None:
                title = _trim(heading.get_text(" ", strip=True))
        if not title:
            continue

        # Snippet: the most likely candidate is a.result__snippet, else the
        # first <a class="result__snippet"> we can find anywhere in the block.
        snippet_node = container.find("a", class_=lambda c: bool(c) and "snippet" in c.split())
        if snippet_node is None:
            snippet_node = container.find("td", class_=lambda c: bool(c) and "snippet" in c.split())
        if snippet_node is None:
            # last-resort: any element whose class mentions "snippet"
            snippet_node = container.find(class_=lambda c: bool(c) and "snippet" in c.split())
        snippet = _trim(snippet_node.get_text(" ", strip=True)) if snippet_node else ""

        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= num_results:
            break

    return results


def _parse_google_html(html_text: str, num_results: int) -> list[SearchResult]:
    """Parse the HTML Google returns for `/search?q=...`."""
    soup = BeautifulSoup(html_text, "lxml")
    results: list[SearchResult] = []

    # Google's organic results live in <div class="g"> containers.
    for container in soup.find_all("div", class_="g"):
        heading = container.find(["h1", "h2", "h3"])
        link = container.find("a", href=lambda h: bool(h) and h.startswith("http"))
        if heading is None or link is None:
            continue

        title = _trim(heading.get_text(" ", strip=True))
        href = _href_str(link.get("href", ""))
        if not title or not href:
            continue

        # Snippet: first text-bearing <div> with a non-trivial length.
        snippet = ""
        for div in container.find_all("div"):
            text = _trim(div.get_text(" ", strip=True))
            if len(text) > 40 and text != title:
                snippet = text
                break

        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= num_results:
            break

    return results


def _parse_bing_html(html_text: str, num_results: int) -> list[SearchResult]:
    """Parse the HTML Bing returns for `/search?q=...`."""
    soup = BeautifulSoup(html_text, "lxml")
    results: list[SearchResult] = []

    for li in soup.find_all("li", class_="b_algo"):
        heading = li.find(["h1", "h2", "h3"])
        link = li.find("a", href=lambda h: bool(h) and h.startswith("http"))
        if heading is None or link is None:
            continue

        title = _trim(heading.get_text(" ", strip=True)) or _trim(link.get_text(" ", strip=True))
        href = _href_str(link.get("href", ""))
        if not title or not href:
            continue

        # Snippet: first <p> with substantive text.
        snippet = ""
        for p in li.find_all("p"):
            text = _trim(p.get_text(" ", strip=True))
            if text:
                snippet = text
                break

        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= num_results:
            break

    return results


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class WebSearchTool(BaseTool):
    """Web search via a chain of engines (Google -> DuckDuckGo -> Baidu -> Bing).

    Each engine is tried in `engines` order; the first non-empty list of
    results wins. If an engine raises or returns `[]`, we log and try the
    next one. With everything exhausted we return an error result.
    """

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the web via a chain of engines (Google -> DuckDuckGo -> Baidu -> Bing). "
        "Returns a list of {title, url, snippet} for the top N results."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    }
    timeout_s: ClassVar[int] = 30

    # Class-level engine chain. Tests can override this attribute to narrow
    # the chain, e.g. `WebSearchTool.engines = ["bing"]`.
    engines: ClassVar[list[str]] = ["google", "duckduckgo", "bing"]

    # ------------------------------------------------------------------ #
    # Public entry point                                                  #
    # ------------------------------------------------------------------ #

    async def _run(  # type: ignore[override]
        self,
        *,
        query: str,
        num_results: int = 5,
    ) -> ToolResult:
        """Try each engine in `self.engines`; first non-empty result wins."""
        if not query or not query.strip():
            return ToolResult(is_error=True, error="web_search: query must be a non-empty string")

        last_error: str | None = None
        for engine in self.engines:
            method = getattr(self, f"_search_{engine}", None)
            if method is None:
                logger.warning("web_search.unknown_engine engine={}", engine)
                continue

            try:
                results = await method(query, num_results)
            except Exception as exc:
                logger.warning(
                    "web_search.engine_error engine={} query={!r} err={}: {}",
                    engine,
                    query,
                    type(exc).__name__,
                    exc,
                )
                last_error = f"{engine}: {type(exc).__name__}: {exc}"
                continue

            if results:
                logger.info(
                    "web_search.ok engine={} query={!r} count={}",
                    engine,
                    query,
                    len(results),
                )
                return ToolResult(output=_format_results(results))

            logger.warning("web_search.empty engine={} query={!r}", engine, query)
            last_error = f"{engine}: no results"

        # All engines either raised or returned empty.
        if last_error is None:
            last_error = "no engines configured"
        return ToolResult(
            is_error=True,
            error=f"All search engines failed for query: {query!r} (last: {last_error})",
        )

    # ------------------------------------------------------------------ #
    # Engine implementations                                              #
    # ------------------------------------------------------------------ #
    # Each `_search_<engine>` returns a list[SearchResult] (possibly empty)
    # or raises. They are the seam tests monkeypatch.

    async def _search_duckduckgo(self, query: str, num_results: int) -> list[SearchResult]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        html_text = await _fetch_html(url)
        return _parse_duckduckgo_html(html_text, num_results)

    async def _search_google(self, query: str, num_results: int) -> list[SearchResult]:
        url = f"https://www.google.com/search?q={quote_plus(query)}&num={num_results}"
        try:
            html_text = await _fetch_html(url)
        except Exception:
            return []
        return _parse_google_html(html_text, num_results)

    async def _search_bing(self, query: str, num_results: int) -> list[SearchResult]:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count={num_results}"
        html_text = await _fetch_html(url)
        return _parse_bing_html(html_text, num_results)

    async def _search_baidu(self, query: str, num_results: int) -> list[SearchResult]:
        # Baidu's results page is JS-rendered. Parsing the static HTML gives
        # at most an empty or login interstitial. We still try once and let
        # the chain fall back; this method exists so a future contributor can
        # wire up a real source (e.g. the Baidu JSON API) without changing
        # the public surface.
        url = f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={num_results}"
        try:
            html_text = await _fetch_html(url)
        except Exception:
            return []
        soup = BeautifulSoup(html_text, "lxml")
        results: list[SearchResult] = []
        for container in soup.find_all("div", class_=lambda c: bool(c) and "result" in c.split()):
            link = container.find("a", href=lambda h: bool(h) and h.startswith("http"))
            heading = container.find(["h1", "h2", "h3"])
            if link is None or heading is None:
                continue
            results.append(
                SearchResult(
                    title=_trim(heading.get_text(" ", strip=True)),
                    url=_href_str(link.get("href", "")),
                    snippet=_trim(container.get_text(" ", strip=True)),
                )
            )
            if len(results) >= num_results:
                break
        # Treat the unparsed case (no matches) as an empty result so the
        # chain falls through to the next engine.
        return results
