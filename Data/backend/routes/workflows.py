"""Workflow control-plane HTTP routes — definitions, versions, executions, overview."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.workflows import WorkflowStepDef
from Data.modules.workflows.graph import validate_graph
from Data.modules.workflows.overview import build_workflows_overview, definition_dependency_counts
from Data.modules.workflows.types import (
    WorkflowDefinitionStatus,
    WorkflowEdgeDef,
    WorkflowGraph,
    WorkflowLayoutNode,
    WorkflowNodeDef,
    WorkflowVariableDef,
)


class WorkflowCreateRequest(BaseModel):
    name: str = Field(default="workflow", min_length=1, max_length=120)
    run_id: str | None = None
    steps: list[dict] = Field(default_factory=list)
    # V2 additive fields
    description: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "DRAFT"
    graph: dict | None = None
    variables: list[dict] = Field(default_factory=list)
    layout: list[dict] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    from_template_id: str | None = None


class WorkflowPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    graph: dict | None = None
    variables: list[dict] | None = None
    layout: list[dict] | None = None
    config: dict | None = None
    trigger_bindings: list[dict] | None = None
    revision: int | None = None
    change_summary: str = ""


class WorkflowRunRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)
    idempotency_key: str | None = None


class WorkflowResumeApprovalRequest(BaseModel):
    approval_id: str | None = None
    decision: str = "approved"


class WorkflowDuplicateRequest(BaseModel):
    name: str | None = None


class WorkflowRestoreVersionRequest(BaseModel):
    version: int = Field(ge=1)


def _parse_graph(raw: dict | None, steps: list[dict] | None = None) -> WorkflowGraph | None:
    if raw:
        return WorkflowGraph.from_dict(raw)
    if steps:
        from Data.modules.workflows.graph import steps_to_graph

        step_defs = [
            WorkflowStepDef(
                step_id=str(item.get("step_id") or f"step-{idx}"),
                capability_id=str(item.get("capability_id") or ""),
                arguments=dict(item.get("arguments") or {}),
                approval_id=item.get("approval_id"),
            )
            for idx, item in enumerate(steps)
            if item.get("capability_id")
        ]
        return steps_to_graph(step_defs)
    return None


def _parse_variables(raw: list[dict] | None) -> list[WorkflowVariableDef]:
    return [WorkflowVariableDef.from_dict(v) for v in (raw or [])]


def _parse_layout(raw: list[dict] | None) -> list[WorkflowLayoutNode]:
    out: list[WorkflowLayoutNode] = []
    for item in raw or []:
        out.append(
            WorkflowLayoutNode(
                node_id=str(item.get("node_id") or ""),
                x=float(item.get("x") or 0),
                y=float(item.get("y") or 0),
            )
        )
    return out


def build_workflows_router(
    *,
    workflow_store: Any,
    workflow_runtime: Any,
    telemetry_sampler: Any | None = None,
    worker_registry: Any | None = None,
    capability_catalog: Any | None = None,
    schedule_store: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["workflows"])

    def _worker_stats() -> dict[str, Any] | None:
        if worker_registry is None:
            return None
        try:
            regs = list(worker_registry.list_workers() if hasattr(worker_registry, "list_workers") else [])
        except Exception:  # noqa: BLE001
            regs = []
        try:
            from Data.modules.workers.settings import WorkerSettings

            wsettings = WorkerSettings()
            desired = wsettings.desired_count("workflow")
        except Exception:  # noqa: BLE001
            desired = None
        busy = 0
        ready = 0
        for reg in regs:
            pool = getattr(reg, "pool_id", None) or getattr(reg, "pool", None)
            if pool and str(pool) != "workflow":
                continue
            state = getattr(getattr(reg, "state", None), "value", getattr(reg, "state", None))
            if str(state).upper() == "BUSY":
                busy += 1
            if str(state).upper() in {"READY", "IDLE"}:
                ready += 1
        capacity = desired if desired is not None else (busy + ready)
        return {
            "busy": busy,
            "desired": capacity,
            "ready": ready,
            "semantics": "BUSY workers / desired capacity for workflow pool",
        }

    def _enrich_definition(definition: Any) -> dict[str, Any]:
        payload = definition.public_dict()
        deps = definition_dependency_counts(definition, catalog=capability_catalog)
        payload.update(deps)
        stats = workflow_store.aggregate_execution_stats(workflow_id=definition.workflow_id)
        payload["execution_count"] = stats.get("total") or 0
        payload["avg_duration_ms"] = stats.get("avg_duration_ms")
        payload["running_executions"] = workflow_store.count_executions(
            workflow_id=definition.workflow_id,
            states=["QUEUED", "STARTING", "RUNNING", "WAITING", "WAITING_APPROVAL", "CANCELLING"],
        )
        if schedule_store is not None:
            try:
                schedules = [
                    s.public_dict()
                    for s in schedule_store.list(limit=100)
                    if (s.target_ref == definition.workflow_id)
                    or (s.target_payload or {}).get("workflow_id") == definition.workflow_id
                    or (s.target_payload or {}).get("definition_id") == definition.workflow_id
                ]
                payload["schedules"] = schedules
                payload["triggers"] = [
                    {"kind": "SCHEDULE", "schedule_id": s["schedule_id"], "status": s["status"]}
                    for s in schedules
                ] + list(definition.trigger_bindings or [])
            except Exception:  # noqa: BLE001
                payload["schedules"] = []
                payload["triggers"] = list(definition.trigger_bindings or [])
        else:
            payload["triggers"] = list(definition.trigger_bindings or [])
        return payload

    @router.get("/api/workflows/overview")
    def workflows_overview(
        chartHours: Annotated[int, Query(ge=1, le=168)] = 24,
        topDays: Annotated[int, Query(ge=1, le=90)] = 7,
    ) -> dict:
        telemetry = None
        if telemetry_sampler is not None:
            try:
                telemetry = telemetry_sampler.latest_public()
            except Exception:  # noqa: BLE001
                telemetry = None
        overview = build_workflows_overview(
            workflow_store,
            telemetry=telemetry,
            workers=_worker_stats(),
            chart_hours=chartHours,
            top_days=topDays,
        )
        return {"overview": overview}

    @router.get("/api/workflows/templates")
    def list_templates(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        templates = workflow_store.list_definitions(status="TEMPLATE", limit=limit, include_templates=True)
        # Only return templates whose referenced capabilities are known (or explicitly marked).
        out = []
        known: set[str] | None = None
        if capability_catalog is not None:
            try:
                known = {c.id for c in capability_catalog.list()}
            except Exception:  # noqa: BLE001
                known = None
        for item in templates:
            validation = validate_graph(item.graph, capability_ids=known)
            payload = _enrich_definition(item)
            payload["validation"] = validation
            payload["compatible"] = bool(validation.get("ok"))
            out.append(payload)
        return {"templates": out}

    @router.get("/api/workflows/palette")
    def workflow_palette() -> dict:
        """Assemble canvas palette from canonical capability / agent authorities."""
        agents: list[dict] = []
        tools: list[dict] = []
        data: list[dict] = []
        control = [
            {
                "id": "control.condition",
                "kind": "condition",
                "label": "Condition",
                "category": "Control",
                "available": True,
            },
            {
                "id": "control.loop",
                "kind": "loop",
                "label": "Loop",
                "category": "Control",
                "available": True,
            },
            {
                "id": "control.delay",
                "kind": "delay",
                "label": "Delay",
                "category": "Control",
                "available": True,
            },
            {
                "id": "control.trigger.manual",
                "kind": "trigger",
                "label": "Manual Trigger",
                "category": "Control",
                "available": True,
            },
            {
                "id": "control.trigger.schedule",
                "kind": "trigger",
                "label": "Schedule Trigger",
                "category": "Control",
                "available": schedule_store is not None,
                "reason": None if schedule_store is not None else "ScheduleStore unavailable",
            },
        ]
        if capability_catalog is not None:
            try:
                for cap in capability_catalog.list():
                    meta = getattr(cap, "metadata", None) or {}
                    item = {
                        "id": cap.id,
                        "kind": "capability",
                        "label": getattr(cap, "name", None) or cap.id,
                        "capability_id": cap.id,
                        "available": bool(getattr(cap, "available", True)),
                        "authorized": True,
                        "reason": getattr(cap, "availability_reason", None),
                        "category": str(meta.get("category") or meta.get("domain") or "Tools"),
                    }
                    cid = cap.id.lower()
                    if cid.startswith("agent.") or "agent" in str(meta.get("family") or "").lower():
                        item["kind"] = "agent"
                        item["category"] = "Agents"
                        agents.append(item)
                    elif any(
                        key in cid
                        for key in ("dataset", "knowledge", "vector", "database", "sql", "memory")
                    ):
                        item["category"] = "Data"
                        data.append(item)
                    else:
                        tools.append(item)
            except Exception:  # noqa: BLE001
                pass
        return {
            "palette": {
                "Agents": agents,
                "Tools": tools,
                "Data": data,
                "Control": control,
            }
        }

    @router.get("/api/workflows")
    def list_workflows(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        status: str | None = None,
        category: str | None = None,
        q: str | None = None,
        legacy: bool = False,
    ) -> dict:
        if legacy:
            return {"workflows": [item.public_dict() for item in workflow_store.list(limit=limit, offset=offset)]}
        definitions = workflow_store.list_definitions(
            limit=limit,
            offset=offset,
            status=status,
            category=category,
            query=q,
            include_templates=True,
        )
        return {"workflows": [_enrich_definition(item) for item in definitions]}

    @router.post("/api/workflows")
    def create_workflow(payload: WorkflowCreateRequest) -> dict:
        if payload.from_template_id:
            try:
                template = workflow_store.get_definition(payload.from_template_id)
                if template is None or template.status != WorkflowDefinitionStatus.TEMPLATE:
                    raise HTTPException(status_code=404, detail="Template not found")
                definition = workflow_store.duplicate_definition(
                    payload.from_template_id,
                    name=payload.name or f"Kopie van {template.name}",
                )
                if payload.status:
                    try:
                        definition.status = WorkflowDefinitionStatus(payload.status)
                        definition = workflow_store.save_definition(definition, create_version=False)
                    except ValueError:
                        pass
                return {"workflow": _enrich_definition(definition)}
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Template not found") from exc

        graph = _parse_graph(payload.graph, payload.steps)
        try:
            status = WorkflowDefinitionStatus(payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid status: {payload.status}") from exc
        if graph is None and not payload.steps:
            graph = WorkflowGraph(
                nodes=[
                    WorkflowNodeDef(
                        node_id="trigger-manual",
                        kind="trigger",
                        label="Manual",
                        config={"trigger_kind": "MANUAL"},
                    )
                ],
                edges=[],
            )
        try:
            if payload.steps and graph is None:
                steps = []
                for idx, raw in enumerate(payload.steps):
                    capability_id = raw.get("capability_id")
                    if not capability_id:
                        raise HTTPException(status_code=422, detail=f"Step {idx} missing capability_id")
                    steps.append(
                        WorkflowStepDef(
                            step_id=str(raw.get("step_id") or f"step-{idx}"),
                            capability_id=str(capability_id),
                            arguments=dict(raw.get("arguments") or {}),
                            approval_id=raw.get("approval_id"),
                        )
                    )
                # Legacy create returns execution-addressed record.
                record = workflow_runtime.create(name=payload.name, steps=steps, run_id=payload.run_id)
                return {"workflow": record.public_dict(), "mode": "legacy_execution"}
            definition = workflow_store.create_definition(
                name=payload.name,
                graph=graph,
                status=status,
                description=payload.description,
                category=payload.category,
                tags=payload.tags,
                variables=_parse_variables(payload.variables),
                layout=_parse_layout(payload.layout),
                config=payload.config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"workflow": _enrich_definition(definition)}

    @router.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict:
        definition = workflow_store.get_definition(workflow_id)
        if definition is not None:
            return {"workflow": _enrich_definition(definition)}
        record = workflow_store.get(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"workflow": record.public_dict()}

    @router.patch("/api/workflows/{workflow_id}")
    def patch_workflow(workflow_id: str, payload: WorkflowPatchRequest) -> dict:
        definition = workflow_store.get_definition(workflow_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if payload.name is not None:
            definition.name = payload.name.strip() or definition.name
        if payload.description is not None:
            definition.description = payload.description
        if payload.category is not None:
            definition.category = payload.category
        if payload.tags is not None:
            definition.tags = list(payload.tags)
        if payload.status is not None:
            try:
                definition.status = WorkflowDefinitionStatus(payload.status)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if payload.graph is not None:
            definition.graph = WorkflowGraph.from_dict(payload.graph)
        if payload.variables is not None:
            definition.variables = _parse_variables(payload.variables)
        if payload.layout is not None:
            definition.layout = _parse_layout(payload.layout)
        if payload.config is not None:
            definition.config = dict(payload.config)
        if payload.trigger_bindings is not None:
            definition.trigger_bindings = list(payload.trigger_bindings)
        known = None
        if capability_catalog is not None:
            try:
                known = {c.id for c in capability_catalog.list()}
            except Exception:  # noqa: BLE001
                known = None
        validation = validate_graph(definition.graph, variables=definition.variables, capability_ids=known)
        try:
            saved = workflow_store.save_definition(
                definition,
                expected_revision=payload.revision,
                change_summary=payload.change_summary or "update",
            )
        except ValueError as exc:
            code = str(exc)
            status = 409 if "CONFLICT" in code else 422
            raise HTTPException(status_code=status, detail={"code": code, "message": code}) from exc
        payload_out = _enrich_definition(saved)
        payload_out["validation"] = validation
        return {"workflow": payload_out}

    @router.delete("/api/workflows/{workflow_id}")
    def delete_workflow(
        workflow_id: str,
        hard: Annotated[bool, Query()] = False,
    ) -> dict:
        try:
            workflow_store.delete_definition(workflow_id, hard=hard)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "workflow_id": workflow_id, "hard": hard}

    @router.post("/api/workflows/{workflow_id}/duplicate")
    def duplicate_workflow(workflow_id: str, payload: WorkflowDuplicateRequest | None = None) -> dict:
        try:
            definition = workflow_store.duplicate_definition(
                workflow_id,
                name=(payload.name if payload else None),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        return {"workflow": _enrich_definition(definition)}

    @router.get("/api/workflows/{workflow_id}/versions")
    def list_versions(workflow_id: str, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        if workflow_store.get_definition(workflow_id) is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        versions = workflow_store.list_versions(workflow_id, limit=limit)
        return {"versions": [v.public_dict() for v in versions]}

    @router.post("/api/workflows/{workflow_id}/restore-version")
    def restore_version(workflow_id: str, payload: WorkflowRestoreVersionRequest) -> dict:
        try:
            definition = workflow_store.restore_version(workflow_id, payload.version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"workflow": _enrich_definition(definition)}

    @router.get("/api/workflows/{workflow_id}/executions")
    def list_workflow_executions(
        workflow_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        if workflow_store.get_definition(workflow_id) is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        items = workflow_store.list_executions(workflow_id=workflow_id, limit=limit, offset=offset)
        return {"executions": [e.public_dict() for e in items]}

    @router.get("/api/workflows/{workflow_id}/logs")
    def workflow_logs(
        workflow_id: str,
        executionId: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict:
        definition = workflow_store.get_definition(workflow_id)
        if definition is None and workflow_store.get_execution(workflow_id) is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        executions = []
        if executionId:
            item = workflow_store.get_execution(executionId)
            if item is None:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "LOGS_UNAVAILABLE", "message": "Execution not found"},
                )
            executions = [item]
        else:
            executions = workflow_store.list_executions(workflow_id=workflow_id, limit=min(limit, 20))
        events: list[dict] = []
        for execution in executions:
            events.append(
                {
                    "timestamp": execution.created_at,
                    "severity": "info",
                    "node": None,
                    "execution_id": execution.execution_id,
                    "message": f"Execution started ({execution.trigger_source})",
                }
            )
            for receipt in execution.node_results or []:
                events.append(
                    {
                        "timestamp": execution.updated_at,
                        "severity": "error"
                        if str(receipt.get("status") or "").upper() in {"FAILED", "CANCELLED"}
                        else "info",
                        "node": receipt.get("node_id") or receipt.get("step_id"),
                        "execution_id": execution.execution_id,
                        "job_id": (receipt.get("child_job_id") or (receipt.get("output") or {}).get("job_id")),
                        "message": f"Node {receipt.get('node_id') or receipt.get('step_id')} → {receipt.get('status')}",
                    }
                )
            if execution.state.value in {"COMPLETED", "FAILED", "CANCELLED"}:
                events.append(
                    {
                        "timestamp": execution.ended_at or execution.updated_at,
                        "severity": "error" if execution.state.value == "FAILED" else "info",
                        "node": execution.current_node_id,
                        "execution_id": execution.execution_id,
                        "message": f"Execution {execution.state.value}"
                        + (f": {execution.error}" if execution.error else ""),
                    }
                )
        events = events[:limit]
        return {"logs": events, "execution_count": len(executions)}

    @router.post("/api/workflows/{workflow_id}/run")
    def run_workflow(workflow_id: str, payload: WorkflowRunRequest | None = None) -> dict:
        """Start a NEW execution (definition) or enqueue advance (legacy execution id)."""
        if getattr(workflow_runtime, "job_runtime", None) is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "WORKFLOW_WORKER_UNAVAILABLE",
                    "message": "job_runtime not bound; cannot enqueue workflow.advance",
                },
            )
        definition = workflow_store.get_definition(workflow_id)
        if definition is not None:
            try:
                execution, job = workflow_runtime.run_definition(
                    workflow_id,
                    requested_by="api",
                    trigger_source="MANUAL",
                    inputs=(payload.inputs if payload else None),
                    idempotency_key=(payload.idempotency_key if payload else None),
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Workflow not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {
                "workflow": _enrich_definition(definition),
                "execution": execution.public_dict(),
                "job": job.public_dict() if job is not None else None,
                "mode": "enqueued",
            }
        # Legacy: workflow_id is an execution id
        try:
            job = workflow_runtime.enqueue_advance(workflow_id, requested_by="api")
            record = workflow_store.get(workflow_id)
            if record is None:
                raise KeyError(workflow_id)
            return {
                "workflow": record.public_dict(),
                "job": job.public_dict(),
                "mode": "enqueued",
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/api/workflows/{workflow_id}/cancel")
    def cancel_workflow(workflow_id: str) -> dict:
        try:
            record = workflow_runtime.cancel(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"workflow": record.public_dict()}

    @router.get("/api/workflow-executions/{execution_id}")
    def get_execution(execution_id: str) -> dict:
        execution = workflow_store.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        return {"execution": execution.public_dict()}

    @router.post("/api/workflow-executions/{execution_id}/cancel")
    def cancel_execution(execution_id: str) -> dict:
        try:
            record = workflow_runtime.cancel(execution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Execution not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        execution = workflow_store.get_execution(execution_id)
        return {
            "execution": execution.public_dict() if execution else None,
            "workflow": record.public_dict(),
        }

    @router.post("/api/workflow-executions/{execution_id}/resume")
    def resume_execution(
        execution_id: str,
        payload: WorkflowResumeApprovalRequest | None = None,
    ) -> dict:
        """Resume WAITING_APPROVAL after operator approve/reject."""
        body = payload or WorkflowResumeApprovalRequest()
        try:
            record = workflow_runtime.resume_with_approval(
                execution_id,
                approval_id=body.approval_id,
                decision=body.decision,
                requested_by="api",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Execution not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        execution = workflow_store.get_execution(execution_id)
        return {
            "execution": execution.public_dict() if execution else None,
            "workflow": record.public_dict(),
        }

    return router
