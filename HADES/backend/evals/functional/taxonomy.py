"""Campaign failure taxonomy — extends, does not replace, existing taxonomies.

Primary source for coding/dev-partner remains ``evals.failure_taxonomy``.
Flight Recorder continues to use ``gen2.flight_recorder.classify_failure_taxonomy``.

This module adds campaign-wide primary classes aligned with the hardening brief,
plus a mapping into the legacy closed set for aggregation continuity.
"""

from __future__ import annotations

from typing import Any

from evals.failure_taxonomy import FAILURE_CLASS_VERSION as LEGACY_FAILURE_VERSION

CAMPAIGN_TAXONOMY_VERSION = "functional_campaign_failure_v1"

CAMPAIGN_FAILURE_CLASSES = (
    "intent_error",
    "wrong_route",
    "context_failure",
    "retrieval_failure",
    "model_reasoning_failure",
    "tool_selection_failure",
    "tool_argument_failure",
    "tool_runtime_failure",
    "verification_failure",
    "sandbox_failure",
    "timeout",
    "cancellation_failure",
    "coding_edit_failure",
    "test_failure",
    "hallucinated_success",
    "evidence_failure",
    "false_execution",  # severe: explained/negated request treated as execute
    "provider_unavailable",
    "insufficient_evidence",
    "passed",
    "unknown",
)

# Map campaign primary class → legacy coding/dev-partner class where sensible.
_TO_LEGACY: dict[str, str] = {
    "intent_error": "TASK_MISUNDERSTOOD",
    "wrong_route": "TASK_MISUNDERSTOOD",
    "context_failure": "CONTEXT_PROBLEM",
    "retrieval_failure": "RELEVANT_CODE_NOT_FOUND",
    "model_reasoning_failure": "INCORRECT_CHANGE",
    "tool_selection_failure": "TOOL_OR_INFRA_ERROR",
    "tool_argument_failure": "TOOL_OR_INFRA_ERROR",
    "tool_runtime_failure": "TOOL_OR_INFRA_ERROR",
    "verification_failure": "INSUFFICIENT_EVIDENCE",
    "sandbox_failure": "TOOL_OR_INFRA_ERROR",
    "timeout": "TOOL_OR_INFRA_ERROR",
    "cancellation_failure": "BAD_RECOVERY_BEHAVIOR",
    "coding_edit_failure": "INCORRECT_CHANGE",
    "test_failure": "INSUFFICIENT_TEST_COVERAGE",
    "hallucinated_success": "FALSE_SUCCESS_CLAIM",
    "evidence_failure": "INSUFFICIENT_EVIDENCE",
    "false_execution": "SCOPE_VIOLATION",
    "provider_unavailable": "PROVIDER_UNAVAILABLE",
    "insufficient_evidence": "INSUFFICIENT_EVIDENCE",
    "passed": "PASSED",
    "unknown": "INSUFFICIENT_EVIDENCE",
}


def map_to_legacy_failure_class(campaign_class: str) -> str:
    return _TO_LEGACY.get(campaign_class, "INSUFFICIENT_EVIDENCE")


def classify_campaign_failure(
    *,
    outcome: str | None = None,
    family: str | None = None,
    signals: dict[str, Any] | None = None,
    infra_error: str | None = None,
) -> dict[str, Any]:
    """Classify one failed/blocked attempt into a primary campaign class.

    Never invent a confident cause when evidence is missing.
    """
    signals = signals or {}
    if outcome == "success":
        return {
            "failure_class": "passed",
            "contributing": [],
            "confidence": "high",
            "version": CAMPAIGN_TAXONOMY_VERSION,
            "legacy_class": "PASSED",
            "legacy_version": LEGACY_FAILURE_VERSION,
        }

    if infra_error or signals.get("provider_unavailable") or outcome == "blocked":
        cls = "provider_unavailable"
        return {
            "failure_class": cls,
            "contributing": [],
            "confidence": "high",
            "version": CAMPAIGN_TAXONOMY_VERSION,
            "legacy_class": map_to_legacy_failure_class(cls),
            "legacy_version": LEGACY_FAILURE_VERSION,
            "note": str(infra_error or "blocked_or_unavailable"),
        }

    # Explicit safety / intent signals first (weighted severity).
    if signals.get("false_execution"):
        return _pack("false_execution", contributing=list(signals.get("contributing") or []), confidence="high")
    if signals.get("hallucinated_success") or signals.get("false_success"):
        return _pack("hallucinated_success", contributing=[], confidence="high")

    err = str(signals.get("error") or signals.get("error_category") or "").lower()
    if "timeout" in err or signals.get("timeout"):
        return _pack("timeout", confidence="medium")
    if "cancel" in err or signals.get("cancellation_failure"):
        return _pack("cancellation_failure", confidence="medium")

    family = (family or "").lower()
    if signals.get("intent_mismatch") or family in {"intent", "nlu", "routing"}:
        if signals.get("wrong_route"):
            return _pack("wrong_route", confidence="medium")
        return _pack("intent_error", confidence="medium")
    if family in {"retrieval", "rag"} or signals.get("retrieval_miss"):
        return _pack("retrieval_failure", confidence="medium")
    if family in {"coding"} or signals.get("edit_failed"):
        if signals.get("tests_failed"):
            return _pack("test_failure", contributing=["coding_edit_failure"], confidence="medium")
        return _pack("coding_edit_failure", confidence="medium")
    if family in {"tool", "tool_use"}:
        if signals.get("bad_args"):
            return _pack("tool_argument_failure", confidence="medium")
        if signals.get("wrong_tool"):
            return _pack("tool_selection_failure", confidence="medium")
        return _pack("tool_runtime_failure", confidence="low")
    if family in {"verification", "critic"} or signals.get("verification_failed"):
        if signals.get("evidence_invalid"):
            return _pack("evidence_failure", confidence="high")
        return _pack("verification_failure", confidence="medium")
    if family in {"sandbox", "isolation"}:
        return _pack("sandbox_failure", confidence="medium")
    if signals.get("context_failure"):
        return _pack("context_failure", confidence="low")

    return _pack("insufficient_evidence", confidence="low", note="no_decisive_signal")


def _pack(
    failure_class: str,
    *,
    contributing: list[str] | None = None,
    confidence: str = "low",
    note: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "failure_class": failure_class if failure_class in CAMPAIGN_FAILURE_CLASSES else "unknown",
        "contributing": list(contributing or []),
        "confidence": confidence,
        "version": CAMPAIGN_TAXONOMY_VERSION,
        "legacy_class": map_to_legacy_failure_class(failure_class),
        "legacy_version": LEGACY_FAILURE_VERSION,
    }
    if note:
        out["note"] = note
    return out


def aggregate_campaign_failures(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {c: 0 for c in CAMPAIGN_FAILURE_CLASSES}
    for row in rows:
        cls = str(row.get("failure_class") or "insufficient_evidence")
        if cls not in counts:
            counts[cls] = 0
        counts[cls] += 1
    ranked = sorted(
        ((k, v) for k, v in counts.items() if v and k != "passed"),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return {
        "version": CAMPAIGN_TAXONOMY_VERSION,
        "counts": counts,
        "recurring": [{"failure_class": k, "frequency": v} for k, v in ranked],
        "top_bottleneck": ranked[0][0] if ranked else None,
        "sample_size": len(rows),
    }
