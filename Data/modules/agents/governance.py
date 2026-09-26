"""Delegation governance — recursion, authority, and budget ceilings (W9).

HARD RULES:
- Child authority <= parent authority
- Child compute budget comes from remaining parent budget
- No Cognition → Agent → Cognition → equivalent Agent infinite recursion
- Cycle detection on the specialist/agent lineage stack
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class DelegationViolation(str, Enum):
    DEPTH_EXCEEDED = "DEPTH_EXCEEDED"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    AUTHORITY_ESCALATION = "AUTHORITY_ESCALATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INVALID_FRAME = "INVALID_FRAME"


# Rank for RiskClass / authority ceilings — higher = more privileged.
AUTHORITY_RANK: dict[str, int] = {
    "NONE": 0,
    "LOW": 10,
    "MEDIUM": 20,
    "HIGH": 30,
    "CRITICAL": 40,
    "OPERATOR": 50,
}


@dataclass(frozen=True)
class DelegationFrame:
    """One bounded delegation hop — parent owns the child budget."""

    parent_run_id: str
    child_id: str
    agent_kind: str
    delegation_depth: int
    max_delegation_depth: int
    parent_authority: str
    child_authority: str
    remaining_parent_budget: dict[str, Any]
    child_budget: dict[str, Any]
    lineage: tuple[str, ...] = ()
    conversation_id: str | None = None
    memory_scope: str = "AGENT_PRIVATE"
    shared_orchestrator_scope: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "parent_run_id": self.parent_run_id,
            "child_id": self.child_id,
            "agent_kind": self.agent_kind,
            "delegation_depth": self.delegation_depth,
            "max_delegation_depth": self.max_delegation_depth,
            "parent_authority": self.parent_authority,
            "child_authority": self.child_authority,
            "remaining_parent_budget": dict(self.remaining_parent_budget),
            "child_budget": dict(self.child_budget),
            "lineage": list(self.lineage),
            "conversation_id": self.conversation_id,
            "memory_scope": self.memory_scope,
            "shared_orchestrator_scope": self.shared_orchestrator_scope,
            "truth": {
                "child_authority_le_parent": authority_rank(self.child_authority)
                <= authority_rank(self.parent_authority),
                "child_budget_from_parent": True,
                "no_hidden_recursion": True,
            },
        }


@dataclass
class GovernanceDecision:
    allowed: bool
    frame: DelegationFrame | None = None
    violation: DelegationViolation | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "frame": self.frame.public_dict() if self.frame else None,
            "violation": self.violation.value if self.violation else None,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


def authority_rank(raw: str | None) -> int:
    key = str(raw or "MEDIUM").strip().upper()
    if key in AUTHORITY_RANK:
        return AUTHORITY_RANK[key]
    # Unknown ceilings treated as MEDIUM — never escalate silently.
    return AUTHORITY_RANK["MEDIUM"]


def clamp_authority(requested: str | None, parent: str | None) -> str:
    """Child authority must never exceed parent."""
    parent_key = str(parent or "MEDIUM").strip().upper()
    req_key = str(requested or parent_key).strip().upper()
    if authority_rank(req_key) <= authority_rank(parent_key):
        return req_key if req_key in AUTHORITY_RANK else parent_key
    return parent_key if parent_key in AUTHORITY_RANK else "MEDIUM"


def split_budget(
    remaining_parent: Mapping[str, Any] | None,
    *,
    fraction: float = 0.5,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive child budget from remaining parent budget (never invents new quota)."""
    parent = dict(remaining_parent or {})
    child: dict[str, Any] = {}
    frac = max(0.0, min(1.0, float(fraction)))
    for key, value in parent.items():
        if isinstance(value, bool):
            child[key] = value
            continue
        if isinstance(value, (int, float)):
            # Integers stay integers; never round up above parent remaining.
            scaled = value * frac
            child[key] = int(scaled) if isinstance(value, int) else scaled
            if isinstance(value, int) and child[key] > value:
                child[key] = value
            if isinstance(value, int) and value > 0 and child[key] < 1 and frac > 0:
                child[key] = 1 if value >= 1 else 0
            continue
        child[key] = value
    if overrides:
        for key, value in overrides.items():
            if key not in parent:
                continue  # cannot invent parent-unknown budget keys as escalation
            parent_val = parent[key]
            if isinstance(parent_val, (int, float)) and isinstance(value, (int, float)):
                child[key] = type(parent_val)(min(parent_val, value))
            else:
                child[key] = value
    return child


def detect_cycle(lineage: Sequence[str], next_kind: str) -> list[str] | None:
    """Return cycle path if next_kind already appears in lineage (same specialist re-entry)."""
    token = str(next_kind or "").strip().lower()
    if not token:
        return None
    normalized = [str(x).strip().lower() for x in lineage if str(x).strip()]
    if token in normalized:
        idx = normalized.index(token)
        return normalized[idx:] + [token]
    return None


