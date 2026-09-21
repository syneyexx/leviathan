"""A01 executable agent evaluation CLI — production-route scoring.

Separates:
  - software: harness wiring, honesty, fake-route callback tests
  - infra_smoke: LM Studio reachability
  - model_answer: live quality judges (UNMEASURED without LM)
  - agent_task: complete tasks via real production route

Host commands (cwd=backend or PYTHONPATH=backend):

  python -m evals.agent_eval --mode software
  python -m evals.agent_eval --mode executable --split holdout --repeats 2
  python -m evals.agent_eval --mode agent_task --limit 5 --out artifacts/eval_runs/run.json

Never injects coding solutions. Retries preserve prior attempt failures in the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evals.agent_judges import (
    AGENT_JUDGE_VERSION,
    assert_grader_outside_workspace,
    baseline_coding_must_fail,
    judge_agent_task,
)
from evals.agent_tasks import (
    AGENT_TASKS_DATASET_VERSION,
    agent_categories_covered,
    agent_dataset_fingerprint,
    combined_corpus_stats,
    list_agent_dev_tasks,
    list_agent_holdout_tasks,
)
from evals.harness import git_start_commit, model_config_snapshot
from evals.production_route import (
    PRODUCTION_ROUTE_ID,
    ProductionRouteRequest,
    invoke_baseline_route,
    invoke_production_route,
    probe_lm_studio,
)
from evals.release_thresholds import RELEASE_THRESHOLDS, THRESHOLD_VERSION, evaluate_thresholds


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    return _backend_root().parent


def default_out_dir() -> Path:
    return _repo_root() / "artifacts" / "eval_runs"


def evidence_out_dir() -> Path:
    return _repo_root() / "docs" / "evidence" / "eval_runs"


def case_usage_path() -> Path:
    return default_out_dir() / "case_usage.jsonl"


def record_case_usage(task_id: str, *, run_id: str, split: str, mode: str) -> None:
    path = case_usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "run_id": run_id,
        "split": split,
        "mode": mode,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def load_case_usage(*, limit: int = 5000) -> list[dict[str, Any]]:
    path = case_usage_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _select_tasks(*, split: str, limit: int | None, categories: list[str] | None) -> list[dict[str, Any]]:
    if split == "development":
        tasks = list_agent_dev_tasks()
    elif split == "all":
        tasks = list_agent_holdout_tasks() + list_agent_dev_tasks()
    else:
        tasks = list_agent_holdout_tasks()
    if categories:
        allow = set(categories)
        tasks = [t for t in tasks if t.get("category") in allow]
    if limit is not None:
        tasks = tasks[:limit]
    return tasks


def _materialize_task(task: dict[str, Any], *, variant: str) -> Path:
    fixture = task.get("fixture")
    if not callable(fixture):
        raise ValueError(f"task {task.get('id')} missing fixture factory")
    return Path(fixture(variant=variant))


def run_software_layer(*, route_callback: Callable | None = None) -> dict[str, Any]:
    """Offline software evidence: corpus stats, honesty sample, fake-route wiring."""
    from evals.fixed_task_set import assert_fixed_task_set_bounds, fixed_task_set_manifest

    stats = combined_corpus_stats()
    fixed = fixed_task_set_manifest()
    assert_fixed_task_set_bounds()
    # Honesty: a few coding holdouts must start red
    from evals.holdout_judges import run_holdout_honesty_suite

    honesty = run_holdout_honesty_suite(limit=5)
    # Fake production route callback — proves route is called, no solution injection
    calls: list[str] = []

    def _fake(req: ProductionRouteRequest) -> dict[str, Any]:
        calls.append(req.task_id)
        # Do not write fixes into workspace
        return {
            "route": PRODUCTION_ROUTE_ID,
            "invoked": True,
            "solution_injected": False,
            "task_id": req.task_id,
            "status": "fake_callback",
            "work_root": str(req.work_root),
            "artifacts": [],
            "task_status": "fake_callback",
            "tokens": None,
            "duration_ms": 1,
            "model_invoked": False,
            "stages": ["model_gateway", "retrieval", "planning", "tool_execution", "task_status", "artifacts", "verification"],
            "claimed_success": False,
            "measurement_status": "software_fake_callback",
        }

    cb = route_callback or _fake
    sample = next(t for t in list_agent_holdout_tasks() if t.get("task_kind") == "coding")
    root = _materialize_task(sample, variant="software")
    before = None
    target = None
    for p in root.rglob("*.py"):
        if p.name.startswith("test_"):
            continue
        before = p.read_text(encoding="utf-8")
        target = p
        break
    req = ProductionRouteRequest(
        task_id=sample["id"],
        goal=sample["goal"],
        work_root=root,
        task=sample,
    )
    out = invoke_production_route(req, route_callback=cb)
    after = target.read_text(encoding="utf-8") if target else None
    grader_violations = assert_grader_outside_workspace(root)
    wiring_ok = (
        out.get("invoked") is True
        and out.get("solution_injected") is False
        and sample["id"] in calls
        and before == after
        and not grader_violations
        and stats["holdout_count"] >= 30
        and fixed.get("within_bounds") is True
    )
    return {
        "layer": "software",
        "status": "measured",
        "passed": wiring_ok and honesty.get("all_fixtures_honest"),
        "pass_rate": 1.0 if wiring_ok and honesty.get("all_fixtures_honest") else 0.0,
        "false_success_rate": 0.0,
        "corpus": stats,
        "fixed_task_set": fixed,
        "honesty_sample": {
            "all_fixtures_honest": honesty.get("all_fixtures_honest"),
            "total": honesty.get("total"),
        },
        "route_wiring": {
            "callback_invoked_for": calls,
            "solution_injected": out.get("solution_injected"),
            "workspace_unchanged_by_harness": before == after,
            "grader_outside_workspace": grader_violations == [],
            "grader_violations": grader_violations,
        },
        "threshold_version": THRESHOLD_VERSION,
    }


def run_infra_smoke() -> dict[str, Any]:
    probe = probe_lm_studio()
    if probe.get("available"):
        return {
            "layer": "infra_smoke",
            "status": "measured",
            "passed": True,
            "pass_rate": 1.0,
            "lm_studio": probe,
            "note": "Provider reachable; not a model-quality claim.",
        }
    return {
        "layer": "infra_smoke",
        "status": "UNMEASURED",
        "passed": None,
        "pass_rate": None,
        "lm_studio": probe,
        "note": "LM Studio unavailable; infra smoke UNMEASURED (allowed).",
        "missing_reason": probe.get("error") or "unreachable",
    }


def run_model_answer_layer(*, chat_fn: Any | None = None) -> dict[str, Any]:
    from evals.quality_suite import run_live_quality_layer

    if chat_fn is None:
        probe = probe_lm_studio()
        if probe.get("available"):
            from evals.production_route import _resolve_chat_fn

            chat_fn, _meta = _resolve_chat_fn(None)
        else:
            report = run_live_quality_layer(chat_fn=None)
            return {
                "layer": "model_answer",
                "status": "UNMEASURED",
                "passed": None,
                "pass_rate": None,
                "first_attempt_success": None,
                "false_success_rate": None,
                "tokens": None,
                "live": report,
                "missing_reason": "lm_studio_unavailable",
            }
    report = run_live_quality_layer(chat_fn=chat_fn)
    status = "measured" if report.get("status") == "measured" else "UNMEASURED"
    pass_rate = report.get("pass_rate")
    return {
        "layer": "model_answer",
        "status": status if status == "measured" else "UNMEASURED",
        "passed": None if status != "measured" else pass_rate == 1.0,
        "pass_rate": pass_rate,
        "first_attempt_success": pass_rate,
        "false_success_rate": 0.0 if status == "measured" else None,
        "tokens": None,
        "live": report,
        "missing_reason": None if status == "measured" else "live_quality_unmeasured",
    }


def _error_category(route_out: dict[str, Any], judged: dict[str, Any]) -> str | None:
    if route_out.get("error_category"):
        return str(route_out["error_category"])
    if judged.get("false_success"):
        return "false_success"
    if judged.get("policy_violation"):
        return "policy_violation"
    if not judged.get("passed"):
        return judged.get("reason") or judged.get("verdict") or "incorrect"
    return None


def run_single_attempt(
    task: dict[str, Any],
    *,
    attempt: int,
    run_id: str,
    route_callback: Callable | None,
    compare_baseline: bool,
    model_id: str | None,
    budget: dict[str, Any],
) -> dict[str, Any]:
    variant = f"eval_{run_id[:8]}_a{attempt}"
    root = _materialize_task(task, variant=variant)
    grader_violations = assert_grader_outside_workspace(root)
    baseline_failed = None
    if task.get("judge") == "execution_tests" or task.get("task_kind") == "coding":
        base = baseline_coding_must_fail(task, root)
        baseline_failed = not base["passed"]
        if not base["honest"]:
            return {
                "task_id": task["id"],
                "attempt": attempt,
                "passed": False,
                "verdict": "invalid_fixture_green",
                "false_success": False,
                "error_category": "invalid_fixture_green",
                "work_root": str(root),
                "route_invoked": False,
                "note": "Fixture started green; refusing to score.",
            }

    req = ProductionRouteRequest(
        task_id=task["id"],
        goal=task["goal"],
        work_root=root,
        task=task,
        model_id=model_id,
        budget=budget,
        max_attempts=int(budget.get("max_attempts") or 3),
    )
    started = time.perf_counter()
    route_out = invoke_production_route(req, route_callback=route_callback)
    baseline_out = None
    if compare_baseline:
        # Fresh copy for baseline so HADES run is not contaminated
        base_root = _materialize_task(task, variant=f"{variant}_baseline")
        base_req = ProductionRouteRequest(
            task_id=task["id"],
            goal=task["goal"],
            work_root=base_root,
            task=task,
            model_id=model_id,
            budget=budget,
            max_attempts=int(budget.get("max_attempts") or 3),
            run_baseline=True,
        )
        baseline_out = invoke_baseline_route(base_req)

    judged = judge_agent_task(
        task,
        Path(route_out.get("work_root") or root),
        baseline_failed=baseline_failed,
        agent_status=route_out.get("status"),
        agent_claimed_success=bool(route_out.get("claimed_success")),
    )
    duration_s = round(time.perf_counter() - started, 3)
    record_case_usage(task["id"], run_id=run_id, split=str(task.get("split")), mode="agent_task")

    diff = None
    if baseline_out is not None:
        diff = {
            "hades_passed": judged.get("passed"),
            "baseline_status": baseline_out.get("status"),
            "hades_status": route_out.get("status"),
            "hades_duration_ms": route_out.get("duration_ms"),
            "baseline_duration_ms": baseline_out.get("duration_ms"),
            "hades_tokens": route_out.get("tokens"),
            "baseline_tokens": baseline_out.get("tokens"),
            "explicit_diff": {
                "route_hades": route_out.get("route"),
                "route_baseline": baseline_out.get("route"),
                "strategy_note": "HADES uses investigate; baseline uses fast",
            },
        }

    measurement = route_out.get("measurement_status")
    if task.get("task_kind") != "coding" and not route_out.get("model_invoked"):
        measurement = "UNMEASURED"

    return {
        "task_id": task["id"],
        "category": task.get("category"),
        "task_kind": task.get("task_kind"),
        "split": task.get("split"),
        "attempt": attempt,
        "passed": judged.get("passed"),
        "verdict": judged.get("verdict"),
        "false_success": bool(judged.get("false_success")),
        "policy_violation": bool(judged.get("policy_violation")),
        "evidence_backed": judged.get("evidence_backed"),
        "duration_seconds": duration_s,
        "tokens": route_out.get("tokens"),
        "tokens_missing_reason": None if route_out.get("tokens") is not None else "provider_did_not_report_tokens",
        "error_category": _error_category(route_out, judged),
        "work_root": str(route_out.get("work_root") or root),
        "route": route_out.get("route"),
        "route_invoked": bool(route_out.get("invoked")),
        "solution_injected": bool(route_out.get("solution_injected")),
        "stages": route_out.get("stages"),
        "model_invoked": route_out.get("model_invoked"),
        "measurement_status": measurement,
        "judge": {k: v for k, v in judged.items() if k != "evidence"} | {"evidence": judged.get("evidence")},
        "grader_outside_workspace": grader_violations == [],
        "grader_violations": grader_violations,
        "baseline_diff": diff,
        "route_raw": route_out.get("raw"),
    }


def aggregate_agent_metrics(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for row in attempts:
        by_task.setdefault(row["task_id"], []).append(row)

    first_ok = 0
    first_total = 0
    reliable = 0
    reliable_total = 0
    false_success = 0
    policy_violations = 0
    measured = 0
    unmeasured = 0
    error_categories: dict[str, int] = {}
    durations: list[float] = []
    tokens_seen = 0
    tokens_missing = 0
    tool_ok = 0
    tool_total = 0
    model_calls = 0
    model_call_reports = 0
    completed_tasks = 0

    for task_id, rows in by_task.items():
        rows_sorted = sorted(rows, key=lambda r: r["attempt"])
        # Retries do not erase earlier failures — all rows remain in `attempts`.
        first = rows_sorted[0]
        if first.get("measurement_status") == "UNMEASURED":
            unmeasured += 1
            continue
        measured += 1
        first_total += 1
        if first.get("passed"):
            first_ok += 1
            completed_tasks += 1
        if len(rows_sorted) >= 2:
            reliable_total += 1
            if all(r.get("passed") for r in rows_sorted):
                reliable += 1
        for r in rows_sorted:
            if r.get("false_success"):
                false_success += 1
            if r.get("policy_violation"):
                policy_violations += 1
            cat = r.get("error_category")
            if cat:
                error_categories[str(cat)] = error_categories.get(str(cat), 0) + 1
            if r.get("duration_seconds") is not None:
                durations.append(float(r["duration_seconds"]))
            if r.get("tokens") is None:
                tokens_missing += 1
            else:
                tokens_seen += 1
            # Tool success: prefer explicit route fields; else stages containing tool_execution.
            if r.get("tool_success") is not None:
                tool_total += 1
                if r.get("tool_success"):
                    tool_ok += 1
            elif r.get("route_invoked") and "tool_execution" in list(r.get("stages") or []):
                tool_total += 1
                if r.get("passed"):
                    tool_ok += 1
            calls = r.get("model_calls")
            if calls is None and r.get("model_invoked") is True:
                calls = 1
            if calls is not None:
                model_call_reports += 1
                model_calls += int(calls)

    def _rate(n: int, d: int) -> float | None:
        if d <= 0:
            return None
        return round(n / d, 4)

    latency_ms = None
    if durations:
        latency_ms = round((sum(durations) / len(durations)) * 1000.0, 1)

    return {
        "first_attempt_success": _rate(first_ok, first_total),
        "first_attempt_success_missing_reason": None if first_total else "no_measured_tasks",
        "repeated_reliability": _rate(reliable, reliable_total),
        "repeated_reliability_missing_reason": None if reliable_total else "need_repeats_ge_2",
        "false_success_rate": _rate(false_success, max(1, len(attempts))),
        "policy_violations": policy_violations,
        "policy_violation_rate": _rate(policy_violations, max(1, len(attempts))),
        "duration_seconds": {
            "mean": round(sum(durations) / len(durations), 3) if durations else None,
            "n": len(durations),
        },
        "latency_ms": {
            "mean": latency_ms,
            "n": len(durations),
            "missing_reason": None if durations else "no_measured_durations",
        },
        "tokens": {
            "reports_seen": tokens_seen,
            "missing": tokens_missing,
            "missing_reason": "provider_did_not_report_tokens" if tokens_missing else None,
            "real_tokens_aggregate": None,
            "note": "Per-attempt tokens recorded when provider reports usage; else null.",
        },
        "tool_success_ratio": _rate(tool_ok, tool_total),
        "tool_success_ratio_missing_reason": None if tool_total else "no_tool_attempts_recorded",
        "task_completion": _rate(completed_tasks, measured),
        "task_completion_missing_reason": None if measured else "no_measured_tasks",
        "model_calls": {
            "total": model_calls if model_call_reports else None,
            "reports": model_call_reports,
            "missing_reason": None if model_call_reports else "provider_did_not_report_model_calls",
        },
        "error_categories": error_categories,
        "measured_tasks": measured,
        "unmeasured_tasks": unmeasured,
        "attempt_count": len(attempts),
        "task_count": len(by_task),
    }


def run_agent_task_layer(
    *,
    split: str = "holdout",
    limit: int | None = None,
    repeats: int = 1,
    categories: list[str] | None = None,
    route_callback: Callable | None = None,
    compare_baseline: bool = False,
    model_id: str | None = None,
    budget: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or uuid.uuid4().hex
    tasks = _select_tasks(split=split, limit=limit, categories=categories)
    budget = budget or {"max_attempts": 3}
    attempts: list[dict[str, Any]] = []
    for task in tasks:
        for attempt in range(1, max(1, repeats) + 1):
            attempts.append(
                run_single_attempt(
                    task,
                    attempt=attempt,
                    run_id=run_id,
                    route_callback=route_callback,
                    compare_baseline=compare_baseline,
                    model_id=model_id,
                    budget=budget,
                )
            )
    metrics = aggregate_agent_metrics(attempts)
    probe = probe_lm_studio()
    # If everything scenario-unmeasured and no coding measured, layer is UNMEASURED
    status = "measured"
    if metrics["measured_tasks"] == 0 and metrics["unmeasured_tasks"] > 0:
        status = "UNMEASURED"
    elif not probe.get("available") and all(
        (a.get("task_kind") != "coding") or not a.get("model_invoked") for a in attempts
    ):
        # Coding may still be measured via heuristics; keep measured if any coding scored
        if metrics["measured_tasks"] == 0:
            status = "UNMEASURED"

    return {
        "layer": "agent_task",
        "status": status,
        "run_id": run_id,
        "dataset": AGENT_TASKS_DATASET_VERSION,
        "judge_version": AGENT_JUDGE_VERSION,
        "split": split,
        "repeats": repeats,
        "task_ids": [t["id"] for t in tasks],
        "attempts": attempts,  # prior failures retained
        "metrics": metrics,
        "first_attempt_success": metrics.get("first_attempt_success"),
        "repeated_reliability": metrics.get("repeated_reliability"),
        "false_success_rate": metrics.get("false_success_rate"),
        "policy_violation_rate": metrics.get("policy_violation_rate"),
        "pass_rate": metrics.get("first_attempt_success"),
        "lm_studio": probe,
        "missing_reason": None if status != "UNMEASURED" else "live_agent_quality_unmeasured_without_model",
        "case_usage_file": str(case_usage_path()),
    }


def render_human_report(report: dict[str, Any]) -> str:
    lines = [
        f"# HADES Agent Eval Report ({report.get('run_id')})",
        "",
        f"- Generated: {report.get('generated_at')}",
        f"- Start commit: {report.get('start_commit')}",
        f"- Threshold version: {report.get('threshold_version')}",
        f"- Dataset: {report.get('dataset')}",
        f"- Mode: {report.get('mode')}",
        "",
        "## Layers",
    ]
    for name, layer in (report.get("layers") or {}).items():
        lines.append(
            f"- **{name}**: status={layer.get('status')} "
            f"pass_rate={layer.get('pass_rate')} "
            f"first_attempt={layer.get('first_attempt_success')}"
        )
    lines.append("")
    lines.append("## Metrics (honest nulls)")
    metrics = report.get("metrics") or {}
    for key in RELEASE_THRESHOLDS["metrics_required_fields"]:
        val = metrics.get(key)
        lines.append(f"- {key}: {val!r}")
    gate = report.get("threshold_gate") or {}
    lines.append("")
    lines.append(f"## Threshold gate: overall_software_release_ok={gate.get('overall_software_release_ok')}")
    for row in gate.get("layers") or []:
        lines.append(f"- {row.get('layer')}: passed_gate={row.get('passed_gate')} reasons={row.get('reasons')}")
    live = report.get("live_unmeasured") or {}
    lines.append("")
    lines.append("## Live / UNMEASURED")
    for k, v in live.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Host command")
    lines.append(f"`{report.get('host_command')}`")
    lines.append("")
    return "\n".join(lines)


def run_agent_eval(
    *,
    mode: str = "executable",
    split: str = "holdout",
    limit: int | None = None,
    repeats: int = 1,
    categories: list[str] | None = None,
    out_path: str | None = None,
    compare_baseline: bool = False,
    model_id: str | None = None,
    route_callback: Callable | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    started = time.time()
    run_id = uuid.uuid4().hex
    layers: dict[str, Any] = {}

    if mode in {"software", "executable", "all"}:
        layers["software"] = run_software_layer(route_callback=route_callback if mode == "software" else None)
    if mode in {"infra_smoke", "executable", "all"}:
        layers["infra_smoke"] = run_infra_smoke()
    if mode in {"model_answer", "executable", "all"}:
        layers["model_answer"] = run_model_answer_layer()
    if mode in {"agent_task", "executable", "all"}:
        layers["agent_task"] = run_agent_task_layer(
            split=split,
            limit=limit,
            repeats=repeats,
            categories=categories,
            route_callback=route_callback,
            compare_baseline=compare_baseline,
            model_id=model_id,
            run_id=run_id,
        )
    if mode == "software" and "software" not in layers:
        layers["software"] = run_software_layer(route_callback=route_callback)

    gate = evaluate_thresholds(layers)
    agent_metrics = (layers.get("agent_task") or {}).get("metrics") or {}
    live_unmeasured = {
        "infra_smoke": (layers.get("infra_smoke") or {}).get("status"),
        "model_answer": (layers.get("model_answer") or {}).get("status"),
        "agent_task": (layers.get("agent_task") or {}).get("status"),
        "lm_studio_available": probe_lm_studio().get("available"),
    }

    report: dict[str, Any] = {
        "harness": "evals.agent_eval",
        "a01": True,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "seed": seed,
        "dataset": AGENT_TASKS_DATASET_VERSION,
        "dataset_fingerprint_sha256": agent_dataset_fingerprint(),
        "categories": agent_categories_covered(),
        "corpus": combined_corpus_stats(),
        "start_commit": git_start_commit(),
        "model_config": model_config_snapshot(),
        "threshold_version": THRESHOLD_VERSION,
        "release_thresholds": RELEASE_THRESHOLDS,
        "threshold_gate": gate,
        "layers": layers,
        "metrics": agent_metrics,
        "live_unmeasured": live_unmeasured,
        "case_usage": load_case_usage(limit=200),
        "claimed_agent_quality_pass": False,
        "duration_seconds": round(time.time() - started, 3),
        "host_command": (
            f"python -m evals.agent_eval --mode {mode} --split {split}"
            + (f" --limit {limit}" if limit else "")
            + (f" --repeats {repeats}" if repeats != 1 else "")
        ),
        "note": (
            "Software/infra separated from live model and agent-task quality. "
            "UNMEASURED means not measured — not a silent pass. "
            "Thresholds fixed before measurement (see docs/engineering/EVAL_RELEASE_THRESHOLDS.md)."
        ),
    }

    # Never claim agent quality pass unless agent_task measured and gate soft-ok
    agent_layer = layers.get("agent_task") or {}
    if agent_layer.get("status") == "measured" and agent_layer.get("first_attempt_success") is not None:
        report["claimed_agent_quality_pass"] = False  # explicit: human reviews gate; no auto PASS inflate

    text = render_human_report(report)
    report["human_report_markdown"] = text

    out_dir = default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_out_dir().mkdir(parents=True, exist_ok=True)

    json_path = Path(out_path) if out_path else out_dir / f"agent_eval_{run_id}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")
    # Mirror under docs/evidence for audit trail
    evidence_json = evidence_out_dir() / json_path.name
    evidence_md = evidence_out_dir() / md_path.name
    evidence_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    evidence_md.write_text(text, encoding="utf-8")

    report["wrote"] = str(json_path)
    report["wrote_human"] = str(md_path)
    report["wrote_evidence"] = str(evidence_json)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HADES A01 production-route agent eval")
    parser.add_argument(
        "--mode",
        default="executable",
        choices=["software", "infra_smoke", "model_answer", "agent_task", "executable", "all"],
    )
    parser.add_argument("--split", default="holdout", choices=["holdout", "development", "all"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1, help="Repeat representative cases; prior attempts kept")
    parser.add_argument("--category", action="append", default=None)
    parser.add_argument("--out", default="", help="JSON report path")
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    backend = str(_backend_root())
    if backend not in sys.path:
        sys.path.insert(0, backend)

    report = run_agent_eval(
        mode=args.mode,
        split=args.split,
        limit=args.limit,
        repeats=args.repeats,
        categories=args.category,
        out_path=args.out or None,
        compare_baseline=args.compare_baseline,
        model_id=args.model_id,
        seed=args.seed,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "human_report_markdown"}, indent=2, default=str))
    software = (report.get("layers") or {}).get("software") or {}
    if software and software.get("passed") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
