"""ReasoningPolicy — budget profiles for MetaController / Cognitive Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _default_mode_budgets() -> dict[str, dict[str, Any]]:
    """CognitiveBudgets-compatible presets matching MetaController hardcodes."""
    return {
        "FAST": {
            "max_wall_time_seconds": 30.0,
            "max_model_calls": 1,
            "max_model_tokens": 2000,
            "max_tool_calls": 0,
            "max_agent_delegations": 0,
            "max_replans": 0,
            "max_retries": 1,
            "max_retrieval_rounds": 1,
            "max_parallel_workers": 1,
            "max_context_tokens": 3000,
            "max_critic_passes": 0,
            "max_iterations": 2,
        },
        "STANDARD": {
            "max_wall_time_seconds": 90.0,
            "max_model_calls": 3,
            "max_model_tokens": 6000,
            "max_tool_calls": 4,
            "max_agent_delegations": 1,
            "max_replans": 2,
            "max_retries": 2,
            "max_retrieval_rounds": 2,
            "max_parallel_workers": 2,
            "max_context_tokens": 6000,
            "max_critic_passes": 1,
            "max_iterations": 5,
        },
        "DEEP": {
            "max_wall_time_seconds": 180.0,
            "max_model_calls": 6,
            "max_model_tokens": 12000,
            "max_tool_calls": 8,
            "max_agent_delegations": 2,
            "max_replans": 3,
            "max_retries": 3,
            "max_retrieval_rounds": 3,
            "max_parallel_workers": 3,
            "max_context_tokens": 8000,
            "max_critic_passes": 2,
            "max_iterations": 8,
        },
        "MAXIMUM": {
            "max_wall_time_seconds": 300.0,
            "max_model_calls": 10,
            "max_model_tokens": 20000,
            "max_tool_calls": 12,
            "max_agent_delegations": 3,
            "max_replans": 4,
            "max_retries": 4,
            "max_retrieval_rounds": 4,
            "max_parallel_workers": 4,
            "max_context_tokens": 12000,
            "max_critic_passes": 3,
            "max_iterations": 12,
        },
    }


@dataclass(frozen=True)
class ReasoningPolicy:
    """Operator-facing reasoning budget policy (settings → cognition)."""

    default_mode: str = "adaptive"
    allow_fast_path: bool = True
    minimum_evidence_coverage: float = 0.3
    uncertainty_deep_threshold: float = 0.75
    contradiction_replan_threshold: float = 0.3
    minimum_information_gain: float = 0.1
    resource_clamp_pressure_threshold: float = 0.8
    verification_escalation: bool = True
    max_replans_global: int = 4
    max_retries_global: int = 4
    require_verification_for_high_risk: bool = True
    require_grounding_for_knowledge_tasks: bool = True
    mode_budgets: dict[str, dict[str, Any]] = field(default_factory=_default_mode_budgets)
    mode_neural_budgets: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Optional Settings override for ReasoningCapabilityProfile (apply=True required).
    reasoning_capability_override: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def budget_for(self, mode: str) -> dict[str, Any]:
        key = (mode or self.default_mode).strip().upper()
        if key == "ADAPTIVE":
            key = "STANDARD"
        budgets = self.mode_budgets.get(key) or self.mode_budgets.get("STANDARD") or {}
        return dict(budgets)

    def budgets_for(self, mode: str) -> dict[str, Any]:
        """Alias for MetaController / callers that prefer plural naming."""
        return self.budget_for(mode)

    def neural_budget_for(self, mode: str) -> dict[str, Any]:
        key = (mode or self.default_mode).strip().upper()
        if key == "ADAPTIVE":
            key = "STANDARD"
        raw = self.mode_neural_budgets.get(key) or self.mode_neural_budgets.get(mode) or {}
        return dict(raw)

    def public_dict(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode,
            "allow_fast_path": self.allow_fast_path,
            "minimum_evidence_coverage": self.minimum_evidence_coverage,
            "uncertainty_deep_threshold": self.uncertainty_deep_threshold,
            "contradiction_replan_threshold": self.contradiction_replan_threshold,
            "minimum_information_gain": self.minimum_information_gain,
            "resource_clamp_pressure_threshold": self.resource_clamp_pressure_threshold,
            "verification_escalation": self.verification_escalation,
            "max_replans_global": self.max_replans_global,
            "max_retries_global": self.max_retries_global,
            "require_verification_for_high_risk": self.require_verification_for_high_risk,
            "require_grounding_for_knowledge_tasks": self.require_grounding_for_knowledge_tasks,
            "mode_budgets": {k: dict(v) for k, v in self.mode_budgets.items()},
            "mode_neural_budgets": {k: dict(v) for k, v in self.mode_neural_budgets.items()},
            "reasoning_capability_override": dict(self.reasoning_capability_override),
            "enabled": self.enabled,
            "truth": {
                "modes_control_real_budgets": True,
                "two_axis_compute": True,
                "defaults_match_meta_controller_hardcodes": True,
            },
        }

    @classmethod
    def _budgets_from_flat_settings(cls, reasoning: Any) -> dict[str, dict[str, Any]] | None:
        """Assemble mode budgets from ReasoningSettings flat profile fields when present."""
        if reasoning is None:
            return None
        profiles = ("fast", "standard", "deep", "maximum")
        field_map = (
            ("max_wall_time_seconds", float),
            ("max_model_calls", int),
            ("max_model_tokens", int),
            ("max_retrieval_rounds", int),
            ("max_critic_passes", int),
            ("max_tool_calls", int),
            ("max_agent_delegations", int),
            ("max_iterations", int),
            ("max_context_tokens", int),
        )
        # Probe one field — if absent, settings has not been extended yet.
        if not hasattr(reasoning, "fast_max_model_calls"):
            return None
        defaults = _default_mode_budgets()
        out: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            key = profile.upper()
            base = dict(defaults.get(key) or {})
            for field_name, caster in field_map:
                attr = f"{profile}_{field_name}"
                if hasattr(reasoning, attr):
                    try:
                        base[field_name] = caster(getattr(reasoning, attr))
                    except (TypeError, ValueError):
                        pass
            # Align replans/retries with global caps when flat fields omit them.
            out[key] = base
        return out

    @classmethod
    def _neural_budgets_from_flat_settings(cls, reasoning: Any) -> dict[str, dict[str, Any]] | None:
        if reasoning is None or not hasattr(reasoning, "fast_neural_candidate_count"):
            return None
        profiles = ("fast", "standard", "deep", "maximum")
        fields = (
            "native_effort",
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
            "diversity_temperature",
        )
        out: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            key = profile.upper()
            entry: dict[str, Any] = {}
            for field_name in fields:
                attr = f"{profile}_neural_{field_name}"
                if hasattr(reasoning, attr):
                    entry[field_name] = getattr(reasoning, attr)
            if entry:
                out[key] = entry
        return out or None

    @classmethod
    def from_settings(cls, settings: Any) -> "ReasoningPolicy":
        """Read budget profile from Settings.reasoning; fall back to MetaController defaults."""
        reasoning = getattr(settings, "reasoning", None)
        enabled = True
        if reasoning is not None:
            enabled = bool(getattr(reasoning, "enabled", True))

        def _get(name: str, default: Any) -> Any:
            if reasoning is None:
                return default
            return getattr(reasoning, name, default)

        default_mode = str(_get("default_mode", "adaptive") or "adaptive").strip().lower()
        mode_budgets = _default_mode_budgets()
        flat = cls._budgets_from_flat_settings(reasoning)
        if flat:
            mode_budgets.update(flat)
        raw_budgets = _get("mode_budgets", None)
        if isinstance(raw_budgets, Mapping):
            for key, value in raw_budgets.items():
                if isinstance(value, Mapping):
                    mode_budgets[str(key).strip().upper()] = dict(value)

        mode_neural: dict[str, dict[str, Any]] = {}
        neural_flat = cls._neural_budgets_from_flat_settings(reasoning)
        if neural_flat:
            mode_neural.update(neural_flat)
        raw_neural = _get("mode_neural_budgets", None)
        if isinstance(raw_neural, Mapping):
            for key, value in raw_neural.items():
                if isinstance(value, Mapping):
                    mode_neural[str(key).strip().upper()] = dict(value)

        override_raw = _get("reasoning_capability_override", None)
        override: dict[str, Any] = dict(override_raw) if isinstance(override_raw, Mapping) else {}
        if not override and bool(_get("reasoning_capability_override_apply", False)):
            efforts = str(_get("reasoning_capability_override_efforts", "") or "")
            override = {
                "apply": True,
                "supports_native_reasoning": bool(
                    _get("reasoning_capability_override_supports_native", False)
                ),
                "provider_family": str(
                    _get("reasoning_capability_override_provider_family", "generic") or "generic"
                ),
                "supported_efforts": [
                    p.strip().upper() for p in efforts.split(",") if p.strip()
                ],
            }

        allow_fast = bool(_get("allow_fast_path", True))
        max_replans = int(_get("max_replans_global", 4))
        max_retries = int(_get("max_retries_global", 4))

        return cls(
            default_mode=default_mode,
            allow_fast_path=allow_fast,
            minimum_evidence_coverage=float(_get("minimum_evidence_coverage", 0.3)),
            uncertainty_deep_threshold=float(_get("uncertainty_deep_threshold", 0.75)),
            contradiction_replan_threshold=float(_get("contradiction_replan_threshold", 0.3)),
            minimum_information_gain=float(_get("minimum_information_gain", 0.1)),
            resource_clamp_pressure_threshold=float(
                _get("resource_clamp_pressure_threshold", 0.8)
            ),
            verification_escalation=bool(_get("verification_escalation", True)),
            max_replans_global=max_replans,
            max_retries_global=max_retries,
            require_verification_for_high_risk=bool(
                _get("require_verification_for_high_risk", True)
            ),
            require_grounding_for_knowledge_tasks=bool(
                _get("require_grounding_for_knowledge_tasks", True)
            ),
            mode_budgets=mode_budgets,
            mode_neural_budgets=mode_neural,
            reasoning_capability_override=override,
            enabled=enabled,
        )
