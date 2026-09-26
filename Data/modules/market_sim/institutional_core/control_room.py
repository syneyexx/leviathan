"""W68 — Backend snapshot builder for control room UI.

Aggregates real institutional_core / market_sim state — no fake green panels.
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
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "snapshot_from_real_state": True,
                "unmeasured_panels_stay_unmeasured": True,
                "no_fake_green": True,
            },
        }


def build_control_room_snapshot(
    *,
    generated_at: str,
    health: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    exceptions: Mapping[str, Any] | None = None,
    audit: Mapping[str, Any] | None = None,
    feature_enabled: bool = True,
) -> ControlRoomSnapshot:
    notes: list[str] = []
    live = verify_live_trading_blocked()
    matrix = build_capability_gap_matrix()
    gaps_body = {
        "openGapCount": len(open_gaps(matrix)),
        "byStatus": matrix.public_dict()["byStatus"],
        "count": matrix.public_dict()["count"],
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

    states = [
        str(live.get("status") or MeasurementState.UNMEASURED.value),
        str(health_body.get("overall") or health_body.get("status") or MeasurementState.UNMEASURED.value),
        str(recon_body.get("status") or MeasurementState.EMPTY.value),
        str(exc_body.get("status") or MeasurementState.EMPTY.value),
        str(audit_body.get("status") or MeasurementState.UNMEASURED.value),
        MeasurementState.OBSERVED.value,  # gap matrix always inventoriable
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
    )
