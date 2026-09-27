#!/usr/bin/env python3
"""Capture the fixture renderer and diff it against the canonical reference.

This compares layout at 1672x941. Text that must stay truthful (database names,
worker ids, versions) will not match the generated concept screenshot pixel for
pixel. The report records mismatch instead of hiding it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(__file__).resolve().parent / "reference.png"
OUT = Path(__file__).resolve().parent / "output"
WIDTH = 1672
HEIGHT = 941


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shot = OUT / "fixture.png"
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4178/"
    chrome = "/usr/bin/google-chrome"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={WIDTH},{HEIGHT}",
            f"--screenshot={shot}",
            url,
        ],
        check=True,
        timeout=60,
    )
    ref = Image.open(REFERENCE).convert("RGB")
    got = Image.open(shot).convert("RGB")
    got = got.resize((WIDTH, HEIGHT)) if got.size != (WIDTH, HEIGHT) else got
    if ref.size != (WIDTH, HEIGHT):
        ref = ref.resize((WIDTH, HEIGHT))
    diff = ImageChops.difference(ref, got)
    histogram = diff.histogram()
    # 256 bins per channel.
    total = 0
    mismatch = 0
    pixels = WIDTH * HEIGHT
    for channel in range(3):
        bins = histogram[channel * 256 : (channel + 1) * 256]
        for value, count in enumerate(bins):
            total += value * count
            if value > 18:
                mismatch += count
    mean = total / (pixels * 3)
    mismatch_pct = (mismatch / 3) / pixels * 100
    diff.save(OUT / "diff.png")
    report = OUT / "report.txt"
    report.write_text(
        f"viewport={WIDTH}x{HEIGHT}\n"
        f"mean_absolute_difference={mean:.3f}\n"
        f"mismatch_percent_channel_delta_gt_18={mismatch_pct:.2f}\n"
        f"reference={REFERENCE}\n"
        f"capture={shot}\n"
        "note=OS text rasterization and truthful labels differ from the generated concept screenshot.\n",
        encoding="utf-8",
    )
    print(report.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
