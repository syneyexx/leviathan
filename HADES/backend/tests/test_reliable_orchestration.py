"""Focused tests for reliable orchestration: specialists, scheduler, model router,
retrieval, conversation state, evidence coverage, budgets, tool handoffs, run control.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.atomic_budget import BudgetExhausted, SharedBudgetPool
from reasoning.conversation_state import build_conversation_working_state
from reasoning.evidence_coverage import assess_coverage, classify_support
from reasoning.model_router import ModelRouter
from reasoning.plan_scheduler import PlanValidationError, execution_waves, ready_steps, validate_plan
from reasoning.retrieval import (
    RetrievalHit,
    build_lexical_hits_from_records,
    lexical_score,
    merge_rank,
    pack_hits_non_dumping,
    provenance_label,
    rerank_hits,
)
from reasoning.run_control import apply_redirect, can_pause_safely, crash_recovery_notes
from reasoning.specialists import route_specialist, SPECIALISTS
from reasoning.tool_workflows import ToolStepSpec, evaluate_success, resolve_inputs, validate_against_schema


class SpecialistContractTests(unittest.TestCase):
    def test_required_roles_exist(self) -> None:
        for agent_id in (
            "chat",
            "executor",
            "research_worker",
            "document_intel",
            "build",
            "critic",
            "memory_curator",
        ):
            self.assertIn(agent_id, SPECIALISTS)
            contract = SPECIALISTS[agent_id]
            self.assertTrue(contract.responsibility)
            self.assertTrue(contract.required_inputs)
            self.assertTrue(contract.expected_outputs)
            self.assertTrue(contract.acceptance_criteria)

    def test_routing_differs_by_task_kind(self) -> None:
        enabled = set(SPECIALISTS.keys())
        doc = route_specialist("Extraheer tabellen uit dit PDF-document", enabled_ids=enabled)
        research = route_specialist("Doe onderzoek naar bronnen en vergelijk literatuur", enabled_ids=enabled)
        code = route_specialist("Refactor de python repository en schrijf tests", enabled_ids=enabled)
        self.assertEqual(doc, "document_intel")
        self.assertEqual(research, "research_worker")
        self.assertEqual(code, "build")
        self.assertNotEqual(doc, research)
        self.assertNotEqual(research, code)

    def test_explicit_disabled_agent_does_not_gain_privileges(self) -> None:
        enabled = {"chat", "executor"}
        chosen = route_specialist("code refactor", requested="build", enabled_ids=enabled)
        self.assertIn(chosen, enabled)
        self.assertNotEqual(chosen, "build")


class PlanSchedulerTests(unittest.TestCase):
    def test_rejects_cycles_and_unknown_deps(self) -> None:
        with self.assertRaises(PlanValidationError):
            validate_plan(
                {
                    "steps": [
                        {"step_id": "a", "instruction": "one", "agent_id": "executor", "depends_on": ["b"]},
                        {"step_id": "b", "instruction": "two", "agent_id": "executor", "depends_on": ["a"]},
                    ]
                },
                allowed_agents={"executor"},
            )
        with self.assertRaises(PlanValidationError):
            validate_plan(
                {"steps": [{"step_id": "a", "instruction": "one", "agent_id": "executor", "depends_on": ["missing"]}]},
                allowed_agents={"executor"},
            )

    def test_parallel_wave_then_dependent(self) -> None:
        plan = validate_plan(
            {
                "goal": "demo",
                "steps": [
                    {"step_id": "a", "instruction": "independent A", "agent_id": "document_intel", "depends_on": []},
                    {"step_id": "b", "instruction": "independent B", "agent_id": "research_worker", "depends_on": []},
                    {"step_id": "c", "instruction": "merge", "agent_id": "executor", "depends_on": ["a", "b"]},
                ],
            },
            allowed_agents={"document_intel", "research_worker", "executor"},
        )
        waves = execution_waves(plan.steps)
        self.assertEqual(waves[0], ["a", "b"])
        self.assertEqual(waves[1], ["c"])
        self.assertEqual(ready_steps(plan.steps), ["a", "b"])
        self.assertEqual(ready_steps(plan.steps, completed_ids={"a", "b"}), ["c"])


class ModelRouterTests(unittest.TestCase):
    def test_explicit_choice_leads_and_fallback_on_outage(self) -> None:
        router = ModelRouter()
        router.remember_provider_models([{"id": "local-a"}, {"id": "local-b"}])
        selection = router.select(default_model="local-a", explicit_model="local-b")
        self.assertEqual(selection.model_id, "local-b")
        self.assertEqual(selection.reason, "explicit_choice")

        router.mark_available("local-b", False)
        fallback = router.select(
            default_model="local-a",
            explicit_model="local-b",
            fallback_order=["local-a"],
        )
        self.assertEqual(fallback.model_id, "local-a")
        self.assertEqual(fallback.fallback_from, "local-b")

    def test_cloud_fallback_blocked_by_default(self) -> None:
        router = ModelRouter()
        router.remember_provider_models([{"id": "local-a"}, {"id": "openai/gpt"}])
        selection = router.select(
            default_model="local-a",
            fallback_order=["openai/gpt"],
            allow_cloud=False,
        )
        self.assertEqual(selection.model_id, "local-a")
        blocked = router.select(
            default_model="openai/gpt",
            fallback_order=["openai/gpt"],
            allow_cloud=False,
            known_local_ids={"openai/gpt"},
        )
        self.assertIn(blocked.reason, {"no_eligible_model", "explicit_choice_unavailable", "default"})


class AtomicBudgetTests(unittest.TestCase):
    def test_concurrent_workers_cannot_overspend(self) -> None:
        pool = SharedBudgetPool(max_model_calls=5)
        successes = []
        errors = []

        def worker() -> None:
            try:
                pool.reserve("model", 1)
                successes.append(1)
            except BudgetExhausted:
                errors.append(1)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(successes), 5)
        self.assertEqual(sum(errors), 15)
        self.assertEqual(pool.snapshot()["model_calls"], 5)


class RetrievalTests(unittest.TestCase):
    def test_paraphrase_lexical_and_hybrid_ranking(self) -> None:
        records = [
            {"id": "1", "title": "Orchestratie", "content": "HADES gebruikt specialistische agents voor taakverdeling en werk over specialisten."},
            {"id": "2", "title": "Onrelated", "content": "Koffiebonen en theeblaadjes in de keuken."},
        ]
        query = "hoe verdeelt het systeem werk over specialisten"
        lexical = build_lexical_hits_from_records(query, records, kind="knowledge")
        self.assertTrue(lexical)
        self.assertEqual(lexical[0].hit_id, "knowledge-1")
        score_rel, _ = lexical_score(query, records[0]["content"])
        score_unrel, _ = lexical_score(query, records[1]["content"])
        self.assertGreater(score_rel, score_unrel)

        semantic = [
            RetrievalHit(
                hit_id="knowledge-1",
                kind="knowledge",
                content=records[0]["content"],
                provenance="knowledge:1",
                score=0.91,
                reasons=["semantische_overeenkomst:0.910"],
            )
        ]
        merged = merge_rank(lexical, semantic, limit=5)
        self.assertEqual(merged.method, "hybrid")
        self.assertTrue(merged.hits)
        self.assertIn("semantische_overeenkomst", " ".join(merged.hits[0].reasons))

    def test_lexical_fallback_without_embeddings(self) -> None:
        lexical = [
            RetrievalHit("a", "memory", "lokale knowledge passages", "memory:1", 1.2, ["woordmatch:knowledge"])
        ]
        merged = merge_rank(lexical, [], limit=3)
        self.assertEqual(merged.method, "lexical")
        self.assertIn("semantic_unavailable_lexical_fallback", merged.notes)

    def test_rerank_prefers_concise_query_aligned_over_dump(self) -> None:
        query = "HADES lokale agents"
        dump = RetrievalHit(
            hit_id="knowledge-dump",
            kind="knowledge",
            content=("koffie thee " * 200) + " HADES " + ("irrelevant " * 200),
            provenance="manual://dump",
            score=1.0,
            reasons=["woordmatch:hades"],
            metadata={"title": "Dump"},
        )
        precise = RetrievalHit(
            hit_id="memory-precise",
            kind="memory",
            content="HADES gebruikt lokale agents voor taken.",
            provenance="memory:1",
            score=0.8,
            reasons=["woordmatch:hades", "woordmatch:lokale", "woordmatch:agents"],
            metadata={"title": "Agents", "scope": "project"},
        )
        ranked = rerank_hits(query, [dump, precise], limit=2)
        self.assertEqual(ranked[0].hit_id, "memory-precise")
        self.assertTrue(any("rerank:" in reason for reason in ranked[0].reasons))
        self.assertIn("memory ·", provenance_label(ranked[0]))

    def test_non_dumping_pack_budgets_and_provenance_labels(self) -> None:
        hits = [
            RetrievalHit(
                hit_id=f"knowledge-{index}",
                kind="knowledge",
                content=("passage " * 400) + f" token-{index}",
                provenance=f"uri://doc/{index}",
                score=1.0 - (index * 0.01),
                metadata={"title": f"Doc {index}"},
            )
            for index in range(12)
        ]
        packed, meta = pack_hits_non_dumping(hits, max_hits=4, max_chars_total=2_000, max_chars_per_hit=500)
        self.assertLessEqual(len(packed), 4)
        self.assertLessEqual(meta["used_chars"], 2_000 + 200)
        self.assertTrue(meta["provenance_labels"])
        self.assertTrue(any("knowledge ·" in label["label"] for label in meta["provenance_labels"]))
        self.assertTrue(meta["truncated"] or meta["dropped_hits"] > 0)


class ConversationStateTests(unittest.TestCase):
    def test_correction_keeps_latest_agreement_not_assistant_decision(self) -> None:
        state = build_conversation_working_state(
            previous=None,
            user_text="Afspraak: gebruik projectcodenaam Orion.",
            assistant_text="Ik stel voor om later ook Lyra te overwegen.",
            request_spec={"goal": "projectnaam", "constraints": []},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        self.assertTrue(any("Orion" in str(item) for item in state["constraints"] + [d.get("summary") for d in state["decisions"]]))
        self.assertTrue(state["proposals"])  # assistant proposal not a decision
        self.assertFalse(any("Lyra" in str(d.get("summary")) for d in state["decisions"]))

        corrected = build_conversation_working_state(
            previous=state,
            user_text="Correctie: gebruik in plaats van Orion de naam Vega.",
            assistant_text="Begrepen, Vega staat genoteerd.",
            request_spec={"goal": "projectnaam", "constraints": []},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        blob = " ".join(corrected["constraints"]) + " ".join(d.get("summary", "") for d in corrected["decisions"])
        self.assertIn("Vega", blob)
        # Topic continuity: goal retained
        self.assertEqual(corrected["goal"], "projectnaam")


class EvidenceCoverageTests(unittest.TestCase):
    def test_irrelevant_existing_ref_is_not_sufficient(self) -> None:
        report = assess_coverage(
            [{"text": "De reactor is veilig volgens protocol X.", "evidence_refs": ["src1"]}],
            known_refs={"src1"},
            evidence_texts={"src1": "Het koffieapparaat staat in de keuken naast de koelkast."},
        )
        self.assertFalse(report.sufficient)
        self.assertEqual(report.claims[0].support_level, "insufficient")

    def test_quote_verified_passage(self) -> None:
        quote = "De reactor is veilig volgens protocol X."
        record = classify_support(
            claim_text=quote,
            evidence_texts={"src1": "Inleiding. De reactor is veilig volgens protocol X. Slot."},
            evidence_refs=["src1"],
            known_refs={"src1"},
        )
        self.assertEqual(record.support_level, "source_passage")
        self.assertTrue(record.quote_verified)


class ToolWorkflowTests(unittest.TestCase):
    def test_validated_handoff_and_blocked_step(self) -> None:
        spec = ToolStepSpec(
            step_id="save",
            capability="store",
            input_from=["extract"],
            input_schema={"type": "object", "required": ["artifact_id"], "properties": {"artifact_id": {"type": "string"}}},
            expected_output_schema={"type": "object", "required": ["saved"], "properties": {"saved": {"type": "boolean"}}},
            success_check="status==completed",
            artifact_ref_key="artifact_id",
        )
        missing, err = resolve_inputs(spec, {})
        self.assertIsNone(missing)
        self.assertEqual(err.status, "invalid_input")

        ok_input, err2 = resolve_inputs(spec, {"extract": {"artifact_id": "doc_1"}})
        self.assertIsNone(err2)
        self.assertEqual(ok_input["artifact_id"], "doc_1")

        blocked = evaluate_success(spec, {"status": "blocked", "error": "network_policy=block"})
        self.assertEqual(blocked.status, "blocked")
        self.assertIn("network_policy", blocked.blocked_reason or "")

        good = evaluate_success(spec, {"status": "completed", "output": {"saved": True}, "artifact_id": "doc_1"})
        self.assertEqual(good.status, "ok")
        self.assertEqual(good.artifact_ref, "doc_1")

    def test_schema_rejects_free_text_path_as_object(self) -> None:
        errors = validate_against_schema("C:\\temp\\file.txt", {"type": "object", "required": ["path"]})
        self.assertTrue(errors)


class RunControlTests(unittest.TestCase):
    def test_pause_only_at_safe_point(self) -> None:
        self.assertTrue(can_pause_safely("step_completed"))
        self.assertFalse(can_pause_safely("step_completed", inflight_side_effects=True))
        self.assertFalse(can_pause_safely("executing_tool"))

    def test_redirect_reuses_valid_completed_work(self) -> None:
        effect = apply_redirect(
            current_plan_version=1,
            command_plan_version=1,
            steps=[
                {"step_id": "a", "status": "completed", "depends_on": []},
                {"step_id": "b", "status": "pending", "depends_on": ["a"]},
            ],
            completed_ids={"a"},
            new_instruction="Focus op samenvatting i.p.v. volledige extractie",
        )
        self.assertTrue(effect.accepted)
        self.assertIn("a", effect.reused_step_ids)
        self.assertIn("b", effect.invalidated_step_ids)
        self.assertEqual(effect.plan_version, 2)

    def test_crash_recovery_does_not_blindly_replay(self) -> None:
        notes = crash_recovery_notes(
            steps=[{"id": "1", "status": "running"}, {"id": "2", "status": "completed"}],
            uncertain_external_actions=["plugin:send_email"],
        )
        self.assertEqual(notes["requeued_uncertain_steps"], ["1"])
        self.assertEqual(notes["completed_reusable"], ["2"])
        self.assertIn("plugin:send_email", notes["external_actions_unconfirmed"])


class ModelConcurrencyTests(unittest.TestCase):
    def test_model_router_capacity_slot(self) -> None:
        router = ModelRouter()

        async def _run() -> None:
            await router.acquire("m1", endpoint="http://local", limit=1)
            waiter = asyncio.create_task(router.acquire("m1", endpoint="http://local", limit=1))
            await asyncio.sleep(0.05)
            self.assertFalse(waiter.done())
            await router.release("m1", endpoint="http://local")
            await asyncio.wait_for(waiter, timeout=1)
            await router.release("m1", endpoint="http://local")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
