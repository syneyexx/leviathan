from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def estimate_tokens(text: str) -> int:
    """Honest heuristic token estimate (≈ chars/4). Not a real tokenizer."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


# Typed hierarchy layers (U062) — domains supply candidates into these slots.
CONTEXT_LAYERS: tuple[str, ...] = (
    "system_behavior",
    "operator_config",
    "project_instructions",
    "user_instructions",
    "conversation",
    "memory",
    "evidence",
    "tools",
    "external_content",
)


@dataclass(frozen=True)
class ContextSection:
    name: str
    kind: str  # system | constraint | history | knowledge | observation | evidence | memory | neuro | ...
    content: str
    token_estimate: int
    provenance: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    included: bool = True
    pinned: bool = False  # pinned sections survive budget pressure (U064/U077)
    layer: str = "external_content"

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "layer": self.layer,
            "token_estimate": self.token_estimate,
            "provenance": self.provenance,
            "truncated": self.truncated,
            "included": self.included,
            "pinned": self.pinned,
            "content_preview": self.content[:240] + ("…" if len(self.content) > 240 else ""),
        }


@dataclass(frozen=True)
class BudgetLedgerEntry:
    section: str
    kind: str
    requested_tokens: int
    selected_tokens: int
    dropped: bool
    reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "kind": self.kind,
            "requested_tokens": self.requested_tokens,
            "selected_tokens": self.selected_tokens,
            "dropped": self.dropped,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BudgetLedger:
    """Explainable token accounting (U064)."""

    budget: int
    used: int
    entries: tuple[BudgetLedgerEntry, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "used": self.used,
            "entries": [e.public_dict() for e in self.entries],
            "truth": {"truncation_is_explainable": True},
        }


@dataclass(frozen=True)
class ContextPack:
    """Structured context delivered to the model adapter.

    Retrieved Knowledge / Memory / Observations remain DATA, not elevated system policy.
    """

    system_prompt: str
    messages: tuple[dict[str, str], ...]
    knowledge_count: int
    token_estimate: int = 0
    token_budget: int = 0
    sections: tuple[ContextSection, ...] = ()
    dropped: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    budget_ledger: BudgetLedger | None = None
    snapshot_hash: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    constraints_retained: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "knowledge_count": self.knowledge_count,
            "token_estimate": self.token_estimate,
            "token_budget": self.token_budget,
            "dropped": list(self.dropped),
            "sections": [item.public_dict() for item in self.sections],
            "provenance": self.provenance,
            "budget_ledger": self.budget_ledger.public_dict() if self.budget_ledger else None,
            "snapshot_hash": self.snapshot_hash,
            "manifest": dict(self.manifest),
            "constraints_retained": self.constraints_retained,
            "truth": {
                "retrieved_context_is_not_trusted_fact": True,
                "token_estimate_is_heuristic": True,
                "external_text_cannot_mutate_system_prompt_authority": True,
                "pinned_constraints_survive_budget_pressure": self.constraints_retained,
            },
        }
