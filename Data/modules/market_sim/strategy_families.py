"""Canonical strategy family registry — single source of truth for DSL kinds learners may generate.

Consumers: learning_candidates, learning_types, UI labels, capability truth.
Do NOT maintain parallel family lists elsewhere — import from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .strategy_dsl import SUPPORTED_KINDS


@dataclass(frozen=True)
class StrategyFamilyDescriptor:
    """Descriptor for one Strategy DSL family the research system understands."""

    family_id: str
    dsl_kind: str
    label: str
    description: str
    default_parameters: dict[str, Any] = field(default_factory=dict)
    parameter_ranges: dict[str, dict[str, float]] = field(default_factory=dict)
    compatible_features: tuple[str, ...] = ()
    mutation_dimensions: tuple[str, ...] = ()
    exit_options: tuple[str, ...] = ()
    risk_options: tuple[str, ...] = ("stop_loss_pct", "max_position_pct")
    required_data: tuple[str, ...] = ("ohlcv",)
    supported_timeframes: tuple[str, ...] = ()
    learner_may_generate: bool = True
    research_profitable_family: bool = True
    capability_requirements: tuple[str, ...] = ()
    entry_template: dict[str, Any] = field(default_factory=dict)
    exit_template: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "dsl_kind": self.dsl_kind,
            "label": self.label,
            "description": self.description,
            "default_parameters": dict(self.default_parameters),
            "parameter_ranges": {k: dict(v) for k, v in self.parameter_ranges.items()},
            "compatible_features": list(self.compatible_features),
            "mutation_dimensions": list(self.mutation_dimensions),
            "exit_options": list(self.exit_options),
            "risk_options": list(self.risk_options),
            "required_data": list(self.required_data),
            "supported_timeframes": list(self.supported_timeframes),
            "learner_may_generate": self.learner_may_generate,
            "research_profitable_family": self.research_profitable_family,
            "capability_requirements": list(self.capability_requirements),
        }


def _tpl(
    kind: str,
    parameters: dict[str, Any],
    *,
    entry_extra: dict[str, Any] | None = None,
    exit_extra: dict[str, Any] | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    entry: dict[str, Any] = {
        "version": 3,
        "kind": kind,
        "parameters": dict(parameters),
    }
    if entry_extra:
        entry.update(entry_extra)
    if filters:
        entry["filters"] = list(filters)
    exit_rules: dict[str, Any] = {"kind": kind, **dict(exit_extra or {})}
    return entry, exit_rules, dict(parameters)


_FAMILIES: dict[str, StrategyFamilyDescriptor] = {}


def _register(desc: StrategyFamilyDescriptor) -> StrategyFamilyDescriptor:
    _FAMILIES[desc.family_id] = desc
    return desc


def _build_registry() -> None:
    if _FAMILIES:
        return

    e, x, p = _tpl("ma_cross", {"fast_ma": 10, "slow_ma": 30, "lookback": 30})
    _register(
        StrategyFamilyDescriptor(
            family_id="ma_cross",
            dsl_kind="ma_cross",
            label="Moving Average Cross",
            description="Trend-following MA crossover entries/exits.",
            default_parameters=p,
            parameter_ranges={
                "fast_ma": {"min": 3, "max": 50},
                "slow_ma": {"min": 10, "max": 200},
            },
            compatible_features=("sma", "ema", "trend"),
            mutation_dimensions=("fast_ma", "slow_ma", "stop_loss"),
            exit_options=("ma_cross",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl("mean_reversion", {"lookback": 20, "z_entry": 1.5, "z_exit": 0.25})
    _register(
        StrategyFamilyDescriptor(
            family_id="mean_reversion",
            dsl_kind="mean_reversion",
            label="Mean Reversion",
            description="Z-score mean reversion around a rolling mean.",
            default_parameters=p,
            parameter_ranges={
                "lookback": {"min": 5, "max": 100},
                "z_entry": {"min": 0.5, "max": 3.0},
                "z_exit": {"min": 0.0, "max": 1.5},
            },
            compatible_features=("zscore", "sma", "volatility"),
            mutation_dimensions=("lookback", "z_entry", "z_exit", "stop_loss"),
            exit_options=("mean_reversion",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl("breakout", {"period": 20})
    _register(
        StrategyFamilyDescriptor(
            family_id="breakout",
            dsl_kind="breakout",
            label="Breakout",
            description="Donchian-style high/low breakout.",
            default_parameters=p,
            parameter_ranges={"period": {"min": 5, "max": 100}},
            compatible_features=("donchian", "atr", "volume"),
            mutation_dimensions=("period", "stop_loss"),
            exit_options=("breakout",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl(
        "rsi",
        {"period": 14, "oversold": 30, "overbought": 70},
        entry_extra={"entry": {"oversold": 30, "overbought": 70}, "exit": {"overbought": 70}},
        exit_extra={"overbought": 70},
    )
    _register(
        StrategyFamilyDescriptor(
            family_id="rsi",
            dsl_kind="rsi",
            label="RSI",
            description="RSI oversold/overbought mean-reversion.",
            default_parameters=p,
            parameter_ranges={
                "period": {"min": 5, "max": 30},
                "oversold": {"min": 10, "max": 40},
                "overbought": {"min": 60, "max": 90},
            },
            compatible_features=("rsi",),
            mutation_dimensions=("period", "oversold", "overbought", "stop_loss"),
            exit_options=("rsi",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl("momentum", {"lookback": 20, "threshold": 0.02})
    _register(
        StrategyFamilyDescriptor(
            family_id="momentum",
            dsl_kind="momentum",
            label="Momentum",
            description="Return momentum over a lookback window.",
            default_parameters=p,
            parameter_ranges={
                "lookback": {"min": 5, "max": 120},
                "threshold": {"min": 0.0, "max": 0.2},
            },
            compatible_features=("returns", "momentum", "roc"),
            mutation_dimensions=("lookback", "threshold", "stop_loss"),
            exit_options=("momentum",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl("volatility", {"lookback": 20, "vol_entry": 1.5, "vol_exit": 0.8})
    _register(
        StrategyFamilyDescriptor(
            family_id="volatility",
            dsl_kind="volatility",
            label="Volatility",
            description="Volatility expansion/contraction regime entries.",
            default_parameters=p,
            parameter_ranges={
                "lookback": {"min": 5, "max": 100},
                "vol_entry": {"min": 0.5, "max": 3.0},
                "vol_exit": {"min": 0.2, "max": 2.0},
            },
            compatible_features=("realized_vol", "atr", "bollinger"),
            mutation_dimensions=("lookback", "vol_entry", "vol_exit", "stop_loss"),
            exit_options=("volatility",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl(
        "relative_strength",
        {"lookback": 20, "threshold": 0.01},
        entry_extra={"parameters": {"lookback": 20, "threshold": 0.01, "benchmark_feature": "sma"}},
    )
    _register(
        StrategyFamilyDescriptor(
            family_id="relative_strength",
            dsl_kind="relative_strength",
            label="Relative Strength",
            description="Relative strength vs benchmark feature/series.",
            default_parameters=p,
            parameter_ranges={
                "lookback": {"min": 5, "max": 120},
                "threshold": {"min": 0.0, "max": 0.1},
            },
            compatible_features=("relative_strength", "sma", "returns"),
            mutation_dimensions=("lookback", "threshold", "stop_loss"),
            exit_options=("relative_strength",),
            required_data=("ohlcv",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl(
        "pairs_spread",
        {"lookback": 30, "z_entry": 2.0, "z_exit": 0.5},
    )
    _register(
        StrategyFamilyDescriptor(
            family_id="pairs_spread",
            dsl_kind="pairs_spread",
            label="Pairs Spread",
            description="Pairs/spread mean reversion (requires aligned multi-asset data).",
            default_parameters=p,
            parameter_ranges={
                "lookback": {"min": 10, "max": 120},
                "z_entry": {"min": 0.5, "max": 3.5},
                "z_exit": {"min": 0.0, "max": 1.5},
            },
            compatible_features=("spread", "zscore", "correlation"),
            mutation_dimensions=("lookback", "z_entry", "z_exit", "stop_loss"),
            exit_options=("pairs_spread",),
            required_data=("ohlcv", "multi_asset"),
            capability_requirements=("multi_asset",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl(
        "feature_compare",
        {"left_period": 10, "right_period": 30},
        entry_extra={
            "entry": {
                "left": "sma",
                "op": ">",
                "right_feature": "sma",
                "left_period": 10,
                "right_period": 30,
            },
            "parameters": {},
        },
    )
    _register(
        StrategyFamilyDescriptor(
            family_id="feature_compare",
            dsl_kind="feature_compare",
            label="Feature Compare",
            description="Declarative feature comparison entry/exit.",
            default_parameters=p,
            parameter_ranges={
                "left_period": {"min": 2, "max": 100},
                "right_period": {"min": 5, "max": 200},
            },
            compatible_features=("sma", "ema", "rsi", "atr"),
            mutation_dimensions=("left_period", "right_period", "stop_loss"),
            exit_options=("feature_compare",),
            entry_template=e,
            exit_template=x,
        )
    )

    e, x, p = _tpl(
        "composite",
        {"fast_ma": 10, "slow_ma": 40},
        filters=[{"kind": "regime_filter", "mode": "adx", "period": 14, "min_adx": 20}],
        exit_extra={"kind": "ma_cross"},
    )
    # Fix exit kind for composite (ma_cross exits)
    x = {"kind": "ma_cross"}
    _register(
        StrategyFamilyDescriptor(
            family_id="composite",
            dsl_kind="composite",
            label="Composite",
            description="Composite signal with optional regime filters.",
            default_parameters=p,
            parameter_ranges={
                "fast_ma": {"min": 3, "max": 50},
                "slow_ma": {"min": 10, "max": 200},
            },
            compatible_features=("sma", "adx", "regime"),
            mutation_dimensions=("fast_ma", "slow_ma", "filters", "stop_loss"),
            exit_options=("ma_cross", "composite"),
            entry_template=e,
            exit_template=x,
        )
    )

    # hold is operationally valid but NOT a profitable research family
    e, x, p = _tpl("hold", {})
    _register(
        StrategyFamilyDescriptor(
            family_id="hold",
            dsl_kind="hold",
            label="Hold",
            description="Operational flat/hold — not a research profitability family.",
            default_parameters=p,
            learner_may_generate=False,
            research_profitable_family=False,
            entry_template=e,
            exit_template=x,
        )
    )


def all_family_descriptors() -> dict[str, StrategyFamilyDescriptor]:
    _build_registry()
    return dict(_FAMILIES)


def get_family(family_id: str) -> StrategyFamilyDescriptor | None:
    _build_registry()
    return _FAMILIES.get(str(family_id or "").strip())


def research_generatable_families() -> tuple[str, ...]:
    """Families the evolutionary/agent learner may generate (excludes hold)."""
    _build_registry()
    return tuple(
        fid
        for fid, d in _FAMILIES.items()
        if d.learner_may_generate and d.research_profitable_family and d.dsl_kind in SUPPORTED_KINDS
    )


# Canonical export used by learning_types / learning_candidates
SUPPORTED_STRATEGY_FAMILIES: tuple[str, ...] = ()


def _init_supported() -> tuple[str, ...]:
    global SUPPORTED_STRATEGY_FAMILIES
    SUPPORTED_STRATEGY_FAMILIES = research_generatable_families()
    return SUPPORTED_STRATEGY_FAMILIES


_init_supported()


def family_templates() -> dict[str, dict[str, Any]]:
    """Template dicts compatible with legacy FAMILY_TEMPLATES consumers."""
    _build_registry()
    out: dict[str, dict[str, Any]] = {}
    for fid in research_generatable_families():
        desc = _FAMILIES[fid]
        out[fid] = {
            "entry_rules": dict(desc.entry_template),
            "exit_rules": dict(desc.exit_template),
            "parameters": dict(desc.default_parameters),
        }
    return out


def family_labels() -> dict[str, str]:
    _build_registry()
    return {fid: d.label for fid, d in _FAMILIES.items()}


def assert_family_registry_covers_dsl() -> list[str]:
    """Return DSL kinds missing from registry (for tests)."""
    _build_registry()
    registered = {d.dsl_kind for d in _FAMILIES.values()}
    return sorted(SUPPORTED_KINDS - registered)


__all__ = [
    "StrategyFamilyDescriptor",
    "SUPPORTED_STRATEGY_FAMILIES",
    "all_family_descriptors",
    "assert_family_registry_covers_dsl",
    "family_labels",
    "family_templates",
    "get_family",
    "research_generatable_families",
]
