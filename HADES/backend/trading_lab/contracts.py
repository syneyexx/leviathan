"""Validated contracts shared by every Trading Lab layer.

Money and position quantities are ``Decimal`` because they are booked into a ledger that
must reconcile exactly. Market observations stay ``float`` because that is what the source
data is; the conversion happens once, at the execution boundary, via :func:`to_decimal`.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- primitive helpers ---------------------------------------------------------------

MONEY_PLACES = Decimal("0.00000001")

InstrumentFamily = Literal[
    "crypto_spot",
    "crypto_perpetual",
    "equity",
    "etf",
    "forex",
    "future",
    "option",
    "cfd",
    "bond",
]

DataLevel = Literal["ohlcv", "quote", "trades", "l2", "chain", "fundamental", "event"]

OrderType = Literal[
    "market",
    "limit",
    "stop_market",
    "stop_limit",
    "trailing_stop",
    "take_profit",
    "bracket",
]

TimeInForce = Literal["GTC", "DAY", "IOC", "FOK"]

OrderSide = Literal["buy", "sell"]

PositionSide = Literal["long", "short"]

SplitName = Literal["development", "validation", "sealed_test", "prospective_paper", "synthetic"]

RunMode = Literal["historical_simulation", "paper", "synthetic_stress"]

ViewRole = Literal["agent", "evaluator", "operator_review"]


def to_decimal(value: Any, *, default: Decimal | None = None) -> Decimal:
    """Convert to ``Decimal`` without going through binary float rounding."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non_finite_decimal")
        return value
    if value is None:
        if default is None:
            raise ValueError("missing_decimal")
        return default
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non_finite_decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid_decimal:{value!r}") from exc
    if not result.is_finite():
        raise ValueError("non_finite_decimal")
    return result


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_EVEN)


def quantize_step(value: Decimal, step: Decimal, *, rounding: str = ROUND_DOWN) -> Decimal:
    """Round ``value`` onto a tick/lot grid. ``step <= 0`` means no grid."""
    if step <= 0:
        return value
    return (value / step).quantize(Decimal(1), rounding=rounding) * step


def utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def stable_hash(payload: Any) -> str:
    """Deterministic content hash used for strategy/dataset/config identity."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LabModel(BaseModel):
    """Strict base: unknown keys are a contract violation, not a silent no-op."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# --- instruments ---------------------------------------------------------------------


class OptionTerms(LabModel):
    right: Literal["call", "put"]
    strike: Decimal
    expiry: str
    exercise_style: Literal["european", "american"] = "european"
    settlement: Literal["cash", "physical"] = "cash"
    underlying_instrument_id: str


class FutureTerms(LabModel):
    expiry: str
    settlement: Literal["cash", "physical"] = "cash"
    underlying_instrument_id: str | None = None
    roll_days_before_expiry: int = Field(default=3, ge=0, le=60)


class BondTerms(LabModel):
    coupon_rate: Decimal = Field(description="Annual coupon as a fraction of face value.")
    coupon_frequency: int = Field(default=2, ge=0, le=12)
    face_value: Decimal = Decimal("1000")
    maturity: str
    day_count: Literal["30/360", "ACT/365", "ACT/ACT"] = "30/360"
    first_coupon: str | None = None
    quote_convention: Literal["clean", "dirty"] = "clean"


