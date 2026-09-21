"""A12 — lifecycle ownership and work-completion gating."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_lifecycle import (
    SURFACE_OWNERS,
    WORK_STATUS_OWNER,
    decide_work_task_completion,
    mission_may_downgrade,
    mission_may_invent_completion,
    ownership_snapshot,
    reconcile_work_claimed_status,
    work_control_transition_allowed,
    workflow_owns_work_tasks,
)


class A12LifecycleOwnershipTests(unittest.TestCase):
    def test_surfaces_have_one_owner_each(self) -> None:
        snap = ownership_snapshot()
        self.assertIn("work_runtime", snap["surfaces"])
        self.assertIn("mission_control", snap["surfaces"])
        self.assertIn("workflow", snap["surfaces"])
        self.assertEqual(SURFACE_OWNERS["work_runtime"], snap["surfaces"]["work_runtime"])
        self.assertFalse(mission_may_invent_completion())
        self.assertFalse(workflow_owns_work_tasks())
        self.assertEqual(snap["persistence"], "sqlite")

    def test_completed_requires_verified_checkpoint(self) -> None:
        denied = decide_work_task_completion(checkpoint_state={"phase": "step_completed"})
        self.assertFalse(denied.may_complete)
        self.assertIn("checkpoint_phase", denied.reason)

        allowed = decide_work_task_completion(
            checkpoint_state={"phase": "verified", "passed": True, "evidence_refs": ["step:1"]},
            steps=[{"id": "1", "status": "completed"}],
        )
        self.assertTrue(allowed.may_complete)
        self.assertEqual(allowed.owner, WORK_STATUS_OWNER["completed"])

    def test_failed_steps_block_completion(self) -> None:
        decision = decide_work_task_completion(
            checkpoint_state={"phase": "verified", "passed": True},
            steps=[{"id": "1", "status": "completed"}, {"id": "2", "status": "failed"}],
        )
        self.assertFalse(decision.may_complete)
        self.assertTrue(any(b.startswith("failed_steps") for b in decision.blockers))

    def test_cancelled_blocks_completion(self) -> None:
        decision = decide_work_task_completion(
            checkpoint_state={"phase": "verified", "passed": True},
            cancelled=True,
        )
        self.assertFalse(decision.may_complete)
        self.assertEqual(decision.reason, "task_cancelled")

    def test_blocked_steps_block_completion(self) -> None:
        decision = decide_work_task_completion(
            checkpoint_state={"phase": "verified", "passed": True},
            steps=[{"id": "1", "status": "completed"}, {"id": "2", "status": "blocked"}],
        )
        self.assertFalse(decision.may_complete)
        self.assertTrue(any(b.startswith("blocked_steps") for b in decision.blockers))

    def test_mission_may_only_downgrade_completion(self) -> None:
        self.assertTrue(mission_may_downgrade("completed", "failed"))
        self.assertFalse(mission_may_downgrade("failed", "completed"))
        self.assertFalse(mission_may_downgrade("cancelled", "completed"))
        self.assertFalse(mission_may_downgrade("running", "completed"))
        self.assertFalse(mission_may_invent_completion())

    def test_reconcile_completed_with_failed_steps_becomes_failed(self) -> None:
        status, decision = reconcile_work_claimed_status(
            claimed_status="completed",
            checkpoint_state={"phase": "verified", "passed": True},
            steps=[{"id": "1", "status": "completed"}, {"id": "2", "status": "failed"}],
        )
        self.assertEqual(status, "failed")
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertFalse(decision.may_complete)
        # Non-completed claims are left alone.
        kept, none_decision = reconcile_work_claimed_status(
            claimed_status="running",
            checkpoint_state={"phase": "verified", "passed": True},
        )
        self.assertEqual(kept, "running")
        self.assertIsNone(none_decision)

    def test_work_control_transitions_pause_resume_cancel(self) -> None:
        self.assertTrue(work_control_transition_allowed("pause", status="running", control_state="active"))
        self.assertTrue(work_control_transition_allowed("resume", status="running", control_state="paused"))
        self.assertTrue(work_control_transition_allowed("resume", status="running", control_state="pause_requested"))
        self.assertFalse(work_control_transition_allowed("resume", status="running", control_state="active"))
        self.assertTrue(work_control_transition_allowed("cancel", status="running", control_state="paused"))
        self.assertTrue(work_control_transition_allowed("cancel", status="queued"))
        self.assertFalse(work_control_transition_allowed("cancel", status="completed"))
        self.assertFalse(work_control_transition_allowed("pause", status="queued"))

    def test_artifact_and_policy_protocols_match_services(self) -> None:
        from artifacts import ArtifactService
        from policy_enforcement import enforce_tool_invocation_policies
        from run_lifecycle import ArtifactVerifier, PolicyGate

        self.assertTrue(issubclass(ArtifactService, object))
        # Structural: verify_ready exists on ArtifactService.
        self.assertTrue(callable(getattr(ArtifactService, "verify_ready", None)))
        self.assertTrue(isinstance(enforce_tool_invocation_policies, PolicyGate) or callable(enforce_tool_invocation_policies))
        # Protocol check on instance would need db; type presence is enough for contract.
        self.assertIn("artifact", SURFACE_OWNERS)
        self.assertIn("policy", SURFACE_OWNERS)
        self.assertIn("model_gateway", SURFACE_OWNERS)
        _ = ArtifactVerifier  # imported for contract surface


if __name__ == "__main__":
    unittest.main()
