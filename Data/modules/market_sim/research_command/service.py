"""Operator composition over TradeOrchestra, paper portfolios, news, and Research Lab.

Research Command does not place live orders, own a portfolio book, or advance
evolutionary generations. It binds existing owners and projects a bounded snapshot.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.market_sim.orchestra.service import TradingOrchestraError

_ACTIVE = {"CREATED", "RUNNING", "PAUSED"}
_EVOLVE_STATUSES = {"CREATED", "PAUSED", "FAILED"}
_PRIVATE_KEYS = {
    "chainofthought",
    "hiddenreasoning",
    "scratchpad",
    "privatereasoning",
    "reasoningtokens",
    "internalmonologue",
    "cot",
    "rawprompt",
    "privatecot",
    "hiddencot",
    "privatetokens",
}
_CLOSE_RESULTS = {"CLOSED", "COVERED", "CLOSED_AND_SHORT", "COVERED_AND_OPENED", "REDUCED"}
_DECISION_LIMIT = 80
_NEWS_LIMIT = 40
_EVENT_LIMIT = 40
_WATCH_LIMIT = 12


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return f"rcs-{uuid.uuid4().hex[:12]}"


class ResearchCommandError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


def measured(value: Any, *, note: str | None = None) -> dict[str, Any]:
    if value is None or value == "":
        return {"value": None, "measurement": "UNMEASURED", "note": note}
    return {"value": value, "measurement": "MEASURED", "note": note}


def unmeasured(note: str | None = None) -> dict[str, Any]:
    return {"value": None, "measurement": "UNMEASURED", "note": note}


def empty_measured(note: str | None = None) -> dict[str, Any]:
    return {"value": None, "measurement": "EMPTY", "note": note}


def agent_estimate(value: Any, *, note: str = "agent estimate, not measured validation") -> dict[str, Any]:
    if value is None or value == "":
        return unmeasured(note)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return unmeasured(note)
    if not math.isfinite(number):
        return unmeasured(note)
    return {"value": number, "measurement": "AGENT_ESTIMATE", "note": note}


def _norm_key(key: str) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def public_payload(payload: Any) -> Any:
    """Drop private chain-of-thought fields. Public rationale keys are kept."""
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if _norm_key(str(key)) in _PRIVATE_KEYS:
                continue
            out[str(key)] = public_payload(value)
        return out
    if isinstance(payload, list):
        return [public_payload(item) for item in payload]
    return payload


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _uptime_seconds(session: dict[str, Any] | None, *, now: str) -> dict[str, Any]:
    if not session or not session.get("started_at"):
        return unmeasured("no_started_at")
    start = _parse_ts(str(session.get("started_at")))
    if start is None:
        return unmeasured("unparseable_started_at")
    end_raw = session.get("paused_at") if session.get("state") == "PAUSED" else now
    if session.get("state") in {"COMPLETED", "CANCELLED", "FAILED"}:
        end_raw = session.get("ended_at") or session.get("paused_at") or now
    end = _parse_ts(str(end_raw)) if end_raw else None
    if end is None:
        return unmeasured("unparseable_end")
    return measured(max(0, int((end - start).total_seconds())))


class ResearchCommandService:
    def __init__(
        self,
        *,
        store: Any,
        trading: Any,
        portfolios: Any | None = None,
        plane: Any | None = None,
    ) -> None:
        self.store = store
        self.trading = trading
        self.portfolios = portfolios
        self.plane = plane

    # ------------------------------------------------------------------ lifecycle

    def assert_missions_allowed(self, orchestra_id: str) -> None:
        """Pause stops scheduling new orchestra missions. In-flight jobs are untouched."""
        session = self.store.active_research_session(orchestra_id)
        if session and session.get("state") == "PAUSED":
            raise TradingOrchestraError(
                "SESSION_PAUSED",
                "Research Command session is paused; new autonomous missions are not scheduled",
                http_status=409,
            )

    def start(self, *, orchestra_id: str, portfolio_id: str, lab_id: str | None = None) -> dict[str, Any]:
        orchestra = self._require_orchestra(orchestra_id)
        portfolio = self._require_paper_portfolio(portfolio_id)
        now = utc_now()
        universe = _universe_of(orchestra)
        session = self.store.active_research_session(orchestra_id)
        if session and session.get("state") == "RUNNING":
            if session.get("portfolio_id") and session.get("portfolio_id") != portfolio_id:
                raise ResearchCommandError(
                    "BINDING_MISMATCH",
                    "Pause the running session before binding a different paper portfolio",
                    http_status=409,
                )
            return {"session": self._public_session(session), "idempotent": True}
        if session is None:
            session = {
                "session_id": _new_id(),
                "orchestra_id": orchestra_id,
                "portfolio_id": portfolio_id,
                "paper_session_id": None,
                "lab_id": lab_id,
                "state": "CREATED",
                "universe": universe,
                "watch": _mandate_watch(universe),
                "started_at": None,
                "paused_at": None,
                "ended_at": None,
                "as_of": now,
                "created_at": now,
                "updated_at": now,
                "metadata": {},
            }
            self.store.insert_research_session(session)
        else:
            if session.get("state") not in {"CREATED", "PAUSED"}:
                raise ResearchCommandError(
                    "SESSION_TERMINAL",
                    f"state={session.get('state')}",
                    http_status=409,
                )
            session["portfolio_id"] = portfolio_id
            if lab_id:
                session["lab_id"] = lab_id
            session["universe"] = universe
            if not session.get("watch"):
                session["watch"] = _mandate_watch(universe)

        resumed_portfolio = False
        if not portfolio.get("kill_switch") and str(portfolio.get("status") or "") != "RUNNING":
            starter = getattr(self.portfolios, "start", None)
            if not callable(starter):
                raise ResearchCommandError(
                    "PAPER_ENGINE_UNAVAILABLE",
                    "Portfolio start is not available",
                    http_status=503,
                )
            starter(portfolio_id)
            resumed_portfolio = True
        session["state"] = "RUNNING"
        session["started_at"] = session.get("started_at") or now
        session["paused_at"] = None
        session["as_of"] = now
        session["updated_at"] = now
        meta = dict(session.get("metadata") or {})
        meta["last_start_resumed_portfolio"] = resumed_portfolio
        meta["kill_switch_at_start"] = bool(portfolio.get("kill_switch"))
        session["metadata"] = meta
        self.store.update_research_session(session)
        return {
            "session": self._public_session(session),
            "idempotent": False,
            "portfolioResumed": resumed_portfolio,
            "liveTrading": "BLOCKED",
        }

    def pause(self, *, session_id: str | None = None, orchestra_id: str | None = None) -> dict[str, Any]:
        session = self._require_session(session_id=session_id, orchestra_id=orchestra_id)
        if session.get("state") != "RUNNING":
            raise ResearchCommandError(
                "SESSION_NOT_RUNNING",
                f"state={session.get('state')}",
                http_status=409,
            )
        now = utc_now()
        portfolio_id = session.get("portfolio_id")
        paused_portfolio = False
        if portfolio_id and self.portfolios is not None:
            row = self._portfolio_row(str(portfolio_id))
            if row and str(row.get("status") or "") == "RUNNING":
                pauser = getattr(self.portfolios, "pause", None)
                if callable(pauser):
                    pauser(str(portfolio_id))
                    paused_portfolio = True
        session["state"] = "PAUSED"
        session["paused_at"] = now
        session["as_of"] = now
        session["updated_at"] = now
        meta = dict(session.get("metadata") or {})
        meta["paused_portfolio"] = paused_portfolio
        session["metadata"] = meta
        self.store.update_research_session(session)
        return {
            "session": self._public_session(session),
            "pausedPortfolio": paused_portfolio,
            "missionsCancelled": False,
            "liveTrading": "BLOCKED",
        }

    def add_watch(self, *, session_id: str, symbol: str, reason: str) -> dict[str, Any]:
        session = self._require_session(session_id=session_id, orchestra_id=None)
        cleaned_symbol = symbol.strip().upper()
        cleaned_reason = reason.strip()
        if not cleaned_symbol:
            raise ResearchCommandError("INVALID_SYMBOL", "symbol is required", http_status=400)
        if not cleaned_reason:
            raise ResearchCommandError(
                "WATCH_REASON_REQUIRED",
                "An explicit reason is required. Research Command will not invent why a symbol is watched.",
                http_status=400,
            )
        watch = [item for item in list(session.get("watch") or []) if str(item.get("symbol") or "").upper() != cleaned_symbol]
        watch.append({"symbol": cleaned_symbol, "reason": cleaned_reason, "source": "operator"})
        session["watch"] = watch[:_WATCH_LIMIT]
        session["updated_at"] = utc_now()
        self.store.update_research_session(session)
        return {"session": self._public_session(session)}

    def flatten(self, *, session_id: str, confirm: str) -> dict[str, Any]:
        if confirm != "FLATTEN_PAPER":
            raise ResearchCommandError(
                "CONFIRMATION_REQUIRED",
                "Flatten All requires confirm=FLATTEN_PAPER",
                http_status=400,
            )
        session = self._require_session(session_id=session_id, orchestra_id=None)
        portfolio_id = session.get("portfolio_id")
        if not portfolio_id:
            raise ResearchCommandError(
                "NO_PAPER_PORTFOLIO",
                "Flatten All requires a bound paper portfolio",
                http_status=409,
            )
        self._require_paper_portfolio(str(portfolio_id))
        positions = self._open_position_rows(str(portfolio_id))
        if not positions:
            return {
                "flattened": 0,
                "idempotent": True,
                "calledOwner": False,
                "owner": "PortfolioService",
                "liveTrading": "BLOCKED",
                "paperOnly": True,
            }
        flattener = getattr(self.portfolios, "flatten_all", None)
        if not callable(flattener):
            raise ResearchCommandError(
                "PAPER_ENGINE_UNAVAILABLE",
                "Portfolio flatten is not available",
                http_status=503,
            )
        result = flattener(str(portfolio_id))
        now = utc_now()
        meta = dict(session.get("metadata") or {})
        meta["last_flatten_at"] = now
        session["metadata"] = meta
        session["updated_at"] = now
        if session.get("state") == "RUNNING":
            session["state"] = "PAUSED"
            session["paused_at"] = now
            session["as_of"] = now
        self.store.update_research_session(session)
        return {
            "flattened": result.get("flattened") if isinstance(result, dict) else None,
            "idempotent": False,
            "calledOwner": True,
            "owner": "PortfolioService",
            "result": result,
            "liveTrading": "BLOCKED",
            "paperOnly": True,
        }

    def kill_switch(self, *, session_id: str, armed: bool, confirm: str | None = None) -> dict[str, Any]:
        if not armed and confirm != "DISARM_PAPER":
            raise ResearchCommandError(
                "CONFIRMATION_REQUIRED",
                "Disarming the paper kill switch requires confirm=DISARM_PAPER",
                http_status=400,
            )
        session = self._require_session(session_id=session_id, orchestra_id=None)
        portfolio_id = session.get("portfolio_id")
        if not portfolio_id:
            raise ResearchCommandError("NO_PAPER_PORTFOLIO", "No paper portfolio is bound", http_status=409)
        self._require_paper_portfolio(str(portfolio_id))
        switch = getattr(self.portfolios, "kill_switch", None)
        if not callable(switch):
            raise ResearchCommandError(
                "PAPER_ENGINE_UNAVAILABLE",
                "Portfolio kill switch is not available",
                http_status=503,
            )
        portfolio = switch(str(portfolio_id), armed=bool(armed))
        paused_portfolio = False
        if armed:
            row = self._portfolio_row(str(portfolio_id)) or {}
            if str(row.get("status") or "") == "RUNNING":
                pauser = getattr(self.portfolios, "pause", None)
                if callable(pauser):
                    pauser(str(portfolio_id))
                    paused_portfolio = True
            if session.get("state") == "RUNNING":
                now = utc_now()
                session["state"] = "PAUSED"
                session["paused_at"] = now
                session["as_of"] = now
                session["updated_at"] = now
                self.store.update_research_session(session)
        return {
            "armed": bool(armed),
            "pausedPortfolio": paused_portfolio,
            "portfolio": portfolio,
            "session": self._public_session(session),
            "flattened": False,
            "liveTrading": "BLOCKED",
        }

    def start_evolution(self, *, lab_id: str) -> dict[str, Any]:
        if not lab_id:
            raise ResearchCommandError("NO_LAB", "Select a Research Lab run first", http_status=409)
        if self.plane is None:
            raise ResearchCommandError(
                "LEARNER_UNAVAILABLE",
                "Research Lab control plane is not bound",
                http_status=503,
            )
        lab = self._lab(lab_id)
        if lab is None:
            raise ResearchCommandError("LAB_NOT_FOUND", lab_id, http_status=404)
        status = str(lab.get("status") or "")
        if status not in _EVOLVE_STATUSES:
            raise ResearchCommandError(
                "EVOLUTION_NOT_STARTABLE",
                f"status={status or 'UNMEASURED'}",
                http_status=409,
            )
        if status == "PAUSED":
            runner = getattr(self.plane, "resume_agent_lab", None)
            action = "resume_agent_lab"
        else:
            runner = getattr(self.plane, "start_agent_lab", None)
            action = "start_agent_lab"
        if not callable(runner):
            raise ResearchCommandError(
                "LEARNER_UNAVAILABLE",
                "Canonical learner start is not available",
                http_status=503,
            )
        result = runner(lab_id)
        return {
            "action": action,
            "owner": "AdaptiveEvolutionaryLearner",
            "labId": lab_id,
            "result": result,
            "liveTrading": "BLOCKED",
        }

    # ------------------------------------------------------------------ snapshot

    def snapshot(
        self,
        *,
        orchestra_id: str | None = None,
        portfolio_id: str | None = None,
        lab_id: str | None = None,
        session_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if not getattr(self.trading, "enabled", True):
            raise ResearchCommandError(
                "FEATURE_DISABLED",
                "Market sim feature flag is OFF (LEVIATHAN_FEATURE_MARKET_SIM)",
                http_status=503,
            )
        errors: list[str] = []
        catalogs = self._catalogs(errors)
        session = self._resolve_session(session_id=session_id, orchestra_id=orchestra_id)
        selected_orchestra = orchestra_id or (session.get("orchestra_id") if session else None)
        if not selected_orchestra and catalogs["orchestras"]:
            selected_orchestra = None
        orchestra = None
        if selected_orchestra:
            try:
                orchestra = self.trading.get_orchestra(selected_orchestra)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"orchestra:{exc}")
        selected_portfolio = portfolio_id or (session.get("portfolio_id") if session else None)
        selected_lab = lab_id or (session.get("lab_id") if session else None)
        resolved_as_of = as_of or (session.get("as_of") if session else None) or utc_now()

        decisions = self._decisions(selected_orchestra, resolved_as_of, errors)
        news = self._news(resolved_as_of, errors)
        signals = self._signals(resolved_as_of, errors)
        feeds = self._feeds(errors)
        missions = self._missions(selected_orchestra, errors)
        portfolio_row = self._portfolio_row(str(selected_portfolio)) if selected_portfolio else None
        if portfolio_row and not _is_paper(portfolio_row):
            errors.append("portfolio:LIVE_MONEY_BLOCKED")
            portfolio_row = None
            selected_portfolio = None
        dashboard = self._dashboard(str(selected_portfolio), errors) if selected_portfolio else None
        portfolio_view = self._project_portfolio(portfolio_row, dashboard)
        evolution = self._evolution(str(selected_lab) if selected_lab else None, errors)
        paper_forward = self._paper_forward(
            portfolio_id=str(selected_portfolio) if selected_portfolio and portfolio_row else None,
            session=session,
            errors=errors,
        )
        runtime = self._runtime(errors)
        team = self._team(orchestra, missions, decisions)
        thesis = self._thesis(decisions, evolution)
        intent = self._intent(decisions)
        watching = self._watching(
            session=session,
            orchestra=orchestra,
            decisions=decisions,
            signals=signals,
            news=news,
            as_of=resolved_as_of,
        )
        events = self._events(decisions, missions)
        guardrails = self._guardrails(orchestra, portfolio_row, portfolio_view)
        safety = _safety(orchestra, portfolio_row, session)
        evidence_count = len(decisions) + len(signals) + len(news) + len(evolution.get("rows") or [])
        open_count = int(portfolio_view.get("openCount") or 0)
        actions = _actions(
            session=session,
            orchestra_id=selected_orchestra,
            portfolio_id=selected_portfolio if portfolio_row else None,
            portfolio_mode=(portfolio_row or {}).get("mode") if portfolio_row else None,
            open_positions=open_count,
            lab_id=selected_lab,
            lab_status=evolution.get("status"),
            evidence_count=evidence_count,
            kill_switch=bool((portfolio_row or {}).get("kill_switch")),
        )
        return {
            "session": self._session_view(session, orchestra, safety),
            "team": team,
            "portfolio": portfolio_view,
            "watching": watching,
            "publicEvents": events,
            "decisions": decisions,
            "signals": signals,
            "feeds": feeds,
            "thesis": thesis,
            "intent": intent,
            "positions": {
                "open": portfolio_view.get("open") or [],
                "closed": portfolio_view.get("closed") or [],
                "unrealizedPnl": portfolio_view.get("unrealizedPnl"),
                "realizedPnl": portfolio_view.get("realizedPnl"),
                "openCount": open_count,
            },
            "strategyEvolution": evolution,
            "paperForward": paper_forward,
            "guardrails": guardrails,
            "missions": missions[:20],
            "catalogs": catalogs,
            "selection": {
                "orchestraId": selected_orchestra,
                "portfolioId": selected_portfolio if portfolio_row else selected_portfolio,
                "labId": selected_lab,
                "sessionId": session.get("session_id") if session else None,
                "asOf": resolved_as_of,
            },
            "actions": actions,
            "runtime": runtime,
            "truth": {
                "liveTrading": "BLOCKED",
                "paperOnly": True,
                "signalsAreDataNotAuthority": True,
                "publicReasoningOnly": True,
                "privateChainOfThought": "NOT_EXPOSED",
                "readModel": True,
                "compositionOnly": True,
                "doesNotAdvanceGenerations": True,
                "riskAuthority": (orchestra or {}).get("truth", {}).get("risk_authority")
                if orchestra
                else None,
                "asOf": resolved_as_of,
                "errors": errors,
                "owners": {
                    "session": "market_research_command_sessions",
                    "orchestra": "TradingOrchestraService",
                    "portfolio": "PortfolioService",
                    "evolution": "AdaptiveEvolutionaryLearner",
                    "news": "OrchestraStore",
                    "decisions": "market_decisions",
                },
            },
        }

    # ------------------------------------------------------------------ internals

    def _require_orchestra(self, orchestra_id: str) -> dict[str, Any]:
        if not orchestra_id:
            raise ResearchCommandError("NO_ORCHESTRA", "Select a trade orchestra", http_status=409)
        try:
            return self.trading.get_orchestra(orchestra_id)
        except TradingOrchestraError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ResearchCommandError("ORCHESTRA_UNAVAILABLE", str(exc), http_status=503) from exc

    def _portfolio_row(self, portfolio_id: str | None) -> dict[str, Any] | None:
        if not portfolio_id or self.portfolios is None:
            return None
        getter = getattr(self.portfolios, "get_portfolio", None)
        if callable(getter):
            return getter(portfolio_id)
        store = getattr(self.portfolios, "store", None)
        if store is not None and hasattr(store, "get_portfolio"):
            return store.get_portfolio(portfolio_id)
        return None

    def _require_paper_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        if not portfolio_id:
            raise ResearchCommandError(
                "NO_PAPER_PORTFOLIO",
                "A paper portfolio is required",
                http_status=409,
            )
        if self.portfolios is None:
            raise ResearchCommandError(
                "PAPER_ENGINE_UNAVAILABLE",
                "Paper portfolio service is not bound",
                http_status=503,
            )
        row = self._portfolio_row(portfolio_id)
        if row is None:
            raise ResearchCommandError("PORTFOLIO_NOT_FOUND", portfolio_id, http_status=404)
        if not _is_paper(row):
            raise ResearchCommandError(
                "LIVE_MONEY_BLOCKED",
                "Research Command binds paper portfolios only. Live trading remains blocked.",
                http_status=403,
            )
        return row

    def _require_session(
        self, *, session_id: str | None, orchestra_id: str | None
    ) -> dict[str, Any]:
        session = None
        if session_id:
            session = self.store.get_research_session(session_id)
        elif orchestra_id:
            session = self.store.active_research_session(orchestra_id)
        if session is None:
            raise ResearchCommandError("NO_SESSION", "No research session is bound", http_status=404)
        return session

    def _resolve_session(
        self, *, session_id: str | None, orchestra_id: str | None
    ) -> dict[str, Any] | None:
        if session_id:
            return self.store.get_research_session(session_id)
        if orchestra_id:
            return self.store.active_research_session(orchestra_id)
        return None

    def _public_session(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            "sessionId": session.get("session_id"),
            "orchestraId": session.get("orchestra_id"),
            "portfolioId": session.get("portfolio_id"),
            "paperSessionId": session.get("paper_session_id"),
            "labId": session.get("lab_id"),
            "state": session.get("state"),
            "universe": list(session.get("universe") or []),
            "watch": list(session.get("watch") or []),
            "startedAt": session.get("started_at"),
            "pausedAt": session.get("paused_at"),
            "endedAt": session.get("ended_at"),
            "asOf": session.get("as_of"),
            "createdAt": session.get("created_at"),
            "updatedAt": session.get("updated_at"),
        }

    def _session_view(
        self,
        session: dict[str, Any] | None,
        orchestra: dict[str, Any] | None,
        safety: str,
    ) -> dict[str, Any]:
        now = utc_now()
        mode = "NO_PAPER_WALLET"
        if session and session.get("portfolio_id"):
            row = self._portfolio_row(str(session.get("portfolio_id")))
            if row and _is_paper(row):
                mode = "PAPER"
            elif row:
                mode = "NOT_SAFE"
        elif orchestra and (orchestra.get("truth") or {}).get("paper_only") is True:
            mode = "PAPER_UNBOUND"
        return {
            "bound": session is not None,
            "sessionId": session.get("session_id") if session else None,
            "state": session.get("state") if session else "NO_SESSION",
            "mode": mode,
            "safety": safety,
            "name": (orchestra or {}).get("name") if orchestra else None,
            "orchestraId": (orchestra or {}).get("orchestraId") if orchestra else (session.get("orchestra_id") if session else None),
            "startedAt": session.get("started_at") if session else None,
            "pausedAt": session.get("paused_at") if session else None,
            "uptime": _uptime_seconds(session, now=now),
            "universe": _universe_of(orchestra) if orchestra else (list(session.get("universe") or []) if session else []),
            "portfolioId": session.get("portfolio_id") if session else None,
            "labId": session.get("lab_id") if session else None,
            "asOf": (session.get("as_of") if session else None) or now,
            "autonomy": (orchestra or {}).get("autonomyLevel") if orchestra else None,
            "readiness": (orchestra or {}).get("readiness") if orchestra else None,
        }

    def _catalogs(self, errors: list[str]) -> dict[str, list[dict[str, Any]]]:
        orchestras: list[dict[str, Any]] = []
        try:
            if getattr(self.trading, "fleet", None) is not None or hasattr(self.trading, "list_orchestras"):
                for row in self.trading.list_orchestras() or []:
                    orchestras.append(
                        {
                            "orchestraId": row.get("orchestraId"),
                            "name": row.get("name"),
                            "autonomyLevel": row.get("autonomyLevel"),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"orchestras:{exc}")
        portfolios: list[dict[str, Any]] = []
        lister = getattr(self.portfolios, "list_portfolios", None)
        if self.plane is not None and hasattr(self.plane, "list_portfolios"):
            lister = self.plane.list_portfolios
        if callable(lister):
            try:
                listed = lister(limit=30) if _accepts_limit(lister) else lister()
                for row in listed or []:
                    if not isinstance(row, dict) or not _is_paper(row):
                        continue
                    portfolios.append(
                        {
                            "portfolioId": row.get("portfolio_id"),
                            "name": row.get("name"),
                            "status": row.get("status"),
                            "mode": row.get("mode"),
                            "brokerMode": row.get("broker_mode"),
                            "killSwitch": bool(row.get("kill_switch")),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"portfolios:{exc}")
        labs: list[dict[str, Any]] = []
        if self.plane is not None and hasattr(self.plane, "list_agent_labs"):
            try:
                for row in self.plane.list_agent_labs(limit=20) or []:
                    if not isinstance(row, dict):
                        continue
                    labs.append(
                        {
                            "labId": row.get("lab_id"),
                            "name": row.get("name"),
                            "status": row.get("status"),
                            "strategyId": row.get("strategy_id"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"labs:{exc}")
        return {"orchestras": orchestras[:30], "portfolios": portfolios[:30], "labs": labs[:20]}

    def _decisions(self, orchestra_id: str | None, as_of: str, errors: list[str]) -> list[dict[str, Any]]:
        if not orchestra_id:
            return []
        try:
            rows = self.trading.list_decisions(orchestra_id=orchestra_id, limit=_DECISION_LIMIT)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"decisions:{exc}")
            return []
        out: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if row.get("asOf") and str(row.get("asOf")) > as_of:
                continue
            cleaned = dict(row)
            cleaned.pop("promptArtifactId", None)
            cleaned.pop("outputArtifactId", None)
            cleaned["payload"] = public_payload(row.get("payload") or {})
            out.append(cleaned)
        return out

    def _news(self, as_of: str, errors: list[str]) -> list[dict[str, Any]]:
        try:
            rows = self.trading.list_news(as_of=as_of, limit=_NEWS_LIMIT)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"news:{exc}")
            return []
        return [row for row in (rows or []) if isinstance(row, dict)][:_NEWS_LIMIT]

    def _signals(self, as_of: str, errors: list[str]) -> list[dict[str, Any]]:
        try:
            rows = self.trading.list_signals(as_of=as_of, limit=_NEWS_LIMIT)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"signals:{exc}")
            return []
        return [row for row in (rows or []) if isinstance(row, dict)][:_NEWS_LIMIT]

    def _feeds(self, errors: list[str]) -> list[dict[str, Any]]:
        try:
            rows = self.trading.list_feeds()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"feeds:{exc}")
            return []
        return [row for row in (rows or []) if isinstance(row, dict)][:50]

    def _missions(self, orchestra_id: str | None, errors: list[str]) -> list[dict[str, Any]]:
        if not orchestra_id:
            return []
        try:
            rows = self.trading.list_missions(orchestra_id, limit=20)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"missions:{exc}")
            return []
        return [row for row in (rows or []) if isinstance(row, dict)]

    def _dashboard(self, portfolio_id: str, errors: list[str]) -> dict[str, Any] | None:
        dash = getattr(self.portfolios, "dashboard", None)
        if not callable(dash):
            errors.append("portfolio:dashboard_unavailable")
            return None
        try:
            return dash(portfolio_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"dashboard:{exc}")
            return None

    def _open_position_rows(self, portfolio_id: str) -> list[dict[str, Any]]:
        dash = self._dashboard(portfolio_id, [])
        if not dash:
            raise ResearchCommandError(
                "PAPER_STATE_UNAVAILABLE",
                "Cannot prove open paper positions, so flatten was not called",
                http_status=503,
            )
        rows = []
        for pos in dash.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            try:
                qty = float(pos.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty != 0 and pos.get("position_id"):
                rows.append(pos)
        return rows

    def _project_portfolio(
        self, row: dict[str, Any] | None, dashboard: dict[str, Any] | None
    ) -> dict[str, Any]:
        if row is None:
            return {
                "bound": False,
                "portfolioId": None,
                "name": None,
                "status": None,
                "mode": None,
                "currency": None,
                "killSwitch": None,
                "equity": unmeasured("no_portfolio"),
                "cash": unmeasured("no_portfolio"),
                "allocated": unmeasured("no_portfolio"),
                "openRisk": unmeasured("no_portfolio"),
                "buyingPower": unmeasured("no_portfolio"),
                "leverage": unmeasured("no_portfolio"),
                "dailyPnl": unmeasured("no_portfolio"),
                "sessionPnl": unmeasured("no_portfolio"),
                "unrealizedPnl": unmeasured("no_portfolio"),
                "realizedPnl": unmeasured("no_portfolio"),
                "allocations": {
                    "cash": unmeasured("no_portfolio"),
                    "positions": unmeasured("no_portfolio"),
                    "risk": unmeasured("no_portfolio"),
                },
                "open": [],
                "closed": [],
                "openCount": 0,
                "marks": "UNAVAILABLE",
            }
        kpis = (dashboard or {}).get("kpis") or {}
        market = (dashboard or {}).get("market_status") or {}
        stale = bool(kpis.get("stale") or market.get("stale"))
        positions = [p for p in ((dashboard or {}).get("positions") or []) if isinstance(p, dict)]
        has_positions = len(positions) > 0
        marks_ok = dashboard is not None and not stale
        cash = measured(kpis.get("cash_balance")) if kpis.get("cash_balance") is not None else measured(row.get("cash"))
        realized = (
            measured(kpis.get("realized_pnl"))
            if kpis.get("realized_pnl") is not None
            else measured(row.get("realized_pnl"))
            if row.get("realized_pnl") is not None
            else unmeasured("no_realized_pnl")
        )
        if not has_positions and dashboard is not None:
            equity = measured(kpis.get("total_equity") or row.get("equity") or kpis.get("cash_balance"))
            unrealized = measured("0", note="no_open_positions")
            daily = measured(kpis.get("daily_pnl")) if kpis.get("daily_pnl") is not None else unmeasured("no_daily_pnl")
            leverage = measured(0, note="no_open_positions")
        elif marks_ok:
            equity = measured(kpis.get("total_equity"))
            unrealized = measured(kpis.get("unrealized_pnl"))
            daily = measured(kpis.get("daily_pnl")) if kpis.get("daily_pnl") is not None else unmeasured("no_daily_pnl")
            exposure = (dashboard or {}).get("exposure") or {}
            leverage = measured(exposure.get("leverage")) if exposure.get("leverage") is not None else unmeasured("no_leverage")
        else:
            equity = unmeasured("mark_stale_or_missing")
            unrealized = unmeasured("mark_stale_or_missing")
            daily = unmeasured("mark_stale_or_missing")
            leverage = unmeasured("mark_stale_or_missing")
        allocated = unmeasured("mark_stale_or_missing") if has_positions and not marks_ok else _allocated(kpis, equity)
        open_rows = [_open_position(pos, marks_ok=marks_ok or not has_positions) for pos in positions]
        closed_rows = _closed_positions((dashboard or {}).get("recent_transactions") or [])
        allocations = _allocation_bars(cash, equity, leverage, has_positions=has_positions, marks_ok=marks_ok)
        buying = kpis.get("available_buying_power")
        return {
            "bound": True,
            "portfolioId": row.get("portfolio_id"),
            "name": row.get("name"),
            "status": row.get("status"),
            "mode": row.get("mode"),
            "brokerMode": row.get("broker_mode"),
            "currency": row.get("base_currency") or "USD",
            "killSwitch": bool(row.get("kill_switch")),
            "equity": equity,
            "cash": cash,
            "allocated": allocated,
            "openRisk": leverage,
            "buyingPower": measured(buying) if buying is not None else unmeasured("no_buying_power"),
            "leverage": leverage,
            "dailyPnl": daily,
            "sessionPnl": unmeasured("session_pnl_not_separately_recorded"),
            "unrealizedPnl": unrealized,
            "realizedPnl": realized,
            "allocations": allocations,
            "open": open_rows,
            "closed": closed_rows,
            "openCount": len(open_rows),
            "marks": "MEASURED" if marks_ok else ("UNMEASURED" if has_positions or dashboard is None else "NO_POSITIONS"),
        }

    def _team(
        self,
        orchestra: dict[str, Any] | None,
        missions: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not orchestra:
            return {"name": None, "members": [], "telemetry": "UNMEASURED"}
        running = any(str(m.get("status") or "") in {"queued", "starting", "running"} for m in missions)
        members = []
        for member in orchestra.get("members") or []:
            if not isinstance(member, dict):
                continue
            agent_id = member.get("agentId")
            last = next((d for d in decisions if d.get("agentId") == agent_id), None)
            enabled = bool(member.get("enabled", True))
            if not enabled:
                state = "IDLE"
            elif running:
                state = "ACTIVE"
            else:
                state = "IDLE"
            members.append(
                {
                    "agentId": agent_id,
                    "name": member.get("name"),
                    "role": member.get("role") or member.get("canonicalRole"),
                    "kind": member.get("kind"),
                    "enabled": enabled,
                    "health": member.get("health"),
                    "state": state,
                    "activity": last.get("stage") if last else None,
                    "activityMeasurement": "MEASURED" if last else "UNMEASURED",
                    "telemetry": "UNMEASURED",
                }
            )
        return {
            "name": orchestra.get("name"),
            "orchestraId": orchestra.get("orchestraId"),
            "members": members,
            "telemetry": "UNMEASURED",
            "modelAvailable": None,
        }

    def _thesis(self, decisions: list[dict[str, Any]], evolution: dict[str, Any]) -> dict[str, Any]:
        proposal = next((d for d in decisions if d.get("stage") == "proposal"), None)
        if proposal:
            payload = proposal.get("payload") or {}
            critique = next(
                (
                    d
                    for d in decisions
                    if d.get("stage") == "critique" and d.get("parentDecisionId") == proposal.get("decisionId")
                ),
                None,
            )
            flags = ((critique or {}).get("payload") or {}).get("riskFlags")
            return {
                "present": True,
                "source": "trade_orchestra_proposal",
                "decisionId": proposal.get("decisionId"),
                "primary": payload.get("rationale") or None,
                "instruments": [payload.get("instrument")] if payload.get("instrument") else [],
                "direction": payload.get("direction"),
                "horizon": measured(payload.get("horizon")) if payload.get("horizon") else unmeasured("no_horizon"),
                "expectedEdge": unmeasured("not_recorded"),
                "invalidation": measured(flags) if flags else unmeasured("not_recorded"),
                "catalysts": empty_measured("not_recorded"),
                "confidence": agent_estimate(payload.get("confidence"))
                if payload.get("confidence") is not None
                else unmeasured("no_confidence_field"),
                "measuredValidation": unmeasured("not_a_lab_measurement"),
                "asOf": proposal.get("asOf"),
            }
        hypothesis = evolution.get("hypothesis")
        if hypothesis:
            return {
                "present": True,
                "source": "research_lab_hypothesis",
                "decisionId": None,
                "primary": hypothesis,
                "instruments": [],
                "direction": None,
                "horizon": unmeasured("not_recorded"),
                "expectedEdge": unmeasured("not_recorded"),
                "invalidation": unmeasured("not_recorded"),
                "catalysts": empty_measured("not_recorded"),
                "confidence": unmeasured("no_confidence_field"),
                "measuredValidation": evolution.get("bestValidation") or unmeasured("not_recorded"),
                "asOf": None,
            }
        return {
            "present": False,
            "source": None,
            "primary": None,
            "instruments": [],
            "confidence": unmeasured("no_thesis"),
            "measuredValidation": unmeasured("no_thesis"),
            "expectedEdge": unmeasured("no_thesis"),
            "horizon": unmeasured("no_thesis"),
            "invalidation": unmeasured("no_thesis"),
            "catalysts": empty_measured("no_thesis"),
        }

    def _intent(self, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        intent = next((d for d in decisions if d.get("stage") == "order_intent"), None)
        risk = next((d for d in decisions if d.get("stage") == "risk_decision"), None)
        source = intent or risk
        if not source:
            return {
                "present": False,
                "authority": "proposal",
                "liveTrading": "BLOCKED",
                "paperOnly": True,
                "instrument": None,
                "direction": None,
                "size": unmeasured("no_intent"),
                "maxRisk": unmeasured("no_intent"),
                "stop": unmeasured("no_intent"),
                "target": unmeasured("no_intent"),
                "rationale": None,
                "sizingRationale": unmeasured("no_intent"),
            }
        payload = source.get("payload") or {}
        size = payload.get("qty") if payload.get("qty") is not None else payload.get("sizedQty")
        return {
            "present": True,
            "authority": "proposal",
            "stage": source.get("stage"),
            "decisionId": source.get("decisionId"),
            "liveTrading": "BLOCKED",
            "paperOnly": True,
            "routed": payload.get("routed") is True and str(payload.get("venue") or "paper") == "paper",
            "instrument": payload.get("instrument"),
            "direction": payload.get("side") or payload.get("direction"),
            "size": measured(size) if size is not None else unmeasured("not_recorded"),
            "maxRisk": measured(payload.get("maxRisk")) if payload.get("maxRisk") is not None else unmeasured("not_recorded"),
            "stop": measured(payload.get("stop") or payload.get("stopPrice"))
            if payload.get("stop") or payload.get("stopPrice")
            else unmeasured("not_recorded"),
            "target": measured(payload.get("target") or payload.get("targetPrice"))
            if payload.get("target") or payload.get("targetPrice")
            else unmeasured("not_recorded"),
            "rationale": payload.get("reason") or payload.get("rationale"),
            "sizingRationale": measured(payload.get("sizingRationale"))
            if payload.get("sizingRationale")
            else unmeasured("not_recorded"),
            "riskAllowed": payload.get("allowed") if source.get("stage") == "risk_decision" else None,
            "status": payload.get("status"),
        }

    def _watching(
        self,
        *,
        session: dict[str, Any] | None,
        orchestra: dict[str, Any] | None,
        decisions: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        news: list[dict[str, Any]],
        as_of: str,
    ) -> dict[str, Any]:
        watch_rows = list(session.get("watch") or []) if session else []
        if not watch_rows:
            watch_rows = _mandate_watch(_universe_of(orchestra) if orchestra else [])
        symbols = []
        seen: set[str] = set()
        for item in watch_rows:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append((symbol, item))
            if len(symbols) >= _WATCH_LIMIT:
                break
        rows = []
        measured_vols: list[float] = []
        for symbol, item in symbols:
            stats = _bar_stats(self.trading, symbol, as_of)
            why, why_source = _why_watching(symbol, item, decisions, signals)
            vol_field = measured(stats["vol"], note="bar_sample") if stats and stats.get("vol") is not None else unmeasured("no_bars")
            if stats and stats.get("vol") is not None:
                measured_vols.append(float(stats["vol"]))
            rows.append(
                {
                    "symbol": symbol,
                    "last": measured(stats["last"]) if stats and stats.get("last") is not None else unmeasured("no_bars"),
                    "change24h": measured(stats["change"]) if stats and stats.get("change") is not None else unmeasured("no_bars"),
                    "change7d": measured(stats["change7"]) if stats and stats.get("change7") is not None else unmeasured("no_bars"),
                    "spark": stats["spark"] if stats and stats.get("spark") else [],
                    "volatility": vol_field,
                    "why": why,
                    "whySource": why_source,
                }
            )
        high: list[dict[str, Any]] = []
        high_note = "No measured volatility."
        if len(measured_vols) >= 2:
            median = sorted(measured_vols)[len(measured_vols) // 2]
            high = [
                row
                for row in rows
                if row["volatility"]["measurement"] == "MEASURED" and float(row["volatility"]["value"]) > median
            ]
            high_note = "Above the median of measured bar-sample volatilities on this watchlist."
        elif len(measured_vols) == 1:
            high_note = "Need at least two measured volatilities to rank."
        opportunities = []
        for decision in decisions:
            if decision.get("stage") != "proposal":
                continue
            payload = decision.get("payload") or {}
            direction = str(payload.get("direction") or "")
            if direction.lower() in {"", "flat", "neutral"}:
                continue
            opportunities.append(
                {
                    "symbol": payload.get("instrument"),
                    "direction": direction,
                    "why": payload.get("rationale"),
                    "whySource": "proposal" if payload.get("rationale") else None,
                    "asOf": decision.get("asOf"),
                    "decisionId": decision.get("decisionId"),
                }
            )
            if len(opportunities) >= 12:
                break
        return {
            "watchlist": rows,
            "opportunities": opportunities,
            "highVolatility": {"rows": high, "note": high_note},
            "news": news,
            "signals": signals,
            "signalsAreDataNotAuthority": True,
        }

    def _events(self, decisions: list[dict[str, Any]], missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for decision in decisions:
            events.append(
                {
                    "id": decision.get("decisionId"),
                    "at": decision.get("createdAt") or decision.get("asOf"),
                    "kind": "decision",
                    "stage": decision.get("stage"),
                    "role": decision.get("role"),
                    "summary": _decision_summary(decision),
                    "source": "market_decisions",
                }
            )
        for mission in missions:
            events.append(
                {
                    "id": mission.get("missionId"),
                    "at": mission.get("updatedAt") or mission.get("createdAt"),
                    "kind": "mission",
                    "stage": (mission.get("metadata") or {}).get("missionKind") if isinstance(mission.get("metadata"), dict) else None,
                    "role": "orchestra",
                    "summary": f"{mission.get('status') or 'UNMEASURED'} · {mission.get('title') or mission.get('missionId')}",
                    "source": "agent_missions",
                }
            )
        events.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
        return events[:_EVENT_LIMIT]

    def _evolution(self, lab_id: str | None, errors: list[str]) -> dict[str, Any]:
        base = {
            "bound": False,
            "labId": lab_id,
            "name": None,
            "status": None,
            "runMode": None,
            "stage": None,
            "rows": [],
            "currentGeneration": unmeasured("no_lab"),
            "hypothesis": None,
            "activeHypothesisCount": 0,
            "activeHypothesisIds": [],
            "bestCandidate": None,
            "qualification": None,
            "bestValidation": unmeasured("no_lab"),
            "canStart": False,
            "owner": "AdaptiveEvolutionaryLearner",
            "liveTrading": "BLOCKED",
        }
        if not lab_id:
            return base
        lab = self._lab(lab_id)
        if lab is None:
            errors.append(f"lab:not_found:{lab_id}")
            base["status"] = None
            return base
        meta = dict(lab.get("metadata") or {})
        learning = lab.get("learning") if isinstance(lab.get("learning"), dict) else None
        summaries: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        candidate_payload: dict[str, Any] = {}
        current = None
        if self.plane is not None and hasattr(self.plane, "get_lab_generations"):
            try:
                gens = self.plane.get_lab_generations(lab_id) or {}
                summaries = list(gens.get("generation_summaries") or [])
                current = gens.get("current_generation")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"generations:{exc}")
        if self.plane is not None and hasattr(self.plane, "get_lab_candidates"):
            try:
                candidate_payload = self.plane.get_lab_candidates(lab_id) or {}
                candidates = list(candidate_payload.get("candidates") or [])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"candidates:{exc}")
        if not candidates:
            raw = lab.get("candidates") or []
            candidates = [c for c in raw if isinstance(c, dict)]
        if learning is None and self.plane is not None and hasattr(self.plane, "get_lab_learning"):
            try:
                learning = (self.plane.get_lab_learning(lab_id) or {}).get("learning")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"learning:{exc}")
        rows = _evolution_rows(candidates, summaries)
        hypothesis = None
        for candidate in candidates:
            text = str(candidate.get("hypothesis") or "").strip()
            if text:
                hypothesis = text
                break
        best_validation = unmeasured("not_recorded")
        for row in rows:
            score = row.get("validationScore") or {}
            if score.get("measurement") == "MEASURED":
                best_validation = score
                break
        active_ids, active_count = _active_hypotheses(self.plane, lab_id, lab=lab, errors=errors)
        best_candidate = _best_candidate_summary(
            candidates=candidates,
            learning=learning,
            payload=candidate_payload,
        )
        qualification = _qualification_projection(learning=learning, lab=lab)
        status = lab.get("status")
        run_mode = lab.get("run_mode") or meta.get("run_mode")
        stage = None
        if learning and learning.get("stage"):
            stage = learning.get("stage")
        elif meta.get("stage"):
            stage = meta.get("stage")
        if current is None and learning and isinstance(learning.get("current_generation"), int):
            current = learning.get("current_generation")
        return {
            "bound": True,
            "labId": lab_id,
            "name": lab.get("name"),
            "status": status,
            "runMode": run_mode,
            "stage": stage,
            "rows": rows[:12],
            "currentGeneration": measured(current) if isinstance(current, int) else unmeasured("not_recorded"),
            "hypothesis": hypothesis,
            "activeHypothesisCount": active_count,
            "activeHypothesisIds": active_ids,
            "bestCandidate": best_candidate,
            "qualification": qualification,
            "bestValidation": best_validation,
            "canStart": str(status or "") in _EVOLVE_STATUSES,
            "owner": "AdaptiveEvolutionaryLearner",
            "paperPnl": unmeasured("learner_does_not_record_paper_pnl"),
            "liveTrading": "BLOCKED",
        }

    def _paper_forward(
        self,
        *,
        portfolio_id: str | None,
        session: dict[str, Any] | None,
        errors: list[str],
    ) -> dict[str, Any]:
        base = {
            "bound": False,
            "portfolioId": portfolio_id,
            "deployments": [],
            "driftTickets": [],
            "liveTrading": "BLOCKED",
            "note": "no_paper_portfolio",
        }
        if not portfolio_id:
            return base
        if self.plane is None or not hasattr(self.plane, "list_paper_deployments"):
            return {
                **base,
                "note": "paper_deployments_unavailable",
            }
        try:
            rows = list(self.plane.list_paper_deployments(limit=30) or [])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"paper_deployments:{exc}")
            return {**base, "note": "paper_deployments_error"}
        paper_session = session.get("paper_session_id") if session else None
        matched: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []
        for dep in rows:
            if not isinstance(dep, dict):
                continue
            meta = dict(dep.get("metadata") or dep.get("metadata_json") or {})
            payload = dict(dep.get("payload") or dep.get("payload_json") or {})
            loop = dict(dep.get("loop") or dep.get("loop_state_json") or {})
            refs = {
                str(meta.get("portfolio_id") or ""),
                str(payload.get("portfolio_id") or ""),
                str(loop.get("portfolio_id") or ""),
            }
            session_refs = {
                str(dep.get("session_id") or ""),
                str(meta.get("session_id") or ""),
                str(payload.get("session_id") or ""),
            }
            linked = portfolio_id in refs or (paper_session and paper_session in session_refs)
            if not linked and not (refs - {""} or (paper_session and session_refs - {""})):
                # Honest: when no linkage fields exist, do not invent ownership.
                continue
            if not linked:
                continue
            drift = loop.get("drift_review") if isinstance(loop.get("drift_review"), dict) else None
            ticket = (drift or {}).get("continualResearch") if drift else None
            matched.append(
                {
                    "deploymentId": dep.get("deployment_id"),
                    "status": dep.get("status"),
                    "mode": dep.get("mode"),
                    "driftStatus": (drift or {}).get("status") if drift else None,
                }
            )
            if isinstance(ticket, dict) and ticket.get("ticketId"):
                tickets.append(
                    {
                        "ticketId": ticket.get("ticketId"),
                        "reason": ticket.get("reason"),
                        "deploymentId": dep.get("deployment_id"),
                        "status": (drift or {}).get("status"),
                        "researchQuestion": ticket.get("researchQuestion"),
                    }
                )
        return {
            "bound": True,
            "portfolioId": portfolio_id,
            "deployments": matched[:20],
            "driftTickets": tickets[:20],
            "liveTrading": "BLOCKED",
            "note": None if matched else "no_linked_paper_deployments",
        }

    def _lab(self, lab_id: str) -> dict[str, Any] | None:
        if self.plane is None:
            return None
        getter = getattr(self.plane, "get_agent_lab", None)
        if not callable(getter):
            return None
        try:
            lab = getter(lab_id)
        except Exception:
            return None
        return lab if isinstance(lab, dict) else None

    def _guardrails(
        self,
        orchestra: dict[str, Any] | None,
        portfolio: dict[str, Any] | None,
        portfolio_view: dict[str, Any],
    ) -> dict[str, Any]:
        mandate = (orchestra or {}).get("mandate") or {}
        settings = (portfolio or {}).get("settings") or {}
        daily = settings.get("daily_loss_limit_pct")
        authority = ((orchestra or {}).get("truth") or {}).get("risk_authority")
        risk_enabled = authority == "risk_guard_deterministic"
        kill = portfolio_view.get("killSwitch")
        return {
            "paperTradingOnly": True,
            "liveTrading": "BLOCKED",
            "riskGuard": "ENABLED" if risk_enabled else "UNAVAILABLE",
            "maxSymbolExposurePct": measured(mandate.get("maxSymbolExposurePct"))
            if mandate.get("maxSymbolExposurePct") is not None
            else unmeasured("no_mandate"),
            "maxGrossExposurePct": measured(mandate.get("maxGrossExposurePct"))
            if mandate.get("maxGrossExposurePct") is not None
            else unmeasured("no_mandate"),
            "perTradeRiskPct": measured(mandate.get("perTradeRiskPct"))
            if mandate.get("perTradeRiskPct") is not None
            else unmeasured("no_mandate"),
            "maxOrdersPerDay": measured(mandate.get("maxOrdersPerDay"))
            if mandate.get("maxOrdersPerDay") is not None
            else unmeasured("no_mandate"),
            "maxDrawdownPct": measured(mandate.get("maxDrawdownPct"))
            if mandate.get("maxDrawdownPct") is not None
            else unmeasured("no_mandate"),
            "dailyLossLimitPct": measured(daily) if daily is not None else unmeasured("not_on_portfolio"),
            "killSwitch": "ARMED" if kill is True else ("DISARMED" if kill is False else "UNMEASURED"),
            "cannotEnableLive": mandate.get("cannotEnableLive") is True if orchestra else None,
            "mandateFingerprint": (orchestra or {}).get("mandateFingerprint"),
        }

    def _runtime(self, errors: list[str]) -> dict[str, Any]:
        try:
            summary = self.trading.summary()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"summary:{exc}")
            summary = {}
        if summary.get("externalized") and not summary.get("jobRuntimeBound"):
            worker = "BLOCKED"
        elif summary.get("fleetBound") is False:
            worker = "UNAVAILABLE"
        elif summary.get("modelAvailable") is False:
            worker = "MODEL_UNAVAILABLE"
        elif summary:
            worker = "READY"
        else:
            worker = "UNMEASURED"
        return {
            "worker": worker,
            "paperEngine": "READY" if self.portfolios is not None else "UNAVAILABLE",
            "model": summary.get("model"),
            "modelAvailable": summary.get("modelAvailable"),
            "externalized": summary.get("externalized"),
            "feedsEnabled": summary.get("feedsEnabled"),
            "feeds": summary.get("feeds"),
            "liveTrading": "BLOCKED",
        }


def _is_paper(row: dict[str, Any]) -> bool:
    if str(row.get("mode") or "PAPER") != "PAPER":
        return False
    if str(row.get("broker_mode") or "local_paper") in {"live", "live_broker"}:
        return False
    return True


def _universe_of(orchestra: dict[str, Any] | None) -> list[str]:
    if not orchestra:
        return []
    universe = (orchestra.get("mandate") or {}).get("universe") or []
    return [str(item).upper() for item in universe if str(item).strip()]


def _mandate_watch(universe: list[str]) -> list[dict[str, str]]:
    return [
        {
            "symbol": symbol,
            "reason": "Listed on the orchestra mandate universe.",
            "source": "mandate",
        }
        for symbol in universe[:_WATCH_LIMIT]
    ]


def _accepts_limit(fn: Callable[..., Any]) -> bool:
    try:
        import inspect

        return "limit" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _safety(
    orchestra: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    session: dict[str, Any] | None,
) -> str:
    if orchestra is None and portfolio is None:
        return "UNMEASURED"
    live = ((orchestra or {}).get("truth") or {}).get("live_trading")
    if orchestra and live != "BLOCKED":
        return "NOT_SAFE"
    authority = ((orchestra or {}).get("truth") or {}).get("risk_authority")
    if orchestra and authority != "risk_guard_deterministic":
        return "NOT_SAFE"
    if portfolio and not _is_paper(portfolio):
        return "NOT_SAFE"
    if portfolio is None:
        return "UNMEASURED"
    if portfolio.get("kill_switch"):
        return "NO_NEW_EXPOSURE"
    if session and session.get("state") == "PAUSED":
        return "PAUSED"
    if session and session.get("state") == "RUNNING" and orchestra:
        return "SAFE"
    return "STANDBY"


def _actions(
    *,
    session: dict[str, Any] | None,
    orchestra_id: str | None,
    portfolio_id: str | None,
    portfolio_mode: str | None,
    open_positions: int,
    lab_id: str | None,
    lab_status: str | None,
    evidence_count: int,
    kill_switch: bool,
) -> dict[str, dict[str, Any]]:
    state = session.get("state") if session else None
    paper = portfolio_mode == "PAPER" and bool(portfolio_id)
    start_enabled = bool(orchestra_id) and paper and state != "RUNNING"
    pause_enabled = state == "RUNNING"
    flatten_enabled = bool(session) and paper and open_positions > 0
    evolve_enabled = bool(lab_id) and str(lab_status or "") in _EVOLVE_STATUSES
    return {
        "start": {
            "enabled": start_enabled,
            "reason": "" if start_enabled else "Requires an orchestra, a paper portfolio, and a session that is not already running",
        },
        "pause": {
            "enabled": pause_enabled,
            "reason": "" if pause_enabled else "Pause is only available while the session is RUNNING",
        },
        "flatten": {
            "enabled": flatten_enabled,
            "reason": "" if flatten_enabled else "Requires a bound paper portfolio with open positions",
        },
        "evolve": {
            "enabled": evolve_enabled,
            "reason": "" if evolve_enabled else "Requires a Research Lab run in CREATED, PAUSED, or FAILED",
        },
        "reviewEvidence": {
            "enabled": evidence_count > 0,
            "reason": "" if evidence_count > 0 else "No decisions, signals, news, or evolution rows are loaded",
        },
        "openPaper": {"enabled": True, "reason": ""},
        "launchMission": {
            "enabled": state == "RUNNING",
            "reason": "" if state == "RUNNING" else "Missions launch only while the research session is RUNNING",
        },
        "killSwitch": {
            "enabled": paper and not kill_switch,
            "reason": "" if paper and not kill_switch else "Paper portfolio required, or the kill switch is already armed",
        },
    }


def _allocated(kpis: dict[str, Any], equity: dict[str, Any]) -> dict[str, Any]:
    if equity.get("measurement") != "MEASURED":
        return unmeasured("equity_unmeasured")
    try:
        eq = float(equity.get("value"))
        cash = float(kpis.get("cash_balance"))
    except (TypeError, ValueError):
        return unmeasured("unparseable")
    if eq <= 0:
        return unmeasured("non_positive_equity")
    return measured(round(eq - cash, 2))


def _allocation_bars(
    cash: dict[str, Any],
    equity: dict[str, Any],
    leverage: dict[str, Any],
    *,
    has_positions: bool,
    marks_ok: bool,
) -> dict[str, Any]:
    if equity.get("measurement") != "MEASURED" or cash.get("measurement") != "MEASURED":
        return {
            "cash": unmeasured("equity_unmeasured"),
            "positions": unmeasured("equity_unmeasured"),
            "risk": unmeasured("equity_unmeasured"),
        }
    try:
        eq = float(equity["value"])
        cash_v = float(cash["value"])
    except (TypeError, ValueError):
        return {
            "cash": unmeasured("unparseable"),
            "positions": unmeasured("unparseable"),
            "risk": unmeasured("unparseable"),
        }
    if eq <= 0:
        return {
            "cash": unmeasured("non_positive_equity"),
            "positions": unmeasured("non_positive_equity"),
            "risk": unmeasured("non_positive_equity"),
        }
    cash_pct = round(max(0.0, cash_v) / eq * 100, 2)
    if has_positions and not marks_ok:
        return {
            "cash": measured(cash_pct),
            "positions": unmeasured("mark_stale_or_missing"),
            "risk": unmeasured("mark_stale_or_missing"),
        }
    positions_pct = round(max(0.0, 100 - cash_pct), 2)
    if not has_positions:
        risk_pct = measured(0, note="no_open_positions")
    elif leverage.get("measurement") == "MEASURED":
        risk_pct = measured(leverage.get("value"), note="gross_leverage")
    else:
        risk_pct = unmeasured("no_leverage")
    return {
        "cash": measured(cash_pct),
        "positions": measured(positions_pct),
        "risk": risk_pct,
    }


def _open_position(pos: dict[str, Any], *, marks_ok: bool) -> dict[str, Any]:
    return {
        "positionId": pos.get("position_id"),
        "symbol": pos.get("symbol"),
        "side": pos.get("side"),
        "size": measured(pos.get("qty")),
        "entry": measured(pos.get("avg_entry_price")),
        "mark": measured(pos.get("mark_price")) if marks_ok else unmeasured("mark_stale_or_missing"),
        "pnl": measured(pos.get("unrealized_pnl")) if marks_ok else unmeasured("mark_stale_or_missing"),
        "pnlPct": measured(pos.get("pnl_pct")) if marks_ok else unmeasured("mark_stale_or_missing"),
        "state": pos.get("status") or "OPEN",
        "paper": True,
    }


def _closed_positions(transactions: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        side = str(tx.get("side") or "").upper()
        result = str(tx.get("result") or "").upper()
        if side not in {"SELL", "COVER"} or result not in _CLOSE_RESULTS:
            continue
        out.append(
            {
                "positionId": tx.get("transaction_id"),
                "symbol": tx.get("symbol"),
                "side": "LONG" if side == "SELL" else "SHORT",
                "size": measured(tx.get("qty")),
                "entry": unmeasured("not_on_close_fill"),
                "mark": measured(tx.get("price")),
                "pnl": unmeasured("not_recorded_on_close_fill"),
                "pnlPct": unmeasured("not_recorded_on_close_fill"),
                "state": result,
                "paper": True,
                "at": tx.get("timestamp"),
            }
        )
        if len(out) >= 20:
            break
    return out


def _why_watching(
    symbol: str,
    item: dict[str, Any],
    decisions: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    reason = str(item.get("reason") or "").strip()
    source = str(item.get("source") or "").strip()
    if reason and source in {"mandate", "operator"}:
        return reason, source
    for signal in signals:
        instruments = [str(s).upper() for s in (signal.get("instruments") or [])]
        if symbol in instruments and str(signal.get("rationale") or "").strip():
            return str(signal.get("rationale")).strip(), "signal"
    for decision in decisions:
        payload = decision.get("payload") or {}
        if str(payload.get("instrument") or "").upper() != symbol:
            continue
        text = str(payload.get("rationale") or payload.get("reason") or "").strip()
        if text:
            return text, "decision"
    if reason:
        return reason, source or "watch"
    return None, None


def _bar_stats(trading: Any, symbol: str, as_of: str) -> dict[str, Any] | None:
    bars_provider = getattr(trading, "bars_provider", None)
    if not callable(bars_provider):
        return None
    try:
        series = bars_provider()(symbol, as_of)
    except Exception:
        return None
    closes: list[float] = []
    for bar in series or []:
        try:
            closes.append(float(getattr(bar, "close")))
        except (AttributeError, TypeError, ValueError):
            continue
    if len(closes) < 2:
        return None
    last = closes[-1]
    prev = closes[-2]
    change = ((last - prev) / prev * 100) if prev else None
    change7 = None
    if len(closes) >= 8 and closes[-8]:
        change7 = (last - closes[-8]) / closes[-8] * 100
    vol = None
    if len(closes) >= 6:
        rets = []
        window = closes[-16:]
        for left, right in zip(window, window[1:]):
            if left:
                rets.append((right - left) / left)
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            var = sum((item - mean) ** 2 for item in rets) / (len(rets) - 1)
            vol = math.sqrt(var)
    return {
        "last": last,
        "change": None if change is None else round(change, 4),
        "change7": None if change7 is None else round(change7, 4),
        "vol": None if vol is None else round(vol, 6),
        "spark": [round(value, 6) for value in closes[-16:]],
    }


def _decision_summary(decision: dict[str, Any]) -> str:
    payload = decision.get("payload") or {}
    stage = str(decision.get("stage") or "")
    if stage == "proposal":
        return f"{payload.get('instrument') or '—'} · {payload.get('direction') or '—'} · {payload.get('rationale') or 'no public rationale'}"
    if stage == "critique":
        return f"{payload.get('verdict') or '—'} · {payload.get('counterargument') or ''}".strip()
    if stage == "risk_decision":
        allowed = "ALLOWED" if payload.get("allowed") else "REFUSED"
        return f"{allowed} · {payload.get('reason') or ''}".strip()
    if stage == "order_intent":
        return f"{payload.get('side') or 'HOLD'} {payload.get('qty') or '—'} {payload.get('instrument') or ''} · {payload.get('status') or 'paper'}".strip()
    if stage == "digest":
        return str(payload.get("status") or payload.get("eventType") or "digest")
    if stage == "post_mortem":
        return str(payload.get("claim") or payload.get("status") or "post-mortem")
    return stage or "decision"


def _evolution_rows(candidates: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if candidates:
        ordered = sorted(candidates, key=lambda item: int(item.get("generation") or 0), reverse=True)
        for candidate in ordered[:12]:
            stage_results = ((candidate.get("metadata") or {}).get("stage_results") or {})
            val = stage_results.get("VAL") or stage_results.get("VALIDATING") or {}
            fitness = val.get("fitness_score") if isinstance(val, dict) else None
            rows.append(
                {
                    "generation": candidate.get("generation"),
                    "variant": candidate.get("strategy_id"),
                    "strategyVersion": candidate.get("strategy_version"),
                    "status": candidate.get("status") or "UNMEASURED",
                    "validationScore": measured(fitness, note="lab_val_fitness")
                    if fitness is not None
                    else unmeasured("not_recorded"),
                    "paperPnl": unmeasured("learner_does_not_record_paper_pnl"),
                }
            )
        return rows
    for summary in reversed(summaries[-12:]):
        if not isinstance(summary, dict):
            continue
        fitness = summary.get("best_train_fitness")
        rows.append(
            {
                "generation": summary.get("generation"),
                "variant": summary.get("best_candidate_ref") or (summary.get("elite_refs") or [None])[0],
                "strategyVersion": None,
                "status": "RECORDED",
                "validationScore": unmeasured("train_fitness_is_not_validation"),
                "trainFitness": measured(fitness) if fitness is not None else unmeasured("not_recorded"),
                "paperPnl": unmeasured("learner_does_not_record_paper_pnl"),
            }
        )
    return rows


_ACTIVE_HYPOTHESIS_STATUSES = frozenset({"PROPOSED", "TESTING", "UNDER_TEST", "FRAGILE"})


def _active_hypotheses(
    plane: Any,
    lab_id: str,
    *,
    lab: dict[str, Any],
    errors: list[str],
) -> tuple[list[str], int]:
    ids: list[str] = []
    if plane is not None and hasattr(plane, "list_lab_hypotheses"):
        try:
            payload = plane.list_lab_hypotheses(lab_id, limit=50) or {}
            for hyp in payload.get("hypotheses") or []:
                if not isinstance(hyp, dict):
                    continue
                if str(hyp.get("status") or "").upper() not in _ACTIVE_HYPOTHESIS_STATUSES:
                    continue
                hid = hyp.get("hypothesis_id")
                if hid:
                    ids.append(str(hid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hypotheses:{exc}")
    if not ids:
        meta = dict(lab.get("metadata") or {})
        hid = meta.get("hypothesis_id")
        if hid:
            ids = [str(hid)]
    # Preserve order, unique
    seen: set[str] = set()
    unique: list[str] = []
    for hid in ids:
        if hid in seen:
            continue
        seen.add(hid)
        unique.append(hid)
    return unique[:20], len(unique)


def _best_candidate_summary(
    *,
    candidates: list[dict[str, Any]],
    learning: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not learning and not payload and not candidates:
        return None
    by_id = {
        str(c.get("candidate_id")): c
        for c in candidates
        if isinstance(c, dict) and c.get("candidate_id")
    }
    best_id = (
        (payload or {}).get("qualified_candidate")
        or (learning or {}).get("qualified_candidate")
        or (payload or {}).get("best_validation_candidate")
        or (learning or {}).get("best_validation_candidate")
        or (payload or {}).get("best_train_candidate")
        or (learning or {}).get("best_train_candidate")
    )
    if not best_id:
        return {
            "present": False,
            "candidateId": None,
            "note": "no_best_candidate_recorded",
            "measurement": "EMPTY",
        }
    cand = by_id.get(str(best_id))
    if cand is None:
        return {
            "present": True,
            "candidateId": str(best_id),
            "role": "ref_only",
            "measurement": "MEASURED",
            "note": "candidate_ref_without_row",
        }
    stages = ((cand.get("metadata") or {}).get("stage_results") or {})
    val = stages.get("VAL") if isinstance(stages.get("VAL"), dict) else {}
    role = "qualified"
    if best_id == ((learning or {}).get("qualified_candidate") or (payload or {}).get("qualified_candidate")):
        role = "qualified"
    elif best_id == (
        (learning or {}).get("best_validation_candidate") or (payload or {}).get("best_validation_candidate")
    ):
        role = "best_validation"
    else:
        role = "best_train"
    return {
        "present": True,
        "candidateId": cand.get("candidate_id"),
        "strategyId": cand.get("strategy_id"),
        "strategyVersion": cand.get("strategy_version"),
        "generation": cand.get("generation"),
        "status": cand.get("status"),
        "proposalMethod": cand.get("proposal_method"),
        "hypothesis": cand.get("hypothesis"),
        "validationFitness": measured(val.get("fitness_score"), note="lab_val_fitness")
        if val.get("fitness_score") is not None
        else unmeasured("not_recorded"),
        "role": role,
        "measurement": "MEASURED",
    }


def _qualification_projection(
    *,
    learning: dict[str, Any] | None,
    lab: dict[str, Any],
) -> dict[str, Any] | None:
    meta = dict((learning or {}).get("metadata") or {})
    lab_meta = dict(lab.get("metadata") or {})
    if not learning and "qualification_required" not in lab_meta and "institutional_qualified" not in lab_meta:
        return None
    source = meta if meta else lab_meta
    status = None
    if source.get("institutional_qualified") is True:
        status = "INSTITUTIONAL_QUALIFIED"
    elif source.get("qualification_required"):
        status = "QUALIFICATION_REQUIRED"
    elif (learning or {}).get("qualified_candidate"):
        status = "LAB_FINALIST"
    elif (learning or {}).get("stage"):
        status = str((learning or {}).get("stage"))
    return {
        "status": status,
        "institutionalQualified": source.get("institutional_qualified"),
        "qualificationRequired": source.get("qualification_required"),
        "readyForShadow": source.get("ready_for_shadow"),
        "labFinalist": source.get("lab_finalist") or (learning or {}).get("qualified_candidate"),
        "qualificationId": source.get("qualification_id"),
        "note": source.get("note"),
        "authority": "Q01–Q11 QualificationAuthority",
        "liveTrading": "BLOCKED",
    }