class InstrumentSpec(LabModel):
    """Identity and contract rules of one tradable instrument."""

    instrument_id: str = Field(min_length=3, max_length=160)
    family: InstrumentFamily
    venue: str = Field(min_length=1, max_length=40)
    symbol: str = Field(min_length=1, max_length=60)
    description: str = ""
    base_currency: str = Field(min_length=2, max_length=10)
    quote_currency: str = Field(min_length=2, max_length=10)
    settlement_currency: str | None = None
    multiplier: Decimal = Decimal("1")
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("0.00000001")
    min_notional: Decimal = Decimal("0")
    price_can_be_negative: bool = False
    shorting_allowed: bool = True
    calendar: str = "24x7"
    timezone: str = "UTC"
    listed_from: str | None = None
    delisted_at: str | None = None
    initial_margin_rate: Decimal = Decimal("1")
    maintenance_margin_rate: Decimal = Decimal("1")
    funding_interval_hours: int | None = None
    borrow_available: bool = True
    borrow_fee_annual: Decimal = Decimal("0")
    financing_spread_annual: Decimal = Decimal("0")
    option_terms: OptionTerms | None = None
    future_terms: FutureTerms | None = None
    bond_terms: BondTerms | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instrument_id")
    @classmethod
    def _identity_shape(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError("instrument_id must be '<family>:<venue>:<symbol>'")
        return value

    @model_validator(mode="after")
    def _family_terms(self) -> "InstrumentSpec":
        if self.family == "option" and self.option_terms is None:
            raise ValueError("option instruments require option_terms")
        if self.family == "future" and self.future_terms is None:
            raise ValueError("future instruments require future_terms")
        if self.family == "bond" and self.bond_terms is None:
            raise ValueError("bond instruments require bond_terms")
        if self.family == "crypto_perpetual" and not self.funding_interval_hours:
            raise ValueError("perpetual instruments require funding_interval_hours")
        if self.tick_size <= 0 or self.lot_size <= 0 or self.multiplier <= 0:
            raise ValueError("tick_size, lot_size and multiplier must be positive")
        return self

    @property
    def settle_currency(self) -> str:
        return self.settlement_currency or self.quote_currency

    def validate_price(self, price: float | Decimal) -> None:
        """Instrument-specific price rule. There is no universal positive-price rule."""
        value = to_decimal(price)
        if self.price_can_be_negative:
            return
        if value <= 0:
            raise ValueError(f"non_positive_price_not_allowed:{self.instrument_id}")


# --- market data ---------------------------------------------------------------------


class DataQualityIssue(LabModel):
    code: str
    severity: Literal["info", "warning", "error"]
    count: int = 0
    detail: str = ""
    sample: list[str] = Field(default_factory=list)


class DataQualityReport(LabModel):
    rows_in: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    first_event_time: str | None = None
    last_event_time: str | None = None
    expected_bars: int | None = None
    missing_bars: int | None = None
    gap_ratio: float | None = None
    stale_runs: int = 0
    duplicate_timestamps: int = 0
    out_of_order: int = 0
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


class DatasetManifest(LabModel):
    """Immutable description of one market-history version bound to experiments."""

    dataset_id: str
    name: str
    instrument_id: str
    timeframe: str
    data_level: DataLevel = "ohlcv"
    provider: str
    provider_kind: Literal["import", "download", "synthetic"] = "import"
    source_reference: str = ""
    licence: str = "unspecified"
    is_synthetic: bool = False
    revision: int = 1
    row_count: int = 0
    first_event_time: str | None = None
    last_event_time: str | None = None
    calendar: str = "24x7"
    timezone: str = "UTC"
    availability_delay_seconds: int = 0
    content_checksum: str = ""
    partitions: list[str] = Field(default_factory=list)
    quality: DataQualityReport | None = None
    corporate_actions: int = 0
    frozen: bool = False
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketEvent(LabModel):
    """One point-in-time market observation with explicit availability bookkeeping."""

    instrument_id: str
    timeframe: str
    event_time: str
    available_at: str
    ingested_at: str = ""
    kind: Literal["bar", "quote", "trade", "funding", "corporate_action", "news", "macro"] = "bar"
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float = 0.0
    bid: float | None = None
    ask: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    revision: int = 1
    source: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def reference_price(self) -> float:
        for candidate in (self.close, self.mark_price, self.index_price, self.bid, self.ask):
            if candidate is not None:
                return float(candidate)
        raise ValueError(f"market_event_without_price:{self.instrument_id}@{self.event_time}")


class Observation(LabModel):
    """What a strategy or agent is allowed to see at one simulation instant."""

    as_of: str
    instrument_id: str
    timeframe: str
    dataset_id: str
    split: SplitName
    bars: list[MarketEvent] = Field(default_factory=list)
    auxiliary: dict[str, list[MarketEvent]] = Field(default_factory=dict)
    data_level: DataLevel = "ohlcv"
    stale_seconds: float | None = None
    truncated: bool = False

    @property
    def closes(self) -> list[float]:
        return [bar.reference_price for bar in self.bars]

    @property
    def last(self) -> MarketEvent | None:
        return self.bars[-1] if self.bars else None


# --- strategies and experiments ------------------------------------------------------


class SizingSpec(LabModel):
    mode: Literal["fixed_notional", "equity_fraction", "fixed_quantity", "risk_per_trade"] = "equity_fraction"
    value: Decimal = Decimal("0.1")
    max_position_notional: Decimal | None = None

    @model_validator(mode="after")
    def _positive(self) -> "SizingSpec":
        if self.value <= 0:
            raise ValueError("sizing value must be positive")
        if self.mode == "equity_fraction" and self.value > 1:
            raise ValueError("equity_fraction sizing must be <= 1")
        return self


class StrategyHypothesis(LabModel):
    """The reasoning protocol contract: a strategy cannot exist without one."""

    economic_rationale: str = Field(min_length=20, max_length=4000)
    horizon: Literal["scalping", "intraday", "swing", "position"] = "swing"
    direction: Literal["long_only", "short_only", "long_short"] = "long_only"
    allowed_data: list[DataLevel] = Field(default_factory=lambda: ["ohlcv"])
    expected_costs: str = ""
    plausible_regimes: str = ""
    implausible_regimes: str = ""
    falsification_criteria: list[str] = Field(default_factory=list, max_length=20)
    benchmarks: list[str] = Field(default_factory=lambda: ["buy_and_hold"])
    no_trade_conditions: list[str] = Field(default_factory=list, max_length=20)
    evaluation_protocol: str = ""

    @model_validator(mode="after")
    def _requires_falsification(self) -> "StrategyHypothesis":
        if not self.falsification_criteria:
            raise ValueError("a hypothesis needs at least one falsification criterion")
        return self


class StrategySpec(LabModel):
    strategy_id: str = ""
    name: str = Field(min_length=1, max_length=160)
    family: str = Field(min_length=1, max_length=60)
    version: int = 1
    params: dict[str, Any] = Field(default_factory=dict)
    instruments: list[str] = Field(default_factory=list, max_length=40)
    timeframe: str = "1h"
    sizing: SizingSpec = Field(default_factory=SizingSpec)
    order_type: OrderType = "market"
    time_in_force: TimeInForce = "GTC"
    hypothesis: StrategyHypothesis | None = None
    required_data_level: DataLevel = "ohlcv"
    scope_note: str = ""
    code_reference: str = ""
    code_hash: str = ""

    @model_validator(mode="after")
    def _has_instruments(self) -> "StrategySpec":
        if not self.instruments:
            raise ValueError("a strategy must declare at least one instrument")
        return self

    def content_hash(self) -> str:
        return stable_hash(
            {
                "family": self.family,
                "version": self.version,
                "params": self.params,
                "instruments": sorted(self.instruments),
                "timeframe": self.timeframe,
                "sizing": self.sizing.as_json(),
                "order_type": self.order_type,
                "time_in_force": self.time_in_force,
                "code_hash": self.code_hash,
            }
        )


class CostModel(LabModel):
    """Everything the execution layer charges. Never set by the strategy itself."""

    taker_fee_bps: Decimal = Decimal("5")
    maker_fee_bps: Decimal = Decimal("1")
    min_fee: Decimal = Decimal("0")
    half_spread_bps: Decimal = Decimal("2")
    slippage_bps: Decimal = Decimal("1")
    latency_events: int = Field(default=0, ge=0, le=100)
    max_volume_participation: Decimal = Decimal("0.1")
    reject_probability: Decimal = Decimal("0")
    borrow_fee_annual_override: Decimal | None = None
    funding_multiplier: Decimal = Decimal("1")
    intrabar_rule: Literal["conservative", "requires_finer_data"] = "conservative"

    @model_validator(mode="after")
    def _bounds(self) -> "CostModel":
        if self.max_volume_participation <= 0 or self.max_volume_participation > 1:
            raise ValueError("max_volume_participation must be in (0, 1]")
        if not Decimal("0") <= self.reject_probability <= Decimal("1"):
            raise ValueError("reject_probability must be in [0, 1]")
        return self


class RiskLimits(LabModel):
    max_position_notional: Decimal | None = Decimal("100000")
    max_gross_exposure: Decimal | None = Decimal("200000")
    max_net_exposure: Decimal | None = Decimal("150000")
    max_leverage: Decimal | None = Decimal("3")
    max_instrument_concentration: Decimal | None = Decimal("0.5")
    max_correlated_group_exposure: Decimal | None = Decimal("0.7")
    max_daily_loss: Decimal | None = Decimal("1000")
    max_drawdown_fraction: Decimal | None = Decimal("0.25")
    max_order_notional: Decimal | None = Decimal("50000")
    max_participation: Decimal | None = Decimal("0.1")
    max_open_orders: int = Field(default=40, ge=1, le=5000)
    max_stale_data_seconds: int = Field(default=0, ge=0)
    min_maintenance_margin_buffer: Decimal = Decimal("0.1")
    kill_switch_armed: bool = False
    kill_switch_cancels_open_orders: bool = True
    kill_switch_allows_risk_reduction: bool = True


class ExperimentSpec(LabModel):
    experiment_id: str = ""
    title: str = Field(min_length=1, max_length=200)
    objective: str = ""
    strategy_family: str
    dataset_ids: list[str] = Field(min_length=1, max_length=40)
    instruments: list[str] = Field(min_length=1, max_length=40)
    timeframe: str = "1h"
    split: SplitName = "development"
    search_method: Literal["single", "grid", "random", "sequential_refinement"] = "single"
    search_budget: int = Field(default=1, ge=1, le=2000)
    seed: int = Field(default=7, ge=0, le=2_147_483_647)
    param_space: dict[str, list[Any]] = Field(default_factory=dict)
    fixed_params: dict[str, Any] = Field(default_factory=dict)
    starting_cash: Decimal = Decimal("100000")
    base_currency: str = "USD"
    cost_model: CostModel = Field(default_factory=CostModel)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    evaluation_protocol: str = "walk_forward_expanding"
    requested_by: str = "operator"
    notes: str = ""

    def content_hash(self) -> str:
        return stable_hash(self.as_json())


# --- execution ------------------------------------------------------------------------


class OrderIntent(LabModel):
    """What a strategy or agent may ask for. It carries no guaranteed fill price."""

    intent_id: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType = "market"
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    trail_offset: Decimal | None = None
    take_profit_price: Decimal | None = None
    stop_loss_price: Decimal | None = None
    time_in_force: TimeInForce = "GTC"
    reduce_only: bool = False
    post_only: bool = False
    legs: list["OrderIntent"] = Field(default_factory=list, max_length=8)
    created_at_event_time: str = ""
    strategy_id: str | None = None
    strategy_version: int | None = None
    rationale: str = ""
    price_source: Literal["strategy_signal", "operator_input", "risk_reduction"] = "strategy_signal"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> "OrderIntent":
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.order_type in {"limit", "stop_limit", "take_profit"} and self.limit_price is None:
            raise ValueError(f"{self.order_type} requires limit_price")
        if self.order_type in {"stop_market", "stop_limit"} and self.stop_price is None:
            raise ValueError(f"{self.order_type} requires stop_price")
        if self.order_type == "trailing_stop" and (self.trail_offset is None or self.trail_offset <= 0):
            raise ValueError("trailing_stop requires a positive trail_offset")
        if self.order_type == "bracket" and self.take_profit_price is None and self.stop_loss_price is None:
            raise ValueError("bracket requires take_profit_price and/or stop_loss_price")
        if self.post_only and self.order_type not in {"limit", "take_profit"}:
            raise ValueError("post_only is only meaningful for resting limit orders")
        return self


class RiskDecision(LabModel):
    decision: Literal["allow", "allow_reduced", "block"]
    approved_quantity: Decimal = Decimal("0")
    reasons: list[str] = Field(default_factory=list)
    limit_snapshot: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: str = ""
    engine_version: str = "1"

    @property
    def allowed(self) -> bool:
        return self.decision != "block"


class OrderEvent(LabModel):
    event_id: str
    order_id: str
    instrument_id: str
    event_time: str
    kind: Literal[
        "accepted",
        "rejected",
        "working",
        "partially_filled",
        "filled",
        "cancelled",
        "expired",
        "triggered",
        "replaced",
        "liquidated",
    ]
    reason: str = ""
    remaining_quantity: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict)


