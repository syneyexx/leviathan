"""Workflow domain types — definitions, versions, executions, and legacy records.

Definition status is independent of execution lifecycle. A reusable workflow
definition may be ACTIVE while zero or many executions run against pinned versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowState(str, Enum):
    """Legacy / projected execution-facing states (WorkflowRecord)."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowDefinitionStatus(str, Enum):
    """Reusable definition lifecycle — NOT an execution state."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DRAFT = "DRAFT"
    TEMPLATE = "TEMPLATE"
    ARCHIVED = "ARCHIVED"


class WorkflowExecutionState(str, Enum):
    """One run of a version-pinned workflow."""

    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


class WorkflowNodeKind(str, Enum):
    TRIGGER = "trigger"
    CAPABILITY = "capability"
    AGENT = "agent"
    CONDITION = "condition"
    LOOP = "loop"
    DELAY = "delay"


class WorkflowTriggerKind(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULE = "SCHEDULE"
    TASK = "TASK"
    API = "API"
    OTHER = "OTHER"


class WorkflowVariableType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"
    SECRET_REF = "secret_ref"


# Map execution states onto legacy WorkflowState for TaskService / old clients.
_EXEC_TO_LEGACY: dict[WorkflowExecutionState, WorkflowState] = {
    WorkflowExecutionState.QUEUED: WorkflowState.CREATED,
    WorkflowExecutionState.STARTING: WorkflowState.RUNNING,
    WorkflowExecutionState.RUNNING: WorkflowState.RUNNING,
    WorkflowExecutionState.WAITING: WorkflowState.RUNNING,
    WorkflowExecutionState.WAITING_APPROVAL: WorkflowState.RUNNING,
    WorkflowExecutionState.COMPLETED: WorkflowState.COMPLETED,
    WorkflowExecutionState.FAILED: WorkflowState.FAILED,
    WorkflowExecutionState.CANCELLING: WorkflowState.RUNNING,
    WorkflowExecutionState.CANCELLED: WorkflowState.CANCELLED,
}

_LEGACY_TO_EXEC: dict[WorkflowState, WorkflowExecutionState] = {
    WorkflowState.CREATED: WorkflowExecutionState.QUEUED,
    WorkflowState.RUNNING: WorkflowExecutionState.RUNNING,
    WorkflowState.COMPLETED: WorkflowExecutionState.COMPLETED,
    WorkflowState.FAILED: WorkflowExecutionState.FAILED,
    WorkflowState.CANCELLED: WorkflowExecutionState.CANCELLED,
}


def execution_to_legacy_state(state: WorkflowExecutionState) -> WorkflowState:
    return _EXEC_TO_LEGACY.get(state, WorkflowState.RUNNING)


def legacy_to_execution_state(state: WorkflowState | str) -> WorkflowExecutionState:
    if isinstance(state, str):
        try:
            state = WorkflowState(state)
        except ValueError:
            try:
                return WorkflowExecutionState(state)
            except ValueError:
                return WorkflowExecutionState.RUNNING
    return _LEGACY_TO_EXEC.get(state, WorkflowExecutionState.RUNNING)


@dataclass(frozen=True)
class WorkflowStepDef:
    """Legacy ordered step — still accepted; converted to a sequential graph."""

    step_id: str
    capability_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "arguments": self.arguments,
            "approval_id": self.approval_id,
        }


@dataclass(frozen=True)
class WorkflowNodeDef:
    node_id: str
    kind: WorkflowNodeKind | str
    label: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def kind_value(self) -> str:
        return self.kind.value if isinstance(self.kind, WorkflowNodeKind) else str(self.kind)

    def public_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind_value,
            "label": self.label,
            "config": self.config,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> WorkflowNodeDef:
        return WorkflowNodeDef(
            node_id=str(raw.get("node_id") or raw.get("id") or ""),
            kind=str(raw.get("kind") or WorkflowNodeKind.CAPABILITY.value),
            label=str(raw.get("label") or ""),
            config=dict(raw.get("config") or {}),
        )


@dataclass(frozen=True)
class WorkflowEdgeDef:
    edge_id: str
    source: str
    target: str
    source_handle: str | None = None
    label: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "source_handle": self.source_handle,
            "label": self.label,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> WorkflowEdgeDef:
        return WorkflowEdgeDef(
            edge_id=str(raw.get("edge_id") or raw.get("id") or f"{raw.get('source')}:{raw.get('target')}"),
            source=str(raw.get("source") or ""),
            target=str(raw.get("target") or ""),
            source_handle=raw.get("source_handle"),
            label=raw.get("label"),
        )


@dataclass(frozen=True)
class WorkflowLayoutNode:
    """UI canvas metadata — never execution truth."""

    node_id: str
    x: float
    y: float

    def public_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "x": self.x, "y": self.y}


@dataclass
class WorkflowGraph:
    nodes: list[WorkflowNodeDef] = field(default_factory=list)
    edges: list[WorkflowEdgeDef] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.public_dict() for n in self.nodes],
            "edges": [e.public_dict() for e in self.edges],
        }

    @staticmethod
    def from_dict(raw: dict[str, Any] | None) -> WorkflowGraph:
        raw = raw or {}
        return WorkflowGraph(
            nodes=[WorkflowNodeDef.from_dict(n) for n in (raw.get("nodes") or [])],
            edges=[WorkflowEdgeDef.from_dict(e) for e in (raw.get("edges") or [])],
        )


@dataclass(frozen=True)
class WorkflowVariableDef:
    name: str
    var_type: WorkflowVariableType | str = WorkflowVariableType.STRING
    default: Any = None
    required: bool = False
    description: str = ""
    secret: bool = False

    @property
    def type_value(self) -> str:
        return self.var_type.value if isinstance(self.var_type, WorkflowVariableType) else str(self.var_type)

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_value,
            "default": None if self.secret else self.default,
            "required": self.required,
            "description": self.description,
            "secret": self.secret,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> WorkflowVariableDef:
        return WorkflowVariableDef(
            name=str(raw.get("name") or ""),
            var_type=str(raw.get("type") or WorkflowVariableType.STRING.value),
            default=raw.get("default"),
            required=bool(raw.get("required")),
            description=str(raw.get("description") or ""),
            secret=bool(raw.get("secret")),
        )


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    status: WorkflowDefinitionStatus
    created_at: str
    updated_at: str
    description: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    current_version: int = 1
    graph: WorkflowGraph = field(default_factory=WorkflowGraph)
    variables: list[WorkflowVariableDef] = field(default_factory=list)
    layout: list[WorkflowLayoutNode] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    trigger_bindings: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
            "status": self.status.value,
            "definition_status": self.status.value,
            "current_version": self.current_version,
            "graph": self.graph.public_dict(),
            "variables": [v.public_dict() for v in self.variables],
            "layout": [n.public_dict() for n in self.layout],
            "config": self.config,
            "trigger_bindings": list(self.trigger_bindings),
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            # Compatibility: linear steps projection for older clients.
            "steps": linear_steps_from_graph(self.graph),
        }


@dataclass
class WorkflowVersion:
    workflow_id: str
    version: int
    graph: WorkflowGraph
    variables: list[WorkflowVariableDef]
    config: dict[str, Any]
    layout: list[WorkflowLayoutNode]
    created_at: str
    created_by: str | None = None
    change_summary: str = ""
    content_hash: str = ""
    validation: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "graph": self.graph.public_dict(),
            "variables": [v.public_dict() for v in self.variables],
            "config": self.config,
            "layout": [n.public_dict() for n in self.layout],
            "created_at": self.created_at,
            "created_by": self.created_by,
            "change_summary": self.change_summary,
            "content_hash": self.content_hash,
            "validation": self.validation,
            "steps": linear_steps_from_graph(self.graph),
        }


@dataclass
class WorkflowExecution:
    execution_id: str
    workflow_id: str
    workflow_version: int
    state: WorkflowExecutionState
    created_at: str
    updated_at: str
    trigger_source: str = WorkflowTriggerKind.MANUAL.value
    requested_by: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    current_node_id: str | None = None
    node_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    root_job_id: str | None = None
    child_job_ids: list[str] = field(default_factory=list)
    run_id: str | None = None
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Graph cursor bookkeeping for the runtime
    cursor: dict[str, Any] = field(default_factory=dict)
    name_snapshot: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "state": self.state.value,
            "trigger_source": self.trigger_source,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "current_node_id": self.current_node_id,
            "node_results": self.node_results,
            "error": self.error,
            "root_job_id": self.root_job_id,
            "child_job_ids": list(self.child_job_ids),
            "run_id": self.run_id,
            "input_snapshot": self.input_snapshot,
            "metadata": self.metadata,
            "cursor": self.cursor,
        }


@dataclass
class WorkflowRecord:
    """Compatibility projection: one execution + its linear steps.

    ``workflow_id`` historically identified the conflated record. After
    separation it equals ``execution_id`` so TaskService / ScheduleRunner /
    worker entrypoints keep working without a parallel runtime.
    """

    workflow_id: str
    name: str
    state: WorkflowState
    steps: list[WorkflowStepDef]
    created_at: str
    updated_at: str
    current_step: int = 0
    run_id: str | None = None
    step_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # New optional fields (additive)
    definition_id: str | None = None
    execution_id: str | None = None
    workflow_version: int | None = None
    definition_status: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "state": self.state.value,
            "steps": [s.public_dict() for s in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_step": self.current_step,
            "run_id": self.run_id,
            "step_results": self.step_results,
            "error": self.error,
            "metadata": self.metadata,
            "definition_id": self.definition_id,
            "execution_id": self.execution_id or self.workflow_id,
            "workflow_version": self.workflow_version,
            "definition_status": self.definition_status,
        }


def linear_steps_from_graph(graph: WorkflowGraph) -> list[dict[str, Any]]:
    """Best-effort ordered capability projection for legacy consumers."""
    by_id = {n.node_id: n for n in graph.nodes}
    outgoing: dict[str, list[WorkflowEdgeDef]] = {}
    incoming: set[str] = set()
    for edge in graph.edges:
        outgoing.setdefault(edge.source, []).append(edge)
        incoming.add(edge.target)
    starts = [n.node_id for n in graph.nodes if n.node_id not in incoming]
    if not starts and graph.nodes:
        starts = [graph.nodes[0].node_id]
    ordered: list[str] = []
    seen: set[str] = set()
    stack = list(starts)
    while stack:
        nid = stack.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        ordered.append(nid)
        for edge in outgoing.get(nid, []):
            if edge.target not in seen:
                stack.append(edge.target)
    steps: list[dict[str, Any]] = []
    for nid in ordered:
        node = by_id.get(nid)
        if node is None:
            continue
        kind = node.kind_value
        if kind not in {WorkflowNodeKind.CAPABILITY.value, WorkflowNodeKind.AGENT.value}:
            continue
        cfg = dict(node.config or {})
        steps.append(
            {
                "step_id": node.node_id,
                "capability_id": str(cfg.get("capability_id") or ""),
                "arguments": dict(cfg.get("arguments") or {}),
                "approval_id": cfg.get("approval_id"),
            }
        )
    return steps


def steps_to_workflow_step_defs(steps: list[dict[str, Any]]) -> list[WorkflowStepDef]:
    return [
        WorkflowStepDef(
            step_id=str(item.get("step_id")),
            capability_id=str(item.get("capability_id") or ""),
            arguments=dict(item.get("arguments") or {}),
            approval_id=item.get("approval_id"),
        )
        for item in steps
        if item.get("step_id")
    ]
