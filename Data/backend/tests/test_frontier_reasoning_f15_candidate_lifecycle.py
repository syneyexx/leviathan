"""F15 — Candidate training lifecycle wired from cognition trajectories (R23)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.experience import ExperienceStore
from Data.modules.cognition.meta_controller import MetaDecision
from Data.modules.cognition.neural_compute import NativeEffort, NeuralComputeBudget
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.types import (
    CognitiveBudgets,
    CognitiveRunStatus,
    ReasoningMode,
    ReasoningStrategy,
)
from Data.modules.training import (
    ActiveLearningMiner,
    CandidatePhase,
    CandidateSource,
    CandidateTrainingLifecycle,
)


class CandidateLifecycleUnitTests(unittest.TestCase):
    def test_accept_bundle_pending_then_govern_then_ingest(self) -> None:
        lifecycle = CandidateTrainingLifecycle()
        bundle = {
            "sft_records": [
                {
                    "id": "traj-1",
                    "text": "Goal: fix race\nResponse: locked",
                    "messages": [
                        {"role": "user", "content": "fix race"},
                        {"role": "assistant", "content": "locked"},
                    ],
                    "labels": {
                        "export_class": "verified_sft",
                        "verification_status": "PASSED",
                        "domain": "coding",
                        "admitted": True,
                    },
                    "metadata": {
                        "run_id": "run-1",
                        "experience_id": "exp-1",
                        "auto_promote_forbidden": True,
                    },
                }
            ],
            "preference_seeds": [
                {
                    "trajectory_id": "traj-2",
                    "run_id": "run-2",
                    "prompt": "cite sources",
                    "rejected_preview": "made up",
                    "verification_status": "FAILED",
                    "preferred_id": None,
                }
            ],
            "active_learning": [
                {
                    "candidate_id": "al-1",
                    "run_id": "run-3",
                    "reason": "verification_failed",
                    "kind": "failure",
                    "goal": "check facts",
                    "domain": "research",
                }
            ],
            "trajectories": [],
        }
        created = lifecycle.accept_export_bundle(bundle)
        self.assertEqual(len(created), 3)
        self.assertTrue(all(c.phase == CandidatePhase.PENDING for c in created))
        self.assertTrue(
            any(c.source == CandidateSource.VERIFIED_SFT for c in created)
        )
        self.assertTrue(
            any(c.source == CandidateSource.PREFERENCE_SEED for c in created)
        )
        self.assertTrue(
            any(c.source == CandidateSource.ACTIVE_LEARNING for c in created)
        )
        for c in created:
            self.assertTrue(c.public_dict()["truth"]["auto_promote_forbidden"])
            self.assertTrue(
                c.public_dict()["truth"]["wired_from_cognition_trajectories"]
            )

        sft = next(c for c in created if c.source == CandidateSource.VERIFIED_SFT)
        with self.assertRaises(ValueError):
            lifecycle.mark_ingested(sft.candidate_id, operator="ops")

        governed = lifecycle.govern(sft.candidate_id, operator="ops", note="ok")
        self.assertEqual(governed.phase, CandidatePhase.GOVERNED)
        self.assertTrue(governed.governed)

        ingested = lifecycle.mark_ingested(
            sft.candidate_id, operator="ops", mixture_ref="mix-1"
        )
        self.assertEqual(ingested.phase, CandidatePhase.INGESTED)
        self.assertTrue(ingested.ingested)
        self.assertTrue(ingested.metadata["training_job_not_started"])
        self.assertTrue(ingested.metadata["auto_promote_forbidden"])
        self.assertEqual(ingested.metadata["mixture_ref"], "mix-1")

        summary = lifecycle.public_summary()
        self.assertEqual(summary["by_phase"]["ingested"], 1)
        self.assertEqual(summary["by_phase"]["pending"], 2)
        self.assertTrue(summary["truth"]["candidate_lifecycle_wired_from_cognition"])

    def test_unverified_trajectory_not_registered_as_sft(self) -> None:
        lifecycle = CandidateTrainingLifecycle()
        created = lifecycle.accept_export_bundle(
            {
                "sft_records": [],
                "preference_seeds": [],
                "active_learning": [],
                "trajectories": [
                    {
                        "trajectory_id": "t-u",
                        "run_id": "r",
                        "goal": "hi",
                        "export_class": "unverified_excluded",
                        "messages": [{"role": "user", "content": "hi"}],
                    }
                ],
            }
        )
        self.assertEqual(created, [])

    def test_shared_miner_govern_surface(self) -> None:
        miner = ActiveLearningMiner()
        lifecycle = CandidateTrainingLifecycle(miner=miner)
        created = lifecycle.accept_export_bundle(
            {
                "sft_records": [],
                "preference_seeds": [],
                "active_learning": [
                    {
                        "run_id": "r9",
                        "reason": "budget_exhausted",
                        "kind": "resource",
                        "goal": "deep research",
                    }
                ],
                "trajectories": [],
            }
        )
        cid = created[0].candidate_id
        self.assertIn(cid, miner._pending)
        lifecycle.govern(cid, operator="alice")
        self.assertTrue(miner._pending[cid].governed)


class RuntimeLifecycleWireTests(unittest.TestCase):
    def test_runtime_sync_from_verified_finalize(self) -> None:
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
        state = runtime._require(status["run_id"])
        state.decision = MetaDecision(
            mode=ReasoningMode.DEEP,
            strategy=ReasoningStrategy.CODING_REPAIR,
            budgets=CognitiveBudgets(),
            value_scores={},
            notes=(),
            neural_budgets=NeuralComputeBudget(native_effort=NativeEffort.HIGH),
            expected_gain=0.55,
        )
        state.verification_passed = True
        state.response_text = "Serialized reconnect."
        runtime._finalize(state)

        lifecycle = CandidateTrainingLifecycle()
        out = runtime.sync_training_candidates(lifecycle)
        self.assertGreaterEqual(len(out["created"]), 1)
        self.assertTrue(out["truth"]["wired_from_cognition_trajectories"])
        self.assertTrue(out["truth"]["sync_does_not_train"])
        sft = [
            c
            for c in lifecycle.list_candidates()
            if c.source == CandidateSource.VERIFIED_SFT
        ]
        self.assertTrue(sft)
        self.assertEqual(sft[0].phase, CandidatePhase.PENDING)


if __name__ == "__main__":
    unittest.main()
