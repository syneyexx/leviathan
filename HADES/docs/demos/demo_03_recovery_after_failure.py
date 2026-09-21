#!/usr/bin/env python3
"""Demo 03 — recovery after failure (contentful mission replan).

Compiles a mission, simulates a failed step, runs replan_mission, and shows
a wave diff / alternate tool — without inventing success. No LM Studio required.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from gen2.mission_control import compile_mission, replan_mission
from gen2.store import Gen2Store


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = Gen2Store(str(Path(tmp) / "demo03.db"))
        events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            events.append(row)
            return row

        mission = compile_mission(store, _record, "Finance NVIDIA earnings depth")
        store.update_mission(
            mission["id"],
            status="blocked",
            verification={
                "status": "failed",
                "step_summary": {
                    "completed_ids": ["s_scope"],
                    "failed_ids": ["s_sources"],
                    "total": 6,
                    "completed": 1,
                    "failed": 1,
                },
            },
        )
        before = store.get_mission(mission["id"])
        assert before is not None
        before_tools = None
        for wave in (before.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_sources":
                    before_tools = list(step.get("tools") or [])

        out = replan_mission(
            store,
            _record,
            mission["id"],
            "tool",
            note="portfolio demo: sources tool failed",
            failed_step_id="s_sources",
        )
        after_tools = None
        for wave in (out.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_sources":
                    after_tools = list(step.get("tools") or [])

        contentful = str(out.get("replan_kind") or "") == "contentful"
        changed = before_tools != after_tools and after_tools is not None
        ok = contentful and changed and not out.get("no_valid_alternative")
        payload = {
            "demo": "03_recovery_after_failure",
            "ok": ok,
            "mission_id": mission["id"],
            "replan_kind": out.get("replan_kind"),
            "before_tools": before_tools,
            "after_tools": after_tools,
            "wave_diff_keys": sorted((out.get("wave_diff") or {}).keys()),
            "no_valid_alternative": out.get("no_valid_alternative"),
            "note": "Recovery changes the plan; it does not claim the original failure succeeded.",
        }
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
