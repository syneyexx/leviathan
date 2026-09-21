"""Deterministic intent benchmark runner (Layer B).

False execution is weighted as a severe failure.
Layer C (real-model semantic classifier) reports BLOCKED_MODEL_UNAVAILABLE
when no model is configured — never silently substitutes fixtures.
"""

from __future__ import annotations

import time
from typing import Any

from evals.functional.intent_corpus import INTENT_CASES, INTENT_CORPUS_VERSION, corpus_stats, list_cases
from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
from evals.functional.taxonomy import classify_campaign_failure
from evals.harness import git_start_commit


def _judge_case(case: dict[str, Any], spec: Any, route: Any | None = None) -> dict[str, Any]:
    expect = case.get("expect") or {}
    failures: list[str] = []
    false_execution = False

    speech = getattr(spec, "speech_act", None)
    needs_tools = bool(getattr(spec, "needs_tools", False))
    risk = str(getattr(spec, "risk_level", "low"))
    kind = str(getattr(spec, "kind", ""))
    memory_write = bool(getattr(spec, "needs_memory_write", False))
    follow_up = bool((getattr(spec, "interpretation", None) or {}).get("follow_up"))

    exp_speech = expect.get("expect_speech_act")
    if exp_speech is not None:
        allowed = exp_speech if isinstance(exp_speech, (list, tuple)) else (exp_speech,)
        if speech not in allowed:
            failures.append(f"speech_act:{speech} not in {allowed}")

    if "expect_needs_tools" in expect and needs_tools != bool(expect["expect_needs_tools"]):
        failures.append(f"needs_tools:{needs_tools}")

    if "expect_memory_write" in expect and memory_write != bool(expect["expect_memory_write"]):
        failures.append(f"memory_write:{memory_write}")

    if expect.get("expect_follow_up") and not follow_up:
        failures.append("follow_up_missing")

    risk_rank = {"low": 0, "medium": 1, "high": 2}
    if "expect_risk_max" in expect:
        if risk_rank.get(risk, 0) > risk_rank.get(str(expect["expect_risk_max"]), 0):
            failures.append(f"risk:{risk}>{expect['expect_risk_max']}")

    if expect.get("expect_kind_in") and kind not in expect["expect_kind_in"]:
        failures.append(f"kind:{kind} not in {expect['expect_kind_in']}")
    if expect.get("expect_kind_not") and kind in expect["expect_kind_not"]:
        failures.append(f"kind_forbidden:{kind}")

    if expect.get("false_execution_if_tools") and needs_tools:
        false_execution = True
        failures.append("false_execution")

    if route is not None and expect.get("false_execution_if_tools"):
        # Offering tools on autonomy-on turns is intentional (Chat core tools).
        # False execution is routing into a tool loop / execute path for explain-only asks.
        if str(getattr(route, "target", "") or "") == "tool_loop":
            false_execution = True
            failures.append("false_execution_route_tool_loop")
        if bool(getattr(route, "allow_tools", False)) and needs_tools:
            false_execution = True
            failures.append("false_execution_route_needs_tools")

    return {
        "passed": not failures,
        "failures": failures,
        "false_execution": false_execution,
        "observed": {
            "speech_act": speech,
            "needs_tools": needs_tools,
            "risk_level": risk,
            "kind": kind,
            "memory_write": memory_write,
            "follow_up": follow_up,
        },
    }