class FillEvent(LabModel):
    event_id: str
    order_id: str
    instrument_id: str
    event_time: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    fee_currency: str = "USD"
    liquidity: Literal["taker", "maker", "settlement", "liquidation", "funding"] = "taker"
    intrabar_ambiguous: bool = False
    modelled_slippage_bps: Decimal = Decimal("0")
    observed_execution: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionSnapshot(LabModel):
    instrument_id: str
    side: PositionSide
    quantity: Decimal
    average_price: Decimal
    multiplier: Decimal = Decimal("1")
    mark_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    borrow_liability: Decimal = Decimal("0")
    opened_at: str = ""
    currency: str = "USD"


class PortfolioSnapshot(LabModel):
    as_of: str
    base_currency: str = "USD"
    cash: dict[str, Decimal] = Field(default_factory=dict)
    reserved_cash: dict[str, Decimal] = Field(default_factory=dict)
    positions: list[PositionSnapshot] = Field(default_factory=list)
    fees_paid: Decimal = Decimal("0")
    funding_paid: Decimal = Decimal("0")
    borrow_paid: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    gross_exposure: Decimal = Decimal("0")
    net_exposure: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    liabilities: Decimal = Decimal("0")
    valuation_source: str = "mark"
    stale_marks: list[str] = Field(default_factory=list)


