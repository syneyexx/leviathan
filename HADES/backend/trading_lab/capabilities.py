"""Capability matrix.

Three independent dimensions — instrument family, strategy family, order type — plus the
data level each combination actually needs. Enabling something here is a claim that real
backend logic exists for it, so every entry names the module that implements it.

``implementation`` values:

- ``implemented``            deterministic backend logic exists and runs on OHLCV data
- ``implemented_needs_data`` logic exists but is inert until a richer dataset is attached
- ``blocked_missing_data``   logic exists but HADES ships no dataset that can feed it
- ``not_supported``          deliberately refused; the reason is part of the entry

``verification`` values use the HADES truth vocabulary. Unit coverage for this matrix
lives in ``backend/tests/test_trading_lab*.py`` and is recorded as ``verified_on_host``
when those suites have been executed on a documented host (see ``docs/TRADING_LAB.md`` §8
and ``docs/CURRENT_STATUS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from trading_lab.contracts import DataLevel, InstrumentFamily, InstrumentSpec, OrderIntent, OrderType

VERIFICATION_DEFAULT = "verified_on_host"

ALL_ORDER_TYPES: tuple[OrderType, ...] = (
    "market",
    "limit",
    "stop_market",
    "stop_limit",
    "trailing_stop",
    "take_profit",
    "bracket",
)


@dataclass(frozen=True)
class InstrumentCapability:
    family: InstrumentFamily
    order_types: tuple[OrderType, ...]
    time_in_force: tuple[str, ...]
    supports_short: bool
    supports_reduce_only: bool
    supports_post_only: bool
    supports_multi_leg: bool
    required_data_level: DataLevel
    accounting_features: tuple[str, ...]
    implementation: str
    implemented_by: str
    verification: str = VERIFICATION_DEFAULT
    missing_external_data: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class StrategyCapability:
    family: str
    label: str
    horizons: tuple[str, ...]
    directions: tuple[str, ...]
    instrument_families: tuple[InstrumentFamily, ...]
    required_data_level: DataLevel
    min_instruments: int
    implementation: str
    implemented_by: str
    verification: str = VERIFICATION_DEFAULT
    missing_external_data: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class OrderTypeCapability:
    order_type: OrderType
    label: str
    required_data_level: DataLevel
    implementation: str
    implemented_by: str
    verification: str = VERIFICATION_DEFAULT
    notes: str = ""
    flags: tuple[str, ...] = field(default=())


INSTRUMENT_CAPABILITIES: dict[InstrumentFamily, InstrumentCapability] = {
    "crypto_spot": InstrumentCapability(
        family="crypto_spot",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=False,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("two_currency_wallet", "quote_fee", "min_notional", "lot_rounding"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::SpotAdapter",
        notes="Spot wallets cannot go short; a sell is capped at the held quantity.",
    ),
    "crypto_perpetual": InstrumentCapability(
        family="crypto_perpetual",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("funding", "mark_price", "index_price", "initial_margin", "maintenance_margin", "liquidation"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::PerpetualAdapter",
        missing_external_data=("historical funding rate series (falls back to 0 funding, reported as missing)",),
        notes="Funding uses the dataset funding_rate field when present; absence is reported, not invented.",
    ),
    "equity": InstrumentCapability(
        family="equity",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("splits", "dividends", "delisting", "borrow_availability", "short_borrow_fee", "reg_margin"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::EquityAdapter",
        missing_external_data=("corporate-action history", "borrow availability/fee history"),
        notes="Corporate actions are applied from the dataset's corporate_action events; none are fabricated.",
    ),
    "etf": InstrumentCapability(
        family="etf",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("splits", "distributions", "borrow_availability", "short_borrow_fee"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::EquityAdapter",
        missing_external_data=("distribution history",),
    ),
    "forex": InstrumentCapability(
        family="forex",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("base_quote_conversion", "rollover_financing", "session_hours", "pip_tick"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::ForexAdapter",
        missing_external_data=("tom/next swap points",),
        notes="Financing is modelled from financing_spread_annual; real swap points are venue-specific.",
    ),
    "future": InstrumentCapability(
        family="future",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("contract_multiplier", "expiry_settlement", "initial_margin", "maintenance_margin", "roll", "negative_prices"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::FutureAdapter",
        missing_external_data=("continuous-contract roll calendar per product",),
        notes="Negative prices are permitted when the instrument declares price_can_be_negative.",
    ),
    "option": InstrumentCapability(
        family="option",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_multi_leg=True,
        required_data_level="ohlcv",
        accounting_features=("multiplier", "expiry", "strike", "greeks", "exercise", "assignment", "leg_risk"),
        implementation="implemented_needs_data",
        implemented_by="trading_lab/adapters.py::OptionAdapter",
        missing_external_data=("option chain history", "implied-volatility surface", "dividend/borrow curve"),
        notes="Greeks use Black-Scholes on the dataset's underlying series; without a chain only single known contracts can be simulated.",
    ),
    "cfd": InstrumentCapability(
        family="cfd",
        order_types=ALL_ORDER_TYPES,
        time_in_force=("GTC", "DAY", "IOC", "FOK"),
        supports_short=True,
        supports_reduce_only=True,
        supports_post_only=False,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("broker_contract_spec", "dealer_spread", "overnight_financing", "margin"),
        implementation="implemented",
        implemented_by="trading_lab/adapters.py::CfdAdapter",
        missing_external_data=("broker-specific contract specification and spread schedule",),
        notes="CFDs are bilateral broker contracts; post-only has no meaning without an order book.",
    ),
    "bond": InstrumentCapability(
        family="bond",
        order_types=("market", "limit"),
        time_in_force=("GTC", "DAY"),
        supports_short=False,
        supports_reduce_only=True,
        supports_post_only=False,
        supports_multi_leg=False,
        required_data_level="ohlcv",
        accounting_features=("coupon", "accrued_interest", "clean_dirty_price", "redemption_at_maturity"),
        implementation="implemented_needs_data",
        implemented_by="trading_lab/adapters.py::BondAdapter",
        missing_external_data=("dealer quote history", "issuer coupon schedule"),
        notes="Stop and trailing order types are refused: dealer-quoted bonds have no continuous trigger tape here.",
    ),
}


STRATEGY_CAPABILITIES: dict[str, StrategyCapability] = {
    "trend_following": StrategyCapability(
        family="trend_following",
        label="Trend following (moving-average state)",
        horizons=("swing", "position"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::TrendFollowing",
    ),
    "momentum": StrategyCapability(
        family="momentum",
        label="Cross-sectional / time-series momentum",
        horizons=("swing", "position"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::Momentum",
    ),
    "breakout": StrategyCapability(
        family="breakout",
        label="Donchian channel breakout",
        horizons=("intraday", "swing", "position"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::Breakout",
    ),
    "mean_reversion": StrategyCapability(
        family="mean_reversion",
        label="Z-score mean reversion",
        horizons=("intraday", "swing"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::MeanReversion",
    ),
    "pairs_trading": StrategyCapability(
        family="pairs_trading",
        label="Two-leg spread reversion",
        horizons=("swing", "position"),
        directions=("long_short",),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "future"),
        required_data_level="ohlcv",
        min_instruments=2,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::PairsTrading",
        notes="Requires a short-capable leg; spot-only pairs degrade to long/flat and are reported as such.",
    ),
    "statistical_arbitrage": StrategyCapability(
        family="statistical_arbitrage",
        label="Multi-instrument cross-sectional residual",
        horizons=("swing",),
        directions=("long_short",),
        instrument_families=("equity", "etf", "crypto_spot", "crypto_perpetual"),
        required_data_level="ohlcv",
        min_instruments=3,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::StatisticalArbitrage",
    ),
    "carry_funding": StrategyCapability(
        family="carry_funding",
        label="Perpetual funding carry",
        horizons=("swing", "position"),
        directions=("long_short",),
        instrument_families=("crypto_perpetual",),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented_needs_data",
        implemented_by="trading_lab/strategies.py::CarryFunding",
        missing_external_data=("historical funding-rate series",),
        notes="Without funding observations the strategy holds flat and records missing_funding_data.",
    ),
    "basis": StrategyCapability(
        family="basis",
        label="Future/spot basis convergence",
        horizons=("swing", "position"),
        directions=("long_short",),
        instrument_families=("future", "crypto_perpetual", "crypto_spot"),
        required_data_level="ohlcv",
        min_instruments=2,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::BasisConvergence",
    ),
    "event_driven": StrategyCapability(
        family="event_driven",
        label="Point-in-time event/news reaction",
        horizons=("intraday", "swing"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("equity", "etf", "crypto_spot", "crypto_perpetual", "future", "forex"),
        required_data_level="event",
        min_instruments=1,
        implementation="blocked_missing_data",
        implemented_by="trading_lab/strategies.py::EventDriven",
        missing_external_data=("point-in-time news/event feed with publication timestamps",),
        notes="Logic is implemented and runs against an imported event dataset; HADES ships none.",
    ),
    "option_volatility": StrategyCapability(
        family="option_volatility",
        label="Implied vs realised volatility premium",
        horizons=("swing", "position"),
        directions=("long_short",),
        instrument_families=("option",),
        required_data_level="chain",
        min_instruments=1,
        implementation="blocked_missing_data",
        implemented_by="trading_lab/strategies.py::OptionVolatility",
        missing_external_data=("option chain history with implied volatility",),
    ),
    "market_making": StrategyCapability(
        family="market_making",
        label="Two-sided quoting",
        horizons=("scalping",),
        directions=("long_short",),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "future"),
        required_data_level="l2",
        min_instruments=1,
        implementation="blocked_missing_data",
        implemented_by="trading_lab/strategies.py::MarketMaking",
        missing_external_data=("level-2 order book or full quote tape",),
        notes="Refused on OHLCV. Queue position and adverse selection cannot be simulated from candles.",
    ),
    "execution_schedule": StrategyCapability(
        family="execution_schedule",
        label="TWAP/POV execution schedule",
        horizons=("intraday",),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::ExecutionSchedule",
        notes="Measures modelled participation cost of slicing a parent order; not an alpha strategy.",
    ),
    "model_signal": StrategyCapability(
        family="model_signal",
        label="Trained numerical model signal",
        horizons=("intraday", "swing", "position"),
        directions=("long_only", "short_only", "long_short"),
        instrument_families=("crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "cfd"),
        required_data_level="ohlcv",
        min_instruments=1,
        implementation="implemented",
        implemented_by="trading_lab/strategies.py::ModelSignal",
        notes="Requires a trained artefact from trading_lab/models.py; refuses to run without one.",
    ),
}


ORDER_TYPE_CAPABILITIES: dict[OrderType, OrderTypeCapability] = {
    "market": OrderTypeCapability(
        order_type="market",
        label="Market",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_fill_market",
        notes="Fills from the next event's open with half-spread, slippage and participation capping.",
    ),
    "limit": OrderTypeCapability(
        order_type="limit",
        label="Limit",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_fill_limit",
        flags=("post_only", "reduce_only"),
        notes="Requires the candle to trade through the limit; fill price is never better than the limit.",
    ),
    "stop_market": OrderTypeCapability(
        order_type="stop_market",
        label="Stop market",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_fill_stop",
        notes="Gap-aware: if the event opens beyond the stop, the fill uses the open, not the stop.",
    ),
    "stop_limit": OrderTypeCapability(
        order_type="stop_limit",
        label="Stop limit",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_fill_stop",
        notes="Trigger then limit; an unreachable limit after a gap correctly does not fill.",
    ),
    "trailing_stop": OrderTypeCapability(
        order_type="trailing_stop",
        label="Trailing stop",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_advance_trailing",
        notes="Trail anchor updates on each closed event only; intrabar trailing needs finer data.",
    ),
    "take_profit": OrderTypeCapability(
        order_type="take_profit",
        label="Take profit",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_fill_limit",
        flags=("reduce_only",),
    ),
    "bracket": OrderTypeCapability(
        order_type="bracket",
        label="Bracket / OCO",
        required_data_level="ohlcv",
        implementation="implemented",
        implemented_by="trading_lab/execution.py::_resolve_bracket",
        flags=("oco", "reduce_only"),
        notes="When stop and target are both inside one candle the conservative rule takes the stop and flags intrabar ambiguity.",
    ),
}

TIME_IN_FORCE_SUPPORT: dict[str, str] = {
    "GTC": "implemented — rests until filled or cancelled",
    "DAY": "implemented — expires at the instrument calendar's session end",
    "IOC": "implemented — fills what the event allows, remainder cancelled",
    "FOK": "implemented — all-or-nothing against the event's available liquidity",
}

DATA_LEVEL_AVAILABILITY: dict[DataLevel, str] = {
    "ohlcv": "available — CSV import, directory import and synthetic generation",
    "quote": "importable — no bundled source; bid/ask columns are read when present",
    "trades": "importable — no bundled source",
    "l2": "unavailable — no bundled source and no importer implemented",
    "chain": "importable — option chain CSV schema accepted; no bundled source",
    "fundamental": "importable — point-in-time fundamental CSV accepted; no bundled source",
    "event": "importable — point-in-time event CSV with published_at accepted; no bundled source",
}

DATA_LEVEL_ORDER: tuple[DataLevel, ...] = ("ohlcv", "quote", "trades", "l2", "chain", "fundamental", "event")


def _data_level_rank(level: DataLevel) -> int:
    try:
        return DATA_LEVEL_ORDER.index(level)
    except ValueError:
        return len(DATA_LEVEL_ORDER)


def instrument_capability(family: InstrumentFamily) -> InstrumentCapability:
    capability = INSTRUMENT_CAPABILITIES.get(family)
    if capability is None:
        raise KeyError(f"unknown_instrument_family:{family}")
    return capability


def validate_order_capability(
    spec: InstrumentSpec,
    intent: OrderIntent,
    *,
    available_data_levels: Iterable[DataLevel] = ("ohlcv",),
) -> tuple[bool, str]:
    """Reject invalid instrument/order/data combinations with a usable reason."""
    capability = instrument_capability(spec.family)
    levels = set(available_data_levels)
    if intent.order_type not in capability.order_types:
        return False, (
            f"order_type_not_supported_for_family:{intent.order_type}/{spec.family} — "
            f"{capability.notes or 'no venue mechanism modelled'}"
        )
    if intent.time_in_force not in capability.time_in_force:
        return False, f"time_in_force_not_supported_for_family:{intent.time_in_force}/{spec.family}"
    if intent.post_only and not capability.supports_post_only:
        return False, f"post_only_not_supported_for_family:{spec.family}"
    if intent.reduce_only and not capability.supports_reduce_only:
        return False, f"reduce_only_not_supported_for_family:{spec.family}"
    if intent.legs and not capability.supports_multi_leg:
        return False, f"multi_leg_not_supported_for_family:{spec.family}"
    if intent.legs and len(intent.legs) > 8:
        return False, "too_many_legs"
    order_capability = ORDER_TYPE_CAPABILITIES[intent.order_type]
    if order_capability.required_data_level not in levels:
        return False, f"missing_data_level_for_order_type:{order_capability.required_data_level}"
    if capability.required_data_level not in levels:
        return False, f"missing_data_level_for_instrument:{capability.required_data_level}"
    if intent.side == "sell" and not spec.shorting_allowed and not intent.reduce_only:
        return False, (
            f"short_not_allowed_for_instrument:{spec.instrument_id} — "
            "use reduce_only to sell held quantity"
        )
    if spec.min_notional > 0 and intent.limit_price is not None:
        notional = intent.quantity * intent.limit_price * spec.multiplier
        if notional < spec.min_notional:
            return False, f"below_min_notional:{spec.min_notional}"
    return True, "ok"


def validate_strategy_capability(
    family: str,
    instruments: Iterable[InstrumentSpec],
    *,
    available_data_levels: Iterable[DataLevel] = ("ohlcv",),
    direction: str = "long_only",
) -> tuple[bool, str]:
    capability = STRATEGY_CAPABILITIES.get(family)
    if capability is None:
        return False, f"unknown_strategy_family:{family}"
    specs = list(instruments)
    if len(specs) < capability.min_instruments:
        return False, f"strategy_needs_at_least_{capability.min_instruments}_instruments"
    # Instrument-family fit is checked before direction so a mismatched market
    # (e.g. option_volatility on spot) is refused for the structural reason first.
    for spec in specs:
        if spec.family not in capability.instrument_families:
            return False, f"instrument_family_not_supported_by_strategy:{spec.family}/{family}"
    if direction not in capability.directions:
        return False, f"direction_not_supported_for_strategy:{direction}/{family}"
    for spec in specs:
        if direction in {"short_only", "long_short"} and not spec.shorting_allowed:
            return False, f"strategy_requires_short_but_instrument_forbids_it:{spec.instrument_id}"
    levels = set(available_data_levels)
    if capability.required_data_level not in levels:
        return False, (
            f"missing_data_level_for_strategy:{capability.required_data_level} — "
            f"{DATA_LEVEL_AVAILABILITY.get(capability.required_data_level, 'unknown level')}"
        )
    return True, "ok"


def capability_matrix() -> dict[str, Any]:
    """Machine-readable matrix used by the API, the UI and the delivery report."""
    return {
        "instruments": [
            {
                "family": item.family,
                "order_types": list(item.order_types),
                "time_in_force": list(item.time_in_force),
                "supports_short": item.supports_short,
                "supports_reduce_only": item.supports_reduce_only,
                "supports_post_only": item.supports_post_only,
                "supports_multi_leg": item.supports_multi_leg,
                "required_data_level": item.required_data_level,
                "accounting_features": list(item.accounting_features),
                "implementation": item.implementation,
                "implemented_by": item.implemented_by,
                "verification": item.verification,
                "missing_external_data": list(item.missing_external_data),
                "notes": item.notes,
            }
            for item in INSTRUMENT_CAPABILITIES.values()
        ],
        "strategies": [
            {
                "family": item.family,
                "label": item.label,
                "horizons": list(item.horizons),
                "directions": list(item.directions),
                "instrument_families": list(item.instrument_families),
                "required_data_level": item.required_data_level,
                "min_instruments": item.min_instruments,
                "implementation": item.implementation,
                "implemented_by": item.implemented_by,
                "verification": item.verification,
                "missing_external_data": list(item.missing_external_data),
                "notes": item.notes,
            }
            for item in STRATEGY_CAPABILITIES.values()
        ],
        "order_types": [
            {
                "order_type": item.order_type,
                "label": item.label,
                "required_data_level": item.required_data_level,
                "implementation": item.implementation,
                "implemented_by": item.implemented_by,
                "verification": item.verification,
                "flags": list(item.flags),
                "notes": item.notes,
            }
            for item in ORDER_TYPE_CAPABILITIES.values()
        ],
        "time_in_force": TIME_IN_FORCE_SUPPORT,
        "data_levels": DATA_LEVEL_AVAILABILITY,
        "execution_mode": "SIMULATION/PAPER only — no broker session, no real-money path",
        "verification_disclaimer": (
            "Implementation status describes code that exists and was statically reviewed. "
            "Tests for these paths were written but not executed in the change that introduced them."
        ),
    }


def instrument_order_support(spec: InstrumentSpec) -> dict[str, Any]:
    """Order-ticket capabilities for one concrete instrument."""
    capability = instrument_capability(spec.family)
    return {
        "instrument_id": spec.instrument_id,
        "family": spec.family,
        "order_types": list(capability.order_types),
        "time_in_force": list(capability.time_in_force),
        "supports_short": capability.supports_short and spec.shorting_allowed,
        "supports_reduce_only": capability.supports_reduce_only,
        "supports_post_only": capability.supports_post_only,
        "supports_multi_leg": capability.supports_multi_leg,
        "tick_size": str(spec.tick_size),
        "lot_size": str(spec.lot_size),
        "min_notional": str(spec.min_notional),
        "multiplier": str(spec.multiplier),
        "price_can_be_negative": spec.price_can_be_negative,
        "borrow_available": spec.borrow_available,
        "quote_currency": spec.quote_currency,
        "settlement_currency": spec.settle_currency,
        "accounting_features": list(capability.accounting_features),
        "missing_external_data": list(capability.missing_external_data),
        "notes": capability.notes,
    }


def strategy_families_for(spec: InstrumentSpec) -> list[str]:
    return sorted(
        family
        for family, capability in STRATEGY_CAPABILITIES.items()
        if spec.family in capability.instrument_families
    )


def highest_data_level(levels: Iterable[DataLevel]) -> DataLevel:
    best: DataLevel = "ohlcv"
    for level in levels:
        if _data_level_rank(level) > _data_level_rank(best):
            best = level
    return best


MAX_PARTICIPATION_CEILING = Decimal("0.25")

__all__ = [
    "ALL_ORDER_TYPES",
    "DATA_LEVEL_AVAILABILITY",
    "INSTRUMENT_CAPABILITIES",
    "MAX_PARTICIPATION_CEILING",
    "ORDER_TYPE_CAPABILITIES",
    "STRATEGY_CAPABILITIES",
    "TIME_IN_FORCE_SUPPORT",
    "VERIFICATION_DEFAULT",
    "InstrumentCapability",
    "OrderTypeCapability",
    "StrategyCapability",
    "capability_matrix",
    "highest_data_level",
    "instrument_capability",
    "instrument_order_support",
    "strategy_families_for",
    "validate_order_capability",
    "validate_strategy_capability",
]
