#!/usr/bin/env python3
"""Demo 01 — successful full task path (no LM Studio required).

Simulates Work Runtime completion: steps done → verified checkpoint →
ArtifactService bytes ready → decide_work_task_completion allows completed.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from artifacts import ArtifactService
from database import Database
from platform_db import PlatformDatabase
from run_lifecycle import decide_work_task_completion


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        core = Database(str(root / "hades.db"))
        core.initialize()
        pdb = PlatformDatabase(str(root / "hades.db"))
        pdb.initialize()
        arts = ArtifactService(pdb, root / "data")
        artifact = arts.create(
            name="demo_report.md",
            kind="generated",
            data=b"# Demo report\n\nTask deliverable bytes present.\n",
            status="ready",
            metadata={"demo": "01_successful_task"},
        )
        verified = arts.verify_ready(artifact["id"])
        checks = dict(verified.get("checks") or {})
        ready = bool(checks.get("ok"))
        if not ready:
            print(json.dumps({"ok": False, "stage": "artifact", "verified": verified}, indent=2, default=str))
            return 1

        steps = [
            {"id": "s1", "status": "completed", "title": "plan"},
            {"id": "s2", "status": "completed", "title": "execute"},
            {"id": "s3", "status": "completed", "title": "verify"},
        ]
        decision = decide_work_task_completion(
            checkpoint_state={
                "phase": "verified",
                "passed": True,
                "evidence_refs": [f"artifact:{artifact['id']}", "step:s1", "step:s2", "step:s3"],
            },
            steps=steps,
        )
        payload = {
            "demo": "01_successful_task",
            "ok": bool(decision.may_complete and ready),
            "artifact_id": artifact["id"],
            "artifact_checks": checks,
            "completion": decision.to_dict(),
            "note": "Deterministic success path without model calls.",
        }
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
