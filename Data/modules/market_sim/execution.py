"""Order intents + next-bar fill schedule (no same-close fill after deciding on that close)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .accounting import D, WalletLedger, money
from .types import FillStatus, OrderSide


def deterministic_id(*parts: Any) -> str:
    blob = "|".join(str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass
class OrderIntent:
    """Decision at bar T becomes eligible for fill at bar T+1 open (default)."""

    intent_id: str
    run_id: str
    agent_id: str
    wallet_id: str
    side: str  # BUY | SELL | HOLD
    qty: Decimal | None
    decision_bar_index: int
    decision_ts: str
    eligible_bar_index: int
    strategy_id: str | None = None
    strategy_version: int | None = None
    rationale: str = ""
    confidence: float = 0.0
    decision_scope: str = "individual"  # individual | shared
    status: str = "pending_eligibility"  # pending_eligibility | working | filled | rejected | cancelled
    metadata: dict[str, Any] = field(default_factory=dict)
    info_version: str = ""  # hash of frozen market snapshot at decision time

    def public_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "wallet_id": self.wallet_id,
            "side": self.side,
            "qty": None if self.qty is None else str(self.qty),
            "decision_bar_index": self.decision_bar_index,
            "decision_ts": self.decision_ts,
            "eligible_bar_index": self.eligible_bar_index,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "decision_scope": self.decision_scope,
            "status": self.status,
            "info_version": self.info_version,
            "metadata": self.metadata,
            "truth": {
                "fill_schedule": "next_bar_open",
                "same_bar_close_fill_forbidden": True,
            },
        }


@dataclass
class FillResult:
    filled: bool
    qty: Decimal
    price: Decimal
    fee: Decimal
    slippage: Decimal
    detail: str
    status: str = FillStatus.FILLED.value
    observed_execution: bool = False  # always False for sim fills

    def public_dict(self) -> dict[str, Any]:
        return {
            "filled": self.filled,
            "qty": str(self.qty),
            "price": str(self.price),
            "fee": str(self.fee),
            "slippage": str(self.slippage),
            "detail": self.detail,
            "status": self.status,
            "observed_execution": self.observed_execution,
        }


class NextBarFillModel:
    """Fill at next bar's open ± slippage. Decisions never fill on the same observed close."""

    ASSUMPTIONS = (
        "OHLCV only — not order-book realism",
        "Market orders fill at next bar open ± modelled slippage",
        "Partial fills when qty exceeds participation * bar volume",
        "observed_execution=False — costs are modelled, not measured",
    )

    def __init__(
        self,
        *,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        max_participation: float = 0.1,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.max_participation = max_participation

    def execute_intent(
        self,
        *,
        wallet: WalletLedger,
        intent: OrderIntent,
        fill_open: float,
        bar_volume: float,
        fill_bar_index: int,
    ) -> FillResult:
        if fill_bar_index < intent.eligible_bar_index:
            return FillResult(
                False, money(0), money(fill_open), money(0), money(0),
                "not yet eligible — causality guard",
                status=FillStatus.REJECTED.value,
            )
        if intent.side == OrderSide.HOLD.value or intent.qty is None or D(intent.qty) <= 0:
            intent.status = "cancelled"
            return FillResult(False, money(0), money(fill_open), money(0), money(0), "hold/no qty")

        qty = money(intent.qty)
        # Participation cap → partial fills
        if bar_volume > 0 and self.max_participation > 0:
            max_qty = money(D(bar_volume) * D(self.max_participation))
            if qty > max_qty and max_qty > 0:
                qty = max_qty

        slip_frac = D(self.slippage_bps) / D(10_000)
        open_px = money(fill_open)
        if intent.side == OrderSide.BUY.value:
            fill_price = money(open_px * (D(1) + slip_frac))
        else:
            fill_price = money(open_px * (D(1) - slip_frac))

        notional = money(qty * fill_price)
        fee = money(notional * D(self.fee_bps) / D(10_000))
        slip_cost = money(abs(fill_price - open_px) * qty)
        tx_id = deterministic_id(intent.intent_id, fill_bar_index, "fill")

        try:
            if intent.side == OrderSide.BUY.value:
                total = money(notional + fee)
                if total > wallet.cash + money("0.00000001"):
                    # Try partial to affordable
                    affordable = money(wallet.available_cash / (fill_price * (D(1) + D(self.fee_bps) / D(10_000))))
                    if affordable <= 0:
                        intent.status = "rejected"
                        return FillResult(
                            False, money(0), fill_price, money(0), money(0),
                            "insufficient cash", status=FillStatus.REJECTED.value,
                        )
                    qty = affordable
                    notional = money(qty * fill_price)
                    fee = money(notional * D(self.fee_bps) / D(10_000))
                    slip_cost = money(abs(fill_price - open_px) * qty)
                    wallet.apply_buy(qty=qty, price=fill_price, fee=fee, tx_id=tx_id)
                    intent.status = "filled"
                    status = FillStatus.PARTIAL.value if qty < money(intent.qty) else FillStatus.FILLED.value
                    return FillResult(True, qty, fill_price, fee, slip_cost, "filled buy", status=status)
                wallet.apply_buy(qty=qty, price=fill_price, fee=fee, tx_id=tx_id)
            else:
                if wallet.position_qty <= 0:
                    intent.status = "rejected"
                    return FillResult(
                        False, money(0), fill_price, money(0), money(0),
                        "no position", status=FillStatus.REJECTED.value,
                    )
                sell_qty = money(min(qty, wallet.position_qty))
                fee = money(sell_qty * fill_price * D(self.fee_bps) / D(10_000))
                slip_cost = money(abs(fill_price - open_px) * sell_qty)
                wallet.apply_sell(qty=sell_qty, price=fill_price, fee=fee, tx_id=tx_id)
                qty = sell_qty
            intent.status = "filled"
            status = (
                FillStatus.PARTIAL.value
                if intent.qty is not None and qty < money(intent.qty)
                else FillStatus.FILLED.value
            )
            detail = f"filled {intent.side.lower()} at next-bar open"
            return FillResult(True, qty, fill_price, fee, slip_cost, detail, status=status)
        except ValueError as exc:
            intent.status = "rejected"
            return FillResult(
                False, money(0), fill_price, money(0), money(0),
                str(exc), status=FillStatus.REJECTED.value,
            )


def make_intent(
    *,
    run_id: str,
    agent_id: str,
    wallet_id: str,
    side: str,
    qty: Any,
    decision_bar_index: int,
    decision_ts: str,
    info_version: str,
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    rationale: str = "",
    confidence: float = 0.0,
    decision_scope: str = "individual",
    metadata: dict[str, Any] | None = None,
) -> OrderIntent:
    intent_id = deterministic_id(
        run_id, agent_id, decision_bar_index, side, qty, info_version
    )
    return OrderIntent(
        intent_id=intent_id or str(uuid.uuid4()),
        run_id=run_id,
        agent_id=agent_id,
        wallet_id=wallet_id,
        side=side,
        qty=None if qty is None else money(qty),
        decision_bar_index=decision_bar_index,
        decision_ts=decision_ts,
        eligible_bar_index=decision_bar_index + 1,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        rationale=rationale,
        confidence=confidence,
        decision_scope=decision_scope,
        info_version=info_version,
        metadata=dict(metadata or {}),
    )
