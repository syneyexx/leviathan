"""Provider registry and capability discovery."""

from __future__ import annotations

import os
from typing import Any

from .base import Provider, ProviderRequest, ProviderResult
from .mock import MockProvider
from .openai_images import OpenAIImagesProvider
from .openai_text import OpenAICompatibleTextProvider


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: list[Provider] = []
        self.reload()

    def reload(self) -> None:
        providers: list[Provider] = []
        # Real providers first when enabled
        img = OpenAIImagesProvider()
        if img.enabled():
            providers.append(img)
        text = OpenAICompatibleTextProvider()
        if text.enabled():
            providers.append(text)
        # Mock only when explicitly enabled
        if _truthy("LEVIATHAN_EDITOR_AI_MOCK"):
            latency = int(os.environ.get("LEVIATHAN_EDITOR_AI_MOCK_LATENCY_MS", "40") or "40")
            fail = os.environ.get("LEVIATHAN_EDITOR_AI_MOCK_FAIL") or None
            providers.append(MockProvider(latency_ms=latency, fail_mode=fail))
        self._providers = providers

    def list_providers(self) -> list[dict[str, Any]]:
        # Always surface disabled adapters for honest UI
        out = [p.meta().to_dict() for p in self._providers]
        # Include disabled stubs so UI can explain
        known = {p["id"] for p in out}
        for stub in (OpenAIImagesProvider(), OpenAICompatibleTextProvider()):
            if stub.id not in known:
                out.append(stub.meta().to_dict())
        if not any(p.get("id") == "mock" for p in out):
            mock_meta = MockProvider().meta().to_dict()
            mock_meta["enabled"] = False
            mock_meta["reason"] = "mock-disabled"
            # Mark capabilities unavailable when mock off
            for cap in mock_meta.get("capabilities") or []:
                cap["available"] = False
            out.append(mock_meta)
        return out

    def capability_report(self) -> dict[str, Any]:
        capability_ids = [
            "image.generate",
            "image.edit",
            "image.outpaint",
            "image.background.remove",
            "image.variation",
            "vision.analyze",
            "text.generate",
            "text.rewrite",
            "layout.reason",
        ]
        caps: dict[str, Any] = {}
        any_available = False
        for cap_id in capability_ids:
            providers = []
            for p in self._providers:
                meta = p.meta()
                if not meta.enabled:
                    continue
                for c in meta.capabilities:
                    if c.id == cap_id and c.available and p.supports(cap_id):
                        providers.append(
                            {
                                "id": meta.id,
                                "label": meta.label,
                                "isMock": meta.is_mock,
                                "model": (meta.models[0] if meta.models else None),
                                "referenceImages": c.reference_images,
                            }
                        )
            available = bool(providers)
            any_available = any_available or available
            entry: dict[str, Any] = {"available": available, "providers": providers}
            if not available:
                entry["reason"] = "no-provider"
            caps[cap_id] = entry

        return {
            "available": any_available,
            "mockEnabled": _truthy("LEVIATHAN_EDITOR_AI_MOCK"),
            "aiEnabled": not _truthy("LEVIATHAN_EDITOR_AI_DISABLED"),
            "capabilities": caps,
            "providers": self.list_providers(),
            "omniroute": {
                "boundary": "editor-gateway",
                "note": (
                    "HADES OmniRoute plugin routes coding LLM completions. "
                    "Studio uses this editor gateway with capability-based provider adapters."
                ),
                "hadesCodingOmniroute": "separate-boundary",
            },
        }

    def resolve(self, capability: str) -> tuple[Provider | None, list[str]]:
        """Pick first enabled provider that supports capability. Prefer non-mock."""
        fallback_trail: list[str] = []
        mock_hit: Provider | None = None
        for p in self._providers:
            meta = p.meta()
            if not meta.enabled:
                continue
            if not p.supports(capability):
                continue
            if meta.is_mock:
                mock_hit = p
                continue
            return p, fallback_trail
        if mock_hit:
            fallback_trail.append("mock")
            return mock_hit, fallback_trail
        return None, fallback_trail

    def execute(self, request: ProviderRequest) -> tuple[ProviderResult, dict[str, Any]]:
        provider, trail = self.resolve(request.capability)
        routing = {
            "capability": request.capability,
            "fallbackTrail": trail,
            "providerId": provider.id if provider else None,
            "isMock": bool(provider and provider.is_mock),
        }
        if provider is None:
            return (
                ProviderResult(
                    ok=False,
                    kind="unsupported",
                    error_code="no-provider",
                    error_message=f"No provider available for {request.capability}",
                ),
                routing,
            )
        result = provider.execute(request)
        routing["model"] = result.model
        return result, routing
