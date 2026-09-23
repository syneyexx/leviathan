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
from .runtime import AgentRuntime
from .store import AgentFleetStore, utc_now
from .types import AgentKind


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
    },
    {
        "name": "Coding",
        "kind": "coding",
        "role": "Implementation & Verify",
        "description": "Coding control plane via shared filesystem capabilities.",
        "capabilities": ["file.read", "file.inspect_csv"],
        "tags": ["code", "tests", "refactor"],
        "model_ref": None,
    },
    {
        "name": "Critic",
        "kind": "specialist",
        "role": "Review & Guardrails",
        "description": "Reviewer agent — still uses shared gateway for privileged actions.",
        "capabilities": ["knowledge.search"],
        "tags": ["review", "qa", "policy"],
        "model_ref": None,
    },
    {
        "name": "Planner",
        "kind": "orchestrator",
        "role": "Goals & Decomposition",
        "description": "Orchestrator that delegates to member agents without private execution.",
        "capabilities": [],
        "tags": ["plan", "delegate", "roadmap"],
        "model_ref": None,
        "orchestrator": {
            "memberAgentIds": [],
            "strategy": "sequential",
            "maxDelegationDepth": 3,
            "parallelismLimit": 2,
            "failureStrategy": "fail_fast",
        },
    },
]


class AgentFleetService:
    def __init__(self, store: AgentFleetStore, runtime: AgentRuntime) -> None:
        self.store = store
        self.runtime = runtime

    def initialize(self, *, seed_defaults: bool = True) -> None:
        self.store.initialize()
        if seed_defaults and not self.store.list_definitions(limit=1):
            self._seed_defaults()

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
                orchestrator=orch,
                health=AgentHealth.IDLE if True else AgentHealth.UNKNOWN,
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
                for name in ("research", "coding", "critic")
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
        active = self.store.count_active_for_agent(agent.agent_id)
        if active > 0:
            agent.health = AgentHealth.BUSY
            agent.health_reason = f"{active} active mission(s)"
        else:
            agent.health = AgentHealth.IDLE
            agent.health_reason = None
        return agent

    def _validate_orchestrator(self, orch: OrchestratorConfig, *, self_id: str | None = None) -> None:
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
            if member.kind == AgentDefinitionKind.ORCHESTRATOR:
                # Nested orchestrators count against depth; disallow deep graphs here.
                nested = member.orchestrator.member_agent_ids if member.orchestrator else []
                if self_id and self_id in nested:
                    raise AgentFleetError("ORCHESTRATOR_CYCLE", "Cycle detected in orchestrator graph")

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
            self._validate_orchestrator(orch)
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
            metadata=dict(payload.get("metadata") or {}),
        )
        self.store.create_definition(definition)
        self._emit(agent_id=definition.agent_id, category="agents", message=f"Created agent {definition.name}")
        return self._refresh_health(definition)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> AgentDefinition:
        current = self.get_agent(agent_id)
        if current.archived and not payload.get("unarchive"):
            raise AgentFleetError("AGENT_ARCHIVED", "Cannot update archived agent", http_status=409)
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
        if updated.kind == AgentDefinitionKind.ORCHESTRATOR:
            orch_payload = payload.get("orchestrator")
            if orch_payload is not None:
                updated.orchestrator = OrchestratorConfig.from_dict(orch_payload)
            if updated.orchestrator is None:
                updated.orchestrator = OrchestratorConfig()
            self._validate_orchestrator(updated.orchestrator, self_id=updated.agent_id)
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
        if source.orchestrator:
            payload["orchestrator"] = source.orchestrator.public_dict()
        return self.create_agent(payload)

    def set_enabled(self, agent_id: str, enabled: bool) -> AgentDefinition:
        return self.update_agent(agent_id, {"enabled": enabled})

    def archive_agent(self, agent_id: str) -> AgentDefinition:
        agent = self.get_agent(agent_id)
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
            metadata={"dryRun": dry_run, "depth": depth},
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

        return self._execute_mission(mission, agent, depth=depth, use_jobs=use_jobs)

    def _plan_payload(self, agent: AgentDefinition, request: str, *, depth: int) -> dict[str, Any]:
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
            if agent.kind == AgentDefinitionKind.ORCHESTRATOR:
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
        return mission

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
        self._validate_orchestrator(orch, self_id=agent.agent_id)
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
        return self.launch_mission(
            agent_id=member_id,
            request=mission.request,
            title=f"{mission.title} → {member_id}",
            priority=mission.priority,
            use_jobs=use_jobs,
            dry_run=False,
            parent_mission_id=mission.mission_id,
            depth=depth + 1,
        )

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
        """Mark stale active missions interrupted when feature is off or process restarted."""
        updated: list[str] = []
        for mission in self.store.list_missions(limit=500):
            if mission.status.value not in ACTIVE_MISSION_STATUSES:
                continue
            # In-process fleet currently executes synchronously; any leftover active
            # row after restart is orphaned truth.
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
        for agent in agents:
            by_health[agent.health.value] = by_health.get(agent.health.value, 0) + 1
        active = sum(1 for m in missions if m.status.value in ACTIVE_MISSION_STATUSES)
        return {
            "agentsEnabled": self.runtime.agents_enabled,
            "agentCount": len(agents),
            "orchestratorCount": sum(1 for a in agents if a.kind == AgentDefinitionKind.ORCHESTRATOR),
            "health": by_health,
            "activeMissions": active,
            "recentMissions": len(missions),
            "truth": {
                "health_from_mission_store": True,
                "no_fake_fleet_metrics": True,
            },
        }
