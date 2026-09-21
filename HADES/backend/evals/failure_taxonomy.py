"""Closed failure taxonomy for development-partner / coding evals.

Map free-text and route outcomes onto stable classes for aggregation.
Do not invent a cause when evidence is missing — use INSUFFICIENT_EVIDENCE.
"""

from __future__ import annotations

from typing import Any


FAILURE_CLASSES = (
    "TASK_MISUNDERSTOOD",
    "RELEVANT_CODE_NOT_FOUND",
    "INCORRECT_CHANGE",
    "INSUFFICIENT_TEST_COVERAGE",
    "TOOL_OR_INFRA_ERROR",
    "CONTEXT_PROBLEM",
    "BAD_RECOVERY_BEHAVIOR",
    "FALSE_SUCCESS_CLAIM",
    "MISSING_REQUIRED_OUTPUT",
    "SCOPE_VIOLATION",
    "PROVIDER_UNAVAILABLE",
    "JUDGE_ENV_ERROR",
    "INSUFFICIENT_EVIDENCE",
    "PASSED",
)

FAILURE_CLASS_VERSION = "dev_partner_failure_v1"


def classify_failure(
    *,
    judged: dict[str, Any] | None = None,
    route_out: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    infra_error: str | None = None,
) -> dict[str, Any]:
    judged = judged or {}
    route_out = route_out or {}
    delivery = delivery or {}

    if infra_error:
        return {
            "failure_class": "JUDGE_ENV_ERROR",
            "confidence": "high",
            "evidence": [infra_error],
            "version": FAILURE_CLASS_VERSION,
            "note": "Infrastructure/judge environment failure — not a task content FAIL/PASS.",
        }

    if judged.get("passed") is True and not judged.get("false_success"):
        return {
            "failure_class": "PASSED",
            "confidence": "high",
            "evidence": ["independent_judge_passed"],
            "version": FAILURE_CLASS_VERSION,
        }

    evidence: list[str] = []
    reason = str(judged.get("reason") or "")
    if judged.get("false_success") or judged.get("claimed_without_evidence"):
        return {
            "failure_class": "FALSE_SUCCESS_CLAIM",
            "confidence": "high",
            "evidence": [reason or "claimed_success_without_judge_pass"],
            "version": FAILURE_CLASS_VERSION,
        }

    status = str(route_out.get("status") or route_out.get("measurement_status") or "").lower()
    if status in {"unmeasured", "provider_unavailable"} or route_out.get("provider_unavailable"):
        return {
            "failure_class": "PROVIDER_UNAVAILABLE",
            "confidence": "high",
            "evidence": [status or "provider_unavailable"],
            "version": FAILURE_CLASS_VERSION,
            "note": "Unavailable provider is not counted as successful evaluation.",
        }

    if reason in {
        "missing_regression_report",
        "missing_review_report",
        "incomplete_report_fields",
        "no_findings",
        "missing_evidence_files",
    } or (delivery and delivery.get("complete") is False and delivery.get("missing_fields")):
        missing = delivery.get("missing_fields") if delivery else None
        evidence.append(reason or "missing_required_output")
        if missing:
            evidence.append(f"missing_fields:{missing}")
        return {
            "failure_class": "MISSING_REQUIRED_OUTPUT",
            "confidence": "high",
            "evidence": evidence,
            "version": FAILURE_CLASS_VERSION,
        }

    if reason in {"ungrounded_or_fabricated_review", "admitted_fabricated_issues"} or judged.get(
        "false_findings_only"
    ):
        return {
            "failure_class": "INCORRECT_CHANGE",
            "confidence": "medium",
            "evidence": [reason or "ungrounded_review"],
            "version": FAILURE_CLASS_VERSION,
            "note": "Review findings were ungrounded; not auto-scored as good.",
        }

    err = str(route_out.get("error") or route_out.get("error_category") or "").lower()
    coding = route_out.get("coding") if isinstance(route_out.get("coding"), dict) else {}
    explore = coding.get("explore") if isinstance(coding.get("explore"), dict) else {}

    if "timeout" in err or "cancelled" in err:
        return {
            "failure_class": "TOOL_OR_INFRA_ERROR",
            "confidence": "medium",
            "evidence": [err],
            "version": FAILURE_CLASS_VERSION,
        }
    if "scope" in err or route_out.get("scope_violation"):
        return {
            "failure_class": "SCOPE_VIOLATION",
            "confidence": "high",
            "evidence": [err or "scope_violation"],
            "version": FAILURE_CLASS_VERSION,
        }
    if explore.get("hit_count") == 0 or "not found" in err or "no matches" in err:
        return {
            "failure_class": "RELEVANT_CODE_NOT_FOUND",
            "confidence": "low",
            "evidence": [err or "explore_empty"],
            "version": FAILURE_CLASS_VERSION,
        }
    if "repair" in err and "same" in err:
        return {
            "failure_class": "BAD_RECOVERY_BEHAVIOR",
            "confidence": "medium",
            "evidence": [err],
            "version": FAILURE_CLASS_VERSION,
        }
    if reason in {"incorrect", "ungrounded_or_weak_report"} or judged.get("passed") is False:
        # Prefer INCORRECT_CHANGE when a diff existed; else insufficient evidence.
        if route_out.get("diff_text") or route_out.get("patch_text") or (
            isinstance(route_out.get("applied_edits"), list) and route_out.get("applied_edits")
        ):
            return {
                "failure_class": "INCORRECT_CHANGE",
                "confidence": "medium",
                "evidence": [reason or "judge_failed_after_edit"],
                "version": FAILURE_CLASS_VERSION,
            }
        return {
            "failure_class": "INSUFFICIENT_EVIDENCE",
            "confidence": "low",
            "evidence": [reason or "failed_without_clear_cause"],
            "version": FAILURE_CLASS_VERSION,
            "note": "Cause not forced; evidence insufficient for a confident class.",
        }

    return {
        "failure_class": "INSUFFICIENT_EVIDENCE",
        "confidence": "low",
        "evidence": ["no_decisive_signal"],
        "version": FAILURE_CLASS_VERSION,
    }


def aggregate_failure_classes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {c: 0 for c in FAILURE_CLASSES}
    for row in rows:
        cls = str(row.get("failure_class") or "INSUFFICIENT_EVIDENCE")
        if cls not in counts:
            counts[cls] = 0
        counts[cls] += 1
    ranked = sorted(
        ((k, v) for k, v in counts.items() if v and k != "PASSED"),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return {
        "version": FAILURE_CLASS_VERSION,
        "counts": counts,
        "recurring": [{"failure_class": k, "frequency": v} for k, v in ranked],
        "top_bottleneck": ranked[0][0] if ranked else None,
    }
