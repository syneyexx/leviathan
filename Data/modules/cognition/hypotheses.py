"""Structured hypotheses for debugging, science, and ambiguous analysis.

Confidence uses qualitative bands — never fake precision like 87.32%.
HypothesisBoard is the run-owned public hypothesis set (not private CoT).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


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
    domain: str = "general"
    parent_id: str | None = None
    branch_ids: list[str] = field(default_factory=list)
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
            "domain": self.domain,
            "parent_id": self.parent_id,
            "branch_ids": list(self.branch_ids),
            "metadata": dict(self.metadata),
            "truth": {
                "confidence_band_is_not_precise_probability": True,
                "hypothesis_is_not_fact": True,
                "not_private_cot": True,
            },
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "Hypothesis | None":
        if not isinstance(raw, Mapping):
            return None
        statement = str(raw.get("statement") or "").strip()
        if not statement:
            return None
        try:
            status = HypothesisStatus(str(raw.get("current_status") or "OPEN").upper())
        except ValueError:
            status = HypothesisStatus.OPEN
        try:
            band = ConfidenceBand(str(raw.get("confidence_band") or "moderate").lower())
        except ValueError:
            band = ConfidenceBand.MODERATE
        try:
            prior = float(raw.get("prior_plausibility") or 0.5)
        except (TypeError, ValueError):
            prior = 0.5
        return cls(
            hypothesis_id=str(raw.get("hypothesis_id") or uuid.uuid4()),
            statement=statement[:500],
            prior_plausibility=max(0.0, min(1.0, prior)),
            supporting_evidence_ids=[str(x) for x in (raw.get("supporting_evidence_ids") or []) if x][:32],
            contradicting_evidence_ids=[
                str(x) for x in (raw.get("contradicting_evidence_ids") or []) if x
            ][:32],
            tests=[str(x) for x in (raw.get("tests") or []) if x][:16],
            observations=[str(x) for x in (raw.get("observations") or []) if x][:32],
            current_status=status,
            confidence_band=band,
            belief_id=str(raw["belief_id"]) if raw.get("belief_id") else None,
            domain=str(raw.get("domain") or "general"),
            parent_id=str(raw["parent_id"]) if raw.get("parent_id") else None,
            branch_ids=[str(x) for x in (raw.get("branch_ids") or []) if x][:16],
            metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
        )

    def apply_evidence(self, evidence_id: str, *, supports: bool) -> None:
        if supports:
            if evidence_id not in self.supporting_evidence_ids:
                self.supporting_evidence_ids.append(evidence_id)
        elif evidence_id not in self.contradicting_evidence_ids:
            self.contradicting_evidence_ids.append(evidence_id)
        self._recompute_status()

    def note_observation(self, summary: str) -> None:
        text = (summary or "").strip()
        if not text:
            return
        preview = text if len(text) <= 200 else text[:199] + "…"
        if preview not in self.observations:
            self.observations.append(preview)
            if len(self.observations) > 32:
                self.observations = self.observations[-32:]

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
    """Active hypothesis set for a cognitive run — deep-branched, public."""

    items: dict[str, Hypothesis] = field(default_factory=dict)

    def add(
        self,
        statement: str,
        *,
        prior_plausibility: float = 0.5,
        tests: list[str] | None = None,
        belief_id: str | None = None,
        domain: str = "general",
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Hypothesis:
        text = (statement or "").strip()
        # Deduplicate identical open statements.
        for existing in self.items.values():
            if (
                existing.statement.lower() == text.lower()
                and existing.current_status
                in {
                    HypothesisStatus.OPEN,
                    HypothesisStatus.WEAKENED,
                    HypothesisStatus.UNRESOLVED,
                }
            ):
                return existing
        hyp = Hypothesis(
            hypothesis_id=str(uuid.uuid4()),
            statement=text[:500],
            prior_plausibility=max(0.0, min(1.0, float(prior_plausibility))),
            tests=list(tests or []),
            confidence_band=confidence_to_band(prior_plausibility),
            belief_id=belief_id,
            domain=domain or "general",
            parent_id=parent_id,
            metadata=dict(metadata or {}),
        )
        self.items[hyp.hypothesis_id] = hyp
        if parent_id and parent_id in self.items:
            parent = self.items[parent_id]
            if hyp.hypothesis_id not in parent.branch_ids:
                parent.branch_ids.append(hyp.hypothesis_id)
        return hyp

    def branch(
        self,
        parent_id: str,
        statement: str,
        *,
        prior_plausibility: float = 0.45,
        domain: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Hypothesis | None:
        parent = self.items.get(parent_id)
        if parent is None:
            return None
        return self.add(
            statement,
            prior_plausibility=prior_plausibility,
            domain=domain or parent.domain,
            parent_id=parent_id,
            metadata={**(metadata or {}), "branched_from": parent_id},
        )

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        return self.items.get(hypothesis_id)

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

    def apply_observation_evidence(
        self,
        *,
        observation_id: str,
        summary: str,
        success: bool | None,
        evidence_refs: Sequence[str] | None = None,
    ) -> list[str]:
        """Link observation/evidence to open hypotheses (heuristic support/contradict)."""
        touched: list[str] = []
        refs = [observation_id, *[str(r) for r in (evidence_refs or []) if r]]
        summary_l = (summary or "").lower()
        for hyp in self.open_items():
            hyp.note_observation(summary)
            # Weak lexical overlap → soft support; explicit failure weakens.
            stmt_tokens = {t for t in hyp.statement.lower().split() if len(t) > 3}
            overlap = stmt_tokens.intersection(set(summary_l.split())) if stmt_tokens else set()
            supports = success is not False and len(overlap) >= max(1, min(2, len(stmt_tokens) // 4))
            contradicts = success is False and bool(overlap)
            if supports or contradicts:
                for ref in refs[:3]:
                    hyp.apply_evidence(ref, supports=supports and not contradicts)
                touched.append(hyp.hypothesis_id)
        return touched

    def seed_from_task(
        self,
        *,
        assumptions: Sequence[str] | None = None,
        unknowns: Sequence[str] | None = None,
        domain: str = "general",
    ) -> list[Hypothesis]:
        created: list[Hypothesis] = []
        for assumption in assumptions or []:
            text = (assumption or "").strip()
            if text:
                created.append(
                    self.add(
                        text,
                        prior_plausibility=0.4,
                        domain=domain,
                        metadata={"source": "task_assumption"},
                    )
                )
        for unknown in unknowns or []:
            text = (unknown or "").strip()
            if text:
                created.append(
                    self.add(
                        f"Unresolved: {text}",
                        prior_plausibility=0.35,
                        domain=domain,
                        tests=[f"resolve:{text[:80]}"],
                        metadata={"source": "task_unknown"},
                    )
                )
        return created

    def public_dict(self) -> dict[str, Any]:
        items = list(self.items.values())
        return {
            "items": [h.public_dict() for h in items],
            "open_count": len(self.open_items()),
            "supported_count": sum(
                1 for h in items if h.current_status == HypothesisStatus.SUPPORTED
            ),
            "rejected_count": sum(
                1 for h in items if h.current_status == HypothesisStatus.REJECTED
            ),
            "branch_count": sum(1 for h in items if h.parent_id),
            "truth": {
                "hypothesis_board_is_public": True,
                "not_private_cot": True,
                "deep_branched": True,
            },
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "HypothesisBoard":
        board = cls()
        if not isinstance(raw, Mapping):
            return board
        for item in raw.get("items") or []:
            hyp = Hypothesis.from_public_dict(item if isinstance(item, Mapping) else None)
            if hyp is not None:
                board.items[hyp.hypothesis_id] = hyp
        return board


def hypothesis_board_from_mapping(raw: Mapping[str, Any] | None) -> HypothesisBoard:
    return HypothesisBoard.from_public_dict(raw)
