"""Provider adapter contract for OmniRoute Editor Gateway."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderCapability:
    id: str
    available: bool = True
    inputs: list[str] = field(default_factory=list)
    reference_images: bool = False
    max_references: int = 0
    dimensions: dict[str, Any] = field(default_factory=dict)
    aspect_ratios: list[str] = field(default_factory=list)
    timeout_hint_ms: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "available": self.available,
            "inputs": list(self.inputs),
            "referenceImages": self.reference_images,
            "maxReferences": self.max_references,
            "dimensions": dict(self.dimensions),
            "aspectRatios": list(self.aspect_ratios),
            "timeoutHintMs": self.timeout_hint_ms,
            "notes": self.notes,
        }


@dataclass
class ProviderMeta:
    id: str
    label: str
    kind: str  # mock | openai-compatible | openai-images | adapter
    enabled: bool
    is_mock: bool = False
    models: list[str] = field(default_factory=list)
    capabilities: list[ProviderCapability] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "enabled": self.enabled,
            "isMock": self.is_mock,
            "models": list(self.models),
            "capabilities": [c.to_dict() for c in self.capabilities],
            "reason": self.reason,
        }


@dataclass
class ProviderRequest:
    request_id: str
    task: str
    capability: str
    instruction: str
    context: dict[str, Any]
    width: int | None = None
    height: int | None = None
    variants: int = 1
    timeout_seconds: float = 60.0
    cancel_event: Any = None


@dataclass
class ProviderResult:
    ok: bool
    kind: str  # asset_preview | asset_variants | text_preview | action_preview | analysis | unsupported | error
    variants: list[dict[str, Any]] = field(default_factory=list)
    text: str | None = None
    actions: list[dict[str, Any]] | None = None
    analysis: dict[str, Any] | None = None
    model: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    requested_size: dict[str, int] | None = None
    generated_size: dict[str, int] | None = None
    degraded_context: bool = False
    degrade_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        if self.kind == "asset_variants" or (self.kind == "asset_preview" and len(self.variants) > 1):
            return {
                "kind": "asset_variants",
                "variants": self.variants,
                "requestedSize": self.requested_size,
                "generatedSize": self.generated_size,
            }
        if self.kind in {"asset_preview", "asset_variants"}:
            return {
                "kind": "asset_preview",
                "variants": self.variants,
                "variant": self.variants[0] if self.variants else None,
                "requestedSize": self.requested_size,
                "generatedSize": self.generated_size,
            }
        if self.kind == "text_preview":
            return {"kind": "text_preview", "text": self.text or ""}
        if self.kind == "action_preview":
            return {"kind": "action_preview", "actions": self.actions or []}
        if self.kind == "analysis":
            return {"kind": "analysis", "analysis": self.analysis or {}}
        if self.kind == "unsupported":
            return {"kind": "unsupported", "message": self.error_message or "unsupported"}
        return {
            "kind": "error",
            "code": self.error_code,
            "message": self.error_message,
        }


class Provider(ABC):
    id: str
    label: str
    kind: str
    is_mock: bool = False

    @abstractmethod
    def meta(self) -> ProviderMeta:
        raise NotImplementedError

    @abstractmethod
    def supports(self, capability: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: ProviderRequest) -> ProviderResult:
        raise NotImplementedError
