"""Tests for WebSearchTool — all engine calls are monkeypatched, no network."""

from __future__ import annotations

import pytest
from forgewright.tool.web_search import SearchResult, WebSearchTool

# --------------------------------------------------------------------------- #
# Test fakes                                                                   #
# --------------------------------------------------------------------------- #


def _result(title: str = "T", url: str = "https://x.com", snippet: str = "S") -> SearchResult:
    """Build a SearchResult with sensible defaults."""
    return SearchResult(title=title, url=url, snippet=snippet)


def _make_results(n: int) -> list[SearchResult]:
    """Build a deterministic list of `n` fake results."""
    return [
        SearchResult(title=f"Title {i}", url=f"https://example.com/{i}", snippet=f"Snippet {i}")
        for i in range(n)
    ]


# A shared `engines` chain for tests that don't care about ordering.
_DEFAULT_ENGINES = ["google", "duckduckgo", "bing"]


async def _run_with_first_engine(
    tool: WebSearchTool,
    results: list[SearchResult],
    engines: list[str],
    *,
    query: str = "hi",
) -> str:
    """Run `_run` with the first engine returning `results`; return `output`."""
    first = engines[0]

    async def fake(_query: str, _num: int) -> list[SearchResult]:
        return results

    setattr(tool, f"_search_{first}", fake)
    tool.engines = engines
    res = await tool(query=query, num_results=max(len(results), 1))
    return res.output


# --------------------------------------------------------------------------- #
# Metadata / schema                                                            #
# --------------------------------------------------------------------------- #


def test_metadata() -> None:
    """The tool's name, timeout, and required args match the spec."""
    tool = WebSearchTool()
    assert tool.name == "web_search"
    assert tool.timeout_s == 30
    assert "query" in tool.args_schema["required"]
    props = tool.args_schema["properties"]
    assert props["query"]["type"] == "string"
    assert props["num_results"]["default"] == 5
    assert props["num_results"]["minimum"] == 1
    assert props["num_results"]["maximum"] == 20
    # Default engine chain does not include Baidu (its results are JS-loaded).
    assert tool.engines == ["google", "duckduckgo", "bing"]


def test_openai_and_anthropic_specs() -> None:
    """The tool renders as both OpenAI and Anthropic function-calling specs."""
    tool = WebSearchTool()
    openai = tool.to_openai_tool()
    assert openai["function"]["name"] == "web_search"
    assert "query" in openai["function"]["parameters"]["properties"]

    anthropic = tool.to_anthropic_tool()
    assert anthropic["name"] == "web_search"
    assert "query" in anthropic["input_schema"]["properties"]


# --------------------------------------------------------------------------- #
# Result formatting                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_format_results_contains_title_url_snippet() -> None:
    """The formatted output must surface the title (as bold), URL, and snippet."""
    tool = WebSearchTool()
    out = await _run_with_first_engine(tool, _make_results(1), _DEFAULT_ENGINES)
    assert "**Title 0**" in out
    assert "URL: https://example.com/0" in out
    assert "Snippet: Snippet 0" in out


# --------------------------------------------------------------------------- #
# Engine chain behaviour                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_engine_succeeds_returns_its_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the first engine yields results, the chain stops there."""
    tool = WebSearchTool()
    captured: list[str] = []

    async def fake_google(query: str, num: int) -> list[SearchResult]:
        captured.append(("google", query, num))
        return [_result("Google Hit", "https://g.com", "from google")]

    async def fake_ddg(query: str, num: int) -> list[SearchResult]:
        captured.append(("ddg", query, num))
        return [_result("DDG Hit")]

    monkeypatch.setattr(tool, "_search_google", fake_google)
    monkeypatch.setattr(tool, "_search_duckduckgo", fake_ddg)

    res = await tool(query="hello", num_results=5)

    assert res.is_error is False
    assert "Google Hit" in res.output
    assert "https://g.com" in res.output
    # DDG was never called — the chain short-circuited.
    engines_called = [name for name, _, _ in captured]
    assert engines_called == ["google"]


@pytest.mark.asyncio
async def test_failing_first_engine_falls_back_to_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the first engine raises, the second one is tried and its results returned."""
    tool = WebSearchTool()

    async def boom(query: str, num: int) -> list[SearchResult]:
        raise RuntimeError("network down")

    async def fake_ddg(query: str, num: int) -> list[SearchResult]:
        return [_result("DDG Hit", "https://ddg.example", "fallback worked")]

    monkeypatch.setattr(tool, "_search_google", boom)
    monkeypatch.setattr(tool, "_search_duckduckgo", fake_ddg)

    res = await tool(query="hello")

    assert res.is_error is False
    assert "DDG Hit" in res.output
    assert "https://ddg.example" in res.output


@pytest.mark.asyncio
async def test_empty_first_engine_falls_back_to_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty list from the first engine must also trigger fallback."""
    tool = WebSearchTool()

    async def empty(query: str, num: int) -> list[SearchResult]:
        return []

    async def fake_bing(query: str, num: int) -> list[SearchResult]:
        return [_result("Bing Hit", "https://b.com", "bing snippet")]

    monkeypatch.setattr(tool, "_search_google", empty)
    monkeypatch.setattr(tool, "_search_duckduckgo", empty)
    monkeypatch.setattr(tool, "_search_bing", fake_bing)

    res = await tool(query="hello")

    assert res.is_error is False
    assert "Bing Hit" in res.output


