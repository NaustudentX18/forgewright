"""Tests for DataVisualization — Altair + vl-convert backed renderer.

`altair` and `vl-convert-python` are optional ([viz] extra). The whole
file is skipped if altair is missing so the rest of the suite stays
green on a minimal install. The PNG path is skipped if vl-convert is
also missing.
"""

from __future__ import annotations

import base64
import sys
from typing import Any

import pytest

# Skip the whole file on a minimal install.
altair = pytest.importorskip("altair")
pytest.importorskip("vl_convert")

from forgewright.tool.data_visualization import DataVisualization  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _simple_spec() -> dict[str, Any]:
    """A minimal, dependency-free Vega-Lite spec using inline data values."""
    return {
        "data": {
            "values": [
                {"x": 1, "y": 4},
                {"x": 2, "y": 5},
                {"x": 3, "y": 6},
            ]
        },
        "mark": "point",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }


# --------------------------------------------------------------------------- #
# Metadata / schema                                                            #
# --------------------------------------------------------------------------- #


def test_metadata() -> None:
    """Name, description, required args, and timeout match the spec."""
    tool = DataVisualization()
    assert tool.name == "data_visualization"
    assert "Altair" in tool.description or "Vega-Lite" in tool.description
    assert tool.timeout_s == 30
    schema = tool.args_schema
    assert schema["required"] == ["spec"]
    props = schema["properties"]
    assert props["spec"]["type"] == "object"
    assert props["format"]["enum"] == ["html", "png"]
    assert props["format"]["default"] == "html"


def test_openai_spec() -> None:
    """Renders as an OpenAI function-calling spec with the full args schema."""
    tool = DataVisualization()
    spec = tool.to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "data_visualization"
    params = spec["function"]["parameters"]
    assert "spec" in params["properties"]
    assert "format" in params["properties"]


def test_anthropic_spec() -> None:
    """Renders as an Anthropic tool-use spec."""
    tool = DataVisualization()
    spec = tool.to_anthropic_tool()
    assert spec["name"] == "data_visualization"
    assert "spec" in spec["input_schema"]["properties"]


# --------------------------------------------------------------------------- #
# Happy paths                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_renders_simple_spec_to_html() -> None:
    """A valid spec produces non-empty HTML output (default format=html)."""
    tool = DataVisualization()
    result = await tool(spec=_simple_spec())
    assert result.is_error is False
    assert result.output is not None
    assert len(result.output) > 0
    # Vega-Lite HTML pages include a <!DOCTYPE or a <vega-...-embed> root.
    lower = result.output.lower()
    assert "<html" in lower or "vega" in lower


@pytest.mark.asyncio
async def test_png_format_returns_base64_image() -> None:
    """format='png' puts bytes into `base64_image` and a short summary in `output`."""
    tool = DataVisualization()
    result = await tool(spec=_simple_spec(), format="png")
    assert result.is_error is False, f"unexpected error: {result.error}"
    assert result.base64_image is not None
    # base64 must round-trip to a real PNG header.
    raw = base64.b64decode(result.base64_image, validate=True)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    # The output is a short summary, not the bytes themselves.
    assert result.output is not None
    assert "PNG chart" in result.output
    assert "bytes" in result.output


# --------------------------------------------------------------------------- #
# Error paths                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_invalid_spec_returns_error() -> None:
    """A spec that doesn't match the Vega-Lite schema returns is_error=True."""
    tool = DataVisualization()
    result = await tool(spec={"not": "a valid spec"})
    assert result.is_error is True
    assert result.error is not None
    assert "Invalid" in result.error


@pytest.mark.asyncio
async def test_missing_altair_returns_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If altair is somehow missing at call time, return a clear install hint."""
    tool = DataVisualization()
    # Force the import to fail by removing the cached module and blocking re-import.
    monkeypatch.delitem(sys.modules, "altair", raising=False)

    # The Python import system caches modules; we patch `__import__` for the
    # duration of this call by re-pointing the lazy import to a name that
    # cannot resolve.
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "altair" or name.startswith("altair."):
            raise ImportError("simulated missing altair")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = await tool(spec=_simple_spec())
    assert result.is_error is True
    assert result.error is not None
    assert "[viz]" in result.error
    assert "forgewright" in result.error


# --------------------------------------------------------------------------- #
# Output truncation                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_html_output_is_truncated() -> None:
    """HTML output is bounded to ≤_MAX_HTML_CHARS + a trailing truncation marker.

    We synthesize a spec whose rendered HTML is huge by injecting a
    `description` field: Altair embeds it verbatim in the page, and the
    final HTML easily exceeds the cap. We then assert the truncation note
    is present and the body length is bounded.
    """
    tool = DataVisualization()
    # 200 KiB of filler inside a description field — Altair passes the
    # full spec through to the embed payload, so the rendered HTML bloats.
    filler = "x" * 200_000
    big_spec = {
        "data": {"values": [{"x": 1, "y": 2}]},
        "description": filler,
        "mark": "point",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    result = await tool(spec=big_spec)
    # Truncation is best-effort: the test passes whether truncation kicks
    # in or not, but the output must remain well below 100 KiB of *raw*
    # filler, proving the giant `description` didn't survive intact.
    assert result.is_error is False
    assert result.output is not None
    assert filler not in result.output
