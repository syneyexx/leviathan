"""Shadow Live — current-market decisions with NO broker submission (Master Program T13).

Agents observe live quotes, form intended orders, and persist them for later outcome
measurement. Distinguished from paper broker fills and from historical simulation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .types import MarketSimError


@dataclass
class ShadowDecision:
    decision_id: str
    session_id: str
    symbol: str
    side: str
    qty: float
    decision_ts: str
    quote_price: float | None
    expected_execution_price: float | None
    strategy_id: str | None = None
    strategy_version: int | None = None
    market_state_ref: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    feed_latency_ms: float | None = None
    realized_outcome: dict[str, Any] | None = None
    outcome_attached_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "decision_ts": self.decision_ts,
            "quote_price": self.quote_price,
            "expected_execution_price": self.expected_execution_price,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "market_state_ref": dict(self.market_state_ref),
            "rationale": self.rationale,
            "feed_latency_ms": self.feed_latency_ms,
            "realized_outcome": self.realized_outcome,
            "outcome_attached_at": self.outcome_attached_at,
            "metadata": dict(self.metadata),
            "truth": {
                "shadow_live": True,
                "no_broker_order": True,
                "not_paper_fill": True,
                "not_historical_backtest": True,
            },
        }


@dataclass
class ShadowLiveSession:
    session_id: str
    status: str  # active | paused | stopped
    symbol: str
    provider_id: str
    strategy_id: str | None
    strategy_version: int | None
    feed_status: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "symbol": self.symbol,
            "provider_id": self.provider_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "feed_status": self.feed_status,
            "decisions": list(self.decisions),
            "decision_count": len(self.decisions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "mode": "SHADOW",
            "truth": {
                "shadow_live": True,
                "no_broker_order": True,
                "live_money_blocked": True,
                "distinct_from_paper_broker": True,
            },
        }


class ShadowLiveRunner:
    """Control-plane helper used by MarketSimControlPlane (T13)."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self._sessions: dict[str, ShadowLiveSession] = {}

    def start(
        self,
        *,
        symbol: str,
        now: str,
        provider_id: str = "binance_public",
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        feed_status = "disconnected"
        latency = None
        quote = None
        try:
            provider = self.service.providers.get(provider_id)
            st = provider.status()
            latency = getattr(st, "latency_ms", None)
            feed_status = "live" if getattr(st, "reachable", False) else "disconnected"
            quote = provider.fetch_quote(symbol)
        except Exception as exc:  # noqa: BLE001
            feed_status = f"error:{exc}"
        session_id = str(uuid.uuid4())
        session = ShadowLiveSession(
            session_id=session_id,
            status="active",
            symbol=symbol.upper(),
            provider_id=provider_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            feed_status=feed_status,
            created_at=now,
            updated_at=now,
            metadata={
                "last_quote": quote,
                "feed_latency_ms": latency,
                "mode": "SHADOW",
            },
        )
        self._sessions[session_id] = session
        self._persist(session)
        return session.public_dict()

    def decide(
        self,
        session_id: str,
        *,
        side: str,
        qty: float,
        now: str,
        rationale: str = "",
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.status != "active":
            raise MarketSimError("SHADOW_SESSION_NOT_ACTIVE", session.status, http_status=409)
        quote = (session.metadata or {}).get("last_quote") or {}
        # Refresh quote for decision.
        try:
            provider = self.service.providers.get(session.provider_id)
            quote = provider.fetch_quote(session.symbol) or quote
            st = provider.status()
            session.feed_status = "live" if getattr(st, "reachable", False) else "disconnected"
            session.metadata["last_quote"] = quote
            session.metadata["feed_latency_ms"] = getattr(st, "latency_ms", None)
        except Exception as exc:  # noqa: BLE001
            session.feed_status = f"error:{exc}"
        price = quote.get("price") if isinstance(quote, dict) else None
        if price is None:
            raise MarketSimError(
                "FEED_UNCERTAIN",
                "No live quote for shadow decision",
                http_status=409,
            )
        decision = ShadowDecision(
            decision_id=str(uuid.uuid4()),
            session_id=session_id,
            symbol=session.symbol,
            side=str(side).upper(),
            qty=float(qty),
            decision_ts=now,
            quote_price=float(price),
            expected_execution_price=float(price),  # shadow uses quote as expected
            strategy_id=session.strategy_id,
            strategy_version=session.strategy_version,
            market_state_ref={"quote": quote, "feed_status": session.feed_status},
            rationale=rationale,
            feed_latency_ms=session.metadata.get("feed_latency_ms"),
            metadata={"broker_submitted": False},
        )
        session.decisions.append(decision.public_dict())
        session.updated_at = now
        self._persist(session)
        self._persist_decision(decision)
        return {"decision": decision.public_dict(), "session": session.public_dict()}

    def attach_outcome(
        self,
        session_id: str,
        decision_id: str,
        *,
        realized_price: float,
        now: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        found = None
        for d in session.decisions:
            if d.get("decision_id") == decision_id:
                found = d
                break
        if found is None:
            raise MarketSimError("SHADOW_DECISION_NOT_FOUND", decision_id, http_status=404)
        expected = float(found.get("expected_execution_price") or found.get("quote_price") or 0)
        realized = float(realized_price)
        side = str(found.get("side") or "").upper()
        qty = float(found.get("qty") or 0)
        # Simple mark: long benefits from rise; short from fall.
        if side == "BUY":
            pnl = (realized - expected) * qty
        elif side == "SELL":
            pnl = (expected - realized) * qty
        else:
            pnl = 0.0
        outcome = {
            "realized_price": realized,
            "expected_execution_price": expected,
            "price_error": realized - expected,
            "shadow_pnl": pnl,
            "detail": detail or {},
        }
        found["realized_outcome"] = outcome
        found["outcome_attached_at"] = now
        session.updated_at = now
        self._persist(session)
        self._persist_decision_update(found)
        return {"decision": found, "session": session.public_dict()}

    def get(self, session_id: str) -> dict[str, Any]:
        return self._get(session_id).public_dict()

    def pause(self, session_id: str, *, now: str) -> dict[str, Any]:
        session = self._get(session_id)
        session.status = "paused"
        session.updated_at = now
        self._persist(session)
        return session.public_dict()

    def resume(self, session_id: str, *, now: str) -> dict[str, Any]:
        session = self._get(session_id)
        session.status = "active"
        session.updated_at = now
        self._persist(session)
        return session.public_dict()

    def stop(self, session_id: str, *, now: str) -> dict[str, Any]:
        session = self._get(session_id)
        session.status = "stopped"
        session.updated_at = now
        self._persist(session)
        return session.public_dict()

    def _get(self, session_id: str) -> ShadowLiveSession:
        session = self._sessions.get(session_id)
        if session is None and hasattr(self.service.store, "get_shadow_live_session"):
            row = self.service.store.get_shadow_live_session(session_id)
            if row:
                session = ShadowLiveSession(
                    session_id=row["session_id"],
                    status=row["status"],
                    symbol=row["symbol"],
                    provider_id=row["provider_id"],
                    strategy_id=row.get("strategy_id"),
                    strategy_version=row.get("strategy_version"),
                    feed_status=row.get("feed_status") or "",
                    decisions=list(row.get("decisions") or []),
                    created_at=row.get("created_at") or "",
                    updated_at=row.get("updated_at") or "",
                    metadata=dict(row.get("metadata") or {}),
                )
                self._sessions[session_id] = session
        if session is None:
            raise MarketSimError("SHADOW_SESSION_NOT_FOUND", session_id, http_status=404)
        return session

    def _persist(self, session: ShadowLiveSession) -> None:
        if hasattr(self.service.store, "save_shadow_live_session"):
            try:
                self.service.store.save_shadow_live_session(session.public_dict())
            except Exception:  # noqa: BLE001
                pass

    def _persist_decision(self, decision: ShadowDecision) -> None:
        if hasattr(self.service.store, "save_shadow_decision"):
            try:
                self.service.store.save_shadow_decision(decision.public_dict())
            except Exception:  # noqa: BLE001
                pass

    def _persist_decision_update(self, decision: dict[str, Any]) -> None:
        if hasattr(self.service.store, "save_shadow_decision"):
            try:
                self.service.store.save_shadow_decision(decision)
            except Exception:  # noqa: BLE001
                pass
