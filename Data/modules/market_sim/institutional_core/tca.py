"""W58 — Transaction cost analysis with measurement states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH


@dataclass
class FillObservation:
    order_id: str
    symbol: str
    side: str
    qty: float
    fill_price: float
    arrival_price: float | None = None
    decision_price: float | None = None
    benchmark_price: float | None = None
    fee: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "orderId": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "fillPrice": self.fill_price,
            "arrivalPrice": self.arrival_price,
            "decisionPrice": self.decision_price,
            "benchmarkPrice": self.benchmark_price,
            "fee": self.fee,
        }


@dataclass
class TcaMetrics:
    order_id: str
    implementation_shortfall: StatusedValue
    arrival_slippage_bps: StatusedValue
    fee_bps: StatusedValue
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "orderId": self.order_id,
            "implementationShortfall": self.implementation_shortfall.public_dict(),
            "arrivalSlippageBps": self.arrival_slippage_bps.public_dict(),
            "feeBps": self.fee_bps.public_dict(),
            "notes": list(self.notes),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def _side_sign(side: str) -> float:
    return 1.0 if str(side).upper() in {"BUY", "COVER"} else -1.0


def implementation_shortfall_bps(fill: FillObservation) -> StatusedValue:
    """IS ≈ side * (fill - decision) / decision * 1e4 — UNMEASURED without decision price."""
    if fill.decision_price is None or fill.decision_price == 0:
        return StatusedValue(
            None,
            MeasurementState.UNMEASURED,
            methodology="implementation_shortfall_bps",
            notes=["decision_price_missing"],
        )
    sign = _side_sign(fill.side)
    bps = sign * (fill.fill_price - fill.decision_price) / fill.decision_price * 10_000.0
    return StatusedValue(
        bps,
        MeasurementState.OBSERVED,
        unit="bps",
        methodology="implementation_shortfall_bps",
    )


def arrival_slippage_bps(fill: FillObservation) -> StatusedValue:
    if fill.arrival_price is None or fill.arrival_price == 0:
        return StatusedValue(
            None,
            MeasurementState.UNMEASURED,
            methodology="arrival_slippage_bps",
            notes=["arrival_price_missing"],
        )
    sign = _side_sign(fill.side)
    bps = sign * (fill.fill_price - fill.arrival_price) / fill.arrival_price * 10_000.0
    return StatusedValue(
        bps,
        MeasurementState.OBSERVED,
        unit="bps",
        methodology="arrival_slippage_bps",
    )


def fee_bps(fill: FillObservation) -> StatusedValue:
    notional = abs(fill.qty * fill.fill_price)
    if notional == 0:
        return StatusedValue(None, MeasurementState.INFEASIBLE, methodology="fee_bps")
    return StatusedValue(
        fill.fee / notional * 10_000.0,
        MeasurementState.OBSERVED,
        unit="bps",
        methodology="fee_bps",
    )


def analyze_fill(fill: FillObservation | Mapping[str, Any]) -> TcaMetrics:
    if isinstance(fill, Mapping):
        fill = FillObservation(
            order_id=str(fill.get("order_id") or fill.get("orderId") or ""),
            symbol=str(fill.get("symbol") or ""),
            side=str(fill.get("side") or "BUY"),
            qty=float(fill.get("qty") or 0),
            fill_price=float(fill.get("fill_price") or fill.get("fillPrice") or 0),
            arrival_price=(
                None
                if fill.get("arrival_price", fill.get("arrivalPrice")) is None
                else float(fill.get("arrival_price") or fill.get("arrivalPrice"))
            ),
            decision_price=(
                None
                if fill.get("decision_price", fill.get("decisionPrice")) is None
                else float(fill.get("decision_price") or fill.get("decisionPrice"))
            ),
            benchmark_price=(
                None
                if fill.get("benchmark_price", fill.get("benchmarkPrice")) is None
                else float(fill.get("benchmark_price") or fill.get("benchmarkPrice"))
            ),
            fee=float(fill.get("fee") or 0),
        )
    notes: list[str] = []
    if fill.benchmark_price is None:
        notes.append("benchmark_price_UNMEASURED")
    return TcaMetrics(
        order_id=fill.order_id,
        implementation_shortfall=implementation_shortfall_bps(fill),
        arrival_slippage_bps=arrival_slippage_bps(fill),
        fee_bps=fee_bps(fill),
        notes=notes,
    )


def analyze_fills(fills: Sequence[FillObservation | Mapping[str, Any]]) -> dict[str, Any]:
    items = [analyze_fill(f) for f in fills]
    if not items:
        return {
            "items": [],
            "status": MeasurementState.EMPTY.value,
            "truth": DEFAULT_TRUTH.public_dict(),
        }
    states = []
    for item in items:
        states.extend(
            [
                item.implementation_shortfall.state.value,
                item.arrival_slippage_bps.state.value,
                item.fee_bps.state.value,
            ]
        )
    from .status import rollup_states

    return {
        "items": [i.public_dict() for i in items],
        "status": rollup_states(states).value,
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "missing_prices_stay_UNMEASURED": True,
        },
    }
