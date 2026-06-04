"""Regenerate PWA install-card screenshots for the web manifest.

Captures the live chat UI with Playwright at desktop and mobile
viewports. Outputs are checked in under
``src/forgewright/web/static/screenshots/`` so installs do not need
Playwright at runtime.

Run from the repo root (with the web server already listening):

    uv run --extra web forgewright web --port 8787 &
    uv run --extra browser python tools/regen_pwa_screenshots.py

Or pass a base URL:

    python tools/regen_pwa_screenshots.py --base-url http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "forgewright" / "web" / "static"
OUT = STATIC / "screenshots"


def _placeholder_png(path: Path, width: int, height: int) -> None:
    """Write a minimal branded placeholder when Playwright is unavailable."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), "#020617")
    draw = ImageDraw.Draw(img)
    draw.rectangle((24, 24, width - 24, height - 24), outline="#22C55E", width=3)
    label = "forgewright"
    draw.text((width // 2 - 60, height // 2 - 10), label, fill="#F8FAFC")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)


def capture(base_url: str) -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        desktop = browser.new_page(viewport={"width": 1280, "height": 720})
        desktop.goto(base_url.rstrip("/") + "/", wait_until="networkidle")
        desktop.screenshot(path=str(OUT / "desktop.png"), full_page=False)

        mobile = browser.new_page(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        mobile.goto(base_url.rstrip("/") + "/", wait_until="networkidle")
        mobile.screenshot(path=str(OUT / "mobile.png"), full_page=False)
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8787",
        help="forgewright web origin (default: http://127.0.0.1:8787)",
    )
    parser.add_argument(
        "--placeholder-only",
        action="store_true",
        help="Skip Playwright and write minimal placeholder PNGs",
    )
    args = parser.parse_args()

    if args.placeholder_only:
        _placeholder_png(OUT / "desktop.png", 1280, 720)
        _placeholder_png(OUT / "mobile.png", 390, 844)
        print(f"wrote placeholders under {OUT}")
        return 0

    try:
        capture(args.base_url)
    except Exception as exc:
        print(f"playwright capture failed ({exc}); writing placeholders", file=sys.stderr)
        _placeholder_png(OUT / "desktop.png", 1280, 720)
        _placeholder_png(OUT / "mobile.png", 390, 844)
        return 1

    print(f"wrote {OUT / 'desktop.png'} and {OUT / 'mobile.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
