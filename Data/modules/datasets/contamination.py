"""Benchmark contamination scanning against sealed evaluation sets (U265)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .types import CanonicalRecord


CancelCheck = Callable[[], bool]
ProgressCb = Callable[[dict[str, Any]], None]

# Hard ceiling on retained hit objects — total count is tracked separately.
DEFAULT_MAX_RETAINED_HITS = 200


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _ngrams(text: str, n: int = 5) -> set[str]:
    tokens = _normalize(text).split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _exact_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


@dataclass
class ContaminationHit:
    record_id: str
    eval_case_id: str
    kind: str  # exact | fuzzy_ngram
    score: float
    preview: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "eval_case_id": self.eval_case_id,
            "kind": self.kind,
            "score": self.score,
            "preview": self.preview[:160],
        }


@dataclass
class ContaminationReport:
    scanned_records: int
    sealed_cases: int
    hits: list[ContaminationHit] = field(default_factory=list)
    hit_count: int = 0
    hits_truncated: bool = False
    passed: bool = True
    threshold: float = 0.35
    evidence_class: str = "UNMEASURED"
    cancelled: bool = False
    progress: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scanned_records": self.scanned_records,
            "sealed_cases": self.sealed_cases,
            "hits": [h.public_dict() for h in self.hits],
            "hit_count": int(self.hit_count),
            "hitsRetained": len(self.hits),
            "hitsTruncated": self.hits_truncated,
            "passed": self.passed,
            "threshold": self.threshold,
            "evidenceClass": self.evidence_class,
            "cancelled": self.cancelled,
            "progress": dict(self.progress),
            "truth": {
                "scan_against_sealed_eval_only": True,
                "contamination_is_operator_gate": True,
                "evidenceClass": self.evidence_class,
                "noReferenceCorpusIsNotClean": self.evidence_class == "UNMEASURED",
                "hit_count_is_total_not_retained": True,
                "truncation_does_not_downgrade_measured_quality": True,
                "cancellation_is_not_a_clean_pass": True,
            },
        }


def scan_contamination(
    records: Iterable[CanonicalRecord],
    sealed_cases: Iterable[dict[str, Any]],
    *,
    ngram_n: int = 5,
    threshold: float = 0.35,
    max_retained_hits: int = DEFAULT_MAX_RETAINED_HITS,
    cancel_check: CancelCheck | None = None,
    progress_cb: ProgressCb | None = None,
    progress_every: int = 50,
) -> ContaminationReport:
    """Detect exact and fuzzy n-gram overlap with sealed eval prompts/outputs.

    P2-003:
    - Retained ``hits`` are bounded by ``max_retained_hits``.
    - ``hit_count`` always reflects the total matches found.
    - Cancellation / incomplete scans never silently report a clean pass.
    - Truncating retained hits does not downgrade a completed measured scan's
      evidence class (EXACT stays EXACT; ``passed`` still uses total hit_count).
    """
    sealed = list(sealed_cases)
    sealed_index: list[tuple[str, str, str, set[str]]] = []
    for case in sealed:
        case_id = str(case.get("case_id") or case.get("id") or "")
        text = " ".join(
            str(case.get(k) or "")
            for k in ("prompt", "input", "expected", "output", "text")
            if case.get(k)
        )
        if not text.strip():
            continue
        sealed_index.append((case_id, text, _exact_hash(text), _ngrams(text, ngram_n)))

    retain_limit = max(1, int(max_retained_hits))
    hits: list[ContaminationHit] = []
    hit_count = 0
    hits_truncated = False
    scanned = 0
    cancelled = False
    progress_every = max(1, int(progress_every))

    def _retain(hit: ContaminationHit) -> None:
        nonlocal hit_count, hits_truncated
        hit_count += 1
        if len(hits) < retain_limit:
            hits.append(hit)
        else:
            hits_truncated = True

    def _emit(phase: str) -> None:
        if not progress_cb:
            return
        progress_cb(
            {
                "phase": phase,
                "scannedRecords": scanned,
                "hitCount": hit_count,
                "hitsRetained": len(hits),
                "hitsTruncated": hits_truncated,
                "sealedCases": len(sealed_index),
                "cancelled": cancelled,
            }
        )

    measured = len(sealed_index) > 0
    if progress_cb:
        _emit("starting")

    for rec in records:
        if cancel_check is not None and cancel_check():
            cancelled = True
            break
        scanned += 1
        body = rec.text or ""
        if rec.messages:
            body = body + " " + " ".join(
                str(m.get("content") or "") for m in rec.messages if isinstance(m, dict)
            )
        if not body.strip():
            if scanned % progress_every == 0:
                _emit("scanning")
            continue
        rh = _exact_hash(body)
        rn = _ngrams(body, ngram_n)
        for case_id, text, eh, en in sealed_index:
            if rh == eh:
                _retain(
                    ContaminationHit(
                        record_id=rec.id,
                        eval_case_id=case_id,
                        kind="exact",
                        score=1.0,
                        preview=body,
                    )
                )
                continue
            if not rn or not en:
                continue
            score = len(rn & en) / float(len(rn | en))
            if score >= threshold:
                _retain(
                    ContaminationHit(
                        record_id=rec.id,
                        eval_case_id=case_id,
                        kind="fuzzy_ngram",
                        score=round(score, 4),
                        preview=body,
                    )
                )
        if scanned % progress_every == 0:
            _emit("scanning")

    if cancelled:
        # Incomplete scan must not claim clean / EXACT.
        evidence = "UNMEASURED"
        passed = False
        _emit("cancelled")
    elif not measured:
        evidence = "UNMEASURED"
        passed = False
        _emit("completed")
    else:
        evidence = "EXACT"
        # Quality uses total hit_count, never the truncated retained list length.
        passed = hit_count == 0
        _emit("completed")

    return ContaminationReport(
        scanned_records=scanned,
        sealed_cases=len(sealed_index),
        hits=hits,
        hit_count=hit_count,
        hits_truncated=hits_truncated,
        passed=passed,
        threshold=threshold,
        evidence_class=evidence,
        cancelled=cancelled,
        progress={
            "scannedRecords": scanned,
            "hitCount": hit_count,
            "hitsRetained": len(hits),
            "hitsTruncated": hits_truncated,
            "cancelled": cancelled,
        },
    )
