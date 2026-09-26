"""Agent fleet + orchestrator HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.agents import AgentKind
from Data.modules.agents.fleet import AgentFleetError, AgentFleetService


def _raise(exc: AgentFleetError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class AgentExecuteRequest(BaseModel):
    request: str = Field(min_length=1, max_length=30_000)
    kind: str = "GENERIC"
    use_jobs: bool = False
    conversation_id: str | None = None
    capability_overrides: dict = Field(default_factory=dict)


class MultiAgentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=30_000)
    kinds: list[str] = Field(default_factory=lambda: ["RESEARCH", "GENERIC"])
    capability_overrides: dict = Field(default_factory=dict)


class AgentCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "generic"
    description: str = ""
    role: str = ""
    enabled: bool = True
    modelRef: str | None = None
    systemPolicy: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    knowledgeSources: list[str] = Field(default_factory=list)
    memoryPolicy: str = "default"
    datasetAccess: str = "none"
    approvalMode: str = "inherit"
    autonomy: int = Field(default=50, ge=0, le=100)
    maxConcurrency: int = Field(default=1, ge=1, le=32)
    timeoutS: int | None = Field(default=None, ge=1, le=86_400)
    maxRetries: int = Field(default=0, ge=0, le=10)
    tokenBudget: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list)
    orchestrator: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = None
    description: str | None = None
    role: str | None = None
    enabled: bool | None = None
    modelRef: str | None = None
    systemPolicy: str | None = None
    capabilities: list[str] | None = None
    knowledgeSources: list[str] | None = None
    memoryPolicy: str | None = None
    datasetAccess: str | None = None
    approvalMode: str | None = None
    autonomy: int | None = Field(default=None, ge=0, le=100)
    maxConcurrency: int | None = Field(default=None, ge=1, le=32)
    timeoutS: int | None = Field(default=None, ge=1, le=86_400)
    maxRetries: int | None = Field(default=None, ge=0, le=10)
    tokenBudget: int | None = Field(default=None, ge=1)
    tags: list[str] | None = None
    orchestrator: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class MissionLaunchBody(BaseModel):
    request: str = Field(min_length=1, max_length=30_000)
    title: str | None = Field(default=None, max_length=200)
    priority: str = Field(default="med", max_length=16)
    useJobs: bool = False
    dryRun: bool = False


def build_agents_router(
    fleet: AgentFleetService,
    *,
    job_runtime: Any | None = None,
    database_path: Any | None = None,
    agent_runtime: Any | None = None,
    multi_agents: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agents"])

    if agent_runtime is not None:

        @router.post("/api/agents/execute")
        def execute_agent(payload: AgentExecuteRequest) -> dict:
            try:
                kind = AgentKind(payload.kind.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid agent kind: {payload.kind}") from exc
            result = agent_runtime.execute(
                payload.request,
                kind=kind,
                use_jobs=payload.use_jobs,
                conversation_id=payload.conversation_id,
                capability_overrides=payload.capability_overrides or None,
            )
            if result.status == "DISABLED":
                raise HTTPException(status_code=403, detail=result.public_dict())
            return {"agent": result.public_dict()}

    if multi_agents is not None:

        @router.post("/api/agents/multi")
        def execute_multi_agent(payload: MultiAgentRequest) -> dict:
            kinds: list[AgentKind] = []
            for raw in payload.kinds:
                try:
                    kinds.append(AgentKind(raw.upper()))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"Invalid agent kind: {raw}") from exc
            result = multi_agents.run(
                payload.request,
                kinds=kinds,
                capability_overrides=payload.capability_overrides or None,
            )
            if result.status == "DISABLED":
                raise HTTPException(status_code=403, detail=result.public_dict())
            return {"multi_agent": result.public_dict()}

    def _workers_payload() -> dict | None:
        if database_path is None:
            return None
        try:
            from Data.modules.workers.pools import POOL_CATALOG
            from Data.modules.workers.protocol import SupervisorHealth
            from Data.modules.workers.registry import WorkerRegistry
            from Data.modules.workers.settings import load_worker_settings

            registry = WorkerRegistry(database_path)
            registry.initialize()
            workers = registry.list()
            wsettings = load_worker_settings()
            overrides = registry.list_pool_desired_overrides()
            lease = registry.get_supervisor_lease() or {}
            health = lease.get("health_state") or SupervisorHealth.UNAVAILABLE.value
            pools = []
            for pid, defn in POOL_CATALOG.items():
                desired = overrides.get(pid)
                if desired is None:
                    desired = wsettings.desired_count(pid)
                regs = [w for w in workers if w.pool_id == pid]
                pools.append(
                    {
                        **defn.public_dict(),
                        "desired": desired,
                        "instances": len(regs),
                        "ready": sum(1 for r in regs if r.state.value == "READY"),
                        "busy": sum(1 for r in regs if r.state.value == "BUSY"),
                        "draining": sum(1 for r in regs if r.state.value == "DRAINING"),
                        "degraded": sum(1 for r in regs if r.state.value == "DEGRADED"),
                        "workers": [r.public_dict() for r in regs],
                    }
                )
            return {
                "workers": [w.public_dict() for w in workers],
                "pools": pools,
                "supervisor": {"health": health, "degraded_reason": lease.get("degraded_reason")},
            }
        except Exception:  # noqa: BLE001 — dashboard soft-degrades workers
            return None

    def _jobs_by_pool() -> dict[str, dict[str, int]] | None:
        if job_runtime is None:
            return None
        try:
            from Data.modules.agents.dashboard import collect_job_pool_stats

            return collect_job_pool_stats(job_runtime.list, limit=500)
        except Exception:  # noqa: BLE001
            return None

    @router.get("/api/agents/dashboard")
    def agents_dashboard(
        windowHours: int = Query(default=24, ge=1, le=168),
        failureWindowHours: int = Query(default=168, ge=1, le=720),
    ) -> dict:
        """Truthful Agents page read-model (aggregates only)."""
        memory_writeback: int | None = None
        try:
            if getattr(fleet, "signal_fabric", None) is not None:
                # MEMORY_CANDIDATE / completed memory signals in window if fabric exposes metrics.
                metrics = fleet.signal_fabric.metrics(window_minutes=max(60, windowHours * 60))
                by_type = (metrics or {}).get("byType") or {}
                mem = by_type.get("MEMORY_CANDIDATE")
                if mem is not None:
                    memory_writeback = int(mem)
        except Exception:  # noqa: BLE001
            memory_writeback = None
        payload = fleet.dashboard(
            window_hours=windowHours,
            failure_window_hours=failureWindowHours,
            workers_payload=_workers_payload(),
            jobs_by_pool=_jobs_by_pool(),
            memory_writeback_count=memory_writeback,
        )
        return payload

    @router.post("/api/agents/fleet/start-all")
    def fleet_start_all() -> dict:
        """Enable eligible USER fleet agents. SYSTEM components remain protected."""
        return fleet.enable_all_user_agents()

    @router.post("/api/agents/fleet/pause-all")
    def fleet_pause_all() -> dict:
        """Disable eligible USER fleet agents. SYSTEM components remain protected."""
        return fleet.disable_all_user_agents()

    @router.get("/api/agents")
    def list_agents(
        includeArchived: bool = False,
        kind: str | None = None,
        includeSystem: bool = True,
    ) -> dict:
        """List fleet agents. When includeSystem=true (default), also attach system inventory."""
        agents = fleet.list_agents(include_archived=includeArchived, kind=kind)
        payload: dict[str, Any] = {
            "agents": [a.public_dict() for a in agents],
            "summary": fleet.fleet_summary(),
        }
        if includeSystem:
            payload["system"] = fleet.list_system_inventory()
            payload["truth"] = {
                "system_origin_from_backend": True,
                "architecture_not_persisted_as_agent_definitions": True,
            }
        return payload

    @router.get("/api/agents/roster")
    def agents_roster(
        includeArchived: bool = False,
        includeArchitecture: bool = True,
        origin: str | None = None,
        entityType: str | None = None,
    ) -> dict:
        """Unified USER + SYSTEM roster (agents, orchestrators, architecture)."""
        return fleet.list_roster(
            include_archived=includeArchived,
            include_architecture=includeArchitecture,
            origin=origin,
            entity_type=entityType,
        )

    @router.get("/api/agents/system")
    def list_system_components() -> dict:
        """Read-only SYSTEM architecture / orchestrator inventory."""
        return {
            "system": fleet.list_system_inventory(),
            "summary": fleet.fleet_summary(),
            "truth": {
                "not_agent_definitions": True,
                "status_from_runtime_probe": True,
            },
        }

    @router.get("/api/agents/summary")
    def agents_summary() -> dict:
        return {"summary": fleet.fleet_summary()}

    @router.get("/api/agents/dataset-learning")
    def dataset_learning_status() -> dict:
        """Dataset Learning system agent + live dataset index job activity."""
        return fleet.dataset_learning_status()

    @router.get("/api/agents/missions")
    def list_missions(
        agentId: str | None = None,
        status: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        missions = fleet.store.list_missions(agent_id=agentId, status=status, limit=limit)
        return {"missions": [m.public_dict() for m in missions]}

    @router.get("/api/agents/missions/{mission_id}")
    def get_mission(mission_id: str) -> dict:
        mission = fleet.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "MISSION_NOT_FOUND", "message": mission_id},
            )
        children = [
            c.public_dict()
            for c in fleet.store.list_missions(limit=200)
            if c.parent_mission_id == mission_id
        ]
        events = [e.public_dict() for e in fleet.store.list_events(mission_id=mission_id, limit=100)]
        return {"mission": mission.public_dict(), "children": children, "events": events}

    @router.post("/api/agents/missions/{mission_id}/cancel")
    def cancel_mission(mission_id: str) -> dict:
        try:
            mission = fleet.cancel_mission(mission_id)
        except AgentFleetError as exc:
            _raise(exc)
        return {"mission": mission.public_dict()}

    @router.get("/api/agents/events")
    def list_events(
        agentId: str | None = None,
        missionId: str | None = None,
        category: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        events = fleet.store.list_events(
            agent_id=agentId,
            mission_id=missionId,
            category=category,
            limit=limit,
        )
        return {"events": [e.public_dict() for e in events]}

    @router.post("/api/agents/reconcile")
    def reconcile_agents() -> dict:
        updated = fleet.reconcile()
        return {"updated": updated, "count": len(updated)}

    @router.post("/api/agents")
    def create_agent(payload: AgentCreateBody) -> dict:
        try:
            agent = fleet.create_agent(payload.model_dump())
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict:
        try:
            agent = fleet.get_agent(agent_id)
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.patch("/api/agents/{agent_id}")
    def update_agent(agent_id: str, payload: AgentUpdateBody) -> dict:
        try:
            agent = fleet.update_agent(agent_id, payload.model_dump(exclude_unset=True))
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.post("/api/agents/{agent_id}/clone")
    def clone_agent(agent_id: str) -> dict:
        try:
            agent = fleet.clone_agent(agent_id)
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.post("/api/agents/{agent_id}/enable")
    def enable_agent(agent_id: str) -> dict:
        try:
            agent = fleet.set_enabled(agent_id, True)
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.post("/api/agents/{agent_id}/disable")
    def disable_agent(agent_id: str) -> dict:
        try:
            agent = fleet.set_enabled(agent_id, False)
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.post("/api/agents/{agent_id}/archive")
    def archive_agent(agent_id: str) -> dict:
        try:
            agent = fleet.archive_agent(agent_id)
        except AgentFleetError as exc:
            _raise(exc)
        return {"agent": agent.public_dict()}

    @router.post("/api/agents/{agent_id}/missions")
    def launch_mission(agent_id: str, payload: MissionLaunchBody) -> dict:
        try:
            mission = fleet.launch_mission(
                agent_id=agent_id,
                request=payload.request,
                title=payload.title,
                priority=payload.priority,
                use_jobs=payload.useJobs,
                dry_run=payload.dryRun,
            )
        except AgentFleetError as exc:
            _raise(exc)
        return {"mission": mission.public_dict()}

    return router
