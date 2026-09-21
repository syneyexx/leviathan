"""Thin facade over existing model_router. Domains specify requirements only."""

from __future__ import annotations

from typing import Any

from reasoning.model_router import ModelCapabilities, ModelSelection


def requirements_from_domain(domain: str, *, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    extras = extras or {}
    base = {
        "chat": {"supports_tools": False, "complexity": "low"},
        "coding": {"supports_tools": True, "supports_structured_output": True, "complexity": "high"},
        "trading": {"supports_structured_output": True, "complexity": "medium"},
        "media": {"supports_tools": False, "complexity": "medium"},
        "research": {"supports_tools": True, "complexity": "medium"},
        "work": {"supports_tools": True, "complexity": "medium"},
    }.get(domain, {"complexity": "medium"})
    base.update(extras)
    return base


def should_escalate(*, complexity: str, failure_evidence: bool, tool_required: bool, verification_gap: bool) -> bool:
    if failure_evidence or verification_gap:
        return True
    if complexity == "high" and tool_required:
        return True
    return False


def selection_reason(selection: ModelSelection | dict[str, Any]) -> dict[str, Any]:
    if isinstance(selection, ModelSelection):
        payload = selection.to_dict()
    else:
        payload = dict(selection)
    return {
        "model_id": payload.get("model_id"),
        "reason": payload.get("reason"),
        "fallback_reason": payload.get("fallback_reason"),
        "source": "reasoning.model_router",
        "model_called_for_routing": False,
    }


def capabilities_snapshot(items: list[ModelCapabilities] | None = None) -> list[dict[str, Any]]:
    return [item.to_dict() for item in (items or [])]


def coding_specialist_requirements(specialist: str) -> dict[str, Any]:
    """Structured coding-role requirements for optional OmniRoute selection.

    Does not enumerate provider inventories. Routing stays outside the prompt.
    """
    from coding_omniroute import requirements_for_specialist

    return requirements_for_specialist(specialist)
