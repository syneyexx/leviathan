"""A11 — stable correlation IDs, honest token usage, reproducible exports.

Builds on Flight Recorder. Does not invent provider token counts.
Separates inspect/export from live comparative replay.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from gen2.flight_recorder import (
    classify_failure_taxonomy,
    export_audit_bundle,
    normalize_event_type,
    record,
)
from gen2.store import Gen2Store, utc_now

TokenKind = Literal["exact", "estimate", "missing"]
SurfaceName = Literal[
    "conversation",
    "task",
    "mission",
    "workflow",
    "run",
    "step",
    "toolcall",
    "approval",
    "plan_revision",
    "artifact_version",
]


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def new_correlation_id(prefix: str = "corr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def git_fingerprint(cwd: Path | None = None) -> dict[str, Any]:
    """Best-effort git fingerprint; never fails the caller hard."""
    root = cwd or Path(__file__).resolve().parents[2]
    out: dict[str, Any] = {"cwd": str(root), "commit": "unavailable", "dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if commit.returncode == 0:
            out["commit"] = (commit.stdout or "").strip() or "unavailable"
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if dirty.returncode == 0:
            out["dirty"] = bool((dirty.stdout or "").strip())
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def config_hash(config: dict[str, Any] | None) -> str:
    blob = json.dumps(config or {}, sort_keys=True, ensure_ascii=False, default=str)
    return _sha(blob)


@dataclass(slots=True)
class CorrelationIds:
    """Stable relation across HADES surfaces for one logical work stream."""

    correlation_id: str
    conversation_id: str | None = None
    task_id: str | None = None
    mission_id: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    toolcall_id: str | None = None
    approval_id: str | None = None
    plan_revision: int | None = None
    artifact_version: str | None = None
    parent_correlation_id: str | None = None

    def bind(self, **kwargs: Any) -> "CorrelationIds":
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(slots=True)
class TokenUsageRecord:
    """Honest token accounting — exact from provider, else estimate or missing."""

    kind: TokenKind
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    source: str = "unspecified"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_token_usage(payload: dict[str, Any] | None) -> TokenUsageRecord:
    """Prefer provider usage; never invent fixed fake totals."""
    if isinstance(payload, TokenUsageRecord):
        return payload
    if not isinstance(payload, dict):
        return TokenUsageRecord(
            kind="missing",
            source="invalid_payload",
            note="token_usage_not_object",
        )
    body = dict(payload)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    # Explicit labels take priority. Accept both token_kind and kind.
    kind_raw = str(
        body.get("token_kind") or body.get("kind") or usage.get("kind") or usage.get("token_kind") or ""
    ).lower()
    if body.get("tokens_missing") or usage.get("missing") or kind_raw == "missing":
        return TokenUsageRecord(
            kind="missing",
            source=str(body.get("token_source") or usage.get("source") or body.get("source") or "explicit_missing"),
            note=str(body.get("token_note") or body.get("note") or "provider_did_not_report_usage"),
        )
    if body.get("estimated") or usage.get("estimated") or kind_raw == "estimate":
        total = _as_int(body.get("total_tokens") or usage.get("total_tokens") or body.get("tokens"))
        return TokenUsageRecord(
            kind="estimate",
            total_tokens=total,
            prompt_tokens=_as_int(body.get("prompt_tokens") or usage.get("prompt_tokens")),
            completion_tokens=_as_int(body.get("completion_tokens") or usage.get("completion_tokens")),
            source=str(body.get("token_source") or usage.get("source") or body.get("source") or "estimate"),
            note="labeled_estimate_not_provider_exact",
        )
    # Provider-shaped usage without estimate flag → exact.
    total = _as_int(
        usage.get("total_tokens")
        or body.get("total_tokens")
        or body.get("tokens")
        or body.get("token_count")
    )
    prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens") or body.get("prompt_tokens"))
    completion = _as_int(
        usage.get("completion_tokens") or usage.get("output_tokens") or body.get("completion_tokens")
    )
    if total is not None or prompt is not None or completion is not None:
        if total is None and prompt is not None and completion is not None:
            total = prompt + completion
        return TokenUsageRecord(
            kind="exact",
            total_tokens=total,
            prompt_tokens=prompt,
            completion_tokens=completion,
            source=str(body.get("token_source") or usage.get("source") or "provider"),
            note=None,
        )
    return TokenUsageRecord(
        kind="missing",
        source=str(body.get("token_source") or "absent"),
        note="no_provider_usage_and_no_estimate",
    )


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ExperimentMeta:
    """Comparable experiment identity (parent + fingerprints)."""

    experiment_id: str
    parent_run_id: str | None = None
    parent_experiment_id: str | None = None
    git: dict[str, Any] = field(default_factory=dict)
    dataset_version: str | None = None
    grader_version: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    config_hash: str | None = None
    label: str | None = None
    quality_layer: str = "software"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data.get("config_hash"):
            data["config_hash"] = config_hash(self.config)
        return data


def ensure_correlation(
    ids: CorrelationIds | dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
    **surface: Any,
) -> CorrelationIds:
    if isinstance(ids, CorrelationIds):
        bundle = ids
    elif isinstance(ids, dict):
        bundle = CorrelationIds(
            correlation_id=str(ids.get("correlation_id") or correlation_id or new_correlation_id()),
            **{k: ids.get(k) for k in (
                "conversation_id",
                "task_id",
                "mission_id",
                "workflow_id",
                "run_id",
                "step_id",
                "toolcall_id",
                "approval_id",
                "plan_revision",
                "artifact_version",
                "parent_correlation_id",
            ) if ids.get(k) is not None},
        )
    else:
        bundle = CorrelationIds(correlation_id=correlation_id or new_correlation_id())
    if correlation_id and not bundle.correlation_id:
        bundle.correlation_id = correlation_id
    if surface:
        bundle.bind(**surface)
    if not bundle.correlation_id:
        bundle.correlation_id = new_correlation_id()
    return bundle


def record_correlated(
    store: Gen2Store,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    correlation: CorrelationIds | dict[str, Any] | None = None,
    model_id: str | None = None,
    component: str | None = None,
    effective_model_config: dict[str, Any] | None = None,
    source_versions: dict[str, Any] | None = None,
    context_ids: list[str] | None = None,
    budget_decision: dict[str, Any] | None = None,
    tool_outcome: dict[str, Any] | None = None,
    acceptance_evidence: dict[str, Any] | None = None,
    token_usage: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    severity: str | None = None,
    config_fingerprint: str | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    parent_event_id: str | None = None,
) -> dict[str, Any]:
    """Record a Flight Recorder event with stable correlation + honest tokens."""
    corr = ensure_correlation(correlation, run_id=run_id)
    body = dict(payload or {})
    body["correlation"] = corr.to_dict()
    body.setdefault("correlation_id", corr.correlation_id)
    if effective_model_config is not None:
        body["effective_model_config"] = dict(effective_model_config)
        body.setdefault("config_fingerprint", config_hash(effective_model_config))
    if source_versions is not None:
        body["source_versions"] = dict(source_versions)
    if context_ids is not None:
        body["context_ids"] = list(context_ids)
    if budget_decision is not None:
        body["budget_decision"] = dict(budget_decision)
    if tool_outcome is not None:
        body["tool_outcome"] = dict(tool_outcome)
        if tool_outcome.get("ok") is False:
            body.setdefault("ok", False)
            body.setdefault("error", tool_outcome.get("error") or tool_outcome.get("reason"))
    if acceptance_evidence is not None:
        body["acceptance_evidence"] = dict(acceptance_evidence)
    usage_src = token_usage if token_usage is not None else body
    usage = normalize_token_usage(usage_src if isinstance(usage_src, dict) else {})
    body["token_usage"] = usage.to_dict()
    # Never leave a bare fake total without kind.
    if usage.kind == "exact" and usage.total_tokens is not None:
        body["tokens"] = usage.total_tokens
        body["token_kind"] = "exact"
    elif usage.kind == "estimate" and usage.total_tokens is not None:
        body["tokens"] = usage.total_tokens
        body["token_kind"] = "estimate"
        body["estimated"] = True
    else:
        body.pop("tokens", None)
        body["token_kind"] = "missing"
        body["tokens_missing"] = True

    fp = config_fingerprint or body.get("config_fingerprint")
    if isinstance(fp, str) and fp:
        body["config_fingerprint"] = fp

    event = record(
        store,
        run_id,
        event_type,
        body,
        model_id=model_id,
        component=component or "correlation_telemetry",
        input_text=input_text,
        output_text=output_text,
        parent_event_id=parent_event_id,
        severity=severity,
        duration_ms=duration_ms,
        correlation_id=corr.correlation_id,
        config_fingerprint=body.get("config_fingerprint"),
        model_snapshot={"model_id": model_id, "effective_model_config": effective_model_config}
        if model_id or effective_model_config
        else None,
    )
    return event


def human_run_summary(store: Gen2Store, run_id: str) -> dict[str, Any]:
    """Compact human-readable summary of a recorded run."""
    events = store.list_run_events(run_id)
    types: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    correlations: set[str] = set()
    tokens_exact = 0
    tokens_estimate = 0
    tokens_missing_events = 0
    terminal: dict[str, Any] | None = None
    models: set[str] = set()
    aborted = False
    infra_issues: list[str] = []

    for event in events:
        et = str(event.get("event_type") or "")
        canonical = normalize_event_type(et)[0]
        types[canonical] = types.get(canonical, 0) + 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        diag = payload.get("_diagnostics") if isinstance(payload.get("_diagnostics"), dict) else {}
        cid = (
            payload.get("correlation_id")
            or (payload.get("correlation") or {}).get("correlation_id")
            or diag.get("correlation_id")
        )
        if cid:
            correlations.add(str(cid))
        if event.get("model_id"):
            models.add(str(event["model_id"]))
        usage_raw = payload.get("token_usage")
        if isinstance(usage_raw, dict):
            usage = normalize_token_usage(usage_raw)
        else:
            usage = normalize_token_usage(payload if isinstance(payload, dict) else {})
        if usage.kind == "exact" and usage.total_tokens:
            tokens_exact += usage.total_tokens
        elif usage.kind == "estimate" and usage.total_tokens:
            tokens_estimate += usage.total_tokens
        elif usage.kind == "missing" and canonical == "MODEL_IO":
            tokens_missing_events += 1
        status = str(payload.get("status") or "").lower()
        if status in {"aborted", "cancelled", "canceled"} or payload.get("aborted"):
            aborted = True
        if payload.get("infra") or payload.get("infra_issue") or "unavailable" in status:
            infra_issues.append(str(payload.get("infra_issue") or payload.get("error") or status))
        looks_failed = bool(
            payload.get("error")
            or payload.get("ok") is False
            or payload.get("passed") is False
            or status in {"failed", "error", "blocked"}
        )
        if looks_failed:
            failures.append(
                {
                    "sequence": event.get("sequence"),
                    "event_type": canonical,
                    "taxonomy": classify_failure_taxonomy(event),
                    "error": payload.get("error") or payload.get("reason"),
                }
            )
        if canonical == "TERMINAL":
            terminal = {
                "status": payload.get("status"),
                "ok": payload.get("ok"),
                "acceptance_evidence": payload.get("acceptance_evidence"),
            }

    lines = [
        f"Run {run_id}: {len(events)} events",
        f"Models: {', '.join(sorted(models)) or 'none'}",
        f"Correlation IDs: {', '.join(sorted(correlations)) or 'none'}",
        (
            f"Tokens: exact={tokens_exact} estimate={tokens_estimate} "
            f"missing_model_io_events={tokens_missing_events}"
        ),
        f"Failures visible: {len(failures)}; aborted={aborted}; infra_issues={len(infra_issues)}",
    ]
    if terminal:
        lines.append(f"Terminal: {terminal.get('status')} ok={terminal.get('ok')}")
    return {
        "ok": True,
        "run_id": run_id,
        "event_count": len(events),
        "event_types": types,
        "correlation_ids": sorted(correlations),
        "models": sorted(models),
        "token_usage": {
            "exact_total": tokens_exact,
            "estimate_total": tokens_estimate,
            "missing_model_io_events": tokens_missing_events,
            "honesty": "no_fixed_fake_tokens",
        },
        "failures": failures,
        "aborted": aborted,
        "infra_issues": infra_issues,
        "terminal": terminal,
        "completeness": {
            "failures_visible": True,
            "aborts_visible": aborted or any(
                str((e.get("payload") or {}).get("status") or "").lower() in {"aborted", "cancelled"}
                for e in events
            ),
            "infra_visible": bool(infra_issues),
        },
        "human_lines": lines,
        "human_text": "\n".join(lines),
    }


def export_reproducible_bundle(
    store: Gen2Store,
    run_id: str,
    *,
    experiment: ExperimentMeta | dict[str, Any] | None = None,
    include_events: bool = True,
) -> dict[str, Any]:
    """Safe machine-readable export + compact human summary."""
    audit = export_audit_bundle(store, run_id)
    summary = human_run_summary(store, run_id)
    exp: dict[str, Any]
    if isinstance(experiment, ExperimentMeta):
        exp = experiment.to_dict()
    elif isinstance(experiment, dict):
        exp = dict(experiment)
        exp.setdefault("config_hash", config_hash(exp.get("config") or {}))
        exp.setdefault("git", git_fingerprint())
    else:
        exp = {
            "experiment_id": new_correlation_id("exp"),
            "git": git_fingerprint(),
            "config_hash": None,
            "quality_layer": "software",
        }

    # Redacted event view already comes from Flight Recorder record path.
    events = audit.get("events") if include_events else []
    # Completeness: keep failures/aborts/infra even when terminal ok looks green.
    visible_issues = {
        "failures": summary.get("failures") or [],
        "aborted": summary.get("aborted"),
        "infra_issues": summary.get("infra_issues") or [],
    }
    bundle = {
        "ok": True,
        "kind": "reproducible_export",
        "mode": "inspection_export",
        "inspection_not_replay": True,
        "run_id": run_id,
        "exported_at": utc_now(),
        "experiment": exp,
        "summary": summary,
        "human_summary": summary.get("human_text"),
        "audit_manifest": audit.get("manifest"),
        "hashes": audit.get("hashes"),
        "config_fingerprints": audit.get("config_fingerprints"),
        "model_snapshots": audit.get("model_snapshots"),
        "visible_issues": visible_issues,
        "events": events,
        "honesty": {
            "bundle_is_inspection_export": True,
            "not_live_replay": True,
            "tokens_not_fabricated": True,
            "exactly_once_not_claimed": True,
            "failures_remain_visible": True,
        },
    }
    bundle["bundle_hash"] = _sha(
        json.dumps(
            {
                "run_id": run_id,
                "manifest": audit.get("manifest"),
                "experiment": {
                    "experiment_id": exp.get("experiment_id"),
                    "config_hash": exp.get("config_hash"),
                    "dataset_version": exp.get("dataset_version"),
                    "grader_version": exp.get("grader_version"),
                    "git": (exp.get("git") or {}).get("commit"),
                },
                "issue_count": len(visible_issues["failures"]) + len(visible_issues["infra_issues"]),
            },
            sort_keys=True,
            default=str,
        )
    )
    return bundle


def register_experiment_relation(
    store: Gen2Store,
    *,
    parent_run_id: str,
    child_run_id: str,
    experiment: ExperimentMeta | dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Store parent relation + experiment fingerprints on both runs."""
    meta = experiment.to_dict() if isinstance(experiment, ExperimentMeta) else dict(experiment or {})
    meta.setdefault("experiment_id", new_correlation_id("exp"))
    meta.setdefault("git", git_fingerprint())
    meta.setdefault("config_hash", config_hash(meta.get("config") or {}))
    corr = correlation_id or new_correlation_id()
    parent_ev = record_correlated(
        store,
        run_id=parent_run_id,
        event_type="PARENT_RELATION",
        payload={
            "relation": "experiment_parent",
            "child_run_id": child_run_id,
            "experiment": meta,
        },
        correlation={"correlation_id": corr, "run_id": parent_run_id},
        component="experiment",
    )
    child_ev = record_correlated(
        store,
        run_id=child_run_id,
        event_type="PARENT_RELATION",
        payload={
            "relation": "experiment_child",
            "parent_run_id": parent_run_id,
            "experiment": meta,
        },
        correlation={"correlation_id": corr, "run_id": child_run_id, "parent_correlation_id": corr},
        component="experiment",
    )
    return {
        "ok": True,
        "correlation_id": corr,
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "experiment": meta,
        "parent_event_id": parent_ev.get("id"),
        "child_event_id": child_ev.get("id"),
    }


def inspect_vs_replay_modes() -> dict[str, Any]:
    """Document the two modes without executing anything."""
    return {
        "inspect": {
            "api": "replay_plan / export_reproducible_bundle",
            "reexecutes_model": False,
            "reexecutes_tools": False,
            "uses_stored_tool_results": True,
            "label": "inspection_not_replay",
        },
        "comparative_replay": {
            "api": "comparative_replay",
            "reexecutes_model": True,
            "reexecutes_tools": False,
            "default_tool_policy": "reuse_recorded_or_block_side_effects",
            "parent_relation": True,
            "label": "comparative_sandbox",
        },
        "honesty": "Original approvals are never reused as permission for new effects.",
    }
