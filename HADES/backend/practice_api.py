"""Deterministic practice scenarios A–E exposed as a product API.

Mirrors the verified logic in tests.test_practice_scenarios for UI inspection.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from reasoning.atomic_budget import SharedBudgetPool
from reasoning.conversation_state import build_conversation_working_state
from reasoning.evidence_coverage import assess_coverage
from reasoning.model_router import ModelRouter
from reasoning.plan_scheduler import execution_waves, validate_plan
from reasoning.run_control import apply_redirect
from reasoning.specialists import route_specialist
from reasoning.tool_workflows import ToolStepSpec, evaluate_success, resolve_inputs, validate_against_schema

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "A",
        "title": "Conversation continuity",
        "description": "Working state overleeft correctie (Orion → Vega).",
        "kind": "memory",
    },
    {
        "id": "B",
        "title": "Specialist routing & contradictions",
        "description": "Document vs research routing + evidence contradictions.",
        "kind": "routing",
    },
    {
        "id": "C",
        "title": "Tool workflow blockade",
        "description": "Handoffs valideren; policy-block blijft blocked.",
        "kind": "tools",
    },
    {
        "id": "D",
        "title": "Redirect reuses completed steps",
        "description": "Mid-run redirect invalideert toekomst, hergebruikt klaar werk.",
        "kind": "control",
    },
    {
        "id": "E",
        "title": "Budgets & parallel waves",
        "description": "Atomic budgets + parallel execution waves.",
        "kind": "budget",
    },
]


def list_scenarios() -> list[dict[str, Any]]:
    return list(SCENARIOS)


def run_scenario(scenario_id: str, *, enabled_agents: set[str] | None = None) -> dict[str, Any]:
    sid = str(scenario_id).strip().upper()
    enabled = enabled_agents or {"document_intel", "research_worker", "executor", "critic"}

    if sid == "A":
        state = build_conversation_working_state(
            previous=None,
            user_text="Afspraak: projectcodenaam is Orion.",
            assistant_text="Orion is genoteerd.",
            request_spec={"goal": "naamgeving", "constraints": ["projectcodenaam Orion"]},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        corrected = build_conversation_working_state(
            previous=state,
            user_text="Correctie: gebruik in plaats van Orion de naam Vega.",
            assistant_text="Vega staat genoteerd.",
            request_spec={"goal": "naamgeving", "constraints": []},
            route={"target": "direct_chat"},
            executed={"status": "completed"},
        )
        blob = json.dumps(corrected, ensure_ascii=False)
        passed = "Vega" in blob and corrected != state
        return {
            "scenario_id": "A",
            "passed": passed,
            "trace": {"has_vega": "Vega" in blob, "state_changed": corrected != state, "keys": sorted(corrected.keys())},
            "notes": [] if passed else ["Working state behield de correctie niet."],
        }

    if sid == "B":
        doc_agent = route_specialist("Extraheer feiten uit PDF documenten", enabled_ids=enabled)
        research_agent = route_specialist("Onderzoek en vergelijk bronnen literatuur", enabled_ids=enabled)
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
        passed = (
            doc_agent == "document_intel"
            and research_agent == "research_worker"
            and bool(report.contradictions)
            and report.claims[0].support_level == "contradicted"
        )
        return {
            "scenario_id": "B",
            "passed": passed,
            "trace": {
                "document_route": doc_agent,
                "research_route": research_agent,
                "contradictions": len(report.contradictions),
                "support_level": report.claims[0].support_level if report.claims else None,
            },
            "notes": [] if passed else ["Routing of contradiction detectie week af."],
        }

    if sid == "C":
        search = ToolStepSpec(
            step_id="search",
            capability="search",
            input_from=[],
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            expected_output_schema={"type": "object", "required": ["hits"], "properties": {"hits": {"type": "array"}}},
            success_check="status==completed",
            artifact_ref_key="result_id",
        )
        schema_errors = validate_against_schema({"query": "hades plugins"}, search.input_schema)
        search_result = evaluate_success(
            search,
            {"status": "completed", "output": {"hits": [{"id": "1"}]}, "result_id": "res_1"},
        )
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
        save = ToolStepSpec(
            step_id="save",
            capability="store",
            input_from=["process"],
            input_schema={"type": "object", "required": ["artifact_id"], "properties": {"artifact_id": {"type": "string"}}},
            expected_output_schema={"type": "object", "required": ["saved"], "properties": {"saved": {"type": "boolean"}}},
            success_check="status==completed",
        )
        blocked = evaluate_success(save, {"status": "blocked", "error": "file_write_policy=block"})
        passed = (
            schema_errors == []
            and search_result.status == "ok"
            and err is None
            and inputs is not None
            and inputs.get("result_id") == "res_1"
            and blocked.status == "blocked"
        )
        return {
            "scenario_id": "C",
            "passed": passed,
            "trace": {
                "schema_errors": schema_errors,
                "search_status": search_result.status,
                "handoff_ok": err is None,
                "blocked_status": blocked.status,
                "blocked_reason": blocked.blocked_reason,
            },
            "notes": [] if passed else ["Tool workflow gate week af."],
        }

    if sid == "D":
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
        stale = apply_redirect(
            current_plan_version=3,
            command_plan_version=2,
            steps=[{"step_id": "a", "status": "completed", "depends_on": []}],
            completed_ids={"a"},
            new_instruction="oud",
        )
        passed = (
            effect.accepted
            and sorted(effect.reused_step_ids) == ["a", "b"]
            and effect.invalidated_step_ids == ["c"]
            and not stale.accepted
        )
        return {
            "scenario_id": "D",
            "passed": passed,
            "trace": {
                "accepted": effect.accepted,
                "reused": list(effect.reused_step_ids),
                "invalidated": list(effect.invalidated_step_ids),
                "stale_rejected": not stale.accepted,
            },
            "notes": [] if passed else ["Redirect-semantiek week af."],
        }

    if sid == "E":
        pool = SharedBudgetPool(max_model_calls=2, max_active_tasks=2)
        first = pool.try_reserve("model", 1)
        second = pool.try_reserve("model", 1)
        third = pool.try_reserve("model", 1)
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
        passed = first and second and not third and len(waves) >= 1 and len(waves[0]) == 2
        return {
            "scenario_id": "E",
            "passed": passed,
            "trace": {
                "budget_claims": [first, second, third],
                "waves": waves,
                "budget": pool.snapshot(),
            },
            "notes": [] if passed else ["Budget of waves week af."],
        }

    raise KeyError(f"Onbekend scenario: {scenario_id}")


def run_all(*, enabled_agents: set[str] | None = None) -> dict[str, Any]:
    results = [run_scenario(item["id"], enabled_agents=enabled_agents) for item in SCENARIOS]
    return {
        "passed": all(item["passed"] for item in results),
        "results": results,
        "summary": {
            "total": len(results),
            "ok": sum(1 for item in results if item["passed"]),
            "failed": sum(1 for item in results if not item["passed"]),
        },
    }
