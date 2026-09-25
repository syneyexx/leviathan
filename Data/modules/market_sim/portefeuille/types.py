"""Paper Portefeuille domain types — durable contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PortfolioStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


TERMINAL_PORTFOLIO_STATUSES = frozenset(
    {PortfolioStatus.STOPPED, PortfolioStatus.FAILED}
)
ACTIVE_PORTFOLIO_STATUSES = frozenset(
    {PortfolioStatus.RUNNING, PortfolioStatus.PAUSED}
)


@dataclass
class PaperPortfolio:
    portfolio_id: str
    name: str
    status: str = PortfolioStatus.CREATED.value
    mode: str = "PAPER"
    base_currency: str = "USD"
    broker_mode: str = "local_paper"
    provider_id: str = "binance_public"
    benchmark_symbol: str = "BTCUSDT"
    orchestra_id: str | None = None
    initial_equity: str = "100000"
    cash: str = "100000"
    reserved_cash: str = "0"
    realized_pnl: str = "0"
    unrealized_pnl: str = "0"
    fees_paid: str = "0"
    equity: str = "100000"
    peak_equity: str = "100000"
    margin_used: str = "0"
    gross_exposure: str = "0"
    net_exposure: str = "0"
    kill_switch: bool = False
    shorting_enabled: bool = False
    sod_equity: str | None = None
    sod_date: str | None = None
    last_mark_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["available_buying_power"] = str(
            max(0.0, float(self.cash) - float(self.reserved_cash))
        )
        d["truth"] = {
            "paper_only": True,
            "real_money": False,
            "mode": "PAPER",
            "not_historical_simulation": True,
            "not_live_broker": True,
        }
        return d


@dataclass
class PortfolioPosition:
    position_id: str
    portfolio_id: str
    symbol: str
    asset_class: str = "crypto"
    side: str = "LONG"  # LONG | SHORT
    qty: str = "0"
    avg_entry_price: str = "0"
    mark_price: str = "0"
    market_value: str = "0"
    cost_basis: str = "0"
    realized_pnl: str = "0"
    unrealized_pnl: str = "0"
    pnl_pct: str = "0"
    fees: str = "0"
    margin_used: str = "0"
    agent_id: str | None = None
    orchestra_id: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    opened_at: str = ""
    updated_at: str = ""
    status: str = "OPEN"  # OPEN | CLOSED
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioTransaction:
    transaction_id: str
    portfolio_id: str
    order_id: str | None = None
    fill_id: str | None = None
    decision_id: str | None = None
    symbol: str = ""
    side: str = ""  # BUY | SELL | SHORT | COVER
    qty: str = "0"
    price: str = "0"
    gross_notional: str = "0"
    fees: str = "0"
    net_cash_effect: str = "0"
    result: str = ""  # OPENED | CLOSED | REDUCED | COVERED | INCREASED
    agent_id: str | None = None
    orchestra_id: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    risk_result: dict[str, Any] = field(default_factory=dict)
    market_snapshot_id: str | None = None
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioOrder:
    order_id: str
    portfolio_id: str
    client_order_id: str
    symbol: str
    side: str
    qty: str
    status: str  # proposed | blocked | submitted | filled | cancelled | failed
    fill_price: str | None = None
    fee: str = "0"
    reject_reason: str = ""
    decision_id: str | None = None
    agent_id: str | None = None
    orchestra_id: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    risk_result: dict[str, Any] = field(default_factory=dict)
    submitted_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["truth"] = {"paper_only": True, "not_live_money": True}
        return d


@dataclass
class PortfolioSnapshot:
    snapshot_id: str
    portfolio_id: str
    timestamp: str
    equity: str
    cash: str
    realized_pnl: str = "0"
    unrealized_pnl: str = "0"
    gross_exposure: str = "0"
    net_exposure: str = "0"
    margin_used: str = "0"
    drawdown: str = "0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioAllocation:
    allocation_id: str
    portfolio_id: str
    kind: str  # agent | strategy | asset_class | reserve
    target_id: str
    target_allocation_pct: float
    allocated_budget: str = "0"
    current_attributed_equity: str = "0"
    active: bool = True
    strategy_version: int | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioRecommendation:
    recommendation_id: str
    portfolio_id: str
    type: str
    target: str
    reason: str
    current_value: str = ""
    target_value: str = ""
    impact: str = "MEDIUM"  # HIGH | MEDIUM | LOW
    estimated_orders: list[dict[str, Any]] = field(default_factory=list)
    status: str = "PENDING"  # PENDING | APPROVED | EXECUTED | DISMISSED | UNSUPPORTED
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradingDecision:
    """Structured agent/orchestra trading decision — never free-text orders."""

    decision_id: str
    portfolio_id: str
    orchestra_id: str | None
    agent_id: str | None
    strategy_id: str | None
    strategy_version: int | None
    symbol: str
    action: str  # BUY | SELL | SHORT | COVER | HOLD
    requested_qty: str | None = None
    requested_notional: str | None = None
    rationale_summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    market_snapshot_id: str | None = None
    confidence: float | None = None
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)
