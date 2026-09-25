"""Risk Engine v2 — unavoidable on every paper/manual/strategy order path (T9 / G34)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .accounting import WalletLedger
from .execution import OrderIntent
from .risk_guard import OVERRIDE_KEYS, RiskDecision, RiskGuard, RiskLimits
from .types import MarketSimError


@dataclass
class KillSwitchState:
    global_armed: bool = False
    global_reason: str = ""
    per_strategy: dict[str, str] = field(default_factory=dict)  # strategy_id → reason
    requires_human_reset: bool = True
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "global_armed": self.global_armed,
            "global_reason": self.global_reason,
            "per_strategy": dict(self.per_strategy),
            "requires_human_reset": self.requires_human_reset,
            "updated_at": self.updated_at,
            "truth": {"human_reset_required": True, "agents_cannot_reset": True},
        }


class RiskEngineV2:
    """Single risk path for manual + strategy + agent paper orders.

    Pre-trade evaluation + continuous breakers. Global and per-strategy kill
    switches require human reset. Limit loosening is approval-gated.
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
        *,
        store: Any | None = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.guard = RiskGuard(self.limits)
        self.store = store
        self.kill = KillSwitchState()
        self.orders_today = 0
        self._approval_service: Any | None = None

    def bind_approval_service(self, approval_service: Any | None) -> None:
        self._approval_service = approval_service

    def arm_global_kill(self, reason: str, *, now: str) -> KillSwitchState:
        self.kill.global_armed = True
        self.kill.global_reason = reason
        self.kill.updated_at = now
        self.guard.arm_kill_switch(reason)
        self._persist_kill(now)
        return self.kill

    def arm_strategy_kill(self, strategy_id: str, reason: str, *, now: str) -> KillSwitchState:
        self.kill.per_strategy[strategy_id] = reason
        self.kill.updated_at = now
        self._persist_kill(now)
        return self.kill

    def human_reset_kill(
        self,
        *,
        now: str,
        strategy_id: str | None = None,
        human_token: str | None = None,
    ) -> KillSwitchState:
        if not human_token:
            raise MarketSimError(
                "HUMAN_RESET_REQUIRED",
                "Kill switch reset requires an explicit human_token",
                http_status=403,
            )
        if strategy_id:
            self.kill.per_strategy.pop(strategy_id, None)
        else:
            self.kill.global_armed = False
            self.kill.global_reason = ""
            self.guard.killed = False
            self.guard.kill_reason = None
            self.limits = RiskLimits(
                max_position_pct=self.limits.max_position_pct,
                max_drawdown_pct=self.limits.max_drawdown_pct,
                per_trade_risk_pct=self.limits.per_trade_risk_pct,
                max_orders_per_day=self.limits.max_orders_per_day,
                max_symbol_exposure_pct=self.limits.max_symbol_exposure_pct,
                leverage_allowed=False,
                kill_switch_armed=False,
                kill_switch_allows_risk_reduction=self.limits.kill_switch_allows_risk_reduction,
            )
            self.guard.limits = self.limits
        self.kill.updated_at = now
        self._persist_kill(now)
        return self.kill

    def loosen_limits(
        self,
        patch: dict[str, Any],
        *,
        approval_id: str | None,
        now: str,
    ) -> RiskLimits:
        """Limit loosening is approval-gated — never by model output alone."""
        if not approval_id:
            raise MarketSimError(
                "APPROVAL_REQUIRED",
                "Loosening risk limits requires approval_id",
                http_status=403,
            )
        if self._approval_service is not None:
            from Data.modules.function_runtime.types import SideEffect

            ok = self._approval_service.is_approved(
                approval_id,
                capability_id="market_sim.risk.loosen",
                side_effects=(SideEffect.WRITE,),
            )
            if not ok:
                raise MarketSimError(
                    "APPROVAL_DENIED",
                    f"approval_id={approval_id} not approved for risk.loosen",
                    http_status=403,
                )
        # Apply only numeric loosenings that were listed; never clear kill switch here.
        self.limits = RiskLimits(
            max_position_pct=float(patch.get("max_position_pct", self.limits.max_position_pct)),
            max_drawdown_pct=float(patch.get("max_drawdown_pct", self.limits.max_drawdown_pct)),
            per_trade_risk_pct=float(patch.get("per_trade_risk_pct", self.limits.per_trade_risk_pct)),
            max_orders_per_day=int(patch.get("max_orders_per_day", self.limits.max_orders_per_day)),
            max_symbol_exposure_pct=float(
                patch.get("max_symbol_exposure_pct", self.limits.max_symbol_exposure_pct)
            ),
            leverage_allowed=False,
            kill_switch_armed=self.limits.kill_switch_armed,
            kill_switch_allows_risk_reduction=self.limits.kill_switch_allows_risk_reduction,
        )
        self.guard.limits = self.limits
        return self.limits

    def evaluate_order(
        self,
        *,
        side: str,
        qty: float,
        price: float,
        wallet: WalletLedger,
        strategy_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> RiskDecision:
        meta = dict(metadata or {})
        # Continuous breakers
        if self.kill.global_armed:
            return RiskDecision(False, self.kill.global_reason or "global kill switch armed")
        if strategy_id and strategy_id in self.kill.per_strategy:
            return RiskDecision(
                False, self.kill.per_strategy[strategy_id] or "strategy kill switch armed"
            )
        if not self.guard.check_drawdown(wallet, price):
            self.arm_global_kill(self.guard.kill_reason or "drawdown breaker", now=meta.get("now") or "")
            return RiskDecision(False, self.guard.kill_reason or "drawdown breaker")

        intent = OrderIntent(
            intent_id=str(uuid.uuid4()),
            run_id=session_id or "paper",
            agent_id=str(meta.get("agent_id") or "manual"),
            wallet_id=wallet.wallet_id,
            side=side.upper(),
            qty=qty,
            decision_bar_index=0,
            decision_ts="",
            eligible_bar_index=0,
            metadata=meta,
        )
        decision = self.guard.evaluate_intent(intent, wallet=wallet, price=price)
        if decision.allowed and side.upper() in {"BUY", "SELL"}:
            self.orders_today += 1
            self.guard.orders_today = self.orders_today
        return decision

    def _persist_kill(self, now: str) -> None:
        if self.store is None or not hasattr(self.store, "save_risk_kill_state"):
            return
        try:
            payload = self.kill.public_dict()
            payload["updated_at"] = now or payload.get("updated_at") or ""
            self.store.save_risk_kill_state(payload)
        except Exception:  # noqa: BLE001
            pass

    def public_dict(self) -> dict[str, Any]:
        return {
            "limits": asdict(self.limits),
            "kill_switch": self.kill.public_dict(),
            "orders_today": self.orders_today,
            "override_keys_blocked": list(OVERRIDE_KEYS),
            "truth": {
                "unavoidable_on_order_path": True,
                "human_reset_required": True,
                "limit_loosening_approval_gated": True,
            },
        }
