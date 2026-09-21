#!/usr/bin/env python3
"""Pack netstriker-ai as a .HadesPlugin from upstream git + HADES overlay."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_git  # noqa: E402

UPSTREAM = "https://github.com/TechXplorevo/Netstriker.ai"
DEFAULT_REF = "main"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack NetStrikerAI as a .HadesPlugin")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist")
    parser.add_argument("--ref", default=DEFAULT_REF, help="Upstream git ref (default: main)")
    args = parser.parse_args()
    package = pack_git(
        plugin_dir=Path(__file__).resolve().parent,
        out_dir=args.out.resolve(),
        upstream=UPSTREAM,
        ref=args.ref,
        extra_parts={"test_reports", "frontend/node_modules", "memory"},
    )
    print(f"Wrote {package} ({package.stat().st_size / (1024 * 1024):.2f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
