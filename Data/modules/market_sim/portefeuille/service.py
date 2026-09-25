"""Paper Portefeuille control-plane operations — durable multi-asset paper capital."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from ..accounting import D, ZERO, money
from ..paper_broker import utc_now
from ..types import MarketSimError
from .assets import asset_registry
from .intelligence import generate_insights
from .ledger import PortfolioBook
from .metrics import (
    allocation_breakdown,
    downsample_snapshots,
    exposure_summary,
    health_score,
    performance_from_snapshots,
    stress_level,
)
from .recommendations import generate_recommendations, preview_rebalance
from .risk import evaluate_portfolio_order
from .types import PortfolioStatus


class PortfolioService:
    """Owns Portefeuille lifecycle, accounting, dashboard read model."""

    def __init__(self, store: Any, *, providers: Any = None, plane: Any = None) -> None:
        self.store = store
        self.providers = providers
        self.plane = plane
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._books: dict[str, PortfolioBook] = {}

    def _lock(self, portfolio_id: str) -> threading.RLock:
        with self._locks_guard:
            if portfolio_id not in self._locks:
                self._locks[portfolio_id] = threading.RLock()
            return self._locks[portfolio_id]

    def _default_settings(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        base = {
            "fee_bps": 5.0,
            "slippage_bps": 2.0,
            "shorting_enabled": False,
            "max_leverage": 1.0,
            "max_position_pct": 25.0,
            "max_gross_exposure_pct": 200.0,
            "max_net_exposure_pct": 150.0,
            "cash_reserve_pct": 10.0,
            "max_drawdown_pct": 20.0,
            "daily_loss_limit_pct": 10.0,
            "strategy_allocation_ceiling_pct": 40.0,
            "agent_allocation_ceiling_pct": 40.0,
            "asset_concentration_pct": 40.0,
            "max_symbol_exposure_pct": 40.0,
            "max_orders_per_day": 50,
            "per_trade_risk_pct": 1.0,
            "initial_margin_pct": 50.0,
            "min_order_notional": 10.0,
            "max_order_notional": 1_000_000.0,
            "max_concurrent_positions": 20,
            "decision_cadence_seconds": 60,
            "mark_refresh_seconds": 5,
            "benchmark_symbol": "BTCUSDT",
        }
        if overrides:
            base.update(overrides)
        return base

    # --- CRUD ---

    def create_portfolio(
        self,
        *,
        name: str,
        initial_equity: float = 100_000.0,
        base_currency: str = "USD",
        broker_mode: str = "local_paper",
        provider_id: str = "binance_public",
        benchmark_symbol: str = "BTCUSDT",
        orchestra_id: str | None = None,
        shorting_enabled: bool = False,
        settings: dict[str, Any] | None = None,
        agent_allocations: list[dict[str, Any]] | None = None,
        strategy_allocations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if initial_equity <= 0:
            raise MarketSimError("INVALID_CAPITAL", "Initial paper capital must be positive")
        if broker_mode in ("live", "live_broker"):
            raise MarketSimError(
                "LIVE_MONEY_BLOCKED",
                "Portefeuille is paper-only — live broker mode is blocked",
                http_status=403,
            )
        pid = str(uuid.uuid4())
        now = utc_now()
        cfg = self._default_settings(settings)
        cfg["shorting_enabled"] = bool(shorting_enabled or cfg.get("shorting_enabled"))
        cfg["benchmark_symbol"] = benchmark_symbol or cfg.get("benchmark_symbol")
        day = datetime.now(timezone.utc).date().isoformat()
        row = {
            "portfolio_id": pid,
            "name": name.strip() or "Paper Portefeuille",
            "status": PortfolioStatus.CREATED.value,
            "mode": "PAPER",
            "base_currency": base_currency,
            "broker_mode": broker_mode if broker_mode != "live" else "local_paper",
            "provider_id": provider_id,
            "benchmark_symbol": cfg["benchmark_symbol"],
            "orchestra_id": orchestra_id,
            "initial_equity": str(money(initial_equity)),
            "cash": str(money(initial_equity)),
            "reserved_cash": "0",
            "realized_pnl": "0",
            "unrealized_pnl": "0",
            "fees_paid": "0",
            "equity": str(money(initial_equity)),
            "peak_equity": str(money(initial_equity)),
            "margin_used": "0",
            "gross_exposure": "0",
            "net_exposure": "0",
            "kill_switch": False,
            "shorting_enabled": bool(cfg["shorting_enabled"]),
            "sod_equity": str(money(initial_equity)),
            "sod_date": day,
            "last_mark_at": now,
            "created_at": now,
            "updated_at": now,
            "settings": cfg,
            "metadata": {
                "truth": {"paper_only": True, "real_money": False},
                "settings_snapshot": dict(cfg),
            },
            "book_json": {},
        }
        book = PortfolioBook(
            portfolio_id=pid,
            cash=money(initial_equity),
            shorting_enabled=bool(cfg["shorting_enabled"]),
            initial_margin_pct=D(cfg.get("initial_margin_pct", 50)),
        )
        row["book_json"] = book.serialize()
        self.store.upsert_portfolio(row)
        self._books[pid] = book
        self.store.insert_portfolio_snapshot(
            {
                "snapshot_id": str(uuid.uuid4()),
                "portfolio_id": pid,
                "timestamp": now,
                "equity": row["equity"],
                "cash": row["cash"],
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "gross_exposure": "0",
                "net_exposure": "0",
                "margin_used": "0",
                "drawdown": "0",
                "metadata": {"reason": "created"},
            }
        )
        # Allocations
        for a in agent_allocations or []:
            self._save_allocation(pid, "agent", a)
        for a in strategy_allocations or []:
            self._save_allocation(pid, "strategy", a)
        # Reserve bucket
        reserve_pct = float(cfg.get("cash_reserve_pct", 10.0))
        self._save_allocation(
            pid,
            "reserve",
            {"target_id": "CASH_RESERVE", "target_allocation_pct": reserve_pct},
        )
        return self.get_portfolio(pid)

    def _save_allocation(self, portfolio_id: str, kind: str, raw: dict[str, Any]) -> dict[str, Any]:
        row = {
            "allocation_id": str(raw.get("allocation_id") or uuid.uuid4()),
            "portfolio_id": portfolio_id,
            "kind": kind,
            "target_id": str(raw.get("target_id") or raw.get("agent_id") or raw.get("strategy_id") or ""),
            "target_allocation_pct": float(raw.get("target_allocation_pct") or raw.get("allocation_pct") or 0),
            "allocated_budget": str(raw.get("allocated_budget") or "0"),
            "current_attributed_equity": str(raw.get("current_attributed_equity") or "0"),
            "active": bool(raw.get("active", True)),
            "strategy_version": raw.get("strategy_version"),
            "agent_id": raw.get("agent_id"),
            "metadata": raw.get("metadata") or {},
        }
        if not row["target_id"]:
            raise MarketSimError("ALLOCATION_TARGET_REQUIRED", "allocation target_id required")
        return self.store.upsert_portfolio_allocation(row)

    def list_portfolios(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_portfolios(limit=limit)

    def get_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        row = self.store.get_portfolio(portfolio_id)
        if row is None:
            raise MarketSimError("PORTFOLIO_NOT_FOUND", portfolio_id, http_status=404)
        return self._public_portfolio(row)

    def patch_portfolio(self, portfolio_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self.store.get_portfolio(portfolio_id)
            if row is None:
                raise MarketSimError("PORTFOLIO_NOT_FOUND", portfolio_id, http_status=404)
            if "name" in patch and patch["name"]:
                row["name"] = str(patch["name"]).strip()
            if "orchestra_id" in patch:
                row["orchestra_id"] = patch["orchestra_id"]
            if "benchmark_symbol" in patch and patch["benchmark_symbol"]:
                row["benchmark_symbol"] = str(patch["benchmark_symbol"]).upper()
            if "settings" in patch and isinstance(patch["settings"], dict):
                cfg = dict(row.get("settings") or {})
                cfg.update(patch["settings"])
                # Risk loosening may require approval — flag but still apply soft keys;
                # hard widen of drawdown/leverage recorded for audit.
                row["settings"] = self._default_settings(cfg)
                row["shorting_enabled"] = bool(row["settings"].get("shorting_enabled"))
                meta = dict(row.get("metadata") or {})
                snaps = list(meta.get("settings_history") or [])
                snaps.append({"at": utc_now(), "settings": dict(row["settings"])})
                meta["settings_history"] = snaps[-20:]
                row["metadata"] = meta
            row["updated_at"] = utc_now()
            self.store.upsert_portfolio(row)
            book = self._load_book(row)
            book.shorting_enabled = bool(row["shorting_enabled"])
            self._persist_book(row, book)
            return self._public_portfolio(row)

    def _public_portfolio(self, row: dict[str, Any]) -> dict[str, Any]:
        cash = float(row.get("cash") or 0)
        reserved = float(row.get("reserved_cash") or 0)
        return {
            **{k: v for k, v in row.items() if k != "book_json"},
            "available_buying_power": str(money(max(0.0, cash - reserved))),
            "truth": {
                "paper_only": True,
                "real_money": False,
                "mode": "PAPER",
                "not_historical_simulation": True,
                "not_live_broker": True,
            },
        }

    def _load_book(self, row: dict[str, Any]) -> PortfolioBook:
        pid = row["portfolio_id"]
        if pid in self._books:
            return self._books[pid]
        raw = row.get("book_json") or {}
        if isinstance(raw, str):
            raw = json.loads(raw) if raw else {}
        if raw:
            book = PortfolioBook.deserialize(raw)
        else:
            book = PortfolioBook(
                portfolio_id=pid,
                cash=money(row.get("cash") or row.get("initial_equity") or 0),
                shorting_enabled=bool(row.get("shorting_enabled")),
            )
        self._books[pid] = book
        return book

    def _persist_book(self, row: dict[str, Any], book: PortfolioBook, marks: dict[str, Any] | None = None) -> None:
        marks = marks or {}
        eq = book.equity(marks)
        upnl = book.unrealized_pnl(marks)
        row["book_json"] = book.serialize()
        row["cash"] = str(book.cash)
        row["reserved_cash"] = str(book.reserved_cash)
        row["realized_pnl"] = str(book.realized_pnl)
        row["unrealized_pnl"] = str(upnl)
        row["fees_paid"] = str(book.fees_paid)
        row["equity"] = str(eq)
        row["peak_equity"] = str(book.peak_equity)
        row["margin_used"] = str(book.margin_used(marks))
        row["gross_exposure"] = str(book.gross_exposure(marks))
        row["net_exposure"] = str(book.net_exposure(marks))
        row["shorting_enabled"] = book.shorting_enabled
        row["last_mark_at"] = utc_now()
        row["updated_at"] = utc_now()
        # SOD roll
        day = datetime.now(timezone.utc).date().isoformat()
        if row.get("sod_date") != day:
            row["sod_date"] = day
            row["sod_equity"] = str(eq)
        self.store.upsert_portfolio(row)
        self._books[row["portfolio_id"]] = book

    # --- Lifecycle ---

    def start(self, portfolio_id: str) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self.store.get_portfolio(portfolio_id)
            if row is None:
                raise MarketSimError("PORTFOLIO_NOT_FOUND", portfolio_id, http_status=404)
            if not row.get("orchestra_id"):
                # Allow manual-only start as PAUSED-capable RUNNING without orchestra
                # when settings allow; default require orchestra for RUNNING autonomous.
                cfg = row.get("settings") or {}
                if not cfg.get("allow_manual_only"):
                    raise MarketSimError(
                        "ORCHESTRA_REQUIRED",
                        "No Trading Orchestra assigned — assign one or enable manual-only mode",
                        http_status=409,
                    )
            row["status"] = PortfolioStatus.RUNNING.value
            row["updated_at"] = utc_now()
            self.store.upsert_portfolio(row)
            # Enqueue worker tick when plane available
            self._enqueue_tick(portfolio_id)
            return self._public_portfolio(row)

    def pause(self, portfolio_id: str) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            row["status"] = PortfolioStatus.PAUSED.value
            row["updated_at"] = utc_now()
            self.store.upsert_portfolio(row)
            return self._public_portfolio(row)

    def resume(self, portfolio_id: str) -> dict[str, Any]:
        return self.start(portfolio_id)

    def stop(self, portfolio_id: str) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            row["status"] = PortfolioStatus.STOPPED.value
            row["updated_at"] = utc_now()
            self.store.upsert_portfolio(row)
            return self._public_portfolio(row)

    def kill_switch(self, portfolio_id: str, *, armed: bool = True) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            row["kill_switch"] = bool(armed)
            row["updated_at"] = utc_now()
            self.store.upsert_portfolio(row)
            return self._public_portfolio(row)

    def _require(self, portfolio_id: str) -> dict[str, Any]:
        row = self.store.get_portfolio(portfolio_id)
        if row is None:
            raise MarketSimError("PORTFOLIO_NOT_FOUND", portfolio_id, http_status=404)
        return row

    def _enqueue_tick(self, portfolio_id: str) -> None:
        plane = self.plane
        if plane is None or getattr(plane, "job_runtime", None) is None:
            return
        try:
            plane.job_runtime.enqueue(
                capability_id="market_sim.portfolio_tick",
                arguments={"portfolio_id": portfolio_id},
                requested_by="portefeuille",
                idempotency_key=f"market_sim:portfolio_tick:{portfolio_id}:{utc_now()[:16]}",
                domain="market_sim",
                domain_entity_type="market_sim_portfolio",
                domain_entity_id=portfolio_id,
                worker_pool="market_sim",
                latency_class="background",
            )
        except Exception:  # noqa: BLE001
            pass

    # --- Marks ---

    def _provider_registry(self) -> Any:
        if self.plane is not None and getattr(self.plane, "providers", None) is not None:
            return self.plane.providers
        return self.providers

    def fetch_marks(self, row: dict[str, Any], symbols: list[str] | None = None) -> tuple[dict[str, float], dict[str, Any]]:
        marks: dict[str, float] = {}
        meta: dict[str, Any] = {"stale": False, "errors": [], "source": row.get("provider_id")}
        book = self._load_book(row)
        syms = symbols or list(book.positions.keys())
        if not syms and row.get("benchmark_symbol"):
            syms = [row["benchmark_symbol"]]
        provider = None
        registry = self._provider_registry()
        if registry is not None:
            try:
                provider = registry.get(row.get("provider_id") or "binance_public")
            except Exception as exc:  # noqa: BLE001
                meta["errors"].append(str(exc))
        for sym in syms:
            try:
                if provider is not None:
                    q = provider.fetch_quote(sym)
                    px = float(q.get("price") or q.get("last") or 0)
                    if px > 0:
                        marks[sym.upper()] = px
                        continue
                # Fallback: last mark from position
                pos = book.positions.get(sym.upper())
                if pos:
                    marks[sym.upper()] = float(pos.avg_entry)
                    meta["stale"] = True
            except Exception as exc:  # noqa: BLE001
                meta["errors"].append(f"{sym}:{exc}")
                meta["stale"] = True
                pos = book.positions.get(sym.upper())
                if pos:
                    marks[sym.upper()] = float(pos.avg_entry)
        if not marks and provider is None:
            meta["stale"] = True
        return marks, meta

    def mark_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            book = self._load_book(row)
            marks, mark_meta = self.fetch_marks(row)
            book.mark(marks)
            self._persist_book(row, book, marks)
            # Bounded snapshot cadence
            self._maybe_snapshot(row, book, marks, reason="mark")
            return {"portfolio": self._public_portfolio(row), "marks": marks, "mark_meta": mark_meta}

    def _maybe_snapshot(
        self, row: dict[str, Any], book: PortfolioBook, marks: dict[str, Any], *, reason: str
    ) -> None:
        now = utc_now()
        last = self.store.latest_portfolio_snapshot(row["portfolio_id"])
        should = reason in ("fill", "created", "rebalance")
        if last:
            try:
                prev = datetime.fromisoformat(str(last["timestamp"]).replace("Z", "+00:00"))
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - prev.astimezone(timezone.utc)).total_seconds()
                if age >= float((row.get("settings") or {}).get("mark_refresh_seconds", 5)) * 6:
                    should = True
            except ValueError:
                should = True
        else:
            should = True
        if not should:
            return
        eq = book.equity(marks)
        dd = book.drawdown_pct(marks)
        self.store.insert_portfolio_snapshot(
            {
                "snapshot_id": str(uuid.uuid4()),
                "portfolio_id": row["portfolio_id"],
                "timestamp": now,
                "equity": str(eq),
                "cash": str(book.cash),
                "realized_pnl": str(book.realized_pnl),
                "unrealized_pnl": str(book.unrealized_pnl(marks)),
                "gross_exposure": str(book.gross_exposure(marks)),
                "net_exposure": str(book.net_exposure(marks)),
                "margin_used": str(book.margin_used(marks)),
                "drawdown": str(round(dd, 4)),
                "metadata": {"reason": reason},
            }
        )

    # --- Orders ---

    def place_order(
        self,
        portfolio_id: str,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str | None = None,
        agent_id: str | None = None,
        orchestra_id: str | None = None,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        decision_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            if row.get("mode") != "PAPER":
                raise MarketSimError("LIVE_MONEY_BLOCKED", "Only PAPER portefeuilles execute here", http_status=403)
            if row.get("broker_mode") in ("live", "live_broker"):
                raise MarketSimError("LIVE_MONEY_BLOCKED", "Live broker blocked", http_status=403)

            client_order_id = client_order_id or idempotency_key or str(uuid.uuid4())
            existing = self.store.get_portfolio_order_by_client(portfolio_id, client_order_id)
            if existing and existing.get("status") == "filled":
                return {"order": existing, "idempotent_replay": True, "portfolio": self._public_portfolio(row)}

            book = self._load_book(row)
            settings = dict(row.get("settings") or {})
            settings["sod_equity"] = float(row.get("sod_equity") or row.get("equity") or 0)
            marks, mark_meta = self.fetch_marks(row, symbols=[symbol.upper()])
            # Ensure we have a mark for this symbol
            if symbol.upper() not in marks:
                marks, mark_meta = self.fetch_marks(row, symbols=[symbol.upper()])
            price = marks.get(symbol.upper())
            if price is None or price <= 0:
                order = self._record_order(
                    row,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    client_order_id=client_order_id,
                    status="blocked",
                    reject_reason="No market quote — refusing blind paper order",
                    agent_id=agent_id,
                    orchestra_id=orchestra_id or row.get("orchestra_id"),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    decision_id=decision_id,
                )
                return {"order": order, "portfolio": self._public_portfolio(row), "code": "FEED_UNCERTAIN"}

            allocations = self.store.list_portfolio_allocations(portfolio_id)
            gate = evaluate_portfolio_order(
                book=book,
                symbol=symbol.upper(),
                side=side,
                qty=qty,
                price=float(price),
                marks=marks,
                settings=settings,
                allocations=allocations,
                agent_id=agent_id,
                strategy_id=strategy_id,
                kill_switch=bool(row.get("kill_switch")),
                quote_stale=bool(mark_meta.get("stale")),
                shorting_enabled=bool(row.get("shorting_enabled") or settings.get("shorting_enabled")),
            )
            if not gate.get("allowed"):
                order = self._record_order(
                    row,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    client_order_id=client_order_id,
                    status="blocked",
                    reject_reason=str(gate.get("reason") or "risk blocked"),
                    agent_id=agent_id,
                    orchestra_id=orchestra_id or row.get("orchestra_id"),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    decision_id=decision_id,
                    risk_result=gate,
                )
                return {
                    "order": order,
                    "portfolio": self._public_portfolio(row),
                    "risk": gate,
                    "code": gate.get("code") or "RISK_VETO",
                }

            sized = float(gate.get("sized_qty") or qty)
            min_n = float(settings.get("min_order_notional", 10))
            max_n = float(settings.get("max_order_notional", 1_000_000))
            notional = abs(sized * float(price))
            if notional < min_n:
                raise MarketSimError("ORDER_TOO_SMALL", f"notional {notional} < min {min_n}")
            if notional > max_n:
                sized = max_n / float(price)

            open_count = sum(1 for p in book.positions.values() if p.qty > ZERO)
            if (
                side.upper() in ("BUY", "SHORT")
                and symbol.upper() not in book.positions
                and open_count >= int(settings.get("max_concurrent_positions", 20))
            ):
                raise MarketSimError("MAX_POSITIONS", "max concurrent positions reached", http_status=409)

            fee_bps = float(settings.get("fee_bps", 5))
            slip_bps = float(settings.get("slippage_bps", 2))
            slip = float(price) * (slip_bps / 10_000.0)
            fill_px = float(price) + slip if side.upper() in ("BUY", "COVER") else float(price) - slip
            fee = abs(sized * fill_px) * (fee_bps / 10_000.0)

            # Reserve buying power for BUY
            reservation_id = None
            if side.upper() == "BUY":
                need = money(sized * fill_px + fee)
                reservation_id = book.reserve(need)
                if reservation_id is None:
                    order = self._record_order(
                        row,
                        symbol=symbol,
                        side=side,
                        qty=sized,
                        client_order_id=client_order_id,
                        status="blocked",
                        reject_reason="Insufficient paper cash",
                        agent_id=agent_id,
                        orchestra_id=orchestra_id or row.get("orchestra_id"),
                        strategy_id=strategy_id,
                        strategy_version=strategy_version,
                        decision_id=decision_id,
                        risk_result=gate,
                    )
                    return {"order": order, "code": "INSUFFICIENT_CASH", "portfolio": self._public_portfolio(row)}

            order_id = str(uuid.uuid4())
            fill_id = f"fill-{client_order_id}"
            # Idempotent fill id from client order
            try:
                effect = book.apply_fill(
                    symbol=symbol.upper(),
                    side=side.upper(),
                    qty=sized,
                    price=fill_px,
                    fee=fee,
                    tx_id=fill_id,
                    timestamp=utc_now(),
                    agent_id=agent_id,
                    orchestra_id=orchestra_id or row.get("orchestra_id"),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    reservation_id=reservation_id,
                )
            except Exception as exc:  # noqa: BLE001
                if reservation_id:
                    book.release_reserve(reservation_id)
                order = self._record_order(
                    row,
                    symbol=symbol,
                    side=side,
                    qty=sized,
                    client_order_id=client_order_id,
                    status="failed",
                    reject_reason=str(exc),
                    agent_id=agent_id,
                    orchestra_id=orchestra_id or row.get("orchestra_id"),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    decision_id=decision_id,
                    risk_result=gate,
                    order_id=order_id,
                )
                self._persist_book(row, book, marks)
                return {"order": order, "code": "FILL_FAILED", "portfolio": self._public_portfolio(row)}

            order = self._record_order(
                row,
                symbol=symbol,
                side=side,
                qty=sized,
                client_order_id=client_order_id,
                status="filled",
                fill_price=str(money(fill_px)),
                fee=str(money(fee)),
                agent_id=agent_id,
                orchestra_id=orchestra_id or row.get("orchestra_id"),
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                decision_id=decision_id,
                risk_result=gate,
                order_id=order_id,
            )
            tx = {
                "transaction_id": fill_id,
                "portfolio_id": portfolio_id,
                "order_id": order_id,
                "fill_id": fill_id,
                "decision_id": decision_id,
                "symbol": symbol.upper(),
                "side": side.upper(),
                "qty": str(money(sized)),
                "price": str(money(fill_px)),
                "gross_notional": str(money(sized * fill_px)),
                "fees": str(money(fee)),
                "net_cash_effect": effect["net_cash_effect"],
                "result": effect["result"],
                "agent_id": agent_id,
                "orchestra_id": orchestra_id or row.get("orchestra_id"),
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "risk_result": gate,
                "timestamp": utc_now(),
                "metadata": {"paper_only": True, "slippage_bps": slip_bps, "fee_bps": fee_bps},
            }
            self.store.insert_portfolio_transaction(tx)
            self._sync_positions_table(row, book, marks)
            book.mark(marks)
            self._persist_book(row, book, marks)
            self._maybe_snapshot(row, book, marks, reason="fill")
            book.assert_invariants(marks)
            return {
                "order": order,
                "transaction": tx,
                "portfolio": self._public_portfolio(row),
                "risk": gate,
                "truth": {"paper_only": True, "real_money": False},
            }

    def _record_order(self, row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        now = utc_now()
        order = {
            "order_id": kwargs.get("order_id") or str(uuid.uuid4()),
            "portfolio_id": row["portfolio_id"],
            "client_order_id": kwargs["client_order_id"],
            "symbol": str(kwargs["symbol"]).upper(),
            "side": str(kwargs["side"]).upper(),
            "qty": str(money(kwargs["qty"])),
            "status": kwargs["status"],
            "fill_price": kwargs.get("fill_price"),
            "fee": kwargs.get("fee") or "0",
            "reject_reason": kwargs.get("reject_reason") or "",
            "decision_id": kwargs.get("decision_id"),
            "agent_id": kwargs.get("agent_id"),
            "orchestra_id": kwargs.get("orchestra_id"),
            "strategy_id": kwargs.get("strategy_id"),
            "strategy_version": kwargs.get("strategy_version"),
            "risk_result": kwargs.get("risk_result") or {},
            "submitted_at": now,
            "updated_at": now,
            "metadata": {"paper_only": True},
        }
        self.store.upsert_portfolio_order(order)
        return order

    def _sync_positions_table(
        self, row: dict[str, Any], book: PortfolioBook, marks: dict[str, Any]
    ) -> None:
        self.store.replace_portfolio_positions(
            row["portfolio_id"], book.open_positions_public(marks, equity=book.equity(marks))
        )

    def close_position(
        self, portfolio_id: str, position_id: str, *, fraction: float = 1.0
    ) -> dict[str, Any]:
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            book = self._load_book(row)
            marks, _ = self.fetch_marks(row)
            target = None
            for p in book.open_positions_public(marks):
                if p["position_id"] == position_id:
                    target = p
                    break
            if target is None:
                raise MarketSimError("POSITION_NOT_FOUND", position_id, http_status=404)
            qty = float(target["qty"]) * max(0.0, min(1.0, fraction))
            side = "SELL" if target["side"] == "LONG" else "COVER"
            return self.place_order(
                portfolio_id,
                symbol=target["symbol"],
                side=side,
                qty=qty,
                client_order_id=f"close-{position_id}-{uuid.uuid4().hex[:8]}",
                strategy_id=target.get("strategy_id"),
                strategy_version=target.get("strategy_version"),
                agent_id=target.get("agent_id"),
            )

    def close_positions(self, portfolio_id: str, position_ids: list[str]) -> dict[str, Any]:
        results = []
        for pid in position_ids:
            try:
                results.append(self.close_position(portfolio_id, pid))
            except MarketSimError as exc:
                results.append({"error": exc.public_dict(), "position_id": pid})
        return {"results": results, "portfolio": self.get_portfolio(portfolio_id)}

    # --- Autonomous tick ---

    def autonomous_tick(self, portfolio_id: str, *, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        """One autonomous paper cycle. Decision may be injected for tests."""
        with self._lock(portfolio_id):
            row = self._require(portfolio_id)
            if row["status"] != PortfolioStatus.RUNNING.value:
                return {"skipped": True, "reason": f"status={row['status']}", "portfolio": self._public_portfolio(row)}
            book = self._load_book(row)
            marks, mark_meta = self.fetch_marks(row)
            book.mark(marks)
            self._persist_book(row, book, marks)
            self._maybe_snapshot(row, book, marks, reason="tick")

            if decision is None:
                decision = self._propose_decision(row, book, marks)
            if not decision or str(decision.get("action") or "HOLD").upper() == "HOLD":
                return {
                    "decision": decision,
                    "portfolio": self._public_portfolio(row),
                    "mark_meta": mark_meta,
                    "executed": False,
                }

            result = self.place_order(
                portfolio_id,
                symbol=str(decision["symbol"]),
                side=str(decision["action"]),
                qty=float(decision.get("requested_qty") or 0),
                client_order_id=decision.get("client_order_id") or f"auto-{decision.get('decision_id')}",
                agent_id=decision.get("agent_id"),
                orchestra_id=decision.get("orchestra_id") or row.get("orchestra_id"),
                strategy_id=decision.get("strategy_id"),
                strategy_version=decision.get("strategy_version"),
                decision_id=decision.get("decision_id"),
            )
            result["decision"] = decision
            result["executed"] = result.get("order", {}).get("status") == "filled"
            return result

    def _propose_decision(
        self, row: dict[str, Any], book: PortfolioBook, marks: dict[str, Any]
    ) -> dict[str, Any]:
        """Lightweight deterministic proposal when orchestra not injecting.

        Prefer orchestra routing when plane has orchestra service; otherwise HOLD.
        """
        decision_id = str(uuid.uuid4())
        # Try orchestra if available
        plane = self.plane
        if plane is not None and row.get("orchestra_id") and hasattr(plane, "run_portfolio_orchestra_decision"):
            try:
                return plane.run_portfolio_orchestra_decision(row["portfolio_id"])
            except Exception:  # noqa: BLE001
                pass
        return {
            "decision_id": decision_id,
            "portfolio_id": row["portfolio_id"],
            "orchestra_id": row.get("orchestra_id"),
            "agent_id": None,
            "strategy_id": None,
            "strategy_version": None,
            "symbol": row.get("benchmark_symbol") or "BTCUSDT",
            "action": "HOLD",
            "requested_qty": None,
            "rationale_summary": "No autonomous proposal — HOLD",
            "created_at": utc_now(),
        }

    # --- Read models ---

    def dashboard(self, portfolio_id: str, *, range_key: str = "YTD") -> dict[str, Any]:
        row = self._require(portfolio_id)
        # Refresh marks opportunistically
        try:
            self.mark_portfolio(portfolio_id)
            row = self._require(portfolio_id)
        except Exception:  # noqa: BLE001
            pass
        book = self._load_book(row)
        marks, mark_meta = self.fetch_marks(row)
        settings = dict(row.get("settings") or {})
        eq = book.equity(marks)
        upnl = book.unrealized_pnl(marks)
        sod = float(row.get("sod_equity") or row.get("initial_equity") or eq)
        daily_pnl = float(eq) - sod
        daily_pct = (daily_pnl / sod * 100.0) if sod else 0.0
        initial = float(row.get("initial_equity") or 0)
        wr = book.win_rate()
        margin = book.margin_used(marks)
        margin_pct = float(margin) / float(eq) * 100.0 if eq > ZERO else 0.0

        snapshots = self.store.list_portfolio_snapshots(portfolio_id, limit=2000)
        series = downsample_snapshots(snapshots, range_key=range_key)
        perf = performance_from_snapshots(series, baseline_equity=initial or float(eq))
        alloc = allocation_breakdown(book, marks)
        exposure = exposure_summary(book, marks)
        health = health_score(
            drawdown_pct=book.drawdown_pct(marks),
            max_drawdown_limit_pct=float(settings.get("max_drawdown_pct", 20)),
            leverage=float(exposure["leverage"]),
            max_leverage=float(settings.get("max_leverage", 1.0)),
            largest_position_pct=float(exposure["largest_position_pct"]),
            concentration_limit_pct=float(settings.get("asset_concentration_pct", 40)),
            cash_reserve_pct=float(book.cash) / float(eq) * 100 if eq > ZERO else 100.0,
            cash_reserve_target_pct=float(settings.get("cash_reserve_pct", 10)),
            risk_limit_utilization=min(
                1.0,
                book.drawdown_pct(marks) / max(1.0, float(settings.get("max_drawdown_pct", 20))),
            ),
        )
        stress = stress_level(
            drawdown_pct=book.drawdown_pct(marks),
            leverage=float(exposure["leverage"]),
            largest_position_pct=float(exposure["largest_position_pct"]),
            vol=(perf["volatility"] / 100.0) if perf.get("volatility") is not None else None,
            risk_util=health["components"].get("risk_headroom", 0) / 20.0,
        )
        insights = generate_insights(
            book=book,
            marks=marks,
            settings=settings,
            health=health,
            exposure=exposure,
            performance=perf,
        )
        allocations = self.store.list_portfolio_allocations(portfolio_id)
        recs = generate_recommendations(
            portfolio_id=portfolio_id,
            book=book,
            marks=marks,
            settings=settings,
            allocations=allocations,
        )
        # Persist fresh recommendations (replace pending)
        self.store.replace_portfolio_recommendations(portfolio_id, recs)

        positions = book.open_positions_public(marks, equity=eq)
        txs = self.store.list_portfolio_transactions(portfolio_id, limit=30)
        strategies = self._strategy_allocation_view(portfolio_id, book, marks, allocations)

        last_sync = row.get("last_mark_at") or row.get("updated_at")
        kpis = {
            "total_equity": str(eq),
            "daily_pnl": str(money(daily_pnl)),
            "daily_pnl_pct": round(daily_pct, 2),
            "unrealized_pnl": str(upnl),
            "unrealized_pnl_pct": round(float(upnl) / initial * 100, 2) if initial else 0.0,
            "realized_pnl": str(book.realized_pnl),
            "realized_pnl_pct": round(float(book.realized_pnl) / initial * 100, 2) if initial else 0.0,
            "cash_balance": str(book.cash),
            "reserved_cash": str(book.reserved_cash),
            "available_buying_power": str(book.available_cash),
            "margin_usage_pct": round(margin_pct, 2),
            "margin_disabled": float(settings.get("max_leverage", 1.0)) <= 1.0 and not row.get("shorting_enabled"),
            "win_rate": None if wr is None else round(wr, 1),
            "last_sync": last_sync,
            "stale": bool(mark_meta.get("stale")),
        }

        return {
            "portfolio": self._public_portfolio(row),
            "kpis": kpis,
            "positions": positions,
            "allocation": alloc,
            "exposure": exposure,
            "risk": {
                "sharpe": perf.get("sharpe"),
                "sortino": perf.get("sortino"),
                "max_drawdown": perf.get("max_drawdown"),
                "var_1d_95": perf.get("var_1d_95"),
                "beta": perf.get("beta"),
                "volatility": perf.get("volatility"),
                "correlation": perf.get("correlation"),
                "stress_level": stress,
                "liquidity_score": self._liquidity_score(positions),
                "health": health,
                "insufficient": perf.get("insufficient"),
                "exposure_pct": exposure.get("net_exposure_pct"),
            },
            "insights": insights,
            "recent_transactions": txs,
            "strategy_allocation": strategies,
            "recommendations": recs,
            "performance_summary": {
                "total_return": perf.get("total_return"),
                "sharpe": perf.get("sharpe"),
                "max_drawdown": perf.get("max_drawdown"),
                "volatility": perf.get("volatility"),
                "range": range_key,
                "series": series,
            },
            "market_status": {
                "provider_id": row.get("provider_id"),
                "stale": bool(mark_meta.get("stale")),
                "errors": mark_meta.get("errors") or [],
                "marks": marks,
            },
            "generated_at": utc_now(),
            "truth": {
                "paper_only": True,
                "real_money": False,
                "read_model": True,
                "not_canonical_state": True,
            },
        }

    def _liquidity_score(self, positions: list[dict[str, Any]]) -> float | None:
        if not positions:
            return None
        scores = []
        mapping = {"high": 9.0, "medium": 6.0, "low": 3.0, "unknown": None}
        for p in positions:
            cat = asset_registry.get(p["symbol"]).liquidity_category
            sc = mapping.get(cat)
            if sc is not None:
                scores.append(sc)
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)

    def _strategy_allocation_view(
        self,
        portfolio_id: str,
        book: PortfolioBook,
        marks: dict[str, Any],
        allocations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        eq = float(book.equity(marks))
        by: dict[str, dict[str, Any]] = {}
        for a in allocations:
            if a.get("kind") != "strategy":
                continue
            sid = str(a["target_id"])
            by[sid] = {
                "strategy_id": sid,
                "strategy_version": a.get("strategy_version"),
                "allocation_pct": float(a.get("target_allocation_pct") or 0),
                "equity": "0",
                "daily_pnl": "0",
                "total_pnl": "0",
                "status": "ACTIVE" if a.get("active", True) else "INACTIVE",
                "agent_id": a.get("agent_id"),
            }
        for pos in book.open_positions_public(marks):
            sid = pos.get("strategy_id") or "unattributed"
            slot = by.setdefault(
                sid,
                {
                    "strategy_id": sid,
                    "strategy_version": pos.get("strategy_version"),
                    "allocation_pct": 0.0,
                    "equity": "0",
                    "daily_pnl": "0",
                    "total_pnl": "0",
                    "status": "ACTIVE",
                    "agent_id": pos.get("agent_id"),
                },
            )
            cur = float(slot["equity"]) + abs(float(pos["market_value"]))
            slot["equity"] = str(money(cur))
            slot["total_pnl"] = str(
                money(float(slot["total_pnl"]) + float(pos["unrealized_pnl"]) + float(pos["realized_pnl"]))
            )
        for sid, slot in by.items():
            if eq > 0 and float(slot.get("allocation_pct") or 0) == 0:
                slot["allocation_pct"] = round(float(slot["equity"]) / eq * 100, 2)
        return list(by.values())

    def performance(self, portfolio_id: str, *, range_key: str = "YTD") -> dict[str, Any]:
        row = self._require(portfolio_id)
        snaps = downsample_snapshots(
            self.store.list_portfolio_snapshots(portfolio_id, limit=5000), range_key=range_key
        )
        return performance_from_snapshots(
            snaps, baseline_equity=float(row.get("initial_equity") or 0)
        )

    def save_allocations(
        self, portfolio_id: str, allocations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._require(portfolio_id)
        total = sum(float(a.get("target_allocation_pct") or 0) for a in allocations if a.get("kind") != "reserve")
        if total > 100.01:
            raise MarketSimError("ALLOCATION_SUM", f"allocations sum to {total}% > 100%")
        saved = []
        for a in allocations:
            kind = str(a.get("kind") or "strategy")
            saved.append(self._save_allocation(portfolio_id, kind, a))
        return {"allocations": saved}

    def rebalance_preview(self, portfolio_id: str, orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        row = self._require(portfolio_id)
        book = self._load_book(row)
        marks, _ = self.fetch_marks(row)
        settings = row.get("settings") or {}
        if orders is None:
            recs = generate_recommendations(
                portfolio_id=portfolio_id,
                book=book,
                marks=marks,
                settings=settings,
                allocations=self.store.list_portfolio_allocations(portfolio_id),
            )
            orders = []
            for r in recs:
                orders.extend(r.get("estimated_orders") or [])
        return preview_rebalance(
            book=book,
            marks=marks,
            orders=orders,
            fee_bps=float(settings.get("fee_bps", 5)),
            slippage_bps=float(settings.get("slippage_bps", 2)),
        )

    def rebalance_execute(
        self, portfolio_id: str, orders: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        preview = self.rebalance_preview(portfolio_id, orders)
        results = []
        for o in preview.get("orders") or []:
            if o.get("status") == "skipped":
                continue
            try:
                results.append(
                    self.place_order(
                        portfolio_id,
                        symbol=str(o["symbol"]),
                        side=str(o["side"]),
                        qty=float(o["qty"]),
                        client_order_id=f"rebal-{uuid.uuid4().hex[:10]}",
                    )
                )
            except MarketSimError as exc:
                results.append({"error": exc.public_dict()})
        return {
            "preview": preview,
            "results": results,
            "portfolio": self.get_portfolio(portfolio_id),
            "truth": {"paper_only": True},
        }

    def export_report(self, portfolio_id: str, *, fmt: str = "json") -> dict[str, Any]:
        dash = self.dashboard(portfolio_id)
        payload = {
            "summary": dash["portfolio"],
            "kpis": dash["kpis"],
            "positions": dash["positions"],
            "transactions": dash["recent_transactions"],
            "strategy_allocation": dash["strategy_allocation"],
            "performance": dash["performance_summary"],
            "risk": dash["risk"],
            "exported_at": utc_now(),
            "truth": {"paper_only": True},
        }
        if fmt == "csv":
            lines = ["section,key,value"]
            for k, v in (payload["kpis"] or {}).items():
                lines.append(f"kpi,{k},{v}")
            for p in payload["positions"]:
                lines.append(
                    f"position,{p['symbol']},{p['side']},{p['qty']},{p['mark_price']},{p['unrealized_pnl']}"
                )
            for t in payload["transactions"]:
                lines.append(
                    f"tx,{t.get('timestamp')},{t.get('symbol')},{t.get('side')},{t.get('qty')},{t.get('price')}"
                )
            return {"format": "csv", "content": "\n".join(lines), "filename": f"portefeuille-{portfolio_id[:8]}.csv"}
        return {"format": "json", "content": payload, "filename": f"portefeuille-{portfolio_id[:8]}.json"}

    def apply_trading_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Route a structured TradingDecision into paper order flow."""
        action = str(decision.get("action") or "HOLD").upper()
        if action == "HOLD":
            return {"skipped": True, "decision": decision}
        qty = decision.get("requested_qty")
        if qty is None and decision.get("requested_notional"):
            row = self._require(str(decision["portfolio_id"]))
            marks, _ = self.fetch_marks(row, symbols=[str(decision["symbol"]).upper()])
            px = marks.get(str(decision["symbol"]).upper()) or 0
            if px <= 0:
                raise MarketSimError("FEED_UNCERTAIN", "no mark for notional sizing")
            qty = float(decision["requested_notional"]) / float(px)
        return self.place_order(
            str(decision["portfolio_id"]),
            symbol=str(decision["symbol"]),
            side=action,
            qty=float(qty or 0),
            client_order_id=str(decision.get("client_order_id") or f"dec-{decision.get('decision_id')}"),
            agent_id=decision.get("agent_id"),
            orchestra_id=decision.get("orchestra_id"),
            strategy_id=decision.get("strategy_id"),
            strategy_version=decision.get("strategy_version"),
            decision_id=decision.get("decision_id"),
        )
