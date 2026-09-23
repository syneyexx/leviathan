"""Benchmark contamination scanning against sealed evaluation sets (U265)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .types import CanonicalRecord


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
    passed: bool = True
    threshold: float = 0.35

    def public_dict(self) -> dict[str, Any]:
        return {
            "scanned_records": self.scanned_records,
            "sealed_cases": self.sealed_cases,
            "hits": [h.public_dict() for h in self.hits],
            "hit_count": len(self.hits),
            "passed": self.passed,
            "threshold": self.threshold,
            "truth": {
                "scan_against_sealed_eval_only": True,
                "contamination_is_operator_gate": True,
            },
        }


def scan_contamination(
    records: Iterable[CanonicalRecord],
    sealed_cases: Iterable[dict[str, Any]],
    *,
    ngram_n: int = 5,
    threshold: float = 0.35,
) -> ContaminationReport:
    """Detect exact and fuzzy n-gram overlap with sealed eval prompts/outputs."""
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

    hits: list[ContaminationHit] = []
    scanned = 0
    for rec in records:
        scanned += 1
        body = rec.text or ""
        if rec.messages:
            body = body + " " + " ".join(
                str(m.get("content") or "") for m in rec.messages if isinstance(m, dict)
            )
        if not body.strip():
            continue
        rh = _exact_hash(body)
        rn = _ngrams(body, ngram_n)
        for case_id, text, eh, en in sealed_index:
            if rh == eh:
                hits.append(
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
                hits.append(
                    ContaminationHit(
                        record_id=rec.id,
                        eval_case_id=case_id,
                        kind="fuzzy_ngram",
                        score=round(score, 4),
                        preview=body,
                    )
                )
    return ContaminationReport(
        scanned_records=scanned,
        sealed_cases=len(sealed_index),
        hits=hits,
        passed=len(hits) == 0,
        threshold=threshold,
    )
