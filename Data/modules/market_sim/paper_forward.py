"""PaperForwardRunner — autonomous paper loop (P4A / G32).

Paper-only. Uses canonical RiskGuard + per-session WalletLedger.
Never touches live money. Long loops are EXTERNAL_REQUIRED on market_sim worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .accounting import WalletLedger, money
from .execution import OrderIntent, OrderSide, OrderType, TimeInForce
from .risk_guard import RiskGuard, RiskLimits
from .store import utc_now
from .types import MarketSimError


@dataclass
class PaperForwardState:
    session_id: str
    symbol: str
    status: str = "CREATED"  # CREATED | RUNNING | PAUSED | COMPLETED | FAILED | KILLED
    steps: int = 0
    max_steps: int = 100
    checkpoint_step: int = 0
    last_decision: dict[str, Any] = field(default_factory=dict)
    last_risk: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "status": self.status,
            "steps": self.steps,
            "max_steps": self.max_steps,
            "checkpoint_step": self.checkpoint_step,
            "last_decision": dict(self.last_decision),
            "last_risk": dict(self.last_risk),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "paper_only": True,
                "live_money": "BLOCKED",
                "canonical_risk_guard": True,
                "isolated_session_wallet": True,
                "resumable": True,
            },
        }


class PaperForwardRunner:
    """Step a paper session with RiskGuard + strategy signal (no live routing)."""

    def __init__(
        self,
        *,
        risk: RiskGuard | None = None,
        limits: RiskLimits | None = None,
    ) -> None:
        self.risk = risk or RiskGuard(limits or RiskLimits())
        self.limits = limits or self.risk.limits

    def step(
        self,
        *,
        wallet: WalletLedger,
        symbol: str,
        price: float,
        side: str,
        qty: float | None = None,
        bar_index: int = 0,
        rationale: str = "paper_forward",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if price <= 0:
            raise MarketSimError("FEED_UNCERTAIN", "paper forward refuses blind fill", http_status=409)
        side_u = str(side or "HOLD").upper()
        if side_u in {"HOLD", "FLAT", "NONE", ""}:
            return {
                "allowed": True,
                "action": "hold",
                "reason": "hold",
                "order": None,
                "risk": {"allowed": True, "reason": "hold"},
            }
        intent = OrderIntent(
            intent_id=str(uuid.uuid4()),
            run_id="paper-forward",
            agent_id="paper_forward",
            wallet_id=wallet.wallet_id,
            side=OrderSide.BUY.value if side_u == "BUY" else OrderSide.SELL.value,
            qty=money(qty) if qty is not None else None,
            decision_bar_index=bar_index,
            decision_ts=utc_now(),
            eligible_bar_index=bar_index,
            rationale=rationale,
            order_type=OrderType.MARKET.value,
            time_in_force=TimeInForce.BAR.value,
            metadata=dict(metadata or {}),
        )
        decision = self.risk.evaluate_intent(intent, wallet=wallet, price=price)
        if not decision.allowed or decision.sized_qty <= 0:
            return {
                "allowed": False,
                "action": "blocked",
                "reason": decision.reason,
                "order": None,
                "risk": decision.public_dict(),
            }
        return {
            "allowed": True,
            "action": "order",
            "reason": decision.reason,
            "side": intent.side,
            "qty": float(decision.sized_qty),
            "price": float(price),
            "order": intent.public_dict() if hasattr(intent, "public_dict") else {
                "side": intent.side,
                "qty": float(decision.sized_qty),
            },
            "risk": decision.public_dict(),
        }


def new_paper_forward_state(
    *,
    session_id: str,
    symbol: str,
    max_steps: int = 100,
    metadata: dict[str, Any] | None = None,
) -> PaperForwardState:
    now = utc_now()
    return PaperForwardState(
        session_id=session_id,
        symbol=symbol.upper(),
        max_steps=max(1, int(max_steps)),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
