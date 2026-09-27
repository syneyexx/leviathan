#!/usr/bin/env python3
"""Measure Screen 1 panel geometry from gold border runs.

Writes a text report. Coordinates are CSS pixels of the 1672×941 reference.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

DEFAULT = Path(__file__).resolve().parents[1] / "tests" / "visual" / "reference" / "run_leviathan_1672x941.png"


def gold(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > 70 and g > 45 and b < 160 and (r - b) > 25 and r + 20 >= g


def ranges(indexes: list[int], join: int = 1) -> list[tuple[int, int]]:
    if not indexes:
        return []
    start = prev = indexes[0]
    out: list[tuple[int, int]] = []
    for value in indexes[1:]:
        if value <= prev + join:
            prev = value
        else:
            out.append((start, prev))
            start = prev = value
    out.append((start, prev))
    return out


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    image = Image.open(path).convert("RGB")
    width, height = image.size
    px = image.load()
    print(f"Reference: {width}x{height}")
    print(f"source: {path}")

    print("\nHorizontal gold runs longer than 500px:")
    for y in range(height):
        best = cur = start = 0
        best_start = 0
        for x in range(width):
            if gold(px[x, y]):
                if cur == 0:
                    start = x
                cur += 1
                if cur > best:
                    best = cur
                    best_start = start
            else:
                cur = 0
        if best > 500:
            print(f"  y={y:4d} run={best:4d} from x={best_start}")

    print("\nVertical gold runs in the main band y=310..610 longer than 80px:")
    for x in range(width):
        best = cur = 0
        for y in range(310, 610):
            if gold(px[x, y]):
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        if best > 80:
            print(f"  x={x:4d} run={best}")

    print("\nVertical gold runs in the lower band y=640..890 longer than 80px:")
    for x in range(width):
        best = cur = 0
        for y in range(640, 890):
            if gold(px[x, y]):
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        if best > 80:
            print(f"  x={x:4d} run={best}")

    ys = [y for y in range(height) if gold(px[6, y])]
    print("\nLeft frame x=6 segments:")
    for start, end in ranges(ys, 2):
        if end - start > 8:
            print(f"  y={start}-{end} h={end - start + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
