"""Canonical One Brain contracts. Reuse Capability Intelligence types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from capability_intel.contracts import (
    AgentContract,
    CanonicalCapability,
    RankedCandidate,
    RequirementPlan,
    RoutingDecision,
)
from capability_intel.taxonomy import MESSAGE_TYPES, NATIVE_PROVIDER_ID

from .traits import TRAIT_NAMES, infer_traits, normalize_traits

DomainId = Literal["chat", "work", "coding", "trading", "media", "research", "plugins", "mcp", "generic"]

REF_KINDS: tuple[str, ...] = (
    "artifact_ref",
    "evidence_ref",
    "file_ref",
    "dataset_ref",
    "run_ref",
    "summary_ref",
)

MARKETPLACE_STATES: tuple[str, ...] = (
    "available",
    "degraded",
    "unavailable",
    "auth_required",
    "needs_setup",
    "policy_blocked",
    "unknown",
)


@dataclass(slots=True)
class ContentRef:
    kind: str
    value: str
    summary: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.kind not in REF_KINDS:
            payload["unknown_ref_kind"] = True
        return payload


@dataclass(slots=True)
class CanonicalAgent:
    """Shared agent protocol. Domain roles remain domain roles."""

    identity: str
    responsibility: str
    domain: str = "generic"
    role_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    context_requirements: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    model_preferences: dict[str, Any] = field(default_factory=dict)
    budgets: dict[str, int] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    recovery: str = ""
    authority_limits: list[str] = field(default_factory=list)
    contract: AgentContract | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract"] = self.contract.to_dict() if self.contract else None
        return payload


@dataclass(slots=True)
class Claim:
    claim_id: str
    text: str
    domain: str = "generic"
    confidence: str = "unknown"
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Evidence:
    evidence_id: str
    kind: str
    provenance: str
    status: str = "recorded"
    ref: str = ""
    summary: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationOutcome:
    status: str
    proof_kind: str
    deterministic: bool
    verifier_model_called: bool = False
    claims: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def attach_traits(record: CanonicalCapability) -> CanonicalCapability:
    declared = list(getattr(record, "traits", None) or []) or list(record.extras.get("traits") or [])
    traits = infer_traits(
        kind=record.kind,
        side_effect_class=record.side_effect_class,
        extras=record.extras,
        declared=declared,
    )
    record.extras["traits"] = traits
    if hasattr(record, "traits"):
        record.traits = traits  # type: ignore[attr-defined]
    return record


__all__ = [
    "AgentContract",
    "CanonicalAgent",
    "CanonicalCapability",
    "Claim",
    "ContentRef",
    "DomainId",
    "Evidence",
    "MARKETPLACE_STATES",
    "MESSAGE_TYPES",
    "NATIVE_PROVIDER_ID",
    "REF_KINDS",
    "RankedCandidate",
    "RequirementPlan",
    "RoutingDecision",
    "TRAIT_NAMES",
    "VerificationOutcome",
    "attach_traits",
    "normalize_traits",
]