# --- evaluation -----------------------------------------------------------------------


class PeriodMetrics(LabModel):
    label: str
    split: SplitName
    first_event_time: str | None = None
    last_event_time: str | None = None
    observations: int = 0
    trades: int = 0
    net_return: float = 0.0
    gross_return: float = 0.0
    costs_paid: float = 0.0
    annualised_return: float | None = None
    annualised_volatility: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float = 0.0
    drawdown_recovery_observations: int | None = None
    turnover: float = 0.0
    tail_loss_p05: float | None = None
    win_rate: float | None = None
    profit_concentration_top3: float | None = None
    benchmark_net_return: float | None = None
    benchmark_sharpe: float | None = None
    periods_per_year: float | None = None
    insufficient_evidence: bool = False


class StressResult(LabModel):
    scenario: str
    description: str
    net_return: float
    max_drawdown: float
    rejected_orders: int = 0
    note: str = ""


class EvaluationReport(LabModel):
    report_id: str
    strategy_id: str
    strategy_version: int
    evaluated_by: str
    evaluator_role: Literal["independent_validator", "automatic_gate"] = "independent_validator"
    protocol: str = "walk_forward_expanding"
    created_at: str = ""
    dataset_ids: list[str] = Field(default_factory=list)
    splits_used: list[SplitName] = Field(default_factory=list)
    folds: list[PeriodMetrics] = Field(default_factory=list)
    aggregate: PeriodMetrics | None = None
    benchmark: str = "buy_and_hold"
    search_trials_considered: int = 1
    deflated_sharpe: float | None = None
    multiple_testing_note: str = ""
    confidence_intervals: dict[str, list[float]] = Field(default_factory=dict)
    parameter_sensitivity: dict[str, float] = Field(default_factory=dict)
    stress: list[StressResult] = Field(default_factory=list)
    data_quality_note: str = ""
    simulator_limitations: list[str] = Field(default_factory=list)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    verdict: Literal["pass", "fail", "insufficient_evidence"] = "insufficient_evidence"
    verdict_reasons: list[str] = Field(default_factory=list)
    evidence_class: Literal[
        "code_present",
        "static_review",
        "executed_test",
        "historical_evaluation",
        "prospective_paper_evaluation",
    ] = "historical_evaluation"


