"""TEAM orchestrator must bind executors per run — never via global singleton mutation."""

from __future__ import annotations

import unittest

from Data.modules.cognition.team_orchestrator import TeamOrchestrator, TeamSpecialistResult


def _sentinel_executor(label: str):
    def _exec(assignment, state):
        art = {
            "text": f"answer-from-{label}",
            "provisional": True,
            "revision": state.artifact_revision,
            "answer_kind": "prose_reply",
            "sentinel": label,
        }
        return TeamSpecialistResult(
            role=assignment.role.value,
            task_id=assignment.task_id,
            summary=f"from:{label}",
            notes=f"executor={label}",
            artifact_candidate=art,
            provisional_artifact=art,
            evidence_ids=[f"sentinel:{label}"],
            material_claims=[],
            warnings=[],
        ).to_dict()

    return _exec


class TeamPerRunExecutorTests(unittest.TestCase):
    def test_concurrent_runs_do_not_cross_contaminate_executors(self) -> None:
        orch = TeamOrchestrator()
        a = orch.start(
            request_text="run A",
            run_id="team:a",
            task_category="general",
            specialist_executor=_sentinel_executor("A"),
        )
        b = orch.start(
            request_text="run B",
            run_id="team:b",
            task_category="general",
            specialist_executor=_sentinel_executor("B"),
        )
        # Default process executor must remain the fixture — not overwritten by starts.
        self.assertIs(orch._executor, orch._default_fixture_executor)

        orch.run_until_terminal(a.run_id, max_iterations=2)
        orch.run_until_terminal(b.run_id, max_iterations=2)

        state_a = orch.get("team:a")
        state_b = orch.get("team:b")
        assert state_a is not None and state_b is not None

        notes_a = " ".join(
            str((x.result or {}).get("notes") or "") for x in state_a.assignments
        )
        notes_b = " ".join(
            str((x.result or {}).get("notes") or "") for x in state_b.assignments
        )
        self.assertIn("executor=A", notes_a)
        self.assertNotIn("executor=B", notes_a)
        self.assertIn("executor=B", notes_b)
        self.assertNotIn("executor=A", notes_b)

        # Mutating the default after start must not bleed into already-bound runs.
        orch._executor = _sentinel_executor("LEAK")
        # Re-drive a fresh run that relies on default should see LEAK; A/B stay bound.
        c = orch.start(
            request_text="run C default",
            run_id="team:c",
            task_category="general",
        )
        orch.run_until_terminal(c.run_id, max_iterations=2)
        state_c = orch.get("team:c")
        assert state_c is not None
        notes_c = " ".join(
            str((x.result or {}).get("notes") or "") for x in state_c.assignments
        )
        self.assertIn("executor=LEAK", notes_c)
        # A still bound to A
        orch.run_until_terminal(a.run_id, max_iterations=1)
        state_a2 = orch.get("team:a")
        assert state_a2 is not None
        notes_a2 = " ".join(
            str((x.result or {}).get("notes") or "") for x in state_a2.assignments
        )
        self.assertIn("executor=A", notes_a2)


if __name__ == "__main__":
    unittest.main()
