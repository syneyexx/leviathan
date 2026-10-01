"""Capability eligibility policy for ModelRouter / Model Control Plane.

Centralizes how declared/inferred/verified capabilities satisfy request
requirements. Hard required capabilities are fail-closed.

Do not scatter special-cases for embedding/non-chat models elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from Data.modules.models.capability_vocabulary import (
    UnknownCapabilityAlias,
    capability_attr,
    normalize_capability_name,
)
from Data.modules.models.contracts import CapabilityState, ModelCapabilities, ModelDescriptor
from Data.modules.models.effective_capability import (
    EffectiveCapability,
    EffectiveProvenance,
    resolve_effective_capability,
)
from Data.modules.models.contracts import VerifiedCapability


class CapabilityProvenance(str, Enum):
    PROVIDER_REPORTED = "provider_reported"
    RUNTIME_REPORTED = "runtime_reported"
    OPERATOR_CONFIGURED = "operator_configured"
    INFERRED_MODEL_FAMILY = "inferred_model_family"
    VERIFIED_PROBE = "verified_probe"
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
    """Backward-compatible attribute resolver — uses canonical vocabulary."""
    return capability_attr(name)


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

    Uses dataclasses.replace so unrelated / frontier fields are NEVER reset.
    When provider_authoritative is True and chat is already known (supported/unsupported),
    do not override.
    """
    provenance: dict[str, str] = {}
    chat = capabilities.chat
    embeddings = capabilities.embeddings

    if provider_authoritative and chat in {CapabilityState.SUPPORTED, CapabilityState.UNSUPPORTED}:
        provenance["chat"] = CapabilityProvenance.PROVIDER_REPORTED.value
        return capabilities, provenance

    if infer_non_chat_family(model):
        chat = CapabilityState.UNSUPPORTED
        # Rerank/cross-encoder families are NOT embeddings — do not coerce.
        identity = model_identity_text(model)
        is_rerank = bool(
            re.search(r"(?i)rerank(?:er|ing)?|cross[-_]?encoder|colbert", identity)
        )
        if (
            not is_rerank
            and embeddings
            in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED, CapabilityState.UNMEASURED}
        ):
            embeddings = CapabilityState.SUPPORTED
            provenance["embeddings"] = CapabilityProvenance.INFERRED_MODEL_FAMILY.value
        elif is_rerank:
            # Leave embeddings as-is (typically UNKNOWN) — rerank ≠ embeddings.
            provenance["embeddings"] = CapabilityProvenance.UNVERIFIED.value
        provenance["chat"] = CapabilityProvenance.INFERRED_MODEL_FAMILY.value
        if not is_rerank and "embeddings" not in provenance:
            provenance["embeddings"] = CapabilityProvenance.INFERRED_MODEL_FAMILY.value
        reasoning = (
            CapabilityState.UNSUPPORTED
            if capabilities.reasoning in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
            else capabilities.reasoning
        )
        coding = (
            CapabilityState.UNSUPPORTED
            if capabilities.coding in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
            else capabilities.coding
        )
        streaming = (
            CapabilityState.UNSUPPORTED
            if capabilities.streaming in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED}
            else capabilities.streaming
        )
        return (
            replace(
                capabilities,
                chat=chat,
                reasoning=reasoning,
                coding=coding,
                embeddings=embeddings,
                streaming=streaming,
            ),
            provenance,
        )

    if chat == CapabilityState.UNKNOWN and infer_likely_generative(model):
        provenance["chat"] = CapabilityProvenance.UNVERIFIED.value
        return replace(capabilities, chat=CapabilityState.UNVERIFIED), provenance

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
    payload = {k: v for k, v in model.__dict__.items()}
    payload["capabilities"] = caps
    payload["metadata"] = meta
    return ModelDescriptor(**payload)  # type: ignore[arg-type]


