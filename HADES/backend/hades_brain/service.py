"""One Brain façade: shared cognition contracts over existing subsystems."""

from __future__ import annotations

from typing import Any, Callable

from capability_intel.service import CapabilityIntelligence, get_service, reset_service

from .cost import CostLedger, get_ledger, reset_ledger
from .domain_runtime import default_runtimes, migration_matrix
from .evidence import evaluate_verification, should_stop_reasoning
from .mission import compile_role_view, ensure_owner
from .node import advertise_local_node
from .routing import brain_route
from .substrate import substrate_overview
from .tool_context import bound_tools_for_model


class HadesBrain:
    def __init__(self, db: Any | None = None, *, marketplace_search: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.db = db
        self.intel: CapabilityIntelligence = get_service(db)
        self.marketplace_search = marketplace_search
        self.runtimes = default_runtimes()
        self.ledger: CostLedger = get_ledger()
        self._cognitive = None

    def cognitive(self) -> Any:
        """Lazy Cognitive Runtime — same One Brain, not a competing platform."""
        if self._cognitive is None:
            from cognitive.runtime import get_cognitive_runtime

            db_path = None
            if self.db is not None and hasattr(self.db, "path"):
                db_path = self.db.path
            self._cognitive = get_cognitive_runtime(db_path)
        return self._cognitive

    def overview(self) -> dict[str, Any]:
        intel = self.intel.overview()
        cognitive_overview = None
        try:
            cognitive_overview = self.cognitive().overview()
        except Exception as exc:
            cognitive_overview = {"status": "unavailable", "error": type(exc).__name__}
        return {
            "brain": "hades.one",
            "monolith": False,
            "substrate": substrate_overview(),
            "capability_intel": intel,
            "domains": migration_matrix(),
            "node": advertise_local_node(),
            "cost": self.ledger.snapshot(),
            "cognitive": cognitive_overview,
        }

    def self_model(self, **kwargs: Any) -> dict[str, Any]:
        return self.cognitive().self_model(**kwargs)

    def route(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return brain_route(query, intel=self.intel, marketplace_search=self.marketplace_search, **kwargs)

    def observe(self, query: str, **kwargs: Any) -> dict[str, Any]:
        observed = self.intel.observe(query, **kwargs)
        observed.setdefault("model_called", False)
        selected = observed.get("routing", {}).get("selected") or []
        if observed.get("plan", {}).get("simple"):
            observed["agents"] = 0
            observed["agent_reason"] = None
            return observed
        agents = 0
        roles = observed.get("roles")
        if isinstance(roles, dict):
            agents = len(roles)
        mission = observed.get("mission") if isinstance(observed.get("mission"), dict) else {}
        usage = mission.get("usage") if isinstance(mission, dict) else {}
        if isinstance(usage, dict) and usage.get("agents"):
            agents = max(agents, int(usage.get("agents") or 0))
        observed["agents"] = agents
        if not selected and self.marketplace_search is not None:
            try:
                observed["marketplace"] = self.marketplace_search(query)
            except Exception as exc:
                observed["marketplace"] = {"status": "unavailable", "error": type(exc).__name__, "model_called": False}
        return observed

    def role_view(self, mission: Any, *, role: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        ensure_owner(mission)
        return compile_role_view(mission, role=role, extra=extra)

    def verify(self, *, domain: str, execution_success: bool, evidence: dict[str, Any] | None = None, agent_claims: list[str] | None = None, risk_requires_critic: bool = False) -> dict[str, Any]:
        outcome = evaluate_verification(
            domain=domain,
            execution_success=execution_success,
            evidence=evidence,
            agent_claims=agent_claims,
            risk_requires_critic=risk_requires_critic,
        )
        payload = outcome.to_dict()
        payload["stop_reasoning"] = should_stop_reasoning(outcome)
        return payload

    def bind_tools(self, tools: list[dict[str, Any]], *, query: str = "") -> dict[str, Any]:
        bound = bound_tools_for_model(tools, query=query)
        self.ledger.add(tool_schema_load_count=int(bound.get("tool_schema_load_count") or 0))
        return bound

    def domain(self, domain_id: str) -> Any:
        return self.runtimes[domain_id]


_BRAIN: HadesBrain | None = None


def get_brain(db: Any | None = None, **kwargs: Any) -> HadesBrain:
    global _BRAIN
    if _BRAIN is None:
        _BRAIN = HadesBrain(db, **kwargs)
    else:
        if db is not None and _BRAIN.db is None:
            _BRAIN.db = db
            _BRAIN.intel = get_service(db)
        search = kwargs.get("marketplace_search")
        if search is not None:
            _BRAIN.marketplace_search = search
    return _BRAIN


def reset_brain() -> None:
    global _BRAIN
    _BRAIN = None
    reset_service()
    reset_ledger()
    try:
        from cognitive.runtime import reset_cognitive_runtime

        reset_cognitive_runtime()
    except Exception:
        pass
