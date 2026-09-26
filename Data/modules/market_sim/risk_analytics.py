"""Institutional risk analytics helpers (W17) — extend risk_guard owner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class RiskAnalyticsReport:
    var_95: float | None
    var_status: str  # MEASURED | UNMEASURED | INSUFFICIENT_HISTORY
    max_drawdown_pct: float | None
    exposure_pct: float
    factor_exposures: dict[str, float] = field(default_factory=dict)
    factor_status: str = "UNMEASURED"
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "var95": self.var_95,
            "varStatus": self.var_status,
            "maxDrawdownPct": self.max_drawdown_pct,
            "exposurePct": self.exposure_pct,
            "factorExposures": dict(self.factor_exposures),
            "factorStatus": self.factor_status,
            "notes": list(self.notes),
            "truth": {
                "factor_risk_engine_not_claimed": self.factor_status != "MEASURED" or not self.factor_exposures,
                "var_from_returns_is_historical_not_parametric_unless_labelled": True,
            },
        }


def historical_var_from_returns(
    returns: Sequence[float],
    *,
    confidence: float = 0.95,
) -> tuple[float | None, str]:
    vals = [float(r) for r in returns]
    if len(vals) < 10:
        return None, "INSUFFICIENT_HISTORY"
    ordered = sorted(vals)
    idx = max(0, int((1.0 - confidence) * len(ordered)) - 1)
    # VaR as positive loss number
    return abs(min(0.0, ordered[idx])), "MEASURED"


def compute_risk_analytics(
    *,
    returns: Sequence[float],
    equity: float,
    gross_exposure: float,
    peak_equity: float | None = None,
    factor_loadings: dict[str, float] | None = None,
) -> RiskAnalyticsReport:
    var, var_status = historical_var_from_returns(returns)
    dd = None
    if peak_equity and peak_equity > 0 and equity >= 0:
        dd = max(0.0, (peak_equity - equity) / peak_equity * 100.0)
    exposure_pct = (gross_exposure / equity * 100.0) if equity > 0 else 0.0
    factors = dict(factor_loadings or {})
    factor_status = "MEASURED" if factors else "UNMEASURED"
    notes: list[str] = []
    if factor_status == "UNMEASURED":
        notes.append("factor_exposures_UNMEASURED")
    if var_status != "MEASURED":
        notes.append(f"var_{var_status}")
    return RiskAnalyticsReport(
        var_95=var,
        var_status=var_status,
        max_drawdown_pct=dd,
        exposure_pct=exposure_pct,
        factor_exposures=factors,
        factor_status=factor_status,
        notes=notes,
    )
