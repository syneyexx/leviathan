"""Trading Orchestra service — control plane for trade orchestras, mandates, news and decisions.

The service owns no agents: orchestras and trade agents are Agent Fleet definitions
(``kind=orchestrator role=trade_orchestra`` and ``kind=trading``). This module adds the
trading protocol on top through ``TradingMissionExecutor`` (registered on the fleet for
``AgentDefinitionKind.TRADING``) and keeps trading state (mandate, decisions, news) in
the central SQLite (migration 43).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from Data.modules.agents.fleet_types import AgentDefinitionKind

from .executors import (
    ExecutionContext,
    canonical_role,
    run_news_analyst,
    run_orchestra_round,
    run_postmortem,
    run_signal_analyst,
)
from .model_adapter import TradingModel, UnavailableTradingModel
from .news import FeedFetcher, NewsPoller, make_fetcher
from .store import OrchestraStore, new_id, utc_now
from .types import AutonomyLevel, Mandate, MissionKind, NewsFeed, Readiness

TRADE_ORCHESTRA_ROLE = "trade_orchestra"
NEWS_POLL_CAPABILITY = "market_sim.news.poll"
MANDATE_APPROVAL_CAPABILITY = "market_sim.mandate.loosen"

DEFAULT_MEMBER_ROLES: tuple[str, ...] = (
    "news_analyst",
    "signal_analyst",
    "critic",
    "risk_officer",
    "execution_agent",
    "postmortem_agent",
)

_ROLE_NAMES = {
    "news_analyst": "News Analyst",
    "signal_analyst": "Signal Analyst",
    "critic": "Strategy Critic",
    "risk_officer": "Risk Officer",
    "execution_agent": "Execution Agent",
    "postmortem_agent": "Post-mortem Agent",
    "macro_regime_analyst": "Macro Regime Analyst",
    "strategy_author": "Strategy Author",
    "evaluator": "Independent Evaluator",
}


class TradingOrchestraError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message}


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


class TradingOrchestraService:
    def __init__(
        self,
        *,
        store: OrchestraStore,
        fleet: Any | None = None,
        market_plane: Any | None = None,
        model: TradingModel | None = None,
        job_runtime: Any | None = None,
        approval_service: Any | None = None,
        memory: Any | None = None,
        feed_fetcher: FeedFetcher | None = None,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.fleet = fleet
        self.market_plane = market_plane
        self.model: TradingModel = model or UnavailableTradingModel()
        self.job_runtime = job_runtime
        self.approval_service = approval_service
        self.memory = memory
        self._feed_fetcher = feed_fetcher
        self.enabled = enabled
        self.executor = TradingMissionExecutor(self)

    # ------------------------------------------------------------------ binding

    def bind_fleet(self, fleet: Any | None) -> None:
        self.fleet = fleet
        if fleet is not None and hasattr(fleet, "register_kind_executor"):
            fleet.register_kind_executor(AgentDefinitionKind.TRADING, self.executor)

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def bind_model(self, model: TradingModel | None) -> None:
        self.model = model or UnavailableTradingModel()

    @staticmethod
    def _runners_externalized() -> bool:
        if _truthy_env("LEVIATHAN_WORKERS_EXTERNALIZE_API"):
            return True
        try:
            from Data.modules.workers.settings import load_worker_settings

            ws = load_worker_settings()
            return bool(ws.enabled and ws.externalize_api_runners)
        except Exception:  # noqa: BLE001
            return False

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise TradingOrchestraError(
                "FEATURE_DISABLED",
                "Market sim feature flag is OFF (LEVIATHAN_FEATURE_MARKET_SIM)",
                http_status=503,
            )

    def _require_fleet(self) -> Any:
        if self.fleet is None:
            raise TradingOrchestraError("FLEET_UNAVAILABLE", "Agent Fleet is not bound", http_status=503)
        return self.fleet

    # ------------------------------------------------------------------ orchestras

    @staticmethod
    def is_trade_orchestra(agent: Any) -> bool:
        kind = getattr(getattr(agent, "kind", None), "value", getattr(agent, "kind", None))
        if str(kind) != AgentDefinitionKind.ORCHESTRATOR.value:
            return False
        if canonical_role(getattr(agent, "role", "")) == TRADE_ORCHESTRA_ROLE:
            return True
        return bool((getattr(agent, "metadata", None) or {}).get("tradeOrchestra"))

    @staticmethod
    def mandate_of(agent: Any) -> Mandate:
        raw = (getattr(agent, "metadata", None) or {}).get("mandate")
        try:
            return Mandate.from_dict(raw if isinstance(raw, dict) else None)
        except ValueError:
            return Mandate()

    def _get_orchestra_agent(self, orchestra_id: str) -> Any:
        fleet = self._require_fleet()
        try:
            agent = fleet.get_agent(orchestra_id)
        except Exception as exc:  # noqa: BLE001 — fleet raises its own 404
            raise TradingOrchestraError("ORCHESTRA_NOT_FOUND", f"Unknown orchestra: {orchestra_id}", http_status=404) from exc
        if not self.is_trade_orchestra(agent):
            raise TradingOrchestraError("NOT_A_TRADE_ORCHESTRA", f"{orchestra_id} is not a trade orchestra", http_status=404)
        return agent

    def _members(self, agent: Any) -> list[Any]:
        fleet = self._require_fleet()
        members: list[Any] = []
        for mid in (agent.orchestrator.member_agent_ids if agent.orchestrator else []):
            try:
                members.append(fleet.get_agent(mid))
            except Exception:  # noqa: BLE001
                continue
        return members

    def _orchestra_view(self, agent: Any, *, include_members: bool = True) -> dict[str, Any]:
        mandate = self.mandate_of(agent)
        meta = dict(agent.metadata or {})
        stats = self.store.decision_stats(agent.agent_id)
        readiness = meta.get("readiness") or {"state": Readiness.UNMEASURED.value, "reason": "no sealed evaluation recorded"}
        view: dict[str, Any] = {
            "orchestraId": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "enabled": agent.enabled,
            "archived": agent.archived,
            "health": agent.health.value,
            "role": agent.role,
            "mandate": mandate.public_dict(),
            "mandateFingerprint": mandate.fingerprint(),
            "readiness": readiness,
            "autonomyLevel": mandate.autonomy_level.value,
            "decisionStats": stats,
            "lastMissionId": agent.last_mission_id,
            "lastRunAt": agent.last_run_at,
            "createdAt": agent.created_at,
            "updatedAt": agent.updated_at,
            "memberAgentIds": list(agent.orchestrator.member_agent_ids) if agent.orchestrator else [],
            "truth": {
                "paper_only": True,
                "live_trading": "BLOCKED",
                "risk_authority": "risk_guard_deterministic",
                "decisions_append_only": True,
                "pnl_is_paper_and_unrealised_until_fill_records_exist": True,
            },
        }
        if include_members:
            view["members"] = [
                {
                    "agentId": m.agent_id,
                    "name": m.name,
                    "kind": m.kind.value,
                    "role": m.role,
                    "canonicalRole": canonical_role(m.role),
                    "enabled": m.enabled,
                    "health": m.health.value,
                }
                for m in self._members(agent)
            ]
        return view

    def list_orchestras(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        self._require_enabled()
        fleet = self._require_fleet()
        agents = fleet.list_agents(include_archived=include_archived, kind=AgentDefinitionKind.ORCHESTRATOR.value)
        return [self._orchestra_view(a, include_members=False) for a in agents if self.is_trade_orchestra(a)]

    def get_orchestra(self, orchestra_id: str) -> dict[str, Any]:
        self._require_enabled()
        return self._orchestra_view(self._get_orchestra_agent(orchestra_id))

    def create_orchestra(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        fleet = self._require_fleet()
        name = str(payload.get("name") or "").strip()
        if not name:
            raise TradingOrchestraError("INVALID_NAME", "name is required")
        try:
            mandate = Mandate.from_dict(payload.get("mandate") or {})
        except ValueError as exc:
            raise TradingOrchestraError("INVALID_MANDATE", str(exc)) from exc
        member_ids = [str(m) for m in (payload.get("memberAgentIds") or []) if str(m).strip()]
        seed_roles = payload.get("seedRoles")
        if seed_roles is None:
            seed_roles = list(DEFAULT_MEMBER_ROLES) if not member_ids else []
        for member_id in member_ids:
            member = fleet.get_agent(member_id)
            if member.kind != AgentDefinitionKind.TRADING:
                raise TradingOrchestraError(
                    "TRADING_MEMBER_REQUIRED", f"member {member_id} is {member.kind.value}, expected trading", http_status=422
                )
        created_members: list[str] = []
        for role in seed_roles:
            role_key = canonical_role(str(role))
            if role_key not in _ROLE_NAMES:
                raise TradingOrchestraError("UNKNOWN_TRADING_ROLE", f"unknown trading role: {role}")
            member = fleet.create_agent(
                {
                    "name": f"{name} · {_ROLE_NAMES[role_key]}",
                    "kind": AgentDefinitionKind.TRADING.value,
                    "role": role_key,
                    "description": f"{_ROLE_NAMES[role_key]} of trade orchestra {name}",
                    "tags": ["trading", "market_sim", role_key],
                    "capabilities": [f"market_sim.{role_key}"],
                    "metadata": {"trading_role": True, "orchestraName": name},
                }
            )
            created_members.append(member.agent_id)
        all_members = member_ids + created_members
        now = utc_now()
        orchestra = fleet.create_agent(
            {
                "name": name,
                "kind": AgentDefinitionKind.ORCHESTRATOR.value,
                "role": TRADE_ORCHESTRA_ROLE,
                "description": str(payload.get("description") or "Trade orchestra (paper only)"),
                "tags": ["trading", "market_sim", "orchestra"],
                "capabilities": ["market_sim.orchestrate"],
                "orchestrator": {
                    "memberAgentIds": all_members,
                    "strategy": "sequential",
                    "maxDelegationDepth": 2,
                },
                "metadata": {
                    "tradeOrchestra": True,
                    "mandate": mandate.public_dict(),
                    "mandateFingerprint": mandate.fingerprint(),
                    "mandateHistory": [{"fingerprint": mandate.fingerprint(), "at": now, "reason": "created"}],
                    "readiness": {"state": Readiness.UNMEASURED.value, "reason": "no sealed evaluation recorded"},
                    "paperOnly": True,
                    "cannotEnableLive": True,
                },
            }
        )
        # Back-reference so member missions can resolve their mandate without scanning.
        for member_id in created_members:
            try:
                fleet.update_agent(member_id, {"metadata": {"trading_role": True, "orchestraId": orchestra.agent_id, "orchestraName": name}})
            except Exception:  # noqa: BLE001
                continue
        return self._orchestra_view(orchestra)

    def update_mandate(self, orchestra_id: str, payload: dict[str, Any], *, approval_id: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        fleet = self._require_fleet()
        agent = self._get_orchestra_agent(orchestra_id)
        current = self.mandate_of(agent)
        merged = {**current.public_dict(), **{k: v for k, v in dict(payload or {}).items() if v is not None}}
        try:
            proposed = Mandate.from_dict(merged)
        except ValueError as exc:
            raise TradingOrchestraError("INVALID_MANDATE", str(exc)) from exc
        if proposed.is_loosening_of(current):
            if not approval_id:
                raise TradingOrchestraError(
                    "APPROVAL_REQUIRED",
                    "Loosening a mandate requires an approval (capability market_sim.mandate.loosen)",
                    http_status=403,
                )
            if not self._approval_ok(approval_id):
                raise TradingOrchestraError("APPROVAL_INVALID", "approval is missing, denied or does not match", http_status=403)
        meta = dict(agent.metadata or {})
        history = list(meta.get("mandateHistory") or [])
        history.append(
            {
                "fingerprint": proposed.fingerprint(),
                "previous": current.fingerprint(),
                "at": utc_now(),
                "loosening": bool(proposed.is_loosening_of(current)),
                "approvalId": approval_id,
            }
        )
        meta.update({"mandate": proposed.public_dict(), "mandateFingerprint": proposed.fingerprint(), "mandateHistory": history[-50:]})
        updated = fleet.update_agent(orchestra_id, {"metadata": meta})
        return self._orchestra_view(updated)

    def _approval_ok(self, approval_id: str) -> bool:
        if self.approval_service is None:
            return False
        try:
            from Data.modules.execution.gateway import SideEffect

            return bool(
                self.approval_service.is_approved(
                    approval_id,
                    capability_id=MANDATE_APPROVAL_CAPABILITY,
                    side_effects=(SideEffect.WRITE,),
                )
            )
        except Exception:  # noqa: BLE001
            return False

    def set_autonomy(self, orchestra_id: str, level: str, *, approval_id: str | None = None) -> dict[str, Any]:
        try:
            parsed = AutonomyLevel.parse(level)
        except ValueError as exc:
            raise TradingOrchestraError("INVALID_AUTONOMY", str(exc)) from exc
        return self.update_mandate(orchestra_id, {"autonomyLevel": parsed.value}, approval_id=approval_id)

    # ------------------------------------------------------------------ missions

    def launch_mission(
        self,
        orchestra_id: str,
        *,
        kind: str,
        as_of: str | None = None,
        request: str | None = None,
        priority: str = "med",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self._require_enabled()
        fleet = self._require_fleet()
        agent = self._get_orchestra_agent(orchestra_id)
        try:
            mission_kind = MissionKind.parse(kind)
        except ValueError as exc:
            raise TradingOrchestraError("INVALID_MISSION_KIND", str(exc)) from exc
        text = (request or "").strip() or f"trading:{mission_kind.value} as_of={as_of or 'now'}"
        try:
            mission = fleet.launch_mission(
                agent_id=agent.agent_id,
                request=text,
                title=f"{mission_kind.value} · {agent.name}",
                priority=priority,
                dry_run=dry_run,
                metadata={"missionKind": mission_kind.value, "asOf": as_of, "orchestraId": agent.agent_id, "domain": "market_sim"},
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "MISSION_LAUNCH_FAILED")
            status = int(getattr(exc, "http_status", 400) or 400)
            raise TradingOrchestraError(str(code), str(getattr(exc, "message", exc)), http_status=status) from exc
        return mission.public_dict()

    def list_missions(self, orchestra_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_enabled()
        fleet = self._require_fleet()
        agent = self._get_orchestra_agent(orchestra_id)
        mission_store = getattr(fleet, "store", None)
        if mission_store is None or not hasattr(mission_store, "list_missions"):
            return []
        return [m.public_dict() for m in mission_store.list_missions(agent_id=agent.agent_id, limit=limit)]

    # ------------------------------------------------------------------ decisions

    def list_decisions(
        self,
        *,
        orchestra_id: str | None = None,
        mission_id: str | None = None,
        stage: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        return [d.public_dict() for d in self.store.list_decisions(orchestra_id=orchestra_id, mission_id=mission_id, stage=stage, limit=limit)]

    # ------------------------------------------------------------------ news

    def list_feeds(self) -> list[dict[str, Any]]:
        self._require_enabled()
        return [f.public_dict() for f in self.store.list_feeds()]

    def create_feed(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        url = str(payload.get("url") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise TradingOrchestraError("INVALID_FEED_URL", "url must be http(s)")
        if not name:
            raise TradingOrchestraError("INVALID_FEED_NAME", "name is required")
        existing = self.store.get_feed_by_url(url)
        if existing is not None:
            raise TradingOrchestraError("FEED_EXISTS", f"feed already registered: {existing.feed_id}", http_status=409)
        kind = str(payload.get("kind") or "rss").lower()
        if kind not in {"rss", "atom", "http_json"}:
            raise TradingOrchestraError("INVALID_FEED_KIND", "kind must be rss | atom | http_json")
        license_state = str(payload.get("licenseState") or "UNKNOWN").upper()
        if license_state not in {"UNKNOWN", "DECLARED_FREE", "DECLARED_RESTRICTED"}:
            raise TradingOrchestraError("INVALID_LICENSE_STATE", "licenseState must be UNKNOWN | DECLARED_FREE | DECLARED_RESTRICTED")
        now = utc_now()
        feed = NewsFeed(
            feed_id=new_id("feed"),
            name=name,
            url=url,
            kind=kind,
            enabled=bool(payload.get("enabled", True)),
            declared_latency_seconds=max(0, int(payload.get("declaredLatencySeconds") or 0)),
            license_state=license_state,
            symbols_hint=[str(s).upper() for s in (payload.get("symbolsHint") or []) if str(s).strip()],
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_feed(feed)
        return feed.public_dict()

    def update_feed(self, feed_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        feed = self.store.get_feed(feed_id)
        if feed is None:
            raise TradingOrchestraError("FEED_NOT_FOUND", feed_id, http_status=404)
        if "name" in payload and payload["name"]:
            feed.name = str(payload["name"]).strip()
        if "enabled" in payload and payload["enabled"] is not None:
            feed.enabled = bool(payload["enabled"])
        if "declaredLatencySeconds" in payload and payload["declaredLatencySeconds"] is not None:
            feed.declared_latency_seconds = max(0, int(payload["declaredLatencySeconds"]))
        if "licenseState" in payload and payload["licenseState"]:
            feed.license_state = str(payload["licenseState"]).upper()
        if "symbolsHint" in payload and payload["symbolsHint"] is not None:
            feed.symbols_hint = [str(s).upper() for s in payload["symbolsHint"] if str(s).strip()]
        feed.updated_at = utc_now()
        self.store.upsert_feed(feed)
        return feed.public_dict()

    def delete_feed(self, feed_id: str) -> dict[str, Any]:
        self._require_enabled()
        if not self.store.delete_feed(feed_id):
            raise TradingOrchestraError("FEED_NOT_FOUND", feed_id, http_status=404)
        return {"feedId": feed_id, "deleted": True}

    def list_news(self, *, as_of: str | None = None, feed_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_enabled()
        return [i.public_dict() for i in self.store.list_items(as_of=as_of, feed_id=feed_id, limit=limit)]

    def list_signals(self, *, as_of: str | None = None, instrument: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_enabled()
        return [s.public_dict() for s in self.store.list_signals(as_of=as_of, instrument=instrument, limit=limit)]

    def request_poll(self, *, feed_id: str | None = None, requested_by: str = "api") -> dict[str, Any]:
        """Poll feeds. Externalized → durable ``market_sim.news.poll`` job on the market_sim
        pool (fetch via provider_io). Inline → only when a fetcher is bound; never raw HTTP
        from the Control Plane."""
        self._require_enabled()
        if self._runners_externalized() and self.job_runtime is not None:
            job = self.job_runtime.enqueue(
                capability_id=NEWS_POLL_CAPABILITY,
                arguments={"feed_id": feed_id} if feed_id else {},
                requested_by=requested_by,
                idempotency_key=f"market_sim:news:poll:{feed_id or 'all'}:{utc_now()[:16]}",
                domain="market_sim",
                domain_entity_type="news_feed",
                domain_entity_id=feed_id or "all",
                worker_pool="market_sim",
                latency_class="background",
                metadata={"feed_id": feed_id},
            )
            return {"status": "ENQUEUED", "jobId": job.job_id, "executedVia": "worker"}
        result = self.poll_now(feed_id=feed_id)
        result["executedVia"] = "control_plane_inline" if self._feed_fetcher is not None else "none"
        return result

    def poll_now(self, *, feed_id: str | None = None, job_runtime: Any | None = None) -> dict[str, Any]:
        """Execute a poll in the current process (worker entrypoint or bound inline fetcher)."""
        fetcher = self._feed_fetcher
        if fetcher is None and job_runtime is not None:
            fetcher = make_fetcher(job_runtime)
        poller = NewsPoller(self.store, fetcher)
        if feed_id:
            feed = self.store.get_feed(feed_id)
            if feed is None:
                raise TradingOrchestraError("FEED_NOT_FOUND", feed_id, http_status=404)
            results = [poller.poll_feed(feed)]
        else:
            results = poller.poll_all()
        status = "OK"
        if not results:
            status = "NO_FEEDS"
        elif all(r.get("status") == "UNAVAILABLE" for r in results):
            status = "UNAVAILABLE"
        elif any(r.get("status") == "FAILED" for r in results):
            status = "PARTIAL"
        return {"status": status, "feeds": results, "inserted": sum(int(r.get("inserted") or 0) for r in results)}

    # ------------------------------------------------------------------ summary

    def summary(self) -> dict[str, Any]:
        orchestras = self.list_orchestras() if (self.enabled and self.fleet is not None) else []
        feeds = self.store.list_feeds() if self.enabled else []
        return {
            "enabled": self.enabled,
            "fleetBound": self.fleet is not None,
            "model": getattr(self.model, "name", type(self.model).__name__),
            "modelAvailable": not isinstance(self.model, UnavailableTradingModel),
            "orchestras": len(orchestras),
            "feeds": len(feeds),
            "feedsEnabled": sum(1 for f in feeds if f.enabled),
            "newsItems": self.store.count_items() if self.enabled else 0,
            "externalized": self._runners_externalized(),
            "jobRuntimeBound": self.job_runtime is not None,
            "truth": {"paper_only": True, "live_trading": "BLOCKED", "risk_authority": "risk_guard_deterministic"},
        }

    # ------------------------------------------------------------------ data providers

    def _source_for(self, instrument: str) -> Any | None:
        plane = self.market_plane
        data = getattr(plane, "data", None)
        if data is None:
            return None
        try:
            sources = data.list_sources(limit=1000)
        except Exception:  # noqa: BLE001
            return None
        wanted = instrument.upper()
        ready = [s for s in sources if str(getattr(s, "symbol", "")).upper() == wanted]
        if not ready:
            return None
        ready.sort(key=lambda s: (str(getattr(s, "status", "")) != "ready", str(getattr(s, "timeframe", ""))))
        return ready[0]

    def bars_provider(self) -> Callable[[str, str], list[Any]]:
        cache: dict[tuple[str, str], list[Any]] = {}

        def _bars(symbol: str, as_of: str) -> list[Any]:
            key = (symbol.upper(), as_of)
            if key in cache:
                return cache[key]
            source = self._source_for(symbol)
            bars: list[Any] = []
            if source is not None:
                try:
                    from Data.modules.market_sim.ohlcv import load_ohlcv

                    path = Path(self.market_plane.data.absolute_path_for(source))
                    bars = load_ohlcv(path, end_ts=as_of)[-400:]
                except Exception:  # noqa: BLE001 — UNMEASURED features, never fabricated bars
                    bars = []
            cache[key] = bars
            return bars

        return _bars

    def price_provider(self, bars: Callable[[str, str], list[Any]]) -> Callable[[str, str], float | None]:
        def _price(symbol: str, as_of: str) -> float | None:
            series = bars(symbol, as_of)
            if not series:
                return None
            try:
                return float(series[-1].close)
            except (AttributeError, TypeError, ValueError):
                return None

        return _price

    def memory_writer(self, *, orchestra_id: str, mission_id: str | None) -> Callable[[dict[str, Any]], str | None] | None:
        if self.memory is None:
            return None

        def _write(lesson: dict[str, Any]) -> str | None:
            from Data.modules.memory.types import MemoryKind

            record = self.memory.create(
                content=str(lesson.get("claim") or "")[:2000],
                kind=MemoryKind.NOTE,
                source="trading_postmortem",
                trust="derived",
                tags=["trading", "lesson", "agent_proposed"],
                metadata={
                    "trust_state": "agent_proposed",
                    "orchestraId": orchestra_id,
                    "missionId": mission_id,
                    "evidenceRefs": list(lesson.get("evidenceRefs") or []),
                    "appliesTo": list(lesson.get("appliesTo") or []),
                    "confidence": lesson.get("confidence"),
                },
            )
            return getattr(record, "memory_id", None) or (record.get("memory_id") if isinstance(record, dict) else None)

        return _write


class TradingMissionExecutor:
    """Fleet kind executor for ``AgentDefinitionKind.TRADING`` + trade orchestras."""

    name = "trading_orchestra"

    def __init__(self, service: TradingOrchestraService) -> None:
        self.service = service

    def owns_orchestrator(self, agent: Any) -> bool:
        return TradingOrchestraService.is_trade_orchestra(agent)

    @staticmethod
    def _mission_kind(mission: Any, agent: Any) -> MissionKind:
        meta = getattr(mission, "metadata", None) or {}
        raw = meta.get("missionKind")
        if not raw:
            text = str(getattr(mission, "request", "") or "")
            if text.startswith("trading:"):
                raw = text.split()[0][len("trading:"):]
        if raw:
            try:
                return MissionKind.parse(raw)
            except ValueError:
                pass
        role = canonical_role(getattr(agent, "role", ""))
        if role == "news_analyst":
            return MissionKind.NEWS_DIGEST
        if role == "postmortem_agent":
            return MissionKind.POST_MORTEM
        return MissionKind.DELIBERATION_ROUND

    def _resolve_orchestra(self, agent: Any, fleet: Any) -> Any | None:
        if self.service.is_trade_orchestra(agent):
            return agent
        orch_id = (getattr(agent, "metadata", None) or {}).get("orchestraId")
        if orch_id and fleet is not None:
            try:
                candidate = fleet.get_agent(orch_id)
                if self.service.is_trade_orchestra(candidate):
                    return candidate
            except Exception:  # noqa: BLE001
                pass
        if fleet is not None:
            for other in fleet.list_agents(kind=AgentDefinitionKind.ORCHESTRATOR.value):
                if self.service.is_trade_orchestra(other) and other.orchestrator and agent.agent_id in other.orchestrator.member_agent_ids:
                    return other
        return None

    def plan(self, agent: Any, request: str) -> dict[str, Any]:
        kind = self._mission_kind(type("M", (), {"metadata": {}, "request": request})(), agent)
        orchestra = self._resolve_orchestra(agent, self.service.fleet)
        mandate = self.service.mandate_of(orchestra) if orchestra else Mandate()
        return {
            "missionKind": kind.value,
            "orchestraId": orchestra.agent_id if orchestra else None,
            "mandateFingerprint": mandate.fingerprint(),
            "universe": list(mandate.universe),
            "steps": ["news_digest", "proposals", "critique", "risk_decision(deterministic)", "order_intent(paper)"]
            if kind == MissionKind.DELIBERATION_ROUND
            else [kind.value],
            "modelAvailable": not isinstance(self.service.model, UnavailableTradingModel),
            "liveTrading": "BLOCKED",
        }

    def execute(self, mission: Any, agent: Any, *, fleet: Any = None) -> dict[str, Any]:
        service = self.service
        fleet = fleet or service.fleet
        if not service.enabled:
            return {"status": "DISABLED", "error": "market_sim feature flag is OFF"}
        kind = self._mission_kind(mission, agent)
        orchestra = self._resolve_orchestra(agent, fleet)
        mandate = service.mandate_of(orchestra) if orchestra is not None else Mandate()
        as_of = str((mission.metadata or {}).get("asOf") or "").strip() or utc_now()
        orchestra_id = orchestra.agent_id if orchestra is not None else agent.agent_id
        bars = service.bars_provider()
        ctx = ExecutionContext(
            orchestra_id=orchestra_id,
            mission_id=mission.mission_id,
            mandate=mandate,
            as_of=as_of,
            mission_kind=kind,
            model=service.model,
            store=service.store,
            bars_provider=bars,
            memory_writer=service.memory_writer(orchestra_id=orchestra_id, mission_id=mission.mission_id),
        )
        base = {
            "missionKind": kind.value,
            "orchestraId": orchestra_id,
            "asOf": as_of,
            "mandateFingerprint": mandate.fingerprint(),
            "liveTrading": "BLOCKED",
        }
        if orchestra is not None and agent.agent_id == orchestra.agent_id:
            members = service._members(orchestra)
            if kind == MissionKind.DELIBERATION_ROUND:
                if not mandate.universe:
                    return {**base, "status": "REFUSED", "error": "mandate universe is empty; nothing to deliberate"}
                round_result = run_orchestra_round(ctx, members=members, price_provider=service.price_provider(bars))
                return {**base, "status": "COMPLETED", **round_result}
            if kind == MissionKind.NEWS_DIGEST:
                analysts = [m for m in members if m.enabled and canonical_role(m.role) == "news_analyst"]
                if not analysts:
                    return {**base, "status": "REFUSED", "error": "orchestra has no enabled news_analyst"}
                records = []
                for analyst in analysts:
                    records.extend(run_news_analyst(ctx, analyst, max_items=20))
                return {**base, "status": "COMPLETED", "decisions": [r.decision_id for r in records], "modelCalls": ctx.model_calls}
            if kind == MissionKind.POST_MORTEM:
                reviewers = [m for m in members if m.enabled and canonical_role(m.role) == "postmortem_agent"]
                if not reviewers:
                    return {**base, "status": "REFUSED", "error": "orchestra has no enabled postmortem_agent"}
                recent = [d for d in service.store.list_decisions(orchestra_id=orchestra_id, limit=200) if d.stage != "post_mortem"]
                record = run_postmortem(ctx, reviewers[0], recent=recent)
                status = "COMPLETED" if record.payload.get("status") not in {"FAILED", "UNAVAILABLE"} else str(record.payload.get("status"))
                return {**base, "status": status, "decisionId": record.decision_id, "lesson": record.payload, "modelCalls": ctx.model_calls,
                        "error": record.payload.get("error")}
            return {**base, "status": "REFUSED", "error": f"unsupported mission kind {kind.value}"}

        # Single trading agent mission (outside an orchestra round).
        role = canonical_role(agent.role)
        if role == "news_analyst":
            records = run_news_analyst(ctx, agent, max_items=20)
            statuses = {str(r.payload.get("status") or "") for r in records}
            status = "UNAVAILABLE" if statuses == {"UNAVAILABLE"} else "COMPLETED"
            return {**base, "status": status, "decisions": [r.decision_id for r in records], "modelCalls": ctx.model_calls,
                    "error": "model unavailable" if status == "UNAVAILABLE" else None}
        if role == "signal_analyst":
            if not mandate.universe:
                return {**base, "status": "REFUSED", "error": "no mandate universe (agent is not in a trade orchestra)"}
            signals = service.store.list_signals(as_of=as_of, limit=200)
            records = [run_signal_analyst(ctx, agent, instrument=i, news=signals) for i in mandate.universe]
            return {**base, "status": "COMPLETED", "decisions": [r.decision_id for r in records], "modelCalls": ctx.model_calls}
        if role == "postmortem_agent":
            recent = [d for d in service.store.list_decisions(orchestra_id=orchestra_id, limit=200) if d.stage != "post_mortem"]
            record = run_postmortem(ctx, agent, recent=recent)
            return {**base, "status": "COMPLETED" if record.payload.get("status") not in {"FAILED", "UNAVAILABLE"} else str(record.payload["status"]),
                    "decisionId": record.decision_id, "lesson": record.payload, "error": record.payload.get("error")}
        return {
            **base,
            "status": "REFUSED",
            "error": f"role {role or 'unknown'} only acts inside a trade orchestra deliberation round (proposal → critique → risk → intent)",
        }
