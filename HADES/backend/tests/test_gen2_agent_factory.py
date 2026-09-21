"""Characterization tests for Gen2 Agent Factory extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.agent_factory import (
    benchmark_skill,
    execute_promoted_skill,
    extract_skill_candidate,
    promote_skill,
    select_promoted_skill,
    skill_definition_content_hash,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class AgentFactoryModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "factory.db"))
        self.events: list[str] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append(event_type)
            return {"run_id": run_id, "event_type": event_type}

        self.record = _record

        def _eval(**kwargs):
            return self.store.save_eval_run(
                suite=str(kwargs.get("suite") or "skill"),
                mode="deterministic_software",
                model_id=str(kwargs.get("model_id") or "software:skill"),
                summary={"pass_rate": 1.0, "model_invoked": False, "not_model_quality": True},
                scores=[],
            )

        self.eval_lab = _eval

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_hash_ignores_versioning(self) -> None:
        a = {"workflow": ["echo"], "versioning": {"version": 1}}
        b = {"workflow": ["echo"], "versioning": {"version": 9}}
        self.assertEqual(skill_definition_content_hash(a), skill_definition_content_hash(b))

    def test_free_text_benchmark_fails(self) -> None:
        skill = extract_skill_candidate(
            self.store,
            self.record,
            name="free-text",
            workflow=["do something clever with NVIDIA"],
            pattern_source="test",
        )
        bench = benchmark_skill(self.store, self.record, skill["id"], run_eval_lab=self.eval_lab)
        self.assertEqual(bench["status"], "failed_benchmark")
        self.assertEqual((bench.get("benchmark") or {}).get("status"), "failed")

    def test_handler_workflow_promote_execute(self) -> None:
        skill = extract_skill_candidate(
            self.store,
            self.record,
            name="echo-skill",
            workflow=[{"action": "echo", "inputs": {"message": "hi"}}],
            pattern_source="test",
        )
        bench = benchmark_skill(self.store, self.record, skill["id"], run_eval_lab=self.eval_lab)
        self.assertEqual(bench["status"], "benchmarked")
        with self.assertRaises(ValueError):
            promote_skill(self.store, self.record, skill["id"], human_approved=False)
        promoted = promote_skill(self.store, self.record, skill["id"], human_approved=True)
        self.assertEqual(promoted["status"], "promoted")
        executed = execute_promoted_skill(self.store, self.record, skill["id"])
        self.assertTrue(executed["passed"])
        matched = select_promoted_skill(self.store, "Please run echo-skill now")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], skill["id"])

    def test_services_delegate(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        skill = svc.extract_skill_candidate(
            name="svc-echo",
            workflow=[{"action": "echo", "inputs": {"message": "ok"}}],
            pattern_source="test",
        )
        self.assertEqual(svc.benchmark_skill(skill["id"])["status"], "benchmarked")
        self.assertEqual(svc.promote_skill(skill["id"], human_approved=True)["status"], "promoted")


if __name__ == "__main__":
    unittest.main()
