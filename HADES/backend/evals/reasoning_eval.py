from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reasoning import (
    assemble_context_messages,
    build_request_spec,
    build_route_decision,
    discover_tools,
    parse_verification_result,
    resolve_reasoning_profile,
    verification_allows_success,
)


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    details: dict[str, Any]
    duration_ms: float


def _run(scenario_id: str, title: str, fn) -> ScenarioResult:
    started = time.perf_counter()
    details = fn()
    return ScenarioResult(
        scenario_id,
        title,
        bool(details.get("passed")),
        details,
        round((time.perf_counter() - started) * 1000, 2),
    )


def scenario_fast_path() -> dict[str, Any]:
    profile, spec, meta = resolve_reasoning_profile("Hoi, hoe gaat het?", "adaptive")
    return {
        "passed": profile == "fast" and spec.kind in {"chat", "question"},
        "profile": profile,
        "kind": spec.kind,
        "model_calls_expected_max": 1,
        "complexity": meta["complexity"]["total"],
    }


def scenario_short_hard_analysis() -> dict[str, Any]:
    text = "Debug deze Traceback en herontwerp de orchestratie-architectuur met tests."
    profile, spec, meta = resolve_reasoning_profile(text, "adaptive")
    return {
        "passed": profile in {"high", "maximum"} and spec.kind in {"debug", "code", "planning", "analysis"},
        "profile": profile,
        "complexity": meta["complexity"],
        "kind": spec.kind,
    }


def scenario_role_safety() -> dict[str, Any]:
    messages = assemble_context_messages(
        system_parts=["policy"],
        history=[{"role": "assistant", "content": "vorige"}],
        context_items=[],
        user_text="Nieuwe vraag",
    )
    user_messages = [item for item in messages if item["role"] == "user"]
    flat = any(("ASSISTANT:" in item["content"] or "SYSTEM:" in item["content"]) for item in user_messages)
    return {"passed": len(user_messages) == 1 and not flat, "roles": [item["role"] for item in messages]}


def scenario_tool_discovery_paging() -> dict[str, Any]:
    plugins = [
        {
            "id": f"p{i}",
            "name": f"Search Plugin {i}",
            "description": "search utility",
            "enabled": True,
            "status": "ready",
            "category": "Research",
            # Trust ladder: autonomous discovery requires >= manual (subprocess default).
            "trust": "manual",
            "manifest": {"autonomous": True, "category": "Research"},
        }
        for i in range(10)
    ]
    tools = [
        {
            "plugin_id": f"p{i}",
            "name": f"search_{i}",
            "description": "search utility",
            "enabled": True,
            "input_schema": {},
            "metadata": {},
        }
        for i in range(10)
    ]
    first = discover_tools(
        query="search",
        plugins=plugins,
        tools=tools,
        permission_ok=lambda *_: True,
        limit=3,
        offset=0,
    )
    second = discover_tools(
        query="search",
        plugins=plugins,
        tools=tools,
        permission_ok=lambda *_: True,
        limit=3,
        offset=3,
    )
    return {
        "passed": first["total"] == 10
        and first["next_offset"] == 3
        and second["tools"][0]["tool_name"] != first["tools"][0]["tool_name"],
        "first_total": first["total"],
        "first_names": [item["tool_name"] for item in first["tools"]],
        "second_names": [item["tool_name"] for item in second["tools"]],
    }


def scenario_fake_success_gate() -> dict[str, Any]:
    unrelated_ok = parse_verification_result(
        '{"passed":true,"issues":[],"final":"","evidence_refs":[],"incomplete":false}'
    )
    allowed, reason = verification_allows_success(
        unrelated_ok,
        tool_observations=[{"status": "completed", "plugin_id": "x", "tool_name": "unrelated"}],
    )
    blocked_parse = verification_allows_success(None)[0]
    return {"passed": (not allowed) and (not blocked_parse), "reason": reason}


def scenario_offline_route() -> dict[str, Any]:
    spec = build_request_spec("Zoek actueel nieuws over Local AI releases")
    route = build_route_decision(
        spec,
        requested_profile="adaptive",
        network_policy="block",
        plugin_tools_enabled=True,
    )
    return {
        "passed": route.allow_web is False,
        "needs_research": spec.needs_research,
        "route": route.to_dict(),
    }


