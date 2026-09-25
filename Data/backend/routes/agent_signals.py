"""Agent Signal Fabric HTTP routes — structured coordination, not chat."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.agents.signals import SignalFabricError, SignalFabricService


def _raise(exc: SignalFabricError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class SignalPublishBody(BaseModel):
    signalType: str = Field(min_length=1, max_length=64)
    recipientType: str = Field(min_length=1, max_length=32)
    recipientId: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    senderId: str | None = Field(default=None, max_length=200)
    missionId: str | None = None
    runId: str | None = None
    traceId: str | None = None
    parentSignalId: str | None = None
    correlationId: str | None = None
    priority: str | None = None
    artifactRefs: list[str] = Field(default_factory=list, max_length=32)
    evidenceRefs: list[str] = Field(default_factory=list, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    requiresAck: bool | None = None
    expiresAt: str | None = None
    idempotencyKey: str | None = Field(default=None, max_length=200)
    hopCount: int = Field(default=0, ge=0, le=64)
    maxHops: int | None = Field(default=None, ge=1, le=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    operator: bool = False


class SignalAckBody(BaseModel):
    deliveryId: str | None = None
    consumer: str = Field(default="operator", max_length=120)


def build_signals_router(fabric: SignalFabricService) -> APIRouter:
    """Register BEFORE /api/agents/{agent_id} catch-alls to avoid path shadowing."""
    router = APIRouter(tags=["agent-signals"])

    @router.get("/api/agents/signals")
    def list_signals(
        agentId: str | None = None,
        senderId: str | None = None,
        recipientId: str | None = None,
        missionId: str | None = None,
        runId: str | None = None,
        traceId: str | None = None,
        signalType: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        correlationId: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> dict:
        if not fabric.config.enabled:
            return {
                "signals": [],
                "enabled": False,
                "truth": {"signal_fabric_disabled": True},
            }
        signals = fabric.store.list_signals(
            agent_id=agentId,
            sender_id=senderId,
            recipient_id=recipientId,
            mission_id=missionId,
            run_id=runId,
            trace_id=traceId,
            signal_type=signalType,
            priority=priority,
            status=status,
            correlation_id=correlationId,
            limit=limit,
            offset=offset,
        )
        return {
            "signals": [s.public_dict() for s in signals],
            "enabled": True,
            "truth": {"from_durable_store": True, "signal_is_not_chat": True},
        }

    @router.get("/api/agents/signals/metrics")
    def signal_metrics(windowMinutes: int = Query(60, ge=1, le=1440)) -> dict:
        if not fabric.config.enabled:
            return {"enabled": False, "metrics": {}, "truth": {"signal_fabric_disabled": True}}
        return {"enabled": True, "metrics": fabric.metrics(window_minutes=windowMinutes)}

    @router.get("/api/agents/signals/graph")
    def signal_graph(
        windowHours: int = Query(24, ge=1, le=168),
        missionId: str | None = None,
    ) -> dict:
        if not fabric.config.enabled:
            return {"enabled": False, "graph": {"nodes": [], "edges": []}, "truth": {"signal_fabric_disabled": True}}
        return {
            "enabled": True,
            "graph": fabric.graph(window_hours=windowHours, mission_id=missionId),
        }

    @router.get("/api/agents/signals/dead-letters")
    def list_dead_letters(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> dict:
        if not fabric.config.enabled:
            return {"deadLetters": [], "enabled": False}
        items = fabric.list_dead_letters(limit=limit, offset=offset)
        return {"deadLetters": [d.public_dict() for d in items], "enabled": True}

    @router.post("/api/agents/signals/dead-letters/{dead_letter_id}/retry")
    def retry_dead_letter(dead_letter_id: str) -> dict:
        try:
            delivery = fabric.retry_dead_letter(dead_letter_id)
        except SignalFabricError as exc:
            _raise(exc)
            raise
        return {"delivery": delivery.public_dict()}

    @router.get("/api/agents/signals/{signal_id}")
    def get_signal(signal_id: str) -> dict:
        signal = fabric.store.get_signal(signal_id)
        if signal is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SIGNAL_NOT_FOUND", "message": signal_id},
            )
        return {"signal": signal.public_dict()}

    @router.get("/api/agents/signals/{signal_id}/deliveries")
    def get_deliveries(signal_id: str, limit: int = Query(100, ge=1, le=500)) -> dict:
        deliveries = fabric.store.list_deliveries(signal_id=signal_id, limit=limit)
        return {"deliveries": [d.public_dict() for d in deliveries]}

    @router.get("/api/agents/signals/{signal_id}/chain")
    def get_chain(
        signal_id: str,
        depth: int = Query(4, ge=1, le=8),
        limit: int = Query(40, ge=1, le=100),
    ) -> dict:
        try:
            return fabric.causal_chain(signal_id, depth=depth, limit=limit)
        except SignalFabricError as exc:
            _raise(exc)
            raise

    @router.post("/api/agents/signals")
    def publish_signal(body: SignalPublishBody) -> dict:
        try:
            signal = fabric.publish_http(body.model_dump(), operator=bool(body.operator))
        except SignalFabricError as exc:
            _raise(exc)
            raise
        return {"signal": signal.public_dict()}

    @router.post("/api/agents/signals/{signal_id}/ack")
    def ack_signal(signal_id: str, body: SignalAckBody) -> dict:
        try:
            return fabric.ack(signal_id, delivery_id=body.deliveryId, consumer=body.consumer)
        except SignalFabricError as exc:
            _raise(exc)
            raise

    @router.get("/api/agents/{agent_id}/signals")
    def agent_signals(
        agent_id: str,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        signals = fabric.store.list_signals(agent_id=agent_id, limit=limit)
        stats = fabric.agent_signal_stats(agent_id)
        return {
            "signals": [s.public_dict() for s in signals],
            "stats": stats,
            "enabled": fabric.config.enabled,
        }

    @router.get("/api/agents/missions/{mission_id}/signals")
    def mission_signals(
        mission_id: str,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        signals = fabric.store.list_signals(mission_id=mission_id, limit=limit)
        return {
            "signals": [s.public_dict() for s in signals],
            "enabled": fabric.config.enabled,
        }

    return router
