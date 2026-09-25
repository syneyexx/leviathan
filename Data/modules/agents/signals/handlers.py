"""Typed Signal Fabric handlers — small explicit registry, no god-switch."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .envelope import AgentSignal, AgentSignalDelivery
from .types import BLACKBOARD_PROJECTION, SignalType

logger = logging.getLogger("leviathan.agents.signals.handlers")


class HandlerContext(Protocol):
    fleet: Any
    blackboard_for: Any  # (run_id) -> AgentBlackboard | None
    job_runtime: Any
    memory_store: Any
    knowledge_enqueue: Any  # callable for knowledge candidate
    emit_fleet_event: Any


class SignalHandler:
    signal_types: frozenset[SignalType] = frozenset()

    def handle(
        self,
        signal: AgentSignal,
        delivery: AgentSignalDelivery,
        ctx: HandlerContext,
    ) -> dict[str, Any]:
        raise NotImplementedError


class InformationalSignalHandler(SignalHandler):
    signal_types = frozenset(
        {
            SignalType.FINDING,
            SignalType.EVIDENCE,
            SignalType.HYPOTHESIS,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.DECISION,
            SignalType.PROGRESS,
            SignalType.WARNING,
            SignalType.ARTIFACT_READY,
            SignalType.COMPLETED,
        }
    )

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        projected = False
        kind = BLACKBOARD_PROJECTION.get(signal.signal_type)
        if kind and signal.run_id:
            board = ctx.blackboard_for(signal.run_id) if ctx.blackboard_for else None
            if board is not None:
                supersedes = None
                if isinstance(signal.payload, dict):
                    supersedes = signal.payload.get("supersedes") or signal.metadata.get("supersedes")
                board.post(
                    kind=kind,
                    content=signal.subject or str(signal.payload.get("claim") or signal.payload.get("summary") or signal.signal_type.value),
                    author=signal.sender_id,
                    confidence=float(signal.confidence if signal.confidence is not None else 0.5),
                    provenance={
                        "signal_id": signal.signal_id,
                        "sender": signal.sender_id,
                        "mission_id": signal.mission_id,
                        "trace_id": signal.trace_id,
                        "artifact_refs": list(signal.artifact_refs),
                        "evidence_refs": list(signal.evidence_refs),
                        "projection": True,
                    },
                    supersedes=supersedes,
                    metadata={"signal_projection": True, "signal_type": signal.signal_type.value},
                )
                projected = True
        return {"handler": "informational", "blackboardProjected": projected}


class TaskSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.TASK_REQUEST, SignalType.TASK_HANDOFF})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        if ctx.fleet is None:
            return {"handler": "task", "status": "fleet_unavailable"}
        agent_id = delivery.resolved_agent_id or signal.recipient_id
        payload = dict(signal.payload or {})
        request = str(payload.get("request") or payload.get("task") or signal.subject or "").strip()
        if not request:
            return {"handler": "task", "status": "missing_request"}

        # Idempotent mission creation via metadata key on fleet side.
        dedupe = signal.idempotency_key or f"{signal.mission_id}:{signal.signal_id}:handoff"
        existing_mission_id = payload.get("missionId") or payload.get("childMissionId")
        if existing_mission_id:
            return {
                "handler": "task",
                "status": "linked_existing",
                "missionId": existing_mission_id,
            }

        # Check if a child was already created for this signal.
        meta_marker = f"signal:{signal.signal_id}"
        try:
            missions = ctx.fleet.store.list_missions(agent_id=agent_id, limit=50)
            for m in missions:
                if (m.metadata or {}).get("signalFabricKey") == dedupe:
                    return {
                        "handler": "task",
                        "status": "idempotent_hit",
                        "missionId": m.mission_id,
                    }
                if (m.metadata or {}).get("parentSignalId") == signal.signal_id:
                    return {
                        "handler": "task",
                        "status": "idempotent_hit",
                        "missionId": m.mission_id,
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("task_handler_list_failed signal=%s err=%s", signal.signal_id, exc)

        child = ctx.fleet.launch_mission(
            agent_id=agent_id,
            request=request,
            title=str(payload.get("title") or signal.subject or "signal-handoff")[:200],
            priority=str(payload.get("priority") or "med"),
            parent_mission_id=signal.mission_id,
            depth=int(payload.get("depth") or 0) + 1,
            dry_run=bool(payload.get("dryRun") or False),
            use_jobs=bool(payload.get("useJobs") or False),
            metadata={
                "signalFabricKey": dedupe,
                "parentSignalId": signal.signal_id,
                "correlationId": signal.correlation_id,
                "traceId": signal.trace_id,
                "source": "signal_fabric",
                meta_marker: True,
            },
        )
        # Preserve parent/trace correlation on the child mission when provided.
        if signal.trace_id and child.trace_id != signal.trace_id:
            child.trace_id = signal.trace_id
            child.metadata = {
                **dict(child.metadata or {}),
                "traceId": signal.trace_id,
                "correlationId": signal.correlation_id or signal.trace_id,
            }
            ctx.fleet.store.update_mission(child)
        if signal.run_id and not child.run_id:
            child.run_id = signal.run_id
            ctx.fleet.store.update_mission(child)
        if ctx.emit_fleet_event:
            ctx.emit_fleet_event(
                agent_id=agent_id,
                mission_id=child.mission_id,
                category="tasks",
                message=f"Signal {signal.signal_type.value} created mission {child.mission_id}",
                payload={"signalId": signal.signal_id},
            )
        return {
            "handler": "task",
            "status": "mission_created",
            "missionId": child.mission_id,
        }


class VerificationSignalHandler(SignalHandler):
    signal_types = frozenset(
        {
            SignalType.VERIFY_REQUEST,
            SignalType.VERIFIED,
            SignalType.REJECTED,
            SignalType.CHALLENGE,
        }
    )

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        if signal.signal_type == SignalType.VERIFY_REQUEST and ctx.fleet is not None:
            agent_id = delivery.resolved_agent_id or signal.recipient_id
            payload = dict(signal.payload or {})
            claim = str(payload.get("claim") or signal.subject or "verify")
            checks = payload.get("expectedChecks") or payload.get("checks") or []
            request = (
                f"VERIFY_REQUEST\nclaim: {claim}\n"
                f"artifact_refs: {signal.artifact_refs}\n"
                f"evidence_refs: {signal.evidence_refs}\n"
                f"expected_checks: {checks}\n"
                f"origin_signal: {signal.signal_id}\n"
                f"Respond with VERIFIED or REJECTED and structured rationale."
            )
            dedupe = signal.idempotency_key or f"{signal.mission_id}:{signal.signal_id}:verify"
            try:
                for m in ctx.fleet.store.list_missions(agent_id=agent_id, limit=50):
                    if (m.metadata or {}).get("signalFabricKey") == dedupe:
                        return {
                            "handler": "verification",
                            "status": "idempotent_hit",
                            "missionId": m.mission_id,
                        }
            except Exception:  # noqa: BLE001
                pass
            mission = ctx.fleet.launch_mission(
                agent_id=agent_id,
                request=request,
                title=f"Verify: {claim}"[:200],
                parent_mission_id=signal.mission_id,
                dry_run=bool(payload.get("dryRun") or False),
                metadata={
                    "signalFabricKey": dedupe,
                    "parentSignalId": signal.signal_id,
                    "verification": True,
                    "source": "signal_fabric",
                },
            )
            return {
                "handler": "verification",
                "status": "verify_mission_created",
                "missionId": mission.mission_id,
            }

        # VERIFIED / REJECTED / CHALLENGE — project + audit; do not overwrite peers.
        if signal.run_id and ctx.blackboard_for:
            board = ctx.blackboard_for(signal.run_id)
            if board is not None:
                board.post(
                    kind="decision" if signal.signal_type != SignalType.CHALLENGE else "open_question",
                    content=signal.subject or signal.signal_type.value,
                    author=signal.sender_id,
                    confidence=float(signal.confidence if signal.confidence is not None else 0.5),
                    provenance={
                        "signal_id": signal.signal_id,
                        "target_signal_id": (signal.payload or {}).get("targetSignalId"),
                        "sender": signal.sender_id,
                        "mission_id": signal.mission_id,
                        "trace_id": signal.trace_id,
                        "projection": True,
                    },
                    metadata={"signal_projection": True, "signal_type": signal.signal_type.value},
                )
        return {"handler": "verification", "status": signal.signal_type.value.lower()}


class ControlSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.BLOCK, SignalType.UNBLOCK, SignalType.CANCEL})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        if ctx.fleet is None:
            return {"handler": "control", "status": "fleet_unavailable"}
        payload = dict(signal.payload or {})
        target_mission = payload.get("targetMissionId") or signal.mission_id
        if signal.signal_type == SignalType.CANCEL and target_mission:
            mission = ctx.fleet.cancel_mission(target_mission)
            return {
                "handler": "control",
                "status": "cancelled",
                "missionId": mission.mission_id,
                "missionStatus": mission.status.value,
            }
        if signal.signal_type == SignalType.BLOCK and target_mission:
            # Record block via cancel_requested without inventing new authority paths.
            mission = ctx.fleet.store.get_mission(target_mission)
            if mission is None:
                return {"handler": "control", "status": "mission_not_found"}
            mission.cancel_requested = True
            mission.metadata = {
                **dict(mission.metadata or {}),
                "blockedBySignal": signal.signal_id,
                "blockReason": payload.get("reason") or signal.subject,
            }
            mission.updated_at = mission.updated_at
            ctx.fleet.store.update_mission(mission)
            if ctx.emit_fleet_event:
                ctx.emit_fleet_event(
                    agent_id=mission.agent_id,
                    mission_id=mission.mission_id,
                    category="errors",
                    message=f"BLOCK via signal {signal.signal_id}: {payload.get('reason') or signal.subject}",
                    level="warn",
                    payload={"signalId": signal.signal_id},
                )
            return {"handler": "control", "status": "blocked", "missionId": target_mission}
        if signal.signal_type == SignalType.UNBLOCK and target_mission:
            mission = ctx.fleet.store.get_mission(target_mission)
            if mission is None:
                return {"handler": "control", "status": "mission_not_found"}
            meta = dict(mission.metadata or {})
            meta.pop("blockedBySignal", None)
            meta.pop("blockReason", None)
            meta["unblockedBySignal"] = signal.signal_id
            mission.metadata = meta
            mission.cancel_requested = False
            ctx.fleet.store.update_mission(mission)
            return {"handler": "control", "status": "unblocked", "missionId": target_mission}
        return {"handler": "control", "status": "noop"}


class KnowledgeCandidateSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.KNOWLEDGE_CANDIDATE})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        payload = dict(signal.payload or {})
        verification_state = str(payload.get("verificationState") or payload.get("verification") or "").lower()
        if verification_state not in {"verified", "accepted", "passed"}:
            return {
                "handler": "knowledge",
                "status": "held_unverified",
                "truth": {"knowledge_candidate_not_canonical": True},
            }
        if not ctx.knowledge_enqueue:
            return {
                "handler": "knowledge",
                "status": "pipeline_unavailable",
                "truth": {"knowledge_candidate_not_canonical": True},
            }
        result = ctx.knowledge_enqueue(signal)
        return {
            "handler": "knowledge",
            "status": result.get("status", "enqueued"),
            "jobId": result.get("jobId"),
            "truth": {"knowledge_candidate_not_canonical": True, "uses_existing_pipeline": True},
        }


class MemoryCandidateSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.MEMORY_CANDIDATE})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        payload = dict(signal.payload or {})
        content = str(payload.get("content") or signal.subject or "").strip()
        if not content:
            return {"handler": "memory", "status": "missing_content"}
        if ctx.memory_store is None:
            return {
                "handler": "memory",
                "status": "UNSUPPORTED",
                "truth": {"memory_write_unavailable": True},
            }
        try:
            trust = str(payload.get("trust") or "explicit")
            if trust == "model_output":
                return {
                    "handler": "memory",
                    "status": "REJECTED_TRUST",
                    "truth": {"memory_refuses_model_output_trust": True},
                }
            record = ctx.memory_store.create(
                content=content,
                kind=str(payload.get("kind") or "NOTE"),
                source=f"signal:{signal.sender_id}",
                trust=trust,
                run_id=signal.run_id,
                tags=list(payload.get("tags") or ["signal_fabric"]),
                metadata={
                    "signalId": signal.signal_id,
                    "missionId": signal.mission_id,
                    "traceId": signal.trace_id,
                },
                confidence=float(signal.confidence if signal.confidence is not None else 0.5),
                source_refs=list(signal.evidence_refs or signal.artifact_refs or []),
            )
            return {
                "handler": "memory",
                "status": "STORED",
                "memoryId": getattr(record, "memory_id", None),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "handler": "memory",
                "status": "PENDING",
                "error": str(exc)[:300],
                "truth": {"memory_write_failed_honestly": True},
            }


class ResourceSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.RESOURCE_REQUEST, SignalType.WORKER_SPAWN_REQUEST})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        # Record intent only — never spawn unrestricted workers from a signal.
        if ctx.emit_fleet_event:
            ctx.emit_fleet_event(
                agent_id=delivery.resolved_agent_id or signal.sender_id,
                mission_id=signal.mission_id,
                category="system",
                message=f"{signal.signal_type.value}: {signal.subject}",
                payload={
                    "signalId": signal.signal_id,
                    "requested": dict(signal.payload or {}),
                    "truth": {"signal_does_not_spawn_workers_directly": True},
                },
            )
        return {
            "handler": "resource",
            "status": "recorded",
            "truth": {"no_direct_worker_spawn": True},
        }


class HeartbeatSignalHandler(SignalHandler):
    signal_types = frozenset({SignalType.HEARTBEAT, SignalType.ERROR})

    def handle(self, signal: AgentSignal, delivery: AgentSignalDelivery, ctx: HandlerContext) -> dict[str, Any]:
        # Heartbeats: persist/delivery only — never Blackboard.
        if signal.signal_type == SignalType.ERROR and ctx.emit_fleet_event:
            ctx.emit_fleet_event(
                agent_id=signal.sender_id,
                mission_id=signal.mission_id,
                category="errors",
                message=signal.subject or "signal error",
                level="error",
                payload={"signalId": signal.signal_id, "payload": signal.payload},
            )
        return {"handler": "heartbeat" if signal.signal_type == SignalType.HEARTBEAT else "error"}


def build_default_handler_registry() -> dict[SignalType, SignalHandler]:
    handlers: list[SignalHandler] = [
        InformationalSignalHandler(),
        TaskSignalHandler(),
        VerificationSignalHandler(),
        ControlSignalHandler(),
        KnowledgeCandidateSignalHandler(),
        MemoryCandidateSignalHandler(),
        ResourceSignalHandler(),
        HeartbeatSignalHandler(),
    ]
    registry: dict[SignalType, SignalHandler] = {}
    for h in handlers:
        for t in h.signal_types:
            registry[t] = h
    return registry
