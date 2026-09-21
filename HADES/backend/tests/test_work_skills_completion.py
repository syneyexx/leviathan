"""Completion tests for remaining A→L wiring (leases, claims, reviewer, scenarios)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claim_register import ClaimRegister, filter_circular_knowledge
from coding_reviewer import review_coding_result
from compute_fabric import get_local_executor
from evals.quality_suite import run_live_quality_layer, run_quality_suite
from gen2 import Gen2Services, Gen2Store
from preview_runtime import get_preview_manager
from reasoning.run_context import adapt_from_working_state, compact_for_summary
from retrieval_compare import compare_retrieval_methods
from run_leases import ExecutionLeaseStore


class CompletionWiringTests(unittest.TestCase):
    def test_quality_suite_at_least_39(self) -> None:
        report = run_quality_suite()
        self.assertGreaterEqual(report["total"], 42)
        self.assertEqual(report["passed"], report["total"], [s for s in report["scores"] if not s["passed"]])

    def test_live_quality_unmeasured_without_lm(self) -> None:
        report = run_live_quality_layer(chat_fn=None)
        self.assertEqual(report["status"], "unmeasured")
        self.assertFalse(report["model_invoked"])

    def test_lease_persist_and_restore_pause(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "leases.json"
        store = ExecutionLeaseStore(path)
        acquired = store.acquire("step:t1:s1", worker_id="w1", ttl_s=120)
        self.assertTrue(acquired["ok"])
        store.request_pause("t1")
        # Simulate process restart
        store2 = ExecutionLeaseStore(path)
        self.assertTrue(store2.snapshot("t1")["pause_requested"])
        self.assertIn("step:t1:s1", store2.dump()["leases"])
        # Restore from durable task control_state
        store3 = ExecutionLeaseStore()
        restored = store3.restore_control_from_tasks(
            [{"id": "t2", "control_state": "paused"}, {"id": "t3", "control_state": "pause_requested"}]
        )
        self.assertEqual(restored["paused"], 1)
        self.assertTrue(store3.snapshot("t2")["paused"])
        self.assertTrue(store3.snapshot("t3")["pause_requested"])
        self.assertFalse(store3.should_start_new_step("t2"))

    def test_claim_sqlite_and_circular_filter(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "claims.sqlite"
        reg = ClaimRegister(db)
        cid = reg.add_claim(text="x", provenance="knowledge:derived:1", source_kind="derived_analysis", task_id="t1")
        reg2 = ClaimRegister(db)
        self.assertIsNotNone(reg2.get(cid))
        self.assertFalse(reg2.allows_independent_confirmation(cid, evidence_id="knowledge:derived:1"))
        independent, derived = filter_circular_knowledge(
            [
                {"uri": "file:a.md", "source_type": "markdown"},
                {"uri": "knowledge:derived:9", "source_type": "ai_answer"},
            ]
        )
        self.assertEqual(len(independent), 1)
        self.assertEqual(len(derived), 1)

    def test_run_context_compact_survives(self) -> None:
        ctx = adapt_from_working_state(
            run_id="r1",
            kind="work",
            goal="ship feature",
            working_state={"decisions": ["use sqlite"], "open_criteria": ["tests green"], "constraints": ["offline"]},
            task_id="t1",
        )
        compact = compact_for_summary(ctx)
        self.assertEqual(compact["goal"], "ship feature")
        self.assertIn("use sqlite", compact["decisions"])
        self.assertIn("tests green", compact["open_criteria"])

    def test_coding_reviewer_and_async_lm_propose(self) -> None:
        from coding_agent import CodingAgentService, ExploreHit
        from build_agent import BuildAgentService

        review = review_coding_result(
            goal="add field",
            diff_text="+ name: str\n",
            changed_files=["api.ts"],
            test_result={"status": "passed"},
        )
        self.assertIn(review["status"], {"accept", "needs_attention"})

        async def fake_chat(payload):  # noqa: ANN001
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "edits": [
                                        {
                                            "path": "app.py",
                                            "action": "replace",
                                            "content": "x=1\n",
                                            "old_content": "",
                                            "base_hash": "abc",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        # Under a running loop, propose must not skip with lm_propose_skipped_running_loop.
        async def _inner() -> None:
            svc = CodingAgentService(BuildAgentService(Path(tempfile.mkdtemp()), None))  # type: ignore[arg-type]
            # BuildAgent may need real artifact service — only exercise propose_edits path via heuristic miss.
            hits = [
                ExploreHit(path="app.py", reason="test", score=1.0, content_hash="abc"),
            ]
            # Force LM path: empty heuristic by using an unrelated goal with no pattern.
            tmp = tempfile.TemporaryDirectory()
            root = Path(tmp.name)
            (root / "app.py").write_text("print(1)\n", encoding="utf-8")
            hits = [ExploreHit(path="app.py", reason="test", score=1.0, content_hash="abc")]
            # Monkeypatch hash check loosely via propose with chat_fn under running loop
            from coding_agent import _invoke_chat_fn

            async def _call():
                return await fake_chat({})

            response, meta = _invoke_chat_fn(fake_chat, _call)
            self.assertIsNotNone(response)
            self.assertNotIn("lm_propose_skipped_running_loop", meta.get("note", ""))
            tmp.cleanup()

        asyncio.run(_inner())

    def test_committee_role_selection_complexity(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Gen2Store(str(Path(tmp.name) / "g.db"))
        svc = Gen2Services(store, data_root=Path(tmp.name))
        session = svc.run_committee("What is RAM?", evidence=["RAM is memory"])
        selection = (session.get("consensus") or {}).get("role_selection") or {}
        self.assertEqual(selection.get("complexity"), "simple")
        self.assertLessEqual(int(selection.get("role_count") or 99), 3)

    def test_preview_and_compute_contracts(self) -> None:
        mgr = get_preview_manager()
        plan = mgr.plan_preview(Path("."), kind="static_check")
        self.assertTrue(plan["supported"])
        started = mgr.start_preview("run-x", Path("."), kind="auto")
        self.assertFalse(started.get("started"))
        status = mgr.status("run-x")
        self.assertFalse(status.get("running"))
        ex = get_local_executor()
        job = ex.submit({"op": "echo", "payload": {"message": "hi"}})
        self.assertEqual(job["status"], "completed")
        self.assertTrue(ex.status(job["id"])["ok"])

    def test_retrieval_compare(self) -> None:
        report = compare_retrieval_methods(Path(__file__).resolve().parents[1], query="ClaimRegister", symbol="ClaimRegister")
        self.assertIn("comparison", report)
        self.assertFalse(report["embeddings"]["used"])

    def test_user_scenario_skill_reuse(self) -> None:
        """Scenario 7: candidate → benchmark → promote → execute."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Gen2Store(str(Path(tmp.name) / "g.db"))
        svc = Gen2Services(store, data_root=Path(tmp.name))
        skill = svc.extract_skill_candidate(
            name="scenario-skill",
            workflow=[
                {"action": "echo", "inputs": {"message": "hi"}},
                {"action": "assert_nonempty", "inputs": {"value": "ok"}},
            ],
            pattern_source="scenario",
        )
        bench = svc.benchmark_skill(skill["id"])
        self.assertEqual(bench["status"], "benchmarked")
        promoted = svc.promote_skill(skill["id"], human_approved=True)
        self.assertEqual(promoted["status"], "promoted")
        executed = svc.execute_promoted_skill(skill["id"])
        self.assertTrue(executed["passed"])


if __name__ == "__main__":
    unittest.main()
