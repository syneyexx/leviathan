"""Capability registry — what can actually be configured vs external ceilings."""

from __future__ import annotations

from typing import Any

from .types import CapabilityDescriptor, ConstraintKind


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityDescriptor] = {}

    def register(self, capability: CapabilityDescriptor) -> None:
        self._items[capability.id] = capability

    def update(self, capability_id: str, **kwargs: Any) -> CapabilityDescriptor:
        current = self._items.get(capability_id)
        if not current:
            current = CapabilityDescriptor(id=capability_id, kind=ConstraintKind.RUNTIME_CAPABILITY, label=capability_id)
        data = {
            "id": current.id,
            "kind": current.kind,
            "label": current.label,
            "supported": current.supported,
            "provider_max": current.provider_max,
            "runtime_max": current.runtime_max,
            "details": dict(current.details),
        }
        data.update(kwargs)
        if isinstance(data["kind"], str):
            data["kind"] = ConstraintKind(data["kind"])
        updated = CapabilityDescriptor(**data)
        self._items[capability_id] = updated
        return updated

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        return self._items.get(capability_id)

    def as_dict(self) -> dict[str, CapabilityDescriptor]:
        return dict(self._items)

    def public(self) -> list[dict[str, Any]]:
        return [item.to_public() for item in self._items.values()]

    def set_model_context_window(self, model_id: str, context_window: int | None) -> None:
        self.update(
            "models.context_window",
            kind=ConstraintKind.PROVIDER_LIMIT,
            label=f"Model context window ({model_id})",
            supported=context_window is not None,
            provider_max=context_window,
            details={"model_id": model_id},
        )

    def set_model_max_output_tokens(self, model_id: str, max_output: int | None) -> None:
        self.update(
            "models.max_output_tokens",
            kind=ConstraintKind.PROVIDER_LIMIT,
            label=f"Model max output tokens ({model_id})",
            supported=max_output is not None,
            provider_max=max_output,
            details={"model_id": model_id},
        )

    def set_runtime_vram_jobs(self, jobs: int | None) -> None:
        self.update(
            "resources.max_concurrent_inference",
            kind=ConstraintKind.RUNTIME_CAPABILITY,
            label="VRAM scheduler concurrent jobs",
            supported=True,
            runtime_max=jobs,
        )


def default_capabilities() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDescriptor(
            id="models.reasoning_effort",
            kind=ConstraintKind.PROVIDER_LIMIT,
            label="Reasoning effort parameter",
            supported=False,
            details={"note": "Only shown when the active model/provider advertises support."},
        )
    )
    registry.register(
        CapabilityDescriptor(
            id="models.seed",
            kind=ConstraintKind.PROVIDER_LIMIT,
            label="Deterministic seed",
            supported=True,
            details={"note": "LM Studio / local OpenAI-compatible adapters generally accept seed."},
        )
    )
    return registry
