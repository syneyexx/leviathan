"""Flight Recorder — append-only run events, compare, inspect-only replay.

Two distinct modes:

1. ``replay_plan`` — inspection/simulation manifest only. Never re-invokes
   models and never re-executes write/side-effect tools unless explicitly
   permitted — and even then only *simulates* (no live side effects).
   Do not present this as a newly executed run.

2. ``comparative_replay`` — sandboxed re-execution of recorded inputs against
   a different local model or implementation. Immutable inputs/source versions.
   Model calls may be newly executed; tool results reuse the recording by
   default (fixtures / isolated adapters). Side-effecting tools are NOT
   re-executed unless an explicit isolated adapter is supplied. Original
   approvals are never reused as permission for new effects. Original and
   new runs are stored separately with a parent relation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable

from gen2.store import Gen2Store, new_id, utc_now


RecordFn = Callable[..., dict[str, Any]]
ChatFn = Callable[[dict[str, Any]], dict[str, Any]]
ToolAdapterFn = Callable[[dict[str, Any]], dict[str, Any]]

# E2 canonical vocabulary (plus durable lifecycle bookkeeping types).
CANONICAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "MODEL_IO",
        "CONTEXT_SELECTED",
        "PLAN",
        "TOOL",
        "APPROVAL",
        "REPLAN",
        "VERIFY",
        "ARTIFACT",
        "TERMINAL",
        "RUN_CREATED",
        "REPLAY_MANIFEST",
        "PARENT_RELATION",
        "COMPARATIVE_REPLAY_SUMMARY",
        "SIDE_EFFECT_BLOCKED",
    }
)

EVENT_TYPE_ALIASES: dict[str, str] = {
    "MODEL_REQUEST": "MODEL_IO",
    "MODEL_RESPONSE": "MODEL_IO",
    "model_request": "MODEL_IO",
    "model_response": "MODEL_IO",
    "MODEL_IO": "MODEL_IO",
    "CONTEXT_SELECTED": "CONTEXT_SELECTED",
    "context_selected": "CONTEXT_SELECTED",
    "source_acquired": "CONTEXT_SELECTED",
    "PLAN": "PLAN",
    "plan": "PLAN",
    "PLAN_CREATED": "PLAN",
    "TOOL": "TOOL",
    "TOOL_RESULT": "TOOL",
    "TOOL_STARTED": "TOOL",
    "TOOL_CALL": "TOOL",
    "tool_status": "TOOL",
    "APPROVAL": "APPROVAL",
    "approval": "APPROVAL",
    "GATE_DECISION": "APPROVAL",
    "REPLAN": "REPLAN",
    "replan": "REPLAN",
    "VERIFY": "VERIFY",
    "VERIFICATION": "VERIFY",
    "verification": "VERIFY",
    "ARTIFACT": "ARTIFACT",
    "ARTIFACT_CREATED": "ARTIFACT",
    "artifact": "ARTIFACT",
    "TERMINAL": "TERMINAL",
    "RUN_COMPLETED": "TERMINAL",
    "RUN_FAILED": "TERMINAL",
    "OUTCOME": "TERMINAL",
    "ACCEPTANCE": "TERMINAL",
    "outcome": "TERMINAL",
}

FAILURE_TAXONOMY = (
    "permission",
    "schema",
    "tool",
    "model",
    "verification",
    "budget",
    "unknown",
)


def normalize_event_type(event_type: str) -> tuple[str, str | None]:
    """Return (canonical_type, original_alias_or_None)."""
    raw = str(event_type or "").strip()
    if not raw:
        return "UNKNOWN", None
    if raw in EVENT_TYPE_ALIASES:
        canonical = EVENT_TYPE_ALIASES[raw]
        return canonical, (None if raw == canonical else raw)
    upper = raw.upper()
    if upper in EVENT_TYPE_ALIASES:
        canonical = EVENT_TYPE_ALIASES[upper]
        return canonical, (None if raw == canonical else raw)
    if raw in CANONICAL_EVENT_TYPES:
        return raw, None
    return raw, None


def classify_failure_taxonomy(event: dict[str, Any]) -> str:
    """Classify a run event into a coarse failure taxonomy (E8)."""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    et = str(event.get("event_type") or "")
    canonical, _alias = normalize_event_type(et)
    text = " ".join(
        str(x)
        for x in (
            et,
            canonical,
            payload.get("error"),
            payload.get("reason"),
            payload.get("status"),
            payload.get("failure"),
            payload.get("code"),
            payload.get("failure_class"),
        )
    ).lower()

    explicit = str(payload.get("failure_taxonomy") or payload.get("taxonomy") or "").lower()
    if explicit in FAILURE_TAXONOMY:
        return explicit

    if any(k in text for k in ("permission", "denied", "unauthorized", "approval", "forbidden", "bypass")):
        return "permission"
    if any(k in text for k in ("schema", "validation", "json_invalid", "type_error", "contract")):
        return "schema"
    if canonical == "TOOL" or any(k in text for k in ("tool_", "tool error", "tool_failed", "exfil")):
        if payload.get("ok") is False or payload.get("passed") is False or "fail" in text or "error" in text:
            return "tool"
    if canonical == "MODEL_IO" or any(k in text for k in ("model_", "lm studio", "timeout", "empty_response")):
        if payload.get("ok") is False or payload.get("error") or "fail" in text:
            return "model"
    if canonical == "VERIFY" or any(k in text for k in ("verif", "evidence", "hallucin", "acceptance")):
        if payload.get("passed") is False or payload.get("ok") is False or "fail" in text:
            return "verification"
    if any(k in text for k in ("budget", "quota", "token_limit", "rate_limit", "exhausted")):
        return "budget"

    # Terminal failures without a clearer class.
    if canonical == "TERMINAL" and (
        payload.get("ok") is False
        or str(payload.get("status") or "").lower() in {"failed", "error", "blocked"}
        or "fail" in text
    ):
        return "unknown"
    if payload.get("ok") is False or payload.get("passed") is False or payload.get("error"):
        return "unknown"
    return "unknown"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


_SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "credential",
)
# Metric / budget field names that contain "token" but are not secrets.
_SECRET_KEY_ALLOWLIST = frozenset(
    {
        "tokens",
        "total_tokens",
        "token_count",
        "max_tokens",
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "context_tokens",
        "compiler_max_tokens",
        "token_usage",
        "token_kind",
        "token_source",
        "token_note",
        "tokens_missing",
    }
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|bearer)\s*[=:]\s*([^\s,;]+)"
)


def redact_secrets(value: Any) -> Any:
    """Redact likely secrets from recorder payloads/text (never store raw secrets)."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if key_l not in _SECRET_KEY_ALLOWLIST and any(frag in key_l for frag in _SECRET_KEY_FRAGMENTS):
                out[key] = "***REDACTED***"
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub(r"\1=***REDACTED***", value)
    return value


