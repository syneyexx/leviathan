"""Paper broker adapters — local ledger + optional Alpaca paper (never live money)."""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .accounting import WalletBook, WalletLedger, money
from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PaperOrder:
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    qty: float
    status: str  # submitted | filled | rejected | cancelled | unknown
    broker_order_id: str | None = None
    fill_price: float | None = None
    fee: float = 0.0
    submitted_at: str = ""
    updated_at: str = ""
    reject_reason: str = ""
    strategy_id: str | None = None
    strategy_version: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "status": self.status,
            "fill_price": self.fill_price,
            "fee": self.fee,
            "submitted_at": self.submitted_at,
            "updated_at": self.updated_at,
            "reject_reason": self.reject_reason,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "metadata": self.metadata,
            "truth": {"paper_only": True, "not_live_money": True},
        }


@dataclass
class PaperSession:
    session_id: str
    mode: str  # live_paper
    provider_id: str
    broker_id: str
    symbol: str
    strategy_id: str | None
    strategy_version: int | None
    status: str  # active | paused | stopped | error
    kill_switch: bool = False
    feed_status: str = "unknown"
    feed_latency_ms: float | None = None
    last_quote: dict[str, Any] | None = None
    wallet: dict[str, Any] = field(default_factory=dict)
    orders: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "provider_id": self.provider_id,
            "broker_id": self.broker_id,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "status": self.status,
            "kill_switch": self.kill_switch,
            "feed_status": self.feed_status,
            "feed_latency_ms": self.feed_latency_ms,
            "last_quote": self.last_quote,
            "wallet": self.wallet,
            "orders": self.orders[-50:],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "truth": {
                "mode": "live_paper",
                "not_historical_backtest": True,
                "not_live_broker": True,
                "no_real_money": True,
            },
        }


class PaperBroker(ABC):
    broker_id: str

    @abstractmethod
    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperOrder: ...

    @abstractmethod
    def reconcile(self, order: PaperOrder) -> PaperOrder: ...

    @abstractmethod
    def account(self) -> dict[str, Any]: ...


class LocalPaperBroker(PaperBroker):
    """Local simulated fills against a live quote price — not exchange-matched."""

    broker_id = "local_paper"

    def __init__(self, *, fee_bps: float = 5.0, slippage_bps: float = 2.0) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._orders: dict[str, PaperOrder] = {}
        self.wallet = WalletLedger(
            wallet_id="wal-paper",
            owner_id="paper",
            owner_kind="paper",
            cash=money(100_000),
            currency="USD",
        )

    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperOrder:
        # Idempotent by client_order_id
        for existing in self._orders.values():
            if existing.client_order_id == client_order_id:
                return existing
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
        if price_hint is None or price_hint <= 0:
            order.status = "rejected"
            order.reject_reason = "no quote — refuse blind fill"
            order.updated_at = utc_now()
            self._orders[order.order_id] = order
            return order

        slip = self.slippage_bps / 10_000.0
        px = price_hint * (1 + slip) if order.side == "BUY" else price_hint * (1 - slip)
        fee = abs(qty * px) * (self.fee_bps / 10_000.0)
        try:
            if order.side == "BUY":
                self.wallet.apply_buy(
                    qty=qty, price=px, fee=fee, tx_id=order.order_id, meta={"symbol": symbol}
                )
            else:
                self.wallet.apply_sell(
                    qty=qty, price=px, fee=fee, tx_id=order.order_id, meta={"symbol": symbol}
                )
            order.status = "filled"
            order.fill_price = px
            order.fee = fee
            order.broker_order_id = f"local-{order.order_id[:8]}"
        except ValueError as exc:
            order.status = "rejected"
            order.reject_reason = str(exc)
        order.updated_at = utc_now()
        self._orders[order.order_id] = order
        return order

    def reconcile(self, order: PaperOrder) -> PaperOrder:
        current = self._orders.get(order.order_id, order)
        # Local broker has no unknown state after place
        if current.status == "submitted":
            current.status = "unknown"
            current.reject_reason = "incomplete local state — no blind resubmit"
            current.updated_at = utc_now()
        return current

    def account(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "wallet": self.wallet.public_dict(),
            "open_orders": [o.public_dict() for o in self._orders.values() if o.status == "submitted"],
            "truth": {"paper_only": True, "local_simulation": True},
        }


class AlpacaPaperBroker(PaperBroker):
    """Alpaca paper trading — only when paper credentials are configured.

    Live (real-money) Alpaca endpoints are never used here.
    """

    broker_id = "alpaca_paper"
    PAPER_BASE = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.key_id = os.environ.get("LEVIATHAN_ALPACA_PAPER_KEY_ID", "").strip()
        self.secret = os.environ.get("LEVIATHAN_ALPACA_PAPER_SECRET", "").strip()
        if not self.key_id or not self.secret:
            raise MarketSimError(
                "ALPACA_PAPER_NOT_CONFIGURED",
                "Set LEVIATHAN_ALPACA_PAPER_KEY_ID and LEVIATHAN_ALPACA_PAPER_SECRET",
                http_status=503,
            )
        self._orders: dict[str, PaperOrder] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
        }

    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperOrder:
        import json
        import urllib.request

        for existing in self._orders.values():
            if existing.client_order_id == client_order_id:
                return existing
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
        body = json.dumps(
            {
                "symbol": symbol.upper(),
                "qty": str(qty),
                "side": side.lower(),
                "type": "market",
                "time_in_force": "day",
                "client_order_id": client_order_id,
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.PAPER_BASE}/v2/orders",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
            order.broker_order_id = str(data.get("id") or "")
            order.status = str(data.get("status") or "submitted")
            if data.get("filled_avg_price"):
                order.fill_price = float(data["filled_avg_price"])
                order.status = "filled"
        except Exception as exc:  # noqa: BLE001
            order.status = "rejected"
            order.reject_reason = f"alpaca_paper error: {exc}"
        order.updated_at = utc_now()
        self._orders[order.order_id] = order
        return order

    def reconcile(self, order: PaperOrder) -> PaperOrder:
        import json
        import urllib.request

        if not order.broker_order_id:
            order.status = "unknown"
            order.reject_reason = "missing broker id — no blind resubmit"
            return order
        req = urllib.request.Request(
            f"{self.PAPER_BASE}/v2/orders/{order.broker_order_id}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
            order.status = str(data.get("status") or order.status)
            if data.get("filled_avg_price"):
                order.fill_price = float(data["filled_avg_price"])
            order.updated_at = utc_now()
        except Exception as exc:  # noqa: BLE001
            order.status = "unknown"
            order.reject_reason = f"reconcile failed: {exc}"
        return order

    def account(self) -> dict[str, Any]:
        import json
        import urllib.request

        req = urllib.request.Request(
            f"{self.PAPER_BASE}/v2/account",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
            return {
                "broker_id": self.broker_id,
                "equity": data.get("equity"),
                "cash": data.get("cash"),
                "status": data.get("status"),
                "truth": {"paper_only": True, "alpaca_paper": True, "not_live_money": True},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "broker_id": self.broker_id,
                "error": str(exc),
                "truth": {"paper_only": True},
            }


def build_paper_broker(broker_id: str = "local_paper") -> PaperBroker:
    if broker_id == "alpaca_paper":
        return AlpacaPaperBroker()
    if broker_id == "local_paper":
        return LocalPaperBroker()
    raise MarketSimError("PAPER_BROKER_UNKNOWN", broker_id, http_status=404)