class DecisionRecord(LabModel):
    """Structured decision summary. Never a private chain-of-thought transcript."""

    decision_id: str
    run_id: str
    event_time: str
    instrument_id: str
    strategy_id: str | None = None
    strategy_version: int | None = None
    model_version: str | None = None
    data_status: str = "complete"
    observed: dict[str, Any] = Field(default_factory=dict)
    in_scope: bool = True
    signal: str = "flat"
    signal_uncertainty: str = ""
    cost_assessment: str = ""
    action: Literal["execute", "wait", "reduce", "reject"] = "wait"
    action_reason: str = ""
    risk_decision: RiskDecision | None = None
    order_ids: list[str] = Field(default_factory=list)
    fill_event_ids: list[str] = Field(default_factory=list)
    deferred_evaluation_at: str | None = None
    later_outcome: dict[str, Any] | None = None


OrderIntent.model_rebuild()


__all__ = [
    "BondTerms",
    "CostModel",
    "DataLevel",
    "DataQualityIssue",
    "DataQualityReport",
    "DatasetManifest",
    "DecisionRecord",
    "EvaluationReport",
    "ExperimentSpec",
    "FillEvent",
    "FutureTerms",
    "InstrumentFamily",
    "InstrumentSpec",
    "LabModel",
    "MarketEvent",
    "MONEY_PLACES",
    "Observation",
    "OptionTerms",
    "OrderEvent",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "PeriodMetrics",
    "PortfolioSnapshot",
    "PositionSide",
    "PositionSnapshot",
    "RiskDecision",
    "RiskLimits",
    "RunMode",
    "SizingSpec",
    "SplitName",
    "StrategyHypothesis",
    "StrategySpec",
    "StressResult",
    "TimeInForce",
    "ViewRole",
    "quantize_money",
    "quantize_step",
    "stable_hash",
    "to_decimal",
    "utc_iso",
]
