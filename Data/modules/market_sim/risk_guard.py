"""Deterministic risk guard — model output cannot override limits.

Wave 18 extends paper-trading safety kill controls. LLMs cannot bypass.
Rejection reasons are persisted on the decision object and, when a receipt
sink is bound, durably into the MARKET domain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .accounting import D, WalletLedger, money
from .execution import OrderIntent
from .instruments import InstrumentSpec, validate_intent_rules
from .short_margin import ShortMarginPolicy
from .sizing import SizingModel


OVERRIDE_KEYS = (
    "risk_override",
    "override_limits",
    "bypass_risk",
    "force",
    "force_execute",
    "ignore_limits",
    "approved_by_model",
    "simulate_human_auth",
    "llm_override",
    "model_override",
    "ai_approved",
)


class HealthState(str, Enum):
    """Fail-closed runtime health. UNKNOWN must never silently become HEALTHY."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, raw: Any, *, default: "HealthState | None" = None) -> "HealthState":
        if isinstance(raw, HealthState):
            return raw
        if raw is None:
            return default if default is not None else cls.UNKNOWN
        if isinstance(raw, bool):
            # Explicit booleans only — never treat missing as True.
            return cls.HEALTHY if raw else cls.UNHEALTHY
        text = str(raw).strip().upper()
        if not text:
            return default if default is not None else cls.UNKNOWN
        aliases = {
            "OK": cls.HEALTHY,
            "LIVE": cls.HEALTHY,
            "TRUE": cls.HEALTHY,
            "FALSE": cls.UNHEALTHY,
            "STALE": cls.UNHEALTHY,
            "GAP": cls.UNHEALTHY,
            "DISCONNECTED": cls.UNHEALTHY,
            "DOWN": cls.UNHEALTHY,
            "FAILED": cls.UNHEALTHY,
            "UNMEASURED": cls.UNKNOWN,
            "NONE": cls.UNKNOWN,
        }
        if text in aliases:
            return aliases[text]
        try:
            return cls(text)
        except ValueError:
            return default if default is not None else cls.UNKNOWN

    def allows_new_risk(self) -> bool:
        return self is HealthState.HEALTHY

    def is_known(self) -> bool:
        return self is not HealthState.UNKNOWN


@dataclass(frozen=True)
class RiskLimits:
    """Paper / research risk envelope. All kill controls are deterministic."""

    max_position_pct: float = 25.0
    max_drawdown_pct: float = 20.0
    per_trade_risk_pct: float = 1.0
    max_orders_per_day: int = 50
    max_symbol_exposure_pct: float = 40.0
    leverage_allowed: bool = False
    kill_switch_armed: bool = False
    kill_switch_allows_risk_reduction: bool = True
    # Wave 18 — paper trading safety envelope
    max_capital: float | None = None  # absolute cash/equity ceiling for paper book
    max_position_qty: float | None = None
    max_gross_exposure_pct: float = 200.0
    max_net_exposure_pct: float = 100.0
    max_leverage: float = 1.0
    max_order_notional: float | None = None
    max_daily_turnover: float | None = None  # absolute notional turned over per UTC day
    max_daily_loss_pct: float = 10.0
    stale_data_max_age_seconds: float | None = 120.0
    require_provider_healthy: bool = True
    require_model_healthy: bool = False  # paper may run without model health unless set
    require_broker_reconciled: bool = True
    global_paper_suspended: bool = False


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    sized_qty: float = 0.0
    blocked_keys: list[str] | None = None
    rejection_code: str | None = None
    persisted: bool = False
    receipt_id: str | None = None
    durable_persisted: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "sized_qty": self.sized_qty,
            "blocked_keys": self.blocked_keys or [],
            "rejection_code": self.rejection_code,
            "persisted": self.persisted,
            "receipt_id": self.receipt_id,
            "durable_persisted": self.durable_persisted,
            "truth": {
                "deterministic": True,
                "llm_cannot_bypass": True,
                "rejection_reason_persisted": self.persisted or (not self.allowed),
                "durable_receipt": self.durable_persisted,
                "in_memory_log_is_not_durable": not self.durable_persisted,
            },
        }


