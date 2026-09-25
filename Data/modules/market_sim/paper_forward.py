"""PaperForwardRunner — autonomous strategy→orders loop with checkpoints (T9 / G32)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import MarketSimError


QuoteFn = Callable[[str], dict[str, Any] | None]


@dataclass
class PaperForwardState:
    runner_id: str
    session_id: str
    status: str  # running | paused | stopped | error
    strategy_id: str | None = None
    strategy_version: int | None = None
    symbol: str = ""
    checkpoint: dict[str, Any] = field(default_factory=dict)
    loop_count: int = 0
    last_client_order_id: str | None = None
    last_error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "session_id": self.session_id,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "checkpoint": dict(self.checkpoint),
            "loop_count": self.loop_count,
            "last_client_order_id": self.last_client_order_id,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "truth": {
                "paper_only": True,
                "per_session_wallet": True,
                "idempotent_client_order_ids": True,
                "restart_resumable": True,
            },
        }


class PaperForwardRunner:
    """Autonomous paper loop: observe quote → risk → place idempotent order → checkpoint."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self._runners: dict[str, PaperForwardState] = {}

    def start(
        self,
        *,
        session_id: str,
        now: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
    ) -> dict[str, Any]:
        session = self.service.store.get_paper_session(session_id)
        if session is None:
            raise MarketSimError("PAPER_SESSION_NOT_FOUND", session_id, http_status=404)
        if session.get("status") != "active":
            raise MarketSimError("SESSION_NOT_ACTIVE", session.get("status") or "", http_status=409)
        runner_id = str(uuid.uuid4())
        state = PaperForwardState(
            runner_id=runner_id,
            session_id=session_id,
            status="running",
            strategy_id=strategy_id or session.get("strategy_id"),
            strategy_version=strategy_version or session.get("strategy_version"),
            symbol=str(session.get("symbol") or ""),
            checkpoint={"loops_done": 0, "last_side": None},
            created_at=now,
            updated_at=now,
        )
        self._runners[runner_id] = state
        self._persist(state)
        return state.public_dict()

    def pause(self, runner_id: str, *, now: str) -> dict[str, Any]:
        state = self._get(runner_id)
        if state.status in {"stopped", "error"}:
            raise MarketSimError("RUNNER_NOT_RUNNING", state.status, http_status=409)
        # Idempotent: already-paused (e.g. feed watchdog) stays paused.
        state.status = "paused"
        state.updated_at = now
        self._persist(state)
        return state.public_dict()

    def resume(self, runner_id: str, *, now: str) -> dict[str, Any]:
        state = self._get(runner_id)
        if state.status != "paused":
            raise MarketSimError("RUNNER_NOT_PAUSED", state.status, http_status=409)
        state.status = "running"
        state.updated_at = now
        self._persist(state)
        return state.public_dict()

    def stop(self, runner_id: str, *, now: str) -> dict[str, Any]:
        state = self._get(runner_id)
        state.status = "stopped"
        state.updated_at = now
        self._persist(state)
        return state.public_dict()

    def get(self, runner_id: str) -> dict[str, Any]:
        return self._get(runner_id).public_dict()

    def tick(self, runner_id: str, *, now: str, side: str | None = None) -> dict[str, Any]:
        """One autonomous loop iteration (idempotent client_order_id per loop index)."""
        state = self._get(runner_id)
        if state.status != "running":
            raise MarketSimError("RUNNER_NOT_RUNNING", state.status, http_status=409)
        # Deterministic client order id — retries do not duplicate.
        client_order_id = f"pfr:{state.runner_id}:{state.loop_count}"
        chosen_side = (side or self._default_side(state)).upper()
        try:
            result = self.service.paper_place_order(
                state.session_id,
                side=chosen_side,
                qty=1.0,
                client_order_id=client_order_id,
            )
            state.last_client_order_id = client_order_id
            state.loop_count += 1
            state.checkpoint = {
                "loops_done": state.loop_count,
                "last_side": chosen_side,
                "last_order_status": (result.get("order") or {}).get("status"),
            }
            state.last_error = ""
        except MarketSimError as exc:
            state.last_error = f"{exc.code}:{exc}"
            if exc.code in {"KILL_SWITCH", "FEED_UNCERTAIN", "FEED_STALE"}:
                state.status = "paused"
                state.checkpoint["paused_reason"] = exc.code
        state.updated_at = now
        self._persist(state)
        return {
            "runner": state.public_dict(),
            "client_order_id": client_order_id,
        }

    def _default_side(self, state: PaperForwardState) -> str:
        # Alternate for demo autonomy when no strategy signal is bound.
        last = (state.checkpoint or {}).get("last_side")
        return "SELL" if last == "BUY" else "BUY"

    def _get(self, runner_id: str) -> PaperForwardState:
        state = self._runners.get(runner_id)
        if state is None and hasattr(self.service.store, "get_paper_forward_runner"):
            row = self.service.store.get_paper_forward_runner(runner_id)
            if row:
                state = PaperForwardState(
                    runner_id=row["runner_id"],
                    session_id=row["session_id"],
                    status=row["status"],
                    strategy_id=row.get("strategy_id"),
                    strategy_version=row.get("strategy_version"),
                    symbol=row.get("symbol") or "",
                    checkpoint=dict(row.get("checkpoint") or {}),
                    loop_count=int(row.get("loop_count") or 0),
                    last_client_order_id=row.get("last_client_order_id"),
                    last_error=row.get("last_error") or "",
                    created_at=row.get("created_at") or "",
                    updated_at=row.get("updated_at") or "",
                )
                self._runners[runner_id] = state
        if state is None:
            raise MarketSimError("RUNNER_NOT_FOUND", runner_id, http_status=404)
        return state

    def _persist(self, state: PaperForwardState) -> None:
        if hasattr(self.service.store, "save_paper_forward_runner"):
            try:
                self.service.store.save_paper_forward_runner(state.public_dict())
            except Exception:  # noqa: BLE001
                pass
