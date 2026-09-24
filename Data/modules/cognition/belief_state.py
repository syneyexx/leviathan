"""BeliefState — structured epistemic state (not private CoT)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .types import BeliefCategory, BeliefStatus, EpistemicType


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def confidence_band(confidence: float) -> str:
    c = max(0.0, min(1.0, float(confidence)))
    if c < 0.35:
        return "weak"
    if c < 0.6:
        return "moderate"
    if c < 0.85:
        return "strong"
    return "very_strong"


@dataclass
class BeliefItem:
    belief_id: str
    proposition: str
    category: BeliefCategory
    confidence: float
    support_refs: list[str] = field(default_factory=list)
    contradiction_refs: list[str] = field(default_factory=list)
    source_type: EpistemicType = EpistemicType.HYPOTHESIS
    status: BeliefStatus = BeliefStatus.UNVERIFIED
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    next_information_needed: str | None = None
    freshness: str | None = None  # fresh | aging | stale | unknown
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    def public_dict(self) -> dict[str, Any]:
        return {
            "belief_id": self.belief_id,
            "proposition": self.proposition,
            "category": self.category.value,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band,
            "support_refs": list(self.support_refs),
            "contradiction_refs": list(self.contradiction_refs),
            "source_type": self.source_type.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_information_needed": self.next_information_needed,
            "freshness": self.freshness,
            "provenance": dict(self.provenance),
            "metadata": self.metadata,
            "truth": {
                "neural_association_is_not_exact_fact": True,
                "model_inference_is_not_evidence": True,
                "confidence_band_is_not_precise_probability": True,
            },
        }


@dataclass
class BeliefState:
    """Canonical belief store for an active cognitive run."""

    items: dict[str, BeliefItem] = field(default_factory=dict)
    contradiction_pairs: list[tuple[str, str]] = field(default_factory=list)

    def add(
        self,
        proposition: str,
        *,
        category: BeliefCategory = BeliefCategory.HYPOTHESIS,
        confidence: float = 0.5,
        source_type: EpistemicType = EpistemicType.HYPOTHESIS,
        status: BeliefStatus = BeliefStatus.UNVERIFIED,
        support_refs: list[str] | None = None,
        next_information_needed: str | None = None,
        freshness: str | None = None,
        provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BeliefItem:
        conf = max(0.0, min(1.0, float(confidence)))
        # Exact facts / evidence cannot be silently created from neural associations.
        if source_type == EpistemicType.NEURAL_ASSOCIATION and category == BeliefCategory.FACT:
            category = BeliefCategory.HYPOTHESIS
            status = BeliefStatus.INFERRED
            conf = min(conf, 0.55)
        # Model speculation must never silently become FACT.
        if source_type == EpistemicType.MODEL_INFERENCE and category == BeliefCategory.FACT:
            category = BeliefCategory.HYPOTHESIS
            status = BeliefStatus.INFERRED
            conf = min(conf, 0.55)
        item = BeliefItem(
            belief_id=str(uuid.uuid4()),
            proposition=proposition.strip(),
            category=category,
            confidence=conf,
            support_refs=list(support_refs or []),
            source_type=source_type,
            status=status,
            next_information_needed=next_information_needed,
            freshness=freshness,
            provenance=dict(provenance or {}),
            metadata=dict(metadata or {}),
        )
        self.items[item.belief_id] = item
        return item

    def get(self, belief_id: str) -> BeliefItem | None:
        return self.items.get(belief_id)

    def revise(
        self,
        belief_id: str,
        *,
        confidence: float | None = None,
        status: BeliefStatus | None = None,
        add_support: list[str] | None = None,
        add_contradiction: list[str] | None = None,
        next_information_needed: str | None = None,
    ) -> BeliefItem | None:
        item = self.items.get(belief_id)
        if item is None:
            return None
        if confidence is not None:
            item.confidence = max(0.0, min(1.0, float(confidence)))
        if status is not None:
            item.status = status
        if add_support:
            for ref in add_support:
                if ref not in item.support_refs:
                    item.support_refs.append(ref)
        if add_contradiction:
            for ref in add_contradiction:
                if ref not in item.contradiction_refs:
                    item.contradiction_refs.append(ref)
            if item.contradiction_refs and item.status not in {
                BeliefStatus.CONTRADICTED,
                BeliefStatus.REJECTED,
            }:
                item.status = BeliefStatus.CONTRADICTED
                item.confidence = min(item.confidence, 0.4)
        if next_information_needed is not None:
            item.next_information_needed = next_information_needed
        item.updated_at = _now()
        return item

    def reject(self, belief_id: str, *, reason: str | None = None) -> BeliefItem | None:
        item = self.revise(belief_id, status=BeliefStatus.REJECTED, confidence=0.0)
        if item is not None and reason:
            item.metadata["reject_reason"] = reason
            item.updated_at = _now()
        return item

    def record_contradiction(self, belief_a: str, belief_b: str) -> None:
        if belief_a not in self.items or belief_b not in self.items:
            return
        pair = tuple(sorted((belief_a, belief_b)))
        if pair not in self.contradiction_pairs:
            self.contradiction_pairs.append(pair)  # type: ignore[arg-type]
        self.revise(belief_a, add_contradiction=[belief_b])
        self.revise(belief_b, add_contradiction=[belief_a])

    def apply_observation_support(
        self,
        belief_id: str,
        *,
        observation_id: str,
        supports: bool,
        delta: float = 0.12,
    ) -> BeliefItem | None:
        item = self.items.get(belief_id)
        if item is None:
            return None
        if supports:
            new_conf = min(1.0, item.confidence + delta)
            status = (
                BeliefStatus.SUPPORTED
                if new_conf >= 0.75
                else BeliefStatus.PARTIALLY_SUPPORTED
            )
            return self.revise(
                belief_id,
                confidence=new_conf,
                status=status,
                add_support=[observation_id],
            )
        new_conf = max(0.0, item.confidence - delta)
        return self.revise(
            belief_id,
            confidence=new_conf,
            status=BeliefStatus.CONTRADICTED if new_conf < 0.35 else item.status,
            add_contradiction=[observation_id],
        )

    def uncertainty(self) -> float:
        if not self.items:
            return 0.5
        open_items = [
            i
            for i in self.items.values()
            if i.status
            in {
                BeliefStatus.UNVERIFIED,
                BeliefStatus.INFERRED,
                BeliefStatus.PARTIALLY_SUPPORTED,
                BeliefStatus.CONTRADICTED,
            }
            and i.category != BeliefCategory.FACT
        ]
        if not open_items:
            return 0.15
        avg_conf = sum(i.confidence for i in open_items) / len(open_items)
        contradiction_penalty = min(0.3, 0.08 * len(self.contradiction_pairs))
        return round(max(0.0, min(1.0, (1.0 - avg_conf) + contradiction_penalty)), 3)

    def counts(self) -> dict[str, int]:
        by_status: dict[str, int] = {}
        for item in self.items.values():
            by_status[item.status.value] = by_status.get(item.status.value, 0) + 1
        return {
            "total": len(self.items),
            "contradictions": len(self.contradiction_pairs),
            **by_status,
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [i.public_dict() for i in self.items.values()],
            "contradiction_pairs": [list(p) for p in self.contradiction_pairs],
            "counts": self.counts(),
            "uncertainty": self.uncertainty(),
        }

    def snapshot_for_context(self, *, limit: int = 12) -> list[dict[str, Any]]:
        ranked = sorted(
            self.items.values(),
            key=lambda i: (
                0 if i.status == BeliefStatus.CONTRADICTED else 1,
                -i.confidence,
                i.updated_at,
            ),
        )
        return [i.public_dict() for i in ranked[:limit]]
