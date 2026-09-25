"""Honest performance metrics — unmeasured stays UNMEASURED."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Sequence

from .instruments import InstrumentFamily, InstrumentSpec
from .types import MetricStatus, WinRateDefinition

# Documented timeframe fallback only — never sole source when family/calendar known.
TIMEFRAME_PERIODS_FALLBACK: dict[str, float] = {
    "1m": 252.0 * 6.5 * 60.0,  # ~US equity cash session minutes
    "5m": 252.0 * 6.5 * 12.0,
    "15m": 252.0 * 6.5 * 4.0,
    "1h": 252.0 * 6.5,
    "4h": 252.0 * 6.5 / 4.0,
    "1D": 252.0,
    "1d": 252.0,
}

# Asset-family continuous calendars (bars per year for continuous 24/7 markets).
_CRYPTO_CONTINUOUS: dict[str, float] = {
    "1m": 365.0 * 24.0 * 60.0,
    "5m": 365.0 * 24.0 * 12.0,
    "15m": 365.0 * 24.0 * 4.0,
    "1h": 365.0 * 24.0,
    "4h": 365.0 * 6.0,
    "1D": 365.0,
    "1d": 365.0,
}

# US listed equity cash-session approximate hours (not overnight).
_US_EQUITY_SESSION: dict[str, float] = {
    "1m": 252.0 * 6.5 * 60.0,
    "5m": 252.0 * 6.5 * 12.0,
    "15m": 252.0 * 6.5 * 4.0,
    "1h": 252.0 * 6.5,
    "4h": 252.0 * 6.5 / 4.0,
    "1D": 252.0,
    "1d": 252.0,
}

_MIN_OBSERVED_INTERVALS = 20


def _parse_ts(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _observed_periods_per_year(timestamps: Sequence[str]) -> float | None:
    """Estimate bars/year from observed deltas — requires a long enough sample."""
    parsed = [p for p in (_parse_ts(t) for t in timestamps) if p is not None]
    if len(parsed) < _MIN_OBSERVED_INTERVALS + 1:
        return None
    deltas_sec: list[float] = []
    for i in range(1, len(parsed)):
        sec = (parsed[i] - parsed[i - 1]).total_seconds()
        if sec > 0:
            deltas_sec.append(sec)
    if len(deltas_sec) < _MIN_OBSERVED_INTERVALS:
        return None
    deltas_sec.sort()
    median = deltas_sec[len(deltas_sec) // 2]
    if median <= 0:
        return None
    return (365.25 * 24.0 * 3600.0) / median


def resolve_periods_per_year(
    *,
    timeframe: str | None = None,
    instrument_family: str | InstrumentFamily | None = None,
    instrument_spec: InstrumentSpec | dict[str, Any] | None = None,
    bar_timestamps: Sequence[str] | None = None,
    explicit_periods: float | None = None,
) -> dict[str, Any]:
    """Resolve annualization with provenance.

    Order:
      1. explicit InstrumentSpec calendar/session metadata (or explicit_periods)
      2. observed timestamp/session statistics (sufficient sample)
      3. asset-family calendar
      4. documented timeframe fallback

    If none responsible → UNMEASURED.
    """
    tf = (timeframe or "").strip() or "1D"
    meta: dict[str, Any] = {}
    family_raw: str | None = None

    if isinstance(instrument_spec, InstrumentSpec):
        meta = dict(instrument_spec.metadata or {})
        family_raw = instrument_spec.family.value
        if timeframe is None and meta.get("timeframe"):
            tf = str(meta["timeframe"])
    elif isinstance(instrument_spec, dict):
        meta = dict(instrument_spec.get("metadata") or instrument_spec)
        family_raw = instrument_spec.get("family") or meta.get("family")

    if instrument_family is not None:
        family_raw = (
            instrument_family.value
            if isinstance(instrument_family, InstrumentFamily)
            else str(instrument_family)
        )

    # 1) Explicit calendar / periods on instrument
    if explicit_periods is not None and explicit_periods > 0:
        return {
            "status": MetricStatus.MEASURED.value,
            "value": float(explicit_periods),
            "annualization_source": "instrument_calendar",
            "timeframe": tf,
            "instrument_family": family_raw,
        }
    for key in ("periods_per_year", "bars_per_year", "annualization_periods"):
        if meta.get(key) is not None:
            try:
                val = float(meta[key])
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                return {
                    "status": MetricStatus.MEASURED.value,
                    "value": val,
                    "annualization_source": "instrument_calendar",
                    "timeframe": tf,
                    "instrument_family": family_raw,
                }
    session = meta.get("session") or meta.get("trading_calendar")
    if isinstance(session, dict) and session.get("periods_per_year"):
        try:
            val = float(session["periods_per_year"])
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return {
                "status": MetricStatus.MEASURED.value,
                "value": val,
                "annualization_source": "instrument_calendar",
                "timeframe": tf,
                "instrument_family": family_raw,
            }

    # 2) Observed frequency
    if bar_timestamps:
        observed = _observed_periods_per_year(bar_timestamps)
        if observed is not None and observed > 0:
            return {
                "status": MetricStatus.MEASURED.value,
                "value": float(observed),
                "annualization_source": "observed_frequency",
                "timeframe": tf,
                "instrument_family": family_raw,
            }

    # 3) Asset-family defaults
    family = (family_raw or "").lower()
    if family in {InstrumentFamily.CRYPTO_SPOT.value, "crypto", "crypto_spot"}:
        crypto_val = _CRYPTO_CONTINUOUS.get(tf)
        if crypto_val is not None:
            return {
                "status": MetricStatus.MEASURED.value,
                "value": float(crypto_val),
                "annualization_source": "asset_family_default",
                "timeframe": tf,
                "instrument_family": family_raw or InstrumentFamily.CRYPTO_SPOT.value,
            }
    if family in {InstrumentFamily.EQUITY.value, "equity", "stock", "us_equity"}:
        eq_val = _US_EQUITY_SESSION.get(tf)
        if eq_val is not None:
            return {
                "status": MetricStatus.MEASURED.value,
                "value": float(eq_val),
                "annualization_source": "asset_family_default",
                "timeframe": tf,
                "instrument_family": family_raw or InstrumentFamily.EQUITY.value,
            }

    # 4) Documented timeframe fallback
    fallback = TIMEFRAME_PERIODS_FALLBACK.get(tf)
    if fallback is not None and fallback > 0:
        return {
            "status": MetricStatus.MEASURED.value,
            "value": float(fallback),
            "annualization_source": "fallback",
            "timeframe": tf,
            "instrument_family": family_raw,
        }

    return {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "annualization_source": "unresolved",
        "reason": "annualization not responsibly determined",
        "timeframe": tf,
        "instrument_family": family_raw,
    }


def _safe_sharpe(
    returns: Sequence[float],
    *,
    periods_per_year: float | None,
    annualization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ann = annualization or {}
    if periods_per_year is None or periods_per_year <= 0:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "annualization unresolved",
            "annualization_source": ann.get("annualization_source", "unresolved"),
        }
    if len(returns) < 2:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "insufficient returns",
            "annualization_source": ann.get("annualization_source"),
        }
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std <= 0:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "zero volatility",
            "annualization_source": ann.get("annualization_source"),
        }
    sharpe = (mean / std) * math.sqrt(periods_per_year)
    return {
        "status": MetricStatus.MEASURED.value,
        "value": sharpe,
        "periods_per_year": periods_per_year,
        "annualization_source": ann.get("annualization_source"),
    }


def _safe_sortino(
    returns: Sequence[float],
    *,
    periods_per_year: float | None,
    annualization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ann = annualization or {}
    if periods_per_year is None or periods_per_year <= 0:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "annualization unresolved",
            "annualization_source": ann.get("annualization_source", "unresolved"),
        }
    if len(returns) < 2:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "insufficient returns",
            "annualization_source": ann.get("annualization_source"),
        }
    mean = sum(returns) / len(returns)
    downside = [min(0.0, r) for r in returns]
    downside_var = sum(d ** 2 for d in downside) / (len(returns) - 1)
    downside_std = math.sqrt(downside_var)
    if downside_std <= 0:
        return {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "no downside",
            "annualization_source": ann.get("annualization_source"),
        }
    sortino = (mean / downside_std) * math.sqrt(periods_per_year)
    return {
        "status": MetricStatus.MEASURED.value,
        "value": sortino,
        "periods_per_year": periods_per_year,
        "annualization_source": ann.get("annualization_source"),
    }


def max_drawdown(equity: Sequence[float]) -> dict[str, Any]:
    if len(equity) < 2:
        return {"status": MetricStatus.UNMEASURED.value, "value": None, "reason": "insufficient equity points"}
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return {"status": MetricStatus.MEASURED.value, "value": max_dd}


def _win_rate_from_pnls(
    pnls: Sequence[float],
    *,
    definition: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wins = sum(1 for r in pnls if r > 0)
    losses = sum(1 for r in pnls if r < 0)
    gross_profit = sum(r for r in pnls if r > 0)
    gross_loss = abs(sum(r for r in pnls if r < 0))
    total_closed = wins + losses
    if not total_closed:
        return (
            {
                "status": MetricStatus.UNMEASURED.value,
                "value": None,
                "reason": "no non-zero closed PnL samples",
                "definition": definition,
            },
            {
                "status": MetricStatus.UNMEASURED.value,
                "value": None,
                "reason": "requires closed-trade PnL attribution",
                "definition": definition,
            },
        )
    win_rate = {
        "status": MetricStatus.MEASURED.value,
        "value": wins / total_closed,
        "definition": definition,
        "wins": wins,
        "losses": losses,
        "sample_size": total_closed,
    }
    if gross_loss > 0:
        profit_factor = {
            "status": MetricStatus.MEASURED.value,
            "value": gross_profit / gross_loss,
            "definition": definition,
        }
    elif gross_profit > 0:
        profit_factor = {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "no losses — infinite profit factor not claimed",
            "definition": definition,
        }
    else:
        profit_factor = {
            "status": MetricStatus.UNMEASURED.value,
            "value": None,
            "reason": "no gross profit/loss",
            "definition": definition,
        }
    return win_rate, profit_factor


def compute_metrics(
    *,
    equity: Sequence[float],
    fills: Sequence[dict[str, Any]],
    initial_cash: float,
    benchmark_equity: Sequence[float] | None = None,
    causality_violations: int = 0,
    brain_hits: int = 0,
    brain_misses: int = 0,
    agreement_rate: float | None = None,
    veto_rate: float | None = None,
    periods_per_year: float | None = 252.0,
    annualization: dict[str, Any] | None = None,
    closed_trades: Sequence[dict[str, Any]] | None = None,
    timeframe: str | None = None,
    instrument_family: str | None = None,
    instrument_spec: InstrumentSpec | dict[str, Any] | None = None,
    bar_timestamps: Sequence[str] | None = None,
) -> dict[str, Any]:
    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev > 0:
            returns.append((equity[i] - prev) / prev)

    total_return = None
    total_return_status = MetricStatus.UNMEASURED.value
    if equity and initial_cash > 0:
        total_return = (equity[-1] / initial_cash) - 1.0
        total_return_status = MetricStatus.MEASURED.value

    fees_paid = 0.0
    turnover = 0.0
    for fill in fills:
        fees_paid += float(fill.get("fee") or 0.0)
        turnover += abs(float(fill.get("qty") or 0.0) * float(fill.get("price") or 0.0))

    # Closed-trade win rate is canonical; fill-level is separately labeled.
    closed_trade_win_rate: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "PositionEpisode / ClosedTrade ledger not provided",
        "definition": WinRateDefinition.CLOSED_POSITION_EPISODE.value,
    }
    closed_trade_profit_factor: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "requires ClosedTrade PnL attribution",
        "definition": WinRateDefinition.CLOSED_POSITION_EPISODE.value,
    }

    win_rate: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "round-trip ledger not yet attributed per trade",
        "definition": WinRateDefinition.UNMEASURED.value,
    }
    profit_factor: dict[str, Any] = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "requires closed-trade PnL attribution",
        "definition": WinRateDefinition.UNMEASURED.value,
    }

    closed_payloads = list(closed_trades or [])
    if closed_payloads:
        episode_pnls = [
            float(t["net_pnl"])
            for t in closed_payloads
            if t.get("net_pnl") is not None
        ]
        closed_trade_win_rate, closed_trade_profit_factor = _win_rate_from_pnls(
            episode_pnls,
            definition=WinRateDefinition.CLOSED_POSITION_EPISODE.value,
        )
        win_rate = dict(closed_trade_win_rate)
        profit_factor = dict(closed_trade_profit_factor)
    else:
        # Fill-level realized_delta may support P0 interim metric — never claim
        # it equals closed-position-episode win rate.
        realized = [
            float(f["realized_delta"])
            for f in fills
            if f.get("realized_delta") is not None
        ]
        if realized:
            fill_wr, fill_pf = _win_rate_from_pnls(
                realized,
                definition=WinRateDefinition.FILL_LEVEL_REALIZED_DELTA.value,
            )
            win_rate = fill_wr
            profit_factor = fill_pf

    buy_hold = {
        "status": MetricStatus.UNMEASURED.value,
        "value": None,
        "reason": "benchmark equity not provided",
    }
    if benchmark_equity and len(benchmark_equity) >= 2 and benchmark_equity[0] > 0:
        buy_hold = {
            "status": MetricStatus.MEASURED.value,
            "value": (benchmark_equity[-1] / benchmark_equity[0]) - 1.0,
        }

    excess_return = None
    excess_status = MetricStatus.UNMEASURED.value
    excess_reason = "requires measured total_return and buy_and_hold_return"
    if (
        total_return is not None
        and buy_hold.get("status") == MetricStatus.MEASURED.value
        and buy_hold.get("value") is not None
    ):
        excess_return = float(total_return) - float(buy_hold["value"])
        excess_status = MetricStatus.MEASURED.value
        excess_reason = ""

    brain_total = brain_hits + brain_misses
    brain_hit_rate = {
        "status": MetricStatus.MEASURED.value if brain_total else MetricStatus.UNMEASURED.value,
        "value": (brain_hits / brain_total) if brain_total else None,
        "hits": brain_hits,
        "misses": brain_misses,
    }

    if annualization is None:
        if periods_per_year is not None and timeframe is None and instrument_family is None and instrument_spec is None:
            # Backward-compatible explicit override (legacy callers pass 252.0).
            annualization = {
                "status": MetricStatus.MEASURED.value,
                "value": float(periods_per_year),
                "annualization_source": "explicit" if periods_per_year != 252.0 else "fallback",
            }
        else:
            annualization = resolve_periods_per_year(
                timeframe=timeframe,
                instrument_family=instrument_family,
                instrument_spec=instrument_spec,
                bar_timestamps=bar_timestamps,
                explicit_periods=periods_per_year if periods_per_year is not None and timeframe is not None else (
                    periods_per_year if periods_per_year is not None and periods_per_year != 252.0 else None
                ),
            )
            # Legacy default: if nothing else provided, keep 252 fallback for callers
            # that only pass equity/fills (characterization of compute_metrics signature).
            if (
                annualization.get("status") == MetricStatus.UNMEASURED.value
                and periods_per_year is not None
                and timeframe is None
                and instrument_family is None
                and instrument_spec is None
                and not bar_timestamps
            ):
                annualization = {
                    "status": MetricStatus.MEASURED.value,
                    "value": float(periods_per_year),
                    "annualization_source": "fallback",
                }

    ppy = annualization.get("value")
    if annualization.get("status") != MetricStatus.MEASURED.value:
        ppy = None

    dd = max_drawdown(equity)
    trade_count_value = len(closed_payloads) if closed_payloads else len(fills)

    total_return_block = {"status": total_return_status, "value": total_return}
    result = {
        "total_return": total_return_block,
        # Acceptance-aligned pct aliases (fraction * 100) — same measurement, labeled unit.
        "total_return_pct": {
            "status": total_return_status,
            "value": (total_return * 100.0) if total_return is not None else None,
            "unit": "percent",
        },
        "sharpe": _safe_sharpe(returns, periods_per_year=ppy, annualization=annualization),
        "sortino": _safe_sortino(returns, periods_per_year=ppy, annualization=annualization),
        "max_drawdown": dd,
        "max_drawdown_pct": {
            "status": dd["status"],
            "value": (float(dd["value"]) * 100.0) if dd.get("value") is not None else None,
            "unit": "percent",
            "reason": dd.get("reason"),
        },
        "win_rate": win_rate,
        "closed_trade_win_rate": closed_trade_win_rate,
        "profit_factor": profit_factor,
        "closed_trade_profit_factor": closed_trade_profit_factor,
        "turnover": {"status": MetricStatus.MEASURED.value, "value": turnover},
        "fees_paid": {"status": MetricStatus.MEASURED.value, "value": fees_paid},
        "trade_count": {
            "status": MetricStatus.MEASURED.value,
            "value": trade_count_value,
            "definition": (
                "closed_position_episodes"
                if closed_payloads
                else "fills"
            ),
        },
        "buy_and_hold_return": buy_hold,
        "excess_return": {
            "status": excess_status,
            "value": excess_return,
            **({"reason": excess_reason} if excess_reason else {}),
        },
        "excess_return_pct": {
            "status": excess_status,
            "value": (excess_return * 100.0) if excess_return is not None else None,
            "unit": "percent",
            **({"reason": excess_reason} if excess_reason else {}),
        },
        "causality_violations": {
            "status": MetricStatus.MEASURED.value,
            "value": causality_violations,
        },
        "brain_hit_rate": brain_hit_rate,
        "annualization": annualization,
        "closed_trade_count": {
            "status": MetricStatus.MEASURED.value if closed_payloads else MetricStatus.UNMEASURED.value,
            "value": len(closed_payloads) if closed_payloads else None,
            **(
                {}
                if closed_payloads
                else {"reason": "no ClosedTrade / PositionEpisode samples"}
            ),
        },
        "deliberation": {
            "agreement_rate": {
                "status": MetricStatus.MEASURED.value if agreement_rate is not None else MetricStatus.UNMEASURED.value,
                "value": agreement_rate,
            },
            "veto_rate": {
                "status": MetricStatus.MEASURED.value if veto_rate is not None else MetricStatus.UNMEASURED.value,
                "value": veto_rate,
            },
        },
        "truth": {
            "unmeasured_stays_unmeasured": True,
            "no_fabricated_metrics": True,
            "win_rate_not_sell_fill_ratio": True,
            "ohlcv_execution_is_modelled": True,
        },
    }
    return result
