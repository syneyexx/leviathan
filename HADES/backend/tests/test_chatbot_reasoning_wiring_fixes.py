"""Behavioral regressions for chatbot reasoning wiring fixes (2026-09-10).

ADDED_NOT_EXECUTED — user requested no CLI test runs due to GitHub billing.
These tests use fakes/fixtures only (no live LM Studio / network / plugins).
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class EvidencePackageCoverageTests(unittest.TestCase):
    def test_retrieved_passage_available_to_coverage_not_global_tool_refs(self) -> None:
        from reasoning.contracts import ContextItem
        from reasoning.evidence_coverage import assess_coverage
        from reasoning.evidence_package import bind_claims_to_evidence, build_evidence_package

        items = [
            ContextItem(
                item_id="k1",
                kind="knowledge",
                content="De reactor koeling gebruikt helium als medium volgens paragraaf 4.",
                provenance="knowledge:doc-helium",
                priority=10,
            )
        ]
        package = build_evidence_package(
            context_items=items,
            tool_log=[
                {
                    "call_id": "c-weather",
                    "status": "completed",
                    "plugin_id": "weather",
                    "tool_name": "get",
                    "output": "Het is 12C in Amsterdam.",
                }
            ],
        )
        claims = bind_claims_to_evidence(
            ["De reactor koeling gebruikt helium als medium volgens paragraaf 4."],
            package,
            critic_refs=["tool:c-weather"],  # unrelated successful tool must not auto-prove
        )
        self.assertEqual(claims[0]["evidence_refs"], ["knowledge:doc-helium"])
        report = assess_coverage(
            [{**claims[0], "claim_id": "c1"}],
            known_refs=package.known_refs(),
            evidence_texts=package.evidence_texts(),
            evidence_kinds=package.evidence_kinds(),
            require_factual=True,
        )
        self.assertEqual(report.claims[0].support_level, "source_passage")
        self.assertTrue(report.factual_verified)

    def test_unrelated_tool_success_does_not_validate_other_claim(self) -> None:
        from reasoning.contracts import ContextItem
        from reasoning.evidence_coverage import assess_coverage
        from reasoning.evidence_package import bind_claims_to_evidence, build_evidence_package

        package = build_evidence_package(
            context_items=[
                ContextItem(
                    item_id="k2",
                    kind="knowledge",
                    content="Bijlage over contractduur van 12 maanden.",
                    provenance="knowledge:contract",
                )
            ],
            tool_log=[
                {
                    "call_id": "c1",
                    "status": "completed",
                    "output": "DNS lookup ok for example.com",
                }
            ],
        )
        claims = bind_claims_to_evidence(
            ["De omzet steeg vorig kwartaal met 40 procent."],
            package,
            critic_refs=["tool:c1", "knowledge:contract"],
        )
        self.assertEqual(claims[0]["evidence_refs"], [])
        report = assess_coverage(
            claims,
            known_refs=package.known_refs(),
            evidence_texts=package.evidence_texts(),
            evidence_kinds=package.evidence_kinds(),
            require_factual=True,
        )
        self.assertFalse(report.factual_verified)
        self.assertEqual(report.claims[0].support_level, "insufficient")


class PayloadAndStreamWiringTests(unittest.TestCase):
    def test_stream_path_passes_prepared_payload_without_second_chat_payload(self) -> None:
        import main as hades_main

        chat_src = inspect.getsource(hades_main.run_model_with_optional_tool)
        self.assertIn("payload=payload", chat_src)
        self.assertNotIn("messages=payload.get(\"messages\")", chat_src)
        stream_src = inspect.getsource(hades_main._chat_with_optional_stream)
        self.assertIn("if payload is not None", stream_src)
        self.assertIn("chat_stream_events", stream_src)
        self.assertNotIn('"usage": {}', stream_src)

    def test_stream_fallback_clears_provisional_parts(self) -> None:
        import main as hades_main

        stream_src = inspect.getsource(hades_main._chat_with_optional_stream)
        self.assertIn("provisional_parts.clear()", stream_src)


class ProviderBudgetTests(unittest.TestCase):
    def test_tokens_to_reserve_chars_uses_explicit_conversion(self) -> None:
        from reasoning.provider_budget import tokens_to_reserve_chars

        # 100 tokens * 4 chars/token = 400, but the floor is 512.
        self.assertEqual(tokens_to_reserve_chars(100), 512)
        self.assertEqual(tokens_to_reserve_chars(10), 512)  # floor
        self.assertEqual(tokens_to_reserve_chars(200), 800)  # above floor, below cap
        self.assertEqual(tokens_to_reserve_chars(10_000), 8_000)  # cap

    def test_overflow_refuses_oversized_mandatory_payload(self) -> None:
        from reasoning.provider_budget import enforce_provider_payload_budget

        huge = "x" * 20_000
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": "policy"},
                    {"role": "user", "content": huge},
                ]
            },
            max_chars=2_000,
            reserve_output_chars=500,
            capacity_source="conservative_estimate",
            allow_truncate=True,
        )
        self.assertTrue(decision.overflow)
        self.assertFalse(decision.ok)


class WebPolicyLocalFirstTests(unittest.TestCase):
    def test_no_web_constraint_disables_allow_web(self) -> None:
        from reasoning.understanding import build_request_spec, build_route_decision

        spec = build_request_spec("Zoek actueel nieuws maar alleen lokaal, niet online zoeken")
        self.assertIn("Geen web / alleen lokaal", spec.constraints)
        self.assertFalse(spec.needs_research)
        route = build_route_decision(
            spec,
            requested_profile="standard",
            network_policy="allow",
            plugin_tools_enabled=True,
        )
        self.assertFalse(route.allow_web)

    def test_maybe_refresh_respects_allow_web_false(self) -> None:
        import main as hades_main

        async def _run() -> dict:
            return await hades_main.maybe_refresh_web_knowledge(
                "laatste nieuws vandaag",
                force=True,
                allow_web=False,
                skip_reason="request_disallow_web",
            )

        with mock.patch.object(
            hades_main,
            "runtime_values",
            return_value={"auto_web_research": True, "network_policy": "allow"},
        ):
            result = asyncio.run(_run())
        self.assertFalse(result.get("attempted"))
        self.assertEqual(result.get("skip_reason"), "request_disallow_web")


class FollowUpResolvedRequestTests(unittest.TestCase):
    def test_follow_up_enriches_resolved_query_from_failures(self) -> None:
        from reasoning.understanding import build_request_spec

        spec = build_request_spec(
            "Waarom faalt dit?",
            conversation_state={
                "last_assistant": "Deploy timeout op stap 3",
                "recent_failures": ["timeout contacting api"],
                "last_user": "Deploy naar staging",
            },
        )
        self.assertTrue(spec.interpretation.get("follow_up"))
        self.assertIn("timeout", spec.effective_query().lower())
        self.assertIn("timeout", spec.effective_goal().lower())
        self.assertEqual(spec.raw_text, "Waarom faalt dit?")

    def test_status_follow_up_does_not_grant_mutation(self) -> None:
        from reasoning.understanding import build_request_spec

        spec = build_request_spec(
            "wat is de status?",
            conversation_state={
                "last_assistant": "Bezig met migratie",
                "goal": "Migreer database",
            },
        )
        self.assertIn("Status", spec.effective_goal())
        self.assertEqual(spec.interpretation.get("authorization_unchanged"), True)


class AttachmentRecordIdentityTests(unittest.TestCase):
    def test_attachment_provenance_uses_artifact_id_not_filtered_index(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("attachment_records", source)
        self.assertIn('provenance=f"attachment:{artifact_id}"', source)
        self.assertNotIn(
            "values.attachment_ids[index]",
            source,
        )


class BranchWorkingStateTests(unittest.TestCase):
    def test_activate_branch_restores_branch_working_state(self) -> None:
        from database import Database

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "core.db")
            db.initialize()
            conv = db.create_conversation(title="branches")
            user = db.add_message(conv["id"], "user", "start")
            db.save_conversation_working_state(
                conv["id"],
                {"goal": "branch-A-constraint", "last_assistant": "A"},
                branch_id=None,
            )
            # Ensure an active branch exists for snapshot semantics.
            # create_branch forks; first create a message then branch.
            branch_b = db.create_branch(conv["id"], user["id"], title="B")
            db.save_conversation_working_state(
                conv["id"],
                {"goal": "branch-B-constraint", "last_assistant": "B"},
                branch_id=branch_b["id"],
            )
            # Create sibling branch A from same fork by manually inserting via activate cycle:
            # Snapshot B, create new branch (clears conv state), set A state, switch back.
            branch_a = db.create_branch(conv["id"], user["id"], title="A")
            db.save_conversation_working_state(
                conv["id"],
                {"goal": "branch-A-constraint", "last_assistant": "A"},
                branch_id=branch_a["id"],
            )
            activated_b = db.activate_branch(conv["id"], branch_b["id"])
            conv_b = db.get_conversation(conv["id"])
            self.assertEqual((conv_b.get("working_state") or {}).get("goal"), "branch-B-constraint")
            activated_a = db.activate_branch(conv["id"], branch_a["id"])
            conv_a = db.get_conversation(conv["id"])
            self.assertEqual((conv_a.get("working_state") or {}).get("goal"), "branch-A-constraint")
            self.assertTrue(activated_a.get("is_active"))
            self.assertTrue(activated_b.get("id"))


class VerificationBudgetAndRepairWiringTests(unittest.TestCase):
    def test_verification_called_only_after_budget_check(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        # Flag must not be set before the budget gate.
        block = source.split("if should_run_verification", 1)[1].split(
            "from execution_truth import", 1
        )[0]
        self.assertIn("verification:skipped_budget", block)
        skipped = block.split("if not exec_budget.can_model_call():", 1)[1].split("else:", 1)[0]
        self.assertIn("verification_called = False", skipped)
        self.assertNotIn("verification_called = True", skipped)

    def test_tool_engine_respects_verification_reserve(self) -> None:
        from reasoning.tool_engine import run_tool_engine

        source = inspect.getsource(run_tool_engine)
        self.assertIn("reserve_verification=reserve", source)
        self.assertIn("verificatiereserve", source)

    def test_repair_plan_applied_when_budget_allows(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("build_repair_plan", source)
        self.assertIn("repair_applied", source)
        self.assertIn("can_repair()", source)


class SendMessageEvidenceWiringTests(unittest.TestCase):
    def test_send_message_builds_evidence_package_for_critic(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("build_evidence_package", source)
        self.assertIn("bind_claims_to_evidence", source)
        self.assertIn("evidence_texts=evidence_package.evidence_texts()", source)


if __name__ == "__main__":
    unittest.main()
