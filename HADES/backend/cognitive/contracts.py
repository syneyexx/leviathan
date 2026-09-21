"""Shared cognitive contracts — observability without private chain-of-thought."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4


CONTROLLER_VERSION = "cognitive.v1"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


# Capability status tiers — never infer from import success alone.
CAPABILITY_STATUSES = frozenset(
    {
        "implemented",
        "available",
        "verified",
        "operationally_tested",
        "degraded",
        "unsupported",
        "unknown",
        "unverified_on_host",
    }
)

UNCERTAINTY_CLASSES = frozenset(
    {
        "missing_information",
        "conflicting_evidence",
        "stale_evidence",
        "ambiguous_goal",
        "low_model_confidence",
        "unknown_runtime_state",
        "unverified_assumption",
        "out_of_distribution",
        "simulation_gap",
        "tool_failure",
        "insufficient_coverage",
    }
)

TRUST_CATEGORIES = frozenset(
    {
        "verified_local",
        "verified_external",
        "trusted_source",
        "untrusted_source",
        "model_generated",
        "user_provided",
        "tool_generated",
        "derived_inference",
        "quarantined",
    }
)

CAUSAL_EVIDENCE_TIERS = frozenset(
    {
        "coincidental",  # occurred earlier — not causal
        "correlated",
        "intervened",  # controlled A/B or intervention
        "verified_cause",  # domain proof (test failure → fix → pass)
        "counterfactual",  # counterfactual evidence available
    }
)


@dataclass
class AdaptiveDecision:
    """Compact observable adaptive decision metadata (never private CoT)."""

    controller: str
    decision: str
    reason_code: str
    version: str = CONTROLLER_VERSION
    input_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    fallback: str | None = None
    verification_result: str | None = None
    mode: str = "shadow"
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityEntry:
    """One evidence-backed capability/component in the machine self-model."""

    component: str
    capability: str
    status: str
    implemented: bool = False
    available: bool = False
    verified: bool = False
    operationally_tested: bool = False
    degraded: bool = False
    unsupported: bool = False
    version: str | None = None
    dependencies: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    last_success: str | None = None
    last_failure: str | None = None
    confidence: float | None = None
    notes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = str(self.status or "unknown").lower()
        if status not in CAPABILITY_STATUSES:
            status = "unknown"
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UncertaintyState:
    """Typed uncertainty — drives recovery action, not a vague confidence float."""

    uncertainty_class: str
    detail: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    recovery_action: str = ""
    severity: str = "medium"  # low | medium | high | critical
    ask_user: bool = False

    def __post_init__(self) -> None:
        cls = str(self.uncertainty_class or "").lower()
        if cls not in UNCERTAINTY_CLASSES:
            cls = "missing_information"
        self.uncertainty_class = cls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mapping_get(raw: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(raw, Mapping):
        return default
    cur: Any = raw
    for key in keys:
        if not isinstance(cur, Mapping) or key not in cur:
            return default
        cur = cur[key]
    return cur
