#!/usr/bin/env python3
"""DEMO 05 — Crash/resume without duplicating committed effects.

Uses the effect ledger: prepared → committed, then restart classification
must be ALREADY_COMMITTED (no blind re-exec).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from runtime.effect_ledger import EffectLedger


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = EffectLedger(Path(tmp) / "effects.db")
        prepared = ledger.prepare(
            tool="write_file",
            arguments={"path": "out.txt", "content": "once"},
            effect_class="fs_write",
            task_id="task_demo",
            run_id="run_1",
        )
        # Crash before commit → irreversible-ish requires reconciliation.
        mid = ledger.classify_on_restart(prepared.effect_id)
        if mid["class"] != "REQUIRES_RECONCILIATION":
            print(f"FAIL: expected REQUIRES_RECONCILIATION, got {mid}")
            return 1

        ledger.mark_committed(prepared.effect_id, detail={"bytes_written": 4})
        after = ledger.classify_on_restart(prepared.effect_id)
        if after["class"] != "ALREADY_COMMITTED":
            print(f"FAIL: expected ALREADY_COMMITTED, got {after}")
            return 1

        # Second prepare with same args is a new effect_id — caller must check hash.
        again = ledger.prepare(
            tool="write_file",
            arguments={"path": "out.txt", "content": "once"},
            effect_class="fs_write",
            task_id="task_demo",
            run_id="run_2",
        )
        if again.args_hash != prepared.args_hash:
            print("FAIL: args_hash unstable")
            return 1

        print("PASS demo_05_crash_resume_effects")
        print(f"  mid={mid['class']} after={after['class']} args_hash={prepared.args_hash[:12]}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
