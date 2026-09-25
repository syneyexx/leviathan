"""Market simulation domain types — control-plane contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MarketSimError(Exception):
    """Domain error with honest public payload."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "detail": self.message,
            "truth": {"no_fabricated_success": True},
        }


class CausalityViolation(MarketSimError):
    def __init__(self, message: str) -> None:
        super().__init__("CAUSALITY_VIOLATION", message, http_status=409)


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1D"


class DataKind(str, Enum):
    OHLCV = "ohlcv"
    TRADES = "trades"
    ORDERBOOK = "orderbook"


class SourceStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    PAPER_READY = "PAPER_READY"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STEPPING = "STEPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"


ACTIVE_RUN_STATUSES = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.STARTING,
        RunStatus.RUNNING,
        RunStatus.PAUSED,
        RunStatus.STEPPING,
    }
)

TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.STOPPED,
    }
)


class AgentRole(str, Enum):
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    EVENT_MACRO = "event_macro"
    RISK_OFFICER = "risk_officer"
    CRITIC = "critic"
    ALLOCATOR = "allocator"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class FillStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MetricStatus(str, Enum):
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class Bar:
    ts: str  # ISO-8601 UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketDataSource:
    source_id: str
    symbol: str
    timeframe: str
    kind: str
    path: str
    content_hash: str
    status: str
    bar_count: int = 0
    start_ts: str | None = None
    end_ts: str | None = None
    byte_size: int = 0
    validation_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "kind": self.kind,
            "path": self.path,
            "content_hash": self.content_hash,
            "status": self.status,
            "bar_count": self.bar_count,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "byte_size": self.byte_size,
            "validation_error": self.validation_error,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class StrategyRecord:
    strategy_id: str
    name: str
    description: str
    status: str
    tags: list[str] = field(default_factory=list)
    current_version: int = 1
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "tags": self.tags,
            "current_version": self.current_version,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class StrategyVersion:
    version_id: str
    strategy_id: str
    version: int
    content_hash: str
    parameters: dict[str, Any]
    entry_rules: dict[str, Any]
    exit_rules: dict[str, Any]
    risk_rules: dict[str, Any]
    required_timeframes: list[str]
    brain_dependencies: list[str]
    created_at: str
    changelog: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "strategy_id": self.strategy_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "parameters": self.parameters,
            "entry_rules": self.entry_rules,
            "exit_rules": self.exit_rules,
            "risk_rules": self.risk_rules,
            "required_timeframes": self.required_timeframes,
            "brain_dependencies": self.brain_dependencies,
            "created_at": self.created_at,
            "changelog": self.changelog,
            "metadata": self.metadata,
        }


@dataclass
class AgentConfig:
    agent_id: str
    role: str
    strategy_id: str | None = None
    strategy_version: int | None = None
    label: str = ""
    weight: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimRun:
    run_id: str
    status: str
    source_id: str
    strategy_id: str | None
    strategy_version: int | None
    symbol: str
    timeframe: str
    start_ts: str
    end_ts: str
    data_hash: str
    seed: int
    speed: float = 1.0
    initial_cash: float = 100_000.0
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    max_position_pct: float = 25.0
    max_drawdown_pct: float = 20.0
    per_trade_risk_pct: float = 1.0
    agents: list[dict[str, Any]] = field(default_factory=list)
    deliberation_every_n: int = 1
    clock_ts: str | None = None
    bar_index: int = 0
    bar_count: int = 0
    cash: float = 100_000.0
    equity: float = 100_000.0
    position_qty: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    causality_violations: int = 0
    brain_hits: int = 0
    brain_misses: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    worker_pid: int | None = None
    cancel_requested: bool = False
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "source_id": self.source_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "data_hash": self.data_hash,
            "seed": self.seed,
            "speed": self.speed,
            "initial_cash": self.initial_cash,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "max_position_pct": self.max_position_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "per_trade_risk_pct": self.per_trade_risk_pct,
            "agents": self.agents,
            "deliberation_every_n": self.deliberation_every_n,
            "clock_ts": self.clock_ts,
            "bar_index": self.bar_index,
            "bar_count": self.bar_count,
            "cash": self.cash,
            "equity": self.equity,
            "position_qty": self.position_qty,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "causality_violations": self.causality_violations,
            "brain_hits": self.brain_hits,
            "brain_misses": self.brain_misses,
            "metrics": self.metrics,
            "error": self.error,
            "worker_pid": self.worker_pid,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata": self.metadata,
            "truth": {
                "paper_sim_only": True,
                "no_real_broker_orders": True,
                "causality_enforced": True,
            },
        }


@dataclass
class SimFill:
    fill_id: str
    run_id: str
    bar_index: int
    ts: str
    side: str
    qty: float
    price: float
    fee: float
    slippage: float
    agent_id: str | None
    rationale: str
    status: str
    created_at: str
    # Ledger-derived closed-trade PnL attribution (G18 / D2). None = not attributed.
    realized_delta: float | None = None

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Always expose the key so metrics can detect ledger attribution;
        # None means "not attributed for this fill" (e.g. opening BUY).
        return payload


@dataclass
class DeliberationMessage:
    message_id: str
    run_id: str
    bar_index: int
    ts: str
    agent_id: str
    role: str
    kind: str  # proposal | challenge | veto | vote | decision | brain
    content: str
    proposal: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    brain_refs: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_AGENT_ROLES: tuple[AgentRole, ...] = (
    AgentRole.TREND,
    AgentRole.MEAN_REVERSION,
    AgentRole.RISK_OFFICER,
)
