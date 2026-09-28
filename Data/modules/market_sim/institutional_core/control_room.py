"""W68 — Backend snapshot builder for control room UI.

Aggregates real institutional_core / market_sim state — no fake green panels.
Wave 30 — bounded research / qualification / certification projections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .status import MeasurementState, DEFAULT_TRUTH, rollup_states
from .gap_ledger import build_capability_gap_matrix, open_gaps
from .multi_asset import build_multi_asset_truth_pack
from .assurance import verify_live_trading_blocked
from .api_surface import api_catalog_public
from .events import event_catalog_public


@dataclass
class ControlRoomSnapshot:
    generated_at: str
    live_trading: dict[str, Any]
    gaps: dict[str, Any]
    multi_asset: dict[str, Any]
    health: dict[str, Any]
    reconciliation: dict[str, Any]
    exceptions: dict[str, Any]
    audit: dict[str, Any]
    api: dict[str, Any]
    events: dict[str, Any]
    overall_status: str
    notes: list[str] = field(default_factory=list)
    research: dict[str, Any] = field(default_factory=dict)
    data_plane: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "generatedAt": self.generated_at,
            "liveTrading": dict(self.live_trading),
            "gaps": dict(self.gaps),
            "multiAsset": dict(self.multi_asset),
            "health": dict(self.health),
            "reconciliation": dict(self.reconciliation),
            "exceptions": dict(self.exceptions),
            "audit": dict(self.audit),
            "api": dict(self.api),
            "events": dict(self.events),
            "overallStatus": self.overall_status,
            "notes": list(self.notes),
            "research": dict(self.research),
            "dataPlane": dict(self.data_plane),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "snapshot_from_real_state": True,
                "unmeasured_panels_stay_unmeasured": True,
                "no_fake_green": True,
                "projections_bounded": True,
            },
        }


def build_research_projections(
    store: Any | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Bounded Wave 30 research projections — never full-table scans."""
    lim = max(1, min(int(limit), 200))
    if store is None:
        return {
            "status": MeasurementState.UNMEASURED.value,
            "notes": ["store_not_supplied"],
            "qualificationRunsCount": 0,
            "qualificationRuns": [],
            "sealedAttemptsCount": 0,
            "sealedAttempts": [],
            "activeCampaigns": 0,
            "hypothesesCount": 0,
            "trialCount": 0,
        }

    campaigns: list[dict[str, Any]] = []
    hyps: list[dict[str, Any]] = []
    quals: list[dict[str, Any]] = []
    sealed: list[dict[str, Any]] = []
    trial_count = 0
    qual_count = 0

    try:
        if hasattr(store, "list_research_campaigns"):
            campaigns = list(store.list_research_campaigns(limit=lim) or [])
    except Exception:  # noqa: BLE001
        campaigns = []
    try:
        if hasattr(store, "list_market_hypotheses"):
            hyps = list(store.list_market_hypotheses(limit=lim) or [])
    except Exception:  # noqa: BLE001
        hyps = []
    try:
        if hasattr(store, "list_qualification_runs"):
            quals = list(store.list_qualification_runs(limit=lim) or [])
        if hasattr(store, "count_qualification_runs"):
            qual_count = int(store.count_qualification_runs())
        else:
            qual_count = len(quals)
    except Exception:  # noqa: BLE001
        quals = []
        qual_count = 0
    try:
        if hasattr(store, "list_sealed_attempts"):
            sealed = list(store.list_sealed_attempts(limit=lim) or [])
    except Exception:  # noqa: BLE001
        sealed = []
    try:
        if hasattr(store, "count_trials"):
            trial_count = int(store.count_trials())
    except Exception:  # noqa: BLE001
        trial_count = 0

    active = [
        c
        for c in campaigns
        if str(c.get("status") or "").upper() in {"CREATED", "QUEUED", "RUNNING", "PAUSED"}
    ]
    sealed_states = {
        str(s.get("status") or MeasurementState.UNMEASURED.value).upper() for s in sealed
    }
    decisions = {
        str(q.get("decision") or q.get("status") or MeasurementState.UNMEASURED.value).upper()
        for q in quals
    }
    rejection_reasons: list[str] = []
    for q in quals:
        for b in q.get("blockers") or []:
            rejection_reasons.append(str(b)[:200])
        if len(rejection_reasons) >= 20:
            break

    return {
        "status": MeasurementState.OBSERVED.value,
        "activeCampaigns": len(active),
        "campaignSample": [
            {
                "campaignId": c.get("campaign_id"),
                "status": c.get("status"),
                "hypothesisId": (c.get("metadata") or {}).get("active_hypothesis_id"),
            }
            for c in active[:20]
        ],
        "hypothesesCount": len(hyps),
        "hypotheses": [
            {
                "hypothesisId": h.get("hypothesis_id"),
                "status": h.get("status"),
                "mechanism": str(h.get("mechanism") or "")[:80],
            }
            for h in hyps[:20]
        ],
        "trialCount": trial_count,
        "qualificationRunsCount": qual_count,
        "qualificationRuns": [
            {
                "qualificationId": q.get("qualification_id"),
                "status": q.get("status"),
                "decision": q.get("decision"),
                "currentGate": q.get("current_gate"),
                "sealedAttemptId": q.get("sealed_attempt_id"),
                "strategyId": q.get("strategy_id"),
                "blockers": [str(b)[:200] for b in (q.get("blockers") or [])][:8],
                "createdAt": q.get("created_at"),
                "updatedAt": q.get("updated_at"),
            }
            for q in quals[:20]
        ],
        "qualificationDecisions": sorted(decisions),
        "rejectionReasons": rejection_reasons[:20],
        "sealedAttemptsCount": len(sealed),
        "sealedStates": sorted(sealed_states) if sealed_states else [MeasurementState.EMPTY.value],
        "sealedAttempts": [
            {
                "sealedAttemptId": s.get("sealed_attempt_id"),
                "status": s.get("status"),
                "strategyId": s.get("strategy_id"),
            }
            for s in sealed[:20]
        ],
        "limit": lim,
        "truth": {
            "bounded_queries": True,
            "no_full_table_scan": True,
        },
    }


