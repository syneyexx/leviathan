"""Agent fleet control plane — definitions, missions, orchestrators.

Side effects always go through AgentRuntime → ExecutionGateway / JobRuntime.
"""

from __future__ import annotations

import concurrent.futures
import copy
from typing import Any

from .fleet_types import (
    ACTIVE_MISSION_STATUSES,
    AgentDefinition,
    AgentDefinitionKind,
    AgentEvent,
    AgentHealth,
    AgentMission,
    MissionStatus,
    OrchestratorConfig,
)
from .governance import DelegationGovernor
from .runtime import AgentRuntime
from .store import AgentFleetStore, utc_now
from .system_inventory import SystemInventory, classify_fleet_agent
from .types import AgentKind
from .general_orchestra import general_intelligence_orchestra_seed


class AgentFleetError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "name": "Research",
        "kind": "research",
        "role": "Information & Analysis",
        "description": "Retrieval and synthesis via shared knowledge capabilities.",
        "capabilities": ["knowledge.search"],
        "tags": ["research", "web", "analysis"],
        "model_ref": None,
        "metadata": {"systemKey": "research"},
    },
    {
        "name": "Coding",
        "kind": "coding",
        "role": "Implementation & Verify",
        "description": "Coding control plane via shared filesystem capabilities.",
        "capabilities": ["file.read", "file.inspect_csv"],
        "tags": ["code", "tests", "refactor"],
        "model_ref": None,
        "metadata": {"systemKey": "coding"},
    },
    {
        "name": "Critic",
        "kind": "specialist",
        "role": "Review & Guardrails",
        "description": "Reviewer agent — still uses shared gateway for privileged actions.",
        "capabilities": ["knowledge.search"],
        "tags": ["review", "qa", "policy"],
        "model_ref": None,
        "metadata": {"systemKey": "critic"},
    },
    {
        "name": "Planner",
        "kind": "orchestrator",
        "role": "Goals & Decomposition",
        "description": "Orchestrator that delegates to member agents without private execution.",
        "capabilities": [],
        "tags": ["plan", "delegate", "roadmap"],
        "model_ref": None,
        "metadata": {"systemKey": "planner"},
        "orchestrator": {
            "memberAgentIds": [],
            "strategy": "sequential",
            "maxDelegationDepth": 3,
            "parallelismLimit": 2,
            "failureStrategy": "fail_fast",
        },
    },
    {
        "name": "Dataset Learning",
        "kind": "specialist",
        "role": "Dataset Learning",
        "description": (
            "Processes dataset index jobs into the shared KnowledgeStore / Brain. "
            "Live progress mirrors real dataset_jobs — not fictional missions."
        ),
        "capabilities": ["knowledge.search"],
        "tags": ["datasets", "learning", "indexing", "brain"],
        "model_ref": None,
        "dataset_access": "controlled",
        "metadata": {
            "systemKey": "dataset_learning",
            "ownsDatasetIndexJobs": True,
            "truth": {"status_from_dataset_jobs": True},
        },
    },
    # General Intelligence Orchestra specialists (CognitiveRuntime remains parent authority).
    *general_intelligence_orchestra_seed(),
]

DATASET_LEARNING_SYSTEM_KEY = "dataset_learning"
# Role string that marks an ORCHESTRATOR definition as a trade orchestra (market_sim owns it).
TRADE_ORCHESTRA_ROLE = "trade_orchestra"


