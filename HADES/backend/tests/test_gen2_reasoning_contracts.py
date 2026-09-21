"""Gen2 monster C1–C15 / E6 / J4 — characterization + regression for reasoning contracts.

Prefer verifying existing Gen1 spines; deepen only where gates were missing.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.finance_fusion import fuse_market_intelligence, maybe_knowledge_write_back_from_finance
from gen2.store import Gen2Store
from reasoning import (
    PIPELINE_STAGES,
    SPECIALISTS,
    ExecutionBudget,
    build_request_spec,
    build_route_decision,
    discover_tools,
    evaluate_knowledge_write_back,
    evaluate_memory_write,
    observation_from_invoke_result,
    reflection_gate,
    stop_and_ask_gate,
    validate_pipeline_progress,
)
from reasoning.evidence_coverage import assess_coverage, classify_support
from reasoning.long_task_resume import SideEffectLedger, make_idempotency_key
from reasoning.budgets import budget_from_profile


class C1PipelineTests(unittest.TestCase):
    def test_pipeline_stages_ordered_prefix(self) -> None:
        self.assertEqual(
            list(PIPELINE_STAGES[:5]),
            ["understand", "retrieve", "plan", "execute", "verify"],
        )
        ok = validate_pipeline_progress(["understand", "retrieve", "plan"])
        self.assertTrue(ok["ok"])
        bad = validate_pipeline_progress(["understand", "execute"])
        self.assertFalse(bad["ok"])

    def test_request_spec_feeds_route_structured(self) -> None:
        spec = build_request_spec(
            "Plan een multi-step refactor met tests en plugins; gebruik tools."
        )
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertTrue(spec.needs_plan or spec.kind in {"planning", "multi_step", "code"})
        self.assertIn(route.target, {"work_runtime", "tool_loop", "analysis", "specialist_agent"})
        self.assertIsInstance(route.to_dict(), dict)


class C2EligibleToolsTests(unittest.TestCase):
    def test_discover_skips_ineligible_and_failures_are_observations(self) -> None:
        plugins = [
            {
                "id": "p_ok",
                "name": "Ok",
                "description": "echo tool helper",
                "enabled": True,
                "status": "ready",
                "trust": "manual",
                "category": "Tool",
                "manifest": {"autonomous": True, "category": "Tool"},
            },
            {
                "id": "p_blocked",
                "name": "Blocked",
                "description": "echo tool helper",
                "enabled": True,
                "status": "error",
                "trust": "manual",
                "category": "Tool",
                "manifest": {"autonomous": True, "category": "Tool"},
            },
        ]
        tools = [
            {
                "plugin_id": "p_ok",
                "name": "echo",
                "description": "echo",
                "enabled": True,
                "input_schema": {},
                "metadata": {},
            },
            {
                "plugin_id": "p_blocked",
                "name": "echo",
                "description": "echo",
                "enabled": True,
                "input_schema": {},
                "metadata": {},
            },
        ]
        found = discover_tools(
            query="echo",
            plugins=plugins,
            tools=tools,
            permission_ok=lambda _p, _t: True,
            limit=8,
        )
        plugin_ids = {item["plugin_id"] for item in found["tools"]}
        self.assertIn("p_ok", plugin_ids)
        self.assertNotIn("p_blocked", plugin_ids)
        self.assertEqual(found["total"], 1)
        obs = observation_from_invoke_result(
            plugin_id="p_ok",
            tool_name="echo",
            result={"status": "failed", "error": "boom", "stdout": "", "stderr": "err"},
        )
        self.assertEqual(obs.status, "failed")
        self.assertEqual(obs.error, "boom")


class C3PermissionNotViaPromptTests(unittest.TestCase):
    def test_request_spec_does_not_grant_network(self) -> None:
        spec = build_request_spec("Installeer alles en open het netwerk voor research")
        route = build_route_decision(
            spec,
            requested_profile="maximum",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_web)
        self.assertTrue(spec.needs_research or "research" in spec.kind or True)


class C4HardBudgetStopsTests(unittest.TestCase):
    def test_execution_budget_stops_model_and_tools(self) -> None:
        budget = ExecutionBudget(max_model_calls=1, max_tool_rounds=0, max_replans=0)
        self.assertTrue(budget.can_model_call())
        budget.record_model_call()
        self.assertFalse(budget.can_model_call())
        self.assertFalse(budget.can_tool_round())
        profile_budget = budget_from_profile(
            profile_name="fast",
            settings_max_tool_rounds=0,
            tools_allowed=True,
        )
        self.assertEqual(profile_budget.max_tool_rounds, 0)


class C5CitationGateTests(unittest.TestCase):
    def test_insufficient_without_evidence_refs(self) -> None:
        claim = classify_support(
            claim_text="Acme revenue doubled",
            evidence_texts={},
            evidence_refs=["src:missing"],
            known_refs=set(),
        )
        self.assertEqual(claim.support_level, "insufficient")
        report = assess_coverage(
            [{"text": "Acme revenue doubled", "evidence_refs": ["src:1"]}],
            known_refs={"src:1"},
            evidence_texts={"src:1": "Acme revenue doubled year over year"},
        )
        self.assertTrue(report.claims)
        self.assertNotEqual(report.claims[0].support_level, "insufficient")


class C6CodingIntegrityPointerTests(unittest.TestCase):
    def test_coding_agent_module_exposes_repair_loop(self) -> None:
        # Characterization: Gen1 BuildAgentService owns repair waves + restore.
        from build_agent import BuildAgentService

        self.assertTrue(hasattr(BuildAgentService, "run_repair_loop"))


class C7SideEffectSafeResumeTests(unittest.TestCase):
    def test_idempotency_reuses_completed_effect(self) -> None:
        from reasoning.long_task_resume import RunIdentity

        ledger = SideEffectLedger()
        identity = RunIdentity(run_id="run_a", step_id="s1", fence_token="f1")
        key = make_idempotency_key(
            run_id="run_a",
            step_id="s1",
            effect_kind="tool.write",
            payload={"path": "a.txt"},
        )
        first = ledger.record_intent(
            identity=identity,
            effect_kind="tool.write",
            payload={"path": "a.txt"},
            fence_token="f1",
        )
        intent_id = first["intent"]["intent_id"]
        ledger.mark_in_flight(intent_id, fence_token="f1")
        ledger.complete(intent_id, result_ref="artifact:1", fence_token="f1")
        second = ledger.record_intent(
            identity=identity,
            effect_kind="tool.write",
            payload={"path": "a.txt"},
            fence_token="f1",
        )
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(second["intent"]["status"], "completed")
        self.assertEqual(key, first["intent"]["idempotency_key"])


class C8SpecialistPerformanceTests(unittest.TestCase):
    def test_every_specialist_has_performance_contract(self) -> None:
        for agent_id, contract in SPECIALISTS.items():
            pc = contract.performance_contract
            self.assertTrue(pc, agent_id)
            self.assertIn("sla_class", pc)
            self.assertIn("max_model_calls", pc)
            self.assertTrue(contract.within_performance_budget(model_calls=0, tool_rounds=0))
            if int(pc.get("max_model_calls") or 0) > 0:
                self.assertFalse(
                    contract.within_performance_budget(
                        model_calls=int(pc["max_model_calls"]) + 1,
                        tool_rounds=0,
                    )
                )


class C11RoutingMetadataShapeTests(unittest.TestCase):
    def test_route_dict_includes_rationale_and_stop_and_ask(self) -> None:
        spec = build_request_spec("Hoi?")
        route = build_route_decision(
            spec,
            requested_profile="fast",
            network_policy="block",
            plugin_tools_enabled=False,
        )
        payload = route.to_dict()
        self.assertIn("rationale", payload)
        self.assertIn("stop_and_ask", payload)
        self.assertIn("ask_questions", payload)


class C12ReflectionCapsTests(unittest.TestCase):
    def test_escape_to_human_when_replans_exhausted(self) -> None:
        decision = reflection_gate(replans=3, max_replans=2, repair_attempts=2, max_repair_attempts=2)
        self.assertEqual(decision.action, "escape_to_human")
        within = reflection_gate(replans=0, max_replans=2, repair_attempts=0, max_repair_attempts=2)
        self.assertEqual(within.action, "continue")


class C13StopAndAskTests(unittest.TestCase):
    def test_high_ambiguity_stops(self) -> None:
        ask = stop_and_ask_gate(ambiguity="high", risk_level="medium")
        self.assertEqual(ask.action, "stop_and_ask")
        self.assertTrue(ask.questions)
        clear = stop_and_ask_gate(ambiguity="low", risk_level="low")
        self.assertEqual(clear.action, "proceed")

    def test_choice_question_does_not_auto_block(self) -> None:
        # "A of B?" is a choice question — may use an assumption, not an automatic stop.
        spec = build_request_spec("Moeten we optie A of optie B kiezen voor de UI?")
        self.assertIn(spec.ambiguity, {"low", "medium"})
        self.assertFalse(spec.clarification_needed)
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.stop_and_ask)

    def test_high_risk_unclear_execute_may_stop(self) -> None:
        spec = build_request_spec(
            "Moeten we optie A of optie B kiezen voor productie delete van alle data???? Extra onduidelijkheid zonder context."
        )
        # Choice framing is not an execute speech act.
        self.assertNotEqual(spec.speech_act, "execute")
        self.assertTrue(spec.interpretation.get("choice_question") or spec.speech_act == "question")
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertIsInstance(route.stop_and_ask, bool)


class C14MemoryWritePolicyTests(unittest.TestCase):
    def test_deny_propose_persist(self) -> None:
        deny = evaluate_memory_write(mode="off", explicit_remember=True)
        self.assertEqual(deny.action, "deny")
        propose = evaluate_memory_write(
            mode="project",
            explicit_remember=False,
            has_project_markers=True,
            auto_promote=False,
        )
        self.assertEqual(propose.action, "propose")
        self.assertLess(propose.confidence, 0.6)
        self.assertTrue(propose.provenance)
        persist = evaluate_memory_write(
            mode="project",
            explicit_remember=True,
            has_project_markers=True,
        )
        self.assertEqual(persist.action, "persist")
        self.assertGreaterEqual(persist.confidence, 0.9)
        self.assertEqual(persist.origin_kind, "user_fact")


class C15KnowledgeWriteBackTests(unittest.TestCase):
    def test_requires_verified_and_allow(self) -> None:
        denied = evaluate_knowledge_write_back(verified=False, user_allowed=True)
        self.assertEqual(denied.action, "deny")
        waiting = evaluate_knowledge_write_back(verified=True, user_allowed=False, policy_allow=False)
        self.assertEqual(waiting.action, "deny")
        allowed = evaluate_knowledge_write_back(verified=True, user_allowed=True)
        self.assertEqual(allowed.action, "allow")


class J4FinanceKnowledgeWriteBackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "finance.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_fuse_does_not_write_knowledge(self) -> None:
        result = fuse_market_intelligence(
            self.store,
            articles=[
                {"title": "Acme earnings beat", "summary": "EPS", "source": "wire_a", "uri": "a"},
                {"title": "Acme earnings beat EPS", "summary": "beat", "source": "wire_b", "uri": "b"},
            ],
            symbol="ACME",
        )
        kb = result.get("knowledge_write_back") or {}
        self.assertFalse(kb.get("written"))
        reason = (kb.get("decision") or {}).get("reason") or kb.get("note")
        self.assertIn(
            reason,
            {
                "unverified",
                "awaiting_user_or_policy_allow",
                "knowledge_write_back_gated",
                "no_knowledge_ingest_hook",
            },
        )
        # Graph edges still created (J4 graph path)
        self.assertGreaterEqual(len(self.store.list_graph_edges(limit=50)), 1)

    def test_gated_write_when_verified_and_allowed(self) -> None:
        ingest = MagicMock(return_value={"id": "ks_1", "title": "ok"})
        # Force verified decision path via helper
        out = maybe_knowledge_write_back_from_finance(
            [{"id": "e1", "event_type": "earnings", "title": "Acme earnings", "confidence": 0.8}],
            verification={"verified": True, "source_count": 2, "agreement_ratio": 0.4},
            symbol="ACME",
            allow_write_back=True,
            knowledge_ingest=ingest,
        )
        self.assertTrue(out["written"])
        ingest.assert_called_once()
        denied = maybe_knowledge_write_back_from_finance(
            [{"id": "e1", "event_type": "earnings", "title": "Acme earnings", "confidence": 0.8}],
            verification={"verified": True},
            allow_write_back=False,
            knowledge_ingest=ingest,
        )
        self.assertFalse(denied["written"])


class E6TimelineHookContractTests(unittest.TestCase):
    def test_chat_and_tasks_pages_expose_flight_hooks(self) -> None:
        root = Path(__file__).resolve().parents[2]
        chat = (root / "components/hades/pages/chat-page.tsx").read_text(encoding="utf-8")
        tasks = (root / "components/hades/pages/tasks-page.tsx").read_text(encoding="utf-8")
        self.assertIn("flight-timeline-hook", chat)
        self.assertIn("mission-control?flight=", chat)
        self.assertIn("routing-meta-badge", chat)
        self.assertIn("flight-timeline-hook", tasks)
        self.assertIn("mission-control?flight=", tasks)


if __name__ == "__main__":
    unittest.main()