def _is_side_effect_event(event_type: str) -> bool:
    canonical, _ = normalize_event_type(event_type)
    et = (event_type or "").upper()
    if canonical in {"TOOL", "ARTIFACT"}:
        return True
    if event_type == "tool_status":
        return True
    if "TOOL" in et:
        return True
    return any(marker in et for marker in ("WRITE", "NETWORK", "SUBPROCESS", "ARTIFACT_CREATED"))


def _is_model_event(event_type: str) -> bool:
    canonical, _ = normalize_event_type(event_type)
    return canonical == "MODEL_IO" or event_type in {
        "MODEL_REQUEST",
        "model_request",
        "MODEL_RESPONSE",
        "model_response",
        "MODEL_IO",
    }


def _is_model_request(event_type: str, payload: dict[str, Any] | None = None) -> bool:
    """Distinguish request vs response after MODEL_* → MODEL_IO normalization."""
    if event_type in {"MODEL_REQUEST", "model_request"}:
        return True
    if event_type in {"MODEL_RESPONSE", "model_response"}:
        return False
    body = payload if isinstance(payload, dict) else {}
    alias = str(body.get("_event_type_alias") or "")
    if alias in {"MODEL_RESPONSE", "model_response"}:
        return False
    if alias in {"MODEL_REQUEST", "model_request"}:
        return True
    io_kind = str(body.get("io_kind") or body.get("kind") or "").lower()
    if io_kind in {"response", "model_response"}:
        return False
    if event_type == "MODEL_IO" or normalize_event_type(event_type)[0] == "MODEL_IO":
        # Bare MODEL_IO defaults to request-capable for comparative replay.
        return io_kind in {"", "request", "model_request", "io"}
    return False

def _duration_ms(event: dict[str, Any]) -> float | None:
    payload = event.get("payload") or {}
    if isinstance(payload, dict):
        diag = payload.get("_diagnostics") or {}
        if isinstance(diag, dict) and diag.get("duration_ms") is not None:
            try:
                return float(diag["duration_ms"])
            except (TypeError, ValueError):
                return None
        if payload.get("duration_ms") is not None:
            try:
                return float(payload["duration_ms"])
            except (TypeError, ValueError):
                return None
    return None


def _token_count(event: dict[str, Any]) -> int | None:
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    for key in ("tokens", "total_tokens", "token_count"):
        if payload.get(key) is not None:
            try:
                return int(payload[key])
            except (TypeError, ValueError):
                return None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        for key in ("total_tokens", "tokens"):
            if usage.get(key) is not None:
                try:
                    return int(usage[key])
                except (TypeError, ValueError):
                    return None
    return None


