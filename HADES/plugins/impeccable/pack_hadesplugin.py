#!/usr/bin/env python3
"""Pack impeccable as a .HadesPlugin from upstream git + overlay (skills only)."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_git  # noqa: E402

UPSTREAM = "https://github.com/pbakaus/impeccable"
DEFAULT_REF = "main"
# Keep agent skill trees; drop build/browser/cargo noise.
EXTRA_PARTS = {
    "browser-bundle",
    ".cargo",
    "target",
    "node_modules",
    ".git",
    "dist",
    "build",
    "crates",
    "wasm",
    "fixtures",
    "screenshots",
    "tests",
    "oracle",
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist")
    parser.add_argument("--ref", default=DEFAULT_REF)
    args = parser.parse_args()
    package = pack_git(
        plugin_dir=Path(__file__).resolve().parent,
        out_dir=args.out.resolve(),
        upstream=UPSTREAM,
        ref=args.ref,
        extra_parts=EXTRA_PARTS,
    )
    print(f"Wrote {package} ({package.stat().st_size / (1024 * 1024):.2f} MiB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
