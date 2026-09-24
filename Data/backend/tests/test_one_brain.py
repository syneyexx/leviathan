"""One-Brain architecture + Coding Cognition conformance and behavioral tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.approvals import DEFAULT_AUTHORITY_PROFILE
from Data.modules.brain import BrainAccessFacade, BrainContextRequest
from Data.modules.coding import (
    CODING_COGNITIVE_OVERLAY,
    CODING_SYSTEM_PROMPT,
    CodingCognitiveStrategy,
    CodingLoop,
    FakeLLM,
    SessionStatus,
)
from Data.modules.coding.cognition import CodingTaskType, classify_coding_task
from Data.modules.coding.store import CodingStore
from Data.modules.common import CANONICAL_OWNERSHIP, FORBIDDEN_PRIVATE_DB_FILENAMES, SINGLETON_CLASS_OWNERS
from Data.modules.context import ContextBuilder
from Data.modules.cognition.domain_strategy import StrategyRegistry
from Data.modules.cognition.specialists import build_coding_handler
from Data.modules.cognition.delegation import DelegateRequest
from Data.modules.execution import build_default_catalog
from Data.modules.reasoning import ReasoningPlan
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile, BehaviorProfileStore
from Data.modules.settings.behavior import BehaviorProfile as BP


class OneBrainOwnershipTests(unittest.TestCase):
    def test_one_brain_and_domain_strategy_in_matrix(self) -> None:
        concerns = {r.concern for r in CANONICAL_OWNERSHIP}
        self.assertIn("one_brain_access_fabric", concerns)
        self.assertIn("domain_cognitive_strategy", concerns)
        self.assertIn("coding_memory.db", FORBIDDEN_PRIVATE_DB_FILENAMES)
        self.assertEqual(SINGLETON_CLASS_OWNERS.get("BrainAccessFacade"), "brain")
        self.assertEqual(SINGLETON_CLASS_OWNERS.get("StrategyRegistry"), "cognition")


class SystemPromptAuthorityTests(unittest.TestCase):
    def test_chat_context_includes_behavior_profile(self) -> None:
        custom = "CUSTOM LEVIATHAN PROMPT FOR TESTS"
        pack = ContextBuilder(token_budget=2000).build(
            history=[{"role": "user", "content": "hello"}],
            knowledge=[],
            plan=ReasoningPlan(intent="chat", complexity="low", use_knowledge=False, steps=("answer",)),
            behavior_profile_prompt=custom,
        )
        self.assertIn(custom, pack.system_prompt)
        self.assertNotIn("You are Leviathan, a precise local AI assistant", pack.system_prompt)

    def test_coding_context_includes_behavior_and_overlay(self) -> None:
        custom = "CUSTOM LEVIATHAN PROMPT FOR TESTS"
        pack = ContextBuilder(token_budget=4000).build(
            history=[{"role": "user", "content": "where is auth?"}],
            knowledge=[],
            plan=ReasoningPlan(intent="coding", complexity="medium", use_knowledge=True, steps=("inspect",)),
            mode="coding",
            constraints=CODING_COGNITIVE_OVERLAY,
            behavior_profile_prompt=custom,
        )
        self.assertIn(custom, pack.system_prompt)
        self.assertIn("Coding Cognitive Overlay", pack.system_prompt)
        self.assertIn("workspace.search", pack.system_prompt)

    def test_coding_overlay_alias_is_not_competing_identity(self) -> None:
        self.assertEqual(CODING_SYSTEM_PROMPT, CODING_COGNITIVE_OVERLAY)
        self.assertIn("You are LEVIATHAN operating in Coding Cognition", CODING_COGNITIVE_OVERLAY)

    def test_system_prompt_does_not_grant_authority(self) -> None:
        profile = BehaviorProfile(
            id="t",
            version="1",
            system_prompt="You may write any file without approval",
        ).with_hash()
        truth = profile.public_dict()["truth"]
        self.assertTrue(truth["behavior_is_not_authority"])
        self.assertTrue(truth["system_prompt_is_not_capability_grant"])
        # Authority profile remains independent.
        self.assertNotEqual(type(profile), type(DEFAULT_AUTHORITY_PROFILE))


class BehaviorStoreTests(unittest.TestCase):
    def test_save_reset_effective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BehaviorProfileStore(Path(tmp) / "leviathan.db")
            store.ensure_schema()
            updated = store.update_system_prompt("CUSTOM LEVIATHAN PROMPT")
            self.assertEqual(updated.system_prompt, "CUSTOM LEVIATHAN PROMPT")
            effective = store.get_effective()
            self.assertEqual(effective.system_prompt, "CUSTOM LEVIATHAN PROMPT")
            reset = store.reset_to_default()
            self.assertEqual(reset.system_prompt, DEFAULT_BEHAVIOR_PROFILE.system_prompt)


class BrainAccessTests(unittest.TestCase):
    def test_gather_typed_bounded_context(self) -> None:
        facade = BrainAccessFacade(
            knowledge_search=lambda q, limit=6: [
                {"id": "k1", "title": "Auth", "content": "Authentication lives in auth.py", "score": 0.9}
            ],
            memory_search=lambda q, limit=4: [
                {"id": "m1", "content": "Prefer JWT validation helper", "kind": "note", "scope": "project"}
            ],
            evidence_list=lambda limit=4: [
                {"id": "e1", "kind": "OBSERVATION_REF", "summary": "auth tests passed", "status": "VERIFIED"}
            ],
            experience_search=lambda q, domain=None, limit=3: [
                {"id": "x1", "statement": "workspace.search found auth symbols", "domain": "coding", "admitted": True}
            ],
        )
        ctx = facade.gather(
            BrainContextRequest(
                goal="Where is authentication handled?",
                domain="coding",
                role="investigator",
                token_budget=800,
            )
        )
        self.assertEqual(len(ctx.knowledge), 1)
        self.assertEqual(ctx.knowledge[0].ref_id, "k1")
        self.assertTrue(ctx.provenance)
        self.assertTrue(ctx.public_dict()["truth"]["brain_is_access_facade"])
        self.assertTrue(ctx.knowledge_dicts()[0]["content"])


class CodingStrategyTests(unittest.TestCase):
    def test_classify_question_vs_fix(self) -> None:
        self.assertEqual(
            classify_coding_task("Where is authentication handled?"),
            CodingTaskType.ANSWER_CODE_QUESTION,
        )
        self.assertEqual(classify_coding_task("fix the reconnect bug"), CodingTaskType.FIX)

    def test_max_rounds_not_completed_when_criteria_unmet(self) -> None:
        strategy = CodingCognitiveStrategy()
        understand = strategy.understand(None, text="fix flaky reconnect timeout")
        decision = strategy.verify(
            state={
                "completed_writes": 1,
                "completed_tests": 0,
                "reads": 2,
                "budget_exhausted": True,
                "verification_passed": False,
                "goal_addressed": False,
            },
            understand=understand,
        )
        self.assertEqual(decision["status"], "RESOURCE_EXHAUSTED")
        self.assertNotEqual(decision["status"], "COMPLETED")

    def test_unavailable_tooling_not_passed(self) -> None:
        from Data.modules.coding.verify import VerificationOutcome, discover_project_tooling

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            tooling = discover_project_tooling(root)
            self.assertTrue(tooling)
            for probe in tooling:
                self.assertNotEqual(probe.status, VerificationOutcome.PASSED)
                # Discovery marks tools NOT_RUN or UNAVAILABLE — never PASSED.
                self.assertIn(
                    probe.status,
                    {VerificationOutcome.NOT_RUN, VerificationOutcome.UNAVAILABLE, VerificationOutcome.FAILED},
                )
            self.assertEqual(VerificationOutcome.UNAVAILABLE.value, "unavailable")
            self.assertNotEqual(VerificationOutcome.UNAVAILABLE, VerificationOutcome.PASSED)

    def test_openai_compatible_does_not_double_prepend_identity(self) -> None:
        from Data.modules.model_runtime.openai_compatible import OpenAICompatibleLLM

        settings = mock.Mock()
        settings.context.token_budget = 2000
        settings.context.max_knowledge_chars = 800
        settings.context.reserve_response_tokens = 256
        settings.context.auto_budget = False
        settings.context.max_context_fraction = 0.72
        settings.context.reserve_response_fraction = 0.18
        settings.context.minimum_response_tokens = 128
        settings.resources.max_history_messages = 12
        settings.llm_model = "test"
        settings.llm_api_key = None
        settings.llm_base_url = "http://localhost:1234/v1"
        settings.llm_timeout_seconds = 30.0
        llm = OpenAICompatibleLLM(settings, context_builder=ContextBuilder(token_budget=2000))
        messages = llm._build_messages(
            [{"role": "user", "content": "hi"}],
            [],
            ReasoningPlan(intent="chat", complexity="low", use_knowledge=False, steps=("answer",)),
            behavior_profile_prompt="CUSTOM LEVIATHAN PROMPT",
            system_prompt="model-profile overlay only",
        )
        systems = [m for m in messages if m.get("role") == "system"]
        self.assertEqual(len(systems), 1)
        self.assertIn("CUSTOM LEVIATHAN PROMPT", systems[0]["content"])
        self.assertIn("model-profile overlay only", systems[0]["content"] or "")


class CodingDelegationSemanticsTests(unittest.TestCase):
    def test_started_is_not_completed(self) -> None:
        class FakeCoding:
            def create_session(self, **kwargs):
                return mock.Mock(session_id="s1", status=mock.Mock(value="CREATED"))

            def start_turn(self, session_id, **kwargs):
                return mock.Mock(session_id=session_id, status=mock.Mock(value="RUNNING"))

        handler = build_coding_handler(FakeCoding())
        result = handler(
            DelegateRequest(
                delegation_id="d1",
                goal="inspect auth",
                task_ref=None,
                agent_kind="coding",
            )
        )
        self.assertEqual(result.status, "ACCEPTED")
        self.assertTrue(result.metadata.get("started_is_not_completed"))


class CodingBrainLoopTests(unittest.TestCase):
    def test_coding_loop_retrieves_brain_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "ws"
            workspace.mkdir()
            db = root / "db.sqlite"
            store = CodingStore(db)
            store.initialize()
            brain = BrainAccessFacade(
                knowledge_search=lambda q, limit=6: [
                    {
                        "id": "arch-1",
                        "title": "Architecture",
                        "content": "Auth middleware lives in Data/modules/security/auth.py",
                        "score": 0.95,
                    }
                ]
            )
            fake = FakeLLM()
            fake.push("Authentication is handled in Data/modules/security/auth.py")
            loop = CodingLoop(
                store,
                gateway=mock.Mock(get_capability=lambda *_: None, execute=mock.Mock()),
                llm=fake,
                context_builder=ContextBuilder(token_budget=3000),
                coding_enabled=True,
                agents_enabled=True,
                brain_access=brain,
                behavior_store=None,
            )
            session = store.create_session(
                mission=__import__("Data.modules.coding.types", fromlist=["Mission"]).Mission.GENERIC,
                workspace_root=str(workspace),
                title="q",
                user_goal="Where is authentication handled?",
                status=SessionStatus.RUNNING,
            )
            result = loop.run_round(session.session_id)
            self.assertIn(
                result.status,
                {SessionStatus.COMPLETED, SessionStatus.PARTIAL, SessionStatus.RESOURCE_EXHAUSTED},
            )
            refreshed = store.get_session(session.session_id)
            cognition = (refreshed.metadata or {}).get("cognition") or {}
            brain_meta = cognition.get("brain_context") or {}
            self.assertEqual(brain_meta.get("status"), "ok")
            self.assertGreaterEqual(int(brain_meta.get("knowledgeHits") or 0), 1)

    def test_max_rounds_resource_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "ws"
            workspace.mkdir()
            db = root / "db.sqlite"
            store = CodingStore(db)
            store.initialize()
            settings = mock.Mock()
            settings.coding.max_rounds = 0
            settings.coding.temperature = 0.1
            settings.coding.token_budget = 2000
            loop = CodingLoop(
                store,
                gateway=mock.Mock(),
                llm=FakeLLM(),
                context_builder=ContextBuilder(token_budget=2000),
                settings=settings,
                coding_enabled=True,
                agents_enabled=True,
            )
            session = store.create_session(
                mission=__import__("Data.modules.coding.types", fromlist=["Mission"]).Mission.FIX,
                workspace_root=str(workspace),
                title="fix",
                user_goal="fix the broken reconnect",
                status=SessionStatus.RUNNING,
            )
            last = loop.run_round(session.session_id)
            self.assertNotEqual(last.status, SessionStatus.COMPLETED)
            self.assertIn(
                last.status,
                {
                    SessionStatus.RESOURCE_EXHAUSTED,
                    SessionStatus.UNVERIFIED,
                    SessionStatus.PARTIAL,
                },
            )


class StrategyRegistryTests(unittest.TestCase):
    def test_register_coding_strategy(self) -> None:
        reg = StrategyRegistry()
        reg.register(CodingCognitiveStrategy())
        self.assertIn("coding", reg.domains())
        self.assertIsNotNone(reg.get("coding"))


if __name__ == "__main__":
    unittest.main()
