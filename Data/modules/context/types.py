from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def estimate_tokens(text: str) -> int:
    """Honest heuristic token estimate (≈ chars/4). Not a real tokenizer."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class ContextSection:
    name: str
    kind: str  # system | history | knowledge | observation | evidence | memory | neuro | constraint
    content: str
    token_estimate: int
    provenance: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    included: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "token_estimate": self.token_estimate,
            "provenance": self.provenance,
            "truncated": self.truncated,
            "included": self.included,
            "content_preview": self.content[:240] + ("…" if len(self.content) > 240 else ""),
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

    def public_dict(self) -> dict[str, Any]:
        return {
            "knowledge_count": self.knowledge_count,
            "token_estimate": self.token_estimate,
            "token_budget": self.token_budget,
            "dropped": list(self.dropped),
            "sections": [item.public_dict() for item in self.sections],
            "provenance": self.provenance,
            "truth": {
                "retrieved_context_is_not_trusted_fact": True,
                "token_estimate_is_heuristic": True,
            },
        }
