"""Strategy DSL v2/v3 — structured specs over FeatureEngine (P2A / W14).

No arbitrary code execution. Unknown kinds → HOLD with honest rationale.
Filters (e.g. regime_filter) gate entries without peeking at future bars.
V3 adds declarative risk exits, sizing, universe/session/portfolio constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .causality import MarketView, SimulationClock
from .features import FeatureEngine, FeatureStatus
from .types import MarketSimError, OrderSide


DSL_V2_VERSION = 2
DSL_V3_VERSION = 3
DSL_CURRENT_VERSION = DSL_V3_VERSION

SUPPORTED_KINDS = frozenset(
    {
        "ma_cross",
        "mean_reversion",
        "breakout",
        "rsi",
        "feature_compare",
        "hold",
        "composite",
    }
)

SUPPORTED_FILTERS = frozenset({"regime_filter", "universe_filter", "session_filter"})


@dataclass(frozen=True)
class StrategySpecV2:
    """Validated Strategy Spec v2/v3 document (v3 fields optional, default empty)."""

    version: int
    kind: str
    parameters: dict[str, Any] = field(default_factory=dict)
    entry: dict[str, Any] = field(default_factory=dict)
    exit: dict[str, Any] = field(default_factory=dict)
    filters: list[dict[str, Any]] = field(default_factory=list)
    required_timeframes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # W14 DSL v3 declarative extensions (no eval/exec)
    stop_loss: dict[str, Any] = field(default_factory=dict)
    take_profit: dict[str, Any] = field(default_factory=dict)
    trailing_stop: dict[str, Any] = field(default_factory=dict)
    time_stop: dict[str, Any] = field(default_factory=dict)
    position_sizing: dict[str, Any] = field(default_factory=dict)
    risk_conditions: list[dict[str, Any]] = field(default_factory=list)
    universe_filters: list[dict[str, Any]] = field(default_factory=list)
    portfolio_constraints: dict[str, Any] = field(default_factory=dict)
    session_schedule: dict[str, Any] = field(default_factory=dict)
    composite_signals: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "kind": self.kind,
            "parameters": self.parameters,
            "entry": self.entry,
            "exit": self.exit,
            "filters": list(self.filters),
            "required_timeframes": list(self.required_timeframes),
            "metadata": dict(self.metadata),
            "stop_loss": dict(self.stop_loss),
            "take_profit": dict(self.take_profit),
            "trailing_stop": dict(self.trailing_stop),
            "time_stop": dict(self.time_stop),
            "position_sizing": dict(self.position_sizing),
            "risk_conditions": list(self.risk_conditions),
            "universe_filters": list(self.universe_filters),
            "portfolio_constraints": dict(self.portfolio_constraints),
            "session_schedule": dict(self.session_schedule),
            "composite_signals": list(self.composite_signals),
            "truth": {
                "dsl_v2": self.version >= 2,
                "dsl_v3": self.version >= 3,
                "no_arbitrary_code": True,
                "feature_engine_backed": True,
            },
        }


# Backward-compatible alias — same dataclass, not a parallel system.
StrategySpecV3 = StrategySpecV2


def _v3_fields(src: dict[str, Any]) -> dict[str, Any]:
    return {
        "stop_loss": dict(src.get("stop_loss") or {}),
        "take_profit": dict(src.get("take_profit") or {}),
        "trailing_stop": dict(src.get("trailing_stop") or {}),
        "time_stop": dict(src.get("time_stop") or {}),
        "position_sizing": dict(src.get("position_sizing") or {}),
        "risk_conditions": list(src.get("risk_conditions") or []),
        "universe_filters": list(src.get("universe_filters") or []),
        "portfolio_constraints": dict(src.get("portfolio_constraints") or {}),
        "session_schedule": dict(src.get("session_schedule") or {}),
        "composite_signals": list(src.get("composite_signals") or []),
    }


def parse_strategy_spec(
    entry_rules: dict[str, Any] | None,
    *,
    exit_rules: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
) -> StrategySpecV2:
    """Accept v2/v3 documents or legacy entry_rules.kind forms."""
    entry_rules = dict(entry_rules or {})
    exit_rules = dict(exit_rules or {})
    parameters = dict(parameters or {})

    ver = int(entry_rules.get("version") or entry_rules.get("spec_version") or 0)
    if ver >= 2:
        kind = str(entry_rules.get("kind") or "hold").lower()
        version = DSL_V3_VERSION if ver >= 3 else DSL_V2_VERSION
        # Promote to v3 document shape when v3 fields present even if version==2
        v3 = _v3_fields(entry_rules)
        if any(v3.values()):
            version = DSL_V3_VERSION
        return StrategySpecV2(
            version=version,
            kind=kind,
            parameters={**parameters, **dict(entry_rules.get("parameters") or {})},
            entry=dict(entry_rules.get("entry") or entry_rules),
            exit=dict(entry_rules.get("exit") or exit_rules),
            filters=list(entry_rules.get("filters") or []),
            required_timeframes=list(entry_rules.get("required_timeframes") or []),
            metadata=dict(entry_rules.get("metadata") or {}),
            **v3,
        )

    # Legacy: promote entry_rules.kind into v2 shell
    kind = str(entry_rules.get("kind") or "ma_cross").lower()
    return StrategySpecV2(
        version=DSL_V2_VERSION,
        kind=kind,
        parameters=parameters,
        entry=entry_rules,
        exit=exit_rules or {"kind": kind},
        filters=list(entry_rules.get("filters") or []),
        required_timeframes=list(entry_rules.get("required_timeframes") or []),
    )


def validate_strategy_spec(spec: StrategySpecV2) -> tuple[bool, str]:
    if spec.version not in {DSL_V2_VERSION, DSL_V3_VERSION}:
        return False, f"unsupported spec version {spec.version}"
    if spec.kind not in SUPPORTED_KINDS:
        return False, f"unsupported kind {spec.kind}"
    for filt in spec.filters:
        fk = str(filt.get("kind") or "").lower()
        if fk not in SUPPORTED_FILTERS:
            return False, f"unsupported filter {fk}"
    if spec.kind == "feature_compare":
        entry = spec.entry
        if not entry.get("left") or not entry.get("op") or entry.get("right") is None:
            # allow right as feature name via right_feature
            if not (entry.get("left") and entry.get("op") and entry.get("right_feature")):
                return False, "feature_compare requires left, op, and right|right_feature"
    # V3 declarative field sanity — refuse code/eval keys
    for blob in (spec.stop_loss, spec.take_profit, spec.trailing_stop, spec.time_stop, spec.position_sizing, spec.portfolio_constraints, spec.session_schedule):
        if any(k in blob for k in ("eval", "exec", "code", "__import__")):
            return False, "arbitrary code keys forbidden in DSL"
    return True, "ok"


def apply_risk_exits(
    *,
    position_qty: float,
    entry_price: float | None,
    last_price: float,
    bars_held: int,
    spec: StrategySpecV2,
) -> dict[str, Any]:
    """Evaluate declarative stop / take-profit / trailing / time-stop (v3).

    Returns action HOLD|SELL with reasons. No arbitrary code.
    """
    if position_qty <= 0 or entry_price is None:
        return {"side": OrderSide.HOLD.value, "reason": "flat", "triggered": None}
    pnl_pct = (last_price - float(entry_price)) / float(entry_price) if entry_price else 0.0
    if spec.stop_loss:
        pct = spec.stop_loss.get("pct")
        if pct is not None and pnl_pct <= -abs(float(pct)):
            return {"side": OrderSide.SELL.value, "reason": f"stop_loss pct={pct}", "triggered": "stop_loss"}
    if spec.take_profit:
        pct = spec.take_profit.get("pct")
        if pct is not None and pnl_pct >= abs(float(pct)):
            return {"side": OrderSide.SELL.value, "reason": f"take_profit pct={pct}", "triggered": "take_profit"}
    if spec.trailing_stop:
        trail = spec.trailing_stop.get("pct")
        peak = spec.trailing_stop.get("peak_price") or entry_price
        if trail is not None and peak:
            dd = (float(peak) - last_price) / float(peak)
            if dd >= abs(float(trail)):
                return {"side": OrderSide.SELL.value, "reason": f"trailing_stop pct={trail}", "triggered": "trailing_stop"}
    if spec.time_stop:
        max_bars = spec.time_stop.get("max_bars")
        if max_bars is not None and bars_held >= int(max_bars):
            return {"side": OrderSide.SELL.value, "reason": f"time_stop bars={bars_held}", "triggered": "time_stop"}
    return {"side": OrderSide.HOLD.value, "reason": "no_risk_exit", "triggered": None}


def _feat(engine: FeatureEngine, bars: list[Any], name: str, as_of: str, period: int | None) -> float | None:
    key = str(name or "").lower()
    if key in {"close", "last", "price"}:
        if not bars:
            return None
        return float(bars[-1].close)
    result = engine.compute(bars, name, as_of=as_of, period=period)
    if result.status != FeatureStatus.MEASURED.value and result.status != "MEASURED":
        return None
    val = result.value
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compare(left: float, op: str, right: float) -> bool:
    op = op.strip().lower()
    if op in {"<", "lt"}:
        return left < right
    if op in {"<=", "lte"}:
        return left <= right
    if op in {">", "gt"}:
        return left > right
    if op in {">=", "ge"}:
        return left >= right
    if op in {"==", "eq", "equals"}:
        return abs(left - right) < 1e-12
    if op in {"crosses_above"}:
        return left > right
    if op in {"crosses_below"}:
        return left < right
    raise MarketSimError("DSL_BAD_OP", f"unsupported compare op {op}")


def _regime_allows(spec: StrategySpecV2, view: MarketView, engine: FeatureEngine) -> tuple[bool, str]:
    """Apply regime_filter gates. Fail-closed (block entry) when unmeasured."""
    as_of = view.as_of
    if as_of is None:
        return False, "no as_of"
    bars = view.visible_bars()
    for filt in spec.filters:
        if str(filt.get("kind") or "").lower() != "regime_filter":
            continue
        # ADX threshold or realized vol band
        mode = str(filt.get("mode") or "adx").lower()
        if mode == "adx":
            period = int(filt.get("period") or 14)
            min_adx = float(filt.get("min_adx") or 0.0)
            max_adx = filt.get("max_adx")
            adx = _feat(engine, bars, "adx", as_of, period)
            if adx is None:
                return False, "regime_filter adx unmeasured"
            if adx < min_adx:
                return False, f"adx {adx:.2f} < min_adx {min_adx}"
            if max_adx is not None and adx > float(max_adx):
                return False, f"adx {adx:.2f} > max_adx {max_adx}"
        elif mode == "trend":
            # require SMA fast > slow for long-only regime
            fast_p = int(filt.get("fast") or 10)
            slow_p = int(filt.get("slow") or 30)
            fast = _feat(engine, bars, "sma", as_of, fast_p)
            slow = _feat(engine, bars, "sma", as_of, slow_p)
            if fast is None or slow is None:
                return False, "regime_filter trend unmeasured"
            require = str(filt.get("require") or "bullish").lower()
            if require == "bullish" and not (fast > slow):
                return False, "regime not bullish"
            if require == "bearish" and not (fast < slow):
                return False, "regime not bearish"
        else:
            return False, f"unknown regime mode {mode}"
    return True, "ok"


@dataclass(frozen=True)
class DslSignal:
    side: str
    qty: float | None
    confidence: float
    rationale: str
    parameters_used: dict[str, Any]
    filter_passed: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "qty": self.qty,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "parameters_used": self.parameters_used,
            "filter_passed": self.filter_passed,
        }


def evaluate_dsl_v2(
    clock: SimulationClock,
    spec: StrategySpecV2,
    *,
    position_qty: float,
    feature_engine: FeatureEngine | None = None,
) -> DslSignal:
    """Evaluate Strategy Spec v2 against a causal MarketView."""
    ok, reason = validate_strategy_spec(spec)
    if not ok:
        return DslSignal(
            side=OrderSide.HOLD.value,
            qty=None,
            confidence=0.0,
            rationale=f"invalid spec: {reason}",
            parameters_used={"kind": spec.kind},
            filter_passed=False,
        )

    view = MarketView(clock=clock)
    if view.as_of is None or view.index < 0:
        return DslSignal(
            side=OrderSide.HOLD.value,
            qty=None,
            confidence=0.1,
            rationale="warming up",
            parameters_used={"kind": spec.kind},
        )

    engine = feature_engine or FeatureEngine()
    allowed, filt_reason = _regime_allows(spec, view, engine)
    if not allowed and position_qty <= 0:
        # Filters block new entries only; exits still evaluate
        pass

    bars = view.visible_bars()
    as_of = view.as_of
    assert as_of is not None
    kind = spec.kind
    params = spec.parameters
    entry = spec.entry
    exit_rules = spec.exit

    side = OrderSide.HOLD.value
    rationale = "no setup"
    confidence = 0.4
    used: dict[str, Any] = {"kind": kind, "dsl_version": spec.version}

    if kind == "hold":
        return DslSignal(side=OrderSide.HOLD.value, qty=None, confidence=0.0, rationale="hold", parameters_used=used)

    if kind == "breakout":
        period = int(params.get("period") or entry.get("period") or 20)
        brk = engine.compute(bars, "breakout", as_of=as_of, period=period)
        used["breakout"] = brk.public_dict()
        # breakout feature: typically +1 up / -1 down / 0 none — accept numeric or dict
        val = brk.value
        signal = 0
        if isinstance(val, dict):
            signal = int(val.get("signal") or val.get("state") or 0)
        elif val is not None:
            try:
                signal = int(float(val))
            except (TypeError, ValueError):
                signal = 1 if float(val) > 0 else (-1 if float(val) < 0 else 0)
        if position_qty <= 0 and signal > 0 and allowed:
            side = OrderSide.BUY.value
            rationale = f"breakout up period={period}"
            confidence = 0.7
        elif position_qty > 0 and (signal < 0 or str(exit_rules.get("kind") or "") == "breakout"):
            if signal < 0:
                side = OrderSide.SELL.value
                rationale = f"breakout down exit period={period}"
                confidence = 0.65
        elif position_qty <= 0 and not allowed:
            rationale = f"breakout blocked: {filt_reason}"
            used["filter_passed"] = False
            return DslSignal(
                side=OrderSide.HOLD.value,
                qty=None,
                confidence=0.2,
                rationale=rationale,
                parameters_used=used,
                filter_passed=False,
            )

    elif kind == "rsi":
        period = int(params.get("period") or entry.get("period") or 14)
        low = float(entry.get("oversold") or params.get("oversold") or 30)
        high = float(exit_rules.get("overbought") or entry.get("overbought") or params.get("overbought") or 70)
        rsi = _feat(engine, bars, "rsi", as_of, period)
        used["rsi"] = rsi
        used["oversold"] = low
        used["overbought"] = high
        if rsi is None:
            rationale = "rsi unmeasured"
        elif position_qty <= 0 and rsi <= low and allowed:
            side = OrderSide.BUY.value
            rationale = f"rsi oversold {rsi:.1f}<={low}"
            confidence = 0.7
        elif position_qty > 0 and rsi >= high:
            side = OrderSide.SELL.value
            rationale = f"rsi overbought {rsi:.1f}>={high}"
            confidence = 0.65
        elif position_qty <= 0 and not allowed:
            return DslSignal(
                side=OrderSide.HOLD.value,
                qty=None,
                confidence=0.2,
                rationale=f"rsi blocked: {filt_reason}",
                parameters_used=used,
                filter_passed=False,
            )
        else:
            rationale = f"rsi={rsi:.1f}" if rsi is not None else "rsi n/a"

    elif kind == "feature_compare":
        left_name = str(entry.get("left") or "close")
        left_period = entry.get("left_period") or entry.get("period")
        right_feature = entry.get("right_feature")
        right_period = entry.get("right_period") or left_period
        op = str(entry.get("op") or ">")
        left_v = _feat(engine, bars, left_name, as_of, int(left_period) if left_period else None)
        if right_feature:
            right_v = _feat(
                engine, bars, str(right_feature), as_of, int(right_period) if right_period else None
            )
        else:
            right_v = float(entry.get("right"))
        used.update({"left": left_name, "op": op, "left_v": left_v, "right_v": right_v})
        if left_v is None or right_v is None:
            rationale = "feature_compare unmeasured"
        else:
            matched = _compare(float(left_v), op, float(right_v))
            exit_op = str(exit_rules.get("op") or ("<" if op in {">", ">=", "gt", "ge"} else ">"))
            exit_matched = _compare(float(left_v), exit_op, float(right_v))
            if position_qty <= 0 and matched and allowed:
                side = OrderSide.BUY.value
                rationale = f"feature_compare {left_name}{op}{right_v}"
                confidence = 0.6
            elif position_qty > 0 and exit_matched:
                side = OrderSide.SELL.value
                rationale = f"feature_compare exit {left_name}{exit_op}{right_v}"
                confidence = 0.55
            elif position_qty <= 0 and not allowed:
                return DslSignal(
                    side=OrderSide.HOLD.value,
                    qty=None,
                    confidence=0.2,
                    rationale=f"feature_compare blocked: {filt_reason}",
                    parameters_used=used,
                    filter_passed=False,
                )
            else:
                rationale = f"feature_compare idle left={left_v}"

    elif kind in {"ma_cross", "mean_reversion", "composite"}:
        # Delegate composite/legacy kinds to strategy_eval for parity
        from .strategy_eval import evaluate_strategy

        legacy = evaluate_strategy(
            clock,
            parameters=params,
            entry_rules={"kind": "ma_cross" if kind == "composite" else kind, **entry},
            exit_rules=exit_rules or {"kind": kind},
            position_qty=position_qty,
        )
        if position_qty <= 0 and legacy.side == OrderSide.BUY.value and not allowed:
            return DslSignal(
                side=OrderSide.HOLD.value,
                qty=None,
                confidence=0.2,
                rationale=f"{kind} blocked: {filt_reason}",
                parameters_used={**legacy.parameters_used, "filter_passed": False},
                filter_passed=False,
            )
        return DslSignal(
            side=legacy.side,
            qty=legacy.qty,
            confidence=legacy.confidence,
            rationale=legacy.rationale,
            parameters_used={**legacy.parameters_used, "dsl_version": spec.version},
            filter_passed=allowed,
        )

    else:
        rationale = f"unsupported kind {kind}"

    return DslSignal(
        side=side,
        qty=None,
        confidence=confidence,
        rationale=rationale,
        parameters_used=used,
        filter_passed=allowed,
    )
