"""ModelRouter — selection precedence and fallback tracing."""

from __future__ import annotations

import uuid
from typing import Callable

from Data.modules.models.capability_eligibility import (
    capability_satisfies_request,
    enrich_descriptor_capabilities,
)
from Data.modules.models.capability_vocabulary import capability_attr
from Data.modules.models.contracts import (
    ModelDescriptor,
    ModelRequest,
    RouteDecision,
    RouterConfig,
)
from Data.modules.models.effective_capability import (
    enrich_with_effective_capabilities,
    load_verified_map,
)
from Data.modules.models.errors import (
    AMBIGUOUS_MODEL_ID,
    MODEL_NOT_CHAT_CAPABLE,
    MODEL_NOT_FOUND,
    NO_CHAT_MODEL_AVAILABLE,
    NO_MODEL_ASSIGNED,
    ROUTER_EXHAUSTED,
    ModelControlError,
)
from Data.modules.models.gateway import ModelGateway
from Data.modules.models.locality import is_local_execution_eligible
from Data.modules.models.store import ModelStore


class ModelRouter:
    """Resolves which model should serve a request.

    Precedence (production inference — fail closed after this list):
      1. Explicit request-specific model
      2. Agent/task model requirement
      3. Role override
      4. Active/default model
      5. Configured local fallback chain
      6. Optional cloud fallback if explicitly allowed (deterministic; not registry order)
      otherwise FAIL CLOSED — never first_eligible / registry[0] / provider[0]
    """

    def __init__(
        self,
        store: ModelStore,
        gateway: ModelGateway,
        *,
        get_models: Callable[[], list[ModelDescriptor]],
        list_verified: Callable[[str], list] | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self._get_models = get_models
        self._list_verified = list_verified

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

        # Detect duplicate fallback IDs
        seen: set[str] = set()
        duplicates: list[str] = []
        for mid in fallback:
            if mid in seen:
                duplicates.append(mid)
            seen.add(mid)
        if duplicates:
            raise ModelControlError(
                code="VALIDATION_ERROR",
                message=f"fallbackOrder contains duplicate model ids: {duplicates}",
                http_status=422,
                details={"duplicates": duplicates},
            )

        known_ids = {m.id for m in self._get_models()}
        missing_fallback = [mid for mid in fallback if mid not in known_ids]
        missing_roles = {
            role: mid for role, mid in roles.items() if mid not in known_ids
        }
        # Ambiguous aliases in config targets
        ambiguous: list[dict] = []
        for mid in list(fallback) + list(roles.values()):
            if mid in known_ids:
                continue
            matches = [
                m
                for m in self._get_models()
                if m.display_name == mid
                or (m.metadata or {}).get("provider_model_id") == mid
            ]
            if len(matches) > 1:
                ambiguous.append(
                    {
                        "alias": mid,
                        "candidateCanonicalIds": [m.id for m in matches],
                    }
                )
        if ambiguous:
            raise ModelControlError(
                code=AMBIGUOUS_MODEL_ID,
                message="Router config contains ambiguous model aliases",
                http_status=409,
                details={"ambiguous": ambiguous},
            )
        if missing_fallback or missing_roles:
            # Do not silently clean — reject so operator knows targets don't exist.
            # Offline-but-known IDs are allowed (configured-but-unavailable).
            raise ModelControlError(
                code="VALIDATION_ERROR",
                message="Router config references unknown model ids",
                http_status=422,
                details={
                    "missingFallbackOrder": missing_fallback,
                    "missingRoleOverrides": missing_roles,
                    "truth": {
                        "no_silent_cleanup": True,
                        "offline_configured_targets_must_exist_in_registry": True,
                    },
                },
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

    def _enrich(self, model: ModelDescriptor) -> ModelDescriptor:
        enriched = enrich_descriptor_capabilities(model)
        if self._list_verified is not None:
            verified_map = load_verified_map(enriched.id, self._list_verified)
            enriched = enrich_with_effective_capabilities(
                enriched, verified_by_cap=verified_map
            )
        return enriched

    def _resolve_alias(
        self, model_id: str, models: dict[str, ModelDescriptor]
    ) -> ModelDescriptor | None:
        if model_id in models:
            return models[model_id]
        matches = [
            candidate
            for candidate in models.values()
            if candidate.display_name == model_id
            or candidate.metadata.get("provider_model_id") == model_id
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ModelControlError(
                code=AMBIGUOUS_MODEL_ID,
                message=(
                    f"Ambiguous model alias '{model_id}' matches "
                    f"{len(matches)} canonical ids; specify a canonical model id"
                ),
                model_id=model_id,
                http_status=409,
                details={
                    "alias": model_id,
                    "candidateCanonicalIds": [m.id for m in matches],
                },
            )
        return None

    def resolve(self, request: ModelRequest | None = None) -> RouteDecision:
        request = request or ModelRequest()
        models = {m.id: self._enrich(m) for m in self._get_models()}
        config = self.get_config()
        trace_id = str(uuid.uuid4())
        tried: list[str] = []
        requires_chat = any(
            capability_attr(c) == "chat" for c in (request.required_capabilities or ())
        )
        active_id = self.store.get_active_model_id()
        # Active preference that is offline is preference-only, not live-eligible.
        active_model = models.get(active_id) if active_id else None
        active_live = bool(
            active_model
            and active_model.lifecycle_state.value not in {"error", "offline"}
        )

        def eligible(model: ModelDescriptor, *, explicit: bool = False) -> bool:
            if model.lifecycle_state.value in {"error", "offline"}:
                return False
            ctx = {
                "explicit_selection": explicit,
                "runtime_supports_chat": True,
                "preferred_role": request.preferred_role,
                "requirement_mode": "hard",
            }
            for cap in request.required_capabilities:
                decision = capability_satisfies_request(model, cap, request_context=ctx)
                if not decision.satisfies:
                    return False
            if request.locality == "local_only" and not is_local_execution_eligible(model):
                return False
            # Context-fit: unknown capacity with hard minimum → fail closed.
            min_window = request.minimum_context_window
            if min_window is None and request.required_input_tokens is not None:
                out_need = int(request.required_output_tokens or 0)
                min_window = int(request.required_input_tokens) + out_need
            if min_window is not None:
                if model.context_window is None:
                    # Conservative: unknown context capacity cannot satisfy hard minimum.
                    return False
                try:
                    if int(model.context_window) < int(min_window):
                        return False
                except (TypeError, ValueError):
                    return False
            return True

        def try_model(model_id: str, reason: str, *, explicit: bool = False) -> RouteDecision | None:
            if not model_id:
                return None
            tried.append(model_id)
            model = self._resolve_alias(model_id, models)
            if model is None:
                return None
            if not eligible(model, explicit=explicit):
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
            decision = try_model(request.explicit_model_id, "explicit", explicit=True)
            if decision:
                return decision
            model = None
            try:
                model = self._resolve_alias(request.explicit_model_id, models)
            except ModelControlError:
                raise
            if model is not None and requires_chat:
                chat_decision = capability_satisfies_request(
                    model,
                    "chat",
                    request_context={"explicit_selection": True, "runtime_supports_chat": True},
                )
                if not chat_decision.satisfies:
                    raise ModelControlError(
                        code=MODEL_NOT_CHAT_CAPABLE,
                        message=(
                            f"Model {model.id} is not eligible for conversational chat generation"
                        ),
                        model_id=model.id,
                        provider_id=model.provider_id,
                        http_status=422,
                        details={
                            "modelId": model.id,
                            "chatCapability": chat_decision.state.value,
                            "provider": model.provider_id,
                            "reason": chat_decision.reason,
                            "provenance": chat_decision.provenance.value,
                            "capabilities": model.capabilities.public_dict(),
                        },
                    )
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

        # 4. Active default — only if currently live/servable
        if active_id and active_live:
            decision = try_model(active_id, "active_default")
            if decision:
                return decision

        # 5. Fallback chain
        for model_id in config.fallback_order:
            decision = try_model(model_id, "fallback:configured")
            if decision:
                self.gateway.record_fallback("primary unavailable; configured fallback")
                return decision

        # 6. Optional cloud
        if config.cloud_fallback_allowed:
            cloud_candidates = [
                model
                for model in models.values()
                if model.source.value == "api" and eligible(model)
            ]
            if len(cloud_candidates) == 1:
                decision = try_model(cloud_candidates[0].id, "fallback:cloud")
                if decision:
                    self.gateway.record_fallback("local exhausted; cloud fallback allowed")
                    return decision
            elif len(cloud_candidates) > 1:
                raise ModelControlError(
                    code=NO_MODEL_ASSIGNED if not tried else ROUTER_EXHAUSTED,
                    message=(
                        "Multiple cloud models are eligible but none is uniquely configured; "
                        "set fallbackOrder or a role override — registry order is not selection policy"
                    ),
                    retryable=False,
                    http_status=503,
                    details=_exhaustion_details(
                        request=request,
                        tried=tried,
                        active_id=active_id,
                        config=config,
                        requires_chat=requires_chat,
                        reason="CLOUD_FALLBACK_AMBIGUOUS",
                        extra={
                            "cloudCandidateIds": sorted(m.id for m in cloud_candidates),
                            "cloudCandidateCount": len(cloud_candidates),
                        },
                    ),
                )

        code = NO_CHAT_MODEL_AVAILABLE if requires_chat else (
            NO_MODEL_ASSIGNED if not tried else ROUTER_EXHAUSTED
        )
        raise ModelControlError(
            code=code,
            message=(
                "No chat-capable generative model is assigned"
                if requires_chat
                else "No model is assigned for this request (no explicit/agent/role/active/fallback authority)"
            ),
            retryable=True,
            http_status=503,
            details=_exhaustion_details(
                request=request,
                tried=tried,
                active_id=active_id,
                config=config,
                requires_chat=requires_chat,
                reason="NO_MODEL_ASSIGNED",
                extra={
                    "traceId": trace_id,
                    "activeModelConfigured": active_id,
                    "activeModelLive": active_live,
                },
            ),
        )

    def find_compatible(self, *, required_capabilities: list[str], locality: str = "any") -> list[str]:
        models = [self._enrich(m) for m in self._get_models()]
        out: list[str] = []
        for model in models:
            if locality == "local_only" and not is_local_execution_eligible(model):
                continue
            if model.lifecycle_state.value in {"error", "offline"}:
                continue
            ok = True
            for cap in required_capabilities:
                decision = capability_satisfies_request(
                    model,
                    cap,
                    request_context={"explicit_selection": False, "runtime_supports_chat": True},
                )
                if not decision.satisfies:
                    ok = False
                    break
            if ok:
                out.append(model.id)
        return out


def _exhaustion_details(
    *,
    request: ModelRequest,
    tried: list[str],
    active_id: str | None,
    config: RouterConfig,
    requires_chat: bool,
    reason: str,
    extra: dict | None = None,
) -> dict:
    details = {
        "reason": reason,
        "tried": list(tried),
        "candidatesTried": list(tried),
        "requiredCapabilities": list(request.required_capabilities),
        "preferredRole": request.preferred_role,
        "activeModelId": active_id,
        "configuredFallbackOrder": list(config.fallback_order),
        "cloudFallbackAllowed": bool(config.cloud_fallback_allowed),
        "requiresChat": requires_chat,
        "explicitModelId": request.explicit_model_id,
        "agentModelId": request.agent_model_id,
        "truth": {
            "discovery_is_not_execution_authority": True,
            "registry_order_is_not_selection_policy": True,
            "first_eligible_removed": True,
            "preference_is_not_live_active": True,
        },
    }
    if extra:
        details.update(extra)
    return details
