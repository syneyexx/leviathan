#!/usr/bin/env python3
"""Demo 1 — Long-running project continuity + selective invalidation.

Fixtures only; no live LM required.
Proves: interrupt → restart → constraint change; independent branches preserved.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from database import Database
from project_continuity import ProjectContinuityService
from reasoning.plan_scheduler import steps_invalidated_by_input_change


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "hades.db"
        db = Database(str(db_path))
        svc = ProjectContinuityService(db)
        project = svc.create_project("Long mission demo")
        svc.add_item(
            project["id"],
            kind="goal",
            title="Ship offline research report",
            provenance="user_explicit",
        )
        svc.add_item(
            project["id"],
            kind="decision",
            title="Use local fixtures only",
            body="Besluit: geen netwerk voor deze missie",
            provenance="user_explicit",
        )
        svc.add_item(
            project["id"],
            kind="constraint",
            title="Budget max 3 tool calls",
            body="Maximaal 3 tool calls",
            provenance="user_explicit",
        )

        # Interrupt + restart (new service, same SQLite).
        svc2 = ProjectContinuityService(Database(str(db_path)))
        before = svc2.context_package(project["id"])

        # User redirects constraint mid-mission.
        svc2.add_item(
            project["id"],
            kind="constraint",
            title="Budget max 5 tool calls instead of 3",
            body="Correctie: maximaal 5 tool calls in plaats van 3",
            provenance="user_explicit",
        )
        after = svc2.context_package(project["id"])

        steps = [
            {"step_id": "research_a", "depends_on": [], "input_refs": ["src_a"]},
            {"step_id": "research_b", "depends_on": [], "input_refs": ["src_b"]},
            {"step_id": "verify_a", "depends_on": ["research_a"], "input_refs": []},
            {"step_id": "verify_b", "depends_on": ["research_b"], "input_refs": []},
            {"step_id": "merge", "depends_on": ["verify_a", "verify_b"], "input_refs": []},
        ]
        invalidation = steps_invalidated_by_input_change(
            steps,
            completed_ids={"research_a", "research_b", "verify_a", "verify_b"},
            changed_input_refs={"src_a"},
        )

        report = {
            "demo": "01_long_running_project",
            "project_id": project["id"],
            "decisions_preserved": len(after["decisions"]) == 1,
            "constraint_updated": "5" in (after["constraints"][0]["title"] + after["constraints"][0]["body"]),
            "old_constraint_gone": all("3 tool" not in (c["title"] + c["body"]) for c in after["constraints"]),
            "before_constraint_count": len(before["constraints"]),
            "after_constraint_count": len(after["constraints"]),
            "invalidation": invalidation,
            "untouched_branch_preserved": "research_b" in invalidation["reusable_step_ids"]
            and "verify_b" in invalidation["reusable_step_ids"],
            "providers_required": [],
            "fixtures": ["SQLite project_continuity", "plan_scheduler input invalidation"],
            "not_proven": ["Live LM Studio", "Windows GUI interrupt"],
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        ok = (
            report["decisions_preserved"]
            and report["constraint_updated"]
            and report["untouched_branch_preserved"]
        )
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
