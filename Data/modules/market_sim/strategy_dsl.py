"""Strategy DSL v2 — declarative, sandboxed, causal strategy specs.

No arbitrary Python execution. Specs compile to a validated AST and evaluate
against FeatureEngine outputs bound to a causal MarketView / SimulationClock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from Data.modules.common.hashing import sha256_text

from .causality import MarketView, SimulationClock
from .features import FORBIDDEN_OHLCV_FEATURES, FeatureEngine, FeatureStatus
from .types import MarketSimError, OrderSide

DSL_VERSION = 2

STRATEGY_FAMILIES = frozenset(
    {
        "trend_following",
        "moving_average",
        "momentum",
        "mean_reversion",
        "breakout",
        "volatility_breakout",
        "range_trading",
        "relative_strength",
        "multi_timeframe",
        "event_filtered",
        "custom",
    }
)

ALLOWED_COMPARE_OPS = frozenset({"gt", "gte", "lt", "lte", "eq", "neq"})
ALLOWED_CROSS_OPS = frozenset({"cross_above", "cross_below"})
ALLOWED_BOOL_OPS = frozenset({"all", "any", "not"})
ALLOWED_SIZING_KINDS = frozenset(
    {"fixed_fraction", "fixed_qty", "risk_fraction", "none"}
)

# Feature names accepted in DSL feature declarations (subset of FeatureEngine).
ALLOWED_FEATURE_NAMES = frozenset(
    {
        "sma",
        "ema",
        "rsi",
        "atr",
        "adx",
        "bollinger_mid",
        "bollinger_upper",
        "bollinger_lower",
        "bollinger_pct_b",
        "zscore",
        "roc",
        "return",
        "realized_vol",
        "vol_percentile",
        "rolling_high",
        "rolling_low",
        "donchian_high",
        "donchian_mid",
        "donchian_low",
        "momentum",
        "vwap",
        "volume_avg",
        "volume_z",
        "breakout",
        "trend_slope",
        "drawdown",
        "close",  # raw last close — special-cased
    }
)

PARAM_RANGES: dict[str, tuple[int, int]] = {
    "period": (1, 500),
    "lookback": (1, 500),
    "num_std": (1, 5),
}


class StrategyDslError(MarketSimError):
    def __init__(self, message: str, *, code: str = "STRATEGY_DSL_INVALID") -> None:
        super().__init__(code, message, http_status=400)


@dataclass(frozen=True)
class FeatureDecl:
    alias: str
    name: str
    period: int | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {"alias": self.alias, "name": self.name, "period": self.period, "params": self.params}


@dataclass
class CompiledStrategy:
    """Validated internal representation — safe to evaluate."""

    dsl_version: int
    family: str
    metadata: dict[str, Any]
    universe: dict[str, Any]
    required_timeframes: list[str]
    features: list[FeatureDecl]
    regime_filters: dict[str, Any] | None
    entry_conditions: dict[str, Any]
    exit_conditions: dict[str, Any]
    position_sizing: dict[str, Any]
    risk_conditions: dict[str, Any]
    execution_preferences: dict[str, Any]
    cooldowns: dict[str, Any]
    portfolio_constraints: dict[str, Any]
    applicability: dict[str, Any]
    brain_dependencies: list[str]
    content_hash: str
    legacy_kind: str | None = None  # set when compiled from v1 ma_cross / mean_reversion

    def public_dict(self) -> dict[str, Any]:
        return {
            "dsl_version": self.dsl_version,
            "family": self.family,
            "metadata": self.metadata,
            "universe": self.universe,
            "required_timeframes": self.required_timeframes,
            "features": [f.public_dict() for f in self.features],
            "regime_filters": self.regime_filters,
            "entry_conditions": self.entry_conditions,
            "exit_conditions": self.exit_conditions,
            "position_sizing": self.position_sizing,
            "risk_conditions": self.risk_conditions,
            "execution_preferences": self.execution_preferences,
            "cooldowns": self.cooldowns,
            "portfolio_constraints": self.portfolio_constraints,
            "applicability": self.applicability,
            "brain_dependencies": self.brain_dependencies,
            "content_hash": self.content_hash,
            "legacy_kind": self.legacy_kind,
            "truth": {
                "sandboxed": True,
                "no_arbitrary_code": True,
                "causal_features_only": True,
            },
        }


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StrategyDslError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise StrategyDslError(f"{label} must be an array")
    return value


def _validate_condition_tree(
    node: Any,
    *,
    feature_aliases: set[str],
    path: str = "condition",
) -> dict[str, Any]:
    """Validate and normalize a boolean/compare/cross condition tree."""
    if not isinstance(node, dict):
        raise StrategyDslError(f"{path} must be an object")
    keys = set(node.keys())

    # Boolean combinators
    for bool_op in ("all", "any"):
        if bool_op in node:
            if keys - {bool_op}:
                raise StrategyDslError(f"{path}: '{bool_op}' cannot mix with other keys")
            children = _require_list(node[bool_op], f"{path}.{bool_op}")
            if not children:
                raise StrategyDslError(f"{path}.{bool_op} must be non-empty")
            return {
                bool_op: [
                    _validate_condition_tree(c, feature_aliases=feature_aliases, path=f"{path}.{bool_op}[{i}]")
                    for i, c in enumerate(children)
                ]
            }
    if "not" in node:
        if keys - {"not"}:
            raise StrategyDslError(f"{path}: 'not' cannot mix with other keys")
        return {
            "not": _validate_condition_tree(
                node["not"], feature_aliases=feature_aliases, path=f"{path}.not"
            )
        }

    # Cross operators
    for cross in ALLOWED_CROSS_OPS:
        if cross in node:
            pair = node[cross]
            if not isinstance(pair, list) or len(pair) != 2:
                raise StrategyDslError(f"{path}.{cross} needs [left_alias, right_alias]")
            left, right = str(pair[0]), str(pair[1])
            for alias in (left, right):
                if alias not in feature_aliases and alias != "close":
                    raise StrategyDslError(f"{path}.{cross}: unknown feature alias {alias!r}")
            return {cross: [left, right]}

    # Compare: {"feature": alias, "op": "gt", "value": number} or {"left": a, "op":..., "right": b}
    if "op" in node:
        op = str(node["op"]).lower()
        if op not in ALLOWED_COMPARE_OPS:
            raise StrategyDslError(f"{path}: unsupported compare op {op!r}")
        if "feature" in node and "value" in node:
            alias = str(node["feature"])
            if alias not in feature_aliases and alias not in {"close"} and not alias.startswith("regime."):
                raise StrategyDslError(f"{path}: unknown feature alias {alias!r}")
            if not isinstance(node["value"], (int, float)):
                raise StrategyDslError(f"{path}.value must be numeric")
            return {"feature": alias, "op": op, "value": float(node["value"])}
        if "left" in node and "right" in node:
            left, right = str(node["left"]), str(node["right"])
            for alias in (left, right):
                if alias not in feature_aliases and alias != "close":
                    raise StrategyDslError(f"{path}: unknown feature alias {alias!r}")
            return {"left": left, "op": op, "right": right}
        raise StrategyDslError(f"{path}: compare needs feature/value or left/right")

    # Regime shorthand: {"regime.trend": "up"} or {"regime": {"trend": "up"}}
    if "regime" in node and isinstance(node["regime"], dict):
        return {"regime": dict(node["regime"])}
    regime_keys = [k for k in node if str(k).startswith("regime.")]
    if regime_keys:
        if len(keys) != 1:
            raise StrategyDslError(f"{path}: regime shorthand must be a single key")
        key = regime_keys[0]
        return {key: node[key]}

    raise StrategyDslError(
        f"{path}: unsupported operator keys {sorted(keys)}; "
        f"allowed boolean={sorted(ALLOWED_BOOL_OPS)}, cross={sorted(ALLOWED_CROSS_OPS)}, compare op"
    )


def _validate_features(raw: Any) -> list[FeatureDecl]:
    items = _require_list(raw, "features")
    if not items:
        raise StrategyDslError("features must be non-empty for DSL v2")
    seen: set[str] = set()
    out: list[FeatureDecl] = []
    for i, item in enumerate(items):
        d = _require_dict(item, f"features[{i}]")
        alias = str(d.get("alias") or d.get("id") or "").strip()
        name = str(d.get("name") or "").strip().lower()
        if not alias or not alias.replace("_", "").isalnum():
            raise StrategyDslError(f"features[{i}].alias must be alphanumeric/underscore")
        if alias in seen:
            raise StrategyDslError(f"duplicate feature alias {alias!r}")
        seen.add(alias)
        if name in FORBIDDEN_OHLCV_FEATURES:
            raise StrategyDslError(f"feature {name!r} is forbidden from OHLCV data")
        if name not in ALLOWED_FEATURE_NAMES:
            raise StrategyDslError(f"unsupported feature name {name!r}")
        period = d.get("period")
        if period is not None:
            period = int(period)
            lo, hi = PARAM_RANGES["period"]
            if period < lo or period > hi:
                raise StrategyDslError(f"features[{i}].period out of range [{lo},{hi}]")
        params = dict(d.get("params") or {})
        if any(k.startswith("__") for k in params):
            raise StrategyDslError("feature params cannot use dunder keys")
        # Reject anything that looks like code
        for bad in ("eval", "exec", "import", "open", "os", "sys", "subprocess"):
            if bad in params or bad == name:
                raise StrategyDslError(f"forbidden token {bad!r} in feature declaration")
        out.append(FeatureDecl(alias=alias, name=name, period=period, params=params))
    return out


def compile_strategy_dsl(spec: Mapping[str, Any]) -> CompiledStrategy:
    """Validate and compile a DSL v2 document. Raises StrategyDslError on reject."""
    doc = dict(spec)
    version = int(doc.get("dsl_version") or doc.get("dslVersion") or DSL_VERSION)
    if version != DSL_VERSION:
        raise StrategyDslError(f"unsupported dsl_version {version}; only {DSL_VERSION} accepted")

    # Reject obvious code / escape hatches
    blob = json.dumps(doc, sort_keys=True)
    for bad in ("__import__", "eval(", "exec(", "os.system", "subprocess", "open(", "compile("):
        if bad in blob:
            raise StrategyDslError(f"forbidden token in strategy spec: {bad}")

    metadata = dict(doc.get("metadata") or {})
    family = str(doc.get("family") or metadata.get("family") or "custom").lower()
    if family not in STRATEGY_FAMILIES:
        raise StrategyDslError(f"unsupported strategy family {family!r}")

    universe = dict(doc.get("universe") or {})
    required_timeframes = [str(t) for t in (doc.get("required_timeframes") or doc.get("requiredTimeframes") or ["1h"])]
    if not required_timeframes:
        raise StrategyDslError("required_timeframes must be non-empty")

    features = _validate_features(doc.get("features"))
    aliases = {f.alias for f in features} | {"close"}

    regime_filters_raw = doc.get("regime_filters") or doc.get("regimeFilters")
    regime_filters = None
    if regime_filters_raw is not None:
        regime_filters = _validate_condition_tree(
            regime_filters_raw, feature_aliases=aliases, path="regime_filters"
        )

    entry = doc.get("entry_conditions") or doc.get("entryConditions")
    exit_c = doc.get("exit_conditions") or doc.get("exitConditions")
    if entry is None or exit_c is None:
        raise StrategyDslError("entry_conditions and exit_conditions are required")
    entry_conditions = _validate_condition_tree(entry, feature_aliases=aliases, path="entry_conditions")
    exit_conditions = _validate_condition_tree(exit_c, feature_aliases=aliases, path="exit_conditions")

    sizing = dict(doc.get("position_sizing") or doc.get("positionSizing") or {"kind": "none"})
    kind = str(sizing.get("kind") or "none").lower()
    if kind not in ALLOWED_SIZING_KINDS:
        raise StrategyDslError(f"unsupported position_sizing.kind {kind!r}")
    if kind == "fixed_fraction":
        frac = float(sizing.get("fraction", 0.1))
        if not 0.0 < frac <= 1.0:
            raise StrategyDslError("position_sizing.fraction must be in (0, 1]")
        sizing = {"kind": kind, "fraction": frac}
    elif kind == "fixed_qty":
        qty = float(sizing.get("qty", 0))
        if qty <= 0:
            raise StrategyDslError("position_sizing.qty must be > 0")
        sizing = {"kind": kind, "qty": qty}
    elif kind == "risk_fraction":
        rf = float(sizing.get("risk_fraction", sizing.get("fraction", 0.01)))
        if not 0.0 < rf <= 0.25:
            raise StrategyDslError("position_sizing.risk_fraction must be in (0, 0.25]")
        sizing = {"kind": kind, "risk_fraction": rf}
    else:
        sizing = {"kind": "none"}

    risk = dict(doc.get("risk_conditions") or doc.get("riskConditions") or {})
    for key in ("max_position_pct", "max_drawdown_pct", "per_trade_risk_pct"):
        if key in risk:
            val = float(risk[key])
            if val < 0 or val > 100:
                raise StrategyDslError(f"risk_conditions.{key} out of range")
            risk[key] = val

    execution = dict(doc.get("execution_preferences") or doc.get("executionPreferences") or {})
    order_type = str(execution.get("order_type") or "MARKET").upper()
    if order_type not in {"MARKET", "LIMIT"}:
        raise StrategyDslError(f"unsupported order_type {order_type}")
    execution["order_type"] = order_type

    cooldowns = dict(doc.get("cooldowns") or {})
    if "bars_after_exit" in cooldowns:
        cd = int(cooldowns["bars_after_exit"])
        if cd < 0 or cd > 500:
            raise StrategyDslError("cooldowns.bars_after_exit out of range")
        cooldowns["bars_after_exit"] = cd

    portfolio = dict(doc.get("portfolio_constraints") or doc.get("portfolioConstraints") or {})
    applicability = dict(doc.get("applicability") or {})
    brain_deps = [str(x) for x in (doc.get("brain_dependencies") or doc.get("brainDependencies") or [])]

    # No filesystem / network hooks
    for banned_key in ("path", "url", "endpoint", "script", "code", "python", "module"):
        if banned_key in doc:
            raise StrategyDslError(f"forbidden top-level key {banned_key!r}")

    payload = {
        "dsl_version": version,
        "family": family,
        "metadata": metadata,
        "universe": universe,
        "required_timeframes": required_timeframes,
        "features": [f.public_dict() for f in features],
        "regime_filters": regime_filters,
        "entry_conditions": entry_conditions,
        "exit_conditions": exit_conditions,
        "position_sizing": sizing,
        "risk_conditions": risk,
        "execution_preferences": execution,
        "cooldowns": cooldowns,
        "portfolio_constraints": portfolio,
        "applicability": applicability,
        "brain_dependencies": brain_deps,
    }
    content_hash = sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    return CompiledStrategy(
        dsl_version=version,
        family=family,
        metadata=metadata,
        universe=universe,
        required_timeframes=required_timeframes,
        features=features,
        regime_filters=regime_filters,
        entry_conditions=entry_conditions,
        exit_conditions=exit_conditions,
        position_sizing=sizing,
        risk_conditions=risk,
        execution_preferences=execution,
        cooldowns=cooldowns,
        portfolio_constraints=portfolio,
        applicability=applicability,
        brain_dependencies=brain_deps,
        content_hash=content_hash,
        legacy_kind=str(doc.get("legacy_kind") or "") or None,
    )


def legacy_rules_to_dsl_v2(
    *,
    parameters: Mapping[str, Any],
    entry_rules: Mapping[str, Any],
    exit_rules: Mapping[str, Any],
    risk_rules: Mapping[str, Any] | None = None,
    required_timeframes: Sequence[str] | None = None,
    brain_dependencies: Sequence[str] | None = None,
    name: str = "legacy",
) -> dict[str, Any]:
    """Convert v1 ma_cross / mean_reversion rule dicts into a DSL v2 document."""
    kind = str(entry_rules.get("kind") or "ma_cross").lower()
    if kind == "ma_cross":
        fast = int(parameters.get("fast_ma", entry_rules.get("fast_ma", 10)))
        slow = int(parameters.get("slow_ma", entry_rules.get("slow_ma", 30)))
        return {
            "dsl_version": DSL_VERSION,
            "family": "moving_average",
            "legacy_kind": "ma_cross",
            "metadata": {"name": name, "family": "moving_average"},
            "universe": {},
            "required_timeframes": list(required_timeframes or ["1h"]),
            "features": [
                {"alias": "fast", "name": "sma", "period": fast},
                {"alias": "slow", "name": "sma", "period": slow},
            ],
            "regime_filters": None,
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            # Match legacy: exit while fast < slow (not only on fresh cross)
            "exit_conditions": {"left": "fast", "op": "lt", "right": "slow"},
            "position_sizing": {"kind": "none"},
            "risk_conditions": dict(risk_rules or {}),
            "execution_preferences": {"order_type": "MARKET"},
            "cooldowns": {},
            "portfolio_constraints": {},
            "applicability": dict((risk_rules or {}).get("applicability") or {}),
            "brain_dependencies": list(brain_dependencies or []),
        }
    if kind == "mean_reversion":
        lookback = int(parameters.get("lookback", entry_rules.get("lookback", 20)))
        entry_z = float(entry_rules.get("entry_z", parameters.get("entry_z", -1.5)))
        exit_z = float(exit_rules.get("exit_z", parameters.get("exit_z", 0.0)))
        return {
            "dsl_version": DSL_VERSION,
            "family": "mean_reversion",
            "legacy_kind": "mean_reversion",
            "metadata": {"name": name, "family": "mean_reversion"},
            "universe": {},
            "required_timeframes": list(required_timeframes or ["1h"]),
            "features": [
                {"alias": "z", "name": "zscore", "period": lookback},
            ],
            "regime_filters": None,
            "entry_conditions": {"feature": "z", "op": "lte", "value": entry_z},
            "exit_conditions": {"feature": "z", "op": "gte", "value": exit_z},
            "position_sizing": {"kind": "none"},
            "risk_conditions": dict(risk_rules or {}),
            "execution_preferences": {"order_type": "MARKET"},
            "cooldowns": {},
            "portfolio_constraints": {},
            "applicability": {},
            "brain_dependencies": list(brain_dependencies or []),
        }
    # Already DSL-shaped?
    if "entry_conditions" in entry_rules or entry_rules.get("dsl_version") == DSL_VERSION:
        return dict(entry_rules)
    raise StrategyDslError(f"cannot convert legacy kind {kind!r} to DSL v2")


def family_template(family: str, *, symbol: str = "BTCUSDT", timeframe: str = "1h") -> dict[str, Any]:
    """Return a valid DSL v2 starter document for a supported family."""
    fam = family.lower()
    if fam not in STRATEGY_FAMILIES:
        raise StrategyDslError(f"unknown family {family!r}")
    base = {
        "dsl_version": DSL_VERSION,
        "family": fam if fam != "moving_average" else "moving_average",
        "metadata": {"name": f"{fam}_template", "family": fam},
        "universe": {"symbols": [symbol]},
        "required_timeframes": [timeframe],
        "position_sizing": {"kind": "fixed_fraction", "fraction": 0.1},
        "risk_conditions": {"max_position_pct": 25.0},
        "execution_preferences": {"order_type": "MARKET"},
        "cooldowns": {"bars_after_exit": 1},
        "portfolio_constraints": {"max_open_positions": 1},
        "applicability": {},
        "brain_dependencies": [],
        "regime_filters": None,
    }
    templates: dict[str, dict[str, Any]] = {
        "trend_following": {
            **base,
            "family": "trend_following",
            "features": [
                {"alias": "fast", "name": "ema", "period": 12},
                {"alias": "slow", "name": "ema", "period": 26},
                {"alias": "adx14", "name": "adx", "period": 14},
            ],
            "regime_filters": {"feature": "adx14", "op": "gte", "value": 20},
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            "exit_conditions": {"cross_below": ["fast", "slow"]},
            "applicability": {"trends": ["up"]},
        },
        "moving_average": {
            **base,
            "family": "moving_average",
            "features": [
                {"alias": "fast", "name": "sma", "period": 10},
                {"alias": "slow", "name": "sma", "period": 30},
            ],
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            "exit_conditions": {"cross_below": ["fast", "slow"]},
        },
        "momentum": {
            **base,
            "family": "momentum",
            "features": [
                {"alias": "roc10", "name": "roc", "period": 10},
                {"alias": "rsi14", "name": "rsi", "period": 14},
            ],
            "entry_conditions": {
                "all": [
                    {"feature": "roc10", "op": "gt", "value": 0.02},
                    {"feature": "rsi14", "op": "gt", "value": 55},
                ]
            },
            "exit_conditions": {"feature": "roc10", "op": "lt", "value": 0.0},
        },
        "mean_reversion": {
            **base,
            "family": "mean_reversion",
            "features": [{"alias": "z", "name": "zscore", "period": 20}],
            "entry_conditions": {"feature": "z", "op": "lte", "value": -1.5},
            "exit_conditions": {"feature": "z", "op": "gte", "value": 0.0},
        },
        "breakout": {
            **base,
            "family": "breakout",
            "features": [
                {"alias": "brk", "name": "breakout", "period": 20},
                {"alias": "volz", "name": "volume_z", "period": 20},
            ],
            "entry_conditions": {
                "all": [
                    {"feature": "brk", "op": "eq", "value": 1},
                    {"feature": "volz", "op": "gte", "value": 0.5},
                ]
            },
            "exit_conditions": {"feature": "brk", "op": "eq", "value": -1},
        },
        "volatility_breakout": {
            **base,
            "family": "volatility_breakout",
            "features": [
                {"alias": "atr14", "name": "atr", "period": 14},
                {"alias": "brk", "name": "breakout", "period": 10},
                {"alias": "rvol", "name": "realized_vol", "period": 20},
            ],
            "regime_filters": {"feature": "rvol", "op": "gte", "value": 0.01},
            "entry_conditions": {"feature": "brk", "op": "eq", "value": 1},
            "exit_conditions": {"feature": "brk", "op": "eq", "value": -1},
        },
        "range_trading": {
            **base,
            "family": "range_trading",
            "features": [
                {"alias": "z", "name": "zscore", "period": 30},
                {"alias": "adx14", "name": "adx", "period": 14},
            ],
            "regime_filters": {"feature": "adx14", "op": "lt", "value": 20},
            "entry_conditions": {"feature": "z", "op": "lte", "value": -1.0},
            "exit_conditions": {"feature": "z", "op": "gte", "value": 0.5},
        },
        "relative_strength": {
            **base,
            "family": "relative_strength",
            "features": [
                {"alias": "roc20", "name": "roc", "period": 20},
                {"alias": "rsi14", "name": "rsi", "period": 14},
            ],
            "entry_conditions": {
                "all": [
                    {"feature": "roc20", "op": "gt", "value": 0.05},
                    {"feature": "rsi14", "op": "gt", "value": 50},
                ]
            },
            "exit_conditions": {"feature": "roc20", "op": "lt", "value": 0.0},
        },
        "multi_timeframe": {
            **base,
            "family": "multi_timeframe",
            "required_timeframes": [timeframe, "4h"],
            "features": [
                {"alias": "fast", "name": "sma", "period": 10},
                {"alias": "slow", "name": "sma", "period": 30},
                {"alias": "slope", "name": "trend_slope", "period": 20},
            ],
            "regime_filters": {"feature": "slope", "op": "gt", "value": 0},
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            "exit_conditions": {"cross_below": ["fast", "slow"]},
        },
        "event_filtered": {
            **base,
            "family": "event_filtered",
            "features": [
                {"alias": "fast", "name": "sma", "period": 10},
                {"alias": "slow", "name": "sma", "period": 30},
            ],
            # Event gating is expressed as applicability metadata until news context is bound.
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            "exit_conditions": {"cross_below": ["fast", "slow"]},
            "applicability": {"requires_events": True},
        },
        "custom": {
            **base,
            "family": "custom",
            "features": [
                {"alias": "fast", "name": "sma", "period": 10},
                {"alias": "slow", "name": "sma", "period": 30},
            ],
            "entry_conditions": {"cross_above": ["fast", "slow"]},
            "exit_conditions": {"cross_below": ["fast", "slow"]},
        },
    }
    # Map aliases
    if fam == "moving_average":
        return templates["moving_average"]
    return templates.get(fam, templates["custom"])


@dataclass
class DslEvalContext:
    values: dict[str, float]
    prev_values: dict[str, float]
    regime: dict[str, Any] = field(default_factory=dict)
    measured: dict[str, dict[str, Any]] = field(default_factory=dict)


def _compare(op: str, left: float, right: float) -> bool:
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    if op == "eq":
        return abs(left - right) <= 1e-12
    if op == "neq":
        return abs(left - right) > 1e-12
    return False


def eval_condition(node: Mapping[str, Any], ctx: DslEvalContext) -> bool:
    if "all" in node:
        return all(eval_condition(c, ctx) for c in node["all"])
    if "any" in node:
        return any(eval_condition(c, ctx) for c in node["any"])
    if "not" in node:
        return not eval_condition(node["not"], ctx)
    if "cross_above" in node:
        left, right = node["cross_above"]
        if left not in ctx.values or right not in ctx.values:
            return False
        if left not in ctx.prev_values or right not in ctx.prev_values:
            return False
        return ctx.prev_values[left] <= ctx.prev_values[right] and ctx.values[left] > ctx.values[right]
    if "cross_below" in node:
        left, right = node["cross_below"]
        if left not in ctx.values or right not in ctx.values:
            return False
        if left not in ctx.prev_values or right not in ctx.prev_values:
            return False
        return ctx.prev_values[left] >= ctx.prev_values[right] and ctx.values[left] < ctx.values[right]
    if "regime" in node and isinstance(node["regime"], dict):
        for k, v in node["regime"].items():
            if ctx.regime.get(k) != v:
                return False
        return True
    regime_keys = [k for k in node if str(k).startswith("regime.")]
    if regime_keys:
        key = regime_keys[0]
        field_name = key.split(".", 1)[1]
        return ctx.regime.get(field_name) == node[key]
    if "feature" in node and "op" in node:
        alias = str(node["feature"])
        if alias not in ctx.values:
            return False
        return _compare(str(node["op"]), ctx.values[alias], float(node["value"]))
    if "left" in node and "right" in node and "op" in node:
        left, right = str(node["left"]), str(node["right"])
        if left not in ctx.values or right not in ctx.values:
            return False
        return _compare(str(node["op"]), ctx.values[left], ctx.values[right])
    return False


def _resolve_features(
    compiled: CompiledStrategy,
    bars: Sequence[Any],
    *,
    as_of: str,
    engine: FeatureEngine,
) -> tuple[dict[str, float], dict[str, dict[str, Any]], bool]:
    """Return (values, measured_meta, all_ready)."""
    values: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    ready = True
    if bars:
        values["close"] = float(bars[-1].close)
        meta["close"] = {"status": FeatureStatus.MEASURED.value, "value": values["close"]}
    for decl in compiled.features:
        if decl.name == "close":
            if bars:
                values[decl.alias] = float(bars[-1].close)
                meta[decl.alias] = {"status": FeatureStatus.MEASURED.value, "value": values[decl.alias]}
            else:
                ready = False
            continue
        fv = engine.compute(bars, decl.name, as_of=as_of, period=decl.period)
        meta[decl.alias] = fv.public_dict()
        if fv.status != FeatureStatus.MEASURED.value or fv.value is None:
            ready = False
            continue
        values[decl.alias] = float(fv.value)
    return values, meta, ready


def evaluate_compiled_strategy(
    compiled: CompiledStrategy,
    *,
    clock: SimulationClock | None = None,
    view: MarketView | None = None,
    position_qty: float = 0.0,
    bars_after_exit: int = 0,
    regime: Mapping[str, Any] | None = None,
    engine: FeatureEngine | None = None,
) -> dict[str, Any]:
    """Evaluate a compiled DSL strategy causally. Returns signal dict + diagnostics."""
    engine = engine or FeatureEngine()
    if view is not None:
        if view.as_of is None or view.index < 0:
            return _hold("clock not started", compiled)
        bars = view.visible_bars()
        as_of = view.as_of
    elif clock is not None:
        if clock.index < 0 or clock.current_ts is None:
            return _hold("clock not started", compiled)
        bars = list(clock.window(min(500, clock.index + 1)))
        as_of = clock.current_ts
    else:
        raise StrategyDslError("evaluate_compiled_strategy requires clock or view")

    # Cooldown after exit
    cooldown = int((compiled.cooldowns or {}).get("bars_after_exit") or 0)
    if position_qty <= 0 and cooldown > 0 and bars_after_exit < cooldown:
        return _hold(f"cooldown ({bars_after_exit}/{cooldown})", compiled, extra={"cooldown": True})

    values, meta, ready = _resolve_features(compiled, bars, as_of=as_of, engine=engine)
    if not ready:
        return _hold("insufficient feature history", compiled, extra={"features": meta})

    # Previous bar feature snapshot for cross detection
    prev_values: dict[str, float] = {}
    if len(bars) >= 2:
        prev_vals, _, prev_ready = _resolve_features(compiled, bars[:-1], as_of=bars[-2].ts, engine=engine)
        if prev_ready:
            prev_values = prev_vals

    ctx = DslEvalContext(
        values=values,
        prev_values=prev_values,
        regime=dict(regime or {}),
        measured=meta,
    )

    if compiled.regime_filters is not None:
        if not eval_condition(compiled.regime_filters, ctx):
            return _hold("regime filter blocked", compiled, extra={"features": meta, "regime": dict(regime or {})})

    side = OrderSide.HOLD.value
    rationale = "no setup"
    confidence = 0.4

    if position_qty <= 0:
        if eval_condition(compiled.entry_conditions, ctx):
            side = OrderSide.BUY.value
            rationale = "entry conditions satisfied"
            confidence = 0.65
    else:
        if eval_condition(compiled.exit_conditions, ctx):
            side = OrderSide.SELL.value
            rationale = "exit conditions satisfied"
            confidence = 0.6

    qty = None
    sizing = compiled.position_sizing
    if side == OrderSide.BUY.value:
        if sizing.get("kind") == "fixed_qty":
            qty = float(sizing["qty"])
        # fractions resolved later by RiskGuard / portfolio equity — expose intent only

    return {
        "side": side,
        "qty": qty,
        "confidence": confidence,
        "rationale": rationale,
        "parameters_used": {
            "family": compiled.family,
            "dsl_version": compiled.dsl_version,
            "content_hash": compiled.content_hash,
            "features": {k: meta[k].get("value") for k in values},
            "sizing": sizing,
            "legacy_kind": compiled.legacy_kind,
        },
        "features": meta,
        "dsl": True,
    }


def _hold(reason: str, compiled: CompiledStrategy, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "side": OrderSide.HOLD.value,
        "qty": None,
        "confidence": 0.1,
        "rationale": reason,
        "parameters_used": {
            "family": compiled.family,
            "dsl_version": compiled.dsl_version,
            "content_hash": compiled.content_hash,
        },
        "dsl": True,
    }
    if extra:
        payload.update(extra)
    return payload


def is_dsl_v2_document(obj: Mapping[str, Any] | None) -> bool:
    """True for a real DSL v2 document (features + conditions).

    Persisted wrappers ``{kind: dsl_v2, spec: {...}}`` return False — unwrap
    ``spec`` before compiling.
    """
    if not obj:
        return False
    if str(obj.get("kind") or "").lower() == "dsl_v2":
        return False
    has_body = "entry_conditions" in obj or "entryConditions" in obj
    has_features = "features" in obj
    if has_body and has_features:
        return True
    if int(obj.get("dsl_version") or obj.get("dslVersion") or 0) == DSL_VERSION and has_features and has_body:
        return True
    return False


def unwrap_dsl_spec(entry_rules: Mapping[str, Any] | None, *, metadata: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Extract a DSL v2 document from persisted strategy version shapes."""
    if entry_rules and str(entry_rules.get("kind") or "").lower() == "dsl_v2":
        nested = entry_rules.get("spec")
        if isinstance(nested, dict) and is_dsl_v2_document(nested):
            return dict(nested)
    if metadata:
        nested = metadata.get("dsl_spec")
        if isinstance(nested, dict) and is_dsl_v2_document(nested):
            return dict(nested)
    if entry_rules and is_dsl_v2_document(entry_rules):
        return dict(entry_rules)
    return None
