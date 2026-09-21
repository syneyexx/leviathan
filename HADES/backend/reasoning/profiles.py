from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ReasoningProfileName, RequestSpec, TaskFeatures
from .mode_policy import (
    POLICY_VERSION,
    parse_mode_input,
    profile_config_key,
)
from .understanding import (
    apply_classifier_overlay,
    build_request_spec,
    choose_adaptive_profile,
    extract_task_features,
    needs_structured_classification,
    parse_classifier_output,
    score_complexity,
)


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: ReasoningProfileName
    require_plan: bool
    retrieval_limit: int | None
    max_tool_rounds: int | None
    max_replans: int | None
    max_model_calls: int | None
    verify: bool
    allow_specialists: bool
    context_chars: int | None
    temperature_bias: float
    min_max_tokens: int
    notes: str


PROFILE_CONFIGS: dict[str, ProfileConfig] = {
    "fast": ProfileConfig(
        name="fast",
        require_plan=False,
        retrieval_limit=4,
        max_tool_rounds=1,
        max_replans=0,
        max_model_calls=2,
        verify=False,
        allow_specialists=False,
        context_chars=24_000,
        temperature_bias=0.0,
        min_max_tokens=1024,
        notes="Normal: direct antwoord; geen planner/router/critic; tools alleen als de opdracht dat eist.",
    ),
    "standard": ProfileConfig(
        name="standard",
        require_plan=False,
        retrieval_limit=8,
        max_tool_rounds=3,
        max_replans=1,
        max_model_calls=6,
        verify=False,
        allow_specialists=False,
        context_chars=55_000,
        temperature_bias=0.0,
        min_max_tokens=2048,
        notes="Medium: extra structuur alleen bij afhankelijkheden; begrensd herstel.",
    ),
    "high": ProfileConfig(
        name="high",
        require_plan=True,
        retrieval_limit=12,
        max_tool_rounds=5,
        max_replans=2,
        max_model_calls=12,
        verify=True,
        allow_specialists=True,
        context_chars=80_000,
        temperature_bias=-0.05,
        min_max_tokens=4096,
        notes="High: ruimte voor analyse/implementatie/verificatie; geen verplichte keten voor eenvoudige vragen.",
    ),
    "maximum": ProfileConfig(
        name="maximum",
        require_plan=True,
        retrieval_limit=16,
        max_tool_rounds=8,
        max_replans=3,
        max_model_calls=20,
        verify=True,
        allow_specialists=True,
        context_chars=110_000,
        temperature_bias=-0.1,
        min_max_tokens=6144,
        notes="Interne Maximum-budget (agents/taken + legacy High). Geen productmodus.",
    ),
}


def resolve_profile_config(profile_name: str) -> ProfileConfig | None:
    """Return profile config overlaid with control-plane settings when available."""
    key = profile_config_key(profile_name)
    base = PROFILE_CONFIGS.get(key)
    if base is None:
        return None
    try:
        from control.service import get_control_service

        overlay = get_control_service().profile_config_overlay(key)
    except Exception:
        return base

    def _pick(field: str, fallback: Any) -> Any:
        return overlay[field] if field in overlay else fallback

    return ProfileConfig(
        name=base.name,
        require_plan=bool(_pick("require_plan", base.require_plan)),
        retrieval_limit=_pick("retrieval_limit", base.retrieval_limit),
        max_tool_rounds=_pick("max_tool_rounds", base.max_tool_rounds),
        max_replans=_pick("max_replans", base.max_replans),
        max_model_calls=_pick("max_model_calls", base.max_model_calls),
        verify=bool(_pick("verify", base.verify)),
        allow_specialists=bool(_pick("allow_specialists", base.allow_specialists)),
        context_chars=_pick("context_chars", base.context_chars),
        temperature_bias=base.temperature_bias,
        min_max_tokens=int(_pick("min_max_tokens", base.min_max_tokens) or base.min_max_tokens),
        notes=base.notes,
    )


def resolve_reasoning_profile(
    text: str,
    requested: str | None = None,
    *,
    prior_failures: int = 0,
    spec: RequestSpec | None = None,
    conversation_state: dict[str, Any] | None = None,
    classifier_output: str | None = None,
) -> tuple[ReasoningProfileName, RequestSpec, dict[str, Any]]:
    request = spec or build_request_spec(
        text,
        prior_failures=prior_failures,
        conversation_state=conversation_state,
    )
    mode = parse_mode_input(requested, source="stored", allow_unknown=True)
    features: TaskFeatures = extract_task_features(request)
    classification_used = False
    classification_fallback = False
    if classifier_output:
        parsed = parse_classifier_output(classifier_output)
        if parsed:
            features = apply_classifier_overlay(features, parsed)
            classification_used = True
        else:
            classification_fallback = True

    if mode.explicit:
        chosen: ReasoningProfileName = mode.effective_policy  # type: ignore[assignment]
        resolve_mode = "explicit"
        decision_reason = mode.decision_reason
    else:
        chosen = choose_adaptive_profile(request, features)
        resolve_mode = "adaptive"
        decision_reason = f"adaptive_chose_{chosen};{features.speech_act}/{request.kind}"

    config = resolve_profile_config(chosen) or PROFILE_CONFIGS.get(chosen) or PROFILE_CONFIGS["standard"]
    heuristic = score_complexity(request)
    meta = {
        "mode": resolve_mode,
        "requested": mode.requested_raw or (requested or "adaptive").lower(),
        "chosen": chosen,
        "selected_mode": mode.selected_mode,
        "effective_policy": chosen,
        "decision_reason": decision_reason,
        "policy_version": POLICY_VERSION,
        "compatibility": mode.compatibility,
        "explicit": mode.explicit,
        "classification_used": classification_used,
        "classification_fallback": classification_fallback,
        "needs_classifier": needs_structured_classification(
            request, features, selected_mode=mode.selected_mode
        ),
        "task_features": features.to_dict(),
        "complexity": heuristic,
        "complexity_kind": "uncalibrated_hint",
        "config": {
            "require_plan": config.require_plan,
            "retrieval_limit": config.retrieval_limit,
            "max_tool_rounds": config.max_tool_rounds,
            "max_replans": config.max_replans,
            "max_model_calls": config.max_model_calls,
            "verify": config.verify,
            "allow_specialists": config.allow_specialists,
            "context_chars": config.context_chars,
            "min_max_tokens": config.min_max_tokens,
            "notes": config.notes,
        },
        "request": request.to_dict(),
    }
    return chosen, request, meta
