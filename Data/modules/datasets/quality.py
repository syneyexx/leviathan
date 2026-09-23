"""Dataset quality helpers — semantic dedupe, train/eval separation, balance."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable

from .types import CanonicalRecord


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[^\W_]{2,}", _normalize(text), flags=re.UNICODE)}


def semantic_fingerprint(record: CanonicalRecord, *, shingle: int = 3) -> str:
    """Canonical semantic fingerprint BEFORE run-specific metadata is attached."""
    text = _normalize(record.text or "")
    if record.messages:
        parts = []
        for msg in record.messages:
            if isinstance(msg, dict):
                parts.append(str(msg.get("content") or ""))
        text = _normalize(" ".join(parts) or text)
    toks = text.split()
    if len(toks) >= shingle:
        shingles = [" ".join(toks[i : i + shingle]) for i in range(len(toks) - shingle + 1)]
        payload = "|".join(sorted(set(shingles))[:200])
    else:
        payload = text
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_dedupe(
    records: list[CanonicalRecord],
    *,
    jaccard_threshold: float = 0.9,
) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    """Deduplicate by semantic fingerprint + high Jaccard overlap (text only)."""
    kept: list[CanonicalRecord] = []
    kept_fps: list[str] = []
    kept_tokens: list[set[str]] = []
    removed: list[str] = []
    for rec in records:
        fp = semantic_fingerprint(rec)
        toks = _tokens(rec.text or "")
        drop = False
        if fp in kept_fps:
            drop = True
        else:
            for prior in kept_tokens:
                if not toks or not prior:
                    continue
                inter = len(toks & prior)
                union = len(toks | prior) or 1
                if inter / union >= jaccard_threshold:
                    drop = True
                    break
        if drop:
            removed.append(rec.id)
            continue
        kept.append(rec)
        kept_fps.append(fp)
        kept_tokens.append(toks)
    stats = {
        "inputCount": len(records),
        "outputCount": len(kept),
        "removedCount": len(removed),
        "removedIds": removed[:100],
        "method": "semantic_fingerprint_jaccard",
        "jaccard_threshold": jaccard_threshold,
        "truth": {"dedupe_before_run_metadata": True},
    }
    return kept, stats


def train_eval_separation(
    train: Iterable[CanonicalRecord],
    eval_set: Iterable[CanonicalRecord],
    *,
    jaccard_threshold: float = 0.85,
) -> dict[str, Any]:
    """Ensure train does not contain near-duplicates of eval (never optimize on hidden eval)."""
    train_list = list(train)
    eval_list = list(eval_set)
    eval_fps = {semantic_fingerprint(r) for r in eval_list}
    eval_tokens = [_tokens(r.text or "") for r in eval_list]
    leaks: list[dict[str, Any]] = []
    for rec in train_list:
        fp = semantic_fingerprint(rec)
        if fp in eval_fps:
            leaks.append({"train_id": rec.id, "kind": "exact_semantic_fingerprint"})
            continue
        toks = _tokens(rec.text or "")
        for ev, etoks in zip(eval_list, eval_tokens):
            if not toks or not etoks:
                continue
            inter = len(toks & etoks)
            union = len(toks | etoks) or 1
            score = inter / union
            if score >= jaccard_threshold:
                leaks.append(
                    {
                        "train_id": rec.id,
                        "eval_id": ev.id,
                        "kind": "jaccard",
                        "score": round(score, 4),
                    }
                )
                break
    return {
        "train_count": len(train_list),
        "eval_count": len(eval_list),
        "leak_count": len(leaks),
        "leaks": leaks[:50],
        "passed": len(leaks) == 0,
        "truth": {"never_optimize_on_hidden_eval": True},
    }


def quality_balance_report(records: Iterable[CanonicalRecord]) -> dict[str, Any]:
    """Heuristic domain / language / difficulty distribution (not a model claim)."""
    rows = list(records)
    domains: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    difficulties: Counter[str] = Counter()
    licensed = 0
    for rec in rows:
        meta = rec.metadata or {}
        labels = rec.labels or {}
        domains[str(meta.get("domain") or labels.get("domain") or "unknown")] += 1
        languages[str(meta.get("language") or labels.get("language") or _guess_lang(rec.text or ""))] += 1
        difficulties[str(meta.get("difficulty") or labels.get("difficulty") or "unspecified")] += 1
        if meta.get("license") or meta.get("licensing"):
            licensed += 1
    return {
        "record_count": len(rows),
        "domain_balance": dict(domains),
        "language_balance": dict(languages),
        "difficulty_distribution": dict(difficulties),
        "licensing_metadata_present": licensed,
        "licensing_coverage": round(licensed / max(len(rows), 1), 4),
        "truth": {
            "heuristic_balance_is_not_demographic_proof": True,
            "source_provenance_expected_in_metadata": True,
        },
    }


def _guess_lang(text: str) -> str:
    lowered = text.lower()
    dutch_markers = (" de ", " het ", " een ", " van ", " niet ", " voor ", " met ")
    if any(m in f" {lowered} " for m in dutch_markers):
        return "nl"
    if re.search(r"[a-z]", lowered):
        return "en"
    return "unknown"
