"""T13: rejecting critic must leave the Work task failed, not completed.

The complicit FakeLmStudio in ``test_api.py`` always returns ``passed: True``.
This suite proves the verification pillar under model rejection without relying
on that always-green critic.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import main
from database import Database
from reasoning.budgets import ExecutionBudget
from reasoning.verification import (
    build_acceptance_checklist,
    parse_verification_result,
    verification_allows_success,
)
from run_lifecycle import decide_work_task_completion


def _rejecting_critic_payload() -> str:
    return json.dumps(
        {
            "passed": False,
            "issues": ["Acceptance criteria not met under independent review."],
            "final": "Rejected by critic",
            "evidence_refs": ["step:1"],
            "incomplete": False,
            "criteria_checklist": [
                {
                    "id": "c1",
                    "criterion": "Resultaat is concreet en gecontroleerd",
                    "met": False,
                    "note": "Critic rejects on purpose for T13",
                }
            ],
        }
    )


class RejectingCriticUnitTests(unittest.TestCase):
    def test_verification_allows_success_rejects_passed_false(self) -> None:
        parsed = parse_verification_result(_rejecting_critic_payload())
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertFalse(parsed.passed)
        allowed, reason = verification_allows_success(
            parsed,
            tool_observations=[],
            step_outputs=[
                {
                    "title": "Uitvoeren",
                    "output": "Lokaal antwoord",
                    "id": "1",
                    "step_id": "1",
                }
            ],
            require_final=True,
            acceptance_criteria=["Resultaat is concreet en gecontroleerd"],
        )
        self.assertFalse(allowed, reason)
        checklist = build_acceptance_checklist(
            ["Resultaat is concreet en gecontroleerd"], result=parsed
        )
        self.assertTrue(any(not row.met for row in checklist))

    def test_verification_failed_checkpoint_cannot_complete(self) -> None:
        decision = decide_work_task_completion(
            checkpoint_state={
                "phase": "verification_failed",
                "passed": False,
                "issues": ["critic reject"],
            },
            steps=[{"id": "s1", "status": "completed"}],
            cancelled=False,
        )
        self.assertFalse(decision.may_complete)
        self.assertIn("checkpoint_phase", decision.reason)

    def test_zero_replan_budget_cannot_retry_after_reject(self) -> None:
        budget = ExecutionBudget(max_model_calls=10, max_tool_rounds=3, max_replans=0)
        self.assertFalse(budget.can_replan())


class RejectingCriticWorkOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_verification_failure_marks_task_failed_not_completed(self) -> None:
        """Work owner must persist ``failed`` when verification raises (critic reject path)."""
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            root = Path(temp.name)
            main.database = Database(str(root / "critic-reject.db"))
            main.database.initialize()
            platform = main.ensure_platform_services()
            platform.initialize()
            main.runner = main.TaskRunner()

            async def failing_work(*_args, **_kwargs):
                # Mirror main._execute_work when critic rejects and max_replans=0.
                # Bound call is (self, task, ...); unbound patch may pass self first.
                task = _kwargs.get("task")
                if task is None:
                    for arg in _args:
                        if isinstance(arg, dict) and arg.get("id") and arg.get("prompt") is not None:
                            task = arg
                            break
                if not isinstance(task, dict):
                    raise AssertionError(f"expected task dict in _execute_work args, got {_args!r}")
                task_id = task["id"]
                main.platform_db.add_work_checkpoint(
                    task_id,
                    {
                        "phase": "verification_failed",
                        "passed": False,
                        "issues": ["Acceptance criteria not met under independent review."],
                        "acceptance_checklist": [
                            {
                                "id": "c1",
                                "criterion": "Resultaat is concreet en gecontroleerd",
                                "met": False,
                            }
                        ],
                    },
                )
                raise RuntimeError(
                    "Completion verification faalde: Acceptance criteria not met under independent review."
                )

            with (
                patch.object(main.TaskRunner, "_execute_work", new=failing_work),
                patch(
                    "main.resolve_model",
                    new=AsyncMock(return_value=("local-test-model", {"id": "local-test-model"})),
                ),
                patch(
                    "main.retrieval_context",
                    return_value=("", {"memories": 0, "knowledge_chunks": 0}),
                ),
                patch("main.effective_reasoning", return_value="high"),
                patch("main.route_agent", return_value="executor"),
                patch("main.maybe_execute_promoted_skill"),
                patch(
                    "main._async_sync_mission_from_task_safe",
                    new=AsyncMock(return_value={"ok": True}),
                ),
            ):
                task = main.database.create_task(
                    "T13 reject critic",
                    "Voer een controleerbare taak uit",
                    "executor",
                    "normal",
                    "local-test-model",
                )
                task_id = task["id"]
                await main.runner._execute(task_id)

            final = main.database.get_task(task_id)
            self.assertIsNotNone(final)
            assert final is not None
            self.assertEqual(final["status"], "failed", final.get("error"))
            self.assertNotEqual(final["status"], "completed")
            self.assertIn("verification", str(final.get("error") or "").lower())
            checkpoint = main.platform_db.latest_work_checkpoint(task_id)
            self.assertIsNotNone(checkpoint, "verification_failed checkpoint must be persisted")
            assert checkpoint is not None
            state = checkpoint.get("state") or {}
            self.assertEqual(state.get("phase"), "verification_failed", state)
            decision = decide_work_task_completion(
                checkpoint_state=state,
                steps=[{"id": "s1", "status": "completed"}],
            )
            self.assertFalse(decision.may_complete)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
