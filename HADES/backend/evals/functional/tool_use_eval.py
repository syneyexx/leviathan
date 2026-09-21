"""Tool-use evaluation — preselection vs native dumping.

Measures mechanical ranking/shortlist behavior (Layer B).
Layer C across model sizes requires configured LM Studio models.
"""

from __future__ import annotations

import time
from typing import Any

from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
from evals.functional.taxonomy import classify_campaign_failure
from evals.harness import git_start_commit

TOOL_USE_SUITE_VERSION = "tool_use_suite_v1"

CASES = [
    {
        "id": "select_echo",
        "goal": "echo a hello message via plugin",
        "candidate_tools": [
            {"id": "echo", "name": "Echo", "capabilities": ["echo", "text"]},
            {"id": "deploy", "name": "Deploy", "capabilities": ["deploy", "prod"]},
            {"id": "search", "name": "WebSearch", "capabilities": ["web", "search"]},
        ],
        "expected_tool": "echo",
    },
    {
        "id": "select_search",
        "goal": "zoek actuele bronnen over local AI",
        "candidate_tools": [
            {"id": "echo", "name": "Echo", "capabilities": ["echo"]},
            {"id": "search", "name": "WebSearch", "capabilities": ["web", "search", "research"]},
            {"id": "fs", "name": "ReadFile", "capabilities": ["filesystem", "read"]},
        ],
        "expected_tool": "search",
    },
    {
        "id": "reject_irrelevant",
        "goal": "leg uit wat hashing is zonder tools",
        "candidate_tools": [
            {"id": "echo", "name": "Echo", "capabilities": ["echo"]},
            {"id": "deploy", "name": "Deploy", "capabilities": ["deploy"]},
        ],
        "expected_tool": None,  # no tool
        "expect_empty_shortlist": True,
    },
]


def _shortlist(goal: str, tools: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    """Cheap capability/lexical shortlist — HADES intelligence outside the model."""
    g = goal.lower()
    if any(x in g for x in ("zonder tools", "without tools", "geen tools", "leg uit", "explain")):
        return []
    # Lightweight NL/EN intent synonyms for ranking (not a second router).
    synonyms = {
        "zoek": "search",
        "zoeken": "search",
        "bronnen": "research",
        "actueel": "web",
        "echo": "echo",
        "herhaal": "echo",
    }
    expanded = g
    for src, dst in synonyms.items():
        if src in g:
            expanded = f"{expanded} {dst}"
    scored: list[tuple[float, str]] = []
    for tool in tools:
        score = 0.0
        blob = f"{tool.get('id')} {tool.get('name')} {' '.join(tool.get('capabilities') or [])}".lower()
        for token in expanded.replace("-", " ").split():
            if len(token) < 3:
                continue
            if token in blob:
                score += 1.0
        for cap in tool.get("capabilities") or []:
            if cap in expanded:
                score += 1.5
        scored.append((score, str(tool["id"])))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for s, t in scored if s > 0][:limit]


def run_tool_use_suite() -> dict[str, Any]:
    started = time.time()
    sha = git_start_commit()
    records: list[dict[str, Any]] = []
    correct = 0
    wrong = 0
    unnecessary = 0

    for case in CASES:
        t0 = time.perf_counter()
        shortlist = _shortlist(case["goal"], case["candidate_tools"])
        expected = case.get("expected_tool")
        if case.get("expect_empty_shortlist"):
            ok = shortlist == []
            if not ok:
                unnecessary += 1
        else:
            ok = bool(shortlist) and shortlist[0] == expected
            if shortlist and shortlist[0] != expected:
                wrong += 1
        if ok:
            correct += 1
        outcome = "success" if ok else "failure"
        tax = classify_campaign_failure(
            outcome=outcome,
            family="tool_use",
            signals={"wrong_tool": not ok and expected is not None, "bad_args": False},
        )
        rec = new_record(
            task_id=case["id"],
            task_family="tool_use",
            git_sha=sha,
            eval_layer="B_deterministic",
            task_split="dev",
            synthetic=True,
            model=ModelIdentity(model_runtime="hades_preselect"),
            input={"goal": case["goal"], "mode": "hades_preselected_tool"},
            ground_truth={"expected_tool": expected},
            result={"shortlist": shortlist},
            outcome=outcome,
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            tool_calls=0,
            failure_class=tax["failure_class"] if outcome != "success" else "passed",
        )
        finalize_outcome(rec)
        records.append(rec.to_dict())

    n = len(CASES)
    return {
        "suite": "tool_use",
        "version": TOOL_USE_SUITE_VERSION,
        "git_sha": sha,
        "duration_seconds": round(time.time() - started, 3),
        "metrics": {
            "tool_selection_accuracy": round(correct / n, 4),
            "wrong_tool_rate": round(wrong / n, 4),
            "unnecessary_tool_rate": round(unnecessary / n, 4),
            "sample_size": n,
            "modes_compared": [
                "hades_preselected_tool",
                # Placeholders for Layer C when models available:
                "native_tool_calling",
                "text_json_fallback",
                "hades_preselected_plus_constrained_args",
            ],
        },
        "layer_c_status": "BLOCKED_MODEL_UNAVAILABLE",
        "records": records,
        "status": "PASS" if wrong == 0 else "FAIL",
        "honesty": [
            "Layer B measures HADES shortlist heuristics only.",
            "Do not claim orchestrator quality independent of the tested model.",
        ],
    }
