"""SignalFabricService — validation, auth, persistence, routing, delivery orchestration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from Data.modules.observability.redaction import redact_payload

from .dedupe import SignalDedupe
from .delivery import DeliveryManager
from .envelope import AgentSignal, AgentSignalDelivery, utc_now
from .handlers import HandlerContext, SignalHandler, build_default_handler_registry
from .policies import SignalAuthorizationPolicy, SignalPolicyError
from .router import ResolvedRecipient, SignalRouter, SignalRouterError
from .store import SignalStore
from .subscriptions import SubscriptionManager
from .types import (
    ACK_REQUIRED_TYPES,
    COMMUNICATION_BUDGET_EXCEEDED,
    CRITICAL_NEVER_DROP,
    DEFAULT_MAX_HOPS,
    DEFAULT_MAX_PAYLOAD_BYTES,
    DEFAULT_MAX_REFS,
    DEFAULT_MAX_SUBJECT_LEN,
    DEFAULT_MISSION_SIGNAL_BUDGET,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_TELEMETRY_COALESCE_S,
    MAX_HOPS_EXCEEDED,
    PRIORITY_RANK,
    SIGNAL_BUDGET_EXCEEDED,
    SIGNAL_DUPLICATE,
    SIGNAL_EXPIRED,
    SIGNAL_FEATURE_OFF,
    SIGNAL_INVALID_PAYLOAD,
    SIGNAL_INVALID_RECIPIENT,
    SIGNAL_MAX_HOPS,
    SIGNAL_NOT_FOUND,
    SIGNAL_NO_RECIPIENT,
    DeliveryState,
    RecipientType,
    SenderType,
    SignalPriority,
    SignalStatus,
    SignalType,
    TELEMETRY_TYPES,
)

logger = logging.getLogger("leviathan.agents.signals")


class SignalFabricError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass
class SignalFabricConfig:
    enabled: bool = True
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    default_max_hops: int = DEFAULT_MAX_HOPS
    default_signal_budget: int = DEFAULT_MISSION_SIGNAL_BUDGET
    default_retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    telemetry_coalesce_s: float = DEFAULT_TELEMETRY_COALESCE_S
    retention_days_telemetry: int = 3
    retention_days_normal: int = 30


@dataclass
class _HandlerCtx:
    fleet: Any = None
    blackboard_for: Any = None
    job_runtime: Any = None
    memory_store: Any = None
    knowledge_enqueue: Any = None
    emit_fleet_event: Any = None


class SignalFabricService:
    """Application service for LEVIATHAN Signal Fabric.

    Does NOT execute arbitrary side effects. Side effects go through
    AgentFleetService / ExecutionGateway / knowledge pipeline.
    """

    def __init__(
        self,
        store: SignalStore,
        *,
        fleet: Any = None,
        job_runtime: Any = None,
        memory_store: Any = None,
        enabled: bool = True,
        config: SignalFabricConfig | None = None,
    ) -> None:
        self.store = store
        self.fleet = fleet
        self.job_runtime = job_runtime
        self.memory_store = memory_store
        self.config = config or SignalFabricConfig(enabled=enabled)
        self.config.enabled = enabled if config is None else config.enabled
        self.policy = SignalAuthorizationPolicy()
        self.router = SignalRouter(fleet)
        self.dedupe = SignalDedupe(store)
        self.delivery = DeliveryManager(store, max_attempts=self.config.default_retry_attempts)
        self.subscriptions = SubscriptionManager(store)
        self.handlers: dict[SignalType, SignalHandler] = build_default_handler_registry()
        self._blackboards: dict[str, Any] = {}
        self._telemetry_last: dict[str, float] = {}
        self._knowledge_enqueue: Callable[[AgentSignal], dict[str, Any]] | None = None

    def bind_fleet(self, fleet: Any) -> None:
        self.fleet = fleet
        self.router.bind_fleet(fleet)

    def bind_job_runtime(self, job_runtime: Any) -> None:
        self.job_runtime = job_runtime

    def bind_memory_store(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def bind_knowledge_enqueue(self, fn: Callable[[AgentSignal], dict[str, Any]]) -> None:
        self._knowledge_enqueue = fn

    def register_blackboard(self, run_id: str, board: Any) -> None:
        if run_id:
            self._blackboards[run_id] = board

    def blackboard_for(self, run_id: str) -> Any | None:
        return self._blackboards.get(run_id)

    def initialize(self) -> None:
        self.store.initialize()

    # ── Publish ──────────────────────────────────────────────────────────

    def publish(
        self,
        *,
        signal_type: str | SignalType,
        sender_type: str | SenderType = SenderType.SYSTEM,
        sender_id: str,
        recipient_type: str | RecipientType,
        recipient_id: str,
        subject: str = "",
        payload: dict[str, Any] | None = None,
        mission_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_signal_id: str | None = None,
        correlation_id: str | None = None,
        priority: str | SignalPriority | None = None,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        confidence: float | None = None,
        requires_ack: bool | None = None,
        expires_at: str | None = None,
        idempotency_key: str | None = None,
        hop_count: int = 0,
        max_hops: int | None = None,
        metadata: dict[str, Any] | None = None,
        operator: bool = False,
        enqueue_delivery_job: bool = True,
    ) -> AgentSignal:
        if not self.config.enabled:
            raise SignalFabricError(
                SIGNAL_FEATURE_OFF,
                "Signal Fabric is disabled (LEVIATHAN_FEATURE_SIGNAL_FABRIC)",
                http_status=403,
            )

        st = SignalType(signal_type) if not isinstance(signal_type, SignalType) else signal_type
        snd = SenderType(sender_type) if not isinstance(sender_type, SenderType) else sender_type
        rcp = RecipientType(recipient_type) if not isinstance(recipient_type, RecipientType) else recipient_type
        prio = self._default_priority(st, priority)

        subject_s = (subject or "")[:DEFAULT_MAX_SUBJECT_LEN]
        payload_d = redact_payload(dict(payload or {}))
        self._validate_payload(payload_d, artifact_refs or [], evidence_refs or [])

        if hop_count >= (max_hops if max_hops is not None else self.config.default_max_hops):
            raise SignalFabricError(SIGNAL_MAX_HOPS, MAX_HOPS_EXCEEDED)

        # Mission budget
        if mission_id:
            count = self.store.count_mission_signals(mission_id)
            budget = self._mission_budget(mission_id)
            if count >= budget:
                raise SignalFabricError(
                    SIGNAL_BUDGET_EXCEEDED,
                    COMMUNICATION_BUDGET_EXCEEDED,
                    http_status=429,
                )

        # Telemetry coalescing (never drops critical)
        if st in TELEMETRY_TYPES and st not in CRITICAL_NEVER_DROP and prio == SignalPriority.TELEMETRY:
            if self._should_coalesce(st, sender_id, mission_id):
                existing = self.store.list_signals(
                    sender_id=sender_id,
                    mission_id=mission_id,
                    signal_type=st.value,
                    limit=1,
                )
                if existing:
                    logger.info(
                        "signal_telemetry_coalesced type=%s sender=%s mission=%s",
                        st.value,
                        sender_id,
                        mission_id,
                    )
                    return existing[0]

        # Idempotency
        if idempotency_key:
            existing_sig = self.store.find_by_idempotency(idempotency_key)
            if existing_sig is not None:
                logger.info("signal_duplicate_idempotency key=%s -> %s", idempotency_key, existing_sig.signal_id)
                return existing_sig
            dup = self.dedupe.check_or_register(idempotency_key, "pending", scope="publish")
            if dup and dup != "pending":
                hit = self.store.get_signal(dup)
                if hit:
                    return hit

        agent = self._resolve_sender_agent(snd, sender_id)
        try:
            self.policy.authorize_publish(
                signal_type=st,
                sender_type=snd,
                sender_id=sender_id,
                recipient_type=rcp,
                recipient_id=recipient_id,
                agent=agent,
                operator=operator,
                system=snd == SenderType.SYSTEM,
            )
        except SignalPolicyError as exc:
            raise SignalFabricError(exc.code, exc.message, http_status=exc.http_status) from exc

        now = utc_now()
        signal = AgentSignal(
            signal_id=SignalStore.new_id("sig"),
            signal_type=st,
            sender_type=snd,
            sender_id=sender_id,
            recipient_type=rcp,
            recipient_id=recipient_id,
            mission_id=mission_id,
            run_id=run_id,
            trace_id=trace_id or (mission_id and self._mission_trace(mission_id)) or None,
            parent_signal_id=parent_signal_id,
            correlation_id=correlation_id or parent_signal_id or None,
            priority=prio,
            subject=subject_s,
            payload=payload_d,
            artifact_refs=list(artifact_refs or [])[:DEFAULT_MAX_REFS],
            evidence_refs=list(evidence_refs or [])[:DEFAULT_MAX_REFS],
            confidence=None if confidence is None else max(0.0, min(1.0, float(confidence))),
            requires_ack=bool(requires_ack) if requires_ack is not None else (st in ACK_REQUIRED_TYPES),
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            hop_count=int(hop_count),
            max_hops=int(max_hops if max_hops is not None else self.config.default_max_hops),
            status=SignalStatus.CREATED,
            created_at=now,
            updated_at=now,
            metadata=redact_payload(dict(metadata or {})),
        )

        if idempotency_key:
            self.dedupe.check_or_register(idempotency_key, signal.signal_id, scope="publish")

        self.store.create_signal(signal)
        logger.info(
            "signal_published id=%s type=%s sender=%s recipient=%s mission=%s",
            signal.signal_id,
            st.value,
            sender_id,
            recipient_id,
            mission_id,
        )

        # Route + schedule deliveries
        try:
            resolved = self.router.resolve(
                recipient_type=rcp,
                recipient_id=recipient_id,
                signal_type=st,
                mission_id=mission_id,
                sender_id=sender_id,
            )
        except SignalRouterError as exc:
            signal.status = SignalStatus.FAILED
            self.store.update_signal_status(signal.signal_id, SignalStatus.FAILED)
            raise SignalFabricError(exc.code, exc.message, http_status=404) from exc

        if not resolved:
            raise SignalFabricError(SIGNAL_NO_RECIPIENT, "No recipients resolved", http_status=404)

        self.store.update_signal_status(signal.signal_id, SignalStatus.ROUTED)
        signal.status = SignalStatus.ROUTED

        for r in resolved:
            delivery = AgentSignalDelivery(
                delivery_id=SignalStore.new_id("sdel"),
                signal_id=signal.signal_id,
                recipient_type=r.recipient_type,
                recipient_id=r.recipient_id,
                resolved_agent_id=r.resolved_agent_id,
                state=DeliveryState.PENDING,
                max_attempts=self.config.default_retry_attempts,
                created_at=now,
                updated_at=now,
                metadata={"routingMode": r.routing_mode.value, "reason": r.reason},
            )
            self.store.create_delivery(delivery)
            logger.info(
                "signal_routed id=%s delivery=%s resolved=%s mode=%s",
                signal.signal_id,
                delivery.delivery_id,
                r.resolved_agent_id,
                r.routing_mode.value,
            )
            if enqueue_delivery_job:
                self._enqueue_delivery_job(delivery.delivery_id, priority=prio)

        # Light audit event (avoid spam for telemetry)
        if st not in TELEMETRY_TYPES and self.fleet is not None:
            self._emit_fleet_event(
                agent_id=sender_id if snd in {SenderType.AGENT, SenderType.ORCHESTRATOR} else None,
                mission_id=mission_id,
                category="agents",
                message=f"Signal {st.value}: {subject_s[:120]}",
                payload={"signalId": signal.signal_id, "recipientId": recipient_id},
            )

        return signal

    def publish_http(
        self,
        body: dict[str, Any],
        *,
        operator: bool = False,
    ) -> AgentSignal:
        """HTTP entry — client senderId does not grant agent authority."""
        claimed = body.get("senderId")
        st = SignalType(str(body.get("signalType") or body.get("type") or ""))
        try:
            snd = self.policy.authorize_http_publish(
                claimed_sender_id=str(claimed) if claimed else None,
                signal_type=st,
                operator_mode=operator,
            )
        except SignalPolicyError as exc:
            raise SignalFabricError(exc.code, exc.message, http_status=exc.http_status) from exc
        sender_id = "operator" if operator else "system"
        if operator and claimed:
            # Preserve claimed id in metadata only — authority remains operator.
            meta = dict(body.get("metadata") or {})
            meta["claimedSenderId"] = claimed
            body = {**body, "metadata": meta}
        return self.publish(
            signal_type=st,
            sender_type=snd,
            sender_id=sender_id,
            recipient_type=str(body.get("recipientType") or ""),
            recipient_id=str(body.get("recipientId") or ""),
            subject=str(body.get("subject") or ""),
            payload=dict(body.get("payload") or {}),
            mission_id=body.get("missionId"),
            run_id=body.get("runId"),
            trace_id=body.get("traceId"),
            parent_signal_id=body.get("parentSignalId"),
            correlation_id=body.get("correlationId"),
            priority=body.get("priority"),
            artifact_refs=list(body.get("artifactRefs") or []),
            evidence_refs=list(body.get("evidenceRefs") or []),
            confidence=body.get("confidence"),
            requires_ack=body.get("requiresAck"),
            expires_at=body.get("expiresAt"),
            idempotency_key=body.get("idempotencyKey"),
            hop_count=int(body.get("hopCount") or 0),
            max_hops=body.get("maxHops"),
            metadata=dict(body.get("metadata") or {}),
            operator=operator,
        )

    # ── Process delivery (worker) ────────────────────────────────────────

    def process_delivery(self, delivery_id: str, *, worker_id: str = "signal-worker") -> dict[str, Any]:
        delivery = self.store.get_delivery(delivery_id)
        if delivery is None:
            return {"status": "missing_delivery"}
        signal = self.store.get_signal(delivery.signal_id)
        if signal is None:
            return {"status": "missing_signal"}

        if signal.expires_at and signal.expires_at <= utc_now():
            self.store.update_signal_status(signal.signal_id, SignalStatus.EXPIRED)
            delivery.state = DeliveryState.EXPIRED
            self.store.update_delivery(delivery)
            return {"status": "expired", "signalId": signal.signal_id}

        if signal.hop_count >= signal.max_hops:
            self.delivery.dead_letter(
                delivery,
                signal,
                reason=MAX_HOPS_EXCEEDED,
                error=MAX_HOPS_EXCEEDED,
                retryable=False,
            )
            return {"status": "max_hops", "signalId": signal.signal_id}

        try:
            result = self._dispatch_handler(signal, delivery)
            delivery = self.delivery.mark_delivered(delivery)
            if signal.requires_ack:
                # Auto-ack for system/internal handlers after successful consume path
                # only when handler explicitly marks ack; otherwise leave for consumer.
                if result.get("autoAck"):
                    self.store.ack_delivery(delivery.delivery_id, consumer=worker_id)
                    delivery = self.store.mark_consumed(delivery.delivery_id) or delivery
            else:
                delivery = self.store.mark_consumed(delivery.delivery_id) or delivery
            self._maybe_complete_signal(signal.signal_id)
            logger.info(
                "signal_delivered id=%s delivery=%s handler=%s",
                signal.signal_id,
                delivery.delivery_id,
                result.get("handler"),
            )
            return {
                "status": "delivered",
                "signalId": signal.signal_id,
                "deliveryId": delivery.delivery_id,
                "handlerResult": result,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("signal_delivery_failed id=%s delivery=%s", signal.signal_id, delivery_id)
            self.delivery.record_failure(delivery, signal, error=str(exc), retryable=True)
            return {"status": "failed", "error": str(exc)[:300]}

    def process_pending(self, *, worker_id: str, limit: int = 8) -> list[dict[str, Any]]:
        claimed = self.store.claim_pending_deliveries(worker_id=worker_id, limit=limit)
        return [self.process_delivery(d.delivery_id, worker_id=worker_id) for d in claimed]

    def ack(self, signal_id: str, *, delivery_id: str | None = None, consumer: str = "operator") -> dict[str, Any]:
        deliveries = self.store.list_deliveries(signal_id=signal_id, limit=50)
        if delivery_id:
            deliveries = [d for d in deliveries if d.delivery_id == delivery_id]
        if not deliveries:
            raise SignalFabricError(SIGNAL_NOT_FOUND, "No deliveries to acknowledge", http_status=404)
        acked = []
        for d in deliveries:
            updated = self.store.ack_delivery(d.delivery_id, consumer=consumer)
            if updated:
                acked.append(updated.public_dict())
                logger.info("signal_ack signal=%s delivery=%s consumer=%s", signal_id, d.delivery_id, consumer)
        return {"acknowledged": acked}

    def causal_chain(self, signal_id: str, *, depth: int = 4, limit: int = 40) -> dict[str, Any]:
        signal = self.store.get_signal(signal_id)
        if signal is None:
            raise SignalFabricError(SIGNAL_NOT_FOUND, f"Signal {signal_id} not found", http_status=404)
        depth = max(1, min(int(depth), 8))
        limit = max(1, min(int(limit), 100))

        parent = self.store.get_signal(signal.parent_signal_id) if signal.parent_signal_id else None
        related: list[AgentSignal] = []
        if signal.correlation_id:
            related = [
                s
                for s in self.store.list_signals(correlation_id=signal.correlation_id, limit=limit)
                if s.signal_id != signal_id
            ]
        children = [
            s
            for s in self.store.list_signals(limit=limit)
            if s.parent_signal_id == signal_id
        ][:limit]
        # Walk ancestors bounded
        ancestors: list[AgentSignal] = []
        cursor = parent
        for _ in range(depth):
            if cursor is None:
                break
            ancestors.append(cursor)
            cursor = self.store.get_signal(cursor.parent_signal_id) if cursor.parent_signal_id else None

        deliveries = self.store.list_deliveries(signal_id=signal_id, limit=50)
        events: list[dict[str, Any]] = []
        if self.fleet is not None and signal.mission_id:
            try:
                for ev in self.fleet.store.list_events(mission_id=signal.mission_id, limit=30):
                    events.append(ev.public_dict())
            except Exception:  # noqa: BLE001
                pass

        mission = None
        if self.fleet is not None and signal.mission_id:
            try:
                m = self.fleet.store.get_mission(signal.mission_id)
                mission = m.public_dict() if m else None
            except Exception:  # noqa: BLE001
                pass

        return {
            "signal": signal.public_dict(),
            "parent": parent.public_dict() if parent else None,
            "ancestors": [a.public_dict() for a in ancestors],
            "children": [c.public_dict() for c in children],
            "related": [r.public_dict() for r in related[:limit]],
            "deliveries": [d.public_dict() for d in deliveries],
            "mission": mission,
            "events": events[:30],
            "truth": {"bounded_depth": True, "bounded_count": True},
        }

    def metrics(self, *, window_minutes: int = 60) -> dict[str, Any]:
        return self.store.metrics_snapshot(window_minutes=window_minutes)

    def graph(self, *, window_hours: int = 24, mission_id: str | None = None) -> dict[str, Any]:
        return self.store.communication_graph(window_hours=window_hours, mission_id=mission_id)

    def list_dead_letters(self, *, limit: int = 100, offset: int = 0) -> list[Any]:
        return self.store.list_dead_letters(limit=limit, offset=offset)

    def retry_dead_letter(self, dead_letter_id: str) -> AgentSignalDelivery:
        delivery = self.delivery.retry_dead_letter(dead_letter_id)
        if delivery is None:
            raise SignalFabricError(SIGNAL_NOT_FOUND, "Dead letter not found or not retryable", http_status=404)
        self._enqueue_delivery_job(delivery.delivery_id, priority=SignalPriority.HIGH)
        return delivery

    def housekeeping(self) -> dict[str, Any]:
        expired = self.store.expire_due_signals()
        purged = self.store.purge_old_telemetry(older_than_days=self.config.retention_days_telemetry)
        return {"expired": expired, "telemetryPurged": purged}

    def agent_signal_stats(self, agent_id: str, *, window_hours: int = 24) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat(timespec="seconds")
        sent = self.store.list_signals(sender_id=agent_id, limit=500)
        recv = self.store.list_signals(recipient_id=agent_id, limit=500)
        sent = [s for s in sent if s.created_at >= since]
        recv = [s for s in recv if s.created_at >= since]
        handoffs = sum(1 for s in sent if s.signal_type == SignalType.TASK_HANDOFF)
        verifies = sum(1 for s in sent if s.signal_type == SignalType.VERIFY_REQUEST)
        blocks = sum(1 for s in sent if s.signal_type in {SignalType.BLOCK, SignalType.REJECTED})
        return {
            "agentId": agent_id,
            "signalsSent": len(sent),
            "signalsReceived": len(recv),
            "handoffs": handoffs,
            "verificationRequests": verifies,
            "blocksRejections": blocks,
            "windowHours": window_hours,
            "truth": {"from_durable_store": True},
        }

    # ── Integration helpers for fleet / multi ────────────────────────────

    def emit_mission_lifecycle(
        self,
        *,
        signal_type: SignalType,
        mission_id: str,
        agent_id: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentSignal | None:
        if not self.config.enabled:
            return None
        try:
            return self.publish(
                signal_type=signal_type,
                sender_type=SenderType.SYSTEM,
                sender_id="system",
                recipient_type=RecipientType.AGENT,
                recipient_id=agent_id,
                subject=subject,
                payload=payload or {},
                mission_id=mission_id,
                run_id=run_id,
                trace_id=trace_id,
                priority=SignalPriority.NORMAL,
                enqueue_delivery_job=True,
            )
        except SignalFabricError as exc:
            logger.warning("lifecycle_signal_skipped code=%s msg=%s", exc.code, exc.message)
            return None

    # ── internals ────────────────────────────────────────────────────────

    def _dispatch_handler(self, signal: AgentSignal, delivery: AgentSignalDelivery) -> dict[str, Any]:
        handler = self.handlers.get(signal.signal_type)
        if handler is None:
            return {"handler": "noop", "autoAck": True}
        ctx = _HandlerCtx(
            fleet=self.fleet,
            blackboard_for=self.blackboard_for,
            job_runtime=self.job_runtime,
            memory_store=self.memory_store,
            knowledge_enqueue=self._knowledge_enqueue or self._default_knowledge_enqueue,
            emit_fleet_event=self._emit_fleet_event,
        )
        result = handler.handle(signal, delivery, ctx)  # type: ignore[arg-type]
        # Task/verify/control that completed successfully can auto-ack.
        if signal.requires_ack and result.get("status") in {
            "mission_created",
            "idempotent_hit",
            "linked_existing",
            "verify_mission_created",
            "cancelled",
            "blocked",
            "unblocked",
        }:
            result = {**result, "autoAck": True}
        return result

    def _default_knowledge_enqueue(self, signal: AgentSignal) -> dict[str, Any]:
        if self.job_runtime is None:
            return {"status": "job_runtime_unavailable"}
        payload = dict(signal.payload or {})
        claim = str(payload.get("claim") or signal.subject or "knowledge candidate")
        try:
            from Data.modules.knowledge.pipeline import KnowledgeArtifact

            artifact = KnowledgeArtifact.create(
                artifact_type="signal_knowledge_candidate",
                producer=f"signal_fabric:{signal.sender_id}",
                title=claim[:200],
                content=str(payload.get("content") or claim),
                run_id=signal.run_id,
                trace_id=signal.trace_id,
                confidence=signal.confidence,
                evidence_refs=list(signal.evidence_refs),
                provenance={
                    "signal_id": signal.signal_id,
                    "mission_id": signal.mission_id,
                    "verification_state": payload.get("verificationState"),
                },
                tags=list(payload.get("tags") or ["signal_fabric"]),
                domain=payload.get("domain"),
            )
            dedupe_key = signal.idempotency_key or f"knowledge:{signal.signal_id}"
            # Register action dedupe so duplicate delivery cannot double-enqueue promote.
            existing = self.dedupe.check_or_register(
                f"action:{dedupe_key}", signal.signal_id, scope="knowledge"
            )
            if existing:
                return {"status": "idempotent_suppressed"}
            job = self.job_runtime.enqueue(
                capability_id="knowledge.commit",
                arguments={
                    "artifact": artifact.public_dict(),
                    "idempotency_key": dedupe_key,
                },
                requested_by="signal_fabric",
                idempotency_key=dedupe_key,
                domain="agents",
                correlation_id=signal.correlation_id,
                trace_id=signal.trace_id,
                latency_class="background",
            )
            return {"status": "enqueued", "jobId": job.job_id}
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_enqueue_failed signal=%s err=%s", signal.signal_id, exc)
            return {"status": "enqueue_failed", "error": str(exc)[:300]}

    def _enqueue_delivery_job(self, delivery_id: str, *, priority: SignalPriority) -> None:
        if self.job_runtime is None:
            # Inline processing fallback for tests / non-worker environments.
            self.process_delivery(delivery_id, worker_id="inline")
            return
        try:
            self.job_runtime.enqueue(
                capability_id="agent_signal.deliver",
                arguments={"delivery_id": delivery_id},
                requested_by="signal_fabric",
                priority=PRIORITY_RANK.get(priority, 50),
                latency_class="standard" if priority in {SignalPriority.CRITICAL, SignalPriority.HIGH} else "background",
                domain="agents",
                idempotency_key=f"agent_signal.deliver:{delivery_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("enqueue_delivery_failed delivery=%s err=%s — inline fallback", delivery_id, exc)
            self.process_delivery(delivery_id, worker_id="inline-fallback")

    def _validate_payload(
        self,
        payload: dict[str, Any],
        artifact_refs: list[str],
        evidence_refs: list[str],
    ) -> None:
        raw = json.dumps(payload, default=str)
        if len(raw.encode("utf-8")) > self.config.max_payload_bytes:
            raise SignalFabricError(
                SIGNAL_INVALID_PAYLOAD,
                f"Payload exceeds max {self.config.max_payload_bytes} bytes — use artifact refs",
            )
        if len(artifact_refs) > DEFAULT_MAX_REFS or len(evidence_refs) > DEFAULT_MAX_REFS:
            raise SignalFabricError(SIGNAL_INVALID_PAYLOAD, "Too many refs")

    def _default_priority(
        self,
        st: SignalType,
        priority: str | SignalPriority | None,
    ) -> SignalPriority:
        if priority is not None:
            return SignalPriority(priority) if not isinstance(priority, SignalPriority) else priority
        if st in {SignalType.BLOCK, SignalType.CANCEL}:
            return SignalPriority.CRITICAL
        if st in {SignalType.VERIFY_REQUEST, SignalType.REJECTED, SignalType.ERROR, SignalType.UNBLOCK}:
            return SignalPriority.HIGH
        if st in TELEMETRY_TYPES:
            return SignalPriority.TELEMETRY
        if st in {SignalType.PROGRESS, SignalType.WARNING}:
            return SignalPriority.LOW
        return SignalPriority.NORMAL

    def _should_coalesce(self, st: SignalType, sender_id: str, mission_id: str | None) -> bool:
        import time

        key = f"{st.value}:{sender_id}:{mission_id or ''}"
        now = time.time()
        last = self._telemetry_last.get(key, 0.0)
        if now - last < self.config.telemetry_coalesce_s:
            return True
        self._telemetry_last[key] = now
        return False

    def _resolve_sender_agent(self, snd: SenderType, sender_id: str) -> Any | None:
        if self.fleet is None:
            return None
        if snd not in {SenderType.AGENT, SenderType.ORCHESTRATOR}:
            return None
        try:
            return self.fleet.get_agent(sender_id)
        except Exception:  # noqa: BLE001
            return None

    def _mission_budget(self, mission_id: str) -> int:
        if self.fleet is None:
            return self.config.default_signal_budget
        try:
            m = self.fleet.store.get_mission(mission_id)
            if m and isinstance(m.metadata, dict):
                raw = m.metadata.get("maxSignals") or m.metadata.get("signalBudget")
                if raw is not None:
                    return max(1, int(raw))
            agent = self.fleet.get_agent(m.agent_id) if m else None
            if agent and agent.orchestrator:
                # Derive a generous budget from delegation depth * parallelism.
                depth = max(1, agent.orchestrator.max_delegation_depth)
                par = max(1, agent.orchestrator.parallelism_limit)
                return max(self.config.default_signal_budget, depth * par * 40)
        except Exception:  # noqa: BLE001
            pass
        return self.config.default_signal_budget

    def _mission_trace(self, mission_id: str) -> str | None:
        if self.fleet is None:
            return None
        try:
            m = self.fleet.store.get_mission(mission_id)
            return m.trace_id if m else None
        except Exception:  # noqa: BLE001
            return None

    def _maybe_complete_signal(self, signal_id: str) -> None:
        deliveries = self.store.list_deliveries(signal_id=signal_id, limit=100)
        if not deliveries:
            return
        terminal = {
            DeliveryState.CONSUMED,
            DeliveryState.ACKNOWLEDGED,
            DeliveryState.DEAD_LETTER,
            DeliveryState.EXPIRED,
        }
        if all(d.state in terminal or d.state == DeliveryState.DELIVERED for d in deliveries):
            # If any requires ack and not acked, keep open.
            signal = self.store.get_signal(signal_id)
            if signal and signal.requires_ack:
                if not all(
                    d.state in {DeliveryState.ACKNOWLEDGED, DeliveryState.CONSUMED, DeliveryState.DEAD_LETTER}
                    for d in deliveries
                ):
                    return
            self.store.update_signal_status(signal_id, SignalStatus.COMPLETED)

    def _emit_fleet_event(
        self,
        *,
        agent_id: str | None,
        mission_id: str | None,
        category: str,
        message: str,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.fleet is None:
            return
        try:
            from Data.modules.agents.fleet_types import AgentEvent
            from Data.modules.agents.store import AgentFleetStore

            ev = AgentEvent(
                event_id=AgentFleetStore.new_id("aevt"),
                agent_id=agent_id,
                mission_id=mission_id,
                category=category,
                message=message,
                level=level,
                payload=dict(payload or {}),
                created_at=utc_now(),
            )
            self.fleet.store.append_event(ev)
        except Exception as exc:  # noqa: BLE001
            logger.debug("fleet_event_emit_failed: %s", exc)