def record(
    store: Gen2Store,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    model_id: str | None = None,
    component: str | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    parent_event_id: str | None = None,
    severity: str | None = None,
    duration_ms: float | None = None,
    correlation_id: str | None = None,
    config_fingerprint: str | None = None,
    model_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = redact_secrets(dict(payload or {}))
    canonical, alias = normalize_event_type(event_type)
    # Persist canonical vocabulary on write; keep caller alias in payload for audit.
    if alias:
        body.setdefault("_event_type_alias", alias)
    elif str(event_type or "").strip() and str(event_type).strip() != canonical:
        body.setdefault("_event_type_alias", str(event_type).strip())
    body.setdefault("_canonical_event_type", canonical)
    taxonomy = classify_failure_taxonomy({"event_type": canonical, "payload": body})
    # Only attach taxonomy when the event looks like a failure / error outcome.
    looks_failed = bool(
        body.get("error")
        or body.get("ok") is False
        or body.get("passed") is False
        or str(body.get("status") or "").lower() in {"failed", "error", "blocked"}
        or canonical == "SIDE_EFFECT_BLOCKED"
    )
    if looks_failed:
        body.setdefault("failure_taxonomy", taxonomy)
    # E3: content hashes + config fingerprints + model-id snapshots on every write.
    payload_for_hash = {k: v for k, v in body.items() if not str(k).startswith("_")}
    payload_hash = _sha(json.dumps(payload_for_hash, sort_keys=True, default=str))
    snap = dict(model_snapshot or {})
    if model_id and "model_id" not in snap:
        snap["model_id"] = model_id
    if snap:
        snap.setdefault("snapshot_kind", "model_id_record")
        snap.setdefault("recorded_at", utc_now())
    diagnostics = {
        k: v
        for k, v in {
            "severity": severity,
            "duration_ms": duration_ms,
            "correlation_id": correlation_id,
            "component": component,
            "recorded_at": utc_now(),
            "config_fingerprint": config_fingerprint,
            "payload_hash": payload_hash,
            "model_snapshot": snap or None,
            "failure_taxonomy": body.get("failure_taxonomy") if looks_failed else None,
            "canonical_event_type": canonical,
        }.items()
        if v is not None
    }
    if diagnostics:
        existing = dict(body.get("_diagnostics") or {}) if isinstance(body.get("_diagnostics"), dict) else {}
        body["_diagnostics"] = {**existing, **diagnostics}
    body.setdefault("payload_hash", payload_hash)
    if snap:
        body.setdefault("model_snapshot", snap)
    if config_fingerprint:
        body.setdefault("config_fingerprint", config_fingerprint)
    safe_input = redact_secrets(input_text) if input_text is not None else None
    safe_output = redact_secrets(output_text) if output_text is not None else None
    return store.append_run_event(
        run_id=run_id,
        event_type=canonical,
        payload=body,
        model_id=model_id,
        component=component,
        input_hash=_sha(safe_input) if safe_input is not None else None,
        output_hash=_sha(safe_output) if safe_output is not None else None,
        parent_event_id=parent_event_id,
    )


def emit_run_lifecycle(
    store: Gen2Store,
    run_id: str,
    phase: str,
    payload: dict[str, Any] | None = None,
    *,
    model_id: str | None = None,
    component: str | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    parent_event_id: str | None = None,
    severity: str | None = None,
    duration_ms: float | None = None,
    correlation_id: str | None = None,
    config_fingerprint: str | None = None,
    model_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Instrument helper for the E2 lifecycle vocabulary.

    ``phase`` accepts canonical names or aliases (MODEL_IO, TOOL, VERIFY, …).
    """
    canonical, _alias = normalize_event_type(phase)
    if canonical not in {
        "MODEL_IO",
        "CONTEXT_SELECTED",
        "PLAN",
        "TOOL",
        "APPROVAL",
        "REPLAN",
        "VERIFY",
        "ARTIFACT",
        "TERMINAL",
    }:
        # Still record, but label non-vocabulary phases honestly.
        body = dict(payload or {})
        body["_lifecycle_phase_unmapped"] = True
        body["_requested_phase"] = phase
        return record(
            store,
            run_id,
            canonical,
            body,
            model_id=model_id,
            component=component or "run_lifecycle",
            input_text=input_text,
            output_text=output_text,
            parent_event_id=parent_event_id,
            severity=severity,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            config_fingerprint=config_fingerprint,
            model_snapshot=model_snapshot,
        )
    return record(
        store,
        run_id,
        canonical,
        payload,
        model_id=model_id,
        component=component or "run_lifecycle",
        input_text=input_text,
        output_text=output_text,
        parent_event_id=parent_event_id,
        severity=severity,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
        config_fingerprint=config_fingerprint,
        model_snapshot=model_snapshot,
    )


def flight_log(store: Gen2Store, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
    return store.list_run_events(run_id, after_sequence=after_sequence)


def compare_runs(store: Gen2Store, run_a: str, run_b: str) -> dict[str, Any]:
    a = store.list_run_events(run_a)
    b = store.list_run_events(run_b)
    if not a or not b:
        missing = [label for label, rows in (("a", a), ("b", b)) if not rows]
        return {
            "ok": False,
            "error": "no_events" if not a and not b else "empty_run",
            "run_a": run_a,
            "run_b": run_b,
            "missing": missing,
            "event_count": {"a": len(a), "b": len(b), run_a: len(a), run_b: len(b)},
        }
    types_a = [e["event_type"] for e in a]
    types_b = [e["event_type"] for e in b]
    models_a = {e.get("model_id") for e in a if e.get("model_id")}
    models_b = {e.get("model_id") for e in b if e.get("model_id")}

    def _payload_sources(events: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for event in events:
            payload = event.get("payload") or {}
            if isinstance(payload, dict):
                for key in ("source", "sources", "item_id", "tool_name", "path"):
                    val = payload.get(key)
                    if isinstance(val, str) and val:
                        out.append(val)
                    elif isinstance(val, list):
                        out.extend(str(x) for x in val if x)
        return out

    def _canonical(et: str) -> str:
        return normalize_event_type(et)[0]

    ctx_a = [e for e in a if _canonical(e["event_type"]) == "CONTEXT_SELECTED"]
    ctx_b = [e for e in b if _canonical(e["event_type"]) == "CONTEXT_SELECTED"]
    tools_a = [e for e in a if _canonical(e["event_type"]) == "TOOL" or "TOOL" in e["event_type"].upper() or e["event_type"] == "tool_status"]
    tools_b = [e for e in b if _canonical(e["event_type"]) == "TOOL" or "TOOL" in e["event_type"].upper() or e["event_type"] == "tool_status"]
    ver_a = [e for e in a if _canonical(e["event_type"]) == "VERIFY" or "VERIF" in e["event_type"].upper()]
    ver_b = [e for e in b if _canonical(e["event_type"]) == "VERIFY" or "VERIF" in e["event_type"].upper()]
    src_a = set(_payload_sources(ctx_a + tools_a))
    src_b = set(_payload_sources(ctx_b + tools_b))
    tokens_a = sum(t for t in (_token_count(e) for e in a) if t is not None)
    tokens_b = sum(t for t in (_token_count(e) for e in b) if t is not None)
    dur_a = sum(d for d in (_duration_ms(e) for e in a) if d is not None)
    dur_b = sum(d for d in (_duration_ms(e) for e in b) if d is not None)
    accept_a = [
        e.get("payload")
        for e in a
        if _canonical(str(e.get("event_type") or "")) in {"TERMINAL", "VERIFY"}
        or str(e.get("event_type") or "").upper() in {"ACCEPTANCE", "OUTCOME", "RUN_COMPLETED", "VERIFICATION", "TERMINAL", "VERIFY"}
    ]
    accept_b = [
        e.get("payload")
        for e in b
        if _canonical(str(e.get("event_type") or "")) in {"TERMINAL", "VERIFY"}
        or str(e.get("event_type") or "").upper() in {"ACCEPTANCE", "OUTCOME", "RUN_COMPLETED", "VERIFICATION", "TERMINAL", "VERIFY"}
    ]
    evidence_a = src_a
    evidence_b = src_b
    regressions: list[str] = []
    if ver_a and not ver_b:
        regressions.append("verification_missing_in_b")
    if tools_a and not tools_b:
        regressions.append("tools_missing_in_b")
    missing_evidence = sorted(evidence_a - evidence_b)
    if missing_evidence:
        regressions.append("missing_evidence_in_b")
    model_calls_a = [e for e in a if _is_model_event(e["event_type"])]
    model_calls_b = [e for e in b if _is_model_event(e["event_type"])]

    tax_a = [classify_failure_taxonomy(e) for e in a if (e.get("payload") or {}).get("failure_taxonomy") or (e.get("payload") or {}).get("error") or (e.get("payload") or {}).get("ok") is False or (e.get("payload") or {}).get("passed") is False]
    tax_b = [classify_failure_taxonomy(e) for e in b if (e.get("payload") or {}).get("failure_taxonomy") or (e.get("payload") or {}).get("error") or (e.get("payload") or {}).get("ok") is False or (e.get("payload") or {}).get("passed") is False]
    from collections import Counter

    count_a = Counter(tax_a)
    count_b = Counter(tax_b)
    taxonomy_only_a = sorted(k for k in count_a if count_a[k] > count_b.get(k, 0))
    taxonomy_only_b = sorted(k for k in count_b if count_b[k] > count_a.get(k, 0))

    return {
        "ok": True,
        "run_a": run_a,
        "run_b": run_b,
        "model_diff": {"a": sorted(models_a), "b": sorted(models_b), run_a: sorted(models_a), run_b: sorted(models_b)},
        "type_diff": {
            "only_a": sorted(set(types_a) - set(types_b)),
            "only_b": sorted(set(types_b) - set(types_a)),
        },
        "context_diff": {
            "a_count": len(ctx_a),
            "b_count": len(ctx_b),
            run_a: {"count": len(ctx_a), "sources": sorted(src_a)},
            run_b: {"count": len(ctx_b), "sources": sorted(src_b)},
            "only_a": sorted(src_a - src_b),
            "only_b": sorted(src_b - src_a),
        },
        "tool_choice_diff": {
            "a_count": len(tools_a),
            "b_count": len(tools_b),
            "a_tools": [
                (e.get("payload") or {}).get("tool_name")
                for e in tools_a
                if isinstance(e.get("payload"), dict)
            ],
            "b_tools": [
                (e.get("payload") or {}).get("tool_name")
                for e in tools_b
                if isinstance(e.get("payload"), dict)
            ],
        },
        "tool_result_diff": {
            "a_count": len(tools_a),
            "b_count": len(tools_b),
            run_a: {"count": len(tools_a), "payloads": [e.get("payload") for e in tools_a[:20]]},
            run_b: {"count": len(tools_b), "payloads": [e.get("payload") for e in tools_b[:20]]},
        },
        "model_calls": {
            "a_count": len(model_calls_a),
            "b_count": len(model_calls_b),
            "tokens": {"a": tokens_a, "b": tokens_b, "delta": tokens_b - tokens_a},
            "duration_ms": {"a": dur_a, "b": dur_b, "delta": dur_b - dur_a},
        },
        "outcome_acceptance": {
            "a": accept_a,
            "b": accept_b,
        },
        "verification_diff": {
            "a": [e.get("payload") for e in ver_a],
            "b": [e.get("payload") for e in ver_b],
            run_a: [e.get("payload") for e in ver_a],
            run_b: [e.get("payload") for e in ver_b],
        },
        "failure_taxonomy_diff": {
            "a": dict(count_a),
            "b": dict(count_b),
            "increased_in_a": taxonomy_only_a,
            "increased_in_b": taxonomy_only_b,
            "classes": list(FAILURE_TAXONOMY),
        },
        "missing_evidence": missing_evidence,
        "regressions": regressions,
        "event_count": {"a": len(a), "b": len(b), run_a: len(a), run_b: len(b)},
    }


def export_audit_bundle(store: Gen2Store, run_id: str) -> dict[str, Any]:
    """Exportable audit bundle for a run (E3/E7): events, hashes, fingerprints, manifest."""
    events = store.list_run_events(run_id)
    if not events:
        return {
            "ok": False,
            "error": "no_events",
            "run_id": run_id,
            "events": [],
            "manifest": {"run_id": run_id, "event_count": 0},
        }
    event_rows = []
    config_fps: list[str] = []
    payload_hashes: list[str] = []
    model_snapshots: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        diag = payload.get("_diagnostics") if isinstance(payload.get("_diagnostics"), dict) else {}
        fp = diag.get("config_fingerprint") or payload.get("config_fingerprint")
        if fp:
            config_fps.append(str(fp))
        ph = diag.get("payload_hash") or payload.get("payload_hash")
        if ph:
            payload_hashes.append(str(ph))
        snap = diag.get("model_snapshot") or payload.get("model_snapshot")
        if isinstance(snap, dict) and snap:
            model_snapshots.append(snap)
        elif event.get("model_id"):
            model_snapshots.append(
                {"model_id": event.get("model_id"), "snapshot_kind": "model_id_record"}
            )
        event_rows.append(
            {
                "id": event.get("id"),
                "sequence": event.get("sequence"),
                "event_type": event.get("event_type"),
                "timestamp": event.get("timestamp"),
                "model_id": event.get("model_id"),
                "component": event.get("component"),
                "input_hash": event.get("input_hash"),
                "output_hash": event.get("output_hash"),
                "parent_event_id": event.get("parent_event_id"),
                "payload_hash": ph,
                "payload_fingerprint": _sha(json.dumps(payload or {}, sort_keys=True)),
                "model_snapshot": snap if isinstance(snap, dict) else None,
                "config_fingerprint": fp,
                "failure_taxonomy": payload.get("failure_taxonomy")
                or (diag.get("failure_taxonomy") if diag else None)
                or (
                    classify_failure_taxonomy(event)
                    if (
                        payload.get("error")
                        or payload.get("ok") is False
                        or payload.get("passed") is False
                    )
                    else None
                ),
                "payload": payload,
            }
        )

    manifest = {
        "run_id": run_id,
        "event_count": len(event_rows),
        "event_types": sorted({str(e.get("event_type")) for e in event_rows}),
        "model_ids": sorted({str(e.get("model_id")) for e in event_rows if e.get("model_id")}),
        "input_hashes": [e.get("input_hash") for e in event_rows if e.get("input_hash")],
        "output_hashes": [e.get("output_hash") for e in event_rows if e.get("output_hash")],
        "payload_hashes": payload_hashes,
        "config_fingerprints": sorted(set(config_fps)),
        "model_snapshots": model_snapshots,
        "bundle_hash": _sha(
            json.dumps(
                [
                    {
                        "sequence": e.get("sequence"),
                        "event_type": e.get("event_type"),
                        "input_hash": e.get("input_hash"),
                        "output_hash": e.get("output_hash"),
                        "payload_hash": e.get("payload_hash"),
                        "payload_fingerprint": e.get("payload_fingerprint"),
                    }
                    for e in event_rows
                ],
                sort_keys=True,
            )
        ),
        "exported_at": utc_now(),
        "vocabulary": sorted(CANONICAL_EVENT_TYPES),
        "honesty": {
            "side_effects_not_reexecuted": True,
            "bundle_is_inspection_export": True,
            "hashes_are_sha256_16": True,
            "model_snapshots_are_id_records": True,
        },
    }
    return {
        "ok": True,
        "run_id": run_id,
        "events": event_rows,
        "hashes": {
            "input": manifest["input_hashes"],
            "output": manifest["output_hashes"],
            "payload": payload_hashes,
            "bundle": manifest["bundle_hash"],
        },
        "config_fingerprints": manifest["config_fingerprints"],
        "model_snapshots": model_snapshots,
        "manifest": manifest,
    }


def replay_plan(
    store: Gen2Store,
    run_id: str,
    *,
    from_sequence: int = 1,
    alternate_model: str | None = None,
    alternate_plugin_version: str | None = None,
    permit_side_effects: bool = False,
    record_fn: RecordFn | None = None,
) -> dict[str, Any]:
    """Build an inspect/simulate manifest. Never performs live model or tool I/O.

    When ``permit_side_effects`` is False (default), side-effecting steps are
    explicitly ``blocked``. When True, they are ``simulated`` only — recorded
    payloads may be reused for inspection, but no write/network/subprocess
    re-execution occurs (honesty: live re-exec is not implemented).
    """
    events = [e for e in store.list_run_events(run_id) if e["sequence"] >= from_sequence]
    if not events:
        return {"ok": False, "error": "no_events", "run_id": run_id}

    side_policy = "simulate" if permit_side_effects else "block"
    steps: list[dict[str, Any]] = []
    for event in events:
        et = event["event_type"]
        step: dict[str, Any] = {
            "sequence": event["sequence"],
            "event_type": et,
            "action": "inspect",
            "executed": False,
            "side_effects": "none",
            "payload_fingerprint": _sha(json.dumps(event.get("payload") or {}, sort_keys=True)),
        }
        if _is_model_event(et):
            step["action"] = "inspect_model_io"
            step["recorded_model_id"] = event.get("model_id")
            step["suggested_alternate_model"] = alternate_model
            step["note"] = "No model call is performed during inspect replay."
        elif _is_side_effect_event(et):
            if permit_side_effects:
                step["action"] = "simulate_side_effect"
                step["side_effects"] = "simulated"
                step["note"] = (
                    "Side effects simulated only from recorded payload; "
                    "tools/writes are not re-executed."
                )
            else:
                # Back-compat: TOOL events keep reuse_recorded_tool_result action name.
                is_tool = "TOOL" in et.upper() or et == "tool_status"
                step["action"] = "reuse_recorded_tool_result" if is_tool else "block_side_effect"
                step["side_effects"] = "blocked"
                step["note"] = "Write/side-effect tools are not re-executed."
            if alternate_plugin_version:
                step["plugin_version_override_suggested"] = alternate_plugin_version
        steps.append(step)

    blocked = sum(1 for s in steps if s.get("side_effects") == "blocked")
    simulated = sum(1 for s in steps if s.get("side_effects") == "simulated")
    manifest: dict[str, Any] = {
        "ok": True,
        "mode": "inspect_manifest",
        "kind": "inspection_not_replay",
        "source_run_id": run_id,
        "from_sequence": from_sequence,
        "alternate_model": alternate_model,
        "alternate_model_executed": False,
        "alternate_plugin_version": alternate_plugin_version,
        "permit_side_effects": permit_side_effects,
        "side_effect_policy": side_policy,
        "side_effects_blocked": blocked,
        "side_effects_simulated": simulated,
        "live_side_effects_executed": False,
        "steps": steps,
        "note": (
            "This is an inspection manifest over recorded events. "
            "It does not re-run models or side-effecting tools"
            + (" (simulate-only when permitted)." if permit_side_effects else ".")
        ),
        "honesty": {
            "live_model_replay": False,
            "live_tool_reexecution": False,
            "permit_side_effects_means": "simulate_recorded_payloads_only",
        },
    }
    _record = record_fn or (lambda *a, **k: record(store, *a, **k))
    replay_run_id = new_id("replay")
    _record(
        replay_run_id,
        "RUN_CREATED",
        {
            "source_run_id": run_id,
            "mode": "inspect",
            "permit_side_effects": permit_side_effects,
            "side_effect_policy": side_policy,
        },
        component="flight_recorder",
    )
    _record(replay_run_id, "REPLAY_MANIFEST", manifest, component="flight_recorder")
    manifest["replay_run_id"] = replay_run_id
    return manifest


def comparative_replay(
    store: Gen2Store,
    run_id: str,
    *,
    alternate_model: str | None = None,
    implementation_id: str | None = None,
    chat_fn: ChatFn | None = None,
    tool_adapter: ToolAdapterFn | None = None,
    reuse_recorded_tools: bool = True,
    reexecute_side_effects: bool = False,
    from_sequence: int = 1,
    record_fn: RecordFn | None = None,
    source_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sandboxed comparative replay against a different model/implementation.

    Distinct from ``replay_plan`` (inspection). This mode may newly execute
    model calls via ``chat_fn``. Tool results default to recorded fixtures.
    Side-effecting tools are not re-executed unless ``reexecute_side_effects``
    is True *and* an explicit ``tool_adapter`` is provided. Prior approvals
    from the source run are never treated as permission for new effects.
    """
    events = [e for e in store.list_run_events(run_id) if e["sequence"] >= from_sequence]
    if not events:
        return {"ok": False, "error": "no_events", "run_id": run_id, "mode": "comparative_sandbox"}

    if reexecute_side_effects and tool_adapter is None:
        return {
            "ok": False,
            "error": "isolated_adapter_required_for_side_effects",
            "run_id": run_id,
            "mode": "comparative_sandbox",
            "note": "Side-effect re-execution requires an explicit isolated tool_adapter.",
        }

    _record = record_fn or (lambda *a, **k: record(store, *a, **k))
    new_run_id = new_id("creplay")
    immutable_inputs = {
        "source_run_id": run_id,
        "from_sequence": from_sequence,
        "source_versions": dict(source_versions or {}),
        "event_fingerprints": [
            {
                "sequence": e["sequence"],
                "event_type": e["event_type"],
                "input_hash": e.get("input_hash"),
                "output_hash": e.get("output_hash"),
                "payload_fingerprint": _sha(json.dumps(e.get("payload") or {}, sort_keys=True)),
            }
            for e in events
        ],
    }
    _record(
        new_run_id,
        "RUN_CREATED",
        {
            "mode": "comparative_sandbox",
            "kind": "comparative_replay",
            "parent_run_id": run_id,
            "alternate_model": alternate_model,
            "implementation_id": implementation_id,
            "reuse_recorded_tools": reuse_recorded_tools,
            "reexecute_side_effects": bool(reexecute_side_effects and tool_adapter is not None),
            "approvals_reused": False,
            "immutable_inputs": immutable_inputs,
        },
        component="flight_recorder",
    )
    _record(
        new_run_id,
        "PARENT_RELATION",
        {"parent_run_id": run_id, "relation": "comparative_replay_of"},
        component="flight_recorder",
    )

    steps: list[dict[str, Any]] = []
    newly_executed_model_calls = 0
    reused_tool_results = 0
    blocked_side_effects = 0
    adapter_side_effects = 0
    total_tokens = 0
    total_duration_ms = 0.0

    for event in events:
        et = event["event_type"]
        payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
        step: dict[str, Any] = {
            "sequence": event["sequence"],
            "event_type": et,
            "source": "recording",
            "executed": False,
        }

        if _is_model_request(et, payload):
            request_payload = {
                "messages": payload.get("messages") or payload.get("prompt") or payload,
                "model_id": alternate_model or event.get("model_id"),
                "recorded_model_id": event.get("model_id"),
                "implementation_id": implementation_id,
                "input_hash": event.get("input_hash"),
            }
            if chat_fn is None:
                step.update(
                    {
                        "action": "model_call_skipped_no_chat_fn",
                        "note": "Provide chat_fn to newly execute model calls in comparative mode.",
                        "provenance": "not_executed",
                    }
                )
                _record(
                    new_run_id,
                    "MODEL_REQUEST",
                    {**payload, "_comparative": {"executed": False, "reason": "no_chat_fn"}},
                    model_id=request_payload["model_id"],
                    component="comparative_replay",
                )
            else:
                started = time.perf_counter()
                try:
                    result = chat_fn(request_payload)
                    if not isinstance(result, dict):
                        result = {"output": result}
                    ok = True
                    error = None
                except Exception as exc:
                    result = {}
                    ok = False
                    error = str(exc)
                elapsed = (time.perf_counter() - started) * 1000.0
                tokens = 0
                try:
                    tokens = int((result.get("usage") or {}).get("total_tokens") or result.get("tokens") or 0)
                except Exception:
                    tokens = 0
                total_tokens += tokens
                total_duration_ms += elapsed
                newly_executed_model_calls += 1
                step.update(
                    {
                        "action": "model_call_executed",
                        "executed": True,
                        "provenance": "newly_executed",
                        "model_id": request_payload["model_id"],
                        "tokens": tokens,
                        "duration_ms": elapsed,
                        "ok": ok,
                        "error": error,
                    }
                )
                _record(
                    new_run_id,
                    "MODEL_REQUEST",
                    {
                        **{k: payload.get(k) for k in ("messages", "prompt") if k in payload},
                        "_comparative": {
                            "executed": True,
                            "alternate_model": alternate_model,
                            "implementation_id": implementation_id,
                            "parent_sequence": event["sequence"],
                        },
                    },
                    model_id=request_payload["model_id"],
                    input_text=json.dumps(request_payload.get("messages"), sort_keys=True)
                    if not isinstance(request_payload.get("messages"), str)
                    else str(request_payload.get("messages")),
                    component="comparative_replay",
                    duration_ms=elapsed,
                )
                _record(
                    new_run_id,
                    "MODEL_RESPONSE",
                    {
                        "output": result.get("output") or result.get("content") or result,
                        "usage": result.get("usage"),
                        "tokens": tokens,
                        "ok": ok,
                        "error": error,
                        "_comparative": {"provenance": "newly_executed", "parent_sequence": event["sequence"]},
                        "_diagnostics": {"duration_ms": elapsed},
                    },
                    model_id=request_payload["model_id"],
                    output_text=str(result.get("output") or result.get("content") or "")[:4000],
                    component="comparative_replay",
                    duration_ms=elapsed,
                )

        elif _is_model_event(et) and not _is_model_request(et, payload):
            # Recorded responses are kept for comparison only — not re-emitted as new execution.
            step.update(
                {
                    "action": "recorded_model_response_reference",
                    "provenance": "from_recording",
                    "note": "Original model response retained for diff; not treated as newly executed.",
                }
            )

        elif _is_side_effect_event(et):
            is_tool = "TOOL" in et.upper() or et == "tool_status"
            if reexecute_side_effects and tool_adapter is not None:
                try:
                    adapted = tool_adapter(
                        {
                            "event_type": et,
                            "payload": payload,
                            "sequence": event["sequence"],
                            "isolated": True,
                            "approvals_from_recording_honored": False,
                        }
                    )
                    adapter_side_effects += 1
                    step.update(
                        {
                            "action": "isolated_adapter_executed",
                            "executed": True,
                            "provenance": "isolated_adapter",
                            "side_effects": "isolated",
                            "result": adapted,
                            "approvals_reused": False,
                        }
                    )
                    _record(
                        new_run_id,
                        et,
                        {
                            **(adapted if isinstance(adapted, dict) else {"result": adapted}),
                            "_comparative": {
                                "provenance": "isolated_adapter",
                                "parent_sequence": event["sequence"],
                                "approvals_reused": False,
                            },
                        },
                        component="comparative_replay",
                    )
                except Exception as exc:
                    blocked_side_effects += 1
                    step.update(
                        {
                            "action": "isolated_adapter_failed",
                            "executed": False,
                            "provenance": "blocked",
                            "side_effects": "blocked",
                            "error": str(exc),
                            "approvals_reused": False,
                        }
                    )
            elif reuse_recorded_tools and is_tool:
                reused_tool_results += 1
                step.update(
                    {
                        "action": "reuse_recorded_tool_fixture",
                        "executed": False,
                        "provenance": "from_recording",
                        "side_effects": "fixture_only",
                        "note": "Tool result taken from recording; not re-executed.",
                        "approvals_reused": False,
                    }
                )
                _record(
                    new_run_id,
                    et,
                    {
                        **payload,
                        "_comparative": {
                            "provenance": "from_recording",
                            "parent_sequence": event["sequence"],
                            "side_effects": "not_reexecuted",
                            "approvals_reused": False,
                        },
                    },
                    component="comparative_replay",
                )
            else:
                blocked_side_effects += 1
                step.update(
                    {
                        "action": "block_side_effect",
                        "executed": False,
                        "provenance": "blocked",
                        "side_effects": "blocked",
                        "note": "Side-effecting tools are not re-executed by default.",
                        "approvals_reused": False,
                    }
                )
                _record(
                    new_run_id,
                    "SIDE_EFFECT_BLOCKED",
                    {
                        "parent_sequence": event["sequence"],
                        "event_type": et,
                        "approvals_reused": False,
                    },
                    component="comparative_replay",
                )
        else:
            # Context / misc — copy as immutable input reference.
            step.update({"action": "copy_context", "provenance": "from_recording"})
            _record(
                new_run_id,
                et,
                {
                    **payload,
                    "_comparative": {"provenance": "from_recording", "parent_sequence": event["sequence"]},
                },
                model_id=event.get("model_id"),
                component="comparative_replay",
            )

        steps.append(step)

    comparison = compare_runs(store, run_id, new_run_id)
    summary = {
        "ok": True,
        "mode": "comparative_sandbox",
        "kind": "comparative_replay",
        "parent_run_id": run_id,
        "new_run_id": new_run_id,
        "alternate_model": alternate_model,
        "implementation_id": implementation_id,
        "immutable_inputs": immutable_inputs,
        "newly_executed_model_calls": newly_executed_model_calls,
        "reused_tool_results": reused_tool_results,
        "blocked_side_effects": blocked_side_effects,
        "isolated_adapter_side_effects": adapter_side_effects,
        "tokens": total_tokens,
        "duration_ms": total_duration_ms,
        "approvals_reused": False,
        "steps": steps,
        "comparison": comparison,
        "honesty": {
            "inspection_replay": False,
            "comparative_sandbox": True,
            "model_calls_may_be_newly_executed": chat_fn is not None,
            "tools_default": "fixtures_from_recording",
            "side_effects_default": "not_reexecuted",
            "old_approvals_grant_new_effects": False,
            "runs_stored_separately": True,
            "parent_relation": True,
        },
        "note": (
            "Comparative sandbox replay: recorded inputs are immutable. "
            "Model calls may be newly executed; tool results come from the recording "
            "unless an explicit isolated adapter is supplied. "
            "This is not the inspect-only replay_plan mode."
        ),
    }
    _record(new_run_id, "COMPARATIVE_REPLAY_SUMMARY", summary, component="flight_recorder")
    return summary