class DelegationGovernor:
    """Authorize and record bounded agent/cognition delegation hops."""

    DEFAULT_MAX_DEPTH = 3

    def __init__(self, *, default_max_depth: int = DEFAULT_MAX_DEPTH) -> None:
        self.default_max_depth = max(1, min(16, int(default_max_depth)))
        self._open: dict[str, DelegationFrame] = {}

    def authorize(
        self,
        *,
        parent_run_id: str,
        agent_kind: str,
        child_id: str | None = None,
        parent_authority: str = "MEDIUM",
        requested_authority: str | None = None,
        delegation_depth: int = 0,
        max_delegation_depth: int | None = None,
        remaining_parent_budget: Mapping[str, Any] | None = None,
        budget_fraction: float = 0.5,
        budget_overrides: Mapping[str, Any] | None = None,
        lineage: Sequence[str] | None = None,
        conversation_id: str | None = None,
        memory_scope: str = "AGENT_PRIVATE",
        shared_orchestrator_scope: str | None = None,
    ) -> GovernanceDecision:
        max_depth = int(max_delegation_depth if max_delegation_depth is not None else self.default_max_depth)
        max_depth = max(1, min(16, max_depth))
        depth = max(0, int(delegation_depth))
        kind = str(agent_kind or "generic").strip().lower() or "generic"
        stack = tuple(str(x).strip().lower() for x in (lineage or ()) if str(x).strip())

        if depth >= max_depth:
            return GovernanceDecision(
                allowed=False,
                violation=DelegationViolation.DEPTH_EXCEEDED,
                reason=f"delegation_depth {depth} >= max_delegation_depth {max_depth}",
                metadata={"delegation_depth": depth, "max_delegation_depth": max_depth},
            )

        cycle = detect_cycle(stack, kind)
        if cycle is not None:
            return GovernanceDecision(
                allowed=False,
                violation=DelegationViolation.CYCLE_DETECTED,
                reason=f"cycle detected: {' -> '.join(cycle)}",
                metadata={"cycle": cycle, "lineage": list(stack)},
            )

        if authority_rank(requested_authority) > authority_rank(parent_authority):
            # Clamp rather than hard-fail when request asks higher — refuse escalation attempt.
            # Hard refuse when metadata explicitly marks escalate=true is handled by callers;
            # here we always clamp for the frame and flag the attempt.
            clamped = clamp_authority(requested_authority, parent_authority)
            escalation_attempt = True
        else:
            clamped = clamp_authority(requested_authority, parent_authority)
            escalation_attempt = False

        parent_budget = dict(remaining_parent_budget or {})
        # Exhaustion only when explicit capacity quotas are present and all depleted.
        # A lone sentinel like {iterations: 0} (no MetaDecision yet) is NOT exhausted.
        capacity_keys = (
            "agent_delegations",
            "model_calls",
            "tool_calls",
            "slots",
            "max_tool_calls",
            "max_model_calls",
            "max_agent_delegations",
        )
        caps = [
            float(parent_budget[k])
            for k in capacity_keys
            if k in parent_budget and isinstance(parent_budget[k], (int, float))
        ]
        if caps and all(v <= 0 for v in caps):
            return GovernanceDecision(
                allowed=False,
                violation=DelegationViolation.BUDGET_EXHAUSTED,
                reason="remaining_parent_budget exhausted",
                metadata={"remaining_parent_budget": parent_budget},
            )

        child_budget = split_budget(parent_budget, fraction=budget_fraction, overrides=budget_overrides)
        cid = child_id or f"{kind}:{depth + 1}"
        frame = DelegationFrame(
            parent_run_id=str(parent_run_id or ""),
            child_id=cid,
            agent_kind=kind,
            delegation_depth=depth + 1,
            max_delegation_depth=max_depth,
            parent_authority=str(parent_authority or "MEDIUM").upper(),
            child_authority=clamped,
            remaining_parent_budget=parent_budget,
            child_budget=child_budget,
            lineage=stack + (kind,),
            conversation_id=conversation_id,
            memory_scope=memory_scope,
            shared_orchestrator_scope=shared_orchestrator_scope,
        )
        self._open[cid] = frame
        decision = GovernanceDecision(
            allowed=True,
            frame=frame,
            reason="authorized" if not escalation_attempt else "authorized_authority_clamped",
            metadata={
                "authority_clamped": escalation_attempt,
                "requested_authority": requested_authority,
            },
        )
        if escalation_attempt:
            decision.metadata["violation_noted"] = DelegationViolation.AUTHORITY_ESCALATION.value
        return decision

    def close(self, child_id: str) -> None:
        self._open.pop(child_id, None)

    def open_frames(self) -> list[DelegationFrame]:
        return list(self._open.values())
