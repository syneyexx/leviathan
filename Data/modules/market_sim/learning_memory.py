"""Durable learning memory contract shared across Research / Agents / MarketSim / Brain.

Maps cleanly onto existing LessonTrust / epistemic states. Does not persist
chain-of-thought. Negative evidence is retained. Semantic dedupe is conservative.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LearningEpistemicState(str, Enum):
    """Canonical learning epistemic states.

    Compatibility map (existing → canonical):
      AGENT_PROPOSED / PROPOSED → PROPOSED
      OBSERVED / PAPER_OBSERVED → OBSERVED
      MEASURED / TRAIN_ADAPTIVE → MEASURED
      REPLICATED → REPLICATED
      VERIFIED / VALIDATED → VERIFIED
      REJECTED → REJECTED
      SUPERSEDED / SEALED (audit sink, not adaptive) → SUPERSEDED
    """

    PROPOSED = "PROPOSED"
    OBSERVED = "OBSERVED"
    MEASURED = "MEASURED"
    REPLICATED = "REPLICATED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# Public alias used by Wave 6 tests / docs.
EpistemicState = LearningEpistemicState

_COT_KEYS = frozenset(
    {
        "chain_of_thought",
        "chainOfThought",
        "cot",
        "scratchpad",
        "private_reasoning",
        "privateReasoning",
        "hidden_rationale",
    }
)

_ALLOWED_TRANSITIONS: dict[LearningEpistemicState, frozenset[LearningEpistemicState]] = {
    LearningEpistemicState.PROPOSED: frozenset(
        {
            LearningEpistemicState.OBSERVED,
            LearningEpistemicState.MEASURED,
            LearningEpistemicState.REJECTED,
            LearningEpistemicState.SUPERSEDED,
        }
    ),
    LearningEpistemicState.OBSERVED: frozenset(
        {
            LearningEpistemicState.MEASURED,
            LearningEpistemicState.REJECTED,
            LearningEpistemicState.SUPERSEDED,
        }
    ),
    LearningEpistemicState.MEASURED: frozenset(
        {
            LearningEpistemicState.REPLICATED,
            LearningEpistemicState.VERIFIED,
            LearningEpistemicState.REJECTED,
            LearningEpistemicState.SUPERSEDED,
        }
    ),
    LearningEpistemicState.REPLICATED: frozenset(
        {
            LearningEpistemicState.VERIFIED,
            LearningEpistemicState.REJECTED,
            LearningEpistemicState.SUPERSEDED,
        }
    ),
    LearningEpistemicState.VERIFIED: frozenset(
        {
            LearningEpistemicState.SUPERSEDED,
            LearningEpistemicState.REJECTED,
        }
    ),
    LearningEpistemicState.REJECTED: frozenset({LearningEpistemicState.SUPERSEDED}),
    LearningEpistemicState.SUPERSEDED: frozenset(),
}


def map_legacy_epistemic_state(raw: str | None) -> LearningEpistemicState:
    text = str(raw or "").strip().upper()
    legacy = {
        "PROPOSED": LearningEpistemicState.PROPOSED,
        "AGENT_PROPOSED": LearningEpistemicState.PROPOSED,
        "OBSERVED": LearningEpistemicState.OBSERVED,
        "PAPER_OBSERVED": LearningEpistemicState.OBSERVED,
        "MEASURED": LearningEpistemicState.MEASURED,
        "TRAIN_ADAPTIVE": LearningEpistemicState.MEASURED,
        "REPLICATED": LearningEpistemicState.REPLICATED,
        "VERIFIED": LearningEpistemicState.VERIFIED,
        "VALIDATED": LearningEpistemicState.VERIFIED,
        "REJECTED": LearningEpistemicState.REJECTED,
        "SUPERSEDED": LearningEpistemicState.SUPERSEDED,
        "SEALED": LearningEpistemicState.SUPERSEDED,
    }
    if text in legacy:
        return legacy[text]
    try:
        return LearningEpistemicState(text)
    except ValueError:
        return LearningEpistemicState.PROPOSED


def map_trust_to_epistemic(trust: str | None) -> LearningEpistemicState:
    return map_legacy_epistemic_state(trust)


def map_epistemic_to_trust(state: LearningEpistemicState | str) -> str:
    """Project canonical epistemic state onto existing LessonTrust vocabulary."""
    from Data.modules.market_sim.agent_lab import LessonTrust

    ep = (
        state
        if isinstance(state, LearningEpistemicState)
        else map_legacy_epistemic_state(str(state))
    )
    mapping = {
        LearningEpistemicState.PROPOSED: LessonTrust.AGENT_PROPOSED.value,
        LearningEpistemicState.OBSERVED: LessonTrust.AGENT_PROPOSED.value,
        LearningEpistemicState.MEASURED: LessonTrust.AGENT_PROPOSED.value,
        LearningEpistemicState.REPLICATED: LessonTrust.AGENT_PROPOSED.value,
        LearningEpistemicState.VERIFIED: LessonTrust.VALIDATED.value,
        LearningEpistemicState.REJECTED: LessonTrust.REJECTED.value,
        LearningEpistemicState.SUPERSEDED: LessonTrust.REJECTED.value,
    }
    return mapping[ep]


def strip_chain_of_thought(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove private reasoning keys — only externally inspectable conclusions remain."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _COT_KEYS:
            continue
        if isinstance(value, dict):
            cleaned = {
                k: v
                for k, v in value.items()
                if k not in _COT_KEYS
            }
            out[key] = cleaned
        else:
            out[key] = value
    return out


def validate_epistemic_transition(from_state: str, to_state: str) -> None:
    src = map_legacy_epistemic_state(from_state)
    dst = map_legacy_epistemic_state(to_state)
    if src == dst:
        return
    allowed = _ALLOWED_TRANSITIONS.get(src, frozenset())
    if dst not in allowed:
        raise ValueError(f"illegal epistemic transition {src.value} → {dst.value}")


@dataclass
class LearningLesson:
    """Externally inspectable lesson — conclusions, evidence, measurements only."""

    lesson_id: str
    origin: str
    created_at: str
    available_at: str
    producer: str
    domain: str
    subject: str
    claim: str
    evidence_refs: list[str] = field(default_factory=list)
    experiment_refs: list[str] = field(default_factory=list)
    strategy_id: str | None = None
    strategy_version: int | None = None
    dataset_versions: list[str] = field(default_factory=list)
    environment: str = ""
    confidence: float = 0.0
    validation_stage: str = ""
    failure_categories: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    trust_state: LearningEpistemicState = LearningEpistemicState.PROPOSED
    epistemic_state: str = LearningEpistemicState.PROPOSED.value
    rejected: bool = False
    negative_evidence: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.epistemic_state and not isinstance(self.trust_state, LearningEpistemicState):
            self.trust_state = map_legacy_epistemic_state(str(self.trust_state))
        if self.epistemic_state:
            self.trust_state = map_legacy_epistemic_state(self.epistemic_state)
        else:
            self.epistemic_state = self.trust_state.value
        if self.rejected or self.negative_evidence:
            if self.trust_state not in {
                LearningEpistemicState.REJECTED,
                LearningEpistemicState.SUPERSEDED,
            }:
                self.trust_state = LearningEpistemicState.REJECTED
                self.epistemic_state = LearningEpistemicState.REJECTED.value
            self.rejected = True
            self.negative_evidence = True

    def public_dict(self) -> dict[str, Any]:
        trust = map_epistemic_to_trust(self.trust_state)
        return {
            "lesson_id": self.lesson_id,
            "lessonId": self.lesson_id,
            "origin": self.origin,
            "created_at": self.created_at,
            "createdAt": self.created_at,
            "available_at": self.available_at,
            "availableAt": self.available_at,
            "producer": self.producer,
            "domain": self.domain,
            "subject": self.subject,
            "claim": self.claim,
            "evidence_refs": list(self.evidence_refs),
            "evidenceRefs": list(self.evidence_refs),
            "experiment_refs": list(self.experiment_refs),
            "experimentRefs": list(self.experiment_refs),
            "strategy_id": self.strategy_id,
            "strategyId": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategyVersion": self.strategy_version,
            "dataset_versions": list(self.dataset_versions),
            "datasetVersions": list(self.dataset_versions),
            "environment": self.environment,
            "confidence": self.confidence,
            "validation_stage": self.validation_stage,
            "validationStage": self.validation_stage,
            "failure_categories": list(self.failure_categories),
            "failureCategories": list(self.failure_categories),
            "contradictions": list(self.contradictions),
            "supersedes": list(self.supersedes),
            "trust_state": self.trust_state.value,
            "trustState": self.trust_state.value,
            "trust": trust,
            "epistemic_state": self.epistemic_state,
            "epistemicState": self.epistemic_state,
            "rejected": self.rejected or self.trust_state == LearningEpistemicState.REJECTED,
            "negative_evidence": self.negative_evidence or self.rejected,
            "metadata": dict(self.metadata),
            "truth": {
                "noChainOfThoughtPersisted": True,
                "no_private_cot": True,
                "negativeEvidenceRetained": True,
                "sealedIsNotAdaptive": True,
            },
        }

    def to_lab_lesson_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "claim": self.claim,
            "evidence_refs": list(self.evidence_refs),
            "applies_to": list(self.metadata.get("applies_to") or []),
            "confidence": self.confidence,
            "trust": map_epistemic_to_trust(self.trust_state),
            "created_at": self.created_at,
            "metadata": {
                **dict(self.metadata),
                "epistemic_state": self.epistemic_state,
                "origin": self.origin,
                "producer": self.producer,
                "domain": self.domain,
                "subject": self.subject,
            },
        }

    def semantic_key(self) -> str:
        claim_norm = re.sub(r"\s+", " ", (self.claim or "").strip().lower())
        claim_norm = re.sub(r"[^\w\s\-./]", "", claim_norm)[:240]
        applies = ",".join(sorted(str(x).upper() for x in (self.metadata.get("applies_to") or [])[:8]))
        cats = ",".join(sorted(self.failure_categories[:8]))
        payload = f"{self.domain}|{self.subject}|{claim_norm}|{applies}|{cats}|{self.strategy_id or ''}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# Alias for Wave 6 naming.
DurableLearningLesson = LearningLesson


def new_durable_lesson(
    *,
    claim: str,
    origin: str = "learning_runtime",
    producer: str = "system",
    domain: str = "market_sim",
    subject: str = "",
    evidence_refs: list[str] | None = None,
    experiment_refs: list[str] | None = None,
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    dataset_versions: list[str] | None = None,
    environment: str = "",
    confidence: float = 0.0,
    validation_stage: str = "",
    failure_categories: list[str] | None = None,
    contradictions: list[str] | None = None,
    supersedes: list[str] | None = None,
    epistemic_state: str = "PROPOSED",
    negative_evidence: bool = False,
    metadata: dict[str, Any] | None = None,
    lesson_id: str | None = None,
    created_at: str | None = None,
    available_at: str | None = None,
) -> LearningLesson:
    now = created_at or utc_now()
    ep = map_legacy_epistemic_state(epistemic_state)
    if negative_evidence:
        ep = LearningEpistemicState.REJECTED
    return LearningLesson(
        lesson_id=lesson_id or f"lesson-{uuid.uuid4().hex[:16]}",
        origin=origin,
        created_at=now,
        available_at=available_at or now,
        producer=producer,
        domain=domain,
        subject=subject,
        claim=claim,
        evidence_refs=list(evidence_refs or []),
        experiment_refs=list(experiment_refs or []),
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        dataset_versions=list(dataset_versions or []),
        environment=environment,
        confidence=float(confidence),
        validation_stage=validation_stage,
        failure_categories=list(failure_categories or []),
        contradictions=list(contradictions or []),
        supersedes=list(supersedes or []),
        trust_state=ep,
        epistemic_state=ep.value,
        rejected=negative_evidence or ep == LearningEpistemicState.REJECTED,
        negative_evidence=negative_evidence or ep == LearningEpistemicState.REJECTED,
        metadata=dict(metadata or {}),
    )


def persistable_lesson_payload(lesson: LearningLesson) -> dict[str, Any]:
    return strip_chain_of_thought(lesson.public_dict())


def advance_epistemic_state(lesson: LearningLesson, to_state: str) -> LearningLesson:
    validate_epistemic_transition(lesson.epistemic_state, to_state)
    ep = map_legacy_epistemic_state(to_state)
    return replace(
        lesson,
        trust_state=ep,
        epistemic_state=ep.value,
        rejected=ep == LearningEpistemicState.REJECTED or lesson.rejected,
        negative_evidence=ep == LearningEpistemicState.REJECTED or lesson.negative_evidence,
    )


def dedupe_lessons(lessons: Sequence[LearningLesson]) -> list[LearningLesson]:
    seen: dict[str, LearningLesson] = {}
    order: list[str] = []
    rank = {
        LearningEpistemicState.VERIFIED: 5,
        LearningEpistemicState.REPLICATED: 4,
        LearningEpistemicState.MEASURED: 3,
        LearningEpistemicState.OBSERVED: 2,
        LearningEpistemicState.PROPOSED: 1,
        LearningEpistemicState.REJECTED: 3,
        LearningEpistemicState.SUPERSEDED: 0,
    }
    for lesson in lessons:
        key = lesson.semantic_key()
        if key not in seen:
            seen[key] = lesson
            order.append(key)
            continue
        existing = seen[key]
        if rank.get(lesson.trust_state, 0) > rank.get(existing.trust_state, 0):
            seen[key] = lesson
        elif lesson.rejected and not existing.rejected:
            seen[key] = lesson
    return [seen[k] for k in order]


deduplicate_lessons = dedupe_lessons


def lesson_from_legacy(raw: dict[str, Any], *, origin: str = "legacy") -> LearningLesson:
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    trust = map_legacy_epistemic_state(
        raw.get("trust")
        or raw.get("epistemic_state")
        or raw.get("epistemicState")
        or meta.get("trust")
        or meta.get("epistemic_state")
    )
    rejected = bool(raw.get("rejected") or raw.get("negative_evidence")) or trust == LearningEpistemicState.REJECTED
    if rejected:
        trust = LearningEpistemicState.REJECTED
    return LearningLesson(
        lesson_id=str(raw.get("lesson_id") or raw.get("memory_id") or raw.get("lessonId") or ""),
        origin=str(raw.get("origin") or meta.get("origin") or origin),
        created_at=str(raw.get("created_at") or raw.get("createdAt") or ""),
        available_at=str(raw.get("available_at") or raw.get("availableAt") or raw.get("created_at") or ""),
        producer=str(raw.get("producer") or meta.get("producer") or origin),
        domain=str(raw.get("domain") or meta.get("domain") or "trading"),
        subject=str(raw.get("subject") or raw.get("strategy_id") or meta.get("subject") or ""),
        claim=str(raw.get("claim") or raw.get("outcome_summary") or ""),
        evidence_refs=list(raw.get("evidence_refs") or raw.get("evidenceRefs") or meta.get("evidence_refs") or []),
        experiment_refs=list(raw.get("experiment_refs") or raw.get("experimentRefs") or meta.get("experiment_refs") or []),
        strategy_id=(str(raw.get("strategy_id")) if raw.get("strategy_id") else None),
        strategy_version=raw.get("strategy_version") if raw.get("strategy_version") is not None else None,
        dataset_versions=list(raw.get("dataset_versions") or meta.get("dataset_versions") or []),
        environment=str(raw.get("environment") or meta.get("environment") or ""),
        confidence=float(raw.get("confidence") or meta.get("confidence") or 0.0),
        validation_stage=str(raw.get("validation_stage") or meta.get("validation_stage") or ""),
        failure_categories=list(raw.get("failure_categories") or meta.get("failure_categories") or []),
        contradictions=list(raw.get("contradictions") or meta.get("contradictions") or []),
        supersedes=list(raw.get("supersedes") or meta.get("supersedes") or []),
        trust_state=trust,
        epistemic_state=trust.value,
        rejected=rejected,
        negative_evidence=rejected,
        metadata={
            **meta,
            "applies_to": list(raw.get("applies_to") or raw.get("appliesTo") or meta.get("applies_to") or []),
        },
    )


def merge_lesson_streams(*streams: Iterable[dict[str, Any]], origin: str = "merged") -> list[LearningLesson]:
    lessons: list[LearningLesson] = []
    for stream in streams:
        for raw in stream:
            if not isinstance(raw, dict):
                continue
            lesson = lesson_from_legacy(raw, origin=origin)
            if not lesson.claim.strip():
                continue
            lessons.append(lesson)
    return dedupe_lessons(lessons)
