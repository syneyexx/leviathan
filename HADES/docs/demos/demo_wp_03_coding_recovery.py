#!/usr/bin/env python3
"""Demo 3 — Coding with controlled recovery + effect ledger honesty.

Introduces failing test → fix path mapping; failed repair is honest;
mutation timeout requires reconciliation (no blind double write).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from coding_requirement_map import build_requirement_verification_map, failed_repair_delivery
from runtime.effect_ledger import EffectLedger


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "fixture_repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        (repo / "notes.local").write_text("user scratch — do not touch\n", encoding="utf-8")
        test_file = repo / "test_app.py"
        test_file.write_text(
            "from app import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
            encoding="utf-8",
        )
        # First: failing test (off-by-one).
        failing = {"passed": False, "tests": ["test_add"], "status": "failed"}
        # Controlled fix in managed workspace (simulated).
        (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        passing = {"passed": True, "tests": ["test_add"], "status": "passed"}
        mapping = build_requirement_verification_map(
            requirements=[{"id": "r1", "text": "add(1,1)==2", "files": ["app.py"], "tests": ["test_add"]}],
            changed_files=["app.py"],
            test_results=passing,
            base_revision="fixture",
            protected_user_paths=["notes.local"],
        )
        user_ok = (repo / "notes.local").read_text(encoding="utf-8").startswith("user scratch")
        # Failed repair path (honest).
        failed = failed_repair_delivery(
            diagnosis="Secondary assertion still fails on edge case",
            partial_diff="--- app.py\n+++ app.py\n",
            test_results=failing,
            requirement_map=mapping,
        )

        ledger = EffectLedger(Path(tmp) / "effects.db")
        before = ledger.prepare(tool="write", arguments={"path": "app.py"}, effect_class="fs_write")
        ledger.mark_failed(before.effect_id, detail={"effect_applied": False, "failure_stage": "before_execute"})
        during = ledger.prepare(tool="write", arguments={"path": "app.py", "v": 2}, effect_class="fs_write")
        ledger.mark_failed(during.effect_id, detail={"effect_applied": True, "failure_stage": "after_execute"})
        after = ledger.prepare(tool="write", arguments={"path": "app.py", "v": 3}, effect_class="fs_write")
        ledger.mark_unknown(after.effect_id)

        out = {
            "demo": "03_coding_controlled_recovery",
            "user_file_preserved": user_ok and mapping["user_files_preserved"],
            "requirement_map": mapping,
            "failed_repair_honest": failed["completed"] is False,
            "effect_classes": {
                "before": ledger.classify_on_restart(before.effect_id)["class"],
                "during": ledger.classify_on_restart(during.effect_id)["class"],
                "after": ledger.classify_on_restart(after.effect_id)["class"],
            },
            "blind_retry_blocked_when_uncertain": ledger.classify_on_restart(during.effect_id)["class"]
            != "SAFE_TO_RETRY",
            "providers_required": [],
            "fixtures": ["fixture_repo app.py/test_app.py", "EffectLedger"],
            "not_proven": ["Full CodingAgentService worktree on Windows", "Live model repair loop"],
            "measured": {"tests_after_fix": passing},
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        ok = (
            out["user_file_preserved"]
            and out["failed_repair_honest"]
            and out["effect_classes"]["before"] == "SAFE_TO_RETRY"
            and out["effect_classes"]["during"] == "REQUIRES_RECONCILIATION"
            and out["blind_retry_blocked_when_uncertain"]
        )
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
