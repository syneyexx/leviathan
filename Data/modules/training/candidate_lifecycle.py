"""Candidate training lifecycle — cognition trajectories → governed mixture (F15 / R23).

Wires F14 public export bundles into the existing training candidate path.
Phases: pending → governed → ingested (mixture-ready). Never auto-trains or
auto-promotes models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from .active_learning import ActiveLearningMiner, MinedCandidate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CandidatePhase(str, Enum):
    PENDING = "pending"
    GOVERNED = "governed"
    INGESTED = "ingested"  # mixture-ready; still not trained/promoted
    REJECTED = "rejected"


class CandidateSource(str, Enum):
    COGNITION_TRAJECTORY = "cognition_trajectory"
    VERIFIED_SFT = "verified_sft"
    PREFERENCE_SEED = "preference_seed"
    ACTIVE_LEARNING = "active_learning"
    EVENT_MINE = "event_mine"


@dataclass
class TrainingCandidateRecord:
    """Durable-facing candidate with explicit lifecycle phase."""

    candidate_id: str
    phase: CandidatePhase
    source: CandidateSource
    kind: str
    prompt: str
    content: str
    run_id: str | None = None
    trajectory_id: str | None = None
    experience_id: str | None = None
    domain: str | None = None
    export_class: str | None = None
    verification_status: str | None = None
    governed: bool = False
    ingested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "phase": self.phase.value,
            "source": self.source.value,
            "kind": self.kind,
            "prompt": self.prompt,
            "content": self.content,
            "run_id": self.run_id,
            "trajectory_id": self.trajectory_id,
            "experience_id": self.experience_id,
            "domain": self.domain,
            "export_class": self.export_class,
            "verification_status": self.verification_status,
            "governed": self.governed,
            "ingested": self.ingested,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "truth": {
                "candidate_lifecycle_is_explicit": True,
                "mining_requires_explicit_governed_ingestion": True,
                "not_auto_added_to_training_mixture": True,
                "ingested_is_not_trained": True,
                "auto_promote_forbidden": True,
                "wired_from_cognition_trajectories": self.source
                in {
                    CandidateSource.COGNITION_TRAJECTORY,
                    CandidateSource.VERIFIED_SFT,
                    CandidateSource.PREFERENCE_SEED,
                    CandidateSource.ACTIVE_LEARNING,
                },
            },
        }


def _assistant_text(messages: Sequence[Mapping[str, Any]] | None) -> str:
    if not messages:
        return ""
    for msg in messages:
        if str(msg.get("role") or "") == "assistant":
            return str(msg.get("content") or "")
    return ""


class CandidateTrainingLifecycle:
    """Bridge cognition export bundles into governed training candidates.

    Optional ``miner`` keeps Wave-9 ActiveLearningMiner in sync for existing
    ``/api/training/active-learning/*/govern`` routes.
    """

    def __init__(self, miner: ActiveLearningMiner | None = None) -> None:
        self._items: dict[str, TrainingCandidateRecord] = {}
        self.miner = miner if miner is not None else ActiveLearningMiner()

    def accept_export_bundle(
        self,
        bundle: Mapping[str, Any],
        *,
        include_verified_sft: bool = True,
        include_preference_seeds: bool = True,
        include_active_learning: bool = True,
    ) -> list[TrainingCandidateRecord]:
        """Ingest an F14 ``export_training_bundle`` payload into pending candidates.

        Does not govern, write datasets, train, or promote.
        """
        created: list[TrainingCandidateRecord] = []
        if include_verified_sft:
            for rec in bundle.get("sft_records") or []:
                if not isinstance(rec, Mapping):
                    continue
                created.append(
                    self._register(
                        source=CandidateSource.VERIFIED_SFT,
                        kind="verified_sft",
                        prompt=_goal_from_record(rec),
                        content=_assistant_text(rec.get("messages")),
                        run_id=str((rec.get("metadata") or {}).get("run_id") or "") or None,
                        trajectory_id=str(rec.get("id") or "") or None,
                        experience_id=str((rec.get("metadata") or {}).get("experience_id") or "")
                        or None,
                        domain=str((rec.get("labels") or {}).get("domain") or "") or None,
                        export_class=str((rec.get("labels") or {}).get("export_class") or "verified_sft"),
                        verification_status=str(
                            (rec.get("labels") or {}).get("verification_status") or ""
                        )
                        or None,
                        metadata={
                            "canonical_record_id": rec.get("id"),
                            "content_hash": (rec.get("metadata") or {}).get("content_hash"),
                        },
                    )
                )
        if include_preference_seeds:
            for seed in bundle.get("preference_seeds") or []:
                if not isinstance(seed, Mapping):
                    continue
                created.append(
                    self._register(
                        source=CandidateSource.PREFERENCE_SEED,
                        kind="preference",
                        prompt=str(seed.get("prompt") or ""),
                        content=str(seed.get("rejected_preview") or ""),
                        run_id=str(seed.get("run_id") or "") or None,
                        trajectory_id=str(seed.get("trajectory_id") or "") or None,
                        export_class="preference_candidate",
                        verification_status=str(seed.get("verification_status") or "") or None,
                        metadata={
                            "preferred_id": seed.get("preferred_id"),
                            "preference_labels_not_fabricated": True,
                        },
                    )
                )
        if include_active_learning:
            for al in bundle.get("active_learning") or []:
                if not isinstance(al, Mapping):
                    continue
                created.append(
                    self._register(
                        source=CandidateSource.ACTIVE_LEARNING,
                        kind=str(al.get("kind") or al.get("reason") or "active_learning"),
                        prompt=str(al.get("goal") or al.get("prompt") or ""),
                        content=str(al.get("reason") or al.get("content") or ""),
                        run_id=str(al.get("run_id") or "") or None,
                        domain=str(al.get("domain") or "") or None,
                        export_class="active_learning",
                        metadata={
                            "reason": al.get("reason"),
                            "candidate_id_upstream": al.get("candidate_id"),
                        },
                    )
                )
        # Also accept full trajectory rows when present (non-SFT classes).
        for traj in bundle.get("trajectories") or []:
            if not isinstance(traj, Mapping):
                continue
            export_class = str(traj.get("export_class") or "")
            if export_class in {"verified_sft", "unverified_excluded"}:
                continue  # SFT already handled; excluded never becomes a candidate
            if any(c.trajectory_id == traj.get("trajectory_id") for c in created):
                continue
            created.append(
                self._register(
                    source=CandidateSource.COGNITION_TRAJECTORY,
                    kind=export_class or "trajectory",
                    prompt=str(traj.get("goal") or ""),
                    content=_assistant_text(traj.get("messages")),
                    run_id=str(traj.get("run_id") or "") or None,
                    trajectory_id=str(traj.get("trajectory_id") or "") or None,
                    experience_id=str(traj.get("experience_id") or "") or None,
                    domain=str(traj.get("domain") or "") or None,
                    export_class=export_class or None,
                    verification_status=str(traj.get("verification_status") or "") or None,
                    metadata={"status": traj.get("status"), "mode": traj.get("mode")},
                )
            )
        return created

    def _register(
        self,
        *,
        source: CandidateSource,
        kind: str,
        prompt: str,
        content: str,
        run_id: str | None = None,
        trajectory_id: str | None = None,
        experience_id: str | None = None,
        domain: str | None = None,
        export_class: str | None = None,
        verification_status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrainingCandidateRecord:
        cid = f"cand_{uuid.uuid4().hex[:12]}"
        record = TrainingCandidateRecord(
            candidate_id=cid,
            phase=CandidatePhase.PENDING,
            source=source,
            kind=kind,
            prompt=prompt,
            content=content,
            run_id=run_id,
            trajectory_id=trajectory_id,
            experience_id=experience_id,
            domain=domain,
            export_class=export_class,
            verification_status=verification_status,
            metadata=dict(metadata or {}),
        )
        self._items[cid] = record
        # Mirror into ActiveLearningMiner for shared govern surface.
        mined = MinedCandidate(
            candidate_id=cid,
            kind=_miner_kind(kind),
            source_ref=run_id or trajectory_id or experience_id or cid,
            prompt=prompt,
            content=content,
            governed=False,
            metadata={
                **dict(metadata or {}),
                "lifecycle_source": source.value,
                "export_class": export_class,
                "wired_from_cognition_trajectories": True,
            },
        )
        self.miner._pending[cid] = mined  # noqa: SLF001 — intentional shared registry
        return record

    def govern(
        self,
        candidate_id: str,
        *,
        operator: str,
        note: str = "",
    ) -> TrainingCandidateRecord:
        record = self._require(candidate_id)
        if record.phase == CandidatePhase.REJECTED:
            raise ValueError(f"Candidate {candidate_id} was rejected")
        if record.phase == CandidatePhase.INGESTED:
            raise ValueError(f"Candidate {candidate_id} already ingested")
        # Keep miner in sync (Wave-9 API).
        if candidate_id in self.miner._pending:  # noqa: SLF001
            self.miner.govern(candidate_id, operator=operator, note=note)
        record.phase = CandidatePhase.GOVERNED
        record.governed = True
        record.updated_at = _utc_now()
        record.metadata["governed_by"] = operator
        record.metadata["govern_note"] = note
        record.metadata["governed_at"] = record.updated_at
        return record

    def reject(
        self,
        candidate_id: str,
        *,
        operator: str,
        note: str = "",
    ) -> TrainingCandidateRecord:
        record = self._require(candidate_id)
        if record.phase == CandidatePhase.INGESTED:
            raise ValueError(f"Cannot reject ingested candidate {candidate_id}")
        record.phase = CandidatePhase.REJECTED
        record.governed = False
        record.ingested = False
        record.updated_at = _utc_now()
        record.metadata["rejected_by"] = operator
        record.metadata["reject_note"] = note
        record.metadata["rejected_at"] = record.updated_at
        return record

    def mark_ingested(
        self,
        candidate_id: str,
        *,
        operator: str,
        mixture_ref: str | None = None,
        note: str = "",
    ) -> TrainingCandidateRecord:
        """Mark governed candidate as mixture-ready — does not train or promote."""
        record = self._require(candidate_id)
        if record.phase != CandidatePhase.GOVERNED:
            raise ValueError(
                f"Candidate {candidate_id} must be governed before ingest "
                f"(phase={record.phase.value})"
            )
        record.phase = CandidatePhase.INGESTED
        record.ingested = True
        record.updated_at = _utc_now()
        record.metadata["ingested_by"] = operator
        record.metadata["ingest_note"] = note
        record.metadata["ingested_at"] = record.updated_at
        if mixture_ref:
            record.metadata["mixture_ref"] = mixture_ref
        record.metadata["training_job_not_started"] = True
        record.metadata["auto_promote_forbidden"] = True
        return record

    def list_candidates(
        self,
        *,
        phase: CandidatePhase | str | None = None,
        source: CandidateSource | str | None = None,
        limit: int = 100,
    ) -> list[TrainingCandidateRecord]:
        items = list(self._items.values())
        if phase is not None:
            phase_v = phase.value if isinstance(phase, CandidatePhase) else str(phase)
            items = [c for c in items if c.phase.value == phase_v]
        if source is not None:
            source_v = source.value if isinstance(source, CandidateSource) else str(source)
            items = [c for c in items if c.source.value == source_v]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items[: max(0, int(limit))]

    def public_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {p.value: 0 for p in CandidatePhase}
        for c in self._items.values():
            counts[c.phase.value] = counts.get(c.phase.value, 0) + 1
        return {
            "total": len(self._items),
            "by_phase": counts,
            "truth": {
                "candidate_lifecycle_wired_from_cognition": True,
                "auto_promote_forbidden": True,
                "ingested_is_not_trained": True,
                "governed_ingestion_required": True,
            },
        }

    def _require(self, candidate_id: str) -> TrainingCandidateRecord:
        record = self._items.get(candidate_id)
        if record is None:
            raise KeyError(f"Unknown training candidate: {candidate_id}")
        return record


def _goal_from_record(rec: Mapping[str, Any]) -> str:
    messages = rec.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, Mapping) and str(msg.get("role") or "") == "user":
                return str(msg.get("content") or "")
    text = str(rec.get("text") or "")
    if text.startswith("Goal: "):
        return text.split("\n", 1)[0][len("Goal: ") :]
    return text[:500]


def _miner_kind(kind: str) -> str:
    k = (kind or "").lower()
    if k in {"failure", "retry", "correction", "tool_error"}:
        return k
    if "preference" in k:
        return "correction"
    if "sft" in k or "verified" in k:
        return "retry"
    return "failure"
