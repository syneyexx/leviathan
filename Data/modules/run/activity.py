"""User-visible operational activity events.

Extends the canonical Run / EventEnvelope authority. This is a projection and
telemetry contract — never an execution authority.

Distinguishes reportable operational telemetry from private model cognition.
Activity events MUST originate from real runtime transitions; the frontend must
not invent lifecycle, counts, or progress.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from Data.modules.observability.redaction import redact_payload

from .envelope import EVENT_ENVELOPE_SCHEMA_VERSION

ACTIVITY_SCHEMA_VERSION = 1

# Backward-compatible plan step ids still emitted by ReasoningPlan.
LEGACY_STEP_TITLES: dict[str, str] = {
    "understand_request": "Request interpreted",
    "retrieve_atlas_context": "Atlas context retrieval",
    "deep_recall_hydrate": "Deep recall hydration",
    "retrieve_relevant_knowledge": "Knowledge retrieval",
    "structure_response": "Response structure planned",
    "generate_answer": "Answer synthesis",
}


class ActivityCategory(str, Enum):
    REQUEST = "REQUEST"
    PLANNING = "PLANNING"
    RETRIEVAL = "RETRIEVAL"
    MEMORY = "MEMORY"
    KNOWLEDGE = "KNOWLEDGE"
    RESEARCH = "RESEARCH"
    DATA = "DATA"
    MODEL = "MODEL"
    AGENT = "AGENT"
    TOOL = "TOOL"
    EXECUTION = "EXECUTION"
    EXPERIMENT = "EXPERIMENT"
    HYPOTHESIS = "HYPOTHESIS"
    EVALUATION = "EVALUATION"
    VERIFICATION = "VERIFICATION"
    DECISION = "DECISION"
    RISK = "RISK"
    TRADING = "TRADING"
    ARTIFACT = "ARTIFACT"
    SYNTHESIS = "SYNTHESIS"
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"
    RECOVERY = "RECOVERY"


class ActivityPhase(str, Enum):
    REQUEST_RECEIVED = "request_received"
    REQUEST_UNDERSTOOD = "request_understood"
    PLANNING = "planning"
    CONTEXT_RETRIEVAL = "context_retrieval"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    MEMORY_RETRIEVAL = "memory_retrieval"
    SOURCE_VALIDATION = "source_validation"
    AGENT_DELEGATION = "agent_delegation"
    MODEL_INVOCATION = "model_invocation"
    TOOL_INVOCATION = "tool_invocation"
    DATA_LOADING = "data_loading"
    HYPOTHESIS_GENERATION = "hypothesis_generation"
    HYPOTHESIS_EVALUATION = "hypothesis_evaluation"
    EXPERIMENT_EXECUTION = "experiment_execution"
    BACKTEST_EXECUTION = "backtest_execution"
    ROBUSTNESS_TESTING = "robustness_testing"
    RISK_VALIDATION = "risk_validation"
    DECISION_FORMULATION = "decision_formulation"
    EXECUTION = "execution"
    RESULT_VERIFICATION = "result_verification"
    ARTIFACT_PUBLICATION = "artifact_publication"
    ANSWER_SYNTHESIS = "answer_synthesis"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    DEGRADED = "degraded"
    RETRYING = "retrying"
    UNKNOWN = "unknown"


class ActivityLifecycle(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class ActorType(str, Enum):
    LEVIATHAN = "leviathan"
    AGENT = "agent"
    WORKER = "worker"
    TOOL = "tool"
    MODEL = "model"
    RESEARCH = "research"
    TRADING = "trading"
    SYSTEM = "system"


class ProgressKind(str, Enum):
    UNKNOWN = "unknown"
    INDETERMINATE = "indeterminate"
    MEASURED = "measured"
    ESTIMATED = "estimated"


class VisibilityClass(str, Enum):
    USER_VISIBLE = "USER_VISIBLE"
    DEVELOPER = "DEVELOPER"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"


class SensitivityClass(str, Enum):
    PUBLIC = "PUBLIC"
    OPERATIONAL = "OPERATIONAL"
    RESTRICTED = "RESTRICTED"
    SECRET = "SECRET"


TERMINAL_LIFECYCLES = frozenset(
    {
        ActivityLifecycle.COMPLETED,
        ActivityLifecycle.FAILED,
        ActivityLifecycle.CANCELLED,
        ActivityLifecycle.SKIPPED,
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _enum_value(value: Enum | str | None, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


@dataclass(frozen=True)
class ProgressMeasurement:
    """Bounded progress with explicit measurement semantics.

    Never invent percentages for non-deterministic reasoning. Use UNKNOWN or
    INDETERMINATE when work is not measurable.
    """

    kind: ProgressKind = ProgressKind.UNKNOWN
    value: float | None = None
    unit: str | None = None
    numerator: float | None = None
    denominator: float | None = None
    basis: str | None = None

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": _enum_value(self.kind, ProgressKind.UNKNOWN.value)}
        if self.value is not None:
            out["value"] = self.value
        if self.unit is not None:
            out["unit"] = self.unit
        if self.numerator is not None:
            out["numerator"] = self.numerator
        if self.denominator is not None:
            out["denominator"] = self.denominator
        if self.basis is not None:
            out["basis"] = self.basis
        return out

    @classmethod
    def unknown(cls) -> ProgressMeasurement:
        return cls(kind=ProgressKind.UNKNOWN)

    @classmethod
    def indeterminate(cls, *, basis: str | None = None) -> ProgressMeasurement:
        return cls(kind=ProgressKind.INDETERMINATE, basis=basis)

    @classmethod
    def measured(
        cls,
        *,
        numerator: float,
        denominator: float,
        unit: str | None = None,
        basis: str | None = None,
    ) -> ProgressMeasurement:
        if denominator <= 0:
            return cls.unknown()
        ratio = float(numerator) / float(denominator)
        return cls(
            kind=ProgressKind.MEASURED,
            value=ratio,
            unit=unit,
            numerator=float(numerator),
            denominator=float(denominator),
            basis=basis,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ProgressMeasurement | None:
        if not data:
            return None
        kind_raw = str(data.get("kind") or ProgressKind.UNKNOWN.value).lower()
        try:
            kind = ProgressKind(kind_raw)
        except ValueError:
            kind = ProgressKind.UNKNOWN
        return cls(
            kind=kind,
            value=_optional_float(data.get("value")),
            unit=str(data["unit"]) if data.get("unit") is not None else None,
            numerator=_optional_float(data.get("numerator")),
            denominator=_optional_float(data.get("denominator")),
            basis=str(data["basis"]) if data.get("basis") is not None else None,
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class NormalizedActivityError:
    code: str
    message: str
    retryable: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.retryable is not None:
            out["retryable"] = self.retryable
        if self.details:
            out["details"] = redact_payload(dict(self.details))
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> NormalizedActivityError | None:
        if not data:
            return None
        code = str(data.get("code") or "UNKNOWN_ERROR")
        message = str(data.get("message") or code)
        retryable = data.get("retryable")
        details = data.get("details") if isinstance(data.get("details"), dict) else {}
        return cls(
            code=code,
            message=message,
            retryable=bool(retryable) if retryable is not None else None,
            details=dict(details or {}),
        )


@dataclass(frozen=True)
class ConfigTriple:
    """Requested / effective / measured configuration honesty."""

    requested: dict[str, Any] = field(default_factory=dict)
    effective: dict[str, Any] = field(default_factory=dict)
    measured: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": redact_payload(dict(self.requested)),
            "effective": redact_payload(dict(self.effective)),
            "measured": redact_payload(dict(self.measured)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ConfigTriple | None:
        if not data:
            return None
        return cls(
            requested=dict(data.get("requested") or {}),
            effective=dict(data.get("effective") or {}),
            measured=dict(data.get("measured") or {}),
        )


@dataclass(frozen=True)
class ActivityEvent:
    """Canonical user-visible operational activity event.

    Compatible with EventEnvelope correlation fields. ``schema_version`` versions
    this activity contract independently of the envelope version.
    """

    event_id: str
    operation_id: str
    sequence: int
    category: ActivityCategory
    phase: ActivityPhase
    lifecycle: ActivityLifecycle
    title: str
    actor_type: ActorType = ActorType.SYSTEM
    visibility: VisibilityClass = VisibilityClass.USER_VISIBLE
    sensitivity: SensitivityClass = SensitivityClass.OPERATIONAL
    schema_version: int = ACTIVITY_SCHEMA_VERSION
    parent_event_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    actor_id: str | None = None
    summary: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    progress: ProgressMeasurement | None = None
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    model_ref: str | None = None
    agent_ref: str | None = None
    worker_ref: str | None = None
    capability_ref: str | None = None
    config: ConfigTriple | None = None
    result_count: int | None = None
    retry: dict[str, Any] | None = None
    error: NormalizedActivityError | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def public_dict(
        self, *, for_user: bool = True, include_developer: bool = False
    ) -> dict[str, Any] | None:
        if self.visibility == VisibilityClass.SENSITIVE or self.sensitivity == SensitivityClass.SECRET:
            return None
        if for_user:
            if self.visibility == VisibilityClass.USER_VISIBLE:
                allowed = True
            elif self.visibility == VisibilityClass.DEVELOPER and include_developer:
                allowed = True
            else:
                allowed = False
            if not allowed:
                return None

        body: dict[str, Any] = {
            "eventId": self.event_id,
            "operationId": self.operation_id,
            "parentEventId": self.parent_event_id,
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "sequence": self.sequence,
            "actorType": _enum_value(self.actor_type, ActorType.SYSTEM.value),
            "actorId": self.actor_id,
            "category": _enum_value(self.category, ActivityCategory.SYSTEM.value),
            "phase": _enum_value(self.phase, ActivityPhase.UNKNOWN.value),
            "lifecycle": _enum_value(self.lifecycle, ActivityLifecycle.RUNNING.value),
            "title": self.title,
            "summary": self.summary,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "finishedAt": self.finished_at,
            "progress": self.progress.public_dict() if self.progress else None,
            "evidenceRefs": list(self.evidence_refs),
            "artifactRefs": list(self.artifact_refs),
            "sourceRefs": list(self.source_refs),
            "modelRef": self.model_ref,
            "agentRef": self.agent_ref,
            "workerRef": self.worker_ref,
            "capabilityRef": self.capability_ref,
            "config": self.config.public_dict() if self.config else None,
            "resultCount": self.result_count,
            "retry": redact_payload(dict(self.retry)) if self.retry else None,
            "error": self.error.public_dict() if self.error else None,
            "visibility": _enum_value(self.visibility, VisibilityClass.USER_VISIBLE.value),
            "sensitivity": _enum_value(self.sensitivity, SensitivityClass.OPERATIONAL.value),
            "schemaVersion": self.schema_version,
            "payload": redact_payload(dict(self.payload)),
            "truth": {
                "operational_telemetry_not_cot": True,
                "lifecycle_from_runtime": True,
                "progress_not_fabricated": True,
            },
        }
        return body

    def to_envelope_payload(self) -> dict[str, Any]:
        published = self.public_dict(for_user=False) or {}
        return {
            "activity": published,
            "activity_schema_version": ACTIVITY_SCHEMA_VERSION,
            "envelope_schema_version": EVENT_ENVELOPE_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActivityEvent:
        """Parse a public or internal activity dict. Unknown versions degrade safely."""
        version = int(data.get("schemaVersion") or data.get("schema_version") or ACTIVITY_SCHEMA_VERSION)
        if version > ACTIVITY_SCHEMA_VERSION:
            # Forward-compatible: keep known fields, mark degraded in payload.
            pass
        category = _parse_enum(ActivityCategory, data.get("category"), ActivityCategory.SYSTEM)
        phase = _parse_enum(ActivityPhase, data.get("phase"), ActivityPhase.UNKNOWN)
        lifecycle = _parse_enum(ActivityLifecycle, data.get("lifecycle"), ActivityLifecycle.RUNNING)
        actor_type = _parse_enum(ActorType, data.get("actorType") or data.get("actor_type"), ActorType.SYSTEM)
        visibility = _parse_enum(
            VisibilityClass,
            data.get("visibility"),
            VisibilityClass.USER_VISIBLE,
        )
        sensitivity = _parse_enum(
            SensitivityClass,
            data.get("sensitivity"),
            SensitivityClass.OPERATIONAL,
        )
        progress_raw = data.get("progress")
        error_raw = data.get("error")
        config_raw = data.get("config")
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        if version > ACTIVITY_SCHEMA_VERSION:
            payload = {**payload, "_unsupported_schema_version": version}

        return cls(
            event_id=str(data.get("eventId") or data.get("event_id") or uuid.uuid4()),
            operation_id=str(data.get("operationId") or data.get("operation_id") or ""),
            parent_event_id=_optional_str(data.get("parentEventId") or data.get("parent_event_id")),
            trace_id=_optional_str(data.get("traceId") or data.get("trace_id")),
            span_id=_optional_str(data.get("spanId") or data.get("span_id")),
            sequence=int(data.get("sequence") or 0),
            actor_type=actor_type,
            actor_id=_optional_str(data.get("actorId") or data.get("actor_id")),
            category=category,
            phase=phase,
            lifecycle=lifecycle,
            title=str(data.get("title") or phase.value),
            summary=_optional_str(data.get("summary")),
            started_at=_optional_str(data.get("startedAt") or data.get("started_at")),
            updated_at=_optional_str(data.get("updatedAt") or data.get("updated_at")),
            finished_at=_optional_str(data.get("finishedAt") or data.get("finished_at")),
            progress=ProgressMeasurement.from_dict(progress_raw if isinstance(progress_raw, Mapping) else None),
            evidence_refs=tuple(str(x) for x in (data.get("evidenceRefs") or data.get("evidence_refs") or ())),
            artifact_refs=tuple(str(x) for x in (data.get("artifactRefs") or data.get("artifact_refs") or ())),
            source_refs=tuple(str(x) for x in (data.get("sourceRefs") or data.get("source_refs") or ())),
            model_ref=_optional_str(data.get("modelRef") or data.get("model_ref")),
            agent_ref=_optional_str(data.get("agentRef") or data.get("agent_ref")),
            worker_ref=_optional_str(data.get("workerRef") or data.get("worker_ref")),
            capability_ref=_optional_str(data.get("capabilityRef") or data.get("capability_ref")),
            config=ConfigTriple.from_dict(config_raw if isinstance(config_raw, Mapping) else None),
            result_count=_optional_int(data.get("resultCount") if "resultCount" in data else data.get("result_count")),
            retry=dict(data["retry"]) if isinstance(data.get("retry"), dict) else None,
            error=NormalizedActivityError.from_dict(error_raw if isinstance(error_raw, Mapping) else None),
            visibility=visibility,
            sensitivity=sensitivity,
            schema_version=min(version, ACTIVITY_SCHEMA_VERSION) if version <= ACTIVITY_SCHEMA_VERSION else version,
            payload=dict(payload or {}),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Any:
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, Enum):
        value = value.value
    raw = str(value).strip()
    try:
        return enum_cls(raw)
    except ValueError:
        try:
            return enum_cls(raw.upper())
        except ValueError:
            try:
                return enum_cls(raw.lower())
            except ValueError:
                return default


def legacy_step_title(step_id: str) -> str:
    return LEGACY_STEP_TITLES.get(step_id, step_id.replace("_", " ").strip().capitalize() or step_id)


def legacy_steps_to_plan_events(
    steps: Sequence[str],
    *,
    operation_id: str,
    trace_id: str | None = None,
    sequence_start: int = 1,
) -> list[ActivityEvent]:
    """Compatibility projection: plan step ids → PENDING/COMPLETED planning nodes.

    These represent the *planned* execution path, not live proof that each step ran.
    Live instrumentation should overwrite lifecycle with real transitions.
    """
    events: list[ActivityEvent] = []
    seq = sequence_start
    for step in steps:
        sid = str(step).strip()
        if not sid:
            continue
        phase = _phase_for_legacy_step(sid)
        category = _category_for_phase(phase)
        events.append(
            ActivityEvent(
                event_id=f"{operation_id}:plan:{sid}",
                operation_id=operation_id,
                sequence=seq,
                category=category,
                phase=phase,
                lifecycle=ActivityLifecycle.QUEUED,
                title=legacy_step_title(sid),
                summary="Planned execution step — awaiting runtime confirmation.",
                actor_type=ActorType.LEVIATHAN,
                actor_id="reasoning_engine",
                trace_id=trace_id,
                payload={"legacy_step_id": sid, "planned": True},
                progress=ProgressMeasurement.indeterminate(basis="plan_step"),
            )
        )
        seq += 1
    return events


def _phase_for_legacy_step(step_id: str) -> ActivityPhase:
    mapping = {
        "understand_request": ActivityPhase.REQUEST_UNDERSTOOD,
        "retrieve_atlas_context": ActivityPhase.CONTEXT_RETRIEVAL,
        "deep_recall_hydrate": ActivityPhase.KNOWLEDGE_RETRIEVAL,
        "retrieve_relevant_knowledge": ActivityPhase.KNOWLEDGE_RETRIEVAL,
        "structure_response": ActivityPhase.PLANNING,
        "generate_answer": ActivityPhase.ANSWER_SYNTHESIS,
    }
    return mapping.get(step_id, ActivityPhase.PLANNING)


def _category_for_phase(phase: ActivityPhase) -> ActivityCategory:
    mapping = {
        ActivityPhase.REQUEST_RECEIVED: ActivityCategory.REQUEST,
        ActivityPhase.REQUEST_UNDERSTOOD: ActivityCategory.REQUEST,
        ActivityPhase.PLANNING: ActivityCategory.PLANNING,
        ActivityPhase.CONTEXT_RETRIEVAL: ActivityCategory.RETRIEVAL,
        ActivityPhase.KNOWLEDGE_RETRIEVAL: ActivityCategory.KNOWLEDGE,
        ActivityPhase.MEMORY_RETRIEVAL: ActivityCategory.MEMORY,
        ActivityPhase.SOURCE_VALIDATION: ActivityCategory.KNOWLEDGE,
        ActivityPhase.AGENT_DELEGATION: ActivityCategory.AGENT,
        ActivityPhase.MODEL_INVOCATION: ActivityCategory.MODEL,
        ActivityPhase.TOOL_INVOCATION: ActivityCategory.TOOL,
        ActivityPhase.DATA_LOADING: ActivityCategory.DATA,
        ActivityPhase.HYPOTHESIS_GENERATION: ActivityCategory.HYPOTHESIS,
        ActivityPhase.HYPOTHESIS_EVALUATION: ActivityCategory.EVALUATION,
        ActivityPhase.EXPERIMENT_EXECUTION: ActivityCategory.EXPERIMENT,
        ActivityPhase.BACKTEST_EXECUTION: ActivityCategory.EVALUATION,
        ActivityPhase.ROBUSTNESS_TESTING: ActivityCategory.EVALUATION,
        ActivityPhase.RISK_VALIDATION: ActivityCategory.RISK,
        ActivityPhase.DECISION_FORMULATION: ActivityCategory.DECISION,
        ActivityPhase.EXECUTION: ActivityCategory.EXECUTION,
        ActivityPhase.RESULT_VERIFICATION: ActivityCategory.VERIFICATION,
        ActivityPhase.ARTIFACT_PUBLICATION: ActivityCategory.ARTIFACT,
        ActivityPhase.ANSWER_SYNTHESIS: ActivityCategory.SYNTHESIS,
        ActivityPhase.COMPLETED: ActivityCategory.SYSTEM,
        ActivityPhase.CANCELLED: ActivityCategory.SYSTEM,
        ActivityPhase.FAILED: ActivityCategory.SYSTEM,
        ActivityPhase.DEGRADED: ActivityCategory.SYSTEM,
        ActivityPhase.RETRYING: ActivityCategory.RECOVERY,
        ActivityPhase.UNKNOWN: ActivityCategory.SYSTEM,
    }
    return mapping.get(phase, ActivityCategory.SYSTEM)


@dataclass
class ActivityNode:
    event: ActivityEvent
    children: list[ActivityNode] = field(default_factory=list)

    def public_dict(self, *, for_user: bool = True) -> dict[str, Any] | None:
        base = self.event.public_dict(for_user=for_user)
        if base is None:
            return None
        kids = []
        for child in self.children:
            pub = child.public_dict(for_user=for_user)
            if pub is not None:
                kids.append(pub)
        base["children"] = kids
        return base


@dataclass
class ActivityProjection:
    operation_id: str
    nodes: list[ActivityNode]
    events: list[ActivityEvent]
    stale: bool = False
    disconnected: bool = False
    highest_sequence: int = 0

    def public_dict(self, *, for_user: bool = True) -> dict[str, Any]:
        tree = []
        for node in self.nodes:
            pub = node.public_dict(for_user=for_user)
            if pub is not None:
                tree.append(pub)
        return {
            "operationId": self.operation_id,
            "highestSequence": self.highest_sequence,
            "stale": self.stale,
            "disconnected": self.disconnected,
            "tree": tree,
            "events": [
                e.public_dict(for_user=for_user)
                for e in self.events
                if e.public_dict(for_user=for_user) is not None
            ],
            "schemaVersion": ACTIVITY_SCHEMA_VERSION,
            "truth": {
                "projection_not_authority": True,
                "stale_not_completed": True,
            },
        }


class ActivityProjector:
    """Deterministic reconciliation for concurrent / out-of-order activity events."""

    def __init__(self, *, max_events: int = 2_000) -> None:
        if max_events < 16:
            raise ValueError("max_events must be >= 16")
        self.max_events = max_events
        self._by_id: dict[str, ActivityEvent] = {}
        self._order: list[str] = []
        self.stale = False
        self.disconnected = False
        self.operation_id: str | None = None

    def ingest(self, event: ActivityEvent | Mapping[str, Any]) -> ActivityEvent | None:
        parsed = event if isinstance(event, ActivityEvent) else ActivityEvent.from_dict(event)
        if not parsed.event_id:
            return None
        if self.operation_id is None:
            self.operation_id = parsed.operation_id
        existing = self._by_id.get(parsed.event_id)
        if existing is not None:
            merged = _merge_activity_events(existing, parsed)
            self._by_id[parsed.event_id] = merged
            return merged
        self._by_id[parsed.event_id] = parsed
        self._order.append(parsed.event_id)
        self._trim()
        return parsed

    def ingest_many(self, events: Iterable[ActivityEvent | Mapping[str, Any]]) -> None:
        for event in events:
            self.ingest(event)

    def mark_disconnected(self) -> None:
        self.disconnected = True
        self.stale = True

    def mark_stale(self) -> None:
        self.stale = True

    def project(self) -> ActivityProjection:
        events = sorted(
            self._by_id.values(),
            key=lambda e: (e.sequence, e.updated_at or e.started_at or "", e.event_id),
        )
        by_parent: dict[str | None, list[ActivityEvent]] = {}
        for event in events:
            by_parent.setdefault(event.parent_event_id, []).append(event)

        def build(parent_id: str | None) -> list[ActivityNode]:
            nodes: list[ActivityNode] = []
            for event in by_parent.get(parent_id, []):
                nodes.append(ActivityNode(event=event, children=build(event.event_id)))
            return nodes

        highest = max((e.sequence for e in events), default=0)
        return ActivityProjection(
            operation_id=self.operation_id or "",
            nodes=build(None),
            events=events,
            stale=self.stale,
            disconnected=self.disconnected,
            highest_sequence=highest,
        )

    def _trim(self) -> None:
        while len(self._order) > self.max_events:
            # Prefer dropping non-terminal high-frequency updates first.
            drop_id = None
            for eid in self._order:
                ev = self._by_id.get(eid)
                if ev and ev.lifecycle not in TERMINAL_LIFECYCLES and not ev.error:
                    # Keep decisions/artifacts.
                    if ev.category in {
                        ActivityCategory.DECISION,
                        ActivityCategory.ARTIFACT,
                        ActivityCategory.VERIFICATION,
                        ActivityCategory.RISK,
                    }:
                        continue
                    drop_id = eid
                    break
            if drop_id is None:
                drop_id = self._order[0]
            self._order.remove(drop_id)
            self._by_id.pop(drop_id, None)


def _merge_activity_events(existing: ActivityEvent, incoming: ActivityEvent) -> ActivityEvent:
    """Idempotent merge: terminal state wins; higher sequence updates progress/refs."""
    prefer_incoming_lifecycle = (
        _lifecycle_rank(incoming.lifecycle) >= _lifecycle_rank(existing.lifecycle)
        and (incoming.sequence >= existing.sequence or incoming.lifecycle in TERMINAL_LIFECYCLES)
    )
    lifecycle = incoming.lifecycle if prefer_incoming_lifecycle else existing.lifecycle
    sequence = max(existing.sequence, incoming.sequence)
    progress = incoming.progress if incoming.progress is not None else existing.progress
    if (
        existing.progress
        and existing.progress.kind == ProgressKind.MEASURED
        and (incoming.progress is None or incoming.progress.kind != ProgressKind.MEASURED)
        and lifecycle == existing.lifecycle
    ):
        progress = existing.progress
    result_count = (
        incoming.result_count if incoming.result_count is not None else existing.result_count
    )
    error = incoming.error if incoming.error is not None else existing.error
    finished = incoming.finished_at or existing.finished_at
    if lifecycle in TERMINAL_LIFECYCLES and not finished:
        finished = incoming.updated_at or existing.updated_at or _utc_now()
    return ActivityEvent(
        event_id=existing.event_id,
        operation_id=incoming.operation_id or existing.operation_id,
        parent_event_id=incoming.parent_event_id or existing.parent_event_id,
        trace_id=incoming.trace_id or existing.trace_id,
        span_id=incoming.span_id or existing.span_id,
        sequence=sequence,
        actor_type=incoming.actor_type or existing.actor_type,
        actor_id=incoming.actor_id or existing.actor_id,
        category=incoming.category if prefer_incoming_lifecycle else existing.category,
        phase=incoming.phase if prefer_incoming_lifecycle else existing.phase,
        lifecycle=lifecycle,
        title=incoming.title if prefer_incoming_lifecycle else existing.title,
        summary=incoming.summary if incoming.summary is not None else existing.summary,
        started_at=existing.started_at or incoming.started_at,
        updated_at=incoming.updated_at or existing.updated_at,
        finished_at=finished,
        progress=progress,
        evidence_refs=tuple(dict.fromkeys([*existing.evidence_refs, *incoming.evidence_refs])),
        artifact_refs=tuple(dict.fromkeys([*existing.artifact_refs, *incoming.artifact_refs])),
        source_refs=tuple(dict.fromkeys([*existing.source_refs, *incoming.source_refs])),
        model_ref=incoming.model_ref or existing.model_ref,
        agent_ref=incoming.agent_ref or existing.agent_ref,
        worker_ref=incoming.worker_ref or existing.worker_ref,
        capability_ref=incoming.capability_ref or existing.capability_ref,
        config=incoming.config or existing.config,
        result_count=result_count,
        retry=incoming.retry if incoming.retry is not None else existing.retry,
        error=error,
        visibility=incoming.visibility if prefer_incoming_lifecycle else existing.visibility,
        sensitivity=incoming.sensitivity if prefer_incoming_lifecycle else existing.sensitivity,
        schema_version=max(existing.schema_version, incoming.schema_version),
        payload={**existing.payload, **incoming.payload},
    )


def _lifecycle_rank(lifecycle: ActivityLifecycle) -> int:
    order = {
        ActivityLifecycle.QUEUED: 10,
        ActivityLifecycle.STARTING: 20,
        ActivityLifecycle.RUNNING: 30,
        ActivityLifecycle.WAITING: 35,
        ActivityLifecycle.RETRYING: 40,
        ActivityLifecycle.DEGRADED: 45,
        ActivityLifecycle.SKIPPED: 50,
        ActivityLifecycle.COMPLETED: 60,
        ActivityLifecycle.CANCELLED: 70,
        ActivityLifecycle.FAILED: 80,
    }
    return order.get(lifecycle, 0)


class ActivityEmitter:
    """Emit durable + streamable activity events for one operation.

    Persistence targets (optional hooks):
    - RunStore.append_event(EventType.ACTIVITY, ...)
    - ObservabilityHub.emit(category=\"activity\", ...)

    The emitter never decides execution outcomes.
    """

    def __init__(
        self,
        *,
        operation_id: str,
        trace_id: str | None = None,
        run_store: Any | None = None,
        observability: Any | None = None,
        persist: bool = True,
        emit_to_hub: bool = True,
        actor_default: ActorType = ActorType.LEVIATHAN,
        actor_id_default: str | None = "leviathan",
    ) -> None:
        self.operation_id = operation_id
        self.trace_id = trace_id
        self.run_store = run_store
        self.observability = observability
        self.persist = persist
        self.emit_to_hub = emit_to_hub
        self.actor_default = actor_default
        self.actor_id_default = actor_id_default
        self._lock = threading.RLock()
        self._sequence = 0
        self._events: list[ActivityEvent] = []
        self._by_stable_id: dict[str, ActivityEvent] = {}

    @property
    def events(self) -> list[ActivityEvent]:
        with self._lock:
            return list(self._events)

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def emit(
        self,
        *,
        category: ActivityCategory | str,
        phase: ActivityPhase | str,
        lifecycle: ActivityLifecycle | str,
        title: str,
        event_id: str | None = None,
        stable_id: str | None = None,
        parent_event_id: str | None = None,
        summary: str | None = None,
        actor_type: ActorType | str | None = None,
        actor_id: str | None = None,
        progress: ProgressMeasurement | None = None,
        result_count: int | None = None,
        evidence_refs: Sequence[str] | None = None,
        artifact_refs: Sequence[str] | None = None,
        source_refs: Sequence[str] | None = None,
        model_ref: str | None = None,
        agent_ref: str | None = None,
        worker_ref: str | None = None,
        capability_ref: str | None = None,
        config: ConfigTriple | None = None,
        retry: Mapping[str, Any] | None = None,
        error: NormalizedActivityError | Mapping[str, Any] | None = None,
        visibility: VisibilityClass | str = VisibilityClass.USER_VISIBLE,
        sensitivity: SensitivityClass | str = SensitivityClass.OPERATIONAL,
        payload: Mapping[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> ActivityEvent:
        now = _utc_now()
        lifecycle_e = _parse_enum(ActivityLifecycle, lifecycle, ActivityLifecycle.RUNNING)
        category_e = _parse_enum(ActivityCategory, category, ActivityCategory.SYSTEM)
        phase_e = _parse_enum(ActivityPhase, phase, ActivityPhase.UNKNOWN)
        actor_type_e = _parse_enum(
            ActorType,
            actor_type if actor_type is not None else self.actor_default,
            self.actor_default,
        )
        visibility_e = _parse_enum(VisibilityClass, visibility, VisibilityClass.USER_VISIBLE)
        sensitivity_e = _parse_enum(SensitivityClass, sensitivity, SensitivityClass.OPERATIONAL)
        err: NormalizedActivityError | None
        if isinstance(error, NormalizedActivityError):
            err = error
        elif isinstance(error, Mapping):
            err = NormalizedActivityError.from_dict(error)
        else:
            err = None

        with self._lock:
            sid = str(stable_id or event_id or f"{self.operation_id}:{uuid.uuid4().hex}")
            existing = self._by_stable_id.get(sid)
            if existing is None:
                self._sequence += 1
                seq = self._sequence
                event_id_final = str(event_id or sid)
                started = started_at or now
            else:
                seq = max(existing.sequence, self._sequence)
                event_id_final = existing.event_id
                started = existing.started_at or started_at or now

            finished = finished_at
            if lifecycle_e in TERMINAL_LIFECYCLES and not finished:
                finished = now

            event = ActivityEvent(
                event_id=event_id_final,
                operation_id=self.operation_id,
                parent_event_id=parent_event_id
                or (existing.parent_event_id if existing else None),
                trace_id=self.trace_id,
                sequence=seq,
                actor_type=actor_type_e,
                actor_id=actor_id if actor_id is not None else self.actor_id_default,
                category=category_e,
                phase=phase_e,
                lifecycle=lifecycle_e,
                title=title,
                summary=summary,
                started_at=started,
                updated_at=now,
                finished_at=finished or (existing.finished_at if existing else None),
                progress=(
                    progress
                    if progress is not None
                    else (existing.progress if existing else ProgressMeasurement.indeterminate())
                ),
                evidence_refs=tuple(
                    evidence_refs or (existing.evidence_refs if existing else ())
                ),
                artifact_refs=tuple(
                    artifact_refs or (existing.artifact_refs if existing else ())
                ),
                source_refs=tuple(source_refs or (existing.source_refs if existing else ())),
                model_ref=model_ref or (existing.model_ref if existing else None),
                agent_ref=agent_ref or (existing.agent_ref if existing else None),
                worker_ref=worker_ref or (existing.worker_ref if existing else None),
                capability_ref=capability_ref
                or (existing.capability_ref if existing else None),
                config=config or (existing.config if existing else None),
                result_count=(
                    result_count
                    if result_count is not None
                    else (existing.result_count if existing else None)
                ),
                retry=dict(retry) if retry is not None else (existing.retry if existing else None),
                error=err if err is not None else (existing.error if existing else None),
                visibility=visibility_e,
                sensitivity=sensitivity_e,
                payload=dict(payload or {}),
            )
            if existing is not None:
                event = _merge_activity_events(existing, event)
            self._by_stable_id[sid] = event
            replaced = False
            for i, prev in enumerate(self._events):
                if prev.event_id == event.event_id:
                    self._events[i] = event
                    replaced = True
                    break
            if not replaced:
                self._events.append(event)

        self._persist(event)
        return event

    def _persist(self, event: ActivityEvent) -> None:
        if self.persist and self.run_store is not None:
            try:
                from .events import EventType

                self.run_store.append_event(
                    self.operation_id,
                    EventType.ACTIVITY,
                    event.to_envelope_payload(),
                    trace_id=self.trace_id,
                    actor=event.actor_id or "activity",
                    causal_parent=event.parent_event_id,
                    artifact_refs=event.artifact_refs,
                    evidence_refs=event.evidence_refs,
                )
            except Exception:  # noqa: BLE001 — telemetry must not break execution
                pass
        if self.emit_to_hub and self.observability is not None:
            try:
                pub = event.public_dict(for_user=True)
                if pub is not None:
                    self.observability.emit(
                        "activity",
                        event.phase.value,
                        payload=pub,
                        level="error" if event.lifecycle == ActivityLifecycle.FAILED else "info",
                        message=event.title,
                        run_id=self.operation_id,
                        correlation_id=self.trace_id,
                        actor=event.actor_id,
                        success=event.lifecycle == ActivityLifecycle.COMPLETED,
                        duration_ms=None,
                    )
            except Exception:  # noqa: BLE001
                pass

    def public_events(self, *, for_user: bool = True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in self.events:
            pub = event.public_dict(for_user=for_user)
            if pub is not None:
                out.append(pub)
        return out

    def projection(self) -> ActivityProjection:
        projector = ActivityProjector()
        projector.ingest_many(self.events)
        return projector.project()


# --- Operational event adapters (cognition / tools / team) -----------------

_COGNITION_OP_MAP: dict[str, tuple[ActivityCategory, ActivityPhase, ActivityLifecycle, str]] = {
    "tool.started": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.RUNNING, "Tool started"),
    "tool.progress": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.RUNNING, "Tool progress"),
    "tool.completed": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.COMPLETED, "Tool completed"),
    "tool.failed": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.FAILED, "Tool failed"),
    "module.starting": (ActivityCategory.EXECUTION, ActivityPhase.EXECUTION, ActivityLifecycle.STARTING, "Module starting"),
    "module.ready": (ActivityCategory.EXECUTION, ActivityPhase.EXECUTION, ActivityLifecycle.COMPLETED, "Module ready"),
    "artifact.created": (ActivityCategory.ARTIFACT, ActivityPhase.ARTIFACT_PUBLICATION, ActivityLifecycle.COMPLETED, "Artifact created"),
    "source.observed": (ActivityCategory.KNOWLEDGE, ActivityPhase.SOURCE_VALIDATION, ActivityLifecycle.COMPLETED, "Source observed"),
    "knowledge.assimilation_queued": (ActivityCategory.KNOWLEDGE, ActivityPhase.KNOWLEDGE_RETRIEVAL, ActivityLifecycle.QUEUED, "Knowledge assimilation queued"),
    "knowledge.assimilated": (ActivityCategory.KNOWLEDGE, ActivityPhase.KNOWLEDGE_RETRIEVAL, ActivityLifecycle.COMPLETED, "Knowledge assimilated"),
    "job.started": (ActivityCategory.EXECUTION, ActivityPhase.EXECUTION, ActivityLifecycle.RUNNING, "Job started"),
    "job.progress": (ActivityCategory.EXECUTION, ActivityPhase.EXECUTION, ActivityLifecycle.RUNNING, "Job progress"),
    "job.completed": (ActivityCategory.EXECUTION, ActivityPhase.EXECUTION, ActivityLifecycle.COMPLETED, "Job completed"),
    "capability.discovered": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.COMPLETED, "Capability discovered"),
    "capability_invoked": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.RUNNING, "Capability invoked"),
    "capability_searched": (ActivityCategory.TOOL, ActivityPhase.TOOL_INVOCATION, ActivityLifecycle.COMPLETED, "Capability searched"),
}


def activity_from_cognition_operational_event(
    event_type: str,
    payload: Mapping[str, Any] | None,
    *,
    operation_id: str,
    trace_id: str | None = None,
    sequence: int = 0,
) -> ActivityEvent | None:
    mapped = _COGNITION_OP_MAP.get(str(event_type))
    if not mapped:
        return None
    category, phase, lifecycle, default_title = mapped
    data = dict(payload or {})
    capability = _optional_str(data.get("capability_id") or data.get("tool_id"))
    module_id = _optional_str(data.get("module_id"))
    job_id = _optional_str(data.get("job_id"))
    title = default_title
    if capability:
        title = f"{default_title}: {capability}"
    elif module_id:
        title = f"{default_title}: {module_id}"
    elif job_id:
        title = f"{default_title}: {job_id}"

    progress = ProgressMeasurement.indeterminate(basis="cognition_operational")
    pct = data.get("progress")
    if pct is None:
        pct = data.get("percent")
    if isinstance(pct, (int, float)) and float(pct) >= 0:
        ratio = float(pct)
        if ratio > 1.0:
            ratio = ratio / 100.0
        if ratio <= 1.0:
            progress = ProgressMeasurement(
                kind=ProgressKind.MEASURED,
                value=ratio,
                unit="ratio",
                numerator=ratio,
                denominator=1.0,
                basis="reported_job_progress",
            )

    error = None
    if lifecycle == ActivityLifecycle.FAILED:
        error = NormalizedActivityError(
            code=str(data.get("error_code") or "TOOL_FAILED"),
            message=str(data.get("error") or data.get("detail") or "Tool or job failed"),
            retryable=bool(data["retryable"]) if data.get("retryable") is not None else None,
        )

    stable = f"{operation_id}:{event_type}:{capability or module_id or job_id or data.get('event_id') or sequence}"
    return ActivityEvent(
        event_id=stable,
        operation_id=operation_id,
        sequence=sequence,
        category=category,
        phase=phase,
        lifecycle=lifecycle,
        title=title,
        summary=_optional_str(data.get("summary") or data.get("message")),
        actor_type=ActorType.TOOL if category == ActivityCategory.TOOL else ActorType.SYSTEM,
        actor_id=capability or module_id or job_id or "cognition",
        trace_id=trace_id,
        capability_ref=capability,
        worker_ref=_optional_str(data.get("worker_id") or data.get("worker_ref")),
        artifact_refs=tuple(str(x) for x in (data.get("artifact_refs") or data.get("artifact_ids") or ())),
        evidence_refs=tuple(str(x) for x in (data.get("evidence_refs") or ())),
        source_refs=tuple(str(x) for x in (data.get("source_refs") or ())),
        progress=progress,
        result_count=_optional_int(data.get("result_count")),
        error=error,
        payload={"source_event_type": event_type},
    )


def activity_from_team_event(
    team_event: Mapping[str, Any],
    *,
    operation_id: str,
    trace_id: str | None = None,
) -> ActivityEvent | None:
    kind = str(team_event.get("kind") or "").strip()
    if not kind:
        return None
    summary = str(team_event.get("summary") or kind)
    seq = int(team_event.get("seq") or 0)
    lifecycle = ActivityLifecycle.RUNNING
    phase = ActivityPhase.AGENT_DELEGATION
    category = ActivityCategory.AGENT
    lower = kind.lower()
    if "complete" in lower or "accepted" in lower:
        lifecycle = ActivityLifecycle.COMPLETED
        phase = ActivityPhase.COMPLETED
    elif "fail" in lower or "reject" in lower:
        lifecycle = ActivityLifecycle.FAILED
        phase = ActivityPhase.FAILED
    elif "cancel" in lower:
        lifecycle = ActivityLifecycle.CANCELLED
        phase = ActivityPhase.CANCELLED
    elif "assign" in lower or "delegat" in lower:
        lifecycle = ActivityLifecycle.RUNNING
        phase = ActivityPhase.AGENT_DELEGATION
    elif "plan" in lower:
        category = ActivityCategory.PLANNING
        phase = ActivityPhase.PLANNING
    return ActivityEvent(
        event_id=str(team_event.get("event_id") or f"{operation_id}:team:{seq}:{kind}"),
        operation_id=operation_id,
        sequence=seq,
        category=category,
        phase=phase,
        lifecycle=lifecycle,
        title=summary,
        summary=summary,
        actor_type=ActorType.AGENT,
        actor_id=_optional_str((team_event.get("payload") or {}).get("agent_id")) or "team",
        agent_ref=_optional_str((team_event.get("payload") or {}).get("agent_id")),
        trace_id=trace_id,
        progress=ProgressMeasurement.indeterminate(basis="team_activity"),
        payload={"team_kind": kind, "schema_version": team_event.get("schema_version")},
    )
