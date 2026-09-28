"""Weighted ingestion progress model — measurable phases, honest UNMEASURED.

Progress may not move backwards except explicit retry/reset.
ETA is only emitted when defensibly estimable from throughput samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import IngestionPhase


# Defensible phase weight bands (cumulative end percentages).
PHASE_WEIGHT_ENDS: dict[IngestionPhase, float] = {
    IngestionPhase.UPLOADING: 3.0,
    IngestionPhase.STORED: 3.0,
    IngestionPhase.QUEUED: 6.0,
    IngestionPhase.INSPECTING: 10.0,
    IngestionPhase.EXPANDING: 18.0,
    IngestionPhase.CLASSIFYING: 28.0,
    IngestionPhase.PARSING: 45.0,
    IngestionPhase.NORMALIZING: 52.0,
    IngestionPhase.BRAIN_PENDING: 62.0,
    IngestionPhase.BRAIN_SYNCING: 96.0,
    IngestionPhase.COMPLETED: 100.0,
    IngestionPhase.PARTIAL: 100.0,
    IngestionPhase.FAILED: 100.0,
    IngestionPhase.CANCELLED: 100.0,
    IngestionPhase.QUARANTINED: 100.0,
    IngestionPhase.SKIPPED: 100.0,
}

PHASE_WEIGHT_STARTS: dict[IngestionPhase, float] = {
    IngestionPhase.UPLOADING: 0.0,
    IngestionPhase.STORED: 0.0,
    IngestionPhase.QUEUED: 3.0,
    IngestionPhase.INSPECTING: 6.0,
    IngestionPhase.EXPANDING: 10.0,
    IngestionPhase.CLASSIFYING: 18.0,
    IngestionPhase.PARSING: 28.0,
    IngestionPhase.NORMALIZING: 45.0,
    IngestionPhase.BRAIN_PENDING: 52.0,
    IngestionPhase.BRAIN_SYNCING: 62.0,
    IngestionPhase.COMPLETED: 96.0,
    IngestionPhase.PARTIAL: 96.0,
    IngestionPhase.FAILED: 96.0,
    IngestionPhase.CANCELLED: 96.0,
    IngestionPhase.QUARANTINED: 96.0,
    IngestionPhase.SKIPPED: 96.0,
}


@dataclass(frozen=True)
class WeightedProgress:
    progress_pct: float | None
    phase: IngestionPhase
    phase_progress_pct: float | None
    processed_units: int | None
    total_units: int | None
    unit_kind: str | None
    bytes_processed: int | None
    bytes_total: int | None
    throughput: float | None
    eta_seconds: float | None
    measured: bool
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "progress_pct": self.progress_pct,
            "phase": self.phase.value,
            "phase_progress_pct": self.phase_progress_pct,
            "processed_units": self.processed_units,
            "total_units": self.total_units,
            "unit_kind": self.unit_kind,
            "bytes_processed": self.bytes_processed,
            "bytes_total": self.bytes_total,
            "throughput": self.throughput,
            "eta_seconds": self.eta_seconds,
            "measured": self.measured,
            "notes": list(self.notes),
            "truth": {
                "unmeasuredOnlyWhenImpossible": True,
                "etaOnlyWhenDefensible": True,
                "monotonicExceptRetryReset": True,
            },
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def compute_weighted_progress(
    *,
    phase: IngestionPhase,
    files_discovered: int = 0,
    files_done: int = 0,
    brain_synced: int = 0,
    brain_target: int = 0,
    bytes_processed: int | None = None,
    bytes_total: int | None = None,
    pages_parsed: int | None = None,
    pages_total: int | None = None,
    chunks_done: int | None = None,
    chunks_total: int | None = None,
    embedding_batches_done: int | None = None,
    embedding_batches_total: int | None = None,
    elapsed_seconds: float | None = None,
    previous_progress_pct: float | None = None,
    allow_regression: bool = False,
) -> WeightedProgress:
    """Compute weighted phase progress.

    Uses the best available unit kind for the current phase. Returns
    ``progress_pct=None`` only when measurement is genuinely impossible.
    """
    notes: list[str] = []
    start = PHASE_WEIGHT_STARTS.get(phase, 0.0)
    end = PHASE_WEIGHT_ENDS.get(phase, 100.0)
    span = max(0.0, end - start)

    unit_kind: str | None = None
    processed: int | None = None
    total: int | None = None
    phase_frac: float | None = None

    if phase in {IngestionPhase.COMPLETED, IngestionPhase.PARTIAL, IngestionPhase.SKIPPED}:
        return WeightedProgress(
            progress_pct=100.0,
            phase=phase,
            phase_progress_pct=100.0,
            processed_units=files_done or files_discovered or None,
            total_units=files_discovered or None,
            unit_kind="files" if files_discovered else None,
            bytes_processed=bytes_processed,
            bytes_total=bytes_total,
            throughput=None,
            eta_seconds=None,
            measured=True,
            notes=tuple(notes),
        )

    if phase in {IngestionPhase.FAILED, IngestionPhase.CANCELLED, IngestionPhase.QUARANTINED}:
        # Terminal non-success: report last known band end without inventing success.
        base = previous_progress_pct if previous_progress_pct is not None else end
        return WeightedProgress(
            progress_pct=_clamp(base),
            phase=phase,
            phase_progress_pct=None,
            processed_units=files_done or None,
            total_units=files_discovered or None,
            unit_kind="files" if files_discovered else None,
            bytes_processed=bytes_processed,
            bytes_total=bytes_total,
            throughput=None,
            eta_seconds=None,
            measured=previous_progress_pct is not None or files_discovered > 0,
            notes=("terminal_non_success",),
        )

    # Prefer the most specific measurable unit for the phase.
    if phase == IngestionPhase.BRAIN_SYNCING and (brain_target > 0 or files_discovered > 0):
        unit_kind = "brain_documents"
        total = brain_target or max(files_discovered - 0, 0) or None
        processed = brain_synced
        if total and total > 0:
            phase_frac = min(1.0, processed / total)
    elif phase in {IngestionPhase.PARSING, IngestionPhase.NORMALIZING} and pages_total and pages_total > 0:
        unit_kind = "pages"
        total = pages_total
        processed = int(pages_parsed or 0)
        phase_frac = min(1.0, processed / total)
    elif chunks_total and chunks_total > 0 and phase in {IngestionPhase.NORMALIZING, IngestionPhase.BRAIN_PENDING}:
        unit_kind = "chunks"
        total = chunks_total
        processed = int(chunks_done or 0)
        phase_frac = min(1.0, processed / total)
    elif embedding_batches_total and embedding_batches_total > 0 and phase == IngestionPhase.BRAIN_PENDING:
        unit_kind = "embedding_batches"
        total = embedding_batches_total
        processed = int(embedding_batches_done or 0)
        phase_frac = min(1.0, processed / total)
    elif files_discovered > 0 and phase in {
        IngestionPhase.EXPANDING,
        IngestionPhase.CLASSIFYING,
        IngestionPhase.PARSING,
        IngestionPhase.NORMALIZING,
        IngestionPhase.BRAIN_PENDING,
        IngestionPhase.BRAIN_SYNCING,
    }:
        unit_kind = "files"
        total = files_discovered
        processed = min(files_done, files_discovered)
        phase_frac = min(1.0, processed / total) if total else None
    elif bytes_total and bytes_total > 0 and bytes_processed is not None:
        unit_kind = "bytes"
        total = int(bytes_total)
        processed = int(bytes_processed)
        phase_frac = min(1.0, processed / total)

    if phase_frac is None:
        # Phase entered but intra-phase units unknown — report phase start band.
        if phase in {IngestionPhase.UPLOADING, IngestionPhase.STORED, IngestionPhase.QUEUED, IngestionPhase.INSPECTING}:
            # Early phases are measurable by existence of the job itself.
            progress = start if phase != IngestionPhase.STORED else end
            return WeightedProgress(
                progress_pct=round(progress, 2),
                phase=phase,
                phase_progress_pct=0.0 if phase != IngestionPhase.STORED else 100.0,
                processed_units=processed,
                total_units=total,
                unit_kind=unit_kind,
                bytes_processed=bytes_processed,
                bytes_total=bytes_total,
                throughput=None,
                eta_seconds=None,
                measured=True,
                notes=tuple(notes),
            )
        notes.append("phase_units_unmeasured")
        progress = start
        measured = False
        phase_progress_pct = None
    else:
        progress = start + span * phase_frac
        measured = True
        phase_progress_pct = round(100.0 * phase_frac, 2)

    if previous_progress_pct is not None and not allow_regression:
        if progress + 1e-9 < previous_progress_pct:
            notes.append("monotonic_clamp")
            progress = previous_progress_pct

    throughput = None
    eta = None
    if (
        measured
        and elapsed_seconds
        and elapsed_seconds > 0
        and processed
        and total
        and processed > 0
        and total > processed
    ):
        throughput = float(processed) / float(elapsed_seconds)
        if throughput > 0:
            eta = float(total - processed) / throughput
            # Only emit ETA when we have enough samples to be defensible.
            if processed < 3:
                notes.append("eta_suppressed_insufficient_samples")
                eta = None

    if not measured and phase_frac is None and files_discovered <= 0 and not bytes_total:
        return WeightedProgress(
            progress_pct=None,
            phase=phase,
            phase_progress_pct=None,
            processed_units=None,
            total_units=None,
            unit_kind=None,
            bytes_processed=bytes_processed,
            bytes_total=bytes_total,
            throughput=None,
            eta_seconds=None,
            measured=False,
            notes=tuple(notes + ["UNMEASURED"]),
        )

    return WeightedProgress(
        progress_pct=round(_clamp(progress), 2),
        phase=phase,
        phase_progress_pct=phase_progress_pct,
        processed_units=processed,
        total_units=total,
        unit_kind=unit_kind,
        bytes_processed=bytes_processed,
        bytes_total=bytes_total,
        throughput=throughput,
        eta_seconds=eta,
        measured=measured,
        notes=tuple(notes),
    )
