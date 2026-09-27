#!/usr/bin/env python3
"""Capture the fixture renderer and diff it against Screen 1.

Canonical viewport is 1672×941 at device scale 1. A second capture at
2048×857 checks that the reference stage scales up instead of collapsing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(__file__).resolve().parent / "reference" / "run_leviathan_1672x941.png"
OUT = Path(__file__).resolve().parent / "output"
CHROME = "/usr/bin/google-chrome"
REGIONS = {
    "banner": (0, 28, 1672, 136),
    "runtime": (0, 136, 1672, 210),
    "health": (0, 200, 1672, 300),
    "main": (0, 294, 1672, 622),
    "lower": (0, 632, 1672, 901),
    "status": (0, 900, 1672, 941),
}


def capture(url: str, width: int, height: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={width},{height}",
            f"--screenshot={dest}",
            url,
        ],
        check=True,
        timeout=90,
    )


def channel_stats(diff: Image.Image) -> tuple[float, float]:
    histogram = diff.histogram()
    width, height = diff.size
    pixels = width * height
    total = 0
    mismatch = 0
    for channel in range(3):
        bins = histogram[channel * 256 : (channel + 1) * 256]
        for value, count in enumerate(bins):
            total += value * count
            if value > 18:
                mismatch += count
    mean = total / (pixels * 3)
    mismatch_pct = (mismatch / 3) / pixels * 100
    return mean, mismatch_pct


def region_report(reference: Image.Image, actual: Image.Image) -> str:
    lines = []
    for name, box in REGIONS.items():
        diff = ImageChops.difference(reference.crop(box), actual.crop(box))
        mean, mismatch = channel_stats(diff)
        lines.append(f"region {name}: mae={mean:.3f} mismatch={mismatch:.2f}%")
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4178/"
    actual_path = OUT / "actual-reference-viewport.png"
    wide_path = OUT / "actual-2048x857.png"
    capture(url, 1672, 941, actual_path)
    capture(url, 2048, 857, wide_path)
    reference = Image.open(REFERENCE).convert("RGB")
    actual = Image.open(actual_path).convert("RGB")
    note = ""
    if actual.size != reference.size:
        note = f"size_mismatch actual={actual.size} reference={reference.size}\n"
        actual = actual.resize(reference.size)
    diff = ImageChops.difference(reference, actual)
    mean, mismatch = channel_stats(diff)
    diff.save(OUT / "diff.png")
    # Amplify the diff so remaining structure is visible.
    amplified = diff.point(lambda value: min(255, value * 4))
    amplified.save(OUT / "diff-amplified.png")
    wide = Image.open(wide_path).convert("RGB")
    draw = ImageDraw.Draw(wide)
    # Expected stage box when height-limited: scale = 857/941, width = 1672*scale.
    scale = 857 / 941
    stage_w = 1672 * scale
    stage_h = 941 * scale
    left = (wide.size[0] - stage_w) / 2
    top = (wide.size[1] - stage_h) / 2
    draw.rectangle([left, top, left + stage_w, top + stage_h], outline=(255, 64, 64))
    wide.save(OUT / "actual-2048x857-guide.png")
    report = OUT / "report.txt"
    body = (
        f"reference_size={reference.size[0]}x{reference.size[1]}\n"
        f"actual_size={Image.open(actual_path).size[0]}x{Image.open(actual_path).size[1]}\n"
        f"wide_size={Image.open(wide_path).size[0]}x{Image.open(wide_path).size[1]}\n"
        f"{note}"
        f"mean_absolute_difference={mean:.3f}\n"
        f"mismatch_percent_channel_delta_gt_18={mismatch:.2f}\n"
        f"{region_report(reference, actual if actual.size == reference.size else actual.resize(reference.size))}\n"
        "note=font rasterization and truthful fixture labels differ from baked concept text.\n"
    )
    report.write_text(body, encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
