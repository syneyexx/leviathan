"""W45 — Enterprise risk aggregation: market / factor / concentration.

Extends risk_analytics + risk_guard — no RiskEngineV2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH, rollup_states


@dataclass
class PositionRiskInput:
    instrument_id: str
    mv: float  # market value signed
    portfolio_id: str = "default"
    strategy_id: str | None = None
    factor_loadings: dict[str, float] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "mv": self.mv,
            "portfolioId": self.portfolio_id,
            "strategyId": self.strategy_id,
            "factorLoadings": dict(self.factor_loadings),
        }


@dataclass
class ConcentrationBucket:
    key: str
    gross_mv: float
    net_mv: float
    weight_pct: float
    state: str = MeasurementState.MEASURED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "grossMv": self.gross_mv,
            "netMv": self.net_mv,
            "weightPct": self.weight_pct,
            "state": self.state,
        }


@dataclass
class EnterpriseRiskReport:
    nav: float
    gross_exposure: StatusedValue
    net_exposure: StatusedValue
    var_95: StatusedValue
    factor_exposures: dict[str, StatusedValue]
    concentration_by_instrument: list[ConcentrationBucket]
    concentration_by_portfolio: list[ConcentrationBucket]
    rollup: str
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "nav": self.nav,
            "grossExposure": self.gross_exposure.public_dict(),
            "netExposure": self.net_exposure.public_dict(),
            "var95": self.var_95.public_dict(),
            "factorExposures": {k: v.public_dict() for k, v in self.factor_exposures.items()},
            "concentrationByInstrument": [c.public_dict() for c in self.concentration_by_instrument],
            "concentrationByPortfolio": [c.public_dict() for c in self.concentration_by_portfolio],
            "rollup": self.rollup,
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_risk_analytics": True,
                "not_risk_engine_v2": True,
            },
        }


def _buckets(
    items: Sequence[tuple[str, float]],
    *,
    nav: float,
) -> list[ConcentrationBucket]:
    grouped: dict[str, list[float]] = {}
    for key, mv in items:
        grouped.setdefault(key, []).append(mv)
    out: list[ConcentrationBucket] = []
    for key, mvs in sorted(grouped.items()):
        gross = sum(abs(x) for x in mvs)
        net = sum(mvs)
        weight = (gross / nav * 100.0) if nav else 0.0
        state = MeasurementState.MEASURED.value if nav else MeasurementState.INFEASIBLE.value
        out.append(
            ConcentrationBucket(
                key=key, gross_mv=gross, net_mv=net, weight_pct=weight, state=state
            )
        )
    out.sort(key=lambda b: b.gross_mv, reverse=True)
    return out


def aggregate_enterprise_risk(
    positions: Sequence[PositionRiskInput | Mapping[str, Any]],
    *,
    nav: float,
    returns: Sequence[float] | None = None,
) -> EnterpriseRiskReport:
    normalized: list[PositionRiskInput] = []
    for raw in positions:
        if isinstance(raw, PositionRiskInput):
            normalized.append(raw)
        else:
            normalized.append(
                PositionRiskInput(
                    instrument_id=str(raw.get("instrument_id") or raw.get("instrumentId") or ""),
                    mv=float(raw.get("mv") or 0),
                    portfolio_id=str(raw.get("portfolio_id") or raw.get("portfolioId") or "default"),
                    strategy_id=(
                        None
                        if raw.get("strategy_id", raw.get("strategyId")) is None
                        else str(raw.get("strategy_id") or raw.get("strategyId"))
                    ),
                    factor_loadings=dict(raw.get("factor_loadings") or raw.get("factorLoadings") or {}),
                )
            )

    gross = sum(abs(p.mv) for p in normalized)
    net = sum(p.mv for p in normalized)
    notes: list[str] = []

    # Historical VaR via existing risk_analytics owner when returns provided.
    var_value: float | None = None
    var_state = MeasurementState.UNMEASURED
    if returns is None:
        notes.append("var_UNMEASURED_no_returns")
    else:
        try:
            from ..risk_analytics import historical_var_from_returns

            var_value, status = historical_var_from_returns(returns)
            var_state = MeasurementState(status) if status in MeasurementState.__members__ else MeasurementState.OBSERVED
            if status == "INSUFFICIENT_HISTORY":
                var_state = MeasurementState.INSUFFICIENT_HISTORY
        except Exception as exc:  # noqa: BLE001
            notes.append(f"var_import_failed:{exc}")
            var_state = MeasurementState.UNAVAILABLE

    factor_acc: dict[str, float] = {}
    any_factors = False
    for pos in normalized:
        if pos.factor_loadings:
            any_factors = True
        for factor, loading in pos.factor_loadings.items():
            factor_acc[factor] = factor_acc.get(factor, 0.0) + float(loading) * pos.mv

    if not any_factors:
        factor_exposures = {
            "_all": StatusedValue(None, MeasurementState.UNMEASURED, notes=["no_factor_loadings"])
        }
        notes.append("factor_exposures_UNMEASURED")
    else:
        factor_exposures = {
            k: StatusedValue(v, MeasurementState.ESTIMATED, unit="mv_weighted", methodology="sum_loading_times_mv")
            for k, v in sorted(factor_acc.items())
        }
        notes.append("factor_exposures_ESTIMATED_not_full_cov_model")

    by_inst = _buckets([(p.instrument_id, p.mv) for p in normalized], nav=nav)
    by_port = _buckets([(p.portfolio_id, p.mv) for p in normalized], nav=nav)

    states = [
        MeasurementState.MEASURED if nav else MeasurementState.INFEASIBLE,
        var_state,
        MeasurementState.ESTIMATED if any_factors else MeasurementState.UNMEASURED,
    ]
    return EnterpriseRiskReport(
        nav=nav,
        gross_exposure=StatusedValue(
            gross, MeasurementState.MEASURED if normalized else MeasurementState.EMPTY, unit="currency"
        ),
        net_exposure=StatusedValue(
            net, MeasurementState.MEASURED if normalized else MeasurementState.EMPTY, unit="currency"
        ),
        var_95=StatusedValue(var_value, var_state, methodology="historical_var_from_returns"),
        factor_exposures=factor_exposures,
        concentration_by_instrument=by_inst,
        concentration_by_portfolio=by_port,
        rollup=rollup_states(states).value,
        notes=notes,
    )
