"""Independent judges for ``dev_partner_v1``.

Graders stay outside agent writeable workspaces. They score observable
artifacts / tests — never agent self-report alone. Fabricated review findings
do not auto-pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evals.holdout_judges import HOLDOUT_JUDGE_VERSION, judge_final_from_execution, run_task_tests

DEV_PARTNER_JUDGE_VERSION = "dev_partner_judge_v1"

# Keywords that must appear in grounded findings for known review fixtures.
_REVIEW_REQUIRED_SIGNALS: dict[str, tuple[str, ...]] = {
    "DP10": ("sql", "inject", "concat", "string +", "user input", "parameter"),
    "DP11": ("path", "traversal", "../", "absolute", "open(", "arbitrary"),
    "DP12": ("password", "secret", "log", "print", "credential"),
    "DP20": ("lock", "race", "concurren", "thread", "synchron"),
}

_REGRESSION_REQUIRED_SIGNALS: dict[str, tuple[str, ...]] = {
    "DP08": ("none", "null", "guard", "attribute", "name"),
    "DP09": ("safe", "fast", "default", "mode"),
    "DP18": ("legacy", "modern", "import", "charge", "payments"),
    "DP19": ("timeout", "30", "1", "second"),
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _short_id(task: dict[str, Any]) -> str:
    return str(task.get("short_id") or (task.get("id") or "").split("_")[0])


def _text_blob(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def judge_regression_report(task: dict[str, Any], work_root: Path) -> dict[str, Any]:
    root = Path(work_root)
    report = _load_json(root / "artifacts" / "regression_report.json")
    if not report:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "missing_regression_report",
            "evidence_backed": False,
        }
    root_cause = str(report.get("root_cause") or "").strip()
    evidence_files = report.get("evidence_files")
    recommended = str(report.get("recommended_fix") or "").strip()
    if not root_cause or not recommended:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "incomplete_report_fields",
            "evidence_backed": False,
            "evidence": report,
        }
    if not isinstance(evidence_files, list) or not evidence_files:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "missing_evidence_files",
            "evidence_backed": False,
            "evidence": report,
        }
    # Evidence files must exist in workspace (grounding).
    grounded_files = 0
    for item in evidence_files:
        rel = str(item).replace("\\", "/").lstrip("./")
        if (root / rel).is_file():
            grounded_files += 1
    blob = _text_blob(root_cause, recommended, report.get("suspected_commit_note"))
    signals = _REGRESSION_REQUIRED_SIGNALS.get(_short_id(task), ())
    hits = sum(1 for s in signals if s in blob)
    passed = grounded_files >= 1 and hits >= 1 and len(root_cause) >= 12
    return {
        "task_id": task.get("id"),
        "judge_version": DEV_PARTNER_JUDGE_VERSION,
        "verdict": "correct" if passed else "incorrect",
        "passed": passed,
        "evidence_backed": passed,
        "reason": "grounded_regression_report" if passed else "ungrounded_or_weak_report",
        "evidence": {
            "report": report,
            "grounded_files": grounded_files,
            "signal_hits": hits,
            "required_signals": list(signals),
        },
    }


def judge_review_report(task: dict[str, Any], work_root: Path) -> dict[str, Any]:
    root = Path(work_root)
    report = _load_json(root / "artifacts" / "review_report.json")
    if not report:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "missing_review_report",
            "evidence_backed": False,
        }
    if report.get("fabricated_issues") is True:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "admitted_fabricated_issues",
            "evidence_backed": False,
            "evidence": report,
        }
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings:
        return {
            "task_id": task.get("id"),
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
            "verdict": "incorrect",
            "passed": False,
            "reason": "no_findings",
            "evidence_backed": False,
            "evidence": report,
        }
    patch = ""
    patch_path = root / "PATCH.diff"
    if patch_path.is_file():
        patch = patch_path.read_text(encoding="utf-8", errors="replace").lower()
    signals = _REVIEW_REQUIRED_SIGNALS.get(_short_id(task), ())
    grounded = 0
    invented_style_only = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        text = _text_blob(finding.get("severity"), finding.get("evidence"), finding.get("severity"))
        evidence = str(finding.get("evidence") or "")
        # Finding must reference patch content or concrete code token.
        patch_grounded = bool(evidence) and (
            evidence.lower() in patch or any(tok in patch for tok in re.findall(r"[a-z_]{4,}", evidence.lower())[:6])
        )
        signal_hit = any(s in text for s in signals) if signals else True
        if patch_grounded and signal_hit:
            grounded += 1
        elif any(k in text for k in ("whitespace", "rename variable", "prefer const", "nit:")):
            invented_style_only += 1
    # Must have ≥1 grounded finding aligned with the known defect class.
    # Pure style-nit reviews without the security/concurrency signal fail.
    passed = grounded >= 1 and invented_style_only < grounded + 2
    return {
        "task_id": task.get("id"),
        "judge_version": DEV_PARTNER_JUDGE_VERSION,
        "verdict": "correct" if passed else "incorrect",
        "passed": passed,
        "evidence_backed": passed,
        "reason": "grounded_review" if passed else "ungrounded_or_fabricated_review",
        "false_findings_only": grounded == 0,
        "evidence": {
            "findings_count": len(findings),
            "grounded": grounded,
            "style_nits": invented_style_only,
            "required_signals": list(signals),
        },
    }


def judge_dev_partner_task(
    task: dict[str, Any],
    work_root: Path,
    *,
    baseline_failed: bool | None = None,
    agent_status: str | None = None,
    agent_claimed_success: bool = False,
) -> dict[str, Any]:
    judge = task.get("judge") or "execution_tests"
    if judge == "execution_tests":
        if baseline_failed is None:
            baseline_failed = True
        result = judge_final_from_execution(
            task, work_root, baseline_failed=bool(baseline_failed), agent_status=agent_status
        )
        result["judge_version"] = f"{HOLDOUT_JUDGE_VERSION}+{DEV_PARTNER_JUDGE_VERSION}"
        result["dataset_version"] = task.get("dataset_version")
        if agent_claimed_success and not result.get("passed"):
            result["claimed_without_evidence"] = True
            result["false_success"] = True
        else:
            result["false_success"] = bool(result.get("claimed_without_evidence"))
        return result
    if judge == "regression_report":
        result = judge_regression_report(task, work_root)
    elif judge == "review_report":
        result = judge_review_report(task, work_root)
    else:
        result = {
            "task_id": task.get("id"),
            "passed": False,
            "verdict": "invalid",
            "reason": f"unknown_judge:{judge}",
            "judge_version": DEV_PARTNER_JUDGE_VERSION,
        }
    if agent_claimed_success and not result.get("passed"):
        result["claimed_without_evidence"] = True
        result["false_success"] = True
    else:
        result["false_success"] = False
    result["agent_status"] = agent_status
    result["dataset_version"] = task.get("dataset_version")
    return result


def baseline_must_be_red_or_report(task: dict[str, Any], work_root: Path) -> dict[str, Any]:
    """Honesty gate: bugfix/feature fixtures start failing; report tasks start without report."""
    judge = task.get("judge")
    if judge == "execution_tests":
        baseline = run_task_tests(Path(work_root), list(task.get("test_args") or []))
        return {
            "passed": baseline["passed"],
            "honest": baseline["passed"] is False,
            "kind": "tests_red",
            "evidence": baseline,
        }
    report_name = (
        "regression_report.json" if judge == "regression_report" else "review_report.json"
    )
    path = Path(work_root) / "artifacts" / report_name
    exists = path.is_file() and path.stat().st_size > 2
    return {
        "passed": exists,
        "honest": not exists,
        "kind": "report_absent",
        "evidence": {"path": str(path), "exists": exists},
    }


def assert_grader_outside_workspace(work_root: Path) -> list[str]:
    violations: list[str] = []
    forbidden = {
        "dev_partner_judges.py",
        "holdout_judges.py",
        "agent_judges.py",
        "agent_eval.py",
        "dev_partner_harness.py",
        "release_thresholds.py",
    }
    for path in Path(work_root).rglob("*.py"):
        if path.name in forbidden:
            violations.append(f"grader_in_workspace:{path}")
    return violations
