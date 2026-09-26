"""W57 — Order lifecycle state machine (paper/sim only — live trading blocked)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .status import MeasurementState, DEFAULT_TRUTH


ORDER_STATES: tuple[str, ...] = (
    "CREATED",
    "RISK_CHECKED",
    "ACCEPTED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCEL_PENDING",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
)

ALLOWED_ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"RISK_CHECKED", "REJECTED", "CANCELLED"}),
    "RISK_CHECKED": frozenset({"ACCEPTED", "REJECTED", "CANCELLED"}),
    "ACCEPTED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "EXPIRED", "REJECTED"}),
    "PARTIALLY_FILLED": frozenset({"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "EXPIRED"}),
    "FILLED": frozenset(),
    "CANCEL_PENDING": frozenset({"CANCELLED", "FILLED", "PARTIALLY_FILLED"}),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset(),
}

TERMINAL_ORDER_STATES: frozenset[str] = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str
    qty: float
    order_type: str = "MARKET"
    state: str = "CREATED"
    filled_qty: float = 0.0
    mode: str = "PAPER"  # PAPER | SIM | LIVE
    history: list[dict[str, Any]] = field(default_factory=list)
    reject_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "orderId": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "orderType": self.order_type,
            "state": self.state,
            "filledQty": self.filled_qty,
            "mode": self.mode,
            "history": list(self.history),
            "rejectReason": self.reject_reason,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "live_mode_blocked": self.mode != "LIVE",
            },
        }


class OrderLifecycle:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def create(self, order: Order) -> Order:
        if order.mode.upper() == "LIVE":
            order.state = "REJECTED"
            order.reject_reason = "LIVE_TRADING_BLOCKED"
            order.history.append(
                {
                    "from": "CREATED",
                    "to": "REJECTED",
                    "ts": "",
                    "note": "LIVE_TRADING_BLOCKED",
                }
            )
        if order.order_id in self._orders:
            raise ValueError(f"order exists: {order.order_id}")
        self._orders[order.order_id] = order
        return order

    def transition(
        self,
        order_id: str,
        *,
        new_state: str,
        ts: str,
        note: str = "",
        fill_qty: float | None = None,
    ) -> Order:
        order = self._orders[order_id]
        if order.mode.upper() == "LIVE":
            raise PermissionError("LIVE_TRADING_BLOCKED")
        allowed = ALLOWED_ORDER_TRANSITIONS.get(order.state, frozenset())
        if new_state not in allowed:
            raise ValueError(f"illegal order transition {order.state} -> {new_state}")
        if fill_qty is not None:
            order.filled_qty = min(order.qty, order.filled_qty + float(fill_qty))
            if new_state == "PARTIALLY_FILLED" and order.filled_qty >= order.qty:
                new_state = "FILLED"
        order.history.append(
            {"from": order.state, "to": new_state, "ts": ts, "note": note, "filledQty": order.filled_qty}
        )
        order.state = new_state
        if new_state == "REJECTED" and note:
            order.reject_reason = note
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def public_dict(self) -> dict[str, Any]:
        return {
            "orders": [o.public_dict() for o in self._orders.values()],
            "count": len(self._orders),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_execution_paper_broker": True,
                "live_trading_blocked": True,
            },
        }


def order_from_mapping(raw: Mapping[str, Any]) -> Order:
    return Order(
        order_id=str(raw.get("order_id") or raw.get("orderId") or ""),
        symbol=str(raw.get("symbol") or "").upper(),
        side=str(raw.get("side") or "BUY").upper(),
        qty=float(raw.get("qty") or 0),
        order_type=str(raw.get("order_type") or raw.get("orderType") or "MARKET").upper(),
        state=str(raw.get("state") or "CREATED"),
        filled_qty=float(raw.get("filled_qty") or raw.get("filledQty") or 0),
        mode=str(raw.get("mode") or "PAPER").upper(),
    )
