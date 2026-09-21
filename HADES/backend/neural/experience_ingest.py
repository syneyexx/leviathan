"""Offline verified-experience → ContinualLearningPipeline ingest (Neural V2).

Batch / explicit-job path only. Never enables online LEARN during tool rounds.
Never trains from raw assistant text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from neural.continual_learning import ContinualLearningPipeline, ContinualLearningResult
from neural.experience import (
    ExperienceOutcome,
    NeuralExperience,
    experiences_from_store,
    neural_experience_from_verified_item,
)
from neural.learning_lifecycle import assert_learn_disabled_by_default


@dataclass
class ExperienceIngestReport:
    scanned: int = 0
    processed: int = 0
    accepted_positive: int = 0
    accepted_negative: int = 0
    rejected: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ingest_verified_experiences(
    store: Any,
    *,
    query: str = "",
    limit: int = 32,
    pipeline: ContinualLearningPipeline | None = None,
    neural_allow: bool = False,
    neural_mode: str = "off",
    items: Sequence[Mapping[str, Any]] | None = None,
) -> ExperienceIngestReport:
    """Project gen2 verified experiences into the continual-learning pipeline.

    Gated: requires ``neural_allow`` and mode in {read, shadow}. LEARN mode is
    rejected here — ModelGateway primary must stay Standard / non-LEARN.
    """
    assert_learn_disabled_by_default(learn_enabled=False)
    report = ExperienceIngestReport()
    mode = str(neural_mode or "off").strip().lower()
    if not neural_allow:
        report.notes.append("neural_allow_false")
        return report
    if mode == "learn":
        report.notes.append("learn_mode_rejected_as_gateway_primary")
        return report
    if mode not in {"read", "shadow"}:
        report.notes.append(f"mode_{mode}_skip")
        return report

    pipe = pipeline or ContinualLearningPipeline()
    experiences: list[NeuralExperience] = []
    if items is not None:
        for raw in items:
            try:
                experiences.append(neural_experience_from_verified_item(raw))
            except Exception as exc:  # noqa: BLE001
                report.rejected += 1
                report.notes.append(f"item_reject:{type(exc).__name__}")
    else:
        experiences = experiences_from_store(store, query or " ", limit=limit)

    report.scanned = len(experiences)
    for exp in experiences:
        result: ContinualLearningResult = pipe.process_experience(exp)
        report.processed += 1
        payload = result.to_dict()
        report.results.append(payload)
        if result.eligibility.failure_memory and result.negative_slow_sample:
            report.accepted_negative += 1
        elif result.eligibility.eligible and result.eligibility.fast_memory_eligible:
            report.accepted_positive += 1
        elif result.eligibility.eligible and result.eligibility.consolidation_eligible:
            report.accepted_positive += 1
        elif not result.eligibility.eligible:
            report.rejected += 1
        elif result.eligibility.failure_memory and not result.negative_slow_sample:
            report.rejected += 1
            report.notes.append(f"negative_sample_missing:{exp.experience_id}")
    return report


def experience_ingest_allowed(settings: Mapping[str, Any] | None = None) -> bool:
    settings = settings or {}
    if not bool(settings.get("neural_allow")):
        return False
    mode = str(settings.get("neural_mode") or "off").strip().lower()
    return mode in {"read", "shadow"}


def maybe_ingest_verified_experiences(
    store: Any,
    settings: Mapping[str, Any] | None = None,
    *,
    query: str = "",
    limit: int = 32,
    pipeline: ContinualLearningPipeline | None = None,
    items: Sequence[Mapping[str, Any]] | None = None,
) -> ExperienceIngestReport:
    """Post-task / offline hook: gate on allow + read|shadow, then ingest.

    Never enables LEARN as a gateway primary. Safe no-op when Neural is OFF.
    """
    settings = settings or {}
    return ingest_verified_experiences(
        store,
        query=query,
        limit=limit,
        pipeline=pipeline,
        neural_allow=bool(settings.get("neural_allow")),
        neural_mode=str(settings.get("neural_mode") or "off"),
        items=items,
    )