def scenario_evidence_refs_must_exist() -> dict[str, Any]:
    from reasoning import validate_evidence_refs

    ok_bad, reason = validate_evidence_refs(
        ["tool:ghost"],
        step_outputs=[{"title": "A", "agent_id": "executor", "output": "x"}],
        tool_observations=[{"call_id": "real", "status": "completed", "plugin_id": "p", "tool_name": "t"}],
    )
    ok_good, _ = validate_evidence_refs(
        ["step:1", "tool:real"],
        step_outputs=[{"title": "A", "agent_id": "executor", "output": "x"}],
        tool_observations=[{"call_id": "real", "status": "completed", "plugin_id": "p", "tool_name": "t"}],
    )
    return {"passed": (not ok_bad) and ok_good, "reason": reason}


def scenario_tool_budget_finalize() -> dict[str, Any]:
    from reasoning import finalize_without_tool_json

    raw = '{"hades_tool_call":{"plugin_id":"x","tool_name":"y","input":{}}}'
    finalized = finalize_without_tool_json(raw, reason="budget leeg")
    return {
        "passed": "hades_tool_call" not in finalized and "onvoltooid" in finalized.lower(),
        "finalized": finalized[:120],
    }


def scenario_global_tool_cap() -> dict[str, Any]:
    from reasoning import resolve_tool_round_budget

    capped = resolve_tool_round_budget(
        settings_max_tool_rounds=2,
        profile_max_tool_rounds=8,
        route_max_tool_rounds=8,
        tools_allowed=True,
    )
    disabled = resolve_tool_round_budget(
        settings_max_tool_rounds=5,
        profile_max_tool_rounds=8,
        route_max_tool_rounds=0,
        tools_allowed=False,
    )
    return {"passed": capped == 2 and disabled == 0, "capped": capped, "disabled": disabled}


def scenario_work_runtime_route_for_complex() -> dict[str, Any]:
    text = (
        "Implementeer een meerstaps migratieplan met architectuur, refactor en tests. "
        "Gebruik concrete stappen en afhankelijkheden."
    )
    profile, spec, _meta = resolve_reasoning_profile(text, "high")
    route = build_route_decision(
        spec,
        requested_profile=profile,
        network_policy="block",
        plugin_tools_enabled=True,
    )
    return {
        "passed": route.target == "work_runtime" and route.require_verification,
        "route": route.to_dict(),
        "kind": spec.kind,
    }


SCENARIOS = [
    ("S1", "Eenvoudige vraag / fast path", scenario_fast_path),
    ("S2", "Korte moeilijke analyse", scenario_short_hard_analysis),
    ("S3", "Role-safe context assembly", scenario_role_safety),
    ("S4", "Tool discovery buiten eerste shortlist", scenario_tool_discovery_paging),
    ("S5", "Fake-success verification gate", scenario_fake_success_gate),
    ("S6", "Offline/network block route", scenario_offline_route),
    ("S7", "Evidence refs moeten bestaan", scenario_evidence_refs_must_exist),
    ("S8", "Uitgeput toolbudget geen tool-JSON", scenario_tool_budget_finalize),
    ("S9", "Globale toolcap hard afgedwongen", scenario_global_tool_cap),
    ("S10", "Complexe opdracht → work_runtime", scenario_work_runtime_route_for_complex),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES reasoning evaluation suite (deterministic core)")
    parser.add_argument("--output", default="docs/REASONING_EVAL_REPORT.json")
    args = parser.parse_args()
    results = [_run(scenario_id, title, fn) for scenario_id, title, fn in SCENARIOS]
    payload = {
        "suite": "hades-reasoning-core",
        "mode": "deterministic",
        "live_model": "unconfirmed",
        "passed": sum(1 for item in results if item.passed),
        "failed": sum(1 for item in results if not item.passed),
        "results": [asdict(item) for item in results],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"], "output": str(out)}, ensure_ascii=False))
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
