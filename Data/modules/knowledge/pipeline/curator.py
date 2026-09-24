"""Semantic placement seam — routes artifacts to existing authoritative owners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifact import KnowledgeArtifact


@dataclass
class PlacementDecision:
    destination: str
    reason: str
    use_main_llm: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "reason": self.reason,
            "use_main_llm": self.use_main_llm,
        }


class KnowledgeCurator:
    """Deterministic rules first; specialist/small model only when ambiguous."""

    DESTINATIONS = (
        "knowledge_store",
        "research_evidence",
        "atlas",
        "reject",
        "hold_disputed",
    )

    def place(self, artifact: KnowledgeArtifact) -> PlacementDecision:
        flags = set(artifact.security_flags or [])
        if "secret" in flags or "credential" in flags:
            return PlacementDecision(destination="reject", reason="security_flag")
        if artifact.uncertainty and "disputed" in (artifact.uncertainty or "").lower():
            return PlacementDecision(destination="hold_disputed", reason="uncertainty_disputed")
        suggested = list(artifact.suggested_destinations or [])
        if "atlas" in suggested:
            return PlacementDecision(destination="atlas", reason="suggested_atlas")
        if artifact.domain == "research" and not suggested:
            # Research goes through assimilation gates, not raw dump
            return PlacementDecision(destination="knowledge_store", reason="research_via_assimilation")
        if artifact.confidence is not None and artifact.confidence < 0.4:
            return PlacementDecision(destination="hold_disputed", reason="low_confidence")
        # Ambiguous high-value: signal that Tier 3 may be needed — caller decides.
        if not artifact.topics and not artifact.claims and (artifact.summary or "").strip() == "":
            return PlacementDecision(
                destination="knowledge_store",
                reason="ambiguous_sparse_artifact",
                use_main_llm=True,
            )
        return PlacementDecision(destination="knowledge_store", reason="default_canonical")
