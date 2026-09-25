"""F14 — Structured public trajectory export bridge (R22)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.experience import ExperienceStore
from Data.modules.cognition.meta_controller import MetaDecision
from Data.modules.cognition.neural_compute import NativeEffort, NeuralComputeBudget
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.task_model import TaskModelBuilder
from Data.modules.cognition.trajectory_export import (
    TrajectoryExportBridge,
    build_trajectory_from_experience,
    build_trajectory_from_run_snapshot,
    scrub_private_fields,
)
from Data.modules.cognition.types import (
    CognitiveBudgets,
    CognitiveRunStatus,
    ReasoningMode,
    ReasoningStrategy,
)


class ScrubPrivateCotTests(unittest.TestCase):
    def test_strips_nested_private_keys(self) -> None:
        raw = {
            "ok": 1,
            "reasoning_content": "SECRET",
            "nested": {"thinking": "nope", "public": True},
            "private_cot": "x",
        }
        cleaned = scrub_private_fields(raw)
        self.assertEqual(cleaned["ok"], 1)
        self.assertNotIn("reasoning_content", cleaned)
        self.assertNotIn("private_cot", cleaned)
        self.assertEqual(cleaned["nested"]["public"], True)
        self.assertNotIn("thinking", cleaned["nested"])


class TrajectoryBuildTests(unittest.TestCase):
    def test_verified_admitted_becomes_sft_record(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("Fix reconnect race with tests")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_VERIFIED,
            strategy=ReasoningStrategy.CODING_REPAIR,
            action_summaries=["RETRIEVE", "VERIFY"],
            verification_status="PASSED",
            evidence_refs=["ev-1"],
            mode="DEEP",
            neural_effort="HIGH",
            expected_gain=0.7,
        )
        admitted = store.admit(exp)
        self.assertTrue(admitted.admitted)
        traj = build_trajectory_from_experience(
            admitted,
            response_text="Race fixed by serializing reconnect.",
            run_id="run-1",
        )
        self.assertEqual(traj.export_class, "verified_sft")
        pub = traj.public_dict()
        self.assertTrue(pub["truth"]["no_private_cot"])
        self.assertTrue(pub["truth"]["auto_promote_forbidden"])
        self.assertTrue(pub["truth"]["structured_trajectory_bridge"])
        rec = traj.to_canonical_record()
        self.assertEqual(rec["labels"]["export_class"], "verified_sft")
        self.assertTrue(rec["truth"]["auto_promote_forbidden"])
        self.assertEqual(len(rec["messages"]), 2)

    def test_unverified_excluded_from_default_bundle(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("hello")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
            strategy=ReasoningStrategy.DIRECT,
            action_summaries=["RESPOND"],
            verification_status="UNMEASURED",
        )
        store.admit(exp)
        traj = build_trajectory_from_run_snapshot(
            {
                "run_id": "r2",
                "goal": "hello",
                "domain": task.domain,
                "status": CognitiveRunStatus.COMPLETED_UNVERIFIED.value,
                "response_text": "Hi",
                "verification_passed": None,
            },
            experience=exp,
        )
        self.assertEqual(traj.export_class, "unverified_excluded")
        bridge = TrajectoryExportBridge()
        bridge.record(traj)
        bundle = bridge.export_bundle()
        self.assertEqual(bundle["sft_record_count"], 0)
        self.assertEqual(bundle["trajectory_count"], 0)
        self.assertTrue(bundle["truth"]["export_is_not_training"])
        self.assertEqual(bundle["ingestion"]["status"], "exported_not_ingested")

    def test_failed_verification_seeds_preference_without_fabricating_preferred(self) -> None:
        traj = build_trajectory_from_run_snapshot(
            {
                "run_id": "r3",
                "goal": "cite sources",
                "domain": "research",
                "status": CognitiveRunStatus.COMPLETED_UNVERIFIED.value,
                "response_text": "Made-up citation",
                "verification_passed": False,
                "reasoning_content": "PRIVATE_SHOULD_GO",
            }
        )
        self.assertEqual(traj.export_class, "preference_candidate")
        bridge = TrajectoryExportBridge()
        bridge.record(traj)
        bundle = bridge.export_bundle()
        self.assertEqual(bundle["preference_seed_count"], 1)
        seed = bundle["preference_seeds"][0]
        self.assertIsNone(seed["preferred_id"])
        self.assertTrue(seed["truth"]["preference_labels_not_fabricated"])
        blob = str(bundle)
        self.assertNotIn("PRIVATE_SHOULD_GO", blob)


class RuntimeTrainingExportTests(unittest.TestCase):
    def test_finalize_records_trajectory_and_export_bundle(self) -> None:
        store = ExperienceStore()
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=False,
            belief_enabled=True,
            experience_learning=True,
            experience_store=store,
        )
        status = runtime.submit("Fix reconnect race with tests", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.decision = MetaDecision(
            mode=ReasoningMode.DEEP,
            strategy=ReasoningStrategy.CODING_REPAIR,
            budgets=CognitiveBudgets(),
            value_scores={},
            notes=(),
            neural_budgets=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
            expected_gain=0.66,
        )
        state.verification_passed = True
        state.response_text = "Applied lock around reconnect."
        runtime._finalize(state)

        self.assertIsNotNone(state.experience)
        self.assertTrue(state.experience["admitted"])
        traj_events = [
            e for e in state.events if e.get("event_type") == "trajectory_exported"
        ]
        self.assertEqual(len(traj_events), 1)
        self.assertEqual(traj_events[0]["payload"]["export_class"], "verified_sft")

        bundle = runtime.export_training_bundle()
        self.assertGreaterEqual(bundle["sft_record_count"], 1)
        self.assertTrue(bundle["truth"]["structured_trajectory_bridge"])
        self.assertTrue(bundle["truth"]["auto_promote_forbidden"])
        self.assertEqual(bundle["ingestion"]["status"], "exported_not_ingested")
        self.assertTrue(bundle["ingestion"]["dataset_write_requires_explicit_step"])
        for rec in bundle["sft_records"]:
            self.assertNotIn("reasoning_content", rec)
            self.assertTrue(rec["metadata"]["auto_promote_forbidden"])


if __name__ == "__main__":
    unittest.main()
