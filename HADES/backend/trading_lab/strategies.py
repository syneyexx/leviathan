"""Strategy Runtime and strategy family library.

A strategy never produces a fill price and never touches the ledger. It reads an
:class:`Observation` (already clock-filtered) and returns a **target exposure** per
instrument, expressed as a signed fraction of equity, plus the metadata the decision record
needs: the signal, its uncertainty in plain words, and any no-trade reason.

Turning targets into orders is the runtime's job (:class:`StrategyRuntime`), so every family
inherits the same sizing, rounding, short-permission and capability handling instead of
reimplementing it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

from trading_lab.capabilities import STRATEGY_CAPABILITIES
from trading_lab.contracts import (
    DataLevel,
    InstrumentSpec,
    Observation,
    OrderIntent,
    SizingSpec,
    StrategySpec,
    to_decimal,
)
from trading_lab.features import donchian, ema, ols_beta, realized_volatility, sma, zscore

ZERO = Decimal("0")
ONE = Decimal("1")

LEGACY_FAMILY_ALIASES = {
    "sma_crossover": "trend_following",
    "momentum": "momentum",
    "mean_reversion": "mean_reversion",
}


@dataclass
class StrategyContext:
    """Everything a strategy may read. All of it is already point-in-time filtered."""

    as_of: str
    observations: dict[str, Observation]
    positions: dict[str, Decimal]
    equity: Decimal
    specs: dict[str, InstrumentSpec]
    auxiliary: Callable[[str, str], list[dict[str, Any]]] = field(default=lambda _i, _k: [])
    models: dict[str, Any] = field(default_factory=dict)
    event_count: int = 0

    def closes(self, instrument_id: str) -> list[float]:
        observation = self.observations.get(instrument_id)
        return observation.closes if observation else []

    def highs(self, instrument_id: str) -> list[float]:
        observation = self.observations.get(instrument_id)
        if not observation:
            return []
        return [bar.high if bar.high is not None else bar.reference_price for bar in observation.bars]

    def lows(self, instrument_id: str) -> list[float]:
        observation = self.observations.get(instrument_id)
        if not observation:
            return []
        return [bar.low if bar.low is not None else bar.reference_price for bar in observation.bars]


@dataclass
class StrategyDecision:
    """Target exposure per instrument plus the reasoning-protocol metadata."""

    targets: dict[str, Decimal] = field(default_factory=dict)
    signal: str = "flat"
    uncertainty: str = ""
    no_trade_reason: str = ""
    notes: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""

    @property
    def in_scope(self) -> bool:
        return not self.blocked


class Strategy:
    family = "base"
    required_data_level: DataLevel = "ohlcv"
    min_instruments = 1

    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec
        self.params = dict(spec.params or {})
        self.direction = spec.hypothesis.direction if spec.hypothesis else "long_only"

    # --- helpers -----------------------------------------------------------------

    def warmup(self) -> int:
        return 50

    def _int(self, name: str, default: int) -> int:
        return int(self.params.get(name, default))

    def _float(self, name: str, default: float) -> float:
        return float(self.params.get(name, default))

    def _long_target(self) -> Decimal:
        return ONE if self.direction in {"long_only", "long_short"} else ZERO

    def _short_target(self) -> Decimal:
        return -ONE if self.direction in {"short_only", "long_short"} else ZERO

    def decide(self, ctx: StrategyContext) -> StrategyDecision:  # pragma: no cover - abstract
        raise NotImplementedError


class TrendFollowing(Strategy):
    family = "trend_following"

    def warmup(self) -> int:
        return max(self._int("slow", 30) + 2, 20)

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        closes = ctx.closes(instrument_id)
        fast_window = self._int("fast", 10)
        slow_window = self._int("slow", 30)
        if fast_window < 2 or slow_window <= fast_window:
            return StrategyDecision(blocked=True, block_reason="trend_following requires 2 <= fast < slow")
        if len(closes) < slow_window + 1:
            return StrategyDecision(no_trade_reason=f"warmup: need {slow_window + 1} observations, have {len(closes)}")
        use_ema = bool(self.params.get("use_ema", False))
        fast_series = ema(closes, fast_window) if use_ema else sma(closes, fast_window)
        slow_series = ema(closes, slow_window) if use_ema else sma(closes, slow_window)
        fast_value, slow_value = fast_series[-1], slow_series[-1]
        if fast_value is None or slow_value is None:
            return StrategyDecision(no_trade_reason="moving averages not yet defined")
        separation = abs(fast_value - slow_value) / abs(slow_value) if slow_value else 0.0
        min_separation = self._float("min_separation", 0.0)
        if separation < min_separation:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=f"trend separation {separation:.4f} below min_separation {min_separation}",
            )
        if fast_value > slow_value:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=f"moving-average separation {separation:.4f}; crossover state, not a probability",
                notes={"fast": fast_value, "slow": slow_value, "separation": separation},
            )
        return StrategyDecision(
            targets={instrument_id: self._short_target()},
            signal="short" if self._short_target() != ZERO else "flat",
            uncertainty=f"moving-average separation {separation:.4f}",
            notes={"fast": fast_value, "slow": slow_value, "separation": separation},
        )


class Momentum(Strategy):
    family = "momentum"

    def warmup(self) -> int:
        return self._int("lookback", 20) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        closes = ctx.closes(instrument_id)
        lookback = self._int("lookback", 20)
        threshold = self._float("threshold", 0.01)
        if lookback < 2:
            return StrategyDecision(blocked=True, block_reason="momentum lookback must be >= 2")
        if len(closes) <= lookback:
            return StrategyDecision(no_trade_reason=f"warmup: need {lookback + 1} observations, have {len(closes)}")
        base = closes[-1 - lookback]
        if base == 0:
            return StrategyDecision(no_trade_reason="zero base price")
        change = (closes[-1] / base) - 1.0
        volatility = realized_volatility(closes, min(lookback, len(closes) - 1)) or 0.0
        if change >= threshold:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=f"{lookback}-observation return {change:.4f} against realised volatility {volatility:.4f}",
                notes={"change": change, "volatility": volatility},
            )
        if change <= -threshold:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short" if self._short_target() != ZERO else "flat",
                uncertainty=f"{lookback}-observation return {change:.4f}",
                notes={"change": change, "volatility": volatility},
            )
        return StrategyDecision(
            signal="flat",
            no_trade_reason=f"return {change:.4f} inside the +/-{threshold} no-trade band",
            notes={"change": change},
        )


class Breakout(Strategy):
    family = "breakout"

    def warmup(self) -> int:
        return self._int("window", 20) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        closes = ctx.closes(instrument_id)
        highs = ctx.highs(instrument_id)
        lows = ctx.lows(instrument_id)
        window = self._int("window", 20)
        if len(closes) < window + 2:
            return StrategyDecision(no_trade_reason=f"warmup: need {window + 2} observations, have {len(closes)}")
        upper, lower = donchian(highs, lows, window)
        top, bottom = upper[-1], lower[-1]
        if top is None or bottom is None:
            return StrategyDecision(no_trade_reason="channel not yet defined")
        last = closes[-1]
        if last > top:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=f"close {last} above the prior {window}-observation high {top}",
                notes={"channel_high": top, "channel_low": bottom},
            )
        if last < bottom:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short" if self._short_target() != ZERO else "flat",
                uncertainty=f"close {last} below the prior {window}-observation low {bottom}",
                notes={"channel_high": top, "channel_low": bottom},
            )
        return StrategyDecision(
            signal="flat",
            no_trade_reason="price inside the channel",
            notes={"channel_high": top, "channel_low": bottom},
        )


class MeanReversion(Strategy):
    family = "mean_reversion"

    def warmup(self) -> int:
        return self._int("window", 20) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        closes = ctx.closes(instrument_id)
        window = self._int("window", 20)
        entry = self._float("z_entry", 1.5)
        exit_level = self._float("z_exit", 0.0)
        if window < 5:
            return StrategyDecision(blocked=True, block_reason="mean_reversion window must be >= 5")
        if len(closes) < window + 1:
            return StrategyDecision(no_trade_reason=f"warmup: need {window + 1} observations, have {len(closes)}")
        scores = zscore(closes, window)
        score = scores[-1]
        if score is None:
            return StrategyDecision(no_trade_reason="z-score undefined (zero dispersion)")
        held = ctx.positions.get(instrument_id, ZERO)
        if score <= -entry:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=f"z-score {score:.2f} below -{entry}; reversion is an assumption, not a forecast",
                notes={"zscore": score},
            )
        if score >= entry:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short" if self._short_target() != ZERO else "flat",
                uncertainty=f"z-score {score:.2f} above {entry}",
                notes={"zscore": score},
            )
        if held != ZERO and abs(score) <= abs(exit_level):
            return StrategyDecision(
                targets={instrument_id: ZERO},
                signal="flat",
                uncertainty=f"z-score {score:.2f} reverted inside the exit band",
                notes={"zscore": score},
            )
        if held != ZERO:
            return StrategyDecision(
                targets={instrument_id: ONE if held > 0 else -ONE},
                signal="hold",
                notes={"zscore": score},
            )
        return StrategyDecision(signal="flat", no_trade_reason=f"z-score {score:.2f} inside the entry band")


class PairsTrading(Strategy):
    family = "pairs_trading"
    min_instruments = 2

    def warmup(self) -> int:
        return self._int("window", 60) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        if len(self.spec.instruments) < 2:
            return StrategyDecision(blocked=True, block_reason="pairs_trading needs exactly two instruments")
        left, right = self.spec.instruments[0], self.spec.instruments[1]
        left_closes = ctx.closes(left)
        right_closes = ctx.closes(right)
        window = self._int("window", 60)
        entry = self._float("z_entry", 2.0)
        exit_level = self._float("z_exit", 0.5)
        length = min(len(left_closes), len(right_closes))
        if length < window + 2:
            return StrategyDecision(no_trade_reason=f"warmup: need {window + 2} paired observations, have {length}")
        left_series = [math.log(value) for value in left_closes[-length:] if value > 0]
        right_series = [math.log(value) for value in right_closes[-length:] if value > 0]
        if len(left_series) != len(right_series) or len(left_series) < window + 2:
            return StrategyDecision(no_trade_reason="non-positive prices prevent a log spread")
        beta = ols_beta(left_series[-window:], right_series[-window:])
        if beta is None:
            return StrategyDecision(no_trade_reason="hedge ratio not estimable on this window")
        spread = [left_series[i] - beta * right_series[i] for i in range(len(left_series))]
        scores = zscore(spread, window)
        score = scores[-1]
        if score is None:
            return StrategyDecision(no_trade_reason="spread z-score undefined")
        right_spec = ctx.specs.get(right)
        short_ok = bool(right_spec and right_spec.shorting_allowed)
        notes = {"beta": beta, "zscore": score, "short_leg_available": short_ok}
        if not short_ok:
            notes["degraded"] = "the second leg cannot be shorted; the pair degrades to a single-leg long/flat signal"
        if score >= entry:
            targets = {left: -ONE if ctx.specs[left].shorting_allowed else ZERO, right: ONE if short_ok else ZERO}
            return StrategyDecision(
                targets=targets,
                signal="short_spread",
                uncertainty=f"spread z-score {score:.2f}; hedge ratio {beta:.3f} re-estimated each observation",
                notes=notes,
            )
        if score <= -entry:
            targets = {left: ONE, right: -ONE if short_ok else ZERO}
            return StrategyDecision(
                targets=targets,
                signal="long_spread",
                uncertainty=f"spread z-score {score:.2f}; hedge ratio {beta:.3f}",
                notes=notes,
            )
        if abs(score) <= exit_level:
            return StrategyDecision(targets={left: ZERO, right: ZERO}, signal="flat", notes=notes)
        return StrategyDecision(signal="flat", no_trade_reason=f"spread z-score {score:.2f} inside the band", notes=notes)


class StatisticalArbitrage(Strategy):
    family = "statistical_arbitrage"
    min_instruments = 3

    def warmup(self) -> int:
        return self._int("lookback", 20) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instruments = [item for item in self.spec.instruments if ctx.closes(item)]
        if len(instruments) < 3:
            return StrategyDecision(blocked=True, block_reason="statistical_arbitrage needs at least three instruments")
        lookback = self._int("lookback", 20)
        scores: dict[str, float] = {}
        for instrument_id in instruments:
            closes = ctx.closes(instrument_id)
            if len(closes) <= lookback:
                continue
            base = closes[-1 - lookback]
            if base == 0:
                continue
            scores[instrument_id] = (closes[-1] / base) - 1.0
        if len(scores) < 3:
            return StrategyDecision(no_trade_reason=f"warmup: fewer than three instruments have {lookback + 1} observations")
        mean = sum(scores.values()) / len(scores)
        residuals = {key: value - mean for key, value in scores.items()}
        ordered = sorted(residuals.items(), key=lambda item: item[1])
        bucket = max(1, len(ordered) // 3)
        longs = [key for key, _ in ordered[:bucket]]
        shorts = [key for key, _ in ordered[-bucket:]]
        weight = ONE / Decimal(max(1, len(longs)))
        targets: dict[str, Decimal] = {}
        for instrument_id in instruments:
            targets[instrument_id] = ZERO
        for instrument_id in longs:
            targets[instrument_id] = weight
        for instrument_id in shorts:
            spec = ctx.specs.get(instrument_id)
            targets[instrument_id] = -weight if spec and spec.shorting_allowed else ZERO
        return StrategyDecision(
            targets=targets,
            signal="cross_sectional",
            uncertainty=(
                f"residual dispersion over {len(scores)} instruments; the cross-sectional mean is the only "
                "factor removed, so common-factor risk remains"
            ),
            notes={"residuals": residuals, "longs": longs, "shorts": shorts},
        )


class CarryFunding(Strategy):
    family = "carry_funding"

    def warmup(self) -> int:
        return self._int("lookback", 24) + 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        observation = ctx.observations.get(instrument_id)
        if observation is None or not observation.bars:
            return StrategyDecision(no_trade_reason="no observations")
        lookback = self._int("lookback", 24)
        rates = [bar.funding_rate for bar in observation.bars[-lookback:] if bar.funding_rate is not None]
        if not rates:
            return StrategyDecision(
                signal="flat",
                no_trade_reason="missing_funding_data: this dataset carries no funding-rate observations",
                notes={"missing_external_data": "historical funding-rate series"},
            )
        average = sum(rates) / len(rates)
        threshold = self._float("threshold", 0.0001)
        if average > threshold:
            # Longs pay funding when the rate is positive, so the carry receiver is short.
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short_carry",
                uncertainty=f"mean funding {average:.6f} over {len(rates)} observations; carry, not price forecast",
                notes={"mean_funding": average, "observations": len(rates)},
            )
        if average < -threshold:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long_carry",
                uncertainty=f"mean funding {average:.6f} over {len(rates)} observations",
                notes={"mean_funding": average, "observations": len(rates)},
            )
        return StrategyDecision(signal="flat", no_trade_reason=f"mean funding {average:.6f} inside the band")


class BasisConvergence(Strategy):
    family = "basis"
    min_instruments = 2

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        if len(self.spec.instruments) < 2:
            return StrategyDecision(blocked=True, block_reason="basis needs a derivative and a spot instrument")
        derivative, spot = self.spec.instruments[0], self.spec.instruments[1]
        derivative_closes = ctx.closes(derivative)
        spot_closes = ctx.closes(spot)
        if not derivative_closes or not spot_closes:
            return StrategyDecision(no_trade_reason="missing one of the two legs")
        spot_price = spot_closes[-1]
        if spot_price == 0:
            return StrategyDecision(no_trade_reason="zero spot price")
        basis = (derivative_closes[-1] - spot_price) / abs(spot_price)
        threshold = self._float("threshold", 0.005)
        spot_spec = ctx.specs.get(spot)
        derivative_spec = ctx.specs.get(derivative)
        notes = {"basis": basis, "threshold": threshold}
        if basis > threshold:
            targets = {
                derivative: -ONE if derivative_spec and derivative_spec.shorting_allowed else ZERO,
                spot: ONE,
            }
            return StrategyDecision(
                targets=targets,
                signal="short_basis",
                uncertainty=f"basis {basis:.4f} rich; convergence depends on carry and time to expiry",
                notes=notes,
            )
        if basis < -threshold:
            targets = {
                derivative: ONE,
                spot: -ONE if spot_spec and spot_spec.shorting_allowed else ZERO,
            }
            return StrategyDecision(
                targets=targets,
                signal="long_basis",
                uncertainty=f"basis {basis:.4f} cheap",
                notes=notes,
            )
        return StrategyDecision(
            targets={derivative: ZERO, spot: ZERO},
            signal="flat",
            no_trade_reason=f"basis {basis:.4f} inside the band",
            notes=notes,
        )


class EventDriven(Strategy):
    family = "event_driven"
    required_data_level = "event"

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        events = ctx.auxiliary(instrument_id, "news") + ctx.auxiliary(instrument_id, "macro")
        if not events:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=(
                    "missing_point_in_time_event_data: no news or macro observations are available up to the "
                    "simulation clock. HADES ships no event feed; import one to enable this family."
                ),
                notes={"missing_external_data": "point-in-time news/event feed with publication timestamps"},
            )
        window = self._int("reaction_events", 3)
        recent = events[-window:]
        score = 0.0
        for entry in recent:
            payload = entry.get("payload") or {}
            value = payload.get("score", payload.get("surprise", 0))
            try:
                score += float(value)
            except (TypeError, ValueError):
                continue
        threshold = self._float("threshold", 0.5)
        notes = {
            "events_considered": len(recent),
            "aggregate_score": score,
            "latest_available_at": recent[-1].get("available_at"),
        }
        if score >= threshold:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=f"aggregate event score {score:.3f} over {len(recent)} published items",
                notes=notes,
            )
        if score <= -threshold:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short" if self._short_target() != ZERO else "flat",
                uncertainty=f"aggregate event score {score:.3f}",
                notes=notes,
            )
        return StrategyDecision(signal="flat", no_trade_reason="event score inside the band", notes=notes)


class OptionVolatility(Strategy):
    family = "option_volatility"
    required_data_level = "chain"

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        observation = ctx.observations.get(instrument_id)
        if observation is None or not observation.bars:
            return StrategyDecision(no_trade_reason="no observations")
        implied = observation.bars[-1].payload.get("implied_volatility")
        underlying_series = [
            bar.payload.get("underlying_price")
            for bar in observation.bars
            if bar.payload.get("underlying_price") is not None
        ]
        if implied is None or len(underlying_series) < 30:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=(
                    "missing_option_chain_data: implied volatility and an underlying series are required. "
                    "HADES ships no option chain history."
                ),
                notes={"missing_external_data": "option chain history with implied volatility"},
            )
        window = self._int("window", 20)
        realized = realized_volatility([float(value) for value in underlying_series], window)
        if realized is None:
            return StrategyDecision(no_trade_reason="realised volatility not yet estimable")
        annualised = realized * math.sqrt(252.0)
        premium = float(implied) - annualised
        threshold = self._float("threshold", 0.02)
        notes = {"implied": float(implied), "realised_annualised": annualised, "premium": premium}
        if premium > threshold:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short_volatility",
                uncertainty=f"implied minus realised {premium:.4f}; short option risk is asymmetric",
                notes=notes,
            )
        if premium < -threshold:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long_volatility",
                uncertainty=f"implied minus realised {premium:.4f}",
                notes=notes,
            )
        return StrategyDecision(signal="flat", no_trade_reason="volatility premium inside the band", notes=notes)


class MarketMaking(Strategy):
    family = "market_making"
    required_data_level = "l2"

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        observation = ctx.observations.get(instrument_id)
        level = observation.data_level if observation else "ohlcv"
        if level not in {"l2", "quote", "trades"}:
            return StrategyDecision(
                blocked=True,
                block_reason=(
                    "market_making_requires_order_book_data: queue position, adverse selection and fill "
                    "probability cannot be simulated from OHLCV candles. Refusing to produce a result that "
                    "would look like a market-making backtest."
                ),
                notes={"missing_external_data": "level-2 order book or full quote tape"},
            )
        bars = observation.bars if observation else []
        if not bars or bars[-1].bid is None or bars[-1].ask is None:
            return StrategyDecision(no_trade_reason="quote data present but bid/ask missing on the latest observation")
        bid, ask = float(bars[-1].bid), float(bars[-1].ask)
        mid = (bid + ask) / 2.0
        edge = self._float("edge_bps", 5.0) / 10000.0
        return StrategyDecision(
            targets={instrument_id: ZERO},
            signal="quote_two_sided",
            uncertainty="quote-driven; realised fill rate depends on queue position, which this dataset cannot express",
            notes={"mid": mid, "target_bid": mid * (1 - edge), "target_ask": mid * (1 + edge)},
        )


class ExecutionSchedule(Strategy):
    family = "execution_schedule"

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        slices = max(1, self._int("slices", 10))
        total_target = to_decimal(self.params.get("total_target", "1"))
        completed = min(slices, ctx.event_count)
        fraction = Decimal(completed) / Decimal(slices)
        target = total_target * fraction
        return StrategyDecision(
            targets={instrument_id: target},
            signal="execution_schedule",
            uncertainty=(
                f"schedule slice {completed}/{slices}; this family measures modelled participation cost, "
                "it does not claim alpha"
            ),
            notes={"slices": slices, "completed": completed, "target_fraction": str(fraction)},
        )


class ModelSignal(Strategy):
    family = "model_signal"

    def warmup(self) -> int:
        return self._int("warmup", 60)

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        instrument_id = self.spec.instruments[0]
        model_name = str(self.params.get("model", ""))
        model = ctx.models.get(model_name)
        if model is None:
            return StrategyDecision(
                blocked=True,
                block_reason=(
                    f"no_trained_model_artefact:{model_name or '<unset>'} — this family refuses to run without "
                    "an explicitly trained, versioned artefact from trading_lab/models.py"
                ),
            )
        closes = ctx.closes(instrument_id)
        if len(closes) < self.warmup():
            return StrategyDecision(no_trade_reason=f"warmup: need {self.warmup()} observations, have {len(closes)}")
        prediction = model.predict_latest(closes)
        if prediction is None:
            return StrategyDecision(no_trade_reason="model produced no prediction for this observation")
        threshold = self._float("threshold", 0.0)
        notes = {"prediction": prediction, "model": model_name, "model_version": getattr(model, "version", None)}
        if prediction > threshold:
            return StrategyDecision(
                targets={instrument_id: self._long_target()},
                signal="long",
                uncertainty=(
                    f"model score {prediction:.4f}; this is a model output on in-sample-fitted preprocessing, "
                    "not a calibrated probability"
                ),
                notes=notes,
            )
        if prediction < -threshold:
            return StrategyDecision(
                targets={instrument_id: self._short_target()},
                signal="short" if self._short_target() != ZERO else "flat",
                uncertainty=f"model score {prediction:.4f}",
                notes=notes,
            )
        return StrategyDecision(signal="flat", no_trade_reason="model score inside the band", notes=notes)


STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "trend_following": TrendFollowing,
    "momentum": Momentum,
    "breakout": Breakout,
    "mean_reversion": MeanReversion,
    "pairs_trading": PairsTrading,
    "statistical_arbitrage": StatisticalArbitrage,
    "carry_funding": CarryFunding,
    "basis": BasisConvergence,
    "event_driven": EventDriven,
    "option_volatility": OptionVolatility,
    "market_making": MarketMaking,
    "execution_schedule": ExecutionSchedule,
    "model_signal": ModelSignal,
}


def resolve_family(family: str) -> str:
    return LEGACY_FAMILY_ALIASES.get(family, family)


def build_strategy(spec: StrategySpec) -> Strategy:
    family = resolve_family(spec.family)
    cls = STRATEGY_CLASSES.get(family)
    if cls is None:
        raise ValueError(f"unknown_strategy_family:{spec.family}")
    return cls(spec)


def default_param_space(family: str) -> dict[str, list[Any]]:
    """Bounded default search spaces. Recorded with every experiment."""
    family = resolve_family(family)
    spaces: dict[str, dict[str, list[Any]]] = {
        "trend_following": {"fast": [5, 8, 10, 12, 20], "slow": [20, 30, 50, 100], "use_ema": [False, True]},
        "momentum": {"lookback": [10, 20, 30, 48, 96], "threshold": [0.005, 0.01, 0.02, 0.03]},
        "breakout": {"window": [10, 20, 40, 55]},
        "mean_reversion": {"window": [10, 20, 30, 40], "z_entry": [1.0, 1.5, 2.0, 2.5], "z_exit": [0.0, 0.25, 0.5]},
        "pairs_trading": {"window": [30, 60, 120], "z_entry": [1.5, 2.0, 2.5], "z_exit": [0.25, 0.5]},
        "statistical_arbitrage": {"lookback": [5, 10, 20, 40]},
        "carry_funding": {"lookback": [8, 24, 72], "threshold": [0.00005, 0.0001, 0.0005]},
        "basis": {"threshold": [0.002, 0.005, 0.01]},
        "event_driven": {"reaction_events": [1, 3, 5], "threshold": [0.25, 0.5, 1.0]},
        "option_volatility": {"window": [10, 20, 40], "threshold": [0.01, 0.02, 0.05]},
        "execution_schedule": {"slices": [5, 10, 20]},
        "model_signal": {"threshold": [0.0, 0.001, 0.005]},
    }
    return spaces.get(family, {})


def strategy_capability(family: str) -> Any:
    return STRATEGY_CAPABILITIES.get(resolve_family(family))


def _apply_declared_filters(spec: StrategySpec, ctx: StrategyContext, decision: StrategyDecision) -> StrategyDecision:
    """Point-in-time regime / no-trade filters declared on the spec. Additive; families unchanged."""
    from trading_lab.regimes import classify_closes, regime_matches

    params = spec.params or {}
    regime_filter = params.get("regime_filter")
    vol_filter = params.get("volatility_filter")
    no_trade = params.get("no_trade_regimes") or []
    if not regime_filter and not vol_filter and not no_trade:
        return decision
    primary = spec.instruments[0] if spec.instruments else next(iter(ctx.observations), None)
    if not primary:
        return decision
    observation = ctx.observations.get(primary)
    if observation is None or not observation.closes:
        return decision.replace(
            targets={},
            signal="flat",
            no_trade_reason="regime_filter_no_observation",
        ) if hasattr(decision, "replace") else StrategyDecision(
            signal="flat",
            no_trade_reason="regime_filter_no_observation",
            notes=dict(decision.notes),
        )
    snapshot = classify_closes(
        observation.closes,
        volumes=[bar.volume for bar in observation.bars if getattr(bar, "volume", None) is not None],
    )
    if no_trade and snapshot.key in no_trade:
        return StrategyDecision(
            signal="flat",
            no_trade_reason=f"no_trade_regime:{snapshot.key}",
            notes={**dict(decision.notes), "regime": snapshot.as_json()},
        )
    if regime_filter:
        matched, reason = regime_matches(snapshot, regime_filter if isinstance(regime_filter, dict) else None)
        if not matched:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=reason,
                notes={**dict(decision.notes), "regime": snapshot.as_json()},
            )
    if isinstance(vol_filter, dict):
        avoid = vol_filter.get("avoid")
        require = vol_filter.get("require")
        if avoid and snapshot.volatility == avoid:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=f"volatility_filter_avoid:{avoid}",
                notes={**dict(decision.notes), "regime": snapshot.as_json()},
            )
        if require and snapshot.volatility != require:
            return StrategyDecision(
                signal="flat",
                no_trade_reason=f"volatility_filter_require:{require}",
                notes={**dict(decision.notes), "regime": snapshot.as_json()},
            )
    decision.notes = {**dict(decision.notes), "regime": snapshot.as_json()}
    return decision


class StrategyRuntime:
    """Turns strategy targets into validated :class:`OrderIntent` objects.

    Sizing, rounding, short permission and the minimum-trade filter live here so no strategy
    can accidentally bypass them.
    """

    def __init__(self, spec: StrategySpec, *, sizing: SizingSpec | None = None) -> None:
        self.spec = spec
        self.strategy = build_strategy(spec)
        self.sizing = sizing or spec.sizing

    @property
    def warmup(self) -> int:
        return self.strategy.warmup()

    def decide(self, ctx: StrategyContext) -> StrategyDecision:
        decision = self.strategy.decide(ctx)
        return _apply_declared_filters(self.spec, ctx, decision)

    def intents(
        self,
        decision: StrategyDecision,
        ctx: StrategyContext,
        *,
        intent_prefix: str,
        min_trade_fraction: Decimal = Decimal("0.02"),
    ) -> tuple[list[OrderIntent], list[str]]:
        """Diff target exposure against the live position and emit orders."""
        intents: list[OrderIntent] = []
        notes: list[str] = []
        if decision.blocked:
            return intents, [decision.block_reason]
        for instrument_id, target_fraction in decision.targets.items():
            spec = ctx.specs.get(instrument_id)
            observation = ctx.observations.get(instrument_id)
            if spec is None or observation is None or not observation.bars:
                notes.append(f"no_observation_for:{instrument_id}")
                continue
            reference = to_decimal(observation.bars[-1].reference_price)
            if reference == 0:
                notes.append(f"zero_reference_price:{instrument_id}")
                continue
            clamped = target_fraction
            if clamped < 0 and not spec.shorting_allowed:
                clamped = ZERO
                notes.append(f"short_target_clamped_to_flat:{instrument_id}")
            target_quantity = self._target_quantity(spec, clamped, reference, ctx.equity)
            held = ctx.positions.get(instrument_id, ZERO)
            delta = target_quantity - held
            rounded = self._round_lot(spec, delta)
            if rounded == ZERO:
                continue
            threshold = self._minimum_delta(spec, reference, ctx.equity, min_trade_fraction)
            if abs(rounded) < threshold:
                notes.append(f"delta_below_min_trade_threshold:{instrument_id}")
                continue
            side = "buy" if rounded > 0 else "sell"
            reduce_only = (held > 0 and side == "sell" and abs(rounded) <= held) or (
                held < 0 and side == "buy" and abs(rounded) <= abs(held)
            )
            intent = OrderIntent(
                intent_id=f"{intent_prefix}:{instrument_id}:{ctx.as_of}",
                instrument_id=instrument_id,
                side=side,  # type: ignore[arg-type]
                order_type=self.spec.order_type,
                quantity=abs(rounded),
                limit_price=self._limit_price(reference, side) if self.spec.order_type in {"limit", "take_profit"} else None,
                stop_price=self._stop_price(reference, side) if self.spec.order_type in {"stop_market", "stop_limit"} else None,
                trail_offset=self._trail_offset(reference) if self.spec.order_type == "trailing_stop" else None,
                take_profit_price=self._bracket_take_profit(reference, side) if self.spec.order_type == "bracket" else None,
                stop_loss_price=self._bracket_stop_loss(reference, side) if self.spec.order_type == "bracket" else None,
                time_in_force=self.spec.time_in_force,
                reduce_only=bool(reduce_only and self.params_bool("use_reduce_only", True)),
                post_only=bool(self.spec.params.get("post_only", False)),
                strategy_id=self.spec.strategy_id or None,
                strategy_version=self.spec.version,
                rationale=f"{decision.signal}: {decision.uncertainty}"[:480],
                created_at_event_time=ctx.as_of,
                price_source="strategy_signal",
                metadata={"target_fraction": str(clamped), "signal": decision.signal},
            )
            intents.append(intent)
        return intents, notes

    def params_bool(self, name: str, default: bool) -> bool:
        return bool(self.spec.params.get(name, default))

    def _target_quantity(
        self, spec: InstrumentSpec, fraction: Decimal, reference: Decimal, equity: Decimal
    ) -> Decimal:
        sizing = self.sizing
        unit_notional = abs(reference) * spec.multiplier
        if unit_notional == 0:
            return ZERO
        if sizing.mode == "fixed_quantity":
            quantity = sizing.value * fraction
        elif sizing.mode == "fixed_notional":
            quantity = (sizing.value * fraction) / unit_notional
        elif sizing.mode == "risk_per_trade":
            risk_budget = equity * sizing.value
            quantity = (risk_budget * fraction) / unit_notional
        else:  # equity_fraction
            quantity = (equity * sizing.value * fraction) / unit_notional
        if sizing.max_position_notional is not None:
            cap = sizing.max_position_notional / unit_notional
            if abs(quantity) > cap:
                quantity = cap if quantity > 0 else -cap
        return quantity

    @staticmethod
    def _round_lot(spec: InstrumentSpec, quantity: Decimal) -> Decimal:
        from decimal import ROUND_DOWN

        from trading_lab.contracts import quantize_step

        rounded = quantize_step(abs(quantity), spec.lot_size, rounding=ROUND_DOWN)
        return rounded if quantity >= 0 else -rounded

    @staticmethod
    def _minimum_delta(
        spec: InstrumentSpec, reference: Decimal, equity: Decimal, min_trade_fraction: Decimal
    ) -> Decimal:
        unit_notional = abs(reference) * spec.multiplier
        if unit_notional == 0:
            return ZERO
        from_notional = spec.min_notional / unit_notional if spec.min_notional > 0 else ZERO
        from_equity = (equity * min_trade_fraction) / unit_notional if equity > 0 else ZERO
        return max(spec.lot_size, from_notional, from_equity * Decimal("0.05"))

    def _limit_price(self, reference: Decimal, side: str) -> Decimal:
        offset_bps = to_decimal(self.spec.params.get("limit_offset_bps", 5))
        offset = abs(reference) * offset_bps / Decimal("10000")
        return reference - offset if side == "buy" else reference + offset

    def _stop_price(self, reference: Decimal, side: str) -> Decimal:
        offset_bps = to_decimal(self.spec.params.get("stop_offset_bps", 50))
        offset = abs(reference) * offset_bps / Decimal("10000")
        return reference + offset if side == "buy" else reference - offset

    def _trail_offset(self, reference: Decimal) -> Decimal:
        offset_bps = to_decimal(self.spec.params.get("trail_offset_bps", 100))
        return abs(reference) * offset_bps / Decimal("10000")

    def _bracket_take_profit(self, reference: Decimal, side: str) -> Decimal:
        offset_bps = to_decimal(self.spec.params.get("take_profit_bps", 200))
        offset = abs(reference) * offset_bps / Decimal("10000")
        return reference + offset if side == "buy" else reference - offset

    def _bracket_stop_loss(self, reference: Decimal, side: str) -> Decimal:
        offset_bps = to_decimal(self.spec.params.get("stop_loss_bps", 100))
        offset = abs(reference) * offset_bps / Decimal("10000")
        return reference - offset if side == "buy" else reference + offset


def legacy_signals(family: str, closes: Sequence[float], params: dict[str, Any]) -> list[int]:
    """Long/flat signal series matching the legacy bot, kept for comparison runs.

    It exists so a Trading Lab experiment can reproduce what the old bot would have done and
    show the difference once fees, spread and next-event execution are applied. It is not used
    by the engine.
    """
    values = list(closes)
    resolved = resolve_family(family)
    signals = [0] * len(values)
    position = 0
    if resolved == "trend_following":
        fast = sma(values, int(params.get("fast", 10)))
        slow = sma(values, int(params.get("slow", 30)))
        for index in range(len(values)):
            if fast[index] is None or slow[index] is None:
                continue
            if fast[index] > slow[index]:
                position = 1
            elif fast[index] < slow[index]:
                position = 0
            signals[index] = position
        return signals
    if resolved == "momentum":
        lookback = int(params.get("lookback", 20))
        threshold = float(params.get("threshold", 0.01))
        for index in range(len(values)):
            if index < lookback or values[index - lookback] == 0:
                continue
            change = (values[index] / values[index - lookback]) - 1.0
            if change >= threshold:
                position = 1
            elif change <= -threshold:
                position = 0
            signals[index] = position
        return signals
    if resolved == "mean_reversion":
        scores = zscore(values, int(params.get("window", 20)))
        entry = float(params.get("z_entry", 1.5))
        for index in range(len(values)):
            score = scores[index]
            if score is None:
                continue
            if score <= -entry:
                position = 1
            elif score >= 0:
                position = 0
            signals[index] = position
        return signals
    raise ValueError(f"legacy_signals_unsupported_family:{family}")


__all__ = [
    "BasisConvergence",
    "Breakout",
    "CarryFunding",
    "EventDriven",
    "ExecutionSchedule",
    "MarketMaking",
    "MeanReversion",
    "ModelSignal",
    "Momentum",
    "OptionVolatility",
    "PairsTrading",
    "STRATEGY_CLASSES",
    "StatisticalArbitrage",
    "Strategy",
    "StrategyContext",
    "StrategyDecision",
    "StrategyRuntime",
    "TrendFollowing",
    "build_strategy",
    "default_param_space",
    "legacy_signals",
    "resolve_family",
    "strategy_capability",
]
