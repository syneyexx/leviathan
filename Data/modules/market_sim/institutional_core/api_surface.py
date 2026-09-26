"""W66 — Institutional API contract catalog (extends institutional_ops routes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class ApiContract:
    path: str
    method: str
    owner: str
    status: str
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "owner": self.owner,
            "status": self.status,
            "description": self.description,
        }


INSTITUTIONAL_API_CATALOG: tuple[ApiContract, ...] = (
    ApiContract("/api/market-sim/status", "GET", "market_sim.service", MeasurementState.OBSERVED.value),
    ApiContract("/api/market-sim/capabilities", "GET", "market_sim.capabilities", MeasurementState.OBSERVED.value),
    ApiContract("/api/market-sim/data", "GET", "market_sim.service", MeasurementState.OBSERVED.value),
    ApiContract(
        "/api/market-sim/institutional/gap-matrix",
        "GET",
        "institutional_core.gap_ledger",
        MeasurementState.NOT_IMPLEMENTED.value,
        "W37 gap matrix endpoint — contract declared, route may be later wave",
    ),
    ApiContract(
        "/api/market-sim/institutional/control-room",
        "GET",
        "institutional_core.control_room",
        MeasurementState.NOT_IMPLEMENTED.value,
        "W68 control room snapshot",
    ),
    ApiContract(
        "/api/market-sim/institutional/reconciliation",
        "POST",
        "institutional_core.reconciliation",
        MeasurementState.NOT_IMPLEMENTED.value,
    ),
    ApiContract(
        "/api/market-sim/live/order",
        "POST",
        "market_sim.trading_live_guard",
        MeasurementState.BLOCKED.value,
        "Live orders remain blocked",
    ),
)


def api_catalog_public() -> dict[str, Any]:
    return {
        "contracts": [c.public_dict() for c in INSTITUTIONAL_API_CATALOG],
        "count": len(INSTITUTIONAL_API_CATALOG),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "extends_institutional_ops_api_contract": True,
            "catalog_is_not_runtime_proof": True,
        },
    }


def check_institutional_api(registered_paths: Sequence[str]) -> dict[str, Any]:
    """Path presence check — NOT_IMPLEMENTED catalog entries expected missing."""
    registered = set(registered_paths)
    required = [
        c
        for c in INSTITUTIONAL_API_CATALOG
        if c.status in {MeasurementState.OBSERVED.value, MeasurementState.PASS.value}
    ]
    missing = [c.path for c in required if c.path not in registered]
    blocked = [c.public_dict() for c in INSTITUTIONAL_API_CATALOG if c.status == MeasurementState.BLOCKED.value]
    declared_not_implemented = [
        c.public_dict()
        for c in INSTITUTIONAL_API_CATALOG
        if c.status == MeasurementState.NOT_IMPLEMENTED.value
    ]
    return {
        "ok": not missing,
        "missing": missing,
        "blocked": blocked,
        "declaredNotImplemented": declared_not_implemented,
        "status": MeasurementState.PASS.value if not missing else MeasurementState.FAIL.value,
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "not_implemented_routes_are_not_failures": True,
        },
    }
