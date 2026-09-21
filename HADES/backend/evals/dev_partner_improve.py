"""Controlled self-improvement proposal loop for Development Partner.

HADES may prepare an improvement proposal with evidence. It must NOT:
- rewrite independent judges / holdout oracles
- relax security rules
- delete contradicting results
- auto-merge to main
- claim higher scores by skipping tasks

Activation remains human-reviewed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dev_partner_harness import run_dev_partner_suite
from evals.dev_partner_judges import assert_grader_outside_workspace
from evals.failure_taxonomy import FAILURE_CLASS_VERSION


IMPROVE_LOOP_VERSION = "dev_partner_improve_v1"
PROTECTED_JUDGE_MODULES = (
    "backend/evals/dev_partner_judges.py",
    "backend/evals/holdout_judges.py",
    "backend/evals/agent_judges.py",
    "backend/evals/release_thresholds.py",
)


def propose_improvement_from_failures(
    *,
    failure_report: dict[str, Any] | None = None,
    split: str = "development",
) -> dict[str, Any]:
    """Select the top recurring bottleneck and package a reviewable proposal."""
    if failure_report is None:
        failure_report = run_dev_partner_suite(mode="baseline_compare", split=split, limit=12)
    failures = (
        (failure_report.get("baseline") or {}).get("failures")
        or failure_report.get("failures")
        or {}
    )
    top = failures.get("top_bottleneck")
    recurring = failures.get("recurring") or []
    # Targeted improvement already implemented in-product: report-only path + delivery gate.
    proposal = {
        "version": IMPROVE_LOOP_VERSION,
        "failure_taxonomy_version": FAILURE_CLASS_VERSION,
        "selected_bottleneck": top,
        "recurring": recurring[:5],
        "improvement": {
            "id": "DP_IMP_01_report_delivery_gate",
            "title": "Report-only workflow + CodingDeliveryV1 completion gate",
            "component": "coding_agent + coding_delivery",
            "hypothesis": (
                "False success and missing outputs on review/regression tasks drop when "
                "the agent uses a report-only path and cannot mark completed without required fields."
            ),
            "testable": True,
            "eval_rerun": {
                "command": "python -m evals.dev_partner_harness --mode baseline_compare --split development",
                "same_criteria": True,
                "criteria_version": "dev_partner_judge_v1",
            },
        },
        "guards": {
            "may_modify_independent_judges": False,
            "may_relax_security": False,
            "may_delete_contradicting_results": False,
            "may_auto_merge_main": False,
            "may_skip_tasks_to_inflate_score": False,
            "protected_paths": list(PROTECTED_JUDGE_MODULES),
        },
        "recommendation": (
            "Recommend only when baseline_compare shows improved pass_rate without "
            "criteria changes and protected judge modules remain untouched."
        ),
        "activation": "explicit_human_review",
    }
    baseline = failure_report.get("baseline") or {}
    improved = failure_report.get("improved") or {}
    if baseline and improved:
        proposal["measured_delta"] = {
            "baseline_pass_rate": baseline.get("pass_rate"),
            "improved_pass_rate": improved.get("pass_rate"),
            "delta_pass_rate": failure_report.get("delta_pass_rate"),
            "live_agent_quality": failure_report.get("live_agent_quality") or "UNMEASURED",
        }
        b = float(baseline.get("pass_rate") or 0)
        i = float(improved.get("pass_rate") or 0)
        proposal["recommend_apply"] = bool(i > b)
    else:
        proposal["recommend_apply"] = False
        proposal["measured_delta"] = {"live_agent_quality": "UNMEASURED"}
    return proposal


def assert_improvement_cannot_rewrite_judges(work_root: Path) -> dict[str, Any]:
    """Software proof: agent workspace must not contain independent judge modules."""
    violations = assert_grader_outside_workspace(work_root)
    return {
        "ok": not violations,
        "violations": violations,
        "enforcement": (
            "Judges are loaded from the backend package, not the writable fixture tree. "
            "Filename absence is checked; directory naming alone is not the boundary."
        ),
    }


def write_proposal(path: Path, proposal: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, indent=2, default=str), encoding="utf-8")
    return path
