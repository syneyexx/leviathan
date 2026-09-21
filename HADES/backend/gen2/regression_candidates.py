"""Regression candidates from Flight Recorder / Eval Lab failures.

A candidate is a reviewable, redacted snapshot — not yet an independent holdout
eval. Promotion to a regression test requires explicit review.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from gen2.flight_recorder import redact_secrets
from runtime.effect_ledger import EffectLedger

CANDIDATE_SCHEMA_VERSION = "regression_candidate_v1"
REVIEW_PENDING = "pending_review"
REVIEW_APPROVED = "approved_regression"
REVIEW_REJECTED = "rejected"
SPLIT_DEVELOPMENT = "development"
SPLIT_HOLDOUT = "holdout"  # never auto-assign candidates here


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _minimize_personal(value: Any) -> Any:
    """Strip common personal fields while preserving structural fixtures."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("email", "phone", "ssn", "password", "token", "api_key", "secret")):
                out[key] = "[redacted_personal]"
            else:
                out[key] = _minimize_personal(item)
        return out
    if isinstance(value, list):
        return [_minimize_personal(item) for item in value]
    return value


def build_regression_candidate_from_flight(
    store: Any,
    run_id: str,
    *,
    expected_end_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reviewable regression candidate from a failed flight/eval run.

    Replay contract: use recorded tool results / sandboxed comparative replay only.
    Never re-execute external mutating tools.
    """
    from gen2.correlation_telemetry import export_reproducible_bundle

    events = store.list_run_events(run_id)
    if not events:
        return {
            "ok": False,
            "reason": "no_events",
            "run_id": run_id,
            "schema_version": CANDIDATE_SCHEMA_VERSION,
        }

    terminal = [
        e
        for e in events
        if str(e.get("event_type") or "").upper() in {"TERMINAL", "RUN_COMPLETED", "RUN_FAILED", "OUTCOME", "VERIFY", "VERIFICATION"}
    ]
    failed = False
    error_category = "unknown_failure"
    for event in reversed(terminal or events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        status = str(payload.get("status") or event.get("event_type") or "").lower()
        if status in {"failed", "error", "blocked"} or str(event.get("event_type") or "").upper() == "RUN_FAILED":
            failed = True
            error_category = str(payload.get("error_category") or payload.get("error") or status or "failed")
            break
        if payload.get("passed") is False or payload.get("ok") is False or payload.get("success") is False:
            failed = True
            error_category = str(payload.get("error_category") or "verification_failed")
            break

    if not failed:
        return {
            "ok": False,
            "reason": "run_not_failed",
            "run_id": run_id,
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "note": "Only failed runs become regression candidates.",
        }

    bundle = export_reproducible_bundle(store, run_id, include_events=True)
    redacted_bundle = redact_secrets(_minimize_personal(bundle))
    config_fp = _fingerprint(
        {
            "experiment": redacted_bundle.get("experiment") if isinstance(redacted_bundle, dict) else {},
            "run_meta": (redacted_bundle.get("run") if isinstance(redacted_bundle, dict) else {}) or {},
        }
    )
    missing_fixtures: list[str] = []
    recorded_tools = [
        redact_secrets(_minimize_personal(e))
        for e in events
        if "TOOL" in str(e.get("event_type") or "").upper()
    ]
    if not recorded_tools:
        missing_fixtures.append("recorded_tool_results")

    expected = expected_end_state or {
        "terminal_status": "completed",
        "verification_passed": True,
        "external_mutations": False,
    }
    candidate = {
        "ok": True,
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": f"regcand_{hashlib.sha256(run_id.encode()).hexdigest()[:12]}",
        "source_run_id": run_id,
        "created_at": _utc(),
        "review_status": REVIEW_PENDING,
        "split": SPLIT_DEVELOPMENT,
        "error_category": error_category,
        "config_fingerprint": config_fp,
        "inputs": {
            "goal": (redacted_bundle.get("run") or {}).get("goal") if isinstance(redacted_bundle, dict) else None,
            "event_count": len(events),
            "bundle_keys": sorted(redacted_bundle.keys()) if isinstance(redacted_bundle, dict) else [],
        },
        "recorded_tool_results": recorded_tools[:50],
        "missing_fixtures": missing_fixtures,
        "dependencies": {
            "replay_mode": "recorded_tools_or_isolated_fixture",
            "forbid_external_mutations": True,
        },
        "expected_end_state": expected,
        "reproducible_bundle": redacted_bundle,
        "promotion_gate": {
            "requires_review": True,
            "holdout_separate": True,
            "note": "Candidate is not a regression test until review_status=approved_regression.",
        },
    }
    # Persist alongside eval scores as a development artifact (not holdout).
    store.save_eval_run(
        suite="regression_candidates",
        mode="flight_failure_candidate",
        model_id=None,
        summary={
            "suite": "regression_candidates",
            "mode": "flight_failure_candidate",
            "not_model_quality": True,
            "model_invoked": False,
            "split": SPLIT_DEVELOPMENT,
            "review_status": REVIEW_PENDING,
            "source_run_id": run_id,
            "candidate_id": candidate["candidate_id"],
            "error_category": error_category,
            "total": 1,
            "passed": 0,
            "failed": 1,
            "pass_rate": 0.0,
        },
        scores=[
            {
                "scenario_id": candidate["candidate_id"],
                "title": f"Regression candidate from {run_id}",
                "passed": False,
                "task_type": "regression_candidate",
                "quality_layer": "software",
                "details": {
                    "review_status": REVIEW_PENDING,
                    "split": SPLIT_DEVELOPMENT,
                    "error_category": error_category,
                    "config_fingerprint": config_fp,
                },
                "model_invoked": False,
                "measurement_method": "flight_failure_candidate",
            }
        ],
        status="candidate_pending_review",
    )
    return candidate


def run_effect_ledger_contradiction_case(*, ledger_path: Path | str | None = None) -> dict[str, Any]:
    """Deterministic software regression case for contradictory effect metadata.

    Before the Phase-1 fix this returned SAFE_TO_RETRY; after the fix it must
    return REQUIRES_RECONCILIATION. No model call.
    """
    import tempfile

    own_tmp = None
    if ledger_path is None:
        own_tmp = tempfile.TemporaryDirectory()
        ledger_path = Path(own_tmp.name) / "effects.db"
    try:
        ledger = EffectLedger(ledger_path)
        rec = ledger.prepare(tool="plugin.mutate", arguments={"x": 1}, effect_class="plugin_side_effect")
        ledger.mark_failed(
            rec.effect_id,
            detail={"effect_applied": True, "failure_stage": "before_execute", "error": "boom"},
        )
        decision = ledger.classify_on_restart(rec.effect_id)
        passed = decision.get("class") == "REQUIRES_RECONCILIATION"
        return {
            "scenario_id": "effect_ledger_contradiction_applied_vs_early_stage",
            "title": "Contradictory effect metadata must not be SAFE_TO_RETRY",
            "passed": passed,
            "before_fix_expected_class": "SAFE_TO_RETRY",
            "after_fix_expected_class": "REQUIRES_RECONCILIATION",
            "observed_class": decision.get("class"),
            "reason": decision.get("reason"),
            "split": SPLIT_DEVELOPMENT,
            "review_status": REVIEW_APPROVED,
            "model_invoked": False,
            "quality_layer": "software",
            "measurement_method": "deterministic_effect_ledger",
        }
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()


def promote_candidate(candidate: dict[str, Any], *, approve: bool) -> dict[str, Any]:
    """Review gate — only approved candidates may enter the development regression suite."""
    updated = dict(candidate)
    updated["review_status"] = REVIEW_APPROVED if approve else REVIEW_REJECTED
    updated["reviewed_at"] = _utc()
    if approve:
        updated["split"] = SPLIT_DEVELOPMENT
        updated["promoted_to_regression"] = True
    else:
        updated["promoted_to_regression"] = False
    # Holdout remains untouched.
    updated["holdout_untouched"] = True
    return updated
