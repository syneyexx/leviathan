"""Versioned capability, agent, routing and collaboration contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .taxonomy import (
    CONTRACT_VERSION,
    CapabilityKind,
    CostClass,
    HealthState,
    LatencyClass,
    SideEffectClass,
    normalize_cost,
    normalize_health,
    normalize_kind,
    normalize_latency,
    normalize_side_effect,
)


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def content_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


@dataclass(slots=True)
class UsageMetadata:
    when_to_use: str = ""
    when_not_to_use: str = ""
    requires: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    failure_recovery: str = ""
    preferred_followups: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Any) -> "UsageMetadata":
        data = raw if isinstance(raw, dict) else {}
        return cls(
            when_to_use=str(data.get("when_to_use") or ""),
            when_not_to_use=str(data.get("when_not_to_use") or ""),
            requires=_clean_list(data.get("requires")),
            produces=_clean_list(data.get("produces")),
            failure_recovery=str(data.get("failure_recovery") or ""),
            preferred_followups=_clean_list(data.get("preferred_followups")),
            examples=_clean_list(data.get("examples")),
        )


@dataclass(slots=True)
class CanonicalCapability:
    """Normalized HADES capability record used by routing.

    Security fields are copied from Plugin Runtime contracts; they never
    grant extra authority. ``trusted`` content remains untrusted data.
    """

    canonical_id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    provider_id: str = ""
    plugin_id: str | None = None
    source: str = "plugin"
    version: str = ""
    domains: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    side_effect_class: SideEffectClass = "none"
    cost_class: CostClass = "cheap"
    latency_class: LatencyClass = "fast"
    trust_requirements: str = "manual"
    permissions: list[str] = field(default_factory=list)
    isolation: str = "plugin_cwd"
    health: HealthState = "unknown"
    availability: bool = False
    prerequisites: list[str] = field(default_factory=list)
    required_resources: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    agent_affinity: list[str] = field(default_factory=list)
    preferred_followups: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    content_ref: str = ""
    content_hash: str = ""
    adapter_id: str = ""
    contract_version: int = CONTRACT_VERSION
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["usage"] = self.usage.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "CanonicalCapability":
        kind = normalize_kind(raw.get("kind")) or "tool"
        return cls(
            canonical_id=str(raw.get("canonical_id") or "").strip(),
            kind=kind,
            name=str(raw.get("name") or raw.get("canonical_id") or "").strip(),
            description=str(raw.get("description") or ""),
            provider_id=str(raw.get("provider_id") or raw.get("plugin_id") or ""),
            plugin_id=(str(raw["plugin_id"]) if raw.get("plugin_id") else None),
            source=str(raw.get("source") or "plugin"),
            version=str(raw.get("version") or ""),
            domains=_clean_list(raw.get("domains")),
            intents=_clean_list(raw.get("intents")),
            aliases=_clean_list(raw.get("aliases")),
            input_contract=dict(raw.get("input_contract") or {}) if isinstance(raw.get("input_contract"), dict) else {},
            output_contract=dict(raw.get("output_contract") or {}) if isinstance(raw.get("output_contract"), dict) else {},
            effects=_clean_list(raw.get("effects")),
            side_effect_class=normalize_side_effect(raw.get("side_effect_class")),
            cost_class=normalize_cost(raw.get("cost_class")),
            latency_class=normalize_latency(raw.get("latency_class")),
            trust_requirements=str(raw.get("trust_requirements") or "manual"),
            permissions=_clean_list(raw.get("permissions")),
            isolation=str(raw.get("isolation") or "plugin_cwd"),
            health=normalize_health(raw.get("health")),
            availability=bool(raw.get("availability")),
            prerequisites=_clean_list(raw.get("prerequisites")),
            required_resources=_clean_list(raw.get("required_resources")),
            failure_modes=_clean_list(raw.get("failure_modes")),
            agent_affinity=_clean_list(raw.get("agent_affinity")),
            preferred_followups=_clean_list(raw.get("preferred_followups")),
            produces=_clean_list(raw.get("produces") or (raw.get("usage") or {}).get("produces") if isinstance(raw.get("usage"), dict) else []),
            usage=UsageMetadata.from_mapping(raw.get("usage")),
            content_ref=str(raw.get("content_ref") or ""),
            content_hash=str(raw.get("content_hash") or ""),
            adapter_id=str(raw.get("adapter_id") or ""),
            contract_version=int(raw.get("contract_version") or CONTRACT_VERSION),
            extras=dict(raw.get("extras") or {}) if isinstance(raw.get("extras"), dict) else {},
        )


@dataclass(slots=True)
class AgentContract:
    canonical_id: str
    specialties: list[str] = field(default_factory=list)
    accepts: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    required_context: list[str] = field(default_factory=list)
    allowed_capabilities: list[str] = field(default_factory=list)
    cost_class: CostClass = "moderate"
    latency_class: LatencyClass = "normal"
    trust_requirements: str = "verified"
    collaboration: bool = True
    executable: bool = True
    persona_only: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "AgentContract":
        return cls(
            canonical_id=str(raw.get("canonical_id") or raw.get("id") or "").strip(),
            specialties=_clean_list(raw.get("specialties")),
            accepts=_clean_list(raw.get("accepts") or raw.get("accepted_task_types")),
            produces=_clean_list(raw.get("produces")),
            required_context=_clean_list(raw.get("required_context")),
            allowed_capabilities=_clean_list(raw.get("allowed_capabilities") or raw.get("allowed_tools")),
            cost_class=normalize_cost(raw.get("cost_class")),
            latency_class=normalize_latency(raw.get("latency_class")),
            trust_requirements=str(raw.get("trust_requirements") or raw.get("trust") or "verified"),
            collaboration=bool(raw.get("collaboration", True)),
            executable=bool(raw.get("executable", True)),
            persona_only=bool(raw.get("persona_only", False)),
            extras=dict(raw.get("extras") or {}) if isinstance(raw.get("extras"), dict) else {},
        )


@dataclass(slots=True)
class CapabilityRequirement:
    capability: str
    kind_hint: CapabilityKind | None = None
    optional: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RequirementPlan:
    goal: str
    requirements: list[CapabilityRequirement] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    risk: list[str] = field(default_factory=list)
    verification_required: bool = False
    explicit_providers: list[str] = field(default_factory=list)
    simple: bool = False
    model_adjudication: bool = False
    planner: str = "deterministic"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requirements"] = [item.to_dict() for item in self.requirements]
        return payload


@dataclass(slots=True)
class RankedCandidate:
    capability: CanonicalCapability
    score: float
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    rejected_reason: str | None = None
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.capability.canonical_id,
            "kind": self.capability.kind,
            "name": self.capability.name,
            "provider_id": self.capability.provider_id,
            "plugin_id": self.capability.plugin_id,
            "score": round(self.score, 4),
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "rejected_reason": self.rejected_reason,
            "components": {key: round(value, 4) for key, value in self.components.items()},
            "cost_class": self.capability.cost_class,
            "health": self.capability.health,
            "side_effect_class": self.capability.side_effect_class,
        }


@dataclass(slots=True)
class RoutingDecision:
    selected: list[RankedCandidate] = field(default_factory=list)
    rejected: list[RankedCandidate] = field(default_factory=list)
    considered: int = 0
    model_called: bool = False
    reused_cache: bool = False
    explicit_honored: bool = False
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": [item.to_dict() for item in self.selected],
            "rejected": [item.to_dict() for item in self.rejected],
            "considered": self.considered,
            "model_called": self.model_called,
            "reused_cache": self.reused_cache,
            "explicit_honored": self.explicit_honored,
            "explanation": self.explanation,
        }


@dataclass(slots=True)
class UnsupportedMapping:
    path: str
    claimed_kind: str
    reason: str
    adapter_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AdaptationResult:
    capabilities: list[CanonicalCapability] = field(default_factory=list)
    unsupported: list[UnsupportedMapping] = field(default_factory=list)
    adapters_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": [item.to_dict() for item in self.capabilities],
            "unsupported": [item.to_dict() for item in self.unsupported],
            "adapters_used": list(self.adapters_used),
            "warnings": list(self.warnings),
        }
