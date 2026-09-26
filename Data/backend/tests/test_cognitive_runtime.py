"""Cognitive Runtime unit/integration tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import ConfigurationError, Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.cognition import (
    BeliefCategory,
    BeliefState,
    BeliefStatus,
    CapabilityBroker,
    CognitionStore,
    CognitiveAction,
    CognitiveActionKind,
    CognitiveRuntime,
    CognitiveRunStatus,
    CompletionEngine,
    ContextBuilderV3,
    EpistemicType,
    ExperienceStore,
    MetaController,
    PerceptionService,
    ReasoningMode,
    ReasoningStrategy,
    RiskClass,
    TaskModelBuilder,
    WorkingMemory,
)
from Data.modules.cognition.loop_detection import LoopDetector as LD
from Data.modules.cognition.types import validate_transition
from Data.modules.execution import CapabilityCatalog, CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect


class TaskModelTests(unittest.TestCase):
    def test_simple_chat_is_low_risk_fast_domain(self) -> None:
        task = TaskModelBuilder().build("hello")
        self.assertEqual(task.task_type, "simple_chat")
        self.assertEqual(task.risk_class, RiskClass.LOW)
        self.assertIn("helpful direct reply", task.success_criteria)

    def test_coding_repair_gets_coding_domain_and_criteria(self) -> None:
        task = TaskModelBuilder().build(
            "Fix the Python bug in reconnect that loses pending MCP calls and make tests green"
        )
        self.assertEqual(task.domain, "coding")
        self.assertEqual(task.task_type, "coding_repair")
        self.assertIn("coding", task.allowed_delegation)
        self.assertTrue(any("test" in c.lower() or "root" in c.lower() for c in task.success_criteria))

    def test_ambiguity_detected(self) -> None:
        task = TaskModelBuilder().build("Should we use A or B somehow?")
        self.assertTrue(task.ambiguities or task.initial_uncertainty >= 0.5)


class BeliefStateTests(unittest.TestCase):
    def test_add_support_and_contradiction(self) -> None:
        state = BeliefState()
        a = state.add("pending map cleared early", category=BeliefCategory.HYPOTHESIS, confidence=0.6)
        state.apply_observation_support(a.belief_id, observation_id="obs-1", supports=True)
        item = state.get(a.belief_id)
        assert item is not None
        self.assertIn("obs-1", item.support_refs)
        self.assertIn(item.status, {BeliefStatus.SUPPORTED, BeliefStatus.PARTIALLY_SUPPORTED})

        b = state.add("pending map survives teardown", category=BeliefCategory.HYPOTHESIS, confidence=0.55)
        state.record_contradiction(a.belief_id, b.belief_id)
        self.assertEqual(len(state.contradiction_pairs), 1)
        self.assertEqual(state.get(a.belief_id).status, BeliefStatus.CONTRADICTED)

    def test_neural_association_cannot_become_exact_fact(self) -> None:
        state = BeliefState()
        item = state.add(
            "maybe related",
            category=BeliefCategory.FACT,
            source_type=EpistemicType.NEURAL_ASSOCIATION,
            confidence=0.9,
        )
        self.assertEqual(item.category, BeliefCategory.HYPOTHESIS)
        self.assertLessEqual(item.confidence, 0.55)

    def test_reject_hypothesis(self) -> None:
        state = BeliefState()
        item = state.add("bad idea", confidence=0.4)
        state.reject(item.belief_id, reason="contradicted by tests")
        self.assertEqual(state.get(item.belief_id).status, BeliefStatus.REJECTED)


class WorkingMemoryTests(unittest.TestCase):
    def test_capacity_eviction_keeps_goal(self) -> None:
        wm = WorkingMemory(capacity=4)
        wm.set_goal("fix reconnect")
        for i in range(10):
            wm.upsert("neuro", f"assoc-{i}", source_type=EpistemicType.NEURAL_ASSOCIATION, priority=0.1)
        self.assertLessEqual(len(wm.items), 4)
        self.assertTrue(wm.list_by_kind("goal"))

    def test_neuro_items_not_verified(self) -> None:
        wm = WorkingMemory(capacity=8)
        item = wm.upsert(
            "fact",
            "neural hint",
            source_type=EpistemicType.NEURAL_ASSOCIATION,
            verified=True,
        )
        self.assertFalse(item.verified)
        self.assertLessEqual(item.priority, 0.35)


class PerceptionTests(unittest.TestCase):
    def test_provenance_and_source_separation(self) -> None:
        class FakeKnowledge:
            def search(self, query: str, limit: int = 5):
                return [{"id": "k1", "content": f"knowledge about {query}"}]

        class FakeMemory:
            def search(self, query: str, limit: int = 5):
                return [{"memory_id": "m1", "content": "exact fact about reconnect", "trust": "explicit"}]

        svc = PerceptionService(
            knowledge_store=FakeKnowledge(),
            memory_store=FakeMemory(),
            default_budget=20,
        )
        snap = svc.perceive("reconnect pending", history=[{"role": "user", "content": "fix it"}])
        types = {i.source_type for i in snap.items}
        self.assertIn(EpistemicType.KNOWLEDGE_SOURCE, types)
        self.assertIn(EpistemicType.EXACT_FACT, types)
        self.assertIn(EpistemicType.USER_STATEMENT, types)
        for item in snap.items:
            self.assertTrue(item.public_dict()["truth"]["perception_is_not_instruction"])


class ContextV3Tests(unittest.TestCase):
    def test_trust_labels_separate_neural_and_tools(self) -> None:
        task = TaskModelBuilder().build("Explain reconnect race")
        wm = WorkingMemory(capacity=8)
        wm.set_goal(task.goal)
        beliefs = BeliefState()
        beliefs.add("hypothesis A", category=BeliefCategory.HYPOTHESIS, confidence=0.5)
        perception = PerceptionService().perceive(
            task.raw_request,
            history=[{"role": "user", "content": task.raw_request}],
        )
        # Inject a neural item manually
        from Data.modules.cognition.perception import PerceptionItem
        import uuid

        perception.items.append(
            PerceptionItem(
                item_id=str(uuid.uuid4()),
                source_type=EpistemicType.NEURAL_ASSOCIATION,
                summary="advisory association",
                trust=0.2,
                confidence=0.3,
            )
        )
        result = ContextBuilderV3().build(
            task=task,
            working_memory=wm,
            beliefs=beliefs,
            perception=perception,
            capability_shortlist=["fs.read"],
        )
        blob = result.pack.system_prompt
        self.assertIn("TASK MODEL", blob)
        self.assertIn("SUCCESS CRITERIA", blob)
        self.assertTrue(result.pack.provenance.get("trust_labels"))
        # W1: neural/advisory content is DATA — not folded into system authority.
        self.assertNotIn("advisory association", blob)
        data = " ".join(
            s.content for s in result.pack.sections if s.included and s.kind != "system"
        )
        data += " ".join(m.get("content") or "" for m in result.pack.messages)
        self.assertIn("advisory association", data.lower() + data)
        self.assertEqual(
            result.pack.provenance.get("canonical_compiler"),
            "Data.modules.context.ContextBuilder",
        )


class MetaControllerTests(unittest.TestCase):
    def test_simple_stays_shallow(self) -> None:
        task = TaskModelBuilder().build("hi")
        decision = MetaController().decide(task)
        self.assertEqual(decision.mode, ReasoningMode.FAST)
        self.assertEqual(decision.budgets.max_model_calls, 1)
        self.assertEqual(decision.budgets.max_agent_delegations, 0)

    def test_complex_coding_escalates(self) -> None:
        task = TaskModelBuilder().build(
            "Debug and fix the MCP reconnect race that drops pending calls; add regression tests and keep the suite green"
        )
        decision = MetaController().decide(task, uncertainty=0.7)
        self.assertIn(decision.mode, {ReasoningMode.STANDARD, ReasoningMode.DEEP})
        self.assertGreaterEqual(decision.budgets.max_model_calls, 3)
        self.assertEqual(decision.strategy, ReasoningStrategy.CODING_REPAIR)

    def test_resource_pressure_reduces_work(self) -> None:
        task = TaskModelBuilder().build(
            "Research the latest evidence on local agent runtimes and compare sources carefully"
        )
        low = MetaController().decide(task, resource_pressure=0.0)
        high = MetaController().decide(task, resource_pressure=0.9)
        self.assertLessEqual(high.budgets.max_parallel_workers, low.budgets.max_parallel_workers)
        self.assertLessEqual(high.budgets.max_model_calls, low.budgets.max_model_calls)


class LoopDetectionTests(unittest.TestCase):
    def test_repeated_failing_action_detected(self) -> None:
        det = LD(threshold=3)
        action = CognitiveAction(
            kind=CognitiveActionKind.INVOKE_CAPABILITY,
            action_id="a1",
            capability_id="x",
            arguments={"path": "/tmp"},
        )
        for _ in range(2):
            info = det.observe(action, failure="boom")
            self.assertFalse(info["loop_detected"])
        info = det.observe(action, failure="boom")
        self.assertTrue(info["loop_detected"])


class CapabilityBrokerTests(unittest.TestCase):
    def test_availability_independent_of_keyword_nlu(self) -> None:
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="mcp.demo.tool",
                name="Demo Tool",
                description="Does a demo thing",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.MCP,
                provider_ref="demo",
                input_schema={},
                output_schema={},
                available=True,
            )
        )
        broker = CapabilityBroker(catalog)
        # Query without tool keywords still finds capability by description/id search.
        short = broker.search("demo", limit=5)
        self.assertIn("mcp.demo.tool", short.capability_ids)
        self.assertTrue(short.public_dict()["truth"]["availability_independent_of_keyword_nlu"])


class CompletionTests(unittest.TestCase):
    def test_model_cannot_self_complete_without_criteria(self) -> None:
        task = TaskModelBuilder().build(
            "Fix the Python reconnect bug and ensure tests pass with evidence"
        )
        decision = CompletionEngine().evaluate(
            task,
            observations=[],
            response_text="I fixed everything successfully.",
            verification_passed=None,
        )
        self.assertNotEqual(decision.status, CognitiveRunStatus.COMPLETED_VERIFIED)

    def test_verified_completion_requires_verification(self) -> None:
        task = TaskModelBuilder().build("hello")
        decision = CompletionEngine().evaluate(
            task,
            observations=[],
            response_text="Hi there, how can I help?",
        )
        self.assertEqual(decision.status, CognitiveRunStatus.COMPLETED_UNVERIFIED)


class ExperienceTests(unittest.TestCase):
    def test_unverified_rejected_from_learning(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("hello")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
            strategy=ReasoningStrategy.DIRECT,
            action_summaries=["RESPOND"],
            verification_status="UNMEASURED",
        )
        admitted = store.admit(exp)
        self.assertFalse(admitted.admitted)

    def test_verified_can_be_admitted(self) -> None:
        store = ExperienceStore()
        task = TaskModelBuilder().build("Fix reconnect race with tests")
        exp = store.build_from_run(
            task=task,
            status=CognitiveRunStatus.COMPLETED_VERIFIED,
            strategy=ReasoningStrategy.CODING_REPAIR,
            action_summaries=["RETRIEVE", "DELEGATE_AGENT", "VERIFY"],
            verification_status="PASSED",
            evidence_refs=["ev-1"],
        )
        admitted = store.admit(exp)
        self.assertTrue(admitted.admitted)
        self.assertTrue(store.training_candidates()[0]["auto_promote_forbidden"])


class TransitionTests(unittest.TestCase):
    def test_invalid_transition_rejected(self) -> None:
        self.assertFalse(
            validate_transition(
                CognitiveRunStatus.COMPLETED_VERIFIED,
                CognitiveRunStatus.EXECUTING,
            )
        )
        self.assertTrue(
            validate_transition(
                CognitiveRunStatus.CREATED,
                CognitiveRunStatus.PERCEIVING,
            )
        )


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "cog.db"
        MigrationRunner(self.db_path).apply_all()
        self.store = CognitionStore(self.db_path)

        def model_caller(**kwargs):
            return "Public answer based on provided context."

        self.runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=True,
            belief_enabled=True,
            experience_learning=True,
            store=self.store,
            model_caller=model_caller,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_one_step_simple_chat(self) -> None:
        result = self.runtime.submit("hello")
        self.assertIn(result["status"], {
            CognitiveRunStatus.COMPLETED_UNVERIFIED.value,
            CognitiveRunStatus.COMPLETED_VERIFIED.value,
            CognitiveRunStatus.PARTIAL.value,
        })
        self.assertTrue(result["truth"]["no_private_cot"])
        row = self.store.get_run(result["run_id"])
        self.assertIsNotNone(row)

    def test_shadow_mode_no_user_answer_replacement(self) -> None:
        result = self.runtime.submit("Research local agent architectures", shadow=True)
        self.assertEqual(result["status"], CognitiveRunStatus.SHADOW.value)
        self.assertFalse((result.get("response_preview") or "").strip())
        # shadow completion reason present
        self.assertEqual(result["completion"]["status"], "SHADOW")

    def test_cancellation(self) -> None:
        # submit without running then cancel
        submitted = self.runtime.submit("long task please", run=False)
        cancelled = self.runtime.cancel(submitted["run_id"])
        self.assertEqual(cancelled["status"], CognitiveRunStatus.CANCELLED.value)
        self.assertTrue(cancelled["cancel_acknowledged"])

    def test_loop_detection_stops(self) -> None:
        # Force selector into repeated COMPLETE with failing pattern via detector unit already;
        # here ensure iterative run terminates.
        result = self.runtime.submit(
            "Compare alternatives for reconnect ownership and explain conflicts without certainty"
        )
        self.assertIn(result["status"], {s.value for s in CognitiveRunStatus})
        self.assertNotEqual(result["status"], CognitiveRunStatus.CREATED.value)

    def test_feature_disabled(self) -> None:
        rt = CognitiveRuntime(enabled=False)
        from Data.modules.cognition import CognitionFeatureDisabled

        with self.assertRaises(CognitionFeatureDisabled):
            rt.submit("hi")


class ConfigFlagTests(unittest.TestCase):
    def test_cognition_child_requires_parent(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_COGNITION": "false",
            "LEVIATHAN_FEATURE_COGNITION_SHADOW": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_cognition_neuro_requires_neuro(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_COGNITION": "true",
            "LEVIATHAN_FEATURE_COGNITION_NEURO": "true",
            "LEVIATHAN_FEATURE_NEURO": "false",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_cognition_flags_load(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_COGNITION": "true",
            "LEVIATHAN_FEATURE_COGNITION_SHADOW": "true",
            "LEVIATHAN_FEATURE_COGNITION_EXPERIENCE_LEARNING": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertTrue(cfg.features.cognition_enabled)
        self.assertTrue(cfg.features.cognition_shadow)
        self.assertTrue(cfg.features.cognition_experience_learning)
        self.assertIn("cognition_enabled", cfg.public_summary()["features"])


class MigrationTests(unittest.TestCase):
    def test_v19_creates_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            applied = MigrationRunner(path).apply_all()
            self.assertIn(19, applied)
            store = CognitionStore(path)
            run = store.create_run(task_id="t1", task_json={"goal": "x"})
            self.assertTrue(run["run_id"])
            store.add_event(run["run_id"], "task_created", {"ok": True})
            self.assertEqual(len(store.list_events(run["run_id"])), 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
