"""Functional hardening campaign — Wave 0–7 regression tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SchemaTaxonomyTests(unittest.TestCase):
    def test_finalize_outcome_and_taxonomy(self) -> None:
        from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
        from evals.functional.taxonomy import classify_campaign_failure, map_to_legacy_failure_class

        rec = new_record(task_id="t1", task_family="intent", outcome="success")
        finalize_outcome(rec)
        self.assertTrue(rec.success)
        self.assertEqual(rec.status, "PASS")
        self.assertEqual(map_to_legacy_failure_class("false_execution"), "SCOPE_VIOLATION")
        tax = classify_campaign_failure(outcome="failure", family="intent", signals={"false_execution": True})
        self.assertEqual(tax["failure_class"], "false_execution")
        self.assertIn("HADES +", ModelIdentity(model_id="x", model_runtime="lm_studio").label())


class IntentSuiteTests(unittest.TestCase):
    def test_intent_suite_zero_false_execution(self) -> None:
        from evals.functional.intent_eval import run_intent_suite

        report = run_intent_suite()
        self.assertGreaterEqual(report["metrics"]["intent_accuracy"], 0.95)
        self.assertEqual(report["metrics"]["false_execution_count"], 0)
        self.assertEqual(report["metrics"]["false_execution_rate"], 0.0)

    def test_rm_explain_not_execute(self) -> None:
        from reasoning.understanding import build_request_spec, build_route_decision

        spec = build_request_spec("Leg uit hoe ik rm -rf zou uitvoeren")
        self.assertEqual(spec.speech_act, "explain")
        self.assertFalse(spec.needs_tools)
        route = build_route_decision(
            spec, requested_profile="adaptive", network_policy="block", plugin_tools_enabled=True
        )
        self.assertEqual(route.target, "direct_chat")
        self.assertFalse(route.allow_tools)
        self.assertEqual(route.max_tool_rounds, 0)
    def test_do_not_execute_walkthrough(self) -> None:
        from reasoning.understanding import build_request_spec

        spec = build_request_spec(
            "Walk me through how rm -rf / would work; do not execute anything"
        )
        self.assertNotEqual(spec.speech_act, "execute")
        self.assertFalse(spec.needs_tools)
        self.assertEqual(spec.risk_level, "low")

    def test_voer_dat_nu_uit_with_pending_tool(self) -> None:
        from reasoning.understanding import build_request_spec

        spec = build_request_spec(
            "Voer dat nu uit",
            conversation_state={"last_assistant": "Kan echo gebruiken", "pending_tool": "echo"},
        )
        self.assertEqual(spec.speech_act, "execute")
        self.assertTrue(spec.needs_tools)
        self.assertTrue(spec.interpretation.get("follow_up"))


class VerificationAblationTests(unittest.TestCase):
    def test_noisy_and_unavailable_critic_cannot_false_pass(self) -> None:
        from evals.functional.verification_ablation import run_verification_ablation

        report = run_verification_ablation()
        self.assertTrue(report["gate"]["passed"])
        self.assertEqual(report["modes"]["C"]["false_pass"], 0)
        self.assertEqual(report["modes"]["D"]["false_pass"], 0)


class RetrievalSuiteTests(unittest.TestCase):
    def test_retrieval_suite_runs(self) -> None:
        from evals.functional.retrieval_eval import run_retrieval_suite

        report = run_retrieval_suite()
        self.assertIn("summaries", report)
        self.assertGreater(report["query_count"], 10)
        lexical = report["summaries"].get("lexical") or {}
        self.assertIn("Recall@K", lexical)

    def test_multilingual_expand_helper(self) -> None:
        from reasoning.retrieval import expand_query_multilingual

        expanded = expand_query_multilingual("Wat is retrieval-augmented generation?")
        self.assertIn("generatie", expanded.lower())


class SpecialistAndSandboxTests(unittest.TestCase):
    def test_specialist_classes_honest(self) -> None:
        from evals.functional.specialist_audit import classify_specialists

        report = classify_specialists()
        self.assertIn("DOMAIN_ENGINE", report["by_class"])
        self.assertIn("build", report["by_class"]["DOMAIN_ENGINE"])
        self.assertIn("trading_specialist", report["by_class"]["DOMAIN_ENGINE"])

    def test_windows_matrix_does_not_claim_full_jail(self) -> None:
        from evals.functional.windows_threat_matrix import build_threat_matrix

        report = build_threat_matrix()
        self.assertFalse(report["summary"]["job_objects_are_full_fs_network_jail"])
        self.assertTrue(report["summary"]["secured_mode_fail_closed"])


class ChatCoordinatorTests(unittest.TestCase):
    def test_stage_machine_and_cancel(self) -> None:
        from reasoning.chat_coordinator import ChatRunContext, ChatStage, STAGE_ORDER

        ctx = ChatRunContext(request_id="r1", conversation_id="c1")
        self.assertEqual(ctx.stage, ChatStage.RECEIVED)
        ctx.advance(ChatStage.UNDERSTOOD)
        self.assertEqual(ctx.stage, ChatStage.UNDERSTOOD)
        ctx.request_cancel()
        self.assertEqual(ctx.advance(ChatStage.EXECUTING), ChatStage.CANCELLED)
        self.assertEqual(STAGE_ORDER[0], ChatStage.RECEIVED)

    def test_pipeline_characterization(self) -> None:
        from evals.functional.chat_pipeline import characterize_chat_pipeline

        report = characterize_chat_pipeline()
        self.assertIn("streaming", report["must_preserve"])
        self.assertEqual(report["extraction_status"], "partial_coordinator_bridged")


class ToolUseAndCodingPortableTests(unittest.TestCase):
    def test_tool_shortlist(self) -> None:
        from evals.functional.tool_use_eval import run_tool_use_suite

        report = run_tool_use_suite()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["metrics"]["tool_selection_accuracy"], 1.0)

    def test_coding_manifest_export(self) -> None:
        from evals.functional.coding_portable import export_portable_manifest

        manifest = export_portable_manifest()
        self.assertGreaterEqual(len(manifest["cases"]), 5)
        self.assertIn("aider", manifest["competitors_supported"])


class CodingLifecycleMetaTests(unittest.TestCase):
    def test_invoke_timeout_signals_cancel(self) -> None:
        import asyncio
        import threading

        from coding_agent import _invoke_chat_fn

        cancel = threading.Event()

        async def _slow() -> str:
            await asyncio.sleep(2.0)
            return "done"

        result, meta = _invoke_chat_fn(None, lambda: _slow(), timeout_s=0.05, cancel_event=cancel)
        self.assertIsNone(result)
        self.assertTrue(meta.get("cancel_signaled"))
        self.assertIn("timeout", str(meta.get("note") or ""))


class ScoreboardTests(unittest.TestCase):
    def test_scoreboard_separates_layers(self) -> None:
        from evals.functional.scoreboard import build_scoreboard

        records = [
            {"task_family": "intent", "eval_layer": "B_deterministic", "outcome": "success"},
            {"task_family": "coding", "eval_layer": "C_real_model", "outcome": "failure"},
            {"task_family": "intent", "eval_layer": "B_deterministic", "outcome": "failure", "failure_class": "false_execution"},
        ]
        board = build_scoreboard(records, git_sha="abc", benchmark_version="v", generated_at=0.0)
        payload = board.to_dict()
        self.assertIn("mechanical", payload["layers"])
        self.assertIn("agent_quality", payload["layers"])
        note = " ".join(payload["overall_notes"])
        self.assertIn("Do not collapse", note)


if __name__ == "__main__":
    unittest.main()