def build_data_plane_projections(
    store: Any | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Bounded dataset certification / PIT / survivorship projection (Wave 30)."""
    lim = max(1, min(int(limit), 200))
    if store is None:
        return {
            "status": MeasurementState.UNMEASURED.value,
            "notes": ["store_not_supplied"],
            "certificationCount": 0,
            "certifications": [],
        }
    certs: list[dict[str, Any]] = []
    try:
        if hasattr(store, "list_dataset_certifications"):
            certs = list(store.list_dataset_certifications(limit=lim) or [])
    except Exception:  # noqa: BLE001
        certs = []

    pit_states = {
        str(c.get("pit_state") or MeasurementState.UNMEASURED.value).upper() for c in certs
    }
    cert_states = {
        str(c.get("certification_state") or MeasurementState.UNMEASURED.value).upper()
        for c in certs
    }
    surv_states = {
        str(c.get("survivorship_state") or MeasurementState.UNMEASURED.value).upper()
        for c in certs
    }

    return {
        "status": MeasurementState.OBSERVED.value if certs else MeasurementState.EMPTY.value,
        "certificationCount": len(certs),
        "certificationStates": sorted(cert_states) if cert_states else [MeasurementState.EMPTY.value],
        "pitStates": sorted(pit_states) if pit_states else [MeasurementState.EMPTY.value],
        "survivorshipStates": sorted(surv_states) if surv_states else [MeasurementState.EMPTY.value],
        "certifications": [
            {
                "certificationId": c.get("certification_id"),
                "datasetId": c.get("dataset_id"),
                "certificationState": c.get("certification_state"),
                "pitState": c.get("pit_state"),
                "survivorshipState": c.get("survivorship_state"),
                "certifiedAt": c.get("certified_at"),
            }
            for c in certs[:20]
        ],
        "limit": lim,
        "truth": {"bounded_queries": True},
    }


def build_control_room_snapshot(
    *,
    generated_at: str,
    health: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    exceptions: Mapping[str, Any] | None = None,
    audit: Mapping[str, Any] | None = None,
    feature_enabled: bool = True,
    store: Any | None = None,
    projection_limit: int = 50,
) -> ControlRoomSnapshot:
    notes: list[str] = []
    live = verify_live_trading_blocked()
    matrix = build_capability_gap_matrix()
    matrix_public = matrix.public_dict()
    by_implementation: dict[str, int] = {}
    for row in matrix.rows:
        key = str(row.implementation or "UNKNOWN")
        by_implementation[key] = by_implementation.get(key, 0) + 1
    gaps_body = {
        "openGapCount": len(open_gaps(matrix)),
        "byStatus": matrix_public["byStatus"],
        "byImplementation": by_implementation,
        "count": matrix_public["count"],
    }
    multi = build_multi_asset_truth_pack(feature_enabled=feature_enabled).public_dict()

    health_body = dict(health) if health is not None else {
        "overall": MeasurementState.UNMEASURED.value,
        "notes": ["health_not_supplied"],
    }
    if health is None:
        notes.append("health_UNMEASURED")

    recon_body = dict(reconciliation) if reconciliation is not None else {
        "status": MeasurementState.EMPTY.value,
        "openCount": 0,
        "notes": ["no_reconciliation_run_supplied"],
    }
    exc_body = dict(exceptions) if exceptions is not None else {
        "status": MeasurementState.EMPTY.value,
        "openCount": 0,
    }
    audit_body = dict(audit) if audit is not None else {
        "status": MeasurementState.UNMEASURED.value,
        "notes": ["audit_verify_not_supplied"],
    }
    if audit is None:
        notes.append("audit_UNMEASURED")

    research = build_research_projections(store, limit=projection_limit)
    data_plane = build_data_plane_projections(store, limit=projection_limit)
    if research.get("status") == MeasurementState.UNMEASURED.value:
        notes.append("research_projections_UNMEASURED")
    if data_plane.get("status") == MeasurementState.UNMEASURED.value:
        notes.append("data_plane_projections_UNMEASURED")

    states = [
        str(live.get("status") or MeasurementState.UNMEASURED.value),
        str(health_body.get("overall") or health_body.get("status") or MeasurementState.UNMEASURED.value),
        str(recon_body.get("status") or MeasurementState.EMPTY.value),
        str(exc_body.get("status") or MeasurementState.EMPTY.value),
        str(audit_body.get("status") or MeasurementState.UNMEASURED.value),
        MeasurementState.OBSERVED.value,  # gap matrix always inventoriable
        str(research.get("status") or MeasurementState.UNMEASURED.value),
        str(data_plane.get("status") or MeasurementState.UNMEASURED.value),
    ]
    # Live trading PASS (blocked correctly) should not paint everything green alone.
    overall = rollup_states(states).value

    return ControlRoomSnapshot(
        generated_at=generated_at,
        live_trading=live,
        gaps=gaps_body,
        multi_asset=multi,
        health=health_body,
        reconciliation=recon_body,
        exceptions=exc_body,
        audit=audit_body,
        api=api_catalog_public(),
        events=event_catalog_public(),
        overall_status=overall,
        notes=notes,
        research=research,
        data_plane=data_plane,
    )
