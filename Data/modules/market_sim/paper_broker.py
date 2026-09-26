"""Paper broker adapters — local ledger + Alpaca paper via provider_io workers.

Alpaca remote HTTP never executes inside the Control Plane process. When
provider_io workers are unavailable, calls raise PROVIDER_EXECUTION_UNAVAILABLE.
"""

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


def paper_fill_key_for_event(*, session_id: str, event_id: str) -> str:
    """Stable client/fill key so feed replay cannot mint a second paper fill (T09)."""
    sid = str(session_id or "").strip() or "session"
    eid = str(event_id or "").strip() or "event"
    return f"fill:{sid}:{eid}"


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
    """Local simulated fills against a live quote price — not exchange-matched.

    P4A: per-session WalletLedger isolation (no shared cash across sessions).
    """

    broker_id = "local_paper"

    def __init__(self, *, fee_bps: float = 5.0, slippage_bps: float = 2.0) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._orders: dict[str, PaperOrder] = {}
        # Legacy default wallet retained for account() when no session bound.
        self.wallet = WalletLedger(
            wallet_id="wal-paper",
            owner_id="paper",
            owner_kind="paper",
            cash=money(100_000),
            currency="USD",
        )
        self.sessions: dict[str, WalletLedger] = {}

    def wallet_for_session(
        self,
        session_id: str,
        *,
        initial_cash: float = 100_000.0,
        create: bool = True,
    ) -> WalletLedger:
        sid = str(session_id)
        if sid in self.sessions:
            return self.sessions[sid]
        if not create:
            raise KeyError(sid)
        wal = WalletLedger(
            wallet_id=f"wal-paper-{sid[:8]}",
            owner_id=sid,
            owner_kind="paper_session",
            cash=money(initial_cash),
            currency="USD",
        )
        self.sessions[sid] = wal
        return wal

    def restore_session(
        self,
        session_id: str,
        *,
        wallet_payload: dict[str, Any] | None,
        orders: list[dict[str, Any]] | None = None,
    ) -> WalletLedger:
        """Hydrate in-memory wallet + order index from a durable paper session (W18).

        Idempotent: if the session wallet already exists, keep it. Restored orders
        re-seed client_order_id idempotency so reconnect/restart cannot double-fill.
        """
        sid = str(session_id)
        if sid not in self.sessions:
            if wallet_payload:
                wal = WalletLedger.from_public_dict(wallet_payload)
                wal.owner_id = sid
                wal.owner_kind = "paper_session"
                self.sessions[sid] = wal
            else:
                self.wallet_for_session(sid, create=True)
        for raw in orders or []:
            if not isinstance(raw, dict):
                continue
            cid = str(raw.get("client_order_id") or "").strip()
            oid = str(raw.get("order_id") or "").strip() or str(uuid.uuid4())
            meta = dict(raw.get("metadata") or {})
            fkey = str(meta.get("fill_key") or "").strip()
            if not cid and not fkey:
                continue
            # Skip if already indexed under this client id or fill_key.
            if cid and any(o.client_order_id == cid for o in self._orders.values()):
                continue
            if fkey and any(
                str(o.metadata.get("fill_key") or "") == fkey
                or o.client_order_id == fkey
                for o in self._orders.values()
            ):
                continue
            order = PaperOrder(
                order_id=oid,
                client_order_id=cid or fkey,
                symbol=str(raw.get("symbol") or ""),
                side=str(raw.get("side") or "BUY").upper(),
                qty=float(raw.get("qty") or 0),
                status=str(raw.get("status") or "filled"),
                broker_order_id=raw.get("broker_order_id"),
                fill_price=float(raw["fill_price"]) if raw.get("fill_price") is not None else None,
                fee=float(raw.get("fee") or 0),
                submitted_at=str(raw.get("submitted_at") or ""),
                updated_at=str(raw.get("updated_at") or ""),
                reject_reason=str(raw.get("reject_reason") or ""),
                strategy_id=raw.get("strategy_id"),
                strategy_version=raw.get("strategy_version"),
                metadata=meta,
            )
            self._orders[order.order_id] = order
        return self.sessions[sid]

    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        price_hint: float | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        fill_key: str | None = None,
    ) -> PaperOrder:
        meta = dict(metadata or {})
        key = (fill_key or meta.get("fill_key") or "").strip() or None
        if key:
            meta["fill_key"] = key
        # Idempotent by client_order_id OR durable fill_key (feed event identity).
        for existing in self._orders.values():
            if existing.client_order_id == client_order_id:
                return existing
            if key and (
                existing.client_order_id == key
                or str(existing.metadata.get("fill_key") or "") == key
            ):
                return existing
        sid = session_id or meta.get("session_id")
        wallet = self.wallet_for_session(str(sid), create=True) if sid else self.wallet
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
            metadata=meta,
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
        # Prefer stable fill_key as ledger tx_id so replay cannot double-post cash.
        tx_id = key or order.order_id
        try:
            if order.side == "BUY":
                wallet.apply_buy(
                    qty=qty, price=px, fee=fee, tx_id=tx_id, meta={"symbol": symbol}
                )
            else:
                wallet.apply_sell(
                    qty=qty, price=px, fee=fee, tx_id=tx_id, meta={"symbol": symbol}
                )
            order.status = "filled"
            order.fill_price = px
            order.fee = fee
            order.broker_order_id = f"local-{order.order_id[:8]}"
        except ValueError as exc:
            # Duplicate tx_id after hydrate/replay → treat as idempotent success if known.
            if key and "duplicate tx_id" in str(exc).lower():
                for existing in self._orders.values():
                    if str(existing.metadata.get("fill_key") or "") == key:
                        return existing
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

    def account(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id and session_id in self.sessions:
            wallet = self.sessions[session_id]
        else:
            wallet = self.wallet
        return {
            "broker_id": self.broker_id,
            "wallet": wallet.public_dict(),
            "open_orders": [o.public_dict() for o in self._orders.values() if o.status == "submitted"],
            "session_count": len(self.sessions),
            "truth": {
                "paper_only": True,
                "local_simulation": True,
                "isolated_session_wallets": True,
            },
        }


class AlpacaPaperBroker(PaperBroker):
    """Alpaca paper trading via provider_io — never live money, never Control Plane HTTP.

    Live (real-money) Alpaca endpoints are never used here.
    """

    broker_id = "alpaca_paper"

    def __init__(self, job_runtime: Any | None = None) -> None:
        self.key_id = os.environ.get("LEVIATHAN_ALPACA_PAPER_KEY_ID", "").strip()
        self.secret = os.environ.get("LEVIATHAN_ALPACA_PAPER_SECRET", "").strip()
        if not self.key_id or not self.secret:
            raise MarketSimError(
                "ALPACA_PAPER_NOT_CONFIGURED",
                "Set LEVIATHAN_ALPACA_PAPER_KEY_ID and LEVIATHAN_ALPACA_PAPER_SECRET",
                http_status=503,
            )
        self.job_runtime = job_runtime
        self._orders: dict[str, PaperOrder] = {}

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def _require_provider_io(self) -> Any:
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready

        if self.job_runtime is None:
            raise MarketSimError(
                ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                "Alpaca paper requires provider_io job runtime; Control Plane will not call Alpaca.",
                http_status=503,
            )
        db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
        if not provider_io_workers_ready(db_path):
            raise MarketSimError(
                ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                "provider_io workers unavailable; refusing Alpaca Control Plane fallback",
                http_status=503,
            )
        return ProviderExecutionClient(self.job_runtime)

    def _exec(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode

        client = self._require_provider_io()
        try:
            result = client.submit_and_wait(
                provider="alpaca_paper",
                capability="alpaca.paper",
                payload={"action": action, **payload},
                credential_ref="alpaca_paper",
                latency_class="interactive",
                requested_by="alpaca_paper_broker",
                deadline_seconds=30.0,
            )
        except ProviderError as exc:
            if exc.code == ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE:
                raise MarketSimError(exc.code.value, str(exc), http_status=503) from exc
            raise MarketSimError(
                exc.code.value,
                str(exc),
                http_status=503 if exc.retryable else 502,
            ) from exc
        if result.status != "succeeded" or not isinstance(result.structured, dict):
            err = (result.error or {}).get("message") or "alpaca provider_io failed"
            code = (result.error or {}).get("code") or "PROVIDER_UNAVAILABLE"
            raise MarketSimError(str(code), str(err), http_status=502)
        return dict(result.structured)

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
        del price_hint  # market orders — price hint unused
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
        try:
            data = self._exec(
                "place",
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "client_order_id": client_order_id,
                },
            )
            order.broker_order_id = str(data.get("id") or "")
            order.status = str(data.get("status") or "submitted")
            if data.get("filled_avg_price"):
                order.fill_price = float(data["filled_avg_price"])
                order.status = "filled"
            order.metadata["executed_via"] = "provider_io"
            order.metadata["worker_pid"] = None
        except MarketSimError as exc:
            if exc.code == "PROVIDER_EXECUTION_UNAVAILABLE":
                raise
            order.status = "rejected"
            order.reject_reason = f"alpaca_paper error: {exc}"
        order.updated_at = utc_now()
        self._orders[order.order_id] = order
        return order

    def reconcile(self, order: PaperOrder) -> PaperOrder:
        if not order.broker_order_id:
            order.status = "unknown"
            order.reject_reason = "missing broker id — no blind resubmit"
            return order
        try:
            data = self._exec("reconcile", {"broker_order_id": order.broker_order_id})
            order.status = str(data.get("status") or order.status)
            if data.get("filled_avg_price"):
                order.fill_price = float(data["filled_avg_price"])
            order.updated_at = utc_now()
            order.metadata["executed_via"] = "provider_io"
        except MarketSimError as exc:
            if exc.code == "PROVIDER_EXECUTION_UNAVAILABLE":
                raise
            order.status = "unknown"
            order.reject_reason = f"reconcile failed: {exc}"
        return order

    def account(self) -> dict[str, Any]:
        data = self._exec("account", {})
        return {
            "broker_id": self.broker_id,
            "equity": data.get("equity"),
            "cash": data.get("cash"),
            "status": data.get("status"),
            "truth": {
                "paper_only": True,
                "alpaca_paper": True,
                "not_live_money": True,
                "executed_via": "provider_io",
            },
        }


def build_paper_broker(
    broker_id: str = "local_paper",
    *,
    job_runtime: Any | None = None,
) -> PaperBroker:
    if broker_id == "alpaca_paper":
        return AlpacaPaperBroker(job_runtime=job_runtime)
    if broker_id == "local_paper":
        return LocalPaperBroker()
    raise MarketSimError("PAPER_BROKER_UNKNOWN", broker_id, http_status=404)


def apply_paper_fill_from_feed_event(
    broker: LocalPaperBroker,
    *,
    session_id: str,
    event_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    metadata: dict[str, Any] | None = None,
) -> PaperOrder:
    """Place a paper fill keyed by feed event_id — safe under reconnect replay (T09)."""
    fill_key = paper_fill_key_for_event(session_id=session_id, event_id=event_id)
    meta = dict(metadata or {})
    meta["fill_key"] = fill_key
    meta["event_id"] = event_id
    meta["session_id"] = session_id
    return broker.place(
        symbol=symbol,
        side=side,
        qty=qty,
        client_order_id=fill_key,
        price_hint=price,
        session_id=session_id,
        fill_key=fill_key,
        metadata=meta,
    )