def _map_effective_provenance(eff: EffectiveCapability) -> CapabilityProvenance:
    if eff.provenance == EffectiveProvenance.OPERATOR_OVERRIDE:
        return CapabilityProvenance.OPERATOR_CONFIGURED
    if eff.provenance in {
        EffectiveProvenance.VERIFIED_PROBE,
        EffectiveProvenance.VERIFIED_PROBE_STALE,
    }:
        return CapabilityProvenance.VERIFIED_PROBE
    if eff.provenance == EffectiveProvenance.PROVIDER_REPORTED:
        return CapabilityProvenance.PROVIDER_REPORTED
    if eff.provenance == EffectiveProvenance.FAMILY_INFERENCE:
        return CapabilityProvenance.INFERRED_MODEL_FAMILY
    return CapabilityProvenance.UNVERIFIED


def capability_satisfies_request(
    model: ModelDescriptor,
    capability: str,
    *,
    request_context: dict[str, Any] | None = None,
    verified: VerifiedCapability | None = None,
    requirement_mode: str = "hard",
) -> CapabilityDecision:
    """Decide whether ``model`` satisfies a required ``capability``.

    ``requirement_mode``:
      - ``hard`` (default for ModelRequest.required_capabilities): fail-closed
        SUPPORTED / recent-verified SUPPORTED → eligible
        UNSUPPORTED / UNKNOWN / UNVERIFIED / UNMEASURED → reject
      - ``soft`` / ``preference``: scoring preference only — UNKNOWN may pass
      - ``best_effort``: attempt when not UNSUPPORTED

    Reasoning/coding are NOT soft-satisfied when explicitly required as hard.
    Soft preference belongs in scoring, not by weakening required capabilities.
    """
    ctx = request_context or {}
    mode = str(ctx.get("requirement_mode") or requirement_mode or "hard").lower()

    # Reject unsupported aliases (e.g. rerank) honestly.
    try:
        canonical = normalize_capability_name(capability, strict=False)
        if canonical is None:
            # Distinguish empty vs unsupported alias
            lower = str(capability or "").strip().lower().replace("-", "_")
            from Data.modules.models.capability_vocabulary import UNSUPPORTED_CAPABILITY_ALIASES

            if lower in UNSUPPORTED_CAPABILITY_ALIASES:
                return CapabilityDecision(
                    False,
                    CapabilityState.UNSUPPORTED,
                    CapabilityProvenance.UNVERIFIED,
                    "capability_alias_unsupported",
                )
            return CapabilityDecision(
                False,
                CapabilityState.UNKNOWN,
                CapabilityProvenance.UNVERIFIED,
                "capability_name_unknown",
            )
        attr = capability_attr(canonical)
    except UnknownCapabilityAlias:
        return CapabilityDecision(
            False,
            CapabilityState.UNSUPPORTED,
            CapabilityProvenance.UNVERIFIED,
            "capability_alias_unsupported",
        )

    # Prefer pre-merged effective state on the descriptor when present.
    eff_meta = (model.metadata or {}).get("effectiveCapabilities") or {}
    if isinstance(eff_meta, dict) and canonical in eff_meta:
        raw_state = eff_meta[canonical].get("state") if isinstance(eff_meta[canonical], dict) else None
        try:
            state = CapabilityState(str(raw_state)) if raw_state else CapabilityState.UNKNOWN
        except ValueError:
            state = CapabilityState.UNKNOWN
        provenance = CapabilityProvenance.VERIFIED_PROBE if (
            isinstance(eff_meta[canonical], dict)
            and str(eff_meta[canonical].get("provenance") or "").startswith("verified")
        ) else CapabilityProvenance.UNVERIFIED
    elif verified is not None or ctx.get("use_effective", True):
        eff = resolve_effective_capability(model, canonical, verified=verified)
        # Family inference may still refine UNKNOWN chat before hard check.
        if (
            eff.state in {CapabilityState.UNKNOWN, CapabilityState.UNVERIFIED, CapabilityState.UNMEASURED}
            and attr == "chat"
            and infer_non_chat_family(model)
            and eff.provenance
            not in {
                EffectiveProvenance.VERIFIED_PROBE,
                EffectiveProvenance.VERIFIED_PROBE_STALE,
                EffectiveProvenance.OPERATOR_OVERRIDE,
            }
        ):
            return CapabilityDecision(
                False,
                CapabilityState.UNSUPPORTED,
                CapabilityProvenance.INFERRED_MODEL_FAMILY,
                "inferred_non_chat_model_family",
            )
        state = eff.state
        provenance = _map_effective_provenance(eff)
    else:
        state = getattr(model.capabilities, attr, CapabilityState.UNKNOWN)
        if not isinstance(state, CapabilityState):
            try:
                state = CapabilityState(str(state))
            except ValueError:
                state = CapabilityState.UNKNOWN
        provenance = CapabilityProvenance.PROVIDER_REPORTED

    if state == CapabilityState.SUPPORTED:
        return CapabilityDecision(True, state, provenance, "capability_supported")

    if state == CapabilityState.UNSUPPORTED:
        return CapabilityDecision(False, state, provenance, "capability_unsupported")

    # Soft preference / best-effort modes — used by scoring only.
    if mode in {"soft", "preference"}:
        if state == CapabilityState.UNMEASURED:
            return CapabilityDecision(True, state, provenance, "soft_unmeasured_permitted")
        return CapabilityDecision(True, state, provenance, "soft_unknown_permitted")

    if mode == "best_effort":
        if state == CapabilityState.UNSUPPORTED:
            return CapabilityDecision(False, state, provenance, "best_effort_unsupported")
        return CapabilityDecision(True, state, provenance, "best_effort_attempt")

    # ---- HARD REQUIREMENT (default) — fail closed ----
    if attr == "chat" and infer_non_chat_family(model) and provenance != CapabilityProvenance.VERIFIED_PROBE:
        # Verified SUPPORTED already returned; verified UNSUPPORTED already returned.
        # Name heuristic may still reject when state is unresolved.
        if state in {
            CapabilityState.UNKNOWN,
            CapabilityState.UNVERIFIED,
            CapabilityState.UNMEASURED,
        }:
            return CapabilityDecision(
                False,
                CapabilityState.UNSUPPORTED,
                CapabilityProvenance.INFERRED_MODEL_FAMILY,
                "inferred_non_chat_model_family",
            )

    # Operator-authorized chat selection (explicit model id or activated default)
    # may attempt unresolved chat capability. Embedding/non-chat families and
    # verified UNSUPPORTED remain rejected above.
    authorized_chat = attr == "chat" and bool(
        ctx.get("explicit_selection") or ctx.get("authorized_selection")
    )

    if state == CapabilityState.UNMEASURED:
        if authorized_chat or bool(ctx.get("allow_unmeasured_hard", False)):
            return CapabilityDecision(
                True,
                state,
                provenance,
                (
                    "hard_chat_authorized_selection_permitted"
                    if authorized_chat
                    else "hard_unmeasured_explicitly_allowed"
                ),
            )
        return CapabilityDecision(
            False, state, provenance, "hard_unmeasured_rejected"
        )

    if state == CapabilityState.UNVERIFIED:
        # Hard requirements reject UNVERIFIED unless an explicit documented policy
        # allows it for this exact request (operator override / explicit policy flag).
        if authorized_chat or bool(ctx.get("allow_unverified_hard", False)):
            return CapabilityDecision(
                True,
                state,
                provenance,
                (
                    "hard_chat_authorized_selection_permitted"
                    if authorized_chat
                    else "hard_unverified_explicitly_allowed"
                ),
            )
        return CapabilityDecision(
            False, state, provenance, "hard_unverified_rejected"
        )

    # UNKNOWN
    if authorized_chat or bool(ctx.get("allow_unknown_hard", False)):
        return CapabilityDecision(
            True,
            state,
            provenance,
            (
                "hard_chat_authorized_selection_permitted"
                if authorized_chat
                else "hard_unknown_explicitly_allowed"
            ),
        )
    return CapabilityDecision(
        False, state, provenance, "hard_unknown_rejected"
    )


def is_chat_capable(
    model: ModelDescriptor,
    *,
    explicit_selection: bool = False,
    runtime_supports_chat: bool = True,
    verified: VerifiedCapability | None = None,
) -> CapabilityDecision:
    return capability_satisfies_request(
        model,
        "chat",
        request_context={
            "explicit_selection": explicit_selection,
            "runtime_supports_chat": runtime_supports_chat,
        },
        verified=verified,
        requirement_mode="hard",
    )