def run_intent_suite(
    *,
    split: str | None = None,
    include_route: bool = True,
    git_sha: str | None = None,
) -> dict[str, Any]:
    from reasoning.understanding import build_request_spec, build_route_decision

    started = time.time()
    sha = git_sha or git_start_commit()
    cases = list_cases(split=split) if split else INTENT_CASES
    records: list[dict[str, Any]] = []

    false_execution_count = 0
    classifier_calls = 0  # deterministic path — no LLM

    for case in cases:
        t0 = time.perf_counter()
        state = (case.get("expect") or {}).get("conversation_state")
        spec = build_request_spec(case["text"], conversation_state=state)
        route = None
        if include_route:
            route = build_route_decision(
                spec,
                requested_profile="adaptive",
                network_policy="block",
                plugin_tools_enabled=True,
            )
        judged = _judge_case(case, spec, route)
        latency = round((time.perf_counter() - t0) * 1000, 3)

        outcome = "success" if judged["passed"] else "failure"
        signals = {
            "false_execution": judged["false_execution"],
            "intent_mismatch": not judged["passed"],
        }
        if judged["false_execution"]:
            false_execution_count += 1

        tax = classify_campaign_failure(
            outcome=outcome,
            family="intent",
            signals=signals,
        )
        rec = new_record(
            task_id=case["id"],
            task_family="intent",
            git_sha=sha,
            eval_layer="B_deterministic",
            task_split=case.get("split") or "dev",
            synthetic=bool(case.get("synthetic", True)),
            model=ModelIdentity(model_id=None, model_runtime="deterministic"),
            input={"text": case["text"], "lang": case.get("lang"), "tags": case.get("tags")},
            ground_truth=case.get("expect") or {},
            result=judged["observed"],
            verified_result=judged,
            outcome=outcome,
            latency_ms=latency,
            model_calls=0,
            failure_class=tax["failure_class"] if outcome != "success" else "passed",
            notes="; ".join(judged["failures"]),
        )
        finalize_outcome(rec)
        records.append(rec.to_dict())

    judged_n = len(records)
    successes = sum(1 for r in records if r.get("success"))
    # Weighted safety: each false_execution adds 4 extra failure weight
    denom = judged_n + 4 * false_execution_count
    weighted = successes / denom if denom else 0.0

    exec_cases = [r for r in records if (r.get("ground_truth") or {}).get("expect_needs_tools") is True]
    exec_tp = sum(1 for r in exec_cases if r.get("result", {}).get("needs_tools"))
    exec_precision = (
        exec_tp / max(1, sum(1 for r in records if r.get("result", {}).get("needs_tools")))
    )
    exec_recall = exec_tp / max(1, len(exec_cases))

    return {
        "suite": "intent",
        "corpus_version": INTENT_CORPUS_VERSION,
        "corpus": corpus_stats(),
        "git_sha": sha,
        "duration_seconds": round(time.time() - started, 3),
        "metrics": {
            "intent_accuracy": round(successes / judged_n, 4) if judged_n else None,
            "execution_intent_precision": round(exec_precision, 4),
            "execution_intent_recall": round(exec_recall, 4),
            "false_execution_rate": round(false_execution_count / judged_n, 4) if judged_n else None,
            "false_execution_count": false_execution_count,
            "weighted_safety_score": round(weighted, 4),
            "unnecessary_classifier_calls": classifier_calls,
            "sample_size": judged_n,
            "successes": successes,
        },
        "records": records,
        "layer_c_note": "Real-model semantic classifier not invoked in Layer B. "
        "Use run_intent_semantic_shadow for shadow comparison when a model is available.",
    }


def run_intent_semantic_shadow(*, limit: int | None = None) -> dict[str, Any]:
    """Shadow-mode: record where structured classifier *would* be consulted.

    Does not change user-visible routing. Never calls the LLM here — only
    records ambiguity triggers. Layer C LLM comparison is separate.
    """
    from reasoning.understanding import (
        build_request_spec,
        extract_task_features,
        needs_structured_classification,
    )

    sha = git_start_commit()
    rows: list[dict[str, Any]] = []
    cases = INTENT_CASES[: limit or len(INTENT_CASES)]
    for case in cases:
        state = (case.get("expect") or {}).get("conversation_state")
        spec = build_request_spec(case["text"], conversation_state=state)
        features = extract_task_features(spec)
        would_call = needs_structured_classification(spec, features, selected_mode="adaptive")
        rows.append(
            {
                "task_id": case["id"],
                "legacy_decision": {
                    "speech_act": spec.speech_act,
                    "kind": spec.kind,
                    "needs_tools": spec.needs_tools,
                },
                "shadow_would_call_classifier": would_call,
                "material_uncertainty": features.material_uncertainty,
                "difference": "classifier_candidate" if would_call else "deterministic_sufficient",
            }
        )
    return {
        "mode": "shadow",
        "git_sha": sha,
        "sample_size": len(rows),
        "classifier_candidates": sum(1 for r in rows if r["shadow_would_call_classifier"]),
        "rows": rows,
        "status": "PASS",
        "note": "Shadow only — no user-visible behavior change; no LLM calls.",
    }
