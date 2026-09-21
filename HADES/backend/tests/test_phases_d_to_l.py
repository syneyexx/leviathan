"""Integration tests for phases D–L work-skills completion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claim_register import ClaimRegister
from code_intel import analyze_file
from compute_fabric import LocalExecutor
from evals.quality_suite import run_quality_suite
from gen2 import Gen2Services, Gen2Store
from host_capability import check_host_capabilities
from preview_runtime import BrowserAdapter, PreviewManager
from project_map import build_project_map, find_change_impact
from reasoning.run_context import adapt_from_mission, compact_for_summary, record_failed_attempt
from run_leases import ExecutionLeaseStore


class PhasesDELTests(unittest.TestCase):
    def test_quality_suite_has_at_least_30(self) -> None:
        report = run_quality_suite()
        self.assertGreaterEqual(report["total"], 42)
        self.assertEqual(report["passed"], report["total"], [s for s in report["scores"] if not s["passed"]])
        self.assertIn("quality_v1", report["suite"])

    def test_gen2_quality_suite_mode(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Gen2Store(str(Path(tmp.name) / "g.db"))
        svc = Gen2Services(store, data_root=Path(tmp.name))
        report = svc.run_eval_lab(suite="quality", mode="quality_suite")
        self.assertEqual(report["mode"], "quality_suite")
        self.assertGreaterEqual((report.get("summary") or {}).get("total", 0), 30)

    def test_run_context_compaction(self) -> None:
        ctx = adapt_from_mission(
            {"id": "m1", "goal": "G", "acceptance_criteria": ["a"], "status": "running", "verification": {"status": "pending"}}
        )
        ctx = record_failed_attempt(ctx, reason="timeout")
        compact = compact_for_summary(ctx)
        self.assertEqual(compact["goal"], "G")
        self.assertEqual(len(compact["failed_attempts"]), 1)

    def test_promoted_skill_executes(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Gen2Store(str(Path(tmp.name) / "g.db"))
        svc = Gen2Services(store, data_root=Path(tmp.name))
        skill = svc.extract_skill_candidate(
            name="exec-skill",
            workflow=[
                {"action": "echo", "inputs": {"message": "hi"}},
                {"action": "assert_nonempty", "inputs": {"value": "x"}},
            ],
            pattern_source="test",
        )
        bench = svc.benchmark_skill(skill["id"])
        self.assertEqual(bench["status"], "benchmarked")
        promoted = svc.promote_skill(skill["id"], human_approved=True)
        self.assertEqual(promoted["status"], "promoted")
        executed = svc.execute_promoted_skill(skill["id"])
        self.assertTrue(executed["passed"])
        self.assertTrue(executed["executed"])
        deactivated = svc.deactivate_skill(skill["id"])
        self.assertEqual(deactivated["status"], "deactivated")
        with self.assertRaises(ValueError):
            svc.execute_promoted_skill(skill["id"])

    def test_committee_external_evidence_fields(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Gen2Store(str(Path(tmp.name) / "g.db"))
        svc = Gen2Services(store, data_root=Path(tmp.name))
        session = svc.run_committee(
            "NVIDIA earnings outlook",
            evidence=["NVIDIA earnings beat estimates and guidance raised"],
        )
        consensus = session.get("consensus") or {}
        self.assertEqual(consensus.get("basis"), "position_results_plus_external_evidence")
        self.assertIn("evidence_checks", consensus)

    def test_pause_requested_vs_paused(self) -> None:
        leases = ExecutionLeaseStore()
        leases.request_pause("t1")
        self.assertTrue(leases.snapshot("t1")["pause_requested"])
        self.assertFalse(leases.snapshot("t1")["paused"])
        self.assertFalse(leases.should_start_new_step("t1"))
        leases.mark_paused("t1")
        self.assertTrue(leases.snapshot("t1")["paused"])
        self.assertFalse(leases.snapshot("t1")["pause_requested"])

    def test_claim_circular_guard(self) -> None:
        reg = ClaimRegister()
        cid = reg.add_claim(
            text="derived",
            provenance="knowledge:derived-ai",
            source_kind="derived_analysis",
        )
        self.assertFalse(reg.allows_independent_confirmation(cid, evidence_id="knowledge:derived-ai"))
        new_id = reg.supersede(cid, new_text="corrected", provenance="user", reason="fix")
        self.assertTrue(new_id)
        self.assertEqual(reg.get(cid)["verification_status"], "SUPERSEDED")

    def test_host_preview_compute_browser(self) -> None:
        host = check_host_capabilities()
        self.assertIn("python", host["checks"])
        self.assertIn("isolation", host)
        plan = PreviewManager().plan_preview(Path("."), kind="static_check")
        self.assertTrue(plan["supported"])
        caps = BrowserAdapter().capabilities()
        self.assertTrue(caps["vision_model_required_for_image_judge"])
        job = LocalExecutor().submit({"op": "ping"})
        self.assertEqual(job["status"], "completed")

    def test_code_intel_and_map(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "app.py").write_text("import json\nfrom x import y\ndef add(a,b):\n    return a+b\n", encoding="utf-8")
        (root / "test_app.py").write_text("from app import add\n", encoding="utf-8")
        info = analyze_file(root, "app.py")
        self.assertGreaterEqual(len(info["imports"]), 2)
        pmap = build_project_map(root, refresh_symbols=True)
        self.assertIn("app.py", pmap["entrypoints"])
        impact = find_change_impact(root, symbol="add")
        self.assertGreaterEqual(impact["counts"]["references"], 1)

    def test_verify_host_script_exists(self) -> None:
        script = Path(__file__).resolve().parents[2] / "VERIFY_HADES_HOST.bat"
        self.assertTrue(script.is_file())


if __name__ == "__main__":
    unittest.main()
