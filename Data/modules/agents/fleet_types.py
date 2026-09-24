"""Durable agent fleet / orchestrator definition and mission types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentDefinitionKind(str, Enum):
    GENERIC = "generic"
    CODING = "coding"
    RESEARCH = "research"
    ORCHESTRATOR = "orchestrator"
    SPECIALIST = "specialist"


class AgentHealth(str, Enum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    BUSY = "busy"
    DISABLED = "disabled"
    ERROR = "error"
    ARCHIVED = "archived"


class MissionStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    DISABLED = "disabled"


ACTIVE_MISSION_STATUSES = frozenset(
    {
        MissionStatus.QUEUED.value,
        MissionStatus.STARTING.value,
        MissionStatus.RUNNING.value,
        MissionStatus.CANCELLING.value,
    }
)


@dataclass
class OrchestratorConfig:
    member_agent_ids: list[str] = field(default_factory=list)
    strategy: str = "sequential"  # sequential | parallel_bounded
    routing_rules: list[dict[str, Any]] = field(default_factory=list)
    max_delegation_depth: int = 3
    parallelism_limit: int = 2
    fan_out_policy: str = "ordered"
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"max_retries": 0, "backoff_ms": 0})
    per_node_timeout_s: int | None = None
    overall_timeout_s: int | None = None
    approval_escalation: str = "inherit"
    failure_strategy: str = "fail_fast"  # fail_fast | continue
    verification_required: bool = False
    aggregation_agent_id: str | None = None
    default_model_fallback: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "memberAgentIds": list(self.member_agent_ids),
            "strategy": self.strategy,
            "routingRules": list(self.routing_rules),
            "maxDelegationDepth": self.max_delegation_depth,
            "parallelismLimit": self.parallelism_limit,
            "fanOutPolicy": self.fan_out_policy,
            "retryPolicy": dict(self.retry_policy),
            "perNodeTimeoutS": self.per_node_timeout_s,
            "overallTimeoutS": self.overall_timeout_s,
            "approvalEscalation": self.approval_escalation,
            "failureStrategy": self.failure_strategy,
            "verificationRequired": self.verification_required,
            "aggregationAgentId": self.aggregation_agent_id,
            "defaultModelFallback": self.default_model_fallback,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> OrchestratorConfig:
        data = dict(raw or {})
        return cls(
            member_agent_ids=list(data.get("memberAgentIds") or data.get("member_agent_ids") or []),
            strategy=str(data.get("strategy") or "sequential"),
            routing_rules=list(data.get("routingRules") or data.get("routing_rules") or []),
            max_delegation_depth=int(data.get("maxDelegationDepth") or data.get("max_delegation_depth") or 3),
            parallelism_limit=int(data.get("parallelismLimit") or data.get("parallelism_limit") or 2),
            fan_out_policy=str(data.get("fanOutPolicy") or data.get("fan_out_policy") or "ordered"),
            retry_policy=dict(data.get("retryPolicy") or data.get("retry_policy") or {"max_retries": 0}),
            per_node_timeout_s=data.get("perNodeTimeoutS", data.get("per_node_timeout_s")),
            overall_timeout_s=data.get("overallTimeoutS", data.get("overall_timeout_s")),
            approval_escalation=str(data.get("approvalEscalation") or data.get("approval_escalation") or "inherit"),
            failure_strategy=str(data.get("failureStrategy") or data.get("failure_strategy") or "fail_fast"),
            verification_required=bool(data.get("verificationRequired") or data.get("verification_required") or False),
            aggregation_agent_id=data.get("aggregationAgentId") or data.get("aggregation_agent_id"),
            default_model_fallback=data.get("defaultModelFallback") or data.get("default_model_fallback"),
        )


@dataclass
class AgentDefinition:
    agent_id: str
    name: str
    kind: AgentDefinitionKind
    description: str = ""
    role: str = ""
    enabled: bool = True
    archived: bool = False
    model_ref: str | None = None
    system_policy: str | None = None
    capabilities: list[str] = field(default_factory=list)
    knowledge_sources: list[str] = field(default_factory=list)
    memory_policy: str = "default"
    dataset_access: str = "none"
    approval_mode: str = "inherit"  # inherit | auto_low_risk | manual | hybrid
    autonomy: int = 50
    max_concurrency: int = 1
    timeout_s: int | None = None
    max_retries: int = 0
    token_budget: int | None = None
    tags: list[str] = field(default_factory=list)
    version: int = 1
    orchestrator: OrchestratorConfig | None = None
    health: AgentHealth = AgentHealth.UNKNOWN
    health_reason: str | None = None
    last_run_at: str | None = None
    last_mission_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        from .system_inventory import classify_fleet_agent

        ownership = classify_fleet_agent(self)
        return {
            "agentId": self.agent_id,
            "id": self.agent_id,
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "role": self.role,
            "enabled": self.enabled,
            "archived": self.archived,
            "modelRef": self.model_ref,
            "systemPolicy": self.system_policy,
            "capabilities": list(self.capabilities),
            "knowledgeSources": list(self.knowledge_sources),
            "memoryPolicy": self.memory_policy,
            "datasetAccess": self.dataset_access,
            "approvalMode": self.approval_mode,
            "autonomy": self.autonomy,
            "maxConcurrency": self.max_concurrency,
            "timeoutS": self.timeout_s,
            "maxRetries": self.max_retries,
            "tokenBudget": self.token_budget,
            "tags": list(self.tags),
            "version": self.version,
            "orchestrator": self.orchestrator.public_dict() if self.orchestrator else None,
            "health": self.health.value,
            "healthReason": self.health_reason,
            "status": self.health.value,
            "lastRunAt": self.last_run_at,
            "lastMissionId": self.last_mission_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "metadata": dict(self.metadata),
            "origin": ownership["origin"],
            "entityType": ownership["entityType"],
            "systemKey": ownership["systemKey"],
            "mutable": ownership["mutable"],
            "executable": True,
            "truth": {
                "definitions_are_control_plane_only": True,
                "side_effects_via_gateway_only": True,
                "origin_from_metadata_system_key": True,
            },
        }


@dataclass
class AgentMission:
    mission_id: str
    agent_id: str
    title: str
    request: str
    status: MissionStatus
    priority: str = "med"
    progress: float = 0.0
    parent_mission_id: str | None = None
    run_id: str | None = None
    job_ids: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False
    trace_id: str | None = None
    created_at: str = ""
    started_at: str | None = None
    updated_at: str = ""
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "missionId": self.mission_id,
            "agentId": self.agent_id,
            "title": self.title,
            "request": self.request,
            "status": self.status.value,
            "priority": self.priority,
            "progress": self.progress,
            "parentMissionId": self.parent_mission_id,
            "runId": self.run_id,
            "jobIds": list(self.job_ids),
            "result": dict(self.result),
            "error": self.error,
            "cancelRequested": self.cancel_requested,
            "traceId": self.trace_id,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "finishedAt": self.finished_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class AgentEvent:
    event_id: str
    agent_id: str | None
    mission_id: str | None
    category: str
    message: str
    level: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "agentId": self.agent_id,
            "missionId": self.mission_id,
            "category": self.category,
            "message": self.message,
            "level": self.level,
            "payload": dict(self.payload),
            "createdAt": self.created_at,
        }
