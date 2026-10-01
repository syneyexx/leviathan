"""Canonical Chat SSE / response contract helpers."""

from __future__ import annotations

from typing import Any


STREAM_EVENT_TYPES = frozenset(
    {
        "meta",
        "activity",
        "token",
        "snapshot",
        "cancelled",
        "error",
        "done",
        # Operational capability/job status (never private CoT)
        "tool.started",
        "tool.progress",
        "tool.completed",
        "tool.failed",
        "module.starting",
        "module.ready",
        "artifact.created",
        "source.observed",
        "knowledge.assimilation_queued",
        "knowledge.assimilated",
        "job.started",
        "job.progress",
        "job.completed",
        "capability.discovered",
    }
)


def build_stream_meta(
    *,
    conversation_id: str,
    turn_id: str | None,
    chat_run_id: str | None,
    cognition_run_id: str | None = None,
    team_run_id: str | None = None,
    user_message: dict | None = None,
    requested_model: str | None = None,
    effective_model: str | None = None,
    requested_reasoning_mode: str | None = None,
    effective_reasoning_mode: str | None = None,
    collaboration_strategy: str | None = None,
    response_owner: str | None = None,
    streaming: dict | None = None,
    reasoning: dict | None = None,
    activity: dict | None = None,
    truth: dict | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Early meta frame — identity before tokens / done."""
    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "chat_run_id": chat_run_id,
        "run_id": chat_run_id,  # compatibility alias
        "cognition_run_id": cognition_run_id,
        "team_run_id": team_run_id,
        "user_message": user_message,
        "requested_model": requested_model,
        "effective_model": effective_model or (extra or {}).get("model"),
        "model": effective_model or (extra or {}).get("model"),
        "requested_reasoning_mode": requested_reasoning_mode,
        "effective_reasoning_mode": effective_reasoning_mode,
        "collaboration_strategy": collaboration_strategy,
        "response_owner": response_owner,
        "reasoning": reasoning,
        "activity": activity,
        "truth": truth or {},
    }
    if streaming:
        payload.update(streaming)
    if extra:
        for key, value in extra.items():
            if key not in payload or payload[key] is None:
                payload[key] = value
    return payload


def normalize_chat_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure one authoritative response shape across direct / cognition / TEAM."""
    out = dict(payload)
    # Promote legacy `message` → `assistant_message` when needed.
    if out.get("assistant_message") is None and out.get("message") is not None:
        out["assistant_message"] = out["message"]
    # Keep legacy alias for verified compatibility consumers.
    if out.get("assistant_message") is not None:
        out["message"] = out["assistant_message"]
    # Ensure required top-level keys exist.
    out.setdefault("conversation_id", "")
    out.setdefault("knowledge_sources", [])
    out.setdefault(
        "reasoning",
        {"intent": "", "complexity": "", "use_knowledge": False, "steps": []},
    )
    out.setdefault("truth", {})
    out.setdefault("provisional", False)
    # Mark legacy alias explicitly.
    out.setdefault(
        "_compatibility",
        {
            "message_alias": "deprecated — use assistant_message",
            "reason": "older clients and TEAM historical payloads",
        },
    )
    return out


def measurement_or_none(value: Any) -> int | float | None:
    """Return numeric measurement or None — never invent zero from absence."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
