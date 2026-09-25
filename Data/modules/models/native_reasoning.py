"""Provider-native reasoning parameter mapping.

Model Control Plane remains the model owner. These helpers only decide which
provider fields are legal to send. GENERIC / unknown providers send nothing —
LEVIATHAN test-time compute handles depth instead.

Never invent support from a model display name.
Does not import cognition (ownership boundary).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


_OPENAI_EFFORT_MAP = {
    "MINIMAL": "low",
    "LOW": "low",
    "MEDIUM": "medium",
    "HIGH": "high",
    "MAXIMUM": "high",
}


@dataclass(frozen=True)
class NativeReasoningHints:
    """Provider-safe extras for a completion payload (may be empty)."""

    provider_family: str
    path: str  # native | ttc
    provider_hints: dict[str, Any] = field(default_factory=dict)
    forbidden_keys: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    effective_effort: str | None = None
    max_reasoning_tokens: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider_family": self.provider_family,
            "path": self.path,
            "provider_hints_keys": sorted(self.provider_hints.keys()),
            "forbidden_keys": list(self.forbidden_keys),
            "notes": list(self.notes),
            "effective_effort": self.effective_effort,
            "max_reasoning_tokens": self.max_reasoning_tokens,
            "truth": {
                "generic_sends_no_unknown_reasoning_knobs": self.path == "ttc"
                or bool(self.provider_hints),
                "hints_are_not_private_cot": True,
            },
        }


def _normalize_family(provider_family: str) -> str:
    family = (provider_family or "generic").strip().lower()
    if family in {"openai", "openai-compatible", "openai_compatible"}:
        return "openai_compatible"
    if family in {"llama.cpp", "llamacpp", "llama_cpp"}:
        return "llama_cpp"
    if family in {"lm-studio", "lmstudio", "lm_studio"}:
        return "lm_studio"
    if family in {"vllm", "vllm_class"}:
        return "vllm_class"
    return family or "generic"


def build_native_reasoning_hints(
    *,
    provider_family: str,
    supports_native_reasoning: bool,
    supported_efforts: tuple[str, ...] | list[str] = (),
    supports_reasoning_token_budget: bool = False,
    native_effort: str = "MEDIUM",
    max_reasoning_tokens: int | None = None,
) -> NativeReasoningHints:
    """Map semantic effort → legal provider fields for this family."""
    family = _normalize_family(provider_family)
    effort_key = str(native_effort or "MEDIUM").strip().upper()

    if not supports_native_reasoning or effort_key in {"UNSUPPORTED", "UNMEASURED"}:
        return NativeReasoningHints(
            provider_family=family,
            path="ttc",
            provider_hints={},
            forbidden_keys=(
                "reasoning_effort",
                "reasoning",
                "thinking",
                "think",
                "max_reasoning_tokens",
            ),
            notes=(
                (
                    "native_reasoning_unsupported — use_leviathan_ttc"
                    if not supports_native_reasoning
                    else f"effort_{effort_key} — defer_to_ttc"
                ),
            ),
            effective_effort=None,
            max_reasoning_tokens=None,
        )

    if family in {"openai_compatible", "ollama", "llama_cpp", "lm_studio", "vllm_class"}:
        return _openai_compatible_hints(
            family=family,
            supported_efforts=tuple(supported_efforts or ()),
            supports_reasoning_token_budget=supports_reasoning_token_budget,
            effort_key=effort_key,
            max_reasoning_tokens=max_reasoning_tokens,
        )

    return NativeReasoningHints(
        provider_family=family,
        path="ttc",
        provider_hints={},
        forbidden_keys=(
            "reasoning_effort",
            "reasoning",
            "thinking",
            "think",
            "max_reasoning_tokens",
        ),
        notes=("generic_provider_family — no_unknown_reasoning_parameters",),
    )


def _openai_compatible_hints(
    *,
    family: str,
    supported_efforts: tuple[str, ...],
    supports_reasoning_token_budget: bool,
    effort_key: str,
    max_reasoning_tokens: int | None,
) -> NativeReasoningHints:
    effort = _OPENAI_EFFORT_MAP.get(effort_key, "medium")
    supported_lower = {e.lower() for e in supported_efforts}
    supported_upper = {e.upper() for e in supported_efforts}
    if supported_lower and effort not in supported_lower:
        for candidate in ("high", "medium", "low", "minimal"):
            if candidate in supported_lower:
                effort = candidate
                break
        else:
            if effort_key in supported_upper:
                effort = _OPENAI_EFFORT_MAP.get(effort_key, "medium")
            elif "HIGH" in supported_upper:
                effort = "high"
            elif "MEDIUM" in supported_upper:
                effort = "medium"
            elif "LOW" in supported_upper or "MINIMAL" in supported_upper:
                effort = "low"

    hints: dict[str, Any] = {"reasoning_effort": effort}
    tokens: int | None = None
    notes = [f"{family}_reasoning_effort"]
    if (
        supports_reasoning_token_budget
        and max_reasoning_tokens is not None
        and int(max_reasoning_tokens) > 0
    ):
        tokens = int(max_reasoning_tokens)
        hints["max_reasoning_tokens"] = tokens
        notes.append("reasoning_token_budget_attached")

    return NativeReasoningHints(
        provider_family=family,
        path="native",
        provider_hints=hints,
        forbidden_keys=("thinking", "think"),
        notes=tuple(notes),
        effective_effort=effort,
        max_reasoning_tokens=tokens,
    )


def parse_reasoning_usage(raw: Mapping[str, Any] | None) -> tuple[int | None, str]:
    """Extract provider-reported reasoning tokens. Never invent counts."""
    if not isinstance(raw, Mapping):
        return None, "unavailable"
    for key in ("reasoning_tokens", "reasoningTokens"):
        if key in raw and raw[key] is not None:
            try:
                return int(raw[key]), "provider"
            except (TypeError, ValueError):
                pass
    details = raw.get("completion_tokens_details") or raw.get("output_tokens_details")
    if isinstance(details, Mapping):
        for key in ("reasoning_tokens", "reasoningTokens"):
            if key in details and details[key] is not None:
                try:
                    return int(details[key]), "provider"
                except (TypeError, ValueError):
                    pass
    usage = raw.get("usage") if "usage" in raw else None
    if isinstance(usage, Mapping):
        return parse_reasoning_usage(usage)
    return None, "unavailable"


def strip_private_reasoning_fields(message: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove private chain-of-thought channels from a provider message object."""
    if not isinstance(message, Mapping):
        return {}
    return {
        k: v
        for k, v in message.items()
        if k
        not in {
            "reasoning",
            "reasoning_content",
            "reasoning_text",
            "thinking",
            "thinking_content",
            "encrypted_content",
        }
    }