@pytest.mark.asyncio
async def test_all_engines_failing_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If every engine raises, the tool returns `is_error=True`."""
    tool = WebSearchTool()

    async def boom(query: str, num: int) -> list[SearchResult]:
        raise ConnectionError("dead")

    monkeypatch.setattr(tool, "_search_google", boom)
    monkeypatch.setattr(tool, "_search_duckduckgo", boom)
    monkeypatch.setattr(tool, "_search_bing", boom)

    res = await tool(query="anything")

    assert res.is_error is True
    assert res.error is not None
    assert "All search engines failed" in res.error
    assert "anything" in res.error


@pytest.mark.asyncio
async def test_all_engines_empty_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If every engine returns an empty list, the tool still returns an error."""
    tool = WebSearchTool()

    async def empty(query: str, num: int) -> list[SearchResult]:
        return []

    monkeypatch.setattr(tool, "_search_google", empty)
    monkeypatch.setattr(tool, "_search_duckduckgo", empty)
    monkeypatch.setattr(tool, "_search_bing", empty)

    res = await tool(query="niche query")

    assert res.is_error is True
    assert "niche query" in (res.error or "")


@pytest.mark.asyncio
async def test_num_results_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """`num_results` is forwarded verbatim to the engine."""
    tool = WebSearchTool()
    seen: list[int] = []

    async def fake_ddg(query: str, num: int) -> list[SearchResult]:
        seen.append(num)
        return _make_results(num)

    monkeypatch.setattr(tool, "_search_duckduckgo", fake_ddg)

    res = await tool(query="x", num_results=7)

    assert seen == [7]
    assert res.is_error is False
    # We asked for 7; we got 7 numbered entries.
    assert all(f"{i}. **" in res.output for i in range(1, 8))


@pytest.mark.asyncio
async def test_chain_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting `engines` to a custom list narrows the chain."""
    tool = WebSearchTool()
    called: list[str] = []

    async def fake_google(query: str, num: int) -> list[SearchResult]:
        called.append("google")
        return []

    async def fake_bing(query: str, num: int) -> list[SearchResult]:
        called.append("bing")
        return [_result("Only Bing", "https://b.com", "bing snippet")]

    monkeypatch.setattr(tool, "_search_google", fake_google)
    monkeypatch.setattr(
        tool,
        "_search_duckduckgo",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("DDG should not be called")),
    )
    monkeypatch.setattr(tool, "_search_bing", fake_bing)

    tool.engines = ["bing"]
    res = await tool(query="hi")

    assert res.is_error is False
    assert called == ["bing"]
    assert "Only Bing" in res.output


@pytest.mark.asyncio
async def test_chain_with_only_failing_engine_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-engine chain that fails is still a clean error result."""
    tool = WebSearchTool()

    async def boom(query: str, num: int) -> list[SearchResult]:
        raise RuntimeError("nope")

    monkeypatch.setattr(tool, "_search_google", boom)
    tool.engines = ["google"]

    res = await tool(query="x")

    assert res.is_error is True
    assert "google" in (res.error or "")


# --------------------------------------------------------------------------- #
# Argument validation                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_empty_query_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty query short-circuits with an error before hitting any engine."""
    tool = WebSearchTool()

    async def should_not_run(query: str, num: int) -> list[SearchResult]:
        raise AssertionError("engine should not be called for empty query")

    monkeypatch.setattr(tool, "_search_duckduckgo", should_not_run)

    res = await tool(query="")
    assert res.is_error is True
    assert "non-empty" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_schema_validation_rejects_bad_num_results() -> None:
    """`num_results` outside [1, 20] is rejected by the JSON-schema validator."""
    tool = WebSearchTool()
    res = await tool(query="x", num_results=0)
    assert res.is_error is True
    # The user-facing error string reports the violation; the field name
    # surfaces in the `tool.invalid_args` log warning, not in the message.
    assert "Invalid args" in (res.error or "")
    assert "minimum" in (res.error or "")

    res_hi = await tool(query="x", num_results=999)
    assert res_hi.is_error is True
    assert "Invalid args" in (res_hi.error or "")


# --------------------------------------------------------------------------- #
# Pure parser tests                                                            #
# --------------------------------------------------------------------------- #


def test_parse_duckduckgo_defensive_minimal_html() -> None:
    """DuckDuckGo parser returns `[]` for junk, not a crash."""
    from forgewright.tool.web_search import _parse_duckduckgo_html

    assert _parse_duckduckgo_html("<html><body>nothing useful</body></html>", 5) == []


def test_parse_google_defensive_minimal_html() -> None:
    """Google parser returns `[]` for junk, not a crash."""
    from forgewright.tool.web_search import _parse_google_html

    assert _parse_google_html("<html><body>nothing useful</body></html>", 5) == []


def test_parse_bing_defensive_minimal_html() -> None:
    """Bing parser returns `[]` for junk, not a crash."""
    from forgewright.tool.web_search import _parse_bing_html

    assert _parse_bing_html("<html><body>nothing useful</body></html>", 5) == []
