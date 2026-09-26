"""Canonical dataset learning state — single source of truth for Brain readiness.

File/materialization readiness is separate from Brain ingestion readiness.
UI surfaces must consume ``DatasetLearningState`` (or the compatible
``brain_status`` projection) rather than guessing from job lists alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .types import (
    DatasetJob,
    DatasetJobStatus,
    DatasetJobType,
    DatasetRecord,
    DatasetStatus,
    DatasetVersion,
    IndexStatus,
    VersionKind,
    VersionStatus,
    DatasetIndex,
)


class DatasetLearningCanonicalState(str, Enum):
    """Operator-facing canonical learning states (Brain ingestion ladder)."""

    REGISTERED = "REGISTERED"
    SOURCE_READY = "SOURCE_READY"
    MATERIALIZING = "MATERIALIZING"
    VALIDATING = "VALIDATING"
    READY_FOR_INDEX = "READY_FOR_INDEX"
    INDEX_QUEUED = "INDEX_QUEUED"
    INDEXING = "INDEXING"
    LEARNED = "LEARNED"
    REBUILDING = "REBUILDING"
    FAILED = "FAILED"
    STALE_JOB = "STALE_JOB"
    SOURCE_MISSING = "SOURCE_MISSING"
    CANCELLED = "CANCELLED"


# Legacy brainStatus strings kept for UI compatibility.
_BRAIN_STATUS_FOR_CANONICAL: dict[DatasetLearningCanonicalState, str] = {
    DatasetLearningCanonicalState.LEARNED: "learned",
    DatasetLearningCanonicalState.REBUILDING: "indexing",
    DatasetLearningCanonicalState.INDEXING: "indexing",
    DatasetLearningCanonicalState.INDEX_QUEUED: "queued",
    DatasetLearningCanonicalState.FAILED: "failed",
    DatasetLearningCanonicalState.SOURCE_MISSING: "not_learned",
    DatasetLearningCanonicalState.STALE_JOB: "learned",
    DatasetLearningCanonicalState.CANCELLED: "not_learned",
    DatasetLearningCanonicalState.READY_FOR_INDEX: "not_learned",
    DatasetLearningCanonicalState.MATERIALIZING: "not_learned",
    DatasetLearningCanonicalState.VALIDATING: "not_learned",
    DatasetLearningCanonicalState.SOURCE_READY: "not_learned",
    DatasetLearningCanonicalState.REGISTERED: "not_learned",
}

_LABELS_NL: dict[DatasetLearningCanonicalState, str] = {
    DatasetLearningCanonicalState.LEARNED: "Geleerd",
    DatasetLearningCanonicalState.REBUILDING: "Hernieuwd indexeren",
    DatasetLearningCanonicalState.INDEXING: "Bezig met leren",
    DatasetLearningCanonicalState.INDEX_QUEUED: "In wachtrij",
    DatasetLearningCanonicalState.FAILED: "Leren mislukt",
    DatasetLearningCanonicalState.SOURCE_MISSING: "Bron ontbreekt",
    DatasetLearningCanonicalState.STALE_JOB: "Geleerd (stale job genegeerd)",
    DatasetLearningCanonicalState.CANCELLED: "Geannuleerd",
    DatasetLearningCanonicalState.READY_FOR_INDEX: "Klaar voor index",
    DatasetLearningCanonicalState.MATERIALIZING: "Materialiseren",
    DatasetLearningCanonicalState.VALIDATING: "Valideren",
    DatasetLearningCanonicalState.SOURCE_READY: "Bron gereed",
    DatasetLearningCanonicalState.REGISTERED: "Geregistreerd",
}


@dataclass
class DatasetLearningState:
    """Typed canonical learning contract owned by DatasetService."""

    dataset_id: str
    version_id: str | None
    source_state: str
    materialization_state: str
    validation_state: str
    index_state: str
    brain_state: str
    job_state: str | None
    progress: float | None
    phase: str | None
    index_id: str | None
    document_count: int | None
    chunk_count: int | None
    embedding_mode: str | None
    semantic_embeddings: bool | None
    relations: dict[str, Any]
    updated_at: str | None
    stale: bool
    error: str | None
    truth: dict[str, Any]
    canonical_state: DatasetLearningCanonicalState
    # Compatibility projection used by existing UI.
    brain_status: str
    label: str
    learned: bool
    source_missing: bool
    job_id: str | None = None
    usable_index_id: str | None = None
    prior_ready_preserved: bool = False
    learning: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        out = {
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "sourceState": self.source_state,
            "materializationState": self.materialization_state,
            "validationState": self.validation_state,
            "indexState": self.index_state,
            "brainState": self.brain_state,
            "jobState": self.job_state,
            "progress": self.progress,
            "phase": self.phase,
            "indexId": self.index_id,
            "documentCount": self.document_count,
            "chunkCount": self.chunk_count,
            "embeddingMode": self.embedding_mode,
            "semanticEmbeddings": self.semantic_embeddings,
            "relations": self.relations,
            "updatedAt": self.updated_at,
            "stale": self.stale,
            "error": self.error,
            "truth": self.truth,
            "canonicalState": self.canonical_state.value,
            "brainStatus": self.brain_status,
            "label": self.label,
            "learned": self.learned,
            "sourceMissing": self.source_missing,
            "jobId": self.job_id,
            "usableIndexId": self.usable_index_id,
            "priorReadyPreserved": self.prior_ready_preserved,
            "learning": self.learning,
        }
        return out

    def brain_projection(self) -> dict[str, Any]:
        """Backward-compatible brain_status_for_dataset shape."""
        return {
            "brainStatus": self.brain_status,
            "label": self.label,
            "indexId": self.index_id,
            "chunkCount": self.chunk_count,
            "documentCount": self.document_count,
            "jobId": self.job_id,
            "progress": self.progress,
            "phase": self.phase,
            "updatedAt": self.updated_at,
            "sourceMissing": self.source_missing,
            "learned": self.learned,
            "versionId": self.version_id,
            "embeddingMode": self.embedding_mode,
            "embeddingsSemantic": self.semantic_embeddings,
            "relationsAccepted": (self.relations or {}).get("accepted"),
            "relationsRejected": (self.relations or {}).get("rejected"),
            "processed": None,
            "learning": self.learning,
            "canonicalState": self.canonical_state.value,
            "stale": self.stale,
            "usableIndexId": self.usable_index_id,
            "priorReadyPreserved": self.prior_ready_preserved,
            "error": self.error,
            "truth": self.truth,
        }


def _is_rebuild_job(job: DatasetJob) -> bool:
    return bool((job.config or {}).get("rebuild"))


def _active_index_jobs(jobs: list[DatasetJob]) -> list[DatasetJob]:
    return [
        j
        for j in jobs
        if j.job_type == DatasetJobType.INDEX
        and j.status in {DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING}
    ]


def _latest_ready(indexes: list[DatasetIndex]) -> DatasetIndex | None:
    ready = [i for i in indexes if i.status == IndexStatus.READY]
    if not ready:
        return None
    return sorted(ready, key=lambda i: i.updated_at or "", reverse=True)[0]


def _pick_indexable_version(
    versions: list[DatasetVersion],
) -> DatasetVersion | None:
    preferred_kinds = {
        VersionKind.MATERIALIZED,
        VersionKind.TRANSFORMED,
        VersionKind.SPLIT,
        VersionKind.EXPORT,
        VersionKind.RAW,
    }
    ready = [
        v
        for v in versions
        if v.status == VersionStatus.READY and v.kind in preferred_kinds
    ]
    if not ready:
        return None
    # Prefer materialized over raw.
    ready.sort(
        key=lambda v: (
            0 if v.kind == VersionKind.MATERIALIZED else 1,
            v.updated_at or "",
        ),
        reverse=False,
    )
    # Actually prefer most recently updated among materialized first.
    mat = [v for v in ready if v.kind == VersionKind.MATERIALIZED]
    if mat:
        return sorted(mat, key=lambda v: v.updated_at or "", reverse=True)[0]
    return sorted(ready, key=lambda v: v.updated_at or "", reverse=True)[0]


def compute_dataset_learning_state(
    *,
    dataset: DatasetRecord,
    versions: list[DatasetVersion],
    indexes: list[DatasetIndex],
    jobs: list[DatasetJob],
    learning_ladder: dict[str, Any] | None = None,
) -> DatasetLearningState:
    """Pure computation of canonical learning state from durable records."""
    source_missing = bool((dataset.metadata or {}).get("sourceMissing"))
    ready_idx = _latest_ready(indexes)
    indexing_idxs = [i for i in indexes if i.status == IndexStatus.INDEXING]
    failed_idxs = [i for i in indexes if i.status == IndexStatus.FAILED]
    active_jobs = _active_index_jobs(jobs)
    rebuild_running = [
        j
        for j in active_jobs
        if _is_rebuild_job(j) and j.status == DatasetJobStatus.RUNNING
    ]
    rebuild_any = [j for j in active_jobs if _is_rebuild_job(j)]
    non_rebuild_active = [j for j in active_jobs if not _is_rebuild_job(j)]

    # Stale: READY index + non-rebuild queued/running job that is not a rebuild.
    # READY dominates — prior index remains usable truth.
    stale = bool(ready_idx and non_rebuild_active and not rebuild_any)

    version = None
    if ready_idx is not None:
        version = next((v for v in versions if v.version_id == ready_idx.version_id), None)
    if version is None:
        version = _pick_indexable_version(versions)

    # Source / materialization / validation facets (not overloaded with brain).
    if source_missing:
        source_state = "SOURCE_MISSING"
    elif dataset.raw_path or dataset.original_uri:
        source_state = "SOURCE_READY"
    else:
        source_state = "REGISTERED"

    mat_versions = [
        v
        for v in versions
        if v.kind == VersionKind.MATERIALIZED and v.status == VersionStatus.READY
    ]
    if dataset.status == DatasetStatus.MATERIALIZING:
        materialization_state = "MATERIALIZING"
    elif mat_versions:
        materialization_state = "READY"
    elif any(v.kind == VersionKind.MATERIALIZED for v in versions):
        materialization_state = "PENDING"
    else:
        materialization_state = "NONE"

    if version is not None and isinstance(version.validation, dict):
        if version.validation.get("valid") is True:
            validation_state = "VALID"
        elif version.validation.get("valid") is False:
            validation_state = "INVALID"
        else:
            validation_state = "UNMEASURED"
    else:
        validation_state = "UNMEASURED"

    if ready_idx is not None:
        index_state = IndexStatus.READY.value
    elif indexing_idxs:
        index_state = IndexStatus.INDEXING.value
    elif failed_idxs and not ready_idx:
        index_state = IndexStatus.FAILED.value
    else:
        index_state = "none"

    job_state: str | None = None
    job_id: str | None = None
    progress: float | None = None
    phase: str | None = None
    primary_job: DatasetJob | None = None
    if rebuild_running:
        primary_job = rebuild_running[0]
    elif rebuild_any:
        primary_job = rebuild_any[0]
    elif non_rebuild_active and not ready_idx:
        primary_job = non_rebuild_active[0]
    elif stale and non_rebuild_active:
        primary_job = non_rebuild_active[0]

    if primary_job is not None:
        job_state = primary_job.status.value
        job_id = primary_job.job_id
        progress = primary_job.progress
        phase = primary_job.phase

    # Resolve canonical state (Brain readiness dominates file readiness).
    if source_missing and not ready_idx:
        canonical = DatasetLearningCanonicalState.SOURCE_MISSING
    elif ready_idx and rebuild_running:
        canonical = DatasetLearningCanonicalState.REBUILDING
    elif ready_idx and rebuild_any:
        # Queued rebuild — still LEARNED until rebuild actually runs, but expose queued detail.
        canonical = DatasetLearningCanonicalState.LEARNED
        if rebuild_any[0].status == DatasetJobStatus.QUEUED:
            job_state = DatasetJobStatus.QUEUED.value
            job_id = rebuild_any[0].job_id
            phase = rebuild_any[0].phase or "rebuild_queued"
            progress = rebuild_any[0].progress
    elif ready_idx and stale:
        canonical = DatasetLearningCanonicalState.LEARNED
    elif ready_idx:
        canonical = DatasetLearningCanonicalState.LEARNED
    elif primary_job is not None and primary_job.status == DatasetJobStatus.RUNNING:
        canonical = DatasetLearningCanonicalState.INDEXING
    elif primary_job is not None and primary_job.status == DatasetJobStatus.QUEUED:
        canonical = DatasetLearningCanonicalState.INDEX_QUEUED
    elif indexing_idxs:
        canonical = DatasetLearningCanonicalState.INDEXING
    elif failed_idxs and not ready_idx:
        canonical = DatasetLearningCanonicalState.FAILED
    elif dataset.status == DatasetStatus.MATERIALIZING:
        canonical = DatasetLearningCanonicalState.MATERIALIZING
    elif mat_versions or (version and version.status == VersionStatus.READY):
        canonical = DatasetLearningCanonicalState.READY_FOR_INDEX
    elif source_state == "SOURCE_READY":
        canonical = DatasetLearningCanonicalState.SOURCE_READY
    else:
        canonical = DatasetLearningCanonicalState.REGISTERED

    # Check cancelled-only path when latest index job cancelled and nothing else.
    if canonical in {
        DatasetLearningCanonicalState.REGISTERED,
        DatasetLearningCanonicalState.SOURCE_READY,
        DatasetLearningCanonicalState.READY_FOR_INDEX,
    }:
        index_jobs = [j for j in jobs if j.job_type == DatasetJobType.INDEX]
        if index_jobs:
            latest = sorted(index_jobs, key=lambda j: j.updated_at or "", reverse=True)[0]
            if latest.status == DatasetJobStatus.CANCELLED and not ready_idx:
                canonical = DatasetLearningCanonicalState.CANCELLED

    learned = canonical in {
        DatasetLearningCanonicalState.LEARNED,
        DatasetLearningCanonicalState.REBUILDING,
        DatasetLearningCanonicalState.STALE_JOB,
    }
    # REBUILDING preserves prior READY as usable truth.
    prior_ready_preserved = bool(
        ready_idx
        and canonical
        in {
            DatasetLearningCanonicalState.LEARNED,
            DatasetLearningCanonicalState.REBUILDING,
        }
    )
    usable_index_id = ready_idx.index_id if ready_idx else None

    brain_status = _BRAIN_STATUS_FOR_CANONICAL.get(canonical, "not_learned")
    # During REBUILDING expose indexing brainStatus but learned=True for truth.
    if canonical == DatasetLearningCanonicalState.REBUILDING:
        brain_status = "indexing"
        learned = True  # prior READY remains usable

    label = _LABELS_NL.get(canonical, canonical.value)
    if source_missing and learned:
        label = f"{label} (bron ontbreekt)"

    prov: dict[str, Any] = {}
    if ready_idx is not None:
        prov = dict(ready_idx.provenance or {})
    elif indexing_idxs:
        prov = dict(indexing_idxs[0].provenance or {})
    elif failed_idxs:
        prov = dict(sorted(failed_idxs, key=lambda i: i.updated_at or "", reverse=True)[0].provenance or {})

    checkpoint: dict[str, Any] = {}
    if primary_job is not None:
        checkpoint = dict(primary_job.checkpoint or {})

    chunk_count = None
    document_count = None
    embedding_mode = None
    semantic = None
    relations: dict[str, Any] = {}
    error = None
    index_id = None
    updated_at = dataset.updated_at

    if ready_idx is not None:
        index_id = ready_idx.index_id
        chunk_count = ready_idx.chunk_count
        document_count = prov.get("documentCount")
        embedding_mode = prov.get("embeddingMode")
        semantic = prov.get("embeddingsSemantic")
        relations = {
            "accepted": prov.get("relationsAccepted"),
            "rejected": prov.get("relationsRejected"),
        }
        updated_at = ready_idx.updated_at
        if canonical == DatasetLearningCanonicalState.FAILED:
            error = prov.get("error")

    if primary_job is not None and canonical in {
        DatasetLearningCanonicalState.INDEXING,
        DatasetLearningCanonicalState.INDEX_QUEUED,
        DatasetLearningCanonicalState.REBUILDING,
    }:
        if chunk_count is None:
            chunk_count = checkpoint.get("chunkCount")
        if document_count is None:
            document_count = checkpoint.get("indexed")
        if embedding_mode is None:
            embedding_mode = checkpoint.get("embeddingMode")
        if semantic is None:
            semantic = checkpoint.get("embeddingsSemantic")
        relations = {
            "accepted": checkpoint.get("relationsAccepted", relations.get("accepted")),
            "rejected": checkpoint.get("relationsRejected", relations.get("rejected")),
        }
        updated_at = primary_job.updated_at
        # During rebuild keep usable index id as prior READY.
        if canonical != DatasetLearningCanonicalState.REBUILDING:
            index_id = None

    if canonical == DatasetLearningCanonicalState.FAILED and failed_idxs:
        failed = sorted(failed_idxs, key=lambda i: i.updated_at or "", reverse=True)[0]
        index_id = failed.index_id
        chunk_count = failed.chunk_count
        document_count = (failed.provenance or {}).get("documentCount")
        error = (failed.provenance or {}).get("error")
        updated_at = failed.updated_at
        learned = False

    # Progress honesty: never invent a fake percentage.
    if progress is not None:
        try:
            progress = float(progress)
            if not (0.0 <= progress <= 1.0) or progress != progress:  # NaN check
                progress = None
        except (TypeError, ValueError):
            progress = None
    if canonical == DatasetLearningCanonicalState.LEARNED and not rebuild_any:
        progress = 1.0
        phase = phase or "ready"

    truth = {
        "ready_brain_index_dominates_stale_job": True,
        "file_readiness_is_not_brain_readiness": True,
        "job_state_is_detail_not_truth": True,
        "prior_ready_usable_during_rebuild": prior_ready_preserved
        and canonical == DatasetLearningCanonicalState.REBUILDING,
        "stale_non_rebuild_job_ignored": stale,
        "missing_progress_is_not_fake_percent": progress is None
        or canonical
        in {
            DatasetLearningCanonicalState.LEARNED,
            DatasetLearningCanonicalState.INDEXING,
            DatasetLearningCanonicalState.INDEX_QUEUED,
            DatasetLearningCanonicalState.REBUILDING,
        },
        "canonical_owner": "DatasetService.learning_state_for_dataset",
    }

    return DatasetLearningState(
        dataset_id=dataset.dataset_id,
        version_id=version.version_id if version else (ready_idx.version_id if ready_idx else None),
        source_state=source_state,
        materialization_state=materialization_state,
        validation_state=validation_state,
        index_state=index_state,
        brain_state=canonical.value,
        job_state=job_state,
        progress=progress,
        phase=phase,
        index_id=index_id,
        document_count=int(document_count) if document_count is not None else None,
        chunk_count=int(chunk_count) if chunk_count is not None else None,
        embedding_mode=str(embedding_mode) if embedding_mode is not None else None,
        semantic_embeddings=bool(semantic) if semantic is not None else None,
        relations=relations,
        updated_at=updated_at,
        stale=stale,
        error=str(error) if error else None,
        truth=truth,
        canonical_state=canonical,
        brain_status=brain_status,
        label=label,
        learned=learned,
        source_missing=source_missing,
        job_id=job_id,
        usable_index_id=usable_index_id,
        prior_ready_preserved=prior_ready_preserved,
        learning=dict(learning_ladder or {}),
    )


def stale_index_jobs_to_reconcile(
    *,
    indexes: list[DatasetIndex],
    jobs: list[DatasetJob],
) -> list[DatasetJob]:
    """Return non-rebuild active INDEX jobs that are stale against a READY index.

    Callers should mark these INTERRUPTED/CANCELLED so they cannot leave the UI
    stuck on INDEXING forever after a successful learn.
    """
    ready = _latest_ready(indexes)
    if ready is None:
        return []
    out: list[DatasetJob] = []
    for job in _active_index_jobs(jobs):
        if _is_rebuild_job(job):
            continue
        # Auto-index or learn companions that raced after READY.
        out.append(job)
    return out
