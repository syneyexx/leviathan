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


# ---------------------------------------------------------------------------
# Wave 22 — order-level predicted vs observed TCA + calibration inputs
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPrediction:
    decision_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    predicted_fill_ts: str | None = None
    predicted_fill_price: float | None = None
    predicted_spread_bps: float | None = None
    predicted_slippage_bps: float | None = None
    predicted_latency_ms: float | None = None
    predicted_fill_probability: float | None = None
    predicted_participation: float | None = None
    execution_model_id: str = ""
    execution_model_version: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "orderId": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "predictedFillTs": self.predicted_fill_ts,
            "predictedFillPrice": self.predicted_fill_price,
            "predictedSpreadBps": self.predicted_spread_bps,
            "predictedSlippageBps": self.predicted_slippage_bps,
            "predictedLatencyMs": self.predicted_latency_ms,
            "predictedFillProbability": self.predicted_fill_probability,
            "predictedParticipation": self.predicted_participation,
            "executionModelId": self.execution_model_id,
            "executionModelVersion": self.execution_model_version,
        }


@dataclass
class ExecutionObservation:
    paper_order_id: str
    matched_decision_id: str
    actual_fill_ts: str | None = None
    actual_fill_price: float | None = None
    observed_spread_bps: float | None = None
    observed_latency_ms: float | None = None
    actual_fill_fraction: float = 0.0
    reject_or_miss_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "paperOrderId": self.paper_order_id,
            "matchedDecisionId": self.matched_decision_id,
            "actualFillTs": self.actual_fill_ts,
            "actualFillPrice": self.actual_fill_price,
            "observedSpreadBps": self.observed_spread_bps,
            "observedLatencyMs": self.observed_latency_ms,
            "actualFillFraction": self.actual_fill_fraction,
            "rejectOrMissReason": self.reject_or_miss_reason,
        }


@dataclass
class ExecutionGapMeasurement:
    decision_id: str
    order_id: str
    symbol: str
    matched: bool
    state: str
    prediction: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)
    slippage_gap_bps: float | None = None
    latency_gap_ms: float | None = None
    fill_fraction_gap: float | None = None
    blockers: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "orderId": self.order_id,
            "symbol": self.symbol,
            "matched": self.matched,
            "state": self.state,
            "prediction": dict(self.prediction),
            "observation": dict(self.observation),
            "slippageGapBps": self.slippage_gap_bps,
            "latencyGapMs": self.latency_gap_ms,
            "fillFractionGap": self.fill_fraction_gap,
            "blockers": list(self.blockers),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "match_by_stable_lineage_not_nearest_price": True,
                "unmatched_stays_UNMEASURED": True,
            },
        }


def match_execution_gap(
    prediction: ExecutionPrediction | Mapping[str, Any],
    observation: ExecutionObservation | Mapping[str, Any] | None,
) -> ExecutionGapMeasurement:
    """Match by stable decision/order lineage — never nearest-price heuristic."""
    if isinstance(prediction, ExecutionPrediction):
        pred = prediction
    else:
        pred = ExecutionPrediction(
            decision_id=str(prediction.get("decision_id") or prediction.get("decisionId") or ""),
            order_id=str(prediction.get("order_id") or prediction.get("orderId") or ""),
            symbol=str(prediction.get("symbol") or ""),
            side=str(prediction.get("side") or ""),
            qty=float(prediction.get("qty") or 0),
            predicted_fill_ts=prediction.get("predicted_fill_ts") or prediction.get("predictedFillTs"),
            predicted_fill_price=_f(prediction.get("predicted_fill_price") or prediction.get("predictedFillPrice")),
            predicted_spread_bps=_f(prediction.get("predicted_spread_bps") or prediction.get("predictedSpreadBps")),
            predicted_slippage_bps=_f(
                prediction.get("predicted_slippage_bps") or prediction.get("predictedSlippageBps")
            ),
            predicted_latency_ms=_f(
                prediction.get("predicted_latency_ms") or prediction.get("predictedLatencyMs")
            ),
            predicted_fill_probability=_f(
                prediction.get("predicted_fill_probability")
                or prediction.get("predictedFillProbability")
            ),
            predicted_participation=_f(
                prediction.get("predicted_participation") or prediction.get("predictedParticipation")
            ),
            execution_model_id=str(
                prediction.get("execution_model_id") or prediction.get("executionModelId") or ""
            ),
            execution_model_version=str(
                prediction.get("execution_model_version")
                or prediction.get("executionModelVersion")
                or ""
            ),
        )
    if observation is None:
        return ExecutionGapMeasurement(
            decision_id=pred.decision_id,
            order_id=pred.order_id,
            symbol=pred.symbol,
            matched=False,
            state=MeasurementState.UNMEASURED.value,
            prediction=pred.public_dict(),
            blockers=["UNMATCHED_OBSERVATION"],
        )
    if isinstance(observation, Mapping):
        obs = ExecutionObservation(
            paper_order_id=str(
                observation.get("paper_order_id") or observation.get("paperOrderId") or ""
            ),
            matched_decision_id=str(
                observation.get("matched_decision_id")
                or observation.get("matchedDecisionId")
                or ""
            ),
            actual_fill_ts=observation.get("actual_fill_ts") or observation.get("actualFillTs"),
            actual_fill_price=_f(
                observation.get("actual_fill_price") or observation.get("actualFillPrice")
            ),
            observed_spread_bps=_f(
                observation.get("observed_spread_bps") or observation.get("observedSpreadBps")
            ),
            observed_latency_ms=_f(
                observation.get("observed_latency_ms") or observation.get("observedLatencyMs")
            ),
            actual_fill_fraction=float(
                observation.get("actual_fill_fraction")
                or observation.get("actualFillFraction")
                or 0
            ),
            reject_or_miss_reason=observation.get("reject_or_miss_reason")
            or observation.get("rejectOrMissReason"),
        )
    else:
        obs = observation

    lineage_ok = (
        obs.matched_decision_id and obs.matched_decision_id == pred.decision_id
    ) or (obs.paper_order_id and obs.paper_order_id == pred.order_id)
    if not lineage_ok:
        return ExecutionGapMeasurement(
            decision_id=pred.decision_id,
            order_id=pred.order_id,
            symbol=pred.symbol,
            matched=False,
            state=MeasurementState.UNMEASURED.value,
            prediction=pred.public_dict(),
            observation=obs.public_dict(),
            blockers=["LINEAGE_MISMATCH_UNMATCHED"],
        )

    slip_gap = None
    if pred.predicted_slippage_bps is not None and obs.observed_spread_bps is not None:
        slip_gap = float(obs.observed_spread_bps) - float(pred.predicted_slippage_bps)
    lat_gap = None
    if pred.predicted_latency_ms is not None and obs.observed_latency_ms is not None:
        lat_gap = float(obs.observed_latency_ms) - float(pred.predicted_latency_ms)
    fill_gap = None
    if pred.predicted_fill_probability is not None:
        fill_gap = float(obs.actual_fill_fraction) - float(pred.predicted_fill_probability)

    return ExecutionGapMeasurement(
        decision_id=pred.decision_id,
        order_id=pred.order_id,
        symbol=pred.symbol,
        matched=True,
        state=MeasurementState.OBSERVED.value,
        prediction=pred.public_dict(),
        observation=obs.public_dict(),
        slippage_gap_bps=slip_gap,
        latency_gap_ms=lat_gap,
        fill_fraction_gap=fill_gap,
    )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
