"""DataVisualization — render an Altair-style Vega-Lite JSON spec.

The LLM emits the spec as the result of ``altair.Chart(...).to_dict()``.
We render to inline HTML (always) and, on request, to a base64 PNG via
``vl-convert``. The optional [viz] extra pulls in both ``altair`` and
``vl-convert``; if either is missing the tool returns a clear install
hint instead of raising.
"""

from __future__ import annotations

import base64
from typing import Any, ClassVar

from forgewright.logger import logger
from forgewright.schema import ToolResult
from forgewright.tool.base import BaseTool

__all__ = ["DataVisualization"]


# Truncate HTML output at 100 KiB. Vega-Lite HTML for big datasets balloons
# fast; the LLM only needs the head to see what it produced.
_MAX_HTML_CHARS = 100_000


class DataVisualization(BaseTool):
    """Render a chart from an Altair-style Vega-Lite JSON spec."""

    name: ClassVar[str] = "data_visualization"
    description: ClassVar[str] = (
        "Render a chart from an Altair-style Vega-Lite JSON spec. "
        "Returns the chart as inline HTML (always) and as a base64 PNG "
        "image if `format` is 'png'."
    )
    args_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": "Altair/Vega-Lite chart spec (Chart.to_dict()).",
            },
            "format": {
                "type": "string",
                "enum": ["html", "png"],
                "default": "html",
                "description": (
                    "Output format. 'html' returns inline HTML; 'png' "
                    "returns base64 PNG via vl-convert."
                ),
            },
        },
        "required": ["spec"],
    }
    timeout_s: ClassVar[int] = 30

    async def _run(  # type: ignore[override]
        self,
        *,
        spec: dict[str, Any],
        format: str = "html",
    ) -> ToolResult:
        """Render `spec` as HTML or PNG."""
        # Lazy imports so the tool module loads even if altair/vl-convert
        # aren't installed; we surface a clean install hint instead.
        try:
            import altair
        except ImportError as exc:
            logger.warning("data_visualization.missing_altair err={}", exc)
            return ToolResult(
                is_error=True,
                error=(
                    "data_visualization requires the [viz] extra. "
                    "Install with: uv pip install 'forgewright[viz]'"
                ),
            )

        # Build the chart once; Altair validates the spec against the
        # Vega-Lite schema and raises jsonschema.ValidationError on
        # malformed input.
        try:
            chart = altair.Chart.from_dict(spec)
        except Exception as exc:
            logger.warning("data_visualization.invalid_spec err={}: {}", type(exc).__name__, exc)
            return ToolResult(
                is_error=True,
                error=f"Invalid Vega-Lite spec: {type(exc).__name__}: {exc}",
            )

        if format == "png":
            return self._render_png(spec)
        return self._render_html(chart)

    # ------------------------------------------------------------------ #
    # Format-specific renderers                                            #
    # ------------------------------------------------------------------ #

    def _render_html(self, chart: Any) -> ToolResult:
        """Return inline HTML, truncated at `_MAX_HTML_CHARS`."""
        try:
            html = chart.to_html()
        except Exception as exc:
            logger.exception("data_visualization.to_html_failed")
            return ToolResult(
                is_error=True,
                error=f"Failed to render HTML: {type(exc).__name__}: {exc}",
            )

        if len(html) > _MAX_HTML_CHARS:
            html = html[:_MAX_HTML_CHARS] + "\n... [truncated]"
            logger.info("data_visualization.html_truncated len={}", _MAX_HTML_CHARS)
        return ToolResult(output=html)

    def _render_png(self, spec: dict[str, Any]) -> ToolResult:
        """Return a base64 PNG via vl-convert; the model never sees raw bytes."""
        try:
            import vl_convert
        except ImportError as exc:
            logger.warning("data_visualization.missing_vl_convert err={}", exc)
            return ToolResult(
                is_error=True,
                error=(
                    "data_visualization png format requires the [viz] extra. "
                    "Install with: uv pip install 'forgewright[viz]'"
                ),
            )

        try:
            png_bytes = vl_convert.vegalite_to_png(vl_spec=spec)
        except Exception as exc:
            logger.exception("data_visualization.png_failed")
            return ToolResult(
                is_error=True,
                error=f"Failed to render PNG: {type(exc).__name__}: {exc}",
            )

        encoded = base64.b64encode(png_bytes).decode("ascii")
        return ToolResult(
            output=f"PNG chart, {len(png_bytes)} bytes",
            base64_image=encoded,
        )
