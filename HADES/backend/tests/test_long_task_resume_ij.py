"""Acceptance tests for work package I — long-task resume without double work."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_jobs import reset_coding_job_store_for_tests
from reasoning.long_task_resume import (
    RunIdentity,
    SideEffectLedger,
    apply_new_user_instructions,
    build_resume_plan,
    collect_inspectable_partials,
    confirmed_outcome_from_task_and_mission,
    is_worker_live,
    make_idempotency_key,
    model_timeout_recovery,
    pause_during_tool_execution,
)
from reasoning.run_control import resume_after_browser_disconnect
from run_leases import ExecutionLeaseStore


class CrashBetweenEffectAndCheckpointTests(unittest.TestCase):
    def test_no_unintended_double_effect_when_evidence_recoverable(self) -> None:
        ledger = SideEffectLedger()
        identity = RunIdentity(run_id="run_1", step_id="step_a", task_id="task_1", mission_id="m1", fence_token="f1")
        key = make_idempotency_key(run_id="run_1", step_id="step_a", effect_kind="tool.write", payload={"path": "a.txt"})
        recorded = ledger.record_intent(
            identity=identity,
            effect_kind="tool.write",
            payload={"path": "a.txt"},
            fence_token="f1",
        )
        self.assertTrue(recorded["ok"])
        intent_id = recorded["intent"]["intent_id"]
        ledger.mark_in_flight(intent_id, fence_token="f1")
        # Crash before checkpoint — but effect observed on disk.
        reconciled = ledger.reconcile_after_crash(
            idempotency_key=key,
            recovered_result_ref="artifact:a1",
            recovered_evidence={"effect_observed": True, "path": "a.txt"},
        )
        self.assertEqual(reconciled["action"], "reconciled_completed")
        self.assertFalse(reconciled["may_reexec"])
        self.assertTrue(reconciled["double_effect_prevented"])
        # Second attempt with same idempotency key must reuse, not re-exec.
        again = ledger.record_intent(
            identity=identity,
            effect_kind="tool.write",
            payload={"path": "a.txt"},
            fence_token="f1",
        )
        self.assertTrue(again["idempotent"])
        self.assertEqual(again["intent"]["status"], "completed")

    def test_honest_unresolved_when_evidence_missing(self) -> None:
        ledger = SideEffectLedger()
        identity = RunIdentity(run_id="run_2", step_id="step_b", fence_token="f2")
        key = make_idempotency_key(run_id="run_2", step_id="step_b", effect_kind="tool.email", payload={"to": "x"})
        recorded = ledger.record_intent(identity=identity, effect_kind="tool.email", payload={"to": "x"}, fence_token="f2")
        ledger.mark_in_flight(recorded["intent"]["intent_id"], fence_token="f2")
        result = ledger.reconcile_after_crash(idempotency_key=key)
        self.assertEqual(result["action"], "mark_unresolved")
        self.assertFalse(result["may_reexec"])
        self.assertEqual(result["intent"]["status"], "unresolved")


class BrowserRefreshNoDoubleWorkerTests(unittest.TestCase):
    def test_resume_from_browser_refresh_does_not_start_two_workers(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        started = {"n": 0}
        gate = threading.Event()

        def runner(params):  # noqa: ANN001
            started["n"] += 1
            gate.wait(timeout=10)
            return {"status": "verified", "id": "r1"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        for _ in range(80):
            if started["n"] >= 1:
                break
            time.sleep(0.02)
        snap = store.get(job["id"])
        self.assertTrue(snap["worker_live"])
        decision = resume_after_browser_disconnect(status=snap["status"], worker_live=snap["worker_live"])
        self.assertFalse(decision["start_worker"])
        self.assertEqual(decision["action"], "observe_only")
        # Concurrent "refresh resume" must not double-dispatch.
        store.resume(job["id"])
        store.resume(job["id"])
        gate.set()
        for _ in range(100):
            if store.get(job["id"])["status"] in {"verified", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        self.assertEqual(started["n"], 1)

    def test_stale_running_label_is_not_live_process(self) -> None:
        info = is_worker_live(status="running", worker_live=False, lease_expired=True)
        self.assertTrue(info["status_label_stale"])
        self.assertFalse(info["worker_live"])
        self.assertTrue(info["may_start_new_worker"])


class CancelStopsLateArtifactsTests(unittest.TestCase):
    def test_cancel_prevents_late_artifacts(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        hold = threading.Event()

        def runner(params):  # noqa: ANN001
            hold.wait(timeout=5)
            return {"status": "verified", "id": "late", "artifact_ids": ["should_not_land"]}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        for _ in range(80):
            if store.get(job["id"]).get("worker_live"):
                break
            time.sleep(0.02)
        store.request_cancel(job["id"])
        rejected = store.accept_late_artifact(job["id"], "art_late_1")
        self.assertFalse(rejected.get("accepted"))
        self.assertEqual(rejected.get("reason"), "cancelled_late_artifact")
        hold.set()
        for _ in range(80):
            if store.get(job["id"])["status"] in {"cancelled", "verified", "failed"}:
                break
            time.sleep(0.05)
        # Late artifact must not appear in accepted result ids when rejected.
        snap = store.get(job["id"])
        arts = list((snap.get("result") or {}).get("artifact_ids") or [])
        self.assertNotIn("art_late_1", arts)


class FailedStepPartialsTests(unittest.TestCase):
    def test_failed_step_leaves_inspectable_partials(self) -> None:
        partials = collect_inspectable_partials(
            step_id="s1",
            checkpoint={"phase": "before_edit", "action_index": 2, "draft": "partial.txt"},
            artifacts=[{"id": "a1", "kind": "draft_edit"}],
            error="tests_failed",
        )
        self.assertTrue(partials["inspectable"])
        self.assertEqual(partials["checkpoint_phase"], "before_edit")
        self.assertEqual(len(partials["partial_artifacts"]), 1)


class MissionControlTasksSameOutcomeTests(unittest.TestCase):
    def test_mission_and_tasks_show_same_confirmed_outcome(self) -> None:
        task = {
            "id": "task_1",
            "status": "completed",
            "verification": {"status": "passed", "evidence_refs": ["step:s1"]},
            "step_summary": {"total": 1, "completed": 1, "failed": 0},
        }
        mission = {
            "id": "mission_1",
            "task_id": "task_1",
            "status": "completed",
            "execution_id": "exec_1",
            "verification": {"status": "passed", "evidence_refs": ["step:s1"], "step_summary": task["step_summary"]},
        }
        outcome = confirmed_outcome_from_task_and_mission(task=task, mission=mission)
        self.assertTrue(outcome.confirmed)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.task_id, "task_1")
        self.assertEqual(outcome.mission_id, "mission_1")

        # Task claims completed but mission evidence rejects → same failed outcome.
        mission_fail = {
            **mission,
            "status": "failed",
            "verification": {"status": "failed", "evidence_refs": [], "step_summary": {"failed": 1, "completed": 0, "total": 1}},
        }
        aligned = confirmed_outcome_from_task_and_mission(task=task, mission=mission_fail)
        self.assertEqual(aligned.status, "failed")
        self.assertTrue(aligned.confirmed)
        self.assertEqual(aligned.source, "mission_control")


class RedirectKeepsIndependentStepsTests(unittest.TestCase):
    def test_redirect_keeps_independent_completed_reruns_dependents(self) -> None:
        steps = [
            {"step_id": "a", "status": "completed", "depends_on": []},
            {"step_id": "b", "status": "completed", "depends_on": []},
            {"step_id": "c", "status": "pending", "depends_on": ["a"]},
            {"step_id": "d", "status": "pending", "depends_on": ["b", "c"]},
        ]
        effect = apply_new_user_instructions(
            current_plan_version=1,
            steps=steps,
            completed_ids={"a", "b"},
            instruction="Change approach for a",
            invalidate_from_step_ids={"a"},
        )
        self.assertTrue(effect["accepted"])
        self.assertIn("b", effect["reused_step_ids"])
        self.assertIn("a", effect["invalidated_step_ids"])
        self.assertIn("c", effect["invalidated_step_ids"])
        self.assertIn("d", effect["invalidated_step_ids"])
        self.assertNotIn("b", effect["invalidated_step_ids"])


class LeaseFencingCasTests(unittest.TestCase):
    def test_stale_fence_cannot_renew_after_reclaim(self) -> None:
        leases = ExecutionLeaseStore()
        first = leases.acquire("res1", worker_id="w1", ttl_s=0.05)
        self.assertTrue(first["ok"])
        fence = first["fence_token"]
        gen = first["generation"]
        time.sleep(0.06)
        reclaimed = leases.reclaim_stale()
        self.assertIn("res1", reclaimed)
        stale = leases.renew("res1", worker_id="w1", fence_token=fence, generation=gen)
        self.assertFalse(stale["ok"])
        takeover = leases.compare_and_set_holder("res1", expected_worker_id=None, new_worker_id="w2")
        self.assertTrue(takeover["ok"])
        conflict = leases.compare_and_set_holder("res1", expected_worker_id=None, new_worker_id="w3")
        self.assertFalse(conflict["ok"])


class PauseTimeoutInstructionTests(unittest.TestCase):
    def test_pause_during_tool_and_model_timeout(self) -> None:
        mid = pause_during_tool_execution(phase="tool", tool_in_flight=True)
        self.assertFalse(mid["safe_to_mark_paused"])
        safe = pause_during_tool_execution(phase="step_completed", tool_in_flight=False)
        self.assertTrue(safe["safe_to_mark_paused"])
        timeout = model_timeout_recovery(step_id="s1", had_side_effect_intent=True, result_observed=False)
        self.assertEqual(timeout["action"], "mark_unresolved")
        retry = model_timeout_recovery(step_id="s1", had_side_effect_intent=False, result_observed=False)
        self.assertTrue(retry["may_retry_model"])

    def test_resume_plan_avoids_second_worker_and_unresolved(self) -> None:
        identity = RunIdentity(run_id="r", task_id="t", mission_id="m")
        ledger = SideEffectLedger()
        intent = ledger.record_intent(
            identity=identity.bind(step_id="s2"),
            effect_kind="tool.x",
            payload={"n": 1},
        )
        ledger.mark_in_flight(intent["intent"]["intent_id"])
        plan = build_resume_plan(
            identity=identity,
            steps=[
                {"step_id": "s1", "status": "completed"},
                {"step_id": "s2", "status": "running"},
                {"step_id": "s3", "status": "pending"},
            ],
            completed_ids={"s1"},
            intents=ledger.list_for_run("r"),
            worker_live=True,
            status_label="running",
        )
        self.assertIn("s1", plan.reused_step_ids)
        await_live = [d for d in plan.decisions if d.step_id == "s2"][0]
        self.assertEqual(await_live.action, "await_live_worker")


if __name__ == "__main__":
    unittest.main()