class AgentFleetService:
    def __init__(
        self,
        store: AgentFleetStore,
        runtime: AgentRuntime,
        *,
        dataset_activity_provider: Any | None = None,
        system_inventory: SystemInventory | None = None,
        job_runtime: Any | None = None,
        governor: DelegationGovernor | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        # Optional callable returning DatasetService.learning_activity()-shaped dict.
        self.dataset_activity_provider = dataset_activity_provider
        self.system_inventory = system_inventory or SystemInventory()
        self.job_runtime = job_runtime
        # Domain executors keyed by AgentDefinitionKind (e.g. TRADING → market_sim orchestra).
        # Missions for a kind with a registered executor never reach the generic runtime.
        self._kind_executors: dict[AgentDefinitionKind, Any] = {}
        self.signal_fabric: Any | None = None
        # W9: shared recursion/authority/budget governor for orchestrator children.
        self.governor = governor or DelegationGovernor()

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def bind_signal_fabric(self, fabric: Any | None) -> None:
        """Optional LEVIATHAN Signal Fabric for mission lifecycle observability."""
        self.signal_fabric = fabric

    def register_kind_executor(self, kind: AgentDefinitionKind | str, executor: Any) -> None:
        """Register a domain executor: ``executor.execute(mission, agent, fleet=...) -> dict``."""
        key = kind if isinstance(kind, AgentDefinitionKind) else AgentDefinitionKind(str(kind))
        self._kind_executors[key] = executor

    def kind_executor(self, kind: AgentDefinitionKind | str) -> Any | None:
        key = kind if isinstance(kind, AgentDefinitionKind) else AgentDefinitionKind(str(kind))
        return self._kind_executors.get(key)

    @staticmethod
    def _runners_externalized() -> bool:
        import os

        ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
        if ext in {"1", "true", "yes", "on"}:
            return True
        if ext in {"0", "false", "no", "off"}:
            return False
        raw = (os.environ.get("LEVIATHAN_AGENTS_RUNNER") or "").strip().lower()
        if raw in {"external", "worker", "process"}:
            return True
        if raw in {"inprocess", "thread", "api"}:
            return False
        try:
            from Data.modules.workers.settings import load_worker_settings

            return bool(load_worker_settings().externalize_api_runners)
        except Exception:  # noqa: BLE001
            return False

    def enqueue_advance(
        self,
        mission_id: str,
        *,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        requested_by: str = "agent_fleet",
        generation: str | None = None,
    ) -> Any:
        """Enqueue durable ``agent.advance`` for an external agents-pool worker."""
        if self.job_runtime is None:
            raise RuntimeError("job_runtime not bound; cannot enqueue agent.advance")
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise AgentFleetError(
                "MISSION_NOT_FOUND",
                f"Mission not found: {mission_id}",
                http_status=404,
            )
        gen = generation or str(mission.created_at)
        idem = f"agent:advance:{mission_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="agent.advance",
            arguments={
                "mission_id": mission_id,
                "agent_id": mission.agent_id,
            },
            requested_by=requested_by,
            idempotency_key=idem,
            domain="agents",
            domain_entity_type="agent_mission",
            domain_entity_id=mission_id,
            worker_pool="agents",
            parent_job_id=parent_job_id,
            root_job_id=root_job_id or parent_job_id,
            latency_class="background",
            metadata={
                "mission_id": mission_id,
                "agent_id": mission.agent_id,
                "generation": gen,
            },
        )

    def enqueue_queued_missions(self) -> list[str]:
        """Enqueue advance jobs for QUEUED missions (idempotent keys)."""
        job_ids: list[str] = []
        if self.job_runtime is None:
            return job_ids
        for mission in self.store.list_missions(limit=200):
            if mission.status != MissionStatus.QUEUED:
                continue
            try:
                job = self.enqueue_advance(mission.mission_id)
                job_ids.append(job.job_id)
                if job.job_id not in mission.job_ids:
                    mission.job_ids = list(mission.job_ids) + [job.job_id]
                    # Do not bump updated_at — generation is tied to created_at.
                    self.store.update_mission(mission)
            except Exception:  # noqa: BLE001
                continue
        return job_ids

    def start_background(self) -> None:
        """When workers are externalized, enqueue durable jobs; else no API daemon.

        Legacy path advances missions synchronously inside :meth:`launch_mission`.
        """
        if self._runners_externalized():
            if self.job_runtime is not None:
                self.enqueue_queued_missions()
            return
        # In-process legacy: no background thread — launch_mission executes inline.

    def advance_mission(self, mission_id: str, *, use_jobs: bool | None = None) -> AgentMission:
        """Advance one queued mission to completion (agents worker unit of work)."""
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise AgentFleetError(
                "MISSION_NOT_FOUND",
                f"Mission not found: {mission_id}",
                http_status=404,
            )
        if mission.status != MissionStatus.QUEUED:
            return mission
        if mission.cancel_requested:
            mission.status = MissionStatus.CANCELLED
            mission.finished_at = utc_now()
            mission.updated_at = mission.finished_at
            self.store.update_mission(mission)
            return mission
        agent = self.get_agent(mission.agent_id)
        depth = int((mission.metadata or {}).get("depth") or 0)
        if use_jobs is None:
            use_jobs = bool((mission.metadata or {}).get("useJobs"))
        return self._execute_mission(mission, agent, depth=depth, use_jobs=bool(use_jobs))

    def initialize(self, *, seed_defaults: bool = True) -> None:
        self.store.initialize()
        if seed_defaults and not self.store.list_definitions(limit=1):
            self._seed_defaults()
        # Always ensure system agents exist — including on upgraded databases.
        if seed_defaults:
            self.ensure_system_agents()

    def ensure_system_agents(self) -> list[AgentDefinition]:
        """Idempotently create missing system agents (by metadata.systemKey)."""
        existing = self.store.list_definitions(include_archived=True, limit=500)
        by_key: dict[str, AgentDefinition] = {}
        for agent in existing:
            key = str((agent.metadata or {}).get("systemKey") or "").strip()
            if key:
                by_key[key] = agent
        # Fallback: match Dataset Learning by stable name for older installs.
        name_map = {a.name.lower(): a for a in existing}
        created: list[AgentDefinition] = []
        for spec in _DEFAULT_SEED:
            key = str((spec.get("metadata") or {}).get("systemKey") or "").strip()
            if not key:
                continue
            if key in by_key:
                continue
            if spec["name"].lower() in name_map:
                # Attach systemKey to the pre-existing named agent.
                agent = name_map[spec["name"].lower()]
                meta = dict(agent.metadata or {})
                meta.update(dict(spec.get("metadata") or {}))
                agent.metadata = meta
                if spec.get("dataset_access") and agent.dataset_access == "none":
                    agent.dataset_access = str(spec["dataset_access"])
                agent.updated_at = utc_now()
                self.store.update_definition(agent)
                by_key[key] = agent
                continue
            kind = AgentDefinitionKind(spec["kind"])
            orch = None
            if kind == AgentDefinitionKind.ORCHESTRATOR:
                orch = OrchestratorConfig.from_dict(spec.get("orchestrator"))
            now = utc_now()
            definition = AgentDefinition(
                agent_id=AgentFleetStore.new_id("agent"),
                name=str(spec["name"]),
                kind=kind,
                description=str(spec.get("description") or ""),
                role=str(spec.get("role") or ""),
                enabled=True,
                capabilities=list(spec.get("capabilities") or []),
                tags=list(spec.get("tags") or []),
                model_ref=spec.get("model_ref"),
                dataset_access=str(spec.get("dataset_access") or "none"),
                orchestrator=orch,
                health=AgentHealth.IDLE,
                metadata=dict(spec.get("metadata") or {}),
                created_at=now,
                updated_at=now,
            )
            self.store.create_definition(definition)
            created.append(definition)
            by_key[key] = definition
            self._emit(
                agent_id=definition.agent_id,
                category="system",
                message=f"Ensured system agent {definition.name}",
            )
        # Keep Planner membership aware of Dataset Learning when present.
        planner = by_key.get("planner") or next(
            (a for a in self.store.list_definitions() if a.kind == AgentDefinitionKind.ORCHESTRATOR),
            None,
        )
        learning = by_key.get(DATASET_LEARNING_SYSTEM_KEY)
        if planner and planner.orchestrator and learning:
            members = list(planner.orchestrator.member_agent_ids or [])
            if learning.agent_id not in members:
                members.append(learning.agent_id)
                planner.orchestrator.member_agent_ids = members
                planner.updated_at = utc_now()
                self.store.update_definition(planner)
        # Wire General Intelligence Orchestra membership from specialist systemKeys.
        from .general_orchestra import GI_SPECIALIST_KEYS, GENERAL_INTELLIGENCE_ORCHESTRA_KEY

        gi_orch = by_key.get(GENERAL_INTELLIGENCE_ORCHESTRA_KEY)
        if gi_orch and gi_orch.orchestrator:
            members = list(gi_orch.orchestrator.member_agent_ids or [])
            changed = False
            for key in GI_SPECIALIST_KEYS:
                specialist = by_key.get(key)
                if specialist and specialist.agent_id not in members:
                    members.append(specialist.agent_id)
                    changed = True
            if changed:
                gi_orch.orchestrator.member_agent_ids = members
                gi_orch.updated_at = utc_now()
                self.store.update_definition(gi_orch)
        return created

    def get_system_agent(self, system_key: str) -> AgentDefinition | None:
        key = str(system_key or "").strip()
        for agent in self.store.list_definitions(include_archived=True, limit=500):
            if str((agent.metadata or {}).get("systemKey") or "") == key:
                return self._refresh_health(agent)
            if key == DATASET_LEARNING_SYSTEM_KEY and agent.name.lower() == "dataset learning":
                return self._refresh_health(agent)
        return None

    def dataset_learning_status(self) -> dict[str, Any]:
        """Bundle Dataset Learning agent + live dataset job activity."""
        agent = self.get_system_agent(DATASET_LEARNING_SYSTEM_KEY)
        activity: dict[str, Any] = {
            "agentSystemKey": DATASET_LEARNING_SYSTEM_KEY,
            "agentName": "Dataset Learning",
            "activeCount": 0,
            "active": [],
            "recent": [],
            "truth": {"reflects_real_dataset_jobs": True},
        }
        if callable(self.dataset_activity_provider):
            try:
                activity = dict(self.dataset_activity_provider() or activity)
            except Exception as exc:  # noqa: BLE001
                activity["error"] = str(exc)
        payload: dict[str, Any] = {
            "agent": agent.public_dict() if agent else None,
            "activity": activity,
            "truth": {
                "no_fictional_missions": True,
                "status_from_dataset_jobs": True,
            },
        }
        return payload

    def _seed_defaults(self) -> None:
        created: dict[str, str] = {}
        for spec in _DEFAULT_SEED:
            kind = AgentDefinitionKind(spec["kind"])
            orch = None
            if kind == AgentDefinitionKind.ORCHESTRATOR:
                orch = OrchestratorConfig.from_dict(spec.get("orchestrator"))
            now = utc_now()
            definition = AgentDefinition(
                agent_id=AgentFleetStore.new_id("agent"),
                name=str(spec["name"]),
                kind=kind,
                description=str(spec.get("description") or ""),
                role=str(spec.get("role") or ""),
                enabled=True,
                capabilities=list(spec.get("capabilities") or []),
                tags=list(spec.get("tags") or []),
                model_ref=spec.get("model_ref"),
                dataset_access=str(spec.get("dataset_access") or "none"),
                orchestrator=orch,
                health=AgentHealth.IDLE if True else AgentHealth.UNKNOWN,
                metadata=dict(spec.get("metadata") or {}),
                created_at=now,
                updated_at=now,
            )
            self.store.create_definition(definition)
            created[definition.name.lower()] = definition.agent_id
            self._emit(
                agent_id=definition.agent_id,
                category="system",
                message=f"Seeded agent definition {definition.name}",
            )
        # Wire planner orchestrator members once IDs exist
        planner = next(
            (a for a in self.store.list_definitions() if a.kind == AgentDefinitionKind.ORCHESTRATOR),
            None,
        )
        if planner and planner.orchestrator:
            members = [
                created[name]
                for name in ("research", "coding", "critic", "dataset learning")
                if name in created
            ]
            planner.orchestrator.member_agent_ids = members
            planner.updated_at = utc_now()
            self.store.update_definition(planner)

    def _emit(
        self,
        *,
        category: str,
        message: str,
        agent_id: str | None = None,
        mission_id: str | None = None,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=AgentFleetStore.new_id("aevt"),
            agent_id=agent_id,
            mission_id=mission_id,
            category=category,
            message=message,
            level=level,
            payload=dict(payload or {}),
            created_at=utc_now(),
        )
        return self.store.append_event(event)

    def list_agents(self, *, include_archived: bool = False, kind: str | None = None) -> list[AgentDefinition]:
        agents = self.store.list_definitions(include_archived=include_archived, kind=kind)
        return [self._refresh_health(a) for a in agents]

    def get_agent(self, agent_id: str) -> AgentDefinition:
        agent = self.store.get_definition(agent_id)
        if agent is None:
            raise AgentFleetError("AGENT_NOT_FOUND", f"Agent not found: {agent_id}", http_status=404)
        return self._refresh_health(agent)

    def _refresh_health(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.archived:
            agent.health = AgentHealth.ARCHIVED
            agent.health_reason = "archived"
            return agent
        if not agent.enabled:
            agent.health = AgentHealth.DISABLED
            agent.health_reason = "disabled"
            return agent
        if not self.runtime.agents_enabled:
            agent.health = AgentHealth.DISABLED
            agent.health_reason = "LEVIATHAN_FEATURE_AGENTS is OFF"
            return agent
        system_key = str((agent.metadata or {}).get("systemKey") or "")
        if system_key == DATASET_LEARNING_SYSTEM_KEY and callable(self.dataset_activity_provider):
            try:
                activity = dict(self.dataset_activity_provider() or {})
                active_count = int(activity.get("activeCount") or 0)
                if active_count > 0:
                    agent.health = AgentHealth.BUSY
                    agent.health_reason = f"{active_count} active dataset index job(s)"
                    return agent
            except Exception:  # noqa: BLE001
                pass
        active = self.store.count_active_for_agent(agent.agent_id)
        if active > 0:
            agent.health = AgentHealth.BUSY
            agent.health_reason = f"{active} active mission(s)"
        else:
            agent.health = AgentHealth.IDLE
            agent.health_reason = None
        return agent

    def _validate_orchestrator(
        self,
        orch: OrchestratorConfig,
        *,
        self_id: str | None = None,
        role: str = "",
    ) -> None:
        if orch.max_delegation_depth < 1 or orch.max_delegation_depth > 16:
            raise AgentFleetError("INVALID_ORCHESTRATOR", "maxDelegationDepth must be 1..16")
        if orch.parallelism_limit < 1 or orch.parallelism_limit > 32:
            raise AgentFleetError("INVALID_ORCHESTRATOR", "parallelismLimit must be 1..32")
        if orch.strategy not in {"sequential", "parallel_bounded"}:
            raise AgentFleetError("INVALID_ORCHESTRATOR", f"Unsupported strategy: {orch.strategy}")
        if orch.failure_strategy not in {"fail_fast", "continue"}:
            raise AgentFleetError("INVALID_ORCHESTRATOR", f"Unsupported failureStrategy: {orch.failure_strategy}")
        seen: set[str] = set()
        for member_id in orch.member_agent_ids:
            if member_id in seen:
                raise AgentFleetError("INVALID_MEMBER", f"Duplicate member: {member_id}")
            seen.add(member_id)
            if self_id and member_id == self_id:
                raise AgentFleetError("ORCHESTRATOR_CYCLE", "Orchestrator cannot include itself")
            member = self.store.get_definition(member_id)
            if member is None:
                raise AgentFleetError("INVALID_MEMBER", f"Unknown member agent: {member_id}", http_status=422)
            if member.archived:
                raise AgentFleetError("INVALID_MEMBER", f"Member is archived: {member_id}", http_status=422)
            # Trading isolation: TRADING members only inside a trade orchestra, and a trade
            # orchestra holds only TRADING members (no coding/research agents in the loop).
            is_trade_orchestra = str(role or "") == TRADE_ORCHESTRA_ROLE
            if member.kind == AgentDefinitionKind.TRADING and not is_trade_orchestra:
                raise AgentFleetError(
                    "TRADING_MEMBER_ISOLATION",
                    f"Trading agent {member_id} may only be a member of a trade orchestra",
                    http_status=422,
                )
            if is_trade_orchestra and member.kind != AgentDefinitionKind.TRADING:
                raise AgentFleetError(
                    "TRADING_MEMBER_ISOLATION",
                    f"Trade orchestra members must be trading agents (got {member.kind.value}: {member_id})",
                    http_status=422,
                )
            if member.kind == AgentDefinitionKind.ORCHESTRATOR:
                # Nested orchestrators count against depth; disallow deep graphs here.
                nested = member.orchestrator.member_agent_ids if member.orchestrator else []
                if self_id and self_id in nested:
                    raise AgentFleetError("ORCHESTRATOR_CYCLE", "Cycle detected in orchestrator graph")

    def _system_key_of(self, agent: AgentDefinition) -> str | None:
        key = str((agent.metadata or {}).get("systemKey") or "").strip()
        return key or None

    def _assert_system_mutable(self, agent: AgentDefinition, *, action: str) -> None:
        if self._system_key_of(agent):
            raise AgentFleetError(
                "SYSTEM_AGENT_PROTECTED",
                f"Cannot {action} protected SYSTEM agent '{agent.name}' "
                f"(systemKey={self._system_key_of(agent)})",
                http_status=403,
            )

    def create_agent(self, payload: dict[str, Any]) -> AgentDefinition:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise AgentFleetError("INVALID_NAME", "name is required")
        kind_raw = str(payload.get("kind") or "generic").strip().lower()
        try:
            kind = AgentDefinitionKind(kind_raw)
        except ValueError as exc:
            raise AgentFleetError("INVALID_KIND", f"Unsupported kind: {kind_raw}") from exc
        orch = None
        if kind == AgentDefinitionKind.ORCHESTRATOR:
            orch = OrchestratorConfig.from_dict(payload.get("orchestrator"))
            self._validate_orchestrator(orch, role=str(payload.get("role") or ""))
        # USER CRUD must never invent SYSTEM ownership.
        metadata = dict(payload.get("metadata") or {})
        metadata.pop("systemKey", None)
        now = utc_now()
        definition = AgentDefinition(
            agent_id=AgentFleetStore.new_id("agent"),
            name=name,
            kind=kind,
            description=str(payload.get("description") or ""),
            role=str(payload.get("role") or ""),
            enabled=bool(payload.get("enabled", True)),
            model_ref=payload.get("modelRef") or payload.get("model_ref"),
            system_policy=payload.get("systemPolicy") or payload.get("system_policy"),
            capabilities=list(payload.get("capabilities") or []),
            knowledge_sources=list(payload.get("knowledgeSources") or payload.get("knowledge_sources") or []),
            memory_policy=str(payload.get("memoryPolicy") or payload.get("memory_policy") or "default"),
            dataset_access=str(payload.get("datasetAccess") or payload.get("dataset_access") or "none"),
            approval_mode=str(payload.get("approvalMode") or payload.get("approval_mode") or "inherit"),
            autonomy=int(payload.get("autonomy") if payload.get("autonomy") is not None else 50),
            max_concurrency=max(1, int(payload.get("maxConcurrency") or payload.get("max_concurrency") or 1)),
            timeout_s=payload.get("timeoutS", payload.get("timeout_s")),
            max_retries=max(0, int(payload.get("maxRetries") or payload.get("max_retries") or 0)),
            token_budget=payload.get("tokenBudget", payload.get("token_budget")),
            tags=list(payload.get("tags") or []),
            orchestrator=orch,
            health=AgentHealth.IDLE,
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        self.store.create_definition(definition)
        self._emit(agent_id=definition.agent_id, category="agents", message=f"Created agent {definition.name}")
        return self._refresh_health(definition)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> AgentDefinition:
        current = self.get_agent(agent_id)
        if current.archived and not payload.get("unarchive"):
            raise AgentFleetError("AGENT_ARCHIVED", "Cannot update archived agent", http_status=409)
        system_key = self._system_key_of(current)
        if system_key:
            # Protected identity fields — never rename, rekind, or strip systemKey.
            if "name" in payload and payload["name"] is not None:
                if str(payload["name"]).strip() != current.name:
                    raise AgentFleetError(
                        "SYSTEM_AGENT_PROTECTED",
                        f"Cannot rename SYSTEM agent '{current.name}'",
                        http_status=403,
                    )
            if "kind" in payload and payload["kind"]:
                if str(payload["kind"]).lower() != current.kind.value:
                    raise AgentFleetError(
                        "SYSTEM_AGENT_PROTECTED",
                        f"Cannot change kind of SYSTEM agent '{current.name}'",
                        http_status=403,
                    )
            if "metadata" in payload and payload["metadata"] is not None:
                incoming = dict(payload["metadata"] or {})
                if str(incoming.get("systemKey") or "").strip() != system_key:
                    raise AgentFleetError(
                        "SYSTEM_AGENT_PROTECTED",
                        "Cannot remove or replace systemKey on SYSTEM agents",
                        http_status=403,
                    )
        updated = copy.deepcopy(current)
        for field, attr in (
            ("name", "name"),
            ("description", "description"),
            ("role", "role"),
            ("modelRef", "model_ref"),
            ("model_ref", "model_ref"),
            ("systemPolicy", "system_policy"),
            ("system_policy", "system_policy"),
            ("memoryPolicy", "memory_policy"),
            ("memory_policy", "memory_policy"),
            ("datasetAccess", "dataset_access"),
            ("dataset_access", "dataset_access"),
            ("approvalMode", "approval_mode"),
            ("approval_mode", "approval_mode"),
        ):
            if field in payload and payload[field] is not None:
                setattr(updated, attr, payload[field] if attr != "name" else str(payload[field]).strip())
        if "enabled" in payload:
            updated.enabled = bool(payload["enabled"])
        if "capabilities" in payload:
            updated.capabilities = list(payload["capabilities"] or [])
        if "knowledgeSources" in payload or "knowledge_sources" in payload:
            updated.knowledge_sources = list(
                payload.get("knowledgeSources") or payload.get("knowledge_sources") or []
            )
        if "tags" in payload:
            updated.tags = list(payload["tags"] or [])
        if "autonomy" in payload:
            updated.autonomy = int(payload["autonomy"])
        if "maxConcurrency" in payload or "max_concurrency" in payload:
            updated.max_concurrency = max(
                1, int(payload.get("maxConcurrency") or payload.get("max_concurrency") or 1)
            )
        if "timeoutS" in payload or "timeout_s" in payload:
            updated.timeout_s = payload.get("timeoutS", payload.get("timeout_s"))
        if "maxRetries" in payload or "max_retries" in payload:
            updated.max_retries = max(0, int(payload.get("maxRetries") or payload.get("max_retries") or 0))
        if "tokenBudget" in payload or "token_budget" in payload:
            updated.token_budget = payload.get("tokenBudget", payload.get("token_budget"))
        if "kind" in payload and payload["kind"]:
            try:
                updated.kind = AgentDefinitionKind(str(payload["kind"]).lower())
            except ValueError as exc:
                raise AgentFleetError("INVALID_KIND", f"Unsupported kind: {payload['kind']}") from exc
        if "metadata" in payload and payload["metadata"] is not None:
            meta = dict(payload["metadata"] or {})
            if system_key:
                meta["systemKey"] = system_key
            else:
                meta.pop("systemKey", None)
            updated.metadata = meta
        if updated.kind == AgentDefinitionKind.ORCHESTRATOR:
            orch_payload = payload.get("orchestrator")
            if orch_payload is not None:
                updated.orchestrator = OrchestratorConfig.from_dict(orch_payload)
            if updated.orchestrator is None:
                updated.orchestrator = OrchestratorConfig()
            self._validate_orchestrator(updated.orchestrator, self_id=updated.agent_id, role=updated.role)
        elif "orchestrator" in payload and payload["orchestrator"] is not None:
            raise AgentFleetError("INVALID_ORCHESTRATOR", "orchestrator config only valid for kind=orchestrator")
        updated.version = int(updated.version) + 1
        updated.updated_at = utc_now()
        self.store.update_definition(updated)
        self._emit(agent_id=updated.agent_id, category="agents", message=f"Updated agent {updated.name} v{updated.version}")
        return self._refresh_health(updated)

    def clone_agent(self, agent_id: str) -> AgentDefinition:
        source = self.get_agent(agent_id)
        payload = source.public_dict()
        payload["name"] = f"{source.name} (copy)"
        payload.pop("agentId", None)
        payload.pop("id", None)
        # Clones are always USER agents — never inherit SYSTEM ownership.
        meta = dict(payload.get("metadata") or {})
        meta.pop("systemKey", None)
        payload["metadata"] = meta
        if source.orchestrator:
            payload["orchestrator"] = source.orchestrator.public_dict()
        return self.create_agent(payload)

    def set_enabled(self, agent_id: str, enabled: bool) -> AgentDefinition:
        return self.update_agent(agent_id, {"enabled": enabled})

    def archive_agent(self, agent_id: str) -> AgentDefinition:
        agent = self.get_agent(agent_id)
        self._assert_system_mutable(agent, action="archive")
        active = self.store.count_active_for_agent(agent_id)
        if active:
            raise AgentFleetError(
                "AGENT_BUSY",
                f"Cannot archive agent with {active} active mission(s)",
                http_status=409,
            )
        # Prevent deleting members still referenced by orchestrators
        for other in self.store.list_definitions():
            if other.agent_id == agent_id:
                continue
            if other.orchestrator and agent_id in other.orchestrator.member_agent_ids:
                raise AgentFleetError(
                    "AGENT_REFERENCED",
                    f"Referenced by orchestrator {other.agent_id}",
                    http_status=409,
                )
        agent.archived = True
        agent.enabled = False
        agent.health = AgentHealth.ARCHIVED
        agent.updated_at = utc_now()
        agent.version += 1
        self.store.update_definition(agent)
        self._emit(agent_id=agent_id, category="agents", message=f"Archived agent {agent.name}")
        return agent

    def _execution_kind(self, definition: AgentDefinition) -> AgentKind:
        if definition.kind == AgentDefinitionKind.CODING:
            return AgentKind.CODING
        if definition.kind == AgentDefinitionKind.RESEARCH:
            return AgentKind.RESEARCH
        if definition.kind == AgentDefinitionKind.TRADING:
            # Trading agents are never planned by the generic/coding/research planners.
            # AgentKind.TRADING exists for domain labeling; execution requires the orchestra executor.
            raise AgentFleetError(
                "TRADING_EXECUTOR_REQUIRED",
                "Trading agents execute only through the registered trading executor "
                "(market_sim orchestra); generic planning is refused.",
                http_status=409,
            )
        return AgentKind.GENERIC

    def launch_mission(
        self,
        *,
        agent_id: str,
        request: str,
        title: str | None = None,
        priority: str = "med",
        use_jobs: bool = False,
        dry_run: bool = False,
        parent_mission_id: str | None = None,
        depth: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> AgentMission:
        text = (request or "").strip()
        if not text:
            raise AgentFleetError("INVALID_REQUEST", "request is required")
        agent = self.get_agent(agent_id)
        if agent.archived:
            raise AgentFleetError("AGENT_ARCHIVED", "Agent is archived", http_status=409)
        if not agent.enabled:
            raise AgentFleetError("AGENT_DISABLED", "Agent is disabled", http_status=403)
        if not self.runtime.agents_enabled:
            raise AgentFleetError(
                "AGENTS_FEATURE_OFF",
                "Agents feature flag is OFF (LEVIATHAN_FEATURE_AGENTS)",
                http_status=403,
            )
        active = self.store.count_active_for_agent(agent_id)
        if active >= max(1, agent.max_concurrency):
            raise AgentFleetError(
                "CONCURRENCY_LIMIT",
                f"Agent concurrency limit reached ({agent.max_concurrency})",
                http_status=409,
            )
        now = utc_now()
        mission = AgentMission(
            mission_id=AgentFleetStore.new_id("msn"),
            agent_id=agent_id,
            title=(title or text[:80]).strip() or "mission",
            request=text,
            status=MissionStatus.QUEUED,
            priority=priority if priority in {"low", "med", "high"} else "med",
            progress=0.0,
            parent_mission_id=parent_mission_id,
            trace_id=AgentFleetStore.new_id("trace"),
            created_at=now,
            updated_at=now,
            metadata={**dict(metadata or {}), "dryRun": dry_run, "depth": depth, "useJobs": use_jobs},
        )
        self.store.create_mission(mission)
        self._emit(
            agent_id=agent_id,
            mission_id=mission.mission_id,
            category="tasks",
            message=f"Mission queued: {mission.title}",
        )
        if dry_run:
            plan_payload = self._plan_payload(agent, text, depth=depth)
            mission.status = MissionStatus.COMPLETED
            mission.progress = 1.0
            mission.result = {"dryRun": True, "plan": plan_payload}
            mission.started_at = now
            mission.finished_at = utc_now()
            mission.updated_at = mission.finished_at
            self.store.update_mission(mission)
            self._emit(
                agent_id=agent_id,
                mission_id=mission.mission_id,
                category="tasks",
                message="Dry-run plan completed (no side effects)",
            )
            return mission

        # Top-level missions: durable enqueue when workers are externalized.
        # Nested orchestrator children stay inline inside the claiming worker.
        if (
            parent_mission_id is None
            and self._runners_externalized()
            and self.job_runtime is not None
        ):
            try:
                job = self.enqueue_advance(
                    mission.mission_id,
                    requested_by="agent_fleet.launch_mission",
                )
                mission.job_ids = [job.job_id]
                mission.updated_at = utc_now()
                self.store.update_mission(mission)
            except Exception as exc:  # noqa: BLE001 — fall back to inline
                self._emit(
                    agent_id=agent_id,
                    mission_id=mission.mission_id,
                    category="errors",
                    message=f"Enqueue agent.advance failed; executing inline: {exc}",
                    level="warn",
                )
                return self._execute_mission(mission, agent, depth=depth, use_jobs=use_jobs)
            return mission

        return self._execute_mission(mission, agent, depth=depth, use_jobs=use_jobs)

    def _plan_payload(self, agent: AgentDefinition, request: str, *, depth: int) -> dict[str, Any]:
        domain_executor = self._domain_executor_for(agent)
        if domain_executor is not None and hasattr(domain_executor, "plan"):
            return {
                "kind": agent.kind.value,
                "executor": getattr(domain_executor, "name", type(domain_executor).__name__),
                "plan": domain_executor.plan(agent, request),
                "request": request[:500],
            }
        if agent.kind == AgentDefinitionKind.ORCHESTRATOR and agent.orchestrator:
            members = []
            for mid in agent.orchestrator.member_agent_ids:
                member = self.store.get_definition(mid)
                members.append(
                    {
                        "agentId": mid,
                        "name": member.name if member else None,
                        "kind": member.kind.value if member else None,
                        "enabled": member.enabled if member else False,
                    }
                )
            return {
                "kind": "orchestrator",
                "strategy": agent.orchestrator.strategy,
                "depth": depth,
                "maxDepth": agent.orchestrator.max_delegation_depth,
                "members": members,
                "request": request[:500],
            }
        steps = self.runtime.plan(request, kind=self._execution_kind(agent))
        return {
            "kind": agent.kind.value,
            "steps": [s.public_dict() for s in steps],
            "request": request[:500],
        }

    def _execute_mission(
        self,
        mission: AgentMission,
        agent: AgentDefinition,
        *,
        depth: int,
        use_jobs: bool,
    ) -> AgentMission:
        mission.status = MissionStatus.RUNNING
        mission.started_at = utc_now()
        mission.updated_at = mission.started_at
        mission.progress = 0.05
        self.store.update_mission(mission)
        agent.last_run_at = mission.started_at
        agent.last_mission_id = mission.mission_id
        agent.updated_at = mission.started_at
        self.store.update_definition(agent)

        try:
            executor = self._domain_executor_for(agent)
            if executor is not None:
                # Domain executors (e.g. trade orchestra + trading agents) own their own protocol.
                result = self._run_kind_executor(executor, mission, agent)
            elif agent.kind == AgentDefinitionKind.ORCHESTRATOR:
                result = self._run_orchestrator(mission, agent, depth=depth, use_jobs=use_jobs)
            else:
                outcome = self.runtime.execute(
                    mission.request,
                    kind=self._execution_kind(agent),
                    use_jobs=use_jobs,
                )
                result = outcome.public_dict()
                mission.run_id = outcome.run_id
                mission.job_ids = list(outcome.job_ids)
                if outcome.status in {"FAILED", "DISABLED", "UNVERIFIED"}:
                    mission.status = (
                        MissionStatus.DISABLED if outcome.status == "DISABLED" else MissionStatus.FAILED
                    )
                    mission.error = outcome.error or outcome.status
                else:
                    mission.status = MissionStatus.COMPLETED
                    mission.progress = 1.0
            mission.result = result
        except AgentFleetError as exc:
            mission.status = MissionStatus.FAILED
            mission.error = exc.message
            mission.result = exc.public_dict()
            self._emit(
                agent_id=agent.agent_id,
                mission_id=mission.mission_id,
                category="errors",
                message=exc.message,
                level="error",
            )
        except Exception as exc:  # noqa: BLE001 — persist truthful failure
            mission.status = MissionStatus.FAILED
            mission.error = str(exc)
            self._emit(
                agent_id=agent.agent_id,
                mission_id=mission.mission_id,
                category="errors",
                message=str(exc),
                level="error",
            )

        if mission.cancel_requested and mission.status == MissionStatus.RUNNING:
            mission.status = MissionStatus.CANCELLED

        mission.finished_at = utc_now()
        mission.updated_at = mission.finished_at
        if mission.status == MissionStatus.COMPLETED and mission.progress < 1.0:
            mission.progress = 1.0
        self.store.update_mission(mission)
        self._emit(
            agent_id=agent.agent_id,
            mission_id=mission.mission_id,
            category="tasks",
            message=f"Mission {mission.status.value}: {mission.title}",
            level="error" if mission.status == MissionStatus.FAILED else "info",
        )
        self._emit_lifecycle_signal(mission, agent)
        return mission

    def _emit_lifecycle_signal(self, mission: AgentMission, agent: AgentDefinition) -> None:
        fabric = self.signal_fabric
        if fabric is None:
            return
        try:
            from Data.modules.agents.signals.types import SignalType

            if mission.status == MissionStatus.COMPLETED:
                st = SignalType.COMPLETED
                subject = f"Mission completed: {mission.title}"
            elif mission.status == MissionStatus.FAILED:
                st = SignalType.ERROR
                subject = f"Mission failed: {mission.error or mission.title}"
            elif mission.status == MissionStatus.CANCELLED:
                st = SignalType.CANCEL
                subject = f"Mission cancelled: {mission.title}"
            else:
                return
            # Observability-only: do not change mission semantics if publish fails.
            fabric.emit_mission_lifecycle(
                signal_type=st,
                mission_id=mission.mission_id,
                agent_id=agent.agent_id,
                subject=subject,
                payload={
                    "missionStatus": mission.status.value,
                    "progress": mission.progress,
                },
                run_id=mission.run_id,
                trace_id=mission.trace_id,
            )
        except Exception:  # noqa: BLE001
            return

    def _domain_executor_for(self, agent: AgentDefinition) -> Any | None:
        """Resolve the domain executor that owns this agent (by kind, or by orchestra claim)."""
        direct = self._kind_executors.get(agent.kind)
        if direct is not None:
            return direct
        if agent.kind == AgentDefinitionKind.ORCHESTRATOR:
            for executor in self._kind_executors.values():
                owns = getattr(executor, "owns_orchestrator", None)
                if callable(owns) and owns(agent):
                    return executor
        return None

    def _run_kind_executor(
        self,
        executor: Any,
        mission: AgentMission,
        agent: AgentDefinition,
    ) -> dict[str, Any]:
        outcome = executor.execute(mission, agent, fleet=self)
        result = dict(outcome or {})
        status = str(result.get("status") or "COMPLETED").upper()
        if status in {"FAILED", "UNAVAILABLE", "REFUSED"}:
            mission.status = MissionStatus.FAILED
            mission.error = str(result.get("error") or status)
        elif status == "DISABLED":
            mission.status = MissionStatus.DISABLED
            mission.error = str(result.get("error") or status)
        else:
            mission.status = MissionStatus.COMPLETED
            mission.progress = 1.0
        if result.get("runId"):
            mission.run_id = str(result["runId"])
        for job_id in result.get("jobIds") or []:
            if job_id not in mission.job_ids:
                mission.job_ids.append(str(job_id))
        return result

    def _run_orchestrator(
        self,
        mission: AgentMission,
        agent: AgentDefinition,
        *,
        depth: int,
        use_jobs: bool,
    ) -> dict[str, Any]:
        orch = agent.orchestrator or OrchestratorConfig()
        if depth >= orch.max_delegation_depth:
            raise AgentFleetError(
                "DELEGATION_DEPTH",
                f"Max delegation depth {orch.max_delegation_depth} exceeded",
                http_status=422,
            )
        self._validate_orchestrator(orch, self_id=agent.agent_id, role=agent.role)
        if orch.strategy == "parallel_bounded":
            return self._run_orchestrator_parallel(mission, agent, orch, depth=depth, use_jobs=use_jobs)
        return self._run_orchestrator_sequential(mission, agent, orch, depth=depth, use_jobs=use_jobs)

    def _launch_child(
        self,
        mission: AgentMission,
        member_id: str,
        *,
        depth: int,
        use_jobs: bool,
    ) -> AgentMission:
        parent_lineage = list((mission.metadata or {}).get("delegation_lineage") or [])
        if mission.agent_id and mission.agent_id not in parent_lineage:
            parent_lineage.append(mission.agent_id)
        parent_authority = str(
            (mission.metadata or {}).get("authority_ceiling")
            or (mission.metadata or {}).get("parent_authority")
            or "MEDIUM"
        )
        parent_budget = dict((mission.metadata or {}).get("remaining_budget") or {})
        max_depth = int((mission.metadata or {}).get("max_delegation_depth") or 0)
        if max_depth <= 0:
            try:
                parent_agent = self.get_agent(mission.agent_id)
                if parent_agent.orchestrator is not None:
                    max_depth = int(parent_agent.orchestrator.max_delegation_depth)
            except Exception:  # noqa: BLE001
                max_depth = 3
        if max_depth <= 0:
            max_depth = 3
        decision = self.governor.authorize(
            parent_run_id=mission.run_id or mission.mission_id,
            agent_kind=member_id,
            child_id=f"{mission.mission_id}:{member_id}:{depth + 1}",
            parent_authority=parent_authority,
            requested_authority=parent_authority,
            delegation_depth=depth,
            max_delegation_depth=max_depth,
            remaining_parent_budget=parent_budget or {"slots": max(1, max_depth - depth)},
            lineage=parent_lineage,
            conversation_id=str((mission.metadata or {}).get("conversation_id") or "") or None,
            memory_scope="AGENT_PRIVATE",
            shared_orchestrator_scope=mission.mission_id,
        )
        if not decision.allowed or decision.frame is None:
            violation = decision.violation.value if decision.violation else "REFUSED"
            failed = AgentMission(
                mission_id=AgentFleetStore.new_id("msn"),
                agent_id=member_id,
                title=f"{mission.title} → {member_id} (refused)",
                request=mission.request,
                status=MissionStatus.FAILED,
                priority=mission.priority,
                progress=0.0,
                parent_mission_id=mission.mission_id,
                created_at=utc_now(),
                updated_at=utc_now(),
                error=f"DELEGATION_{violation}: {decision.reason}",
                metadata={
                    "governance": decision.public_dict(),
                    "depth": depth + 1,
                },
            )
            # Persist refused child for audit without executing side effects.
            self.store.create_mission(failed)
            return failed
        frame = decision.frame
        try:
            child = self.launch_mission(
                agent_id=member_id,
                request=mission.request,
                title=f"{mission.title} → {member_id}",
                priority=mission.priority,
                use_jobs=use_jobs,
                dry_run=False,
                parent_mission_id=mission.mission_id,
                depth=frame.delegation_depth,
                metadata={
                    "delegation_lineage": list(frame.lineage),
                    "authority_ceiling": frame.child_authority,
                    "parent_authority": frame.parent_authority,
                    "remaining_budget": dict(frame.child_budget),
                    "max_delegation_depth": frame.max_delegation_depth,
                    "parent_run_id": frame.parent_run_id,
                    "memory_scope": frame.memory_scope,
                    "shared_orchestrator_scope": frame.shared_orchestrator_scope,
                    "governance": frame.public_dict(),
                },
            )
            return child
        finally:
            self.governor.close(frame.child_id)

    def _run_orchestrator_sequential(
        self,
        mission: AgentMission,
        agent: AgentDefinition,
        orch: OrchestratorConfig,
        *,
        depth: int,
        use_jobs: bool,
    ) -> dict[str, Any]:
        child_results: list[dict[str, Any]] = []
        for member_id in orch.member_agent_ids:
            if mission.cancel_requested:
                mission.status = MissionStatus.CANCELLED
                break
            child = self._launch_child(mission, member_id, depth=depth, use_jobs=use_jobs)
            child_results.append(child.public_dict())
            mission.job_ids.extend(child.job_ids)
            mission.progress = min(0.95, len(child_results) / max(1, len(orch.member_agent_ids)))
            mission.updated_at = utc_now()
            self.store.update_mission(mission)
            if child.status in {MissionStatus.FAILED, MissionStatus.DISABLED, MissionStatus.INTERRUPTED}:
                if orch.failure_strategy == "fail_fast":
                    mission.status = MissionStatus.FAILED
                    mission.error = child.error or f"Child mission failed: {child.mission_id}"
                    break
        else:
            if mission.status == MissionStatus.RUNNING:
                mission.status = MissionStatus.COMPLETED
                mission.progress = 1.0
        return {
            "orchestrator": True,
            "strategy": orch.strategy,
            "children": child_results,
            "truth": {
                "orchestrator_uses_shared_gateway": True,
                "no_private_orchestrator_execution": True,
            },
        }

    def _run_orchestrator_parallel(
        self,
        mission: AgentMission,
        agent: AgentDefinition,
        orch: OrchestratorConfig,
        *,
        depth: int,
        use_jobs: bool,
    ) -> dict[str, Any]:
        """Bounded parallel member delegation — still uses shared AgentRuntime/gateway."""
        members = list(orch.member_agent_ids)
        child_results: list[dict[str, Any]] = []
        failed = False
        workers = max(1, min(orch.parallelism_limit, len(members) or 1))

        def _run_one(member_id: str) -> AgentMission:
            return self._launch_child(mission, member_id, depth=depth, use_jobs=use_jobs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_one, mid): mid for mid in members}
            for fut in concurrent.futures.as_completed(futures):
                if mission.cancel_requested:
                    mission.status = MissionStatus.CANCELLED
                    break
                child = fut.result()
                child_results.append(child.public_dict())
                mission.job_ids.extend(child.job_ids)
                mission.progress = min(0.95, len(child_results) / max(1, len(members)))
                mission.updated_at = utc_now()
                self.store.update_mission(mission)
                if child.status in {MissionStatus.FAILED, MissionStatus.DISABLED, MissionStatus.INTERRUPTED}:
                    if orch.failure_strategy == "fail_fast":
                        failed = True
                        mission.status = MissionStatus.FAILED
                        mission.error = child.error or f"Child mission failed: {child.mission_id}"
                        # Cancel remaining futures best-effort (in-flight children finish).
                        for pending in futures:
                            pending.cancel()
                        break

        if mission.status == MissionStatus.RUNNING and not failed:
            mission.status = MissionStatus.COMPLETED
            mission.progress = 1.0
        return {
            "orchestrator": True,
            "strategy": orch.strategy,
            "parallelismLimit": orch.parallelism_limit,
            "children": child_results,
            "truth": {
                "orchestrator_uses_shared_gateway": True,
                "no_private_orchestrator_execution": True,
                "parallel_bounded_uses_thread_pool": True,
            },
        }

    def cancel_mission(self, mission_id: str) -> AgentMission:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise AgentFleetError("MISSION_NOT_FOUND", f"Mission not found: {mission_id}", http_status=404)
        if mission.status.value not in ACTIVE_MISSION_STATUSES and mission.status != MissionStatus.QUEUED:
            # Idempotent cancel on terminals
            return mission
        mission.cancel_requested = True
        if mission.status == MissionStatus.QUEUED:
            mission.status = MissionStatus.CANCELLED
            mission.finished_at = utc_now()
        else:
            mission.status = MissionStatus.CANCELLING
        mission.updated_at = utc_now()
        self.store.update_mission(mission)
        # Best-effort cancel child missions
        for child in self.store.list_missions(limit=200):
            if child.parent_mission_id == mission_id and child.status.value in ACTIVE_MISSION_STATUSES:
                child.cancel_requested = True
                child.status = MissionStatus.CANCELLED
                child.finished_at = utc_now()
                child.updated_at = child.finished_at
                self.store.update_mission(child)
        if mission.status == MissionStatus.CANCELLING:
            mission.status = MissionStatus.CANCELLED
            mission.finished_at = utc_now()
            mission.updated_at = mission.finished_at
            self.store.update_mission(mission)
        self._emit(
            agent_id=mission.agent_id,
            mission_id=mission.mission_id,
            category="tasks",
            message="Mission cancelled",
            level="warn",
        )
        return mission

    def reconcile(self) -> list[str]:
        """Mark stale active missions interrupted when feature is off or process restarted.

        When workers are externalized, QUEUED missions are left for the agents pool
        (re-enqueued via :meth:`enqueue_queued_missions` / :meth:`start_background`).
        RUNNING/STARTING rows are assumed owned by leased ``agent.advance`` jobs.
        """
        updated: list[str] = []
        externalized = self._runners_externalized()
        for mission in self.store.list_missions(limit=500):
            if mission.status.value not in ACTIVE_MISSION_STATUSES:
                continue
            if externalized and mission.status in {
                MissionStatus.QUEUED,
                MissionStatus.STARTING,
                MissionStatus.RUNNING,
                MissionStatus.CANCELLING,
            }:
                continue
            # In-process fleet executes synchronously; leftover active rows after
            # restart are orphaned truth.
            mission.status = MissionStatus.INTERRUPTED
            mission.error = mission.error or "Interrupted — no live worker ownership after restart"
            mission.finished_at = utc_now()
            mission.updated_at = mission.finished_at
            self.store.update_mission(mission)
            updated.append(mission.mission_id)
            self._emit(
                agent_id=mission.agent_id,
                mission_id=mission.mission_id,
                category="system",
                message="Reconciled orphaned mission → interrupted",
                level="warn",
            )
        return updated

    def fleet_summary(self) -> dict[str, Any]:
        agents = self.list_agents(include_archived=False)
        missions = self.store.list_missions(limit=200)
        by_health: dict[str, int] = {}
        system_count = 0
        user_count = 0
        agent_type_count = 0
        orchestrator_count = 0
        for agent in agents:
            by_health[agent.health.value] = by_health.get(agent.health.value, 0) + 1
            ownership = classify_fleet_agent(agent)
            if ownership["origin"] == "system":
                system_count += 1
            else:
                user_count += 1
            if ownership["entityType"] == "orchestrator":
                orchestrator_count += 1
            else:
                agent_type_count += 1
        architecture_entries = self.system_inventory.list_entries()
        architecture_count = sum(1 for e in architecture_entries if e.entity_type == "architecture")
        # Architecture orchestrators (cognitive runtime, research service, …)
        system_orchestrator_extra = sum(
            1 for e in architecture_entries if e.entity_type == "orchestrator"
        )
        active = sum(1 for m in missions if m.status.value in ACTIVE_MISSION_STATUSES)
        return {
            "agentsEnabled": self.runtime.agents_enabled,
            "agentCount": len(agents),
            "orchestratorCount": orchestrator_count,
            "total": len(agents) + len(architecture_entries),
            "system": system_count + len(architecture_entries),
            "user": user_count,
            "agents": agent_type_count,
            "orchestrators": orchestrator_count + system_orchestrator_extra,
            "architecture": architecture_count,
            "health": by_health,
            "idle": by_health.get("idle", 0),
            "busy": by_health.get("busy", 0),
            "disabled": by_health.get("disabled", 0),
            "error": by_health.get("error", 0),
            "active": by_health.get("busy", 0),
            "activeMissions": active,
            "recentMissions": len(missions),
            "truth": {
                "health_from_mission_store": True,
                "no_fake_fleet_metrics": True,
                "architecture_not_counted_as_missions": True,
            },
        }

    def list_system_inventory(self) -> list[dict[str, Any]]:
        return [e.public_dict() for e in self.system_inventory.list_entries()]

    def list_roster(
        self,
        *,
        include_archived: bool = False,
        include_architecture: bool = True,
        origin: str | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any]:
        """Unified USER+SYSTEM roster. Architecture entries are descriptors only."""
        agents = self.list_agents(include_archived=include_archived)
        entries: list[dict[str, Any]] = []
        for agent in agents:
            payload = agent.public_dict()
            entries.append(payload)
        if include_architecture:
            for arch in self.system_inventory.list_entries():
                entries.append(arch.public_dict())
        origin_filter = (origin or "").strip().lower() or None
        type_filter = (entity_type or "").strip().lower() or None
        if origin_filter in {"system", "user"}:
            entries = [e for e in entries if str(e.get("origin")) == origin_filter]
        if type_filter in {"agent", "orchestrator", "architecture"}:
            entries = [e for e in entries if str(e.get("entityType")) == type_filter]
        # Deterministic order: SYSTEM first, then entity type, then name.
        type_rank = {"orchestrator": 0, "agent": 1, "architecture": 2}
        entries.sort(
            key=lambda e: (
                0 if e.get("origin") == "system" else 1,
                type_rank.get(str(e.get("entityType")), 9),
                str(e.get("name") or "").lower(),
                str(e.get("id") or e.get("agentId") or ""),
            )
        )
        # Deduplicate by id (architecture IDs never collide with agent_* ids).
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for entry in entries:
            eid = str(entry.get("id") or entry.get("agentId") or "")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            unique.append(entry)
        return {
            "entries": unique,
            "agents": [a.public_dict() for a in agents],
            "system": self.list_system_inventory() if include_architecture else [],
            "summary": self.fleet_summary(),
            "truth": {
                "architecture_not_persisted_as_agent_definitions": True,
                "system_origin_from_backend": True,
            },
        }

    def enable_all_user_agents(self) -> dict[str, Any]:
        """Enable mutable USER fleet agents (not SYSTEM / architecture)."""
        changed: list[str] = []
        skipped: list[dict[str, str]] = []
        for agent in self.list_agents(include_archived=False):
            ownership = classify_fleet_agent(agent)
            if ownership.get("origin") == "system" or ownership.get("mutable") is False:
                skipped.append({"agentId": agent.agent_id, "reason": "system_protected"})
                continue
            if agent.enabled:
                skipped.append({"agentId": agent.agent_id, "reason": "already_enabled"})
                continue
            self.set_enabled(agent.agent_id, True)
            changed.append(agent.agent_id)
        return {
            "changed": changed,
            "skipped": skipped,
            "truth": {"system_agents_never_mutated": True},
        }

    def disable_all_user_agents(self) -> dict[str, Any]:
        """Disable mutable USER fleet agents (pause launch intake for those agents)."""
        changed: list[str] = []
        skipped: list[dict[str, str]] = []
        for agent in self.list_agents(include_archived=False):
            ownership = classify_fleet_agent(agent)
            if ownership.get("origin") == "system" or ownership.get("mutable") is False:
                skipped.append({"agentId": agent.agent_id, "reason": "system_protected"})
                continue
            if not agent.enabled:
                skipped.append({"agentId": agent.agent_id, "reason": "already_disabled"})
                continue
            self.set_enabled(agent.agent_id, False)
            changed.append(agent.agent_id)
        return {
            "changed": changed,
            "skipped": skipped,
            "truth": {"system_agents_never_mutated": True},
        }

    def dashboard(
        self,
        *,
        window_hours: int = 24,
        failure_window_hours: int = 168,
        workers_payload: dict[str, Any] | None = None,
        jobs_by_pool: dict[str, dict[str, int]] | None = None,
        memory_writeback_count: int | None = None,
    ) -> dict[str, Any]:
        """Operator dashboard read-model — aggregates only, no new state store."""
        from .dashboard import build_agents_dashboard

        agents = self.list_agents(include_archived=False)
        missions = self.store.list_missions(limit=500)
        architecture = self.list_system_inventory()
        return build_agents_dashboard(
            agents=agents,
            missions=missions,
            architecture_entries=architecture,
            agents_enabled=bool(self.runtime.agents_enabled),
            workers_payload=workers_payload,
            jobs_by_pool=jobs_by_pool,
            memory_writeback_count=memory_writeback_count,
            window_hours=window_hours,
            failure_window_hours=failure_window_hours,
        )
