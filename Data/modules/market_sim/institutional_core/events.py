"""W67 — Institutional event contracts catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class EventContract:
    event_type: str
    required_fields: tuple[str, ...]
    owner: str
    status: str = MeasurementState.OBSERVED.value
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventType": self.event_type,
            "requiredFields": list(self.required_fields),
            "owner": self.owner,
            "status": self.status,
            "description": self.description,
        }


INSTITUTIONAL_EVENT_CATALOG: tuple[EventContract, ...] = (
    EventContract(
        "market_bar",
        ("symbol", "ts", "open", "high", "low", "close"),
        "market_sim.market_event",
    ),
    EventContract(
        "ibor_mutation",
        ("event_id", "sequence", "kind", "ts", "payload"),
        "institutional_core.ibor",
    ),
    EventContract(
        "decision_packet",
        ("packet_id", "stage", "actor", "as_of", "payload"),
        "institutional_core.decision_ledger",
    ),
    EventContract(
        "audit_chained",
        ("event_id", "kind", "actor", "ts", "prev_hash", "event_hash"),
        "institutional_core.audit_integrity",
    ),
    EventContract(
        "reconciliation_break",
        ("break_id", "domain", "field", "status", "fingerprint"),
        "institutional_core.reconciliation",
    ),
    EventContract(
        "order_lifecycle",
        ("order_id", "state", "symbol", "side", "qty"),
        "institutional_core.order_lifecycle",
    ),
    EventContract(
        "corporate_action",
        ("ca_id", "instrument_id", "ca_type", "effective_time", "observed_at"),
        "institutional_core.corporate_actions",
    ),
    EventContract(
        "live_order",
        ("order_id",),
        "market_sim.trading_live_guard",
        status=MeasurementState.BLOCKED.value,
        description="Live order events are blocked",
    ),
)


def event_catalog_public() -> dict[str, Any]:
    return {
        "contracts": [c.public_dict() for c in INSTITUTIONAL_EVENT_CATALOG],
        "count": len(INSTITUTIONAL_EVENT_CATALOG),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "extends_market_event": True,
        },
    }


def validate_event(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = next((c for c in INSTITUTIONAL_EVENT_CATALOG if c.event_type == event_type), None)
    if contract is None:
        return {
            "ok": False,
            "status": MeasurementState.UNAVAILABLE.value,
            "missingFields": [],
            "reason": "unknown_event_type",
        }
    if contract.status == MeasurementState.BLOCKED.value:
        return {
            "ok": False,
            "status": MeasurementState.BLOCKED.value,
            "missingFields": [],
            "reason": "event_type_BLOCKED",
        }
    missing = [f for f in contract.required_fields if f not in payload or payload.get(f) is None]
    return {
        "ok": not missing,
        "status": MeasurementState.PASS.value if not missing else MeasurementState.FAIL.value,
        "missingFields": missing,
        "contract": contract.public_dict(),
        "truth": DEFAULT_TRUTH.public_dict(),
    }