def _utc_day(ts: str | datetime | None) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        raw = str(ts).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            # date-only or bare date prefix
            if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
                return raw[:10]
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _copy_limits(limits: RiskLimits, **overrides: Any) -> RiskLimits:
    """Rebuild frozen RiskLimits preserving Wave-18 fields."""
    base = {
        "max_position_pct": limits.max_position_pct,
        "max_drawdown_pct": limits.max_drawdown_pct,
        "per_trade_risk_pct": limits.per_trade_risk_pct,
        "max_orders_per_day": limits.max_orders_per_day,
        "max_symbol_exposure_pct": limits.max_symbol_exposure_pct,
        "leverage_allowed": limits.leverage_allowed,
        "kill_switch_armed": limits.kill_switch_armed,
        "kill_switch_allows_risk_reduction": limits.kill_switch_allows_risk_reduction,
        "max_capital": limits.max_capital,
        "max_position_qty": limits.max_position_qty,
        "max_gross_exposure_pct": limits.max_gross_exposure_pct,
        "max_net_exposure_pct": limits.max_net_exposure_pct,
        "max_leverage": limits.max_leverage,
        "max_order_notional": limits.max_order_notional,
        "max_daily_turnover": limits.max_daily_turnover,
        "max_daily_loss_pct": limits.max_daily_loss_pct,
        "stale_data_max_age_seconds": limits.stale_data_max_age_seconds,
        "require_provider_healthy": limits.require_provider_healthy,
        "require_model_healthy": limits.require_model_healthy,
        "require_broker_reconciled": limits.require_broker_reconciled,
        "global_paper_suspended": limits.global_paper_suspended,
    }
    base.update(overrides)
    return RiskLimits(**base)


