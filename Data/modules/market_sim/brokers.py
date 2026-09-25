"""BrokerAdapter protocol — paper / replay / live (UNSUPPORTED) (T9 / G35)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .accounting import WalletLedger, money
from .paper_broker import PaperOrder, utc_now
from .types import MarketSimError


class BrokerAdapter(ABC):
    """Common broker surface for paper and replay paths. Live is never implemented."""

    broker_id: str
    supports_live: bool = False

    @abstractmethod
    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperOrder: ...

    @abstractmethod
    def reconcile(self, order: PaperOrder) -> PaperOrder: ...

    @abstractmethod
    def account(self, *, session_id: str | None = None) -> dict[str, Any]: ...


class LiveBroker(BrokerAdapter):
    """Honest UNSUPPORTED live broker — never places real-money orders (G35)."""

    broker_id = "live"
    supports_live = False

    def place(self, **_: Any) -> PaperOrder:
        raise MarketSimError(
            "UNSUPPORTED",
            "LiveBroker is UNSUPPORTED — real-money orders are blocked by construction",
            http_status=501,
        )

    def reconcile(self, order: PaperOrder) -> PaperOrder:
        raise MarketSimError(
            "UNSUPPORTED",
            "LiveBroker is UNSUPPORTED",
            http_status=501,
        )

    def account(self, *, session_id: str | None = None) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "status": "UNSUPPORTED",
            "truth": {
                "live_broker": "UNSUPPORTED",
                "no_real_money": True,
                "paper_only_paths_available": True,
            },
        }


class ReplayBroker(BrokerAdapter):
    """Deterministic replay fills from a recorded quote series (no network)."""

    broker_id = "replay"

    def __init__(
        self,
        quotes: list[dict[str, Any]] | None = None,
        *,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        initial_cash: float = 100_000.0,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._quotes = list(quotes or [])
        self._quote_i = 0
        self._orders: dict[str, PaperOrder] = {}
        self._by_client: dict[str, str] = {}
        self.sessions: dict[str, WalletLedger] = {}
        self._default_wallet = WalletLedger(
            wallet_id="wal-replay-default",
            owner_id="replay",
            owner_kind="paper",
            cash=money(initial_cash),
            currency="USD",
        )

    def wallet_for_session(self, session_id: str, *, initial_cash: float = 100_000.0) -> WalletLedger:
        if session_id not in self.sessions:
            self.sessions[session_id] = WalletLedger(
                wallet_id=f"wal-replay-{session_id[:8]}",
                owner_id=session_id,
                owner_kind="paper",
                cash=money(initial_cash),
                currency="USD",
            )
        return self.sessions[session_id]

    def next_quote(self) -> dict[str, Any] | None:
        if self._quote_i >= len(self._quotes):
            return None
        q = self._quotes[self._quote_i]
        self._quote_i += 1
        return q

    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperOrder:
        if client_order_id in self._by_client:
            return self._orders[self._by_client[client_order_id]]
        quote = self.next_quote()
        px = float((quote or {}).get("price") or price_hint or 0.0)
        now = utc_now()
        order = PaperOrder(
            order_id=str(uuid.uuid4()),
            client_order_id=client_order_id,
            symbol=symbol,
            side=side.upper(),
            qty=float(qty),
            status="submitted",
            submitted_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        if px <= 0:
            order.status = "rejected"
            order.reject_reason = "replay exhausted / no price"
            self._orders[order.order_id] = order
            self._by_client[client_order_id] = order.order_id
            return order
        wallet = (
            self.wallet_for_session(session_id)
            if session_id
            else self._default_wallet
        )
        slip = self.slippage_bps / 10_000.0
        fill_px = px * (1 + slip) if order.side == "BUY" else px * (1 - slip)
        fee = abs(qty * fill_px) * (self.fee_bps / 10_000.0)
        try:
            if order.side == "BUY":
                wallet.apply_buy(qty=qty, price=fill_px, fee=fee, tx_id=order.order_id)
            else:
                wallet.apply_sell(qty=qty, price=fill_px, fee=fee, tx_id=order.order_id)
            order.status = "filled"
            order.fill_price = fill_px
            order.fee = fee
            order.broker_order_id = f"replay-{order.order_id[:8]}"
        except ValueError as exc:
            order.status = "rejected"
            order.reject_reason = str(exc)
        order.updated_at = utc_now()
        self._orders[order.order_id] = order
        self._by_client[client_order_id] = order.order_id
        return order

    def reconcile(self, order: PaperOrder) -> PaperOrder:
        return self._orders.get(order.order_id, order)

    def account(self, *, session_id: str | None = None) -> dict[str, Any]:
        wallet = self.wallet_for_session(session_id) if session_id else self._default_wallet
        return {
            "broker_id": self.broker_id,
            "wallet": wallet.public_dict(),
            "truth": {"paper_only": True, "replay": True},
        }


def build_broker(broker_id: str, **kwargs: Any) -> BrokerAdapter | Any:
    """Factory for broker adapters. Live always returns LiveBroker (UNSUPPORTED)."""
    key = str(broker_id or "local_paper").lower()
    if key in {"live", "live_broker", "real"}:
        return LiveBroker()
    if key == "replay":
        return ReplayBroker(**{k: v for k, v in kwargs.items() if k in {"quotes", "fee_bps", "slippage_bps", "initial_cash"}})
    # Delegate paper paths to existing paper_broker factory.
    from .paper_broker import build_paper_broker

    return build_paper_broker(key, **kwargs)
