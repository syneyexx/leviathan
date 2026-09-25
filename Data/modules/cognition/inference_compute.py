"""InferenceComputeController — inside CognitiveRuntime architecture (not a new runtime).

Flow:
  CognitiveRuntime → MODEL_CALL/RESPOND
       → InferenceComputeController
            → resolve capability + NeuralComputeBudget
            → native path (provider hints) OR TTC path (no unknown knobs)
       → normalized candidates/results (F3: single primary; F4 expands TTC)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from Data.modules.models.native_reasoning import (
    NativeReasoningHints,
    build_native_reasoning_hints,
    parse_reasoning_usage,
    strip_private_reasoning_fields,
)

from .neural_compute import (
    NativeEffort,
    NeuralComputeBudget,
    ReasoningCapabilityProfile,
    apply_capability_to_budget,
    neural_budget_for_mode,
    resolve_reasoning_capability_profile,
)
from .types import ReasoningMode


@dataclass(frozen=True)
class InferenceComputePlan:
    """Public plan for one model call — no private CoT."""

    path: str  # native | ttc
    provider_family: str
    neural_budget: NeuralComputeBudget
    capability_profile: ReasoningCapabilityProfile
    hints: NativeReasoningHints
    # F3: always 1 primary call; F4 uses candidate_count for TTC fan-out.
    primary_candidate_count: int = 1
    ttc_candidate_budget: int = 1
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "provider_family": self.provider_family,
            "neural_budget": self.neural_budget.public_dict(),
            "capability_profile": self.capability_profile.public_dict(),
            "hints": self.hints.public_dict(),
            "primary_candidate_count": self.primary_candidate_count,
            "ttc_candidate_budget": self.ttc_candidate_budget,
            "notes": list(self.notes),
            "truth": {
                "not_a_second_runtime": True,
                "generic_uses_ttc_not_unknown_knobs": self.path == "ttc",
                "native_path_only_when_capability_affirmed": self.path == "native",
                "private_cot_not_in_plan": True,
            },
        }

    @property
    def provider_hints(self) -> dict[str, Any]:
        return dict(self.hints.provider_hints)


@dataclass
class InferenceComputeResult:
    """Normalized public result after a model call."""

    text: str
    path: str
    native_effort_requested: str | None
    native_effort_effective: str | None
    reasoning_tokens: int | None
    reasoning_tokens_status: str  # provider | UNMEASURED
    usage: dict[str, Any] = field(default_factory=dict)
    usage_source: str = "unavailable"
    finish_reason: str | None = None
    provider_hints_sent: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "native_effort_requested": self.native_effort_requested,
            "native_effort_effective": self.native_effort_effective,
            "reasoning_tokens": self.reasoning_tokens,
            "reasoning_tokens_status": self.reasoning_tokens_status,
            "usage_source": self.usage_source,
            "finish_reason": self.finish_reason,
            "provider_hints_sent": list(self.provider_hints_sent),
            "notes": list(self.notes),
            "text_preview": (self.text or "")[:200],
            "truth": {
                "unmeasured_when_provider_omits_reasoning_tokens": (
                    self.reasoning_tokens_status == "UNMEASURED"
                ),
                "private_cot_not_returned": True,
                "text_is_public_answer_channel_only": True,
            },
        }


class InferenceComputeController:
    """Decide native vs TTC and normalize provider results (no CoT leakage)."""

    def prepare(
        self,
        *,
        mode: ReasoningMode | str | None = None,
        neural_budget: NeuralComputeBudget | None = None,
        capability_profile: ReasoningCapabilityProfile | None = None,
        provider_family: str | None = None,
        provider_adapter: Any | None = None,
        model_metadata: Mapping[str, Any] | None = None,
        settings_capability_override: Mapping[str, Any] | None = None,
        policy_neural_budgets: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> InferenceComputePlan:
        profile = capability_profile or resolve_reasoning_capability_profile(
            provider_adapter=provider_adapter,
            model_metadata=model_metadata,
            settings_override=settings_capability_override,
            provider_family=provider_family,
        )
        family = provider_family or profile.provider_family or "generic"
        if neural_budget is None:
            neural_budget = neural_budget_for_mode(
                mode or ReasoningMode.STANDARD,
                policy_budgets=policy_neural_budgets,
            )
        neural_budget = apply_capability_to_budget(neural_budget, profile)
        hints = build_native_reasoning_hints(
            provider_family=str(family),
            supports_native_reasoning=bool(profile.supports_native_reasoning),
            supported_efforts=tuple(profile.supported_efforts),
            supports_reasoning_token_budget=bool(profile.supports_reasoning_token_budget),
            native_effort=neural_budget.native_effort.value,
            max_reasoning_tokens=neural_budget.max_reasoning_tokens,
        )
        notes: list[str] = list(hints.notes)
        if hints.path == "ttc":
            notes.append(
                f"ttc_candidate_budget={neural_budget.candidate_count} "
                "(F3 prepares; F4 executes multi-candidate TTC)"
            )
        return InferenceComputePlan(
            path=hints.path,
            provider_family=hints.provider_family,
            neural_budget=neural_budget,
            capability_profile=profile,
            hints=hints,
            primary_candidate_count=1,
            ttc_candidate_budget=max(1, int(neural_budget.candidate_count)),
            notes=tuple(notes),
        )

    def normalize_result(
        self,
        *,
        plan: InferenceComputePlan,
        raw_result: Mapping[str, Any] | None,
        public_text: str | None = None,
    ) -> InferenceComputeResult:
        raw = dict(raw_result or {})
        # Prefer explicit public text; never fall back to reasoning channels.
        text = public_text
        if text is None:
            text = str(raw.get("text") or raw.get("content") or "")
        # If provider stuffed a message object, strip private fields.
        message = raw.get("message")
        if isinstance(message, Mapping):
            cleaned = strip_private_reasoning_fields(message)
            if public_text is None and isinstance(cleaned.get("content"), str):
                text = cleaned["content"]

        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        reasoning_tokens, r_source = parse_reasoning_usage(usage)
        if reasoning_tokens is None:
            # Sometimes nested on raw root
            reasoning_tokens, r_source = parse_reasoning_usage(raw)
        status = "provider" if r_source == "provider" and reasoning_tokens is not None else "UNMEASURED"

        requested = plan.neural_budget.native_effort.value
        effective = plan.hints.effective_effort
        if plan.path == "ttc":
            effective = NativeEffort.UNSUPPORTED.value

        # Scrub any accidental CoT keys from usage copy for public telemetry.
        public_usage = {
            k: v
            for k, v in usage.items()
            if k
            not in {
                "reasoning",
                "reasoning_content",
                "thinking",
            }
        }
        if reasoning_tokens is not None:
            public_usage["reasoning_tokens"] = reasoning_tokens

        return InferenceComputeResult(
            text=str(text or "").strip(),
            path=plan.path,
            native_effort_requested=requested,
            native_effort_effective=effective,
            reasoning_tokens=reasoning_tokens,
            reasoning_tokens_status=status,
            usage=public_usage,
            usage_source=str(raw.get("usage_source") or "unavailable"),
            finish_reason=str(raw.get("finish_reason")) if raw.get("finish_reason") else None,
            provider_hints_sent=tuple(sorted(plan.provider_hints.keys())),
            notes=plan.notes,
        )
