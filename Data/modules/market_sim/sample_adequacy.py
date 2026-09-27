"""Institutional sample-adequacy gates — min_trades=5 is never enough alone.

Insufficient evidence must surface as INSUFFICIENT_EVIDENCE, never PASS.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


# Conservative institutional floor — not a profitability claim.
DEFAULT_MIN_TRADES = 30
DEFAULT_MIN_EFFECTIVE_SAMPLE = 20
DEFAULT_MIN_CALENDAR_DAYS = 60
DEFAULT_MIN_REGIME_BUCKETS = 2


def _finite(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        if raw.get("status") == "UNMEASURED" or raw.get("value") is None:
            return None
        raw = raw.get("value")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def estimate_effective_sample_size(
    *,
    trade_count: float | None,
    n_returns: float | None = None,
    autocorr: float | None = None,
) -> dict[str, Any]:
    """Block-bootstrap style ESS approximation. Labels remain APPROXIMATE."""
    n = n_returns if n_returns is not None else trade_count
    if n is None:
        return {
            "effective_sample_size": None,
            "status": "UNMEASURED",
            "method": "APPROXIMATE",
            "qualification_authority": False,
        }
    n = float(n)
    if n <= 0:
        return {
            "effective_sample_size": 0.0,
            "status": "MEASURED",
            "method": "APPROXIMATE",
            "qualification_authority": False,
        }
    rho = autocorr if autocorr is not None else 0.0
    rho = max(min(float(rho), 0.99), -0.99)
    # Classical ESS ≈ n * (1-ρ)/(1+ρ) for AR(1)-like dependence.
    ess = n * (1.0 - rho) / (1.0 + rho) if abs(1.0 + rho) > 1e-12 else n
    ess = max(0.0, ess)
    return {
        "effective_sample_size": ess,
        "n": n,
        "autocorr": rho,
        "status": "MEASURED",
        "method": "APPROXIMATE",
        "qualification_authority": False,
        "truth": {"approximate_not_exact": True},
    }


def assess_sample_adequacy(
    *,
    metrics: dict[str, Any] | None = None,
    trade_count: float | None = None,
    calendar_days: float | None = None,
    regime_labels: Sequence[str] | None = None,
    autocorr: float | None = None,
    min_trades: int = DEFAULT_MIN_TRADES,
    min_effective_sample: float = DEFAULT_MIN_EFFECTIVE_SAMPLE,
    min_calendar_days: float = DEFAULT_MIN_CALENDAR_DAYS,
    min_regime_buckets: int = DEFAULT_MIN_REGIME_BUCKETS,
    institutional: bool = True,
) -> dict[str, Any]:
    """Fail-closed sample adequacy. Institutional defaults reject tiny samples."""
    m = dict(metrics or {})
    trades = trade_count
    if trades is None:
        trades = _finite(m.get("trade_count"))
        if trades is None:
            trades = _finite(m.get("trades"))
    days = calendar_days
    if days is None:
        days = _finite(m.get("calendar_days")) or _finite(m.get("span_days"))
    n_returns = _finite(m.get("n_returns")) or _finite(m.get("bar_count"))
    rho = autocorr if autocorr is not None else _finite(m.get("return_autocorr"))
    ess = estimate_effective_sample_size(trade_count=trades, n_returns=n_returns, autocorr=rho)

    # Non-institutional callers may still use a low min_trades, but we label honesty.
    effective_min_trades = int(min_trades)
    if institutional and effective_min_trades < DEFAULT_MIN_TRADES:
        # Do not silently raise caller's threshold mid-evaluation; report the gap.
        threshold_note = {
            "configured_min_trades": effective_min_trades,
            "institutional_floor": DEFAULT_MIN_TRADES,
            "below_institutional_floor": True,
        }
    else:
        threshold_note = {
            "configured_min_trades": effective_min_trades,
            "institutional_floor": DEFAULT_MIN_TRADES,
            "below_institutional_floor": False,
        }

    gaps: list[str] = []
    if trades is None:
        gaps.append("trade_count_UNMEASURED")
    elif trades < effective_min_trades:
        gaps.append(f"trades {trades} < {effective_min_trades}")

    ess_val = ess.get("effective_sample_size")
    if ess_val is None:
        gaps.append("effective_sample_size_UNMEASURED")
    elif float(ess_val) < float(min_effective_sample):
        gaps.append(f"ess {ess_val} < {min_effective_sample}")

    if days is None:
        gaps.append("calendar_span_UNMEASURED")
    elif float(days) < float(min_calendar_days):
        gaps.append(f"calendar_days {days} < {min_calendar_days}")

    regimes = [str(r) for r in (regime_labels or m.get("regime_labels") or []) if r]
    if regimes:
        unique = {r for r in regimes}
        if len(unique) < int(min_regime_buckets):
            gaps.append(f"regime_buckets {len(unique)} < {min_regime_buckets}")
    else:
        gaps.append("regime_coverage_UNMEASURED")

    adequate = len(gaps) == 0
    return {
        "adequate": adequate,
        "status": "ADEQUATE" if adequate else "INSUFFICIENT_EVIDENCE",
        "gaps": gaps,
        "trade_count": trades,
        "calendar_days": days,
        "regime_bucket_count": len(set(regimes)) if regimes else None,
        "effective_sample": ess,
        "thresholds": {
            "min_trades": effective_min_trades,
            "min_effective_sample": min_effective_sample,
            "min_calendar_days": min_calendar_days,
            "min_regime_buckets": min_regime_buckets,
            **threshold_note,
        },
        "truth": {
            "insufficient_is_not_pass": True,
            "min_trades_5_not_institutional": True,
            "qualification_authority": adequate,
            "live_money": "BLOCKED",
        },
    }


def gate_qualification_on_sample(
    *,
    metrics: dict[str, Any] | None,
    acceptance_passed: bool,
    **kwargs: Any,
) -> dict[str, Any]:
    """Combine acceptance with sample adequacy — never promote on tiny samples."""
    adequacy = assess_sample_adequacy(metrics=metrics, **kwargs)
    if acceptance_passed and not adequacy["adequate"]:
        return {
            "passed": False,
            "reason": "INSUFFICIENT_EVIDENCE",
            "acceptance_passed": True,
            "sample_adequacy": adequacy,
            "truth": {"no_false_pass_on_small_sample": True},
        }
    return {
        "passed": bool(acceptance_passed and adequacy["adequate"]),
        "reason": "OK" if acceptance_passed and adequacy["adequate"] else (
            "ACCEPTANCE_FAILED" if not acceptance_passed else "INSUFFICIENT_EVIDENCE"
        ),
        "acceptance_passed": bool(acceptance_passed),
        "sample_adequacy": adequacy,
        "truth": {"no_false_pass_on_small_sample": True},
    }
