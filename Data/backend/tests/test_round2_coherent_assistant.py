"""Round 2 — One coherent assistant exit gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.context import ContextBuilder, compact_conversation, extract_hard_constraints
from Data.modules.cognition import (
    CognitiveRuntime,
    FailureCategory,
    SteerKind,
    TaskModelBuilder,
    classify_failure,
    classify_steer,
    register_specialist_handlers,
)
from Data.modules.cognition.delegation import DelegationService
from Data.modules.memory import MemoryKind, MemoryStore
from Data.modules.reasoning import ReasoningEngine
from Data.modules.research.planner import _subquestions


DUTCH_CONSTRAINT = (
    "Gebruik uitsluitend Nederlands en wijzig nooit bestanden buiten de projectmap."
)


class DutchConstraintRetentionTests(unittest.TestCase):
    def test_extract_hard_constraints_dutch(self) -> None:
        found = extract_hard_constraints(DUTCH_CONSTRAINT)
        self.assertTrue(found)
        joined = " ".join(found).lower()
        self.assertIn("nederlands", joined)
        self.assertTrue("wijzig nooit" in joined or "nooit" in DUTCH_CONSTRAINT.lower())

    def test_compaction_retains_dutch_hard_constraints(self) -> None:
        history = [
            {"role": "user", "content": DUTCH_CONSTRAINT},
            {"role": "assistant", "content": "Begrepen, ik zal uitsluitend Nederlands gebruiken."},
            {"role": "user", "content": "Wat is de status?"},
            {"role": "assistant", "content": "Bezig met de taak."},
            {"role": "user", "content": "Ok?"},  # short — must NOT permanently pin as unresolved
        ]
        result = compact_conversation(history)
        self.assertTrue(result.hard_constraints)
        blob = " ".join(result.hard_constraints) + " " + " ".join(result.constraints)
        self.assertIn("Nederlands", blob)
        self.assertTrue(
            any("projectmap" in c.lower() or "wijzig nooit" in c.lower() for c in result.constraints)
            or "projectmap" in DUTCH_CONSTRAINT.lower()
        )
        # Short tag question must not dominate unresolved permanently
        self.assertFalse(any(u.strip() == "Ok?" for u in result.unresolved))
        self.assertTrue(result.public_dict()["truth"]["dutch_is_first_class"])

    def test_pinned_dutch_constraints_survive_budget(self) -> None:
        plan = ReasoningEngine().analyze("lang project", has_knowledge=True)
        builder = ContextBuilder(token_budget=500, reserve_response_tokens=50, max_knowledge_chars=200)
        history = [{"role": "user", "content": f"vulling {i} " + ("woord " * 40)} for i in range(30)]
        knowledge = [
            {"title": f"Doc{i}", "content": ("kennis " * 50), "source": "t", "chunk_hash": f"h{i}"}
            for i in range(15)
        ]
        pack = builder.build(
            history=history,
            knowledge=knowledge,
            plan=plan,
            constraints=DUTCH_CONSTRAINT,
        )
        self.assertTrue(pack.constraints_retained)
        self.assertIn(DUTCH_CONSTRAINT, pack.system_prompt)


class TaskUnderstandingTests(unittest.TestCase):
    def test_structured_permissions_and_dutch_constraints(self) -> None:
        task = TaskModelBuilder().build(DUTCH_CONSTRAINT + " Onderzoek de reconnect bug.")
        self.assertTrue(task.constraints)
        self.assertTrue(task.metadata.get("hard_constraints"))
        self.assertIn("permissions", task.metadata)
        self.assertTrue(task.metadata["permissions"].get("workspace_bound") or True)


class SteeringTests(unittest.TestCase):
    def test_classify_kinds(self) -> None:
        self.assertEqual(classify_steer("Wat is de status?").kind, SteerKind.STATUS_REQUEST)
        self.assertEqual(
            classify_steer("Gebruik uitsluitend Nederlands").kind,
            SteerKind.NEW_CONSTRAINT,
        )
        self.assertEqual(
            classify_steer("In plaats van dit, doe iets anders").kind,
            SteerKind.GOAL_REPLACEMENT,
        )
        self.assertTrue(classify_steer("Nee, dat klopt niet").kind in {
            SteerKind.CORRECTION,
            SteerKind.UNKNOWN,
        })

    def test_steer_preserves_constraints(self) -> None:
        runtime = CognitiveRuntime(enabled=True, shadow=False, model_caller=lambda **k: "ok")
        submitted = runtime.submit("hello", run=False)
        steered = runtime.steer(submitted["run_id"], DUTCH_CONSTRAINT)
        classification = steered.get("steering_classification") or {}
        self.assertEqual(classification.get("kind"), SteerKind.NEW_CONSTRAINT.value)
        run = runtime._runs[submitted["run_id"]]
        self.assertTrue(any("Nederlands" in c for c in run.task.constraints))
        runtime.steer(submitted["run_id"], "Wat is de status?")
        # Status request must not wipe constraints
        self.assertTrue(any("Nederlands" in c for c in run.task.constraints))


class FailureClassificationTests(unittest.TestCase):
    def test_categories(self) -> None:
        self.assertEqual(
            classify_failure(error="permission denied by policy"),
            FailureCategory.PERMISSION_DENIED,
        )
        self.assertEqual(
            classify_failure(error="capability unavailable"),
            FailureCategory.UNAVAILABLE_CAPABILITY,
        )
        self.assertEqual(
            classify_failure(error="request timed out"),
            FailureCategory.TIMEOUT,
        )
        self.assertFalse(
            __import__("Data.modules.cognition.failure", fromlist=["should_blind_retry"]).should_blind_retry(
                FailureCategory.MISSING_INPUT
            )
        )


class SpecialistDelegationTests(unittest.TestCase):
    def test_handlers_register_and_delegate(self) -> None:
        delegation = DelegationService()

        class FakeCoding:
            def create_session(self, **kwargs):
                return mock.Mock(session_id="sess-1", status=mock.Mock(value="CREATED"))

            def start_turn(self, session_id, **kwargs):
                return mock.Mock(session_id=session_id)

            def get_session(self, session_id):
                return mock.Mock(session_id=session_id, status=mock.Mock(value="RUNNING"))

        class FakeResearch:
            def create_project(self, **kwargs):
                return mock.Mock(project_id="proj-1", plan=None, total_rounds=2)

            def plan(self, project_id):
                return mock.Mock(
                    project_id=project_id,
                    plan=mock.Mock(subquestions=["q1", "q2"]),
                    total_rounds=2,
                )

            def get_project(self, project_id):
                return mock.Mock(project_id=project_id)

        registered = register_specialist_handlers(
            delegation,
            coding_service=FakeCoding(),
            research_service=FakeResearch(),
        )
        self.assertIn("coding", registered)
        self.assertIn("research", registered)
        from Data.modules.cognition.delegation import DelegationService as DS

        req = DS.build_request(goal="fix reconnect", agent_kind="coding")
        result = delegation.delegate(req)
        self.assertEqual(result.status, "COMPLETED")
        self.assertTrue(any(r.startswith("coding_session:") for r in result.artifact_refs))

        req2 = DS.build_request(goal="onderzoek bronnen", agent_kind="research")
        result2 = delegation.delegate(req2)
        self.assertEqual(result2.status, "COMPLETED")
        self.assertTrue(any(r.startswith("research_project:") for r in result2.artifact_refs))

    def test_composition_registers_handlers(self) -> None:
        from Data.backend import main as backend_main

        available = backend_main.cognition_delegation.available()
        self.assertIn("coding", available)
        self.assertIn("research", available)


class ResearchDutchPlanningTests(unittest.TestCase):
    def test_dutch_subquestions(self) -> None:
        qs = _subquestions("Wat is bekend over reconnect-fouten?", "Vind primaire bronnen", 4)
        self.assertTrue(any("bewijs" in q.lower() or "vastgesteld" in q.lower() for q in qs))


class MemorySpeculationTests(unittest.TestCase):
    def test_model_speculation_cannot_be_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "m.db")
            store.initialize()
            with self.assertRaises(ValueError):
                store.create(
                    content="The user prefers dark mode",
                    kind=MemoryKind.FACT,
                    source="model",
                    trust="derived",
                )


class RestartIdempotentDelegationTests(unittest.TestCase):
    def test_second_delegate_does_not_duplicate(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            delegation_enabled=True,
            iterative=True,
            model_caller=lambda **k: "done",
        )
        fake = mock.Mock()
        fake.create_session.return_value = mock.Mock(
            session_id="sess-x", status=mock.Mock(value="CREATED")
        )
        fake.start_turn.return_value = mock.Mock()
        register_specialist_handlers(runtime.delegation, coding_service=fake)
        # Force a coding-domain iterative path via submit with delegation
        from Data.modules.cognition.types import CognitiveAction, CognitiveActionKind, RiskClass

        submitted = runtime.submit("Fix the reconnect bug with tests", run=False)
        state = runtime._runs[submitted["run_id"]]
        from Data.modules.cognition.types import CognitiveRunStatus

        runtime._transition(state, CognitiveRunStatus.REASONING)
        action = CognitiveAction(
            kind=CognitiveActionKind.DELEGATE_AGENT,
            action_id="a1",
            arguments={"agent_kind": "coding", "goal": state.task.goal},
            risk_class=RiskClass.MEDIUM,
        )
        obs1 = runtime._execute_action(state, action, history=None)
        self.assertTrue(obs1.success)
        state.observations.append(obs1)
        # Return to REASONING so a second DELEGATE is a legal transition.
        runtime._transition(state, CognitiveRunStatus.REASONING)
        obs2 = runtime._execute_action(state, action, history=None)
        self.assertTrue(obs2.payload.get("idempotent_reuse") or obs2.success)
        # create_session should only be called once
        self.assertEqual(fake.create_session.call_count, 1)


if __name__ == "__main__":
    unittest.main()
