"""Regenerate PWA icon assets from the canonical 512x512 source.

Inputs:
  src/forgewright/web/static/icon-512.png   (canonical 512x512 design)

Outputs (written next to the source):
  src/forgewright/web/static/icon-192.png         (re-rendered for sharpness)
  src/forgewright/web/static/icon-512.png         (passed through / re-encoded)
  src/forgewright/web/static/apple-touch-icon.png (180x180 for iOS)
  src/forgewright/web/static/icon-maskable-512.png (512x512 with 410x410
                                                    artwork safe-zone for
                                                    adaptive launchers)

Run from the repo root:
    python3 tools/regen_pwa_icons.py

The script is idempotent and safe to commit; outputs are checked in so
the PWA build does not need a Pillow dependency at install time.
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

from PIL import Image

# Pyright's PIL stubs expose resampling filters under Image.Resampling.
# Fall back to the legacy module-level constant for older Pillow builds
# that don't have Image.Resampling yet. The cast silences the
# "LANCZOS is not a known attribute" report on the legacy fallback.
_resampling = getattr(Image, "Resampling", Image)
_LANCZOS = cast("Image.Resampling", _resampling.LANCZOS)

STATIC = Path(__file__).resolve().parents[1] / "src" / "forgewright" / "web" / "static"
SOURCE = STATIC / "icon-512.png"


def _save(img: Image.Image, name: str) -> Path:
    out = STATIC / name
    img.save(out, format="PNG", optimize=True)
    print(f"wrote {out}  size={img.size}  mode={img.mode}")
    return out


def regenerate_192(src: Image.Image) -> None:
    _save(src.resize((192, 192), _LANCZOS), "icon-192.png")


def regenerate_apple_touch(src: Image.Image) -> None:
    # 180x180 is the iOS sweet spot; LANCZOS keeps the symbol crisp.
    _save(src.resize((180, 180), _LANCZOS), "apple-touch-icon.png")


def regenerate_maskable(src: Image.Image) -> None:
    """Maskable icon: 512x512 with the artwork centered in a 410x410
    safe zone. The outer 51px on every side is the system mask area
    (Android, iOS adaptive icons, web app launchers).

    We compose by:
      1. Solid #0A0A0B background (matches the dark chrome of the brand)
      2. The source scaled into a 410x410 region centered, then alpha-
         composited on top.

    The result is a single 512x512 RGBA PNG.
    """
    SAFE = 410
    BG = (10, 10, 11, 255)  # #0A0A0B
    canvas = Image.new("RGBA", (512, 512), BG)
    # Convert source to RGBA so the paste handles transparency cleanly.
    if src.mode != "RGBA":
        src = src.convert("RGBA")
    artwork = src.resize((SAFE, SAFE), _LANCZOS)
    offset = (512 - SAFE) // 2  # = 51
    canvas.paste(artwork, (offset, offset), artwork)
    _save(canvas, "icon-maskable-512.png")


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"source icon missing: {SOURCE}")
    with Image.open(SOURCE) as raw:
        src = raw.copy()
    # Re-encode the canonical 512 too (lossless normalize).
    _save(src.convert("RGBA"), "icon-512.png")
    regenerate_192(src)
    regenerate_apple_touch(src)
    regenerate_maskable(src)


if __name__ == "__main__":
    main()
