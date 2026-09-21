"""Model router — selection precedence and fallback tracing."""

from __future__ import annotations

import uuid
from typing import Callable

from Data.modules.models.contracts import (
    CapabilityState,
    ModelDescriptor,
    ModelRequest,
    RouteDecision,
    RouterConfig,
)
from Data.modules.models.errors import MODEL_NOT_FOUND, ROUTER_EXHAUSTED, ModelControlError
from Data.modules.models.gateway import ModelGateway
from Data.modules.models.store import ModelStore


class ModelRouter:
    """Resolves which model should serve a request.

    Precedence:
      1. Explicit request-specific model
      2. Agent/task model requirement
      3. Role override
      4. Active/default model
      5. Configured local fallback chain
      6. Optional cloud fallback if explicitly allowed
    """

    def __init__(
        self,
        store: ModelStore,
        gateway: ModelGateway,
        *,
        get_models: Callable[[], list[ModelDescriptor]],
    ) -> None:
        self.store = store
        self.gateway = gateway
        self._get_models = get_models

    def get_config(self) -> RouterConfig:
        raw = self.store.get_router_config()
        return RouterConfig(
            fallback_order=list(raw.get("fallback_order") or []),
            role_overrides=dict(raw.get("role_overrides") or {}),
            cloud_fallback_allowed=bool(raw.get("cloud_fallback_allowed", False)),
            streaming=bool(raw.get("streaming", True)),
            stream_provisional_text=bool(raw.get("stream_provisional_text", True)),
            progress_events_enabled=bool(raw.get("progress_events_enabled", True)),
        )

    def save_config(self, payload: dict) -> RouterConfig:
        current = self.get_config()
        fallback = payload.get("fallbackOrder", payload.get("fallback_order", current.fallback_order))
        roles = payload.get("roleModelOverrides", payload.get("role_overrides", current.role_overrides))
        if not isinstance(fallback, list) or not all(isinstance(x, str) for x in fallback):
            raise ModelControlError(
                code="VALIDATION_ERROR",
                message="fallbackOrder must be a list of model ids",
                http_status=422,
            )
        if not isinstance(roles, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in roles.items()
        ):
            raise ModelControlError(
                code="VALIDATION_ERROR",
                message="roleModelOverrides must be a string-to-string map",
                http_status=422,
            )
        config = {
            "fallback_order": list(fallback),
            "role_overrides": dict(roles),
            "cloud_fallback_allowed": bool(
                payload.get("cloudFallbackAllowed", payload.get("cloud_fallback_allowed", current.cloud_fallback_allowed))
            ),
            "streaming": bool(payload.get("streaming", current.streaming)),
            "stream_provisional_text": bool(
                payload.get("streamProvisionalText", payload.get("stream_provisional_text", current.stream_provisional_text))
            ),
            "progress_events_enabled": bool(
                payload.get(
                    "progressEventsEnabled",
                    payload.get("progress_events_enabled", current.progress_events_enabled),
                )
            ),
        }
        self.store.save_router_config(config)
        self.store.append_audit("routing_changed", detail={"config": config})
        return self.get_config()

    def resolve(self, request: ModelRequest | None = None) -> RouteDecision:
        request = request or ModelRequest()
        models = {m.id: m for m in self._get_models()}
        config = self.get_config()
        trace_id = str(uuid.uuid4())
        tried: list[str] = []

        def eligible(model: ModelDescriptor) -> bool:
            if model.lifecycle_state.value in {"error", "offline"}:
                return False
            for cap in request.required_capabilities:
                state = getattr(model.capabilities, _cap_attr(cap), CapabilityState.UNKNOWN)
                if state == CapabilityState.UNSUPPORTED:
                    return False
            if request.locality == "local_only" and model.source.value not in {"local", "imported", "downloaded"}:
                return False
            if request.locality == "local_preferred":
                pass
            return True

        def try_model(model_id: str, reason: str) -> RouteDecision | None:
            if not model_id:
                return None
            tried.append(model_id)
            model = models.get(model_id)
            if model is None:
                # Also allow matching by display name / provider model id for convenience
                for candidate in models.values():
                    if candidate.display_name == model_id or candidate.metadata.get("provider_model_id") == model_id:
                        model = candidate
                        model_id = candidate.id
                        break
            if model is None:
                return None
            if not eligible(model):
                return None
            decision = RouteDecision(
                model_id=model.id,
                reason=reason,
                fallback_used=reason.startswith("fallback"),
                fallback_reason=None if not reason.startswith("fallback") else reason,
                candidates_tried=list(tried),
                trace_id=trace_id,
            )
            self.gateway.record_selection(model.id, trace_id=trace_id)
            return decision

        # 1. Explicit
        if request.explicit_model_id:
            decision = try_model(request.explicit_model_id, "explicit")
            if decision:
                return decision
            raise ModelControlError(
                code=MODEL_NOT_FOUND,
                message=f"Explicit model not found or ineligible: {request.explicit_model_id}",
                model_id=request.explicit_model_id,
                http_status=404,
            )

        # 2. Agent
        if request.agent_model_id:
            decision = try_model(request.agent_model_id, "agent_requirement")
            if decision:
                return decision

        # 3. Role override
        if request.preferred_role:
            override = config.role_overrides.get(request.preferred_role)
            if override:
                decision = try_model(override, f"role:{request.preferred_role}")
                if decision:
                    return decision

        # 4. Active default
        active_id = self.store.get_active_model_id()
        if active_id:
            decision = try_model(active_id, "active_default")
            if decision:
                return decision

        # 5. Fallback chain
        for model_id in config.fallback_order:
            decision = try_model(model_id, "fallback:configured")
            if decision:
                self.gateway.record_fallback("primary unavailable; configured fallback")
                return decision

        # 6. Optional cloud — only if allowed and we have an api-source model
        if config.cloud_fallback_allowed:
            for model in models.values():
                if model.source.value == "api" and eligible(model):
                    decision = try_model(model.id, "fallback:cloud")
                    if decision:
                        self.gateway.record_fallback("local exhausted; cloud fallback allowed")
                        return decision

        # Last resort: first eligible available model
        for model in models.values():
            if eligible(model):
                decision = try_model(model.id, "fallback:first_eligible")
                if decision:
                    self.gateway.record_fallback("no active/default; first eligible")
                    return decision

        raise ModelControlError(
            code=ROUTER_EXHAUSTED,
            message="No eligible models available for request",
            retryable=True,
            http_status=503,
            details={"tried": tried, "requiredCapabilities": list(request.required_capabilities)},
        )

    def find_compatible(self, *, required_capabilities: list[str], locality: str = "any") -> list[str]:
        models = self._get_models()
        out: list[str] = []
        for model in models:
            req = ModelRequest(
                required_capabilities=tuple(required_capabilities),
                locality=locality if locality != "any" else "local_preferred",
            )
            # Reuse eligibility via temporary check
            ok = True
            if locality == "local_only" and model.source.value not in {"local", "imported", "downloaded"}:
                ok = False
            for cap in req.required_capabilities:
                state = getattr(model.capabilities, _cap_attr(cap), CapabilityState.UNKNOWN)
                if state == CapabilityState.UNSUPPORTED:
                    ok = False
            if ok and model.lifecycle_state.value not in {"error", "offline"}:
                out.append(model.id)
        return out


def _cap_attr(name: str) -> str:
    mapping = {
        "chat": "chat",
        "reasoning": "reasoning",
        "coding": "coding",
        "tool_calling": "tool_calling",
        "toolCalling": "tool_calling",
        "structured_output": "structured_output",
        "structuredOutput": "structured_output",
        "vision": "vision",
        "embeddings": "embeddings",
        "streaming": "streaming",
    }
    return mapping.get(name, name)
