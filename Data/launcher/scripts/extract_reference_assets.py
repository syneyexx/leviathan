#!/usr/bin/env python3
"""Crop decorative artwork from the canonical 1672×941 reference.

Live values are not kept. The clock interior is cleared so the renderer can
draw the real system time in HTML. Buttons, tables, and statuses are not cropped.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = Path("/home/ubuntu/.cursor/projects/workspace/assets/ffccb629-4caa-4e02-9713-c0a6b14e5042.png")
FALLBACK = ROOT / "tests" / "visual" / "reference" / "run_leviathan_1672x941.png"
OUT = ROOT / "src" / "assets" / "reference"
VISUAL = ROOT / "tests" / "visual"


def clear_clock(banner: Image.Image) -> None:
    """Banner crop starts at stage y=28. Clock glyphs sit inside the right box."""
    px = banner.load()
    # Sample the dark field just inside the clock box (stage x=1580, y=90).
    sample = px[1580, 90 - 28]
    for y in range(22, 100):
        for x in range(1508, 1652):
            px[x, y] = sample


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REFERENCE
    if not source.exists():
        source = FALLBACK
    if not source.exists():
        print(f"reference image missing: {source}", file=sys.stderr)
        return 1
    image = Image.open(source).convert("RGB")
    if image.size != (1672, 941):
        print(f"expected 1672x941, got {image.size}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    ref_dir = VISUAL / "reference"
    broken_dir = VISUAL / "baseline-broken"
    ref_dir.mkdir(parents=True, exist_ok=True)
    broken_dir.mkdir(parents=True, exist_ok=True)
    golden = ref_dir / "run_leviathan_1672x941.png"
    if source.resolve() != golden.resolve():
        shutil.copy2(source, golden)

    broken_src = Path("/home/ubuntu/.cursor/projects/workspace/assets/439b9380-bf21-4d7b-a352-5654af708d37.png")
    if broken_src.exists():
        shutil.copy2(broken_src, broken_dir / "screen2-2048x857.png")

    banner = image.crop((0, 28, 1672, 136))
    clear_clock(banner)
    banner.save(OUT / "banner-skyline.png")

    image.crop((760, 36, 980, 132)).save(OUT / "geometry-seal.png")
    image.crop((324, 572, 388, 636)).save(OUT / "panel-texture.png")
    image.crop((6, 294, 28, 316)).save(OUT / "corner-ornament-left.png")
    image.crop((1640, 294, 1666, 316)).save(OUT / "corner-ornament-right.png")
    image.crop((528, 468, 668, 612)).save(OUT / "console-seal.png")
    print(f"wrote decorative crops under {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
