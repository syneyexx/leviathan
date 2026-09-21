"""Facade used by PluginManager, Chat, Work Runtime and HTTP routes."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Callable

from .collaboration import CollaborationSession, MissionState
from .contracts import CanonicalCapability, RequirementPlan, RoutingDecision
from .health import health_from_plugin, metrics_by_capability, remember_failure
from .normalize import adapt_package
from .orchestration import apply_provider_fallback, compose_mission, verification_result
from .planner import plan_requirements
from .policy import apply_runtime_health, filter_candidates
from .ranking import rank_capabilities, cover_kinds
from .registry import CapabilityRegistry, get_registry
from .skills import retrieve_skills, skills_as_context_items
from .store import cache_get, cache_put, cache_invalidate, ensure_capability_schema, save_mission

try:
    from plugin_knowledge_index import search_plugin_knowledge
except Exception:  # pragma: no cover - optional during isolated unit tests
    search_plugin_knowledge = None  # type: ignore[assignment]


class CapabilityIntelligence:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db
        if db is not None:
            ensure_capability_schema(db)
        self.registry: CapabilityRegistry = get_registry(db)

    def on_plugin_imported(self, plugin: dict[str, Any], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result = self.registry.refresh_plugin(plugin, tools=tools)
        return result.to_dict()

    def on_mcp_expanded(self, plugin: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.registry.ingest_mcp_tools(plugin, tools)
        if self.db is not None:
            cache_invalidate(self.db, "route:")
        return result.to_dict()

    def on_plugin_removed(self, plugin_id: str) -> None:
        self.registry.drop_plugin(plugin_id)

    def plan(self, text: str) -> RequirementPlan:
        return plan_requirements(text)

    def _state_hash(self, extra: str = "") -> str:
        snap = self.registry.snapshot()
        raw = f"{snap}|{extra}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def route(
        self,
        query: str,
        *,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
        tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
        permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
        known_dead: set[str] | None = None,
        limit: int = 8,
    ) -> tuple[RequirementPlan, RoutingDecision]:
        plan = plan_requirements(query)
        cache_key = f"route:{hashlib.sha256(query.encode('utf-8')).hexdigest()[:16]}"
        state_hash = self._state_hash(str(sorted(known_dead or [])))
        if self.db is not None:
            cached = cache_get(self.db, cache_key, state_hash)
            if cached and not plan.explicit_providers:
                cached_decision = RoutingDecision(
                    considered=int(cached.get("considered") or 0),
                    model_called=False,
                    reused_cache=True,
                    explicit_honored=bool(cached.get("explicit_honored")),
                    explanation="cached_routing",
                )
                # Reconstruct selected from registry ids.
                by_id = {item.canonical_id: item for item in self.registry.all()}
                from .contracts import RankedCandidate

                for raw in cached.get("selected") or []:
                    cap = by_id.get(str(raw.get("canonical_id") or ""))
                    if cap:
                        cached_decision.selected.append(
                            RankedCandidate(capability=cap, score=float(raw.get("score") or 0), eligible=True, reasons=list(raw.get("reasons") or []))
                        )
                if cached_decision.selected:
                    return plan, cached_decision
        records: list[CanonicalCapability] = []
        for record in self.registry.all():
            plugin = (plugins_by_id or {}).get(record.plugin_id or "")
            if plugin:
                apply_runtime_health(record, plugin)
            else:
                record.health = health_from_plugin(plugin) if plugin is not None else record.health
            records.append(record)
        decision = rank_capabilities(
            query,
            records,
            plan=plan,
            metrics_by_id=metrics_by_capability(self.db) if self.db is not None else {},
            known_dead=known_dead,
            limit=max(limit * 3, 12),
        )
        eligible, rejected = filter_candidates(
            decision.selected,
            plugins_by_id=plugins_by_id,
            tools_by_key=tools_by_key,
            settings=settings,
            permission_ok=permission_ok,
            known_dead=known_dead,
        )
        decision.selected = cover_kinds(eligible, limit=limit)
        decision.rejected = rejected + decision.rejected
        if plan.explicit_providers:
            decision.explicit_honored = any("exact_reference" in item.reasons for item in decision.selected)
            decision.model_called = False
            decision.explanation = "explicit_provider_honored"
        if self.db is not None:
            cache_put(self.db, cache_key, state_hash, decision.to_dict())
        return plan, decision

    def retrieve_skill_context(
        self,
        query: str,
        *,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        skills = [item for item in self.registry.all() if item.kind == "skill"]
        if plugins_by_id is not None:
            skills = [
                item
                for item in skills
                if not item.plugin_id
                or (
                    (plugins_by_id.get(item.plugin_id) or {}).get("enabled")
                    and (plugins_by_id.get(item.plugin_id) or {}).get("status") in {None, "ready", ""}
                )
            ]
        roots = {
            plugin_id: str(plugin.get("local_path") or "")
            for plugin_id, plugin in (plugins_by_id or {}).items()
        }
        hits = []
        if search_plugin_knowledge is not None and self.db is not None:
            try:
                hits = search_plugin_knowledge(self.db, query)
            except Exception:
                hits = []
        retrieved = retrieve_skills(query, skills, plugin_roots=roots, knowledge_hits=hits)
        return retrieved, skills_as_context_items(retrieved)

    def compose(
        self,
        query: str,
        *,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
        tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
        permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
        known_dead: set[str] | None = None,
        mission_id: str | None = None,
        plan: RequirementPlan | None = None,
        decision: RoutingDecision | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        if plan is None or decision is None:
            plan, decision = self.route(
                query,
                plugins_by_id=plugins_by_id,
                tools_by_key=tools_by_key,
                settings=settings,
                permission_ok=permission_ok,
                known_dead=known_dead,
            )
        composed = compose_mission(
            query,
            self.registry.all(),
            plan=plan,
            eligible=decision.selected,
            mission_id=mission_id or str(uuid.uuid4()),
        )
        composed["plan"] = plan.to_dict()
        composed["routing"]["rejected"] = [item.to_dict() for item in decision.rejected[:12]]
        composed["model_called"] = False
        composed["composed"] = True
        mission_key = str((composed.get("mission") or {}).get("mission_id") or "")
        if persist and self.db is not None and mission_key:
            save_mission(
                self.db,
                mission_key,
                composed,
                str((composed.get("mission") or {}).get("status") or "active"),
            )
        return composed

    def observe(
        self,
        query: str,
        *,
        persist: bool = True,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
        tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
        permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
        known_dead: set[str] | None = None,
        mission_id: str | None = None,
        limit: int = 16,
    ) -> dict[str, Any]:
        """Route every request. Compose and persist only when the task is not a simple fast path."""
        plan, decision = self.route(
            query,
            plugins_by_id=plugins_by_id,
            tools_by_key=tools_by_key,
            settings=settings,
            permission_ok=permission_ok,
            known_dead=known_dead,
            limit=limit,
        )
        payload: dict[str, Any] = {
            "plan": plan.to_dict(),
            "routing": decision.to_dict(),
            "model_called": False,
            "composed": False,
        }
        if plan.simple:
            return payload
        composed = self.compose(
            query,
            plan=plan,
            decision=decision,
            persist=persist,
            mission_id=mission_id,
        )
        payload.update(composed)
        payload["composed"] = True
        payload["model_called"] = False
        return payload

    def open_mission(self, payload: dict[str, Any]) -> CollaborationSession:
        mission = MissionState.from_mapping(payload.get("mission") or payload)
        return CollaborationSession(mission, db=self.db)

    def fallback(self, session: CollaborationSession, failed_provider: str, alternatives: list[Any]) -> Any:
        remember_failure(
            self.db,
            mission_id=session.mission.mission_id,
            provider_id=failed_provider,
            capability_id=failed_provider,
            kind="provider_offline",
        )
        return apply_provider_fallback(session.mission, failed_provider=failed_provider, alternatives=alternatives)

    def verify(self, **kwargs: Any) -> dict[str, Any]:
        return verification_result(**kwargs)

    def plugin_groups(self, plugin_id: str) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in self.registry.all():
            if record.plugin_id != plugin_id and not (plugin_id == "hades.native" and record.provider_id == "hades.native"):
                continue
            groups.setdefault(record.kind, []).append(
                {
                    "canonical_id": record.canonical_id,
                    "name": record.name,
                    "health": record.health,
                    "cost_class": record.cost_class,
                    "domains": record.domains,
                    "intents": record.intents,
                }
            )
        return groups

    def overview(self) -> dict[str, Any]:
        self.registry.refresh_native()
        snap = self.registry.snapshot()
        return {"registry": snap, "native_provider": "hades.native"}


_SERVICE: CapabilityIntelligence | None = None


def get_service(db: Any | None = None) -> CapabilityIntelligence:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = CapabilityIntelligence(db)
    elif db is not None and _SERVICE.db is None:
        _SERVICE.db = db
        _SERVICE.registry.db = db
    return _SERVICE


def reset_service() -> None:
    global _SERVICE
    _SERVICE = None
    from .registry import reset_registry

    reset_registry()


def adapt_path(root: str | Path, plugin: dict[str, Any] | None = None) -> dict[str, Any]:
    return adapt_package(Path(root), plugin=plugin).to_dict()
