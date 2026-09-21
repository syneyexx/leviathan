#!/usr/bin/env python3
"""DEMO 04 — False-success defense.

Model/tool claims success while observable acceptance fails → HADES refuses completion.
No LM Studio required.
"""

from __future__ import annotations

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
        arts = ArtifactService(pdb, root)

        # Tool/model says success and even creates an empty "report".
        empty = arts.create(
            name="mission_report.md",
            kind="generated",
            data=b"",
            status="ready",
            verify_format=False,
        )
        ready = arts.verify_ready(empty["id"])
        if ready["checks"].get("ok"):
            print("FAIL: empty artifact incorrectly verify-ready")
            return 1

        # Checkpoint never reached verified — completion must be refused.
        decision = decide_work_task_completion(
            checkpoint_state={"phase": "executed", "passed": True, "model_said": "success"},
            steps=[{"id": "s1", "status": "completed"}],
        )
        if decision.may_complete:
            print("FAIL: completion allowed without verified checkpoint")
            return 1

        print("PASS demo_04_false_success_defense")
        print(f"  empty_artifact_ok={ready['checks'].get('ok')}")
        print(f"  may_complete={decision.may_complete} reason={decision.reason}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
