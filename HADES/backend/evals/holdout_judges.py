"""Holdout judges for generalization evals.

Judges are separated from development examples and from fixture factories.
They score only via observable execution evidence — they do not embed patch
oracles the agent could copy. Agents must not rewrite this module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from evals.generalization_dataset import (
    GENERALIZATION_DATASET_VERSION,
    GENERALIZATION_TASKS,
    list_holdout_tasks,
)


HOLDOUT_JUDGE_VERSION = "holdout_judge_v1"


def run_task_tests(root: Path, test_args: list[str], *, timeout: int = 60) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "unittest", *test_args]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout)
    return {
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


def judge_baseline_must_fail(task: dict[str, Any], *, variant: str = "holdout") -> dict[str, Any]:
    """Honesty: holdout fixture must start failing before any agent work."""
    root = task["fixture"](variant=variant)
    baseline = run_task_tests(root, list(task.get("test_args") or []))
    return {
        "task_id": task["id"],
        "judge_version": HOLDOUT_JUDGE_VERSION,
        "dataset_version": GENERALIZATION_DATASET_VERSION,
        "split": task.get("split"),
        "work_root": str(root),
        "baseline_passed": baseline["passed"],
        "honest": baseline["passed"] is False,
        "verdict": "honest_red" if not baseline["passed"] else "invalid_fixture_green",
        "evidence": {
            "stdout_tail": baseline["stdout"][-500:],
            "stderr_tail": baseline["stderr"][-500:],
        },
    }


def judge_final_from_execution(
    task: dict[str, Any],
    work_root: Path,
    *,
    baseline_failed: bool,
    agent_status: str | None = None,
) -> dict[str, Any]:
    """Score a candidate workspace by re-running tests — never by agent self-report alone."""
    final = run_task_tests(Path(work_root), list(task.get("test_args") or []))
    evidence_backed = bool(baseline_failed and final["passed"])
    # Agent status is advisory only; judge does not trust it without tests.
    claimed = agent_status == "verified"
    return {
        "task_id": task["id"],
        "judge_version": HOLDOUT_JUDGE_VERSION,
        "dataset_version": GENERALIZATION_DATASET_VERSION,
        "split": task.get("split"),
        "verdict": "correct" if evidence_backed else ("incorrect" if baseline_failed else "invalid"),
        "passed": evidence_backed,
        "evidence_backed": evidence_backed,
        "claimed_without_evidence": bool(claimed and not evidence_backed),
        "agent_status": agent_status,
        "evidence": {
            "baseline_failed": baseline_failed,
            "final_tests_passed": final["passed"],
            "final_returncode": final["returncode"],
            "stdout_tail": final["stdout"][-500:],
            "stderr_tail": final["stderr"][-500:],
        },
    }


def run_holdout_honesty_suite(*, limit: int | None = None) -> dict[str, Any]:
    tasks = list_holdout_tasks()[: limit or None]
    rows = [judge_baseline_must_fail(t) for t in tasks]
    honest = sum(1 for r in rows if r["honest"])
    return {
        "suite": "generalization_holdout_honesty",
        "judge_version": HOLDOUT_JUDGE_VERSION,
        "dataset_version": GENERALIZATION_DATASET_VERSION,
        "total": len(rows),
        "honest": honest,
        "all_fixtures_honest": honest == len(rows) and len(rows) > 0,
        "task_ids": [r["task_id"] for r in rows],
        "scores": rows,
        "note": (
            "Holdout honesty only. Development examples are excluded. "
            "Does not claim agent quality PASS."
        ),
    }


def assert_oracle_not_in_agent_paths(agent_source: str) -> list[str]:
    """Return violations if coding_agent embeds holdout task oracles."""
    violations: list[str] = []
    forbidden_snippets = [
        "G01_py_sort",
        "G05_js_multiply",
        "G19_flow_csrf",
        "by_score([{'score': 1}",
        "HADES_REGION",
        "payments.modern",
        "holdout_judge_v1",
        "generalization_v1 oracle",
    ]
    for snip in forbidden_snippets:
        if snip in agent_source:
            violations.append(f"agent_embeds_holdout_marker:{snip}")
    # E01–E08 labels must not remain as production rewrite recipes.
    for snip in ("E01: dumps", "E08: hidden", "return str(obj)", "helper.total"):
        # 'return str(obj)' is too generic; skip. Keep explicit E0x recipe markers.
        if snip.startswith("E0") and snip in agent_source:
            violations.append(f"agent_embeds_known_fixture_recipe:{snip}")
    return violations
