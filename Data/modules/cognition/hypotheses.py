"""Structured hypotheses for debugging, science, and ambiguous analysis.

Confidence uses qualitative bands — never fake precision like 87.32%.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HypothesisStatus(str, Enum):
    OPEN = "OPEN"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class ConfidenceBand(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


def confidence_to_band(confidence: float) -> ConfidenceBand:
    c = max(0.0, min(1.0, float(confidence)))
    if c < 0.35:
        return ConfidenceBand.WEAK
    if c < 0.6:
        return ConfidenceBand.MODERATE
    if c < 0.85:
        return ConfidenceBand.STRONG
    return ConfidenceBand.VERY_STRONG


@dataclass
class Hypothesis:
    """Explicit testable hypothesis — not private chain-of-thought."""

    hypothesis_id: str
    statement: str
    prior_plausibility: float = 0.5
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    current_status: HypothesisStatus = HypothesisStatus.OPEN
    confidence_band: ConfidenceBand = ConfidenceBand.MODERATE
    belief_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "prior_plausibility": self.prior_plausibility,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "tests": list(self.tests),
            "observations": list(self.observations),
            "current_status": self.current_status.value,
            "confidence_band": self.confidence_band.value,
            "belief_id": self.belief_id,
            "metadata": dict(self.metadata),
            "truth": {
                "confidence_band_is_not_precise_probability": True,
                "hypothesis_is_not_fact": True,
            },
        }

    def apply_evidence(self, evidence_id: str, *, supports: bool) -> None:
        if supports:
            if evidence_id not in self.supporting_evidence_ids:
                self.supporting_evidence_ids.append(evidence_id)
        elif evidence_id not in self.contradicting_evidence_ids:
            self.contradicting_evidence_ids.append(evidence_id)
        self._recompute_status()

    def _recompute_status(self) -> None:
        s = len(self.supporting_evidence_ids)
        c = len(self.contradicting_evidence_ids)
        if c > 0 and s == 0:
            self.current_status = HypothesisStatus.REJECTED
            self.confidence_band = ConfidenceBand.WEAK
        elif c > s:
            self.current_status = HypothesisStatus.WEAKENED
            self.confidence_band = ConfidenceBand.WEAK
        elif s >= 2 and c == 0:
            self.current_status = HypothesisStatus.SUPPORTED
            self.confidence_band = ConfidenceBand.STRONG if s >= 3 else ConfidenceBand.MODERATE
        elif s >= 1 and c >= 1:
            self.current_status = HypothesisStatus.UNRESOLVED
            self.confidence_band = ConfidenceBand.WEAK
        else:
            self.current_status = HypothesisStatus.OPEN
            self.confidence_band = confidence_to_band(self.prior_plausibility)


@dataclass
class HypothesisBoard:
    """Active hypothesis set for a cognitive run."""

    items: dict[str, Hypothesis] = field(default_factory=dict)

    def add(
        self,
        statement: str,
        *,
        prior_plausibility: float = 0.5,
        tests: list[str] | None = None,
        belief_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Hypothesis:
        hyp = Hypothesis(
            hypothesis_id=str(uuid.uuid4()),
            statement=statement.strip(),
            prior_plausibility=max(0.0, min(1.0, float(prior_plausibility))),
            tests=list(tests or []),
            confidence_band=confidence_to_band(prior_plausibility),
            belief_id=belief_id,
            metadata=dict(metadata or {}),
        )
        self.items[hyp.hypothesis_id] = hyp
        return hyp

    def open_items(self) -> list[Hypothesis]:
        return [
            h
            for h in self.items.values()
            if h.current_status
            in {
                HypothesisStatus.OPEN,
                HypothesisStatus.WEAKENED,
                HypothesisStatus.UNRESOLVED,
            }
        ]

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [h.public_dict() for h in self.items.values()],
            "open_count": len(self.open_items()),
        }
