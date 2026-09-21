#!/usr/bin/env python3
"""Run the three A14 portfolio demos and exit non-zero on any failure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMOS = [
    ROOT / "docs" / "demos" / "demo_01_successful_task.py",
    ROOT / "docs" / "demos" / "demo_02_blocked_action.py",
    ROOT / "docs" / "demos" / "demo_03_recovery_after_failure.py",
    ROOT / "docs" / "demos" / "demo_04_false_success_defense.py",
    ROOT / "docs" / "demos" / "demo_05_crash_resume_effects.py",
    ROOT / "docs" / "demos" / "demo_06_context_quality.py",
]


def main() -> int:
    failed = 0
    for demo in DEMOS:
        print(f"\n=== {demo.name} ===")
        proc = subprocess.run([sys.executable, str(demo)], cwd=str(ROOT))
        if proc.returncode != 0:
            failed += 1
            print(f"FAIL {demo.name} exit={proc.returncode}")
        else:
            print(f"PASS {demo.name}")
    print(f"\n{len(DEMOS) - failed}/{len(DEMOS)} demos passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
