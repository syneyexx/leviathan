"""Capability eligibility policy for ModelRouter / Model Control Plane.

Centralizes how declared/inferred capabilities satisfy request requirements.
Do not scatter special-cases for embedding/non-chat models elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from Data.modules.models.contracts import CapabilityState, ModelCapabilities, ModelDescriptor


class CapabilityProvenance(str, Enum):
    PROVIDER_REPORTED = "provider_reported"
    RUNTIME_REPORTED = "runtime_reported"
    OPERATOR_CONFIGURED = "operator_configured"
    INFERRED_MODEL_FAMILY = "inferred_model_family"
    UNVERIFIED = "unverified"


# Bounded fallback classifier — only for obvious non-generative families
# when provider capability metadata is missing / unknown.
_NON_CHAT_FAMILY = re.compile(
    r"(?i)("
    r"embed(?:ding|dings)?|"
    r"\bbge\b|"
    r"\be5\b|"
    r"\bgte\b|"
    r"nomic[-_]?embed|"
    r"text[-_]?embedding|"
    r"rerank(?:er|ing)?|"
    r"cross[-_]?encoder|"
    r"sentence[-_]?transformers|"
    r"minilm|"
    r"instructor[-_]?xl|"
    r"\bclip\b|"
    r"colbert"
    r")"
)

_GENERATIVE_HINT = re.compile(
    r"(?i)("
    r"llama|qwen|mistral|mixtral|phi|gemma|deepseek|yi\b|command[-_]?r|"
    r"gpt|claude|mpt|falcon|vicuna|wizard|orca|zephyr|solar|nous|"
    r"chat|instruct|it\b|sft|dpo"
    r")"
)


@dataclass(frozen=True)
class CapabilityDecision:
    satisfies: bool
    state: CapabilityState
    provenance: CapabilityProvenance
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "satisfies": self.satisfies,
            "state": self.state.value,
            "provenance": self.provenance.value,
            "reason": self.reason,
        }


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
        "embedding": "embeddings",
        "rerank": "embeddings",
        "streaming": "streaming",
    }
    return mapping.get(name, name)


def model_identity_text(model: ModelDescriptor) -> str:
    parts = [
        model.id or "",
        model.display_name or "",
        model.family or "",
        model.architecture or "",
        str((model.metadata or {}).get("provider_model_id") or ""),
        " ".join(model.tags or ()),
    ]
    return " ".join(parts).lower()


def infer_non_chat_family(model: ModelDescriptor) -> bool:
    """True when structural name evidence strongly indicates a non-generative model."""
    text = model_identity_text(model)
    if not text.strip():
        return False
    if _NON_CHAT_FAMILY.search(text):
        # Avoid false positives on generative models that mention "embedding" in metadata
        # only as a secondary capability — require the family token to dominate identity.
        return True
    return False


def infer_likely_generative(model: ModelDescriptor) -> bool:
    text = model_identity_text(model)
    return bool(_GENERATIVE_HINT.search(text))


def apply_family_capability_inference(
    capabilities: ModelCapabilities,
    model: ModelDescriptor,
    *,
    provider_authoritative: bool = False,
) -> tuple[ModelCapabilities, dict[str, str]]:
    """Return capabilities with obvious non-chat families marked UNSUPPORTED for chat.

    When provider_authoritative is True and chat is already known (supported/unsupported),
    do not override. Provenance map is returned for telemetry.
    """
    provenance: dict[str, str] = {}
    chat = capabilities.chat
    embeddings = capabilities.embeddings

    if provider_authoritative and chat in {CapabilityState.SUPPORTED, CapabilityState.UNSUPPORTED}:
        provenance["chat"] = CapabilityProvenance.PROVIDER_REPORTED.value
        return capabilities, provenance

    if infer_non_chat_family(model):
        chat = CapabilityState.UNSUPPORTED
        if embeddings in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED, CapabilityState.UNMEASURED}:
            embeddings = CapabilityState.SUPPORTED
        provenance["chat"] = CapabilityProvenance.INFERRED_MODEL_FAMILY.value
        provenance["embeddings"] = CapabilityProvenance.INFERRED_MODEL_FAMILY.value
        return (
            ModelCapabilities(
                chat=chat,
                reasoning=CapabilityState.UNSUPPORTED
                if capabilities.reasoning in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
                else capabilities.reasoning,
                coding=CapabilityState.UNSUPPORTED
                if capabilities.coding in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
                else capabilities.coding,
                tool_calling=capabilities.tool_calling,
                structured_output=capabilities.structured_output,
                vision=capabilities.vision,
                embeddings=embeddings,
                streaming=CapabilityState.UNSUPPORTED
                if capabilities.streaming in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
                else capabilities.streaming,
            ),
            provenance,
        )

    if chat == CapabilityState.UNKNOWN and infer_likely_generative(model):
        provenance["chat"] = CapabilityProvenance.UNVERIFIED.value
        return (
            ModelCapabilities(
                chat=CapabilityState.UNVERIFIED,
                reasoning=capabilities.reasoning,
                coding=capabilities.coding,
                tool_calling=capabilities.tool_calling,
                structured_output=capabilities.structured_output,
                vision=capabilities.vision,
                embeddings=capabilities.embeddings,
                streaming=capabilities.streaming,
            ),
            provenance,
        )

    provenance["chat"] = (
        CapabilityProvenance.PROVIDER_REPORTED.value
        if chat != CapabilityState.UNKNOWN
        else CapabilityProvenance.UNVERIFIED.value
    )
    return capabilities, provenance


def enrich_descriptor_capabilities(model: ModelDescriptor) -> ModelDescriptor:
    """Apply family inference onto a descriptor when chat is not provider-known."""
    provider_auth = model.capabilities.chat in {
        CapabilityState.SUPPORTED,
        CapabilityState.UNSUPPORTED,
    }
    caps, provenance = apply_family_capability_inference(
        model.capabilities,
        model,
        provider_authoritative=provider_auth,
    )
    meta = dict(model.metadata or {})
    if provenance:
        meta["capabilityProvenance"] = {
            **dict(meta.get("capabilityProvenance") or {}),
            **provenance,
        }
    if caps == model.capabilities and meta == (model.metadata or {}):
        return model
    # ModelDescriptor is a dataclass — rebuild via public fields.
    payload = {k: v for k, v in model.__dict__.items()}
    payload["capabilities"] = caps
    payload["metadata"] = meta
    return ModelDescriptor(**payload)  # type: ignore[arg-type]


def capability_satisfies_request(
    model: ModelDescriptor,
    capability: str,
    *,
    request_context: dict[str, Any] | None = None,
) -> CapabilityDecision:
    """Decide whether ``model`` satisfies a required ``capability``.

    Policy for critical generative capabilities such as ``chat``:
      SUPPORTED / UNVERIFIED (generative-runtime evidence) → eligible
      UNSUPPORTED → ineligible
      UNKNOWN on obvious non-chat families → ineligible
      UNMEASURED → conservative (ineligible for chat)
      UNKNOWN otherwise → eligible only when runtime supports generative chat
        and there is reasonable generative-family evidence
    """
    ctx = request_context or {}
    attr = _cap_attr(capability)
    state = getattr(model.capabilities, attr, CapabilityState.UNKNOWN)
    if not isinstance(state, CapabilityState):
        try:
            state = CapabilityState(str(state))
        except ValueError:
            state = CapabilityState.UNKNOWN

    critical = capability in {"chat", "reasoning", "coding"} or attr == "chat"

    if state == CapabilityState.SUPPORTED:
        return CapabilityDecision(
            True, state, CapabilityProvenance.PROVIDER_REPORTED, "capability_supported"
        )

    if state == CapabilityState.UNSUPPORTED:
        return CapabilityDecision(
            False, state, CapabilityProvenance.PROVIDER_REPORTED, "capability_unsupported"
        )

    # Apply family inference for unknown/unmeasured chat-like requirements.
    if critical and attr == "chat" and infer_non_chat_family(model):
        return CapabilityDecision(
            False,
            CapabilityState.UNSUPPORTED,
            CapabilityProvenance.INFERRED_MODEL_FAMILY,
            "inferred_non_chat_model_family",
        )

    if state == CapabilityState.UNMEASURED:
        return CapabilityDecision(
            False if critical else True,
            state,
            CapabilityProvenance.UNVERIFIED,
            "unmeasured_treated_conservatively" if critical else "unmeasured_non_critical",
        )

    if state == CapabilityState.UNVERIFIED:
        # Eligible when the provider/runtime itself supports generative chat inference
        # and there is reasonable evidence this is a generative model.
        runtime_chat = bool(ctx.get("runtime_supports_chat", True))
        if attr == "chat" and not runtime_chat:
            return CapabilityDecision(
                False, state, CapabilityProvenance.RUNTIME_REPORTED, "runtime_lacks_chat"
            )
        if attr == "chat" and infer_non_chat_family(model):
            return CapabilityDecision(
                False,
                CapabilityState.UNSUPPORTED,
                CapabilityProvenance.INFERRED_MODEL_FAMILY,
                "unverified_but_non_chat_family",
            )
        return CapabilityDecision(
            True, state, CapabilityProvenance.UNVERIFIED, "unverified_generative_ok"
        )

    # UNKNOWN
    if not critical:
        return CapabilityDecision(
            True, state, CapabilityProvenance.UNVERIFIED, "unknown_non_critical_permitted"
        )

    runtime_chat = bool(ctx.get("runtime_supports_chat", True))
    if attr == "chat":
        if not runtime_chat:
            return CapabilityDecision(
                False, state, CapabilityProvenance.RUNTIME_REPORTED, "unknown_runtime_lacks_chat"
            )
        if infer_non_chat_family(model):
            return CapabilityDecision(
                False,
                CapabilityState.UNSUPPORTED,
                CapabilityProvenance.INFERRED_MODEL_FAMILY,
                "unknown_inferred_non_chat",
            )
        if infer_likely_generative(model) or bool(ctx.get("allow_unknown_generative", False)):
            return CapabilityDecision(
                True, state, CapabilityProvenance.UNVERIFIED, "unknown_likely_generative"
            )
        # Conservative for critical chat: do not silently admit unknown embedding-like IDs.
        # If neither generative nor non-chat evidence, treat as ineligible for Auto routing
        # unless explicitly selected with operator override (caller decides).
        if bool(ctx.get("explicit_selection", False)):
            return CapabilityDecision(
                False, state, CapabilityProvenance.UNVERIFIED, "unknown_chat_explicit_rejected"
            )
        return CapabilityDecision(
            False, state, CapabilityProvenance.UNVERIFIED, "unknown_chat_conservative"
        )

    # Other critical caps (reasoning/coding): UNKNOWN is soft — do not hard-block
    # unless explicitly marked unsupported.
    return CapabilityDecision(
        True, state, CapabilityProvenance.UNVERIFIED, "unknown_soft_critical"
    )


def is_chat_capable(
    model: ModelDescriptor,
    *,
    explicit_selection: bool = False,
    runtime_supports_chat: bool = True,
) -> CapabilityDecision:
    return capability_satisfies_request(
        model,
        "chat",
        request_context={
            "explicit_selection": explicit_selection,
            "runtime_supports_chat": runtime_supports_chat,
        },
    )