class RiskGuard:
    """Decisive veto layer outside agents. Override-looking keys are themselves blocks."""

    def __init__(
        self,
        limits: RiskLimits,
        *,
        sizing_model: SizingModel | None = None,
        instrument_spec: InstrumentSpec | None = None,
        short_margin_policy: ShortMarginPolicy | None = None,
        portfolio_shorting_enabled: bool | None = None,
        receipt_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.limits = limits
        self.killed = bool(limits.kill_switch_armed)
        self.kill_reason: str | None = "kill switch armed" if self.killed else None
        self.orders_today = 0
        self._current_utc_day: str | None = None
        self.daily_turnover = 0.0
        self.daily_realized_pnl = 0.0
        self.day_start_equity: float | None = None
        self.suspended_strategies: set[str] = set()
        self.global_paper_suspended = bool(limits.global_paper_suspended)
        self.rejection_log: list[dict[str, Any]] = []
        # Health — fail-closed: UNKNOWN until callers bind measured runtime state.
        self.data_age_seconds: float | None = None
        self.provider_health: HealthState = HealthState.UNKNOWN
        self.model_health: HealthState = HealthState.UNKNOWN
        self.broker_recon_health: HealthState = HealthState.UNKNOWN
        self.data_freshness_health: HealthState = HealthState.UNKNOWN
        self.model_degraded: bool = False
        self.gross_exposure_pct: float | None = None
        self.net_exposure_pct: float | None = None
        self.current_leverage: float | None = None
        self.sizing_model = sizing_model or SizingModel(
            kind="risk_pct",
            per_trade_risk_pct=limits.per_trade_risk_pct,
            max_position_pct=limits.max_position_pct,
        )
        self.instrument_spec = instrument_spec
        self.short_margin_policy = short_margin_policy
        self.portfolio_shorting_enabled = portfolio_shorting_enabled
        self._receipt_sink = receipt_sink
        self._last_receipt_context: dict[str, Any] = {}

    # Backward-compatible boolean views — True only when explicitly HEALTHY.
    @property
    def provider_healthy(self) -> bool:
        return self.provider_health is HealthState.HEALTHY

    @provider_healthy.setter
    def provider_healthy(self, value: bool) -> None:
        self.provider_health = HealthState.HEALTHY if value else HealthState.UNHEALTHY

    @property
    def model_healthy(self) -> bool:
        return self.model_health is HealthState.HEALTHY

    @model_healthy.setter
    def model_healthy(self, value: bool) -> None:
        self.model_health = HealthState.HEALTHY if value else HealthState.UNHEALTHY

    @property
    def broker_reconciled(self) -> bool:
        return self.broker_recon_health is HealthState.HEALTHY

    @broker_reconciled.setter
    def broker_reconciled(self, value: bool) -> None:
        self.broker_recon_health = HealthState.HEALTHY if value else HealthState.UNHEALTHY

    def on_bar_timestamp(self, ts: str | datetime | None) -> None:
        """Reset orders_today when the UTC calendar day changes."""
        day = _utc_day(ts)
        if day is None:
            return
        if self._current_utc_day is None:
            self._current_utc_day = day
            return
        if day != self._current_utc_day:
            self.orders_today = 0
            self.daily_turnover = 0.0
            self.daily_realized_pnl = 0.0
            self.day_start_equity = None
            self._current_utc_day = day

    # Alias used by some call sites / characterization
    roll_day = on_bar_timestamp

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "provider_health": self.provider_health.value,
            "model_health": self.model_health.value,
            "broker_recon_health": self.broker_recon_health.value,
            "data_freshness_health": self.data_freshness_health.value,
            "data_age_seconds": self.data_age_seconds,
            "model_degraded": self.model_degraded,
            "truth": {
                "unknown_is_not_healthy": True,
                "defaults_are_unknown": True,
            },
        }

    def _persist_rejection(self, decision: RiskDecision, *, context: dict[str, Any] | None = None) -> RiskDecision:
        if decision.allowed:
            return decision
        receipt_id = str(uuid.uuid4())
        merged_ctx = {**self._last_receipt_context, **(context or {})}
        entry = {
            "receipt_id": receipt_id,
            "reason": decision.reason,
            "rejection_code": decision.rejection_code or decision.reason,
            "blocked_keys": list(decision.blocked_keys or []),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "context": dict(merged_ctx),
            "health": self.health_snapshot(),
            "limits": {
                "max_drawdown_pct": self.limits.max_drawdown_pct,
                "max_daily_loss_pct": self.limits.max_daily_loss_pct,
                "max_orders_per_day": self.limits.max_orders_per_day,
                "max_gross_exposure_pct": self.limits.max_gross_exposure_pct,
                "max_net_exposure_pct": self.limits.max_net_exposure_pct,
                "max_leverage": self.limits.max_leverage,
                "stale_data_max_age_seconds": self.limits.stale_data_max_age_seconds,
                "require_provider_healthy": self.limits.require_provider_healthy,
                "require_model_healthy": self.limits.require_model_healthy,
                "require_broker_reconciled": self.limits.require_broker_reconciled,
            },
            "decision": "REJECT",
            "persistence_status": "IN_MEMORY",
        }
        self.rejection_log.append(entry)
        # Bound log size
        if len(self.rejection_log) > 500:
            self.rejection_log = self.rejection_log[-250:]
        decision.persisted = True
        decision.receipt_id = receipt_id
        if self._receipt_sink is not None:
            try:
                durable = dict(entry)
                durable["persistence_status"] = "DURABLE"
                self._receipt_sink(durable)
                entry["persistence_status"] = "DURABLE"
                decision.durable_persisted = True
            except Exception:  # noqa: BLE001 — never let receipt IO unblock risk veto
                entry["persistence_status"] = "DURABLE_WRITE_FAILED"
                decision.durable_persisted = False
        return decision

    def arm_kill_switch(self, reason: str) -> None:
        self.killed = True
        self.kill_reason = reason
        self.limits = _copy_limits(self.limits, kill_switch_armed=True, leverage_allowed=False)

    def clear_kill_switch(self, reason: str = "cleared") -> None:
        """Disarm kill switch. State must be explicit — never ambiguous.

        ``reason`` is accepted for audit call-sites; armed/clear flags are the
        authoritative state via ``kill_switch_state()``.
        """
        _ = reason
        self.killed = False
        self.kill_reason = None
        self.limits = _copy_limits(self.limits, kill_switch_armed=False)

    def kill_switch_state(self) -> dict[str, Any]:
        """Clear, unambiguous kill-switch status for callers / tests."""
        armed = bool(self.killed or self.limits.kill_switch_armed)
        return {
            "armed": armed,
            "clear": not armed,
            "reason": self.kill_reason,
            "allows_risk_reduction": bool(self.limits.kill_switch_allows_risk_reduction),
            "limits_kill_switch_armed": bool(self.limits.kill_switch_armed),
            "runtime_killed": bool(self.killed),
            "global_paper_suspended": bool(self.global_paper_suspended or self.limits.global_paper_suspended),
            "suspended_strategies": sorted(self.suspended_strategies),
        }

    def suspend_strategy(self, strategy_id: str, *, reason: str = "suspended") -> None:
        sid = str(strategy_id or "").strip()
        if sid:
            self.suspended_strategies.add(sid)
            self.rejection_log.append(
                {
                    "receipt_id": str(uuid.uuid4()),
                    "reason": f"strategy_suspended:{sid}:{reason}",
                    "rejection_code": "STRATEGY_SUSPENDED",
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "context": {"strategy_id": sid},
                    "health": self.health_snapshot(),
                    "persistence_status": "IN_MEMORY",
                }
            )

    def resume_strategy(self, strategy_id: str) -> None:
        self.suspended_strategies.discard(str(strategy_id or "").strip())

    def suspend_global_paper(self, reason: str = "global paper suspension") -> None:
        self.global_paper_suspended = True
        self.limits = _copy_limits(self.limits, global_paper_suspended=True)
        self.arm_kill_switch(reason)

    def resume_global_paper(self, reason: str = "global paper resumed") -> None:
        self.global_paper_suspended = False
        self.limits = _copy_limits(self.limits, global_paper_suspended=False)
        self.clear_kill_switch(reason)

    def set_receipt_context(self, **context: Any) -> None:
        """Attach lineage fields used when writing durable risk receipts."""
        cleaned = {k: v for k, v in context.items() if v is not None}
        self._last_receipt_context.update(cleaned)

    def update_health(
        self,
        *,
        data_age_seconds: float | None = None,
        provider_healthy: bool | None = None,
        provider_health: HealthState | str | None = None,
        model_healthy: bool | None = None,
        model_health: HealthState | str | None = None,
        model_degraded: bool | None = None,
        broker_reconciled: bool | None = None,
        broker_recon_health: HealthState | str | None = None,
        data_freshness_health: HealthState | str | None = None,
        gross_exposure_pct: float | None = None,
        net_exposure_pct: float | None = None,
        current_leverage: float | None = None,
    ) -> None:
        """Update external health inputs used by evaluate_intent kill controls.

        Explicit False/UNHEALTHY/UNKNOWN never become HEALTHY. Omitting a field
        leaves prior state unchanged (initial state is UNKNOWN).
        """
        if data_age_seconds is not None:
            self.data_age_seconds = float(data_age_seconds)
            max_age = self.limits.stale_data_max_age_seconds
            if max_age is None:
                self.data_freshness_health = HealthState.HEALTHY
            elif float(data_age_seconds) > float(max_age):
                self.data_freshness_health = HealthState.UNHEALTHY
            else:
                self.data_freshness_health = HealthState.HEALTHY
        if data_freshness_health is not None:
            self.data_freshness_health = HealthState.parse(data_freshness_health)
        if provider_health is not None:
            self.provider_health = HealthState.parse(provider_health)
        elif provider_healthy is not None:
            self.provider_health = HealthState.HEALTHY if provider_healthy else HealthState.UNHEALTHY
        if model_health is not None:
            self.model_health = HealthState.parse(model_health)
        elif model_healthy is not None:
            self.model_health = HealthState.HEALTHY if model_healthy else HealthState.UNHEALTHY
        if model_degraded is not None:
            self.model_degraded = bool(model_degraded)
            if self.model_degraded and self.model_health is HealthState.HEALTHY:
                self.model_health = HealthState.DEGRADED
        if broker_recon_health is not None:
            self.broker_recon_health = HealthState.parse(broker_recon_health)
        elif broker_reconciled is not None:
            self.broker_recon_health = (
                HealthState.HEALTHY if broker_reconciled else HealthState.UNHEALTHY
            )
        if gross_exposure_pct is not None:
            self.gross_exposure_pct = float(gross_exposure_pct)
        if net_exposure_pct is not None:
            self.net_exposure_pct = float(net_exposure_pct)
        if current_leverage is not None:
            self.current_leverage = float(current_leverage)

    def bind_measured_runtime_health(
        self,
        *,
        provider_ok: bool | None = None,
        provider_health: HealthState | str | None = None,
        broker_ok: bool | None = None,
        broker_recon_health: HealthState | str | None = None,
        model_ok: bool | None = None,
        model_health: HealthState | str | None = None,
        data_age_seconds: float | None = None,
        data_freshness_health: HealthState | str | None = None,
        gross_exposure_pct: float | None = None,
        net_exposure_pct: float | None = None,
        current_leverage: float | None = None,
    ) -> None:
        """Production binder — call from paper order paths with measured values.

        Passing no provider/broker/model value leaves that channel UNKNOWN (fail-closed).
        """
        self.update_health(
            provider_health=provider_health,
            provider_healthy=provider_ok,
            broker_recon_health=broker_recon_health,
            broker_reconciled=broker_ok,
            model_health=model_health,
            model_healthy=model_ok,
            data_age_seconds=data_age_seconds,
            data_freshness_health=data_freshness_health,
            gross_exposure_pct=gross_exposure_pct,
            net_exposure_pct=net_exposure_pct,
            current_leverage=current_leverage,
        )

    def record_fill_turnover(self, notional: float, *, realized_pnl: float = 0.0) -> None:
        self.daily_turnover += abs(float(notional))
        self.daily_realized_pnl += float(realized_pnl)

    def check_drawdown(self, wallet: WalletLedger, price: float) -> bool:
        dd = wallet.drawdown_pct(price)
        if dd >= self.limits.max_drawdown_pct:
            self.arm_kill_switch(f"Max drawdown kill-switch at {dd:.2f}%")
            return False
        return True

    def _reject(self, reason: str, *, code: str, blocked_keys: list[str] | None = None) -> RiskDecision:
        return self._persist_rejection(
            RiskDecision(False, reason, blocked_keys=blocked_keys, rejection_code=code)
        )

    def _paper_safety_gates(
        self,
        intent: OrderIntent,
        *,
        wallet: WalletLedger,
        price: float,
        reduces: bool,
    ) -> RiskDecision | None:
        """Wave 18 deterministic paper safety gates. Returns a rejection or None."""
        meta = intent.metadata or {}
        strategy_id = str(meta.get("strategy_id") or meta.get("strategyId") or "").strip()

        if self.global_paper_suspended or self.limits.global_paper_suspended:
            if reduces and self.limits.kill_switch_allows_risk_reduction:
                return None
            return self._reject(
                "global paper trading suspended",
                code="GLOBAL_PAPER_SUSPENDED",
            )

        if strategy_id and strategy_id in self.suspended_strategies:
            if reduces:
                return None
            return self._reject(
                f"strategy suspended: {strategy_id}",
                code="STRATEGY_SUSPENDED",
            )

        # Fail-closed health: UNKNOWN / DEGRADED / UNHEALTHY block new risk when required.
        if self.limits.require_provider_healthy and not reduces:
            if self.provider_health is HealthState.UNKNOWN:
                return self._reject(
                    "provider health UNKNOWN — new risk blocked",
                    code="PROVIDER_HEALTH_UNKNOWN",
                )
            if not self.provider_health.allows_new_risk():
                return self._reject("provider health stop", code="PROVIDER_HEALTH_STOP")

        if self.limits.require_model_healthy and not reduces:
            if self.model_health is HealthState.UNKNOWN:
                return self._reject(
                    "model health UNKNOWN — new risk blocked",
                    code="MODEL_HEALTH_UNKNOWN",
                )
            if not self.model_health.allows_new_risk() or self.model_degraded:
                return self._reject("model health degradation stop", code="MODEL_HEALTH_STOP")

        if self.limits.require_broker_reconciled and not reduces:
            if self.broker_recon_health is HealthState.UNKNOWN:
                return self._reject(
                    "broker reconciliation UNKNOWN — new risk blocked",
                    code="BROKER_RECONCILIATION_UNKNOWN",
                )
            if not self.broker_recon_health.allows_new_risk():
                return self._reject(
                    "broker reconciliation failure stop",
                    code="BROKER_RECONCILIATION_STOP",
                )

        max_age = self.limits.stale_data_max_age_seconds
        if max_age is not None and not reduces:
            if self.data_freshness_health is HealthState.UNKNOWN and self.data_age_seconds is None:
                return self._reject(
                    "market-data freshness UNKNOWN — new risk blocked",
                    code="DATA_FRESHNESS_UNKNOWN",
                )
            if self.data_freshness_health is HealthState.UNHEALTHY:
                return self._reject(
                    f"stale data stop: age={self.data_age_seconds}s > {max_age}s",
                    code="STALE_DATA_STOP",
                )
            if self.data_age_seconds is not None and float(self.data_age_seconds) > float(max_age):
                return self._reject(
                    f"stale data stop: age={self.data_age_seconds:.1f}s > {max_age}s",
                    code="STALE_DATA_STOP",
                )

        equity = float(wallet.equity(price))
        if self.day_start_equity is None and equity > 0:
            self.day_start_equity = equity
        if self.day_start_equity and self.day_start_equity > 0:
            daily_loss_pct = -100.0 * (equity - self.day_start_equity) / self.day_start_equity
            # Also incorporate realized pnl day tally when equity mark lags.
            if self.daily_realized_pnl < 0:
                daily_loss_pct = max(
                    daily_loss_pct,
                    -100.0 * self.daily_realized_pnl / self.day_start_equity,
                )
            if daily_loss_pct >= self.limits.max_daily_loss_pct and not reduces:
                self.arm_kill_switch(f"Daily loss kill-switch at {daily_loss_pct:.2f}%")
                return self._reject(
                    f"daily loss limit ({self.limits.max_daily_loss_pct}%) exceeded",
                    code="DAILY_LOSS_STOP",
                )

        if self.limits.max_capital is not None and equity > float(self.limits.max_capital) + 1e-6:
            if not reduces:
                return self._reject(
                    f"max capital ({self.limits.max_capital}) exceeded",
                    code="MAX_CAPITAL",
                )

        if self.limits.max_position_qty is not None:
            pos = abs(float(wallet.position_qty))
            if pos > float(self.limits.max_position_qty) + 1e-9 and not reduces:
                return self._reject(
                    f"max position qty ({self.limits.max_position_qty}) exceeded",
                    code="MAX_POSITION",
                )

        gross = self.gross_exposure_pct
        if gross is None and equity > 0:
            gross = 100.0 * abs(float(wallet.position_qty) * price) / equity
        if gross is not None and gross > float(self.limits.max_gross_exposure_pct) + 1e-6 and not reduces:
            return self._reject(
                f"max gross exposure ({self.limits.max_gross_exposure_pct}%) exceeded",
                code="MAX_GROSS_EXPOSURE",
            )

        net = self.net_exposure_pct
        if net is None and equity > 0:
            net = 100.0 * (float(wallet.position_qty) * price) / equity
        if net is not None and abs(net) > float(self.limits.max_net_exposure_pct) + 1e-6 and not reduces:
            return self._reject(
                f"max net exposure ({self.limits.max_net_exposure_pct}%) exceeded",
                code="MAX_NET_EXPOSURE",
            )

        lev = self.current_leverage
        if lev is None and equity > 0:
            lev = abs(float(wallet.position_qty) * price) / equity
        max_lev = float(self.limits.max_leverage)
        if not self.limits.leverage_allowed:
            max_lev = min(max_lev, 1.0)
        if lev is not None and lev > max_lev + 1e-6 and not reduces:
            return self._reject(
                f"max leverage ({max_lev}) exceeded",
                code="MAX_LEVERAGE",
            )

        if self.limits.max_daily_turnover is not None:
            if self.daily_turnover >= float(self.limits.max_daily_turnover) - 1e-9 and not reduces:
                return self._reject(
                    f"max daily turnover ({self.limits.max_daily_turnover}) reached",
                    code="MAX_DAILY_TURNOVER",
                )

        return None

    def evaluate_intent(
        self,
        intent: OrderIntent,
        *,
        wallet: WalletLedger,
        price: float,
    ) -> RiskDecision:
        meta = intent.metadata or {}
        self.set_receipt_context(
            portfolio_id=meta.get("portfolio_id") or getattr(wallet, "owner_id", None),
            strategy_id=meta.get("strategy_id") or getattr(intent, "strategy_id", None),
            agent_id=meta.get("agent_id") or getattr(intent, "agent_id", None),
            orchestra_id=meta.get("orchestra_id"),
            decision_id=meta.get("decision_id"),
            order_intent_id=getattr(intent, "intent_id", None),
            symbol=meta.get("symbol") or meta.get("instrument"),
            action=getattr(intent, "side", None),
            requested_qty=float(intent.qty) if intent.qty is not None else None,
            parent_trace_id=meta.get("parent_trace_id") or meta.get("trace_id"),
            root_trace_id=meta.get("root_trace_id"),
            source_decision=meta.get("source_decision") or meta.get("rationale"),
        )
        blocked = [k for k in OVERRIDE_KEYS if k in meta]
        if blocked:
            return self._reject(
                f"override_attempt_rejected:{','.join(sorted(blocked))}",
                code="LLM_OVERRIDE_REJECTED",
                blocked_keys=blocked,
            )

        if not self.limits.leverage_allowed and meta.get("leverage"):
            return self._reject("leverage disabled by default", code="LEVERAGE_DISABLED")

        reduces = (
            (intent.side == "SELL" and wallet.position_qty > 0)
            or (intent.side == "BUY" and wallet.position_qty < 0)
            or intent.side == "HOLD"
        )

        if self.killed or self.limits.kill_switch_armed:
            if reduces and self.limits.kill_switch_allows_risk_reduction:
                pass
            else:
                return self._reject(
                    self.kill_reason or "kill switch armed",
                    code="KILL_SWITCH",
                )

        safety = self._paper_safety_gates(intent, wallet=wallet, price=price, reduces=reduces)
        if safety is not None:
            return safety

        if self.orders_today >= self.limits.max_orders_per_day and intent.side in {"BUY", "SELL"}:
            return self._reject("max orders per day reached", code="MAX_ORDERS_PER_DAY")

        if intent.side == "HOLD":
            return RiskDecision(True, "hold", sized_qty=0.0)

        equity = float(wallet.equity(price))
        if price <= 0 or equity <= 0:
            return self._reject("invalid price/equity", code="INVALID_PRICE_EQUITY")

        requested = float(intent.qty) if intent.qty is not None else None
        opening_short = intent.side == "SELL" and float(wallet.position_qty) <= 0
        increasing_short = intent.side == "SELL" and float(wallet.position_qty) < 0

        if intent.side == "BUY":
            if float(wallet.position_qty) < 0:
                short_abs = abs(float(wallet.position_qty))
                target = requested if requested is not None else short_abs
                allow_rev = bool(
                    (intent.metadata or {}).get("allow_position_reversal")
                    or getattr(wallet, "allow_position_reversal", False)
                )
                if target > short_abs + 1e-12 and not allow_rev:
                    qty = short_abs
                    reason = "sized_cover_no_reversal"
                    if qty <= 0:
                        return self._reject("POSITION_REVERSAL_BLOCKED", code="POSITION_REVERSAL_BLOCKED")
                else:
                    qty = max(0.0, target)
                    reason = "sized_short_cover"
                if qty <= 0:
                    return self._reject("zero cover size", code="ZERO_SIZE")
            else:
                qty, reason = self.sizing_model.target_qty(
                    price=price,
                    equity=equity,
                    available_cash=float(wallet.available_cash),
                    requested_qty=requested,
                )
                if qty <= 0:
                    return self._reject("insufficient cash or size", code="INSUFFICIENT_SIZE")
                pos_after = float(wallet.position_qty) + qty
                max_sym = equity * (self.limits.max_symbol_exposure_pct / 100.0)
                if pos_after * price > max_sym + 1e-9:
                    qty = max(0.0, max_sym / price - float(wallet.position_qty))
                    if qty <= 0:
                        return self._reject("max symbol exposure", code="MAX_SYMBOL_EXPOSURE")
                    reason = "sized_symbol_cap"
        elif intent.side == "SELL":
            long_exit_only = float(wallet.position_qty) > 0 and not (
                requested is not None
                and requested > float(wallet.position_qty) + 1e-12
                and (
                    getattr(wallet, "shorting_enabled", False)
                    or self.portfolio_shorting_enabled is True
                    or self.short_margin_policy is not None
                )
            )
            if long_exit_only:
                target = requested if requested is not None else float(wallet.position_qty)
                qty = max(0.0, min(target, float(wallet.position_qty)))
                reason = "sized_long_exit"
                if qty <= 0:
                    return self._reject("zero sell size", code="ZERO_SIZE")
            else:
                if self.portfolio_shorting_enabled is False:
                    return self._reject("PORTFOLIO_SHORTING_DISABLED", code="PORTFOLIO_SHORTING_DISABLED")
                ok_short = True
                short_reason = "short_allowed"
                if self.instrument_spec is not None:
                    ok_short, short_reason, _ = validate_intent_rules(
                        spec=self.instrument_spec,
                        side=intent.side,
                        qty=requested or 0,
                        price=price,
                        opening_short=True,
                        short_margin_policy=self.short_margin_policy,
                    )
                else:
                    from .short_margin import short_open_allowed

                    ok_short, short_reason = short_open_allowed(
                        supports_short=bool(
                            getattr(wallet, "shorting_enabled", False)
                            or self.short_margin_policy is not None
                        ),
                        margin_policy=self.short_margin_policy,
                    )
                if not ok_short:
                    return self._reject(short_reason, code="SHORT_BLOCKED")
                if (
                    getattr(wallet, "short_margin_policy", None) is None
                    and self.short_margin_policy is not None
                ):
                    wallet.short_margin_policy = self.short_margin_policy
                if not getattr(wallet, "shorting_enabled", False):
                    wallet.shorting_enabled = True
                qty, reason = self.sizing_model.target_qty(
                    price=price,
                    equity=equity,
                    available_cash=float(wallet.available_cash),
                    requested_qty=requested,
                )
                if qty <= 0:
                    return self._reject("insufficient margin/size for short", code="INSUFFICIENT_MARGIN")
                policy = self.short_margin_policy or getattr(
                    wallet, "short_margin_policy", None
                )
                if policy is not None:
                    from .short_margin import ShortMarginPolicy

                    if isinstance(policy, dict):
                        policy = ShortMarginPolicy.from_dict(policy)
                    if policy is not None:
                        margin_need = (
                            qty * price * float(policy.initial_margin_pct) / 100.0
                        )
                        # Pre-proceeds available cash only — do not let short proceeds fund margin.
                        if float(wallet.available_cash) < margin_need - 1e-6:
                            return self._reject(
                                "MARGIN_BLOCK: insufficient for initial margin",
                                code="MARGIN_BLOCK",
                            )
                reason = f"short_{reason}"
        else:
            return self._reject(f"unknown side {intent.side}", code="UNKNOWN_SIDE")

        # Wave 18 — order notional + position qty caps after sizing
        if self.limits.max_order_notional is not None and qty > 0:
            notional = abs(qty * price)
            if notional > float(self.limits.max_order_notional) + 1e-9:
                capped = float(self.limits.max_order_notional) / price
                if capped <= 0:
                    return self._reject("max order notional exceeded", code="MAX_ORDER_NOTIONAL")
                qty = min(qty, capped)
                reason = f"{reason}_notional_cap"

        if self.limits.max_position_qty is not None and qty > 0 and intent.side == "BUY":
            room = float(self.limits.max_position_qty) - float(wallet.position_qty)
            if room <= 0:
                return self._reject("max position qty exceeded", code="MAX_POSITION")
            if qty > room:
                qty = room
                reason = f"{reason}_position_cap"

        if (
            self.limits.max_daily_turnover is not None
            and qty > 0
            and self.daily_turnover + abs(qty * price) > float(self.limits.max_daily_turnover) + 1e-9
        ):
            remaining = float(self.limits.max_daily_turnover) - self.daily_turnover
            if remaining <= 0:
                return self._reject("max daily turnover reached", code="MAX_DAILY_TURNOVER")
            qty = min(qty, remaining / price)
            reason = f"{reason}_turnover_cap"

        if self.instrument_spec is not None and qty > 0:
            ok, rule_reason, rounded = validate_intent_rules(
                spec=self.instrument_spec,
                side=intent.side,
                qty=qty,
                price=price,
                opening_short=(opening_short or increasing_short)
                and float(wallet.position_qty) <= 0,
                short_margin_policy=self.short_margin_policy,
            )
            if not ok:
                return self._reject(rule_reason, code="INSTRUMENT_RULE")
            qty = float(rounded)
            if qty <= 0:
                return self._reject("INSTRUMENT_RULE: qty rounds to zero", code="INSTRUMENT_RULE")

        return RiskDecision(True, reason, sized_qty=qty)

    def size_order(
        self,
        *,
        portfolio: Any,
        price: float,
        side: str,
        requested_qty: float | None,
        equity: float,
    ) -> RiskDecision:
        """Back-compat shim for legacy Portfolio path."""
        from .portfolio import Portfolio

        if isinstance(portfolio, Portfolio):
            wallet = WalletLedger(
                wallet_id="legacy",
                owner_id="legacy",
                owner_kind="shared",
                cash=money(portfolio.cash),
                position_qty=money(portfolio.position_qty),
                avg_entry=money(portfolio.avg_entry),
                realized_pnl=money(portfolio.realized_pnl),
                peak_equity=money(portfolio.peak_equity),
            )
        else:
            wallet = portfolio
        intent = OrderIntent(
            intent_id="tmp",
            run_id="tmp",
            agent_id="legacy",
            wallet_id=getattr(wallet, "wallet_id", "legacy"),
            side=side,
            qty=None if requested_qty is None else money(requested_qty),
            decision_bar_index=0,
            decision_ts="",
            eligible_bar_index=1,
        )
        return self.evaluate_intent(intent, wallet=wallet, price=price)

    def rejection_log_public(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rejection_log]
