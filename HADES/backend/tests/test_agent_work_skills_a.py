"""Phase A regressions: quality foundation defects on ed8883c / PR #35 tip.

Each test documents: reproduced → fixed behavior.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import ArtifactService
from database import Database
from gen2 import Gen2Services, Gen2Store
from gen2.output_contracts import ModelOutputValidationError, validate_committee_stance
from gen2.skill_runtime import execute_skill_workflow
from platform_db import PlatformDatabase


def _wire_artifacts(root: Path) -> ArtifactService:
    db_path = str(root / "arts.db")
    Database(db_path).initialize()
    pdb = PlatformDatabase(db_path)
    pdb.initialize()
    return ArtifactService(pdb, root)


def _mission_deliverables(arts: ArtifactService, *, task_id: str) -> list[dict]:
    report = arts.create_text_result(
        name="mission_report.md",
        text="# report\nverified\n",
        mime_type="text/markdown",
        kind="generated",
        task_id=task_id,
    )
    index = arts.create_text_result(
        name="evidence_index.json",
        text='{"ok": true}',
        mime_type="application/json",
        kind="generated",
        task_id=task_id,
    )
    return [report, index]


class PhaseA1Regressions(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "gen2.db"))
        self.arts = _wire_artifacts(self.root)
        self.svc = Gen2Services(self.store, data_root=self.root, artifact_service=self.arts)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_benchmark_skill_rejects_free_text_without_handlers(self) -> None:
        """A1: free-text workflow steps must not pass without execution."""
        skill = self.svc.extract_skill_candidate(
            name="text-only-skill",
            workflow=["scope the problem", "retrieve evidence", "synthesize answer"],
            pattern_source="regression",
        )
        bench = self.svc.benchmark_skill(skill["id"])
        self.assertEqual(bench["status"], "failed_benchmark")
        results = (bench.get("benchmark") or {}).get("step_results") or []
        self.assertTrue(results)
        self.assertTrue(all(r.get("detail") == "unknown_action:no_handler" for r in results))
        self.assertFalse(any(r.get("executed") for r in results))

    def test_benchmark_skill_executes_known_handlers(self) -> None:
        skill = self.svc.extract_skill_candidate(
            name="executable-skill",
            workflow=[
                {"action": "set_ctx_flag", "inputs": {"flag": "prepared"}},
                {"action": "check_ctx_flag", "inputs": {"flag": "prepared"}},
                {
                    "action": "record_artifact",
                    "inputs": {"name": "proof.txt", "content": "ok"},
                    "success_criteria": ["output:artifact"],
                },
            ],
            pattern_source="regression",
        )
        bench = self.svc.benchmark_skill(skill["id"])
        self.assertEqual(bench["status"], "benchmarked")
        bm = bench.get("benchmark") or {}
        self.assertEqual(bm.get("status"), "passed")
        self.assertEqual(bm.get("executed_count"), 3)
        self.assertTrue(bm.get("artifacts"))

    def test_sync_mission_rejects_pending_verification_and_pending_steps(self) -> None:
        """A1/A2: pending verification + pending steps must not become completed/passed."""
        mission = self.svc.compile_mission("Pending sync must fail")
        self.store.update_mission(
            mission["id"],
            status="running",
            task_id="task_pending_sync",
            verification={"required": True, "status": "pending"},
        )
        updated = self.svc.sync_mission_from_task(
            "task_pending_sync",
            status="completed",
            verification={"status": "pending", "required": True},
            step_summary={"total": 3, "completed": 1, "failed": 0, "pending": 2},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "failed")
        ver = updated.get("verification") or {}
        self.assertEqual(ver.get("status"), "failed")
        acceptance = ver.get("acceptance") or {}
        self.assertFalse(acceptance.get("passed"))
        blockers = acceptance.get("blockers") or []
        self.assertIn("pending_steps", blockers)
        self.assertTrue(any("verification" in b for b in blockers))

    def test_sync_mission_requires_assessed_criteria_and_evidence(self) -> None:
        mission = self.svc.compile_mission("Evidence required")
        self.store.update_mission(mission["id"], status="running", task_id="task_ok_sync")
        # Explicit passed without criteria assessment while mission has acceptance → fail.
        updated = self.svc.sync_mission_from_task(
            "task_ok_sync",
            status="completed",
            verification={"status": "passed", "required": True, "source": "work_runtime"},
            step_summary={"total": 2, "completed": 2, "failed": 0, "pending": 0},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "failed")
        # With assessed criteria + evidence refs → completed.
        updated2 = self.svc.sync_mission_from_task(
            "task_ok_sync",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "work_runtime",
                "criteria_checklist": [
                    {"criterion": "done", "met": True},
                    {"criterion": "verified", "met": True},
                ],
                "evidence_refs": ["step:1", "step:2"],
            },
            step_summary={"total": 2, "completed": 2, "failed": 0, "pending": 0},
        )
        # Mission already failed terminal — cannot re-complete without retry path.
        assert updated2 is not None
        self.assertEqual(updated2["status"], "failed")

        mission2 = self.svc.compile_mission("Evidence required clean")
        self.store.update_mission(mission2["id"], status="running", task_id="task_ok_sync2")
        arts = _mission_deliverables(self.arts, task_id="task_ok_sync2")
        ok = self.svc.sync_mission_from_task(
            "task_ok_sync2",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "work_runtime",
                "criteria_checklist": [{"criterion": "done", "met": True}],
                "evidence_refs": ["step:1", arts[0]["id"], arts[1]["id"]],
                "artifacts": arts,
                "task_id": "task_ok_sync2",
            },
            step_summary={"total": 1, "completed": 1, "failed": 0, "pending": 0},
        )
        assert ok is not None
        self.assertEqual(ok["status"], "completed")
        self.assertEqual((ok.get("verification") or {}).get("status"), "passed")

    def test_budget_rejects_negative_and_requires_reservation_contract(self) -> None:
        mission = self.svc.compile_mission("Budget contract")
        self.store.update_mission(
            mission["id"],
            budgets={"max_tool_calls": 5, "ledger": {"reserved": {}, "consumed": {}, "entries": []}},
        )
        with self.assertRaises(ValueError):
            self.svc.reserve_mission_budget(mission["id"], key="max_tool_calls", amount=-1)
        with self.assertRaises(ValueError):
            self.svc.reserve_mission_budget(mission["id"], key="not_a_real_budget", amount=1)
        reserved = self.svc.reserve_mission_budget(
            mission["id"], key="max_tool_calls", amount=2, step_id="s1", idempotency_key="r1"
        )
        rid = reserved.get("reservation_id")
        self.assertTrue(rid)
        # Idempotent reserve with same key returns same ledger without double-counting.
        again = self.svc.reserve_mission_budget(
            mission["id"], key="max_tool_calls", amount=2, step_id="s1", idempotency_key="r1"
        )
        self.assertEqual(again["ledger"]["reserved"]["max_tool_calls"], 2.0)
        with self.assertRaises(ValueError):
            self.svc.consume_mission_budget(mission["id"], key="max_tool_calls", amount=1)
        consumed = self.svc.consume_mission_budget(
            mission["id"], key="max_tool_calls", amount=1, reservation_id=rid, step_id="s1"
        )
        self.assertEqual(consumed["ledger"]["consumed"]["max_tool_calls"], 1.0)
        released = self.svc.release_mission_budget(mission["id"], reservation_id=rid, reason="unused")
        self.assertEqual(released["ledger"]["reservations"][rid]["status"], "released")
        self.assertEqual(released["ledger"]["reserved"].get("max_tool_calls", 0.0), 0.0)

    def test_budget_concurrent_reserves_do_not_overspend(self) -> None:
        mission = self.svc.compile_mission("Budget race")
        self.store.update_mission(
            mission["id"],
            budgets={"max_tool_calls": 3, "ledger": {"reserved": {}, "consumed": {}, "entries": []}},
        )
        errors: list[str] = []
        ok_count = {"n": 0}
        lock = threading.Lock()

        def worker(i: int) -> None:
            try:
                self.svc.reserve_mission_budget(
                    mission["id"], key="max_tool_calls", amount=2, step_id=f"s{i}", idempotency_key=f"c{i}"
                )
                with lock:
                    ok_count["n"] += 1
            except ValueError as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ledger = self.svc.mission_budget_ledger(mission["id"])
        reserved = float(ledger["ledger"]["reserved"].get("max_tool_calls") or 0)
        self.assertLessEqual(reserved, 3.0 + 1e-9)
        self.assertGreaterEqual(len(errors), 1)
        self.assertEqual(ok_count["n"] + len(errors), 4)

    def test_role_stance_preserves_zero_confidence_and_rejects_false_string(self) -> None:
        """A1/A4: confidence=0 must stay 0; string 'false' must not become True."""
        validated = validate_committee_stance(
            {"claim": "No support", "confidence": 0, "supported": False, "rationale": "none"}
        )
        self.assertEqual(validated["confidence"], 0.0)
        self.assertFalse(validated["supported"])
        validated2 = validate_committee_stance(
            {"claim": "No support", "confidence": 0.0, "supported": "false", "rationale": "none"}
        )
        self.assertFalse(validated2["supported"])
        with self.assertRaises(ModelOutputValidationError):
            validate_committee_stance({"claim": "x", "confidence": 0, "supported": "maybe"})

        async def chat_fn(payload):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"claim":"c","confidence":0,"supported":"false","rationale":"r"}',
                        }
                    }
                ]
            }

        stance = asyncio.run(
            self.svc._role_stance_live_async(
                "skeptic",
                "topic",
                ["some evidence"],
                chat_fn=chat_fn,
                model_id="m",
                focus="risk",
            )
        )
        self.assertEqual(stance["confidence"], 0.0)
        self.assertFalse(stance["supported"])
        self.assertTrue(stance["model_invoked"])

    def test_run_model_eval_connection_failures_do_not_claim_invoked(self) -> None:
        async def chat_fn(payload):
            raise ConnectionError("lm down")

        report = asyncio.run(self.svc.run_model_eval(model_id="down-model", chat_fn=chat_fn))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse((report.get("summary") or {}).get("model_invoked"))
        self.assertEqual((report.get("summary") or {}).get("reason"), "all_model_connections_failed")
        self.assertTrue((report.get("summary") or {}).get("not_coding_or_research_benchmark"))
        self.assertTrue(all(not s.get("model_invoked") for s in report.get("scores") or []))

    def test_live_eval_default_prompts_are_smoke_not_quality_benchmark(self) -> None:
        async def chat_fn(payload):
            text = " ".join(str((m or {}).get("content") or "") for m in (payload.get("messages") or [])).lower()
            content = "OK" if "exactly: ok" in text else "honest"
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}

        report = asyncio.run(self.svc.run_model_eval(model_id="smoke-model", chat_fn=chat_fn))
        summary = report.get("summary") or {}
        self.assertTrue(summary.get("model_invoked"))
        self.assertEqual(summary.get("quality_layer"), "infrastructure_smoke")
        self.assertTrue(summary.get("not_coding_or_research_benchmark"))
        self.assertTrue(summary.get("not_model_quality"))


class SkillRuntimeUnitTests(unittest.TestCase):
    def test_execute_workflow_unknown_action_fails(self) -> None:
        result = execute_skill_workflow(["invent a step"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["executed_count"], 0)


if __name__ == "__main__":
    unittest.main()
