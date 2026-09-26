"""W11 — Verified experience, active learning, trajectory export, training honesty."""

from __future__ import annotations

import unittest

from Data.modules.cognition.experience import ExperienceStore, VerifiedExperience
from Data.modules.cognition.task_model import TaskModel
from Data.modules.cognition.trajectory_export import (
    export_training_trajectory,
    trajectories_to_dataset_rows,
)
from Data.modules.cognition.types import CognitiveRunStatus, ReasoningStrategy, RiskClass
from Data.modules.training.active_learning import (
    AL_KINDS,
    ActiveLearningMiner,
    TrainingCandidateLifecycle,
)
from Data.modules.training.capabilities import probe_training_capabilities


def _task(goal: str = "test goal", domain: str = "general") -> TaskModel:
    return TaskModel(
        task_id="t1",
        run_id="r1",
        raw_request=goal,
        goal=goal,
        task_type="qa",
        domain=domain,
        risk_class=RiskClass.LOW,
        privacy_class="standard",
    )


class ExperienceAggregateTests(unittest.TestCase):
    def test_aggregate_and_search(self) -> None:
        store = ExperienceStore()
        ok = store.build_from_run(
            task=_task(),
            status=CognitiveRunStatus.COMPLETED_VERIFIED,
            strategy=ReasoningStrategy.DIRECT,
            action_summaries=["RESPOND"],
            verification_status="PASSED",
        )
        bad = store.build_from_run(
            task=_task(goal="fail case", domain="coding"),
            status=CognitiveRunStatus.FAILED,
            strategy=ReasoningStrategy.DIRECT,
            action_summaries=["TOOL"],
            verification_status="FAILED",
            failures=["tool_timeout"],
        )
        store.admit(ok)
        store.admit(bad)
        stats = store.aggregate_stats()
        self.assertEqual(stats["admitted"], 1)
        self.assertEqual(stats["rejected"], 1)
        self.assertIn("coding", stats["by_domain"])
        self.assertTrue(stats["truth"]["unverified_is_not_training_truth"])
        hits = store.search("test goal")
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].admitted)


class ActiveLearningLifecycleTests(unittest.TestCase):
    def test_required_kinds_and_govern_before_dataset(self) -> None:
        miner = ActiveLearningMiner()
        events = [{"kind": k, "prompt": "p", "content": "c", "source_ref": k} for k in sorted(AL_KINDS)]
        created = miner.mine_from_events(events)
        self.assertEqual(len(created), len(AL_KINDS))
        self.assertTrue(all(c.lifecycle == "CANDIDATE" for c in created))
        self.assertEqual(miner.to_dataset_records(governed_only=True), [])
        first = created[0]
        miner.govern(first.candidate_id, operator="tester")
        rows = miner.to_dataset_records(governed_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lifecycle"], TrainingCandidateLifecycle.ELIGIBLE.value)
        self.assertTrue(rows[0]["metadata"]["auto_promote_forbidden"])


class TrajectoryExportTests(unittest.TestCase):
    def test_strips_private_cot_and_skips_unverified(self) -> None:
        traj = export_training_trajectory(
            run_id="r1",
            public_states=[{"phase": "answer", "private_cot": "SECRET_REASONING"}],
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "system", "content": "hidden system"},
            ],
            selected_answer="hello",
            verified_result={"passed": True, "status": "PASSED", "hidden_reasoning": "nope"},
            metadata={"chain_of_thought": "nope", "ok": True},
        )
        self.assertNotIn("private_cot", traj["public_states"][0])
        self.assertNotIn("hidden_reasoning", traj["verified_result"])
        self.assertNotIn("chain_of_thought", traj["metadata"])
        self.assertTrue(traj["truth"]["no_private_cot_required"])
        self.assertEqual(len(traj["messages"]), 2)  # system without public= dropped
        rows = trajectories_to_dataset_rows([traj])
        self.assertEqual(len(rows), 1)
        unverified = export_training_trajectory(
            run_id="r2",
            messages=[{"role": "user", "content": "x"}],
            selected_answer="guess",
            verified_result={"passed": False, "status": "FAILED"},
        )
        self.assertEqual(trajectories_to_dataset_rows([unverified]), [])


class TrainingCapabilitiesHonestyTests(unittest.TestCase):
    def test_grpo_rl_reward_feature_gated(self) -> None:
        caps = probe_training_capabilities()
        public = caps.public_dict()
        self.assertFalse(public["canRunGrpo"])
        self.assertFalse(public["canRunRl"])
        self.assertFalse(public["canRunRewardModel"])
        self.assertEqual(public["grpoStatus"], "FEATURE_GATED")
        self.assertEqual(public["rlStatus"], "FEATURE_GATED")
        self.assertEqual(public["rewardModelStatus"], "FEATURE_GATED")
        self.assertEqual(public["dpoHfStatus"], "FEATURE_GATED")


if __name__ == "__main__":
    unittest.main()
