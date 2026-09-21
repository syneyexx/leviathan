#!/usr/bin/env python3
"""Pack eli5 as a .HadesPlugin from the local plugin folder."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_local  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist")
    args = parser.parse_args()
    package = pack_local(plugin_dir=Path(__file__).resolve().parent, out_dir=args.out.resolve())
    print(f"Wrote {package} ({package.stat().st_size / (1024 * 1024):.2f} MiB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
