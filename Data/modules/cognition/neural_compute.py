"""Two-axis neural inference compute — LEVIATHAN semantic objects.

NeuralComputeBudget is NOT a provider JSON payload.
ReasoningCapabilityProfile is resolved from adapter + metadata + probe +
Settings override — never guessed from the model name alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

from .types import ReasoningMode


class NativeEffort(str, Enum):
    """Provider-agnostic effort levels. Adapters map these to legal fields."""

    MINIMAL = "MINIMAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    MAXIMUM = "MAXIMUM"
    UNSUPPORTED = "UNSUPPORTED"
    UNMEASURED = "UNMEASURED"


class ClampReason(str, Enum):
    NONE = "NONE"
    GPU_RESOURCE_PRESSURE = "GPU_RESOURCE_PRESSURE"
    RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
    POLICY_CLAMP = "POLICY_CLAMP"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"


@dataclass(frozen=True)
class NeuralComputeBudget:
    """Inference-time / neural compute axis (distinct from orchestration budgets)."""

    native_effort: NativeEffort = NativeEffort.MEDIUM
    max_reasoning_tokens: int | None = None  # None = UNMEASURED / provider default

    candidate_count: int = 1
    max_parallel_candidates: int = 1

    branch_width: int = 1
    branch_depth: int = 1

    self_consistency_samples: int = 1

    reflection_passes: int = 0
    critic_calls: int = 0
    verifier_calls: int = 0
    repair_passes: int = 0

    diversity_temperature: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "native_effort": self.native_effort.value,
            "max_reasoning_tokens": self.max_reasoning_tokens,
            "candidate_count": self.candidate_count,
            "max_parallel_candidates": self.max_parallel_candidates,
            "branch_width": self.branch_width,
            "branch_depth": self.branch_depth,
            "self_consistency_samples": self.self_consistency_samples,
            "reflection_passes": self.reflection_passes,
            "critic_calls": self.critic_calls,
            "verifier_calls": self.verifier_calls,
            "repair_passes": self.repair_passes,
            "diversity_temperature": self.diversity_temperature,
            "truth": {
                "neural_budget_is_not_provider_payload": True,
                "orchestration_budget_is_separate_axis": True,
                "unmeasured_reasoning_tokens_when_none": self.max_reasoning_tokens is None,
            },
        }

    def clamped(self, *, max_candidates: int | None = None, max_parallel: int | None = None) -> "NeuralComputeBudget":
        kwargs: dict[str, Any] = {}
        if max_candidates is not None:
            kwargs["candidate_count"] = max(1, min(self.candidate_count, int(max_candidates)))
        if max_parallel is not None:
            kwargs["max_parallel_candidates"] = max(
                1, min(self.max_parallel_candidates, int(max_parallel))
            )
        return replace(self, **kwargs) if kwargs else self


def _default_neural_budgets() -> dict[str, NeuralComputeBudget]:
    """Mode → neural axis presets (program §8)."""
    return {
        ReasoningMode.FAST.value: NeuralComputeBudget(
            native_effort=NativeEffort.LOW,
            max_reasoning_tokens=1024,
            candidate_count=1,
            max_parallel_candidates=1,
            branch_width=1,
            branch_depth=1,
            self_consistency_samples=1,
            reflection_passes=0,
            critic_calls=0,
            verifier_calls=0,
            repair_passes=0,
            diversity_temperature=0.0,
        ),
        ReasoningMode.STANDARD.value: NeuralComputeBudget(
            native_effort=NativeEffort.MEDIUM,
            max_reasoning_tokens=4096,
            candidate_count=1,
            max_parallel_candidates=1,
            branch_width=1,
            branch_depth=1,
            self_consistency_samples=1,
            reflection_passes=0,
            critic_calls=0,
            verifier_calls=1,
            repair_passes=0,
            diversity_temperature=0.15,
        ),
        ReasoningMode.DEEP.value: NeuralComputeBudget(
            native_effort=NativeEffort.HIGH,
            max_reasoning_tokens=8192,
            candidate_count=3,
            max_parallel_candidates=2,
            branch_width=3,
            branch_depth=2,
            self_consistency_samples=3,
            reflection_passes=1,
            critic_calls=2,
            verifier_calls=2,
            repair_passes=1,
            diversity_temperature=0.35,
        ),
        ReasoningMode.MAXIMUM.value: NeuralComputeBudget(
            native_effort=NativeEffort.MAXIMUM,
            max_reasoning_tokens=16384,
            candidate_count=6,
            max_parallel_candidates=4,
            branch_width=4,
            branch_depth=3,
            self_consistency_samples=5,
            reflection_passes=2,
            critic_calls=3,
            verifier_calls=3,
            repair_passes=2,
            diversity_temperature=0.45,
        ),
    }


_NEURAL_INT_FIELDS = (
    "max_reasoning_tokens",
    "candidate_count",
    "max_parallel_candidates",
    "branch_width",
    "branch_depth",
    "self_consistency_samples",
    "reflection_passes",
    "critic_calls",
    "verifier_calls",
    "repair_passes",
)


def neural_budget_from_mapping(
    raw: Mapping[str, Any] | None,
    *,
    base: NeuralComputeBudget | None = None,
) -> NeuralComputeBudget:
    base = base or NeuralComputeBudget()
    if not isinstance(raw, dict) or not raw:
        return base
    kwargs: dict[str, Any] = {}
    if "native_effort" in raw:
        try:
            kwargs["native_effort"] = NativeEffort(str(raw["native_effort"]).strip().upper())
        except ValueError:
            pass
    for name in _NEURAL_INT_FIELDS:
        if name not in raw or raw[name] is None:
            continue
        try:
            kwargs[name] = int(raw[name])
        except (TypeError, ValueError):
            continue
    if "diversity_temperature" in raw and raw["diversity_temperature"] is not None:
        try:
            kwargs["diversity_temperature"] = float(raw["diversity_temperature"])
        except (TypeError, ValueError):
            pass
    return replace(base, **kwargs)


def neural_budget_for_mode(
    mode: ReasoningMode | str,
    *,
    policy_budgets: Mapping[str, Mapping[str, Any]] | None = None,
) -> NeuralComputeBudget:
    key = mode.value if isinstance(mode, ReasoningMode) else str(mode).strip().upper()
    if key == "ADAPTIVE":
        key = ReasoningMode.STANDARD.value
    defaults = _default_neural_budgets()
    base = defaults.get(key) or defaults[ReasoningMode.STANDARD.value]
    if policy_budgets and key in policy_budgets:
        return neural_budget_from_mapping(policy_budgets[key], base=base)
    return base


@dataclass(frozen=True)
class ReasoningCapabilityProfile:
    """What the active model/provider can actually do for native reasoning."""

    supports_native_reasoning: bool = False
    supported_efforts: tuple[str, ...] = ()
    supports_reasoning_token_budget: bool = False
    supports_reasoning_output_channel: bool = False
    supports_persistent_reasoning_state: bool = False
    supports_tool_interleaving: bool = False
    supports_parallel_tool_calls: bool = False
    supports_seed: bool = False
    supports_structured_output: bool = False
    supports_context_cache: bool = False
    provider_family: str = "generic"
    resolution_source: str = "unresolved"  # adapter|metadata|probe|settings_override|unresolved
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "supports_native_reasoning": self.supports_native_reasoning,
            "supported_efforts": list(self.supported_efforts),
            "supports_reasoning_token_budget": self.supports_reasoning_token_budget,
            "supports_reasoning_output_channel": self.supports_reasoning_output_channel,
            "supports_persistent_reasoning_state": self.supports_persistent_reasoning_state,
            "supports_tool_interleaving": self.supports_tool_interleaving,
            "supports_parallel_tool_calls": self.supports_parallel_tool_calls,
            "supports_seed": self.supports_seed,
            "supports_structured_output": self.supports_structured_output,
            "supports_context_cache": self.supports_context_cache,
            "provider_family": self.provider_family,
            "resolution_source": self.resolution_source,
            "notes": list(self.notes),
            "truth": {
                "never_guess_capability_from_model_name_alone": True,
                "unknown_is_not_supported": True,
                "generic_provider_uses_ttc_not_unknown_knobs": (
                    self.provider_family == "generic" or not self.supports_native_reasoning
                ),
            },
        }

    def map_effort(self, effort: NativeEffort) -> NativeEffort:
        """Map requested effort to a supported effort, or UNSUPPORTED."""
        if not self.supports_native_reasoning:
            return NativeEffort.UNSUPPORTED
        if effort in {NativeEffort.UNSUPPORTED, NativeEffort.UNMEASURED}:
            return effort
        supported = {e.upper() for e in self.supported_efforts}
        if not supported:
            # Native reasoning claimed but efforts unknown — do not invent.
            return NativeEffort.UNMEASURED
        if effort.value in supported:
            return effort
        # Downgrade to highest supported below requested.
        order = [
            NativeEffort.MINIMAL,
            NativeEffort.LOW,
            NativeEffort.MEDIUM,
            NativeEffort.HIGH,
            NativeEffort.MAXIMUM,
        ]
        idx = order.index(effort) if effort in order else 2
        for candidate in reversed(order[: idx + 1]):
            if candidate.value in supported:
                return candidate
        # Else any supported
        for candidate in order:
            if candidate.value in supported:
                return candidate
        return NativeEffort.UNSUPPORTED


def resolve_reasoning_capability_profile(
    *,
    provider_adapter: Any | None = None,
    model_metadata: Mapping[str, Any] | None = None,
    probe_result: Mapping[str, Any] | None = None,
    settings_override: Mapping[str, Any] | None = None,
    provider_family: str | None = None,
    model_id: str | None = None,
) -> ReasoningCapabilityProfile:
    """Resolve capability without guessing from model_id alone.

    ``model_id`` is accepted only for provenance notes — never as a capability
    oracle.
    """
    notes: list[str] = []
    if model_id:
        notes.append("model_id_recorded_for_provenance_only_not_capability_oracle")

    # Highest authority: explicit settings override.
    if isinstance(settings_override, Mapping) and settings_override.get("apply"):
        return _profile_from_mapping(
            settings_override,
            resolution_source="settings_override",
            provider_family=str(
                settings_override.get("provider_family")
                or provider_family
                or "generic"
            ),
            notes=tuple(notes + ["settings_override_applied"]),
        )

    # Adapter-declared capabilities.
    if provider_adapter is not None:
        profile = _profile_from_adapter(provider_adapter, provider_family=provider_family)
        if profile is not None and profile.resolution_source != "unresolved":
            return replace(profile, notes=tuple(list(profile.notes) + notes))

    # Model metadata (structured fields only — not name heuristics).
    if isinstance(model_metadata, Mapping) and model_metadata:
        meta_profile = _profile_from_metadata(model_metadata, provider_family=provider_family)
        if meta_profile.supports_native_reasoning or meta_profile.resolution_source == "metadata":
            return replace(meta_profile, notes=tuple(list(meta_profile.notes) + notes))

    # Safe capability probe.
    if isinstance(probe_result, Mapping) and probe_result:
        probe_profile = _profile_from_mapping(
            probe_result,
            resolution_source="probe",
            provider_family=str(
                probe_result.get("provider_family") or provider_family or "generic"
            ),
            notes=tuple(notes + ["from_capability_probe"]),
        )
        return probe_profile

    family = (provider_family or "generic").strip().lower() or "generic"
    notes.append("no_adapter_metadata_or_probe — generic_ttc_path")
    return ReasoningCapabilityProfile(
        supports_native_reasoning=False,
        provider_family=family,
        resolution_source="unresolved",
        notes=tuple(notes),
    )


def _profile_from_adapter(
    adapter: Any,
    *,
    provider_family: str | None,
) -> ReasoningCapabilityProfile | None:
    # Explicit method preferred.
    if hasattr(adapter, "reasoning_capability_profile"):
        try:
            raw = adapter.reasoning_capability_profile()
            if isinstance(raw, ReasoningCapabilityProfile):
                return raw
            if isinstance(raw, Mapping):
                return _profile_from_mapping(
                    raw,
                    resolution_source="adapter",
                    provider_family=str(
                        raw.get("provider_family")
                        or provider_family
                        or getattr(adapter, "provider_id", None)
                        or "generic"
                    ),
                )
        except Exception:  # noqa: BLE001
            pass

    caps = None
    if hasattr(adapter, "capabilities"):
        try:
            caps = adapter.capabilities()
        except Exception:  # noqa: BLE001
            caps = None
    family = str(
        provider_family
        or getattr(adapter, "provider_id", None)
        or getattr(adapter, "provider_family", None)
        or "generic"
    )
    if caps is None:
        return ReasoningCapabilityProfile(
            provider_family=family,
            resolution_source="adapter",
            notes=("adapter_capabilities_unavailable",),
        )

    # RuntimeCapabilities / ModelCapabilities — only trust explicit fields.
    tool_calling = bool(getattr(caps, "tool_calling", False))
    structured = bool(getattr(caps, "structured_output", False))
    # ModelCapabilities.reasoning is CapabilityState — SUPPORTED only when explicit.
    reasoning_state = getattr(caps, "reasoning", None)
    supports_native = False
    if reasoning_state is not None:
        value = getattr(reasoning_state, "value", reasoning_state)
        supports_native = str(value).lower() == "supported"
    return ReasoningCapabilityProfile(
        supports_native_reasoning=supports_native,
        supported_efforts=() if not supports_native else (),
        supports_reasoning_token_budget=False,
        supports_tool_interleaving=tool_calling,
        supports_parallel_tool_calls=False,
        supports_structured_output=structured,
        provider_family=family,
        resolution_source="adapter",
        notes=(
            "adapter_reasoning_explicit" if supports_native else "adapter_reasoning_not_supported_or_unknown",
        ),
    )


def _profile_from_metadata(
    metadata: Mapping[str, Any],
    *,
    provider_family: str | None,
) -> ReasoningCapabilityProfile:
    # Only structured capability blocks — ignore display names.
    block = metadata.get("reasoning_capabilities") or metadata.get("reasoningCapability")
    if isinstance(block, Mapping):
        return _profile_from_mapping(
            block,
            resolution_source="metadata",
            provider_family=str(
                block.get("provider_family")
                or metadata.get("provider_family")
                or provider_family
                or "generic"
            ),
            notes=("from_model_metadata_reasoning_capabilities",),
        )
    # Coarse ModelCapabilities.reasoning in metadata
    caps = metadata.get("capabilities")
    supports = False
    if isinstance(caps, Mapping):
        raw = caps.get("reasoning")
        supports = str(raw).lower() == "supported"
    return ReasoningCapabilityProfile(
        supports_native_reasoning=supports,
        provider_family=str(metadata.get("provider_family") or provider_family or "generic"),
        resolution_source="metadata" if isinstance(caps, Mapping) else "unresolved",
        notes=("metadata_without_structured_reasoning_block",),
    )


def _profile_from_mapping(
    raw: Mapping[str, Any],
    *,
    resolution_source: str,
    provider_family: str,
    notes: tuple[str, ...] = (),
) -> ReasoningCapabilityProfile:
    efforts_raw = raw.get("supported_efforts") or raw.get("supportedEfforts") or ()
    if isinstance(efforts_raw, str):
        efforts = tuple(p.strip().upper() for p in efforts_raw.split(",") if p.strip())
    else:
        efforts = tuple(str(x).strip().upper() for x in efforts_raw if str(x).strip())

    def _bool(key: str, *alts: str, default: bool = False) -> bool:
        for k in (key, *alts):
            if k in raw:
                return bool(raw[k])
        return default

    return ReasoningCapabilityProfile(
        supports_native_reasoning=_bool(
            "supports_native_reasoning", "supportsNativeReasoning", default=False
        ),
        supported_efforts=efforts,
        supports_reasoning_token_budget=_bool(
            "supports_reasoning_token_budget", "supportsReasoningTokenBudget"
        ),
        supports_reasoning_output_channel=_bool(
            "supports_reasoning_output_channel", "supportsReasoningOutputChannel"
        ),
        supports_persistent_reasoning_state=_bool(
            "supports_persistent_reasoning_state", "supportsPersistentReasoningState"
        ),
        supports_tool_interleaving=_bool(
            "supports_tool_interleaving", "supportsToolInterleaving"
        ),
        supports_parallel_tool_calls=_bool(
            "supports_parallel_tool_calls", "supportsParallelToolCalls"
        ),
        supports_seed=_bool("supports_seed", "supportsSeed"),
        supports_structured_output=_bool(
            "supports_structured_output", "supportsStructuredOutput"
        ),
        supports_context_cache=_bool("supports_context_cache", "supportsContextCache"),
        provider_family=provider_family,
        resolution_source=resolution_source,
        notes=notes,
    )


def apply_capability_to_budget(
    budget: NeuralComputeBudget,
    profile: ReasoningCapabilityProfile,
) -> NeuralComputeBudget:
    """Adjust provider-bound fields; keep LEVIATHAN semantic effort for TTC.

    When native reasoning is unsupported, candidate/branch fields remain for
    test-time compute. Reasoning-token budgets are cleared (cannot be sent).
    Effort mapping for provider transport happens in adapters (F3).
    """
    if not profile.supports_native_reasoning:
        return replace(budget, max_reasoning_tokens=None)
    mapped = profile.map_effort(budget.native_effort)
    tokens = budget.max_reasoning_tokens
    if not profile.supports_reasoning_token_budget:
        tokens = None
    return replace(budget, native_effort=mapped, max_reasoning_tokens=tokens)
