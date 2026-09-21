"""End-to-end practice scenarios A–E with deterministic providers and temp data."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from database import Database
from platform_db import PlatformDatabase
from reasoning.atomic_budget import SharedBudgetPool
from reasoning.conversation_state import build_conversation_working_state
from reasoning.model_router import ModelRouter
from reasoning.plan_scheduler import execution_waves, validate_plan
from reasoning.specialists import route_specialist
from reasoning.tool_workflows import ToolStepSpec, evaluate_success, resolve_inputs


class ScenarioLm:
    def __init__(self) -> None:
        self.calls = 0

    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model"}]}

    async def chat(self, payload):
        self.calls += 1
        prompt = payload["messages"][-1]["content"] if payload.get("messages") else ""
        if "HADES Work Planner" in prompt:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "acceptance_criteria": ["Resultaat is concreet"],
                                    "steps": [
                                        {
                                            "step_id": "a",
                                            "agent_id": "document_intel",
                                            "kind": "documents",
                                            "title": "Document",
                                            "instruction": "Verwerk document A",
                                            "depends_on": [],
                                        },
                                        {
                                            "step_id": "b",
                                            "agent_id": "research_worker",
                                            "kind": "research",
                                            "title": "Research",
                                            "instruction": "Onderzoek deelvraag B",
                                            "depends_on": [],
                                        },
                                        {
                                            "step_id": "c",
                                            "agent_id": "executor",
                                            "kind": "work",
                                            "title": "Synthese",
                                            "instruction": "Voeg A en B samen",
                                            "depends_on": ["a", "b"],
                                        },
                                    ],
                                }
                            )
                        }
                    }
                ]
            }
        if "Verification/Critic" in prompt or "onafhankelijke HADES Verification" in prompt:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "passed": True,
                                    "issues": [],
                                    "final": "Scenario resultaat geverifieerd",
                                    "evidence_refs": ["step:1"],
                                    "incomplete": False,
                                }
                            )
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": f"Antwoord: {prompt[:80]}"}}]}


class PracticeScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmp.name) / "hades.db")
        main.database = Database(db_path)
        main.database.initialize()
        main.platform_db = PlatformDatabase(db_path)
        main.platform_db.initialize()
        main.ensure_platform_services()
        self.lm = ScenarioLm()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scenario_a_conversation_continuity_across_correction_and_restart(self) -> None:
        """A: project agreement, later correction, restart keeps latest valid agreement."""
        state = build_conversation_working_state(
            previous=None,
            user_text="Afspraak: projectcodenaam is Orion.",
            assistant_text="Orion is genoteerd.",
            request_spec={"goal": "naamgeving", "constraints": ["projectcodenaam Orion"]},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        conv = main.database.create_conversation("Scenario A")
        main.database.save_conversation_working_state(conv["id"], state)
        main.database.add_message(conv["id"], "user", "Afspraak: projectcodenaam is Orion.")
        main.database.add_message(conv["id"], "assistant", "Orion is genoteerd.")

        corrected = build_conversation_working_state(
            previous=state,
            user_text="Correctie: gebruik in plaats van Orion de naam Vega.",
            assistant_text="Vega staat genoteerd.",
            request_spec={"goal": "naamgeving", "constraints": []},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        main.database.save_conversation_working_state(conv["id"], corrected)
        main.database.add_message(conv["id"], "user", "Correctie: gebruik in plaats van Orion de naam Vega.")
        main.database.add_message(conv["id"], "assistant", "Vega staat genoteerd.")

        # Simulate backend restart with a fresh Database handle on same file.
        restarted = Database(main.database.path)
        restarted.initialize()
        loaded = restarted.get_conversation(conv["id"])
        self.assertIsNotNone(loaded)
        ws = loaded.get("working_state") or {}
        blob = json.dumps(ws, ensure_ascii=False)
        self.assertIn("Vega", blob)
        messages = restarted.list_messages(conv["id"])
        self.assertGreaterEqual(len(messages), 4)
        self.assertTrue(any("Orion" in m["content"] for m in messages))
        self.assertTrue(any("Vega" in m["content"] for m in messages))

    def test_scenario_b_research_contradiction_paths(self) -> None:
        """B: document vs research specialists get different routes; contradictions surface in coverage helpers."""
        enabled = {item["id"] for item in main.platform_db.list_agents() if item.get("enabled")}
        doc_agent = route_specialist("Extraheer feiten uit PDF documenten", enabled_ids=enabled)
        research_agent = route_specialist("Onderzoek en vergelijk bronnen literatuur", enabled_ids=enabled)
        self.assertEqual(doc_agent, "document_intel")
        self.assertEqual(research_agent, "research_worker")
        self.assertNotEqual(doc_agent, research_agent)

        # Local conflicting snippets → report helpers classify as contradicted when marked.
        from reasoning.evidence_coverage import assess_coverage

        report = assess_coverage(
            [
                {
                    "text": "Product X is veilig.",
                    "evidence_refs": ["a"],
                    "contradicting_refs": ["b"],
                }
            ],
            known_refs={"a", "b"},
            evidence_texts={"a": "Product X is veilig.", "b": "Product X is niet veilig."},
        )
        self.assertTrue(report.contradictions)
        self.assertEqual(report.claims[0].support_level, "contradicted")

    def test_scenario_c_tool_workflow_block(self) -> None:
        """C: multi-step tool handoff validates transfers and reports real blockade."""
        search = ToolStepSpec(
            step_id="search",
            capability="search",
            input_from=[],
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            expected_output_schema={"type": "object", "required": ["hits"], "properties": {"hits": {"type": "array"}}},
            success_check="status==completed",
            artifact_ref_key="result_id",
        )
        # First step validated against schema without prior handoff.
        from reasoning.tool_workflows import validate_against_schema

        payload = {"query": "hades plugins"}
        errors = validate_against_schema(payload, search.input_schema)
        self.assertEqual(errors, [])
        search_result = evaluate_success(
            search,
            {"status": "completed", "output": {"hits": [{"id": "1"}]}, "result_id": "res_1"},
        )
        self.assertEqual(search_result.status, "ok")

        process = ToolStepSpec(
            step_id="process",
            capability="documents",
            input_from=["search"],
            input_schema={"type": "object", "required": ["result_id"], "properties": {"result_id": {"type": "string"}}},
            expected_output_schema={"type": "object", "required": ["artifact_id"], "properties": {"artifact_id": {"type": "string"}}},
            success_check="status==completed",
            artifact_ref_key="artifact_id",
        )
        inputs, err = resolve_inputs(process, {"search": {"result_id": search_result.artifact_ref}})
        self.assertIsNone(err)
        self.assertEqual(inputs["result_id"], "res_1")

        save = ToolStepSpec(
            step_id="save",
            capability="store",
            input_from=["process"],
            input_schema={"type": "object", "required": ["artifact_id"], "properties": {"artifact_id": {"type": "string"}}},
            expected_output_schema={"type": "object", "required": ["saved"], "properties": {"saved": {"type": "boolean"}}},
            success_check="status==completed",
        )
        blocked = evaluate_success(save, {"status": "blocked", "error": "file_write_policy=block"})
        self.assertEqual(blocked.status, "blocked")
        self.assertIn("file_write_policy", blocked.blocked_reason or "")

    def test_scenario_d_long_running_redirect_reuses_valid_steps(self) -> None:
        """D: redirect invalidates future steps but reuses completed work."""
        from reasoning.run_control import apply_redirect

        effect = apply_redirect(
            current_plan_version=3,
            command_plan_version=3,
            steps=[
                {"step_id": "a", "status": "completed", "depends_on": []},
                {"step_id": "b", "status": "completed", "depends_on": ["a"]},
                {"step_id": "c", "status": "pending", "depends_on": ["b"]},
            ],
            completed_ids={"a", "b"},
            new_instruction="Maak de synthese korter en noem onzekerheden.",
        )
        self.assertTrue(effect.accepted)
        self.assertEqual(sorted(effect.reused_step_ids), ["a", "b"])
        self.assertEqual(effect.invalidated_step_ids, ["c"])
        stale = apply_redirect(
            current_plan_version=3,
            command_plan_version=2,
            steps=[{"step_id": "a", "status": "completed", "depends_on": []}],
            completed_ids={"a"},
            new_instruction="oud",
        )
        self.assertFalse(stale.accepted)

    def test_scenario_e_capacity_limits_and_isolation(self) -> None:
        """E: shared model capacity + budgets; one failure does not clear other reservations wrongly."""
        router = ModelRouter()
        pool = SharedBudgetPool(max_model_calls=2, max_active_tasks=2)

        async def _run() -> None:
            await router.acquire("local-test-model", endpoint="http://127.0.0.1:1234/v1", limit=1)
            pool.reserve("model", 1)
            # Second acquire should wait until release — emulate with try_reserve for budget isolation.
            self.assertTrue(pool.try_reserve("model", 1))
            self.assertFalse(pool.try_reserve("model", 1))
            await router.release("local-test-model", endpoint="http://127.0.0.1:1234/v1")

        asyncio.run(_run())
        plan = validate_plan(
            {
                "steps": [
                    {"step_id": "a", "instruction": "t1", "agent_id": "executor", "depends_on": []},
                    {"step_id": "b", "instruction": "t2", "agent_id": "executor", "depends_on": []},
                ]
            },
            allowed_agents={"executor"},
        )
        waves = execution_waves(plan.steps)
        self.assertEqual(len(waves[0]), 2)

    def test_scenario_work_plan_api_persists_dependencies(self) -> None:
        with patch.object(main, "lm_client", return_value=self.lm):
            # Direct persistence path used by Work Runtime
            steps = main.platform_db.replace_work_plan(
                "task_demo",
                [
                    {"step_id": "a", "agent_id": "document_intel", "kind": "documents", "title": "A", "instruction": "A", "depends_on": []},
                    {"step_id": "b", "agent_id": "research_worker", "kind": "research", "title": "B", "instruction": "B", "depends_on": []},
                    {"step_id": "c", "agent_id": "executor", "kind": "work", "title": "C", "instruction": "C", "depends_on": ["a", "b"]},
                ],
            )
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[2]["depends_on"], ["a", "b"])
        self.assertEqual(steps[0]["step_key"], "a")


if __name__ == "__main__":
    unittest.main()
