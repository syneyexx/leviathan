"""Stable Coding failure-reason / evidence contract for UI and jobs."""

from __future__ import annotations

from typing import Any


# Terminal blockers that must never look like verified implementation.
CODING_BLOCKERS = frozenset(
    {
        "no_change",
        "implementation_missing",
        "model_output_invalid",
        "model_unavailable",
        "model_timeout",
        "scope_not_found",
        "autonomy_blocked",
        "truncated_output",
        "provider_error",
        "stale_hash",
        "empty_edits",
    }
)

# Map blockers → job/run status (coherent across layers).
BLOCKER_TO_STATUS = {
    "no_change": "no_change",
    "implementation_missing": "implementation_missing",
    "model_output_invalid": "model_output_invalid",
    "model_unavailable": "model_unavailable",
    "model_timeout": "model_unavailable",
    "scope_not_found": "failed",
    "autonomy_blocked": "completed",  # analyze-only completion is valid, not verified impl
    "truncated_output": "model_output_invalid",
    "provider_error": "model_unavailable",
    "stale_hash": "failed",
    "empty_edits": "implementation_missing",
}

NL_REASON_COPY = {
    "model_output_invalid": "Model antwoordde, maar edit-JSON was ongeldig.",
    "truncated_output": "Modelresponse werd afgekapt.",
    "model_unavailable": "Geen bruikbaar Coding-model beschikbaar.",
    "model_timeout": "Model-aanroep time-out.",
    "autonomy_blocked": "Autonomy analyze_only blokkeerde wijzigingen.",
    "analyze_only": "Analyze-only: deze taak mag geen bestanden wijzigen.",
    "scope_not_found": "Geen relevante bestanden gevonden.",
    "no_change": "Geen bestanden gewijzigd; groene baseline telt niet als implementatie.",
    "implementation_missing": "Implementatie ontbreekt: geen geldige edits toegepast.",
    "empty_edits": "Model leverde een lege edits-lijst.",
    "stale_hash": "Edit base_hash was verouderd (stale write bescherming).",
    "provider_error": "Modelprovider gaf een fout.",
}


def human_reason_nl(blocker: str | None, *, fallback: str | None = None) -> str:
    key = str(blocker or "").strip()
    if key in NL_REASON_COPY:
        return NL_REASON_COPY[key]
    if fallback:
        return fallback
    return key or "Onbekende Coding-blokkade."


def build_coding_failure_evidence(
    *,
    selected_model: str | None = None,
    provider: str | None = None,
    model_requested: str | None = None,
    model_invocation_attempted: bool = False,
    model_invocation_succeeded: bool = False,
    structured_output_parse: dict[str, Any] | None = None,
    retry_used: bool = False,
    proposed_edit_count: int = 0,
    edit_validation_failures: list[str] | None = None,
    test_runner: str | None = None,
    repair_attempts: int = 0,
    terminal_blocker: str | None = None,
    response_excerpt: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocker = str(terminal_blocker or "").strip() or None
    parse = dict(structured_output_parse or {})
    excerpt = response_excerpt or parse.get("excerpt")
    if isinstance(excerpt, str) and len(excerpt) > 400:
        excerpt = excerpt[:397] + "..."
    evidence = {
        "schema": "coding_failure_evidence_v1",
        "selected_model": selected_model,
        "provider": provider,
        "model_requested": model_requested or selected_model,
        "model_invocation_attempted": bool(model_invocation_attempted),
        "model_invocation_succeeded": bool(model_invocation_succeeded),
        "structured_output_parse": {
            "kind": parse.get("kind"),
            "ok": parse.get("ok"),
            "error": parse.get("error"),
            "retry_recommended": parse.get("retry_recommended"),
        },
        "retry_used": bool(retry_used),
        "proposed_edit_count": int(proposed_edit_count),
        "edit_validation_failures": list(edit_validation_failures or [])[:20],
        "test_runner": test_runner,
        "repair_attempts": int(repair_attempts),
        "terminal_blocker": blocker,
        "human_reason_nl": human_reason_nl(blocker),
        "response_excerpt": excerpt,
        "extra": dict(extra or {}),
    }
    return evidence


def infer_blocker_from_propose_meta(meta: dict[str, Any] | None) -> str | None:
    m = meta or {}
    note = str(m.get("note") or "")
    parse_kind = str((m.get("parse") or {}).get("kind") or m.get("parse_kind") or "")
    if "lm_invoke_timeout" in note or parse_kind == "timeout":
        return "model_timeout"
    if "lm_invoke_cancelled" in note or parse_kind == "cancelled":
        return "cancelled"
    if "lm_invoke_failed" in note or parse_kind == "provider_error":
        return "provider_error"
    if parse_kind in {"malformed_response", "schema_invalid", "retry_failed"}:
        return "model_output_invalid"
    if parse_kind == "truncated":
        return "truncated_output"
    if parse_kind == "stale_hash":
        return "stale_hash"
    if parse_kind == "empty_edits":
        return "empty_edits"
    if m.get("method") == "none" and not m.get("model_invoked"):
        return "model_unavailable"
    if note.startswith("invalid_model_edits") or note.startswith("invalid_model_repair"):
        return "model_output_invalid"
    return None


def apply_mutation_no_change_guard(
    *,
    requires_mutation: bool,
    status: str,
    applied_edits: list[Any] | None,
    diff_text: str | None,
    propose_meta: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """For mutation tasks: green tests without material change ≠ verified."""
    if not requires_mutation:
        return status, None
    changed = bool(applied_edits) and len(applied_edits or []) > 0
    has_diff = bool((diff_text or "").strip())
    if status in {"verified", "completed"} and not (changed and has_diff):
        blocker = infer_blocker_from_propose_meta(propose_meta) or "no_change"
        mapped = BLOCKER_TO_STATUS.get(blocker, "implementation_missing")
        return mapped, blocker
    return status, None
