"""Shared retrieval pipeline for Memory, history, Knowledge, Evidence and workspace files.

Lexical search remains the fully working local baseline. Optional semantic retrieval
activates only when an embedding provider is configured and available.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal


SourceKind = Literal[
    "memory",
    "conversation",
    "knowledge",
    "evidence",
    "workspace",
    "task_result",
    "other",
]


@dataclass(slots=True)
class RetrievalHit:
    hit_id: str
    kind: SourceKind
    content: str
    provenance: str
    score: float
    reasons: list[str] = field(default_factory=list)
    workspace_id: str | None = None
    source_version: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalFilters:
    workspace_id: str | None = None
    source_kinds: list[SourceKind] | None = None
    document_version: str | None = None
    max_age_days: int | None = None
    status_in: list[str] | None = None
    allowed_uris: list[str] | None = None


@dataclass(slots=True)
class RetrievalResult:
    hits: list[RetrievalHit]
    method: str
    lexical_count: int = 0
    semantic_count: int = 0
    deduped: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "method": self.method,
            "lexical_count": self.lexical_count,
            "semantic_count": self.semantic_count,
            "deduped": self.deduped,
            "notes": list(self.notes),
        }


_TOKEN_RE = re.compile(r"[a-zA-Z0-9à-ÿ]{2,}", re.I)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


# Opt-in multilingual expansion for NL↔EN retrieval (measured in functional campaign).
# Default off in production callers unless explicitly enabled — do not silently raise cost.
_ML_SYNONYMS: dict[str, tuple[str, ...]] = {
    "retrieval": ("ophalen", "zoeken", "retrieval"),
    "augmented": ("aangevuld", "augmented"),
    "generation": ("generatie", "generation"),
    "embedding": ("embeddings", "vector", "embedding"),
    "embeddings": ("embedding", "vectoren", "embeddings"),
    "memory": ("geheugen", "memory"),
    "knowledge": ("kennis", "knowledge"),
    "evidence": ("bewijs", "evidence", "bronnen"),
    "latency": ("vertraging", "latency"),
    "hybrid": ("hybride", "hybrid"),
    "lexical": ("lexicaal", "lexical", "trefwoord"),
    "semantic": ("semantisch", "semantic"),
    "zoeken": ("search", "retrieval", "zoeken"),
    "kennis": ("knowledge", "kennis"),
    "geheugen": ("memory", "geheugen"),
    "bewijs": ("evidence", "bewijs"),
    "generatie": ("generation", "generatie"),
    "rag": ("retrieval", "augmented", "generation", "rag"),
}


def expand_query_multilingual(query: str) -> str:
    """Expand query with NL/EN retrieval synonyms for lexical overlap.

    Does not call a model. Safe, cheap, opt-in.
    """
    tokens = tokenize(query)
    extra: list[str] = []
    for tok in tokens:
        for syn in _ML_SYNONYMS.get(tok, ()):
            if syn not in tokens and syn not in extra:
                extra.append(syn)
    if not extra:
        return query
    return f"{query} {' '.join(extra)}"


def lexical_score(query: str, content: str) -> tuple[float, list[str]]:
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0, []
    c_tokens = set(tokenize(content))
    if not c_tokens:
        return 0.0, []
    overlap = [token for token in q_tokens if token in c_tokens]
    if not overlap:
        return 0.0, []
    # TF-ish: unique overlap / sqrt(query len)
    score = len(set(overlap)) / math.sqrt(len(set(q_tokens)))
    reasons = [f"woordmatch:{token}" for token in list(dict.fromkeys(overlap))[:6]]
    return score, reasons


def content_fingerprint(content: str) -> str:
    normalized = re.sub(r"\s+", " ", (content or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def dedupe_hits(hits: list[RetrievalHit], *, diversity_window: int = 3) -> tuple[list[RetrievalHit], int]:
    """Drop near-identical passages and promote diversity of provenance."""
    seen_fp: set[str] = set()
    recent_prov: list[str] = []
    kept: list[RetrievalHit] = []
    dropped = 0
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        fp = content_fingerprint(hit.content)
        if fp in seen_fp:
            dropped += 1
            continue
        if hit.provenance in recent_prov[-diversity_window:]:
            # Soft penalty: skip if we already have enough from same provenance recently
            # unless score is uniquely high.
            if kept and hit.score < kept[-1].score * 0.98:
                dropped += 1
                continue
        seen_fp.add(fp)
        recent_prov.append(hit.provenance)
        kept.append(hit)
    return kept, dropped


def pack_hits_non_dumping(
    hits: list[RetrievalHit],
    *,
    max_hits: int = 8,
    max_chars_total: int = 6_000,
    max_chars_per_hit: int = 1_200,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    """Pack ranked hits under a hard character budget — never dump whole corpora.

    Prefers kind diversity (memory/knowledge/workspace/evidence) while keeping
    provenance labels intact for the UI evidence rail.
    """
    if max_hits <= 0 or max_chars_total <= 0:
        return [], {
            "packed_hits": 0,
            "dropped_hits": len(hits),
            "used_chars": 0,
            "max_chars_total": max_chars_total,
            "provenance_labels": [],
            "kind_counts": {},
            "truncated": False,
            "notes": ["non_dumping_budget_zero"],
        }

    ranked = sorted(hits, key=lambda item: item.score, reverse=True)
    kind_quota: dict[str, int] = {}
    packed: list[RetrievalHit] = []
    used = 0
    truncated = False
    notes: list[str] = []
    packed_ids: set[str] = set()

    def _try_pack(hit: RetrievalHit, *, enforce_kind_cap: bool) -> bool:
        nonlocal used, truncated
        if hit.hit_id in packed_ids:
            return False
        if len(packed) >= max_hits or used >= max_chars_total:
            return False
        kind = str(hit.kind)
        if enforce_kind_cap and kind_quota.get(kind, 0) >= 2:
            return False
        remain = max_chars_total - used
        cap = min(max_chars_per_hit, remain)
        if cap < 160:
            notes.append(f"budget_exhausted_before:{hit.hit_id}")
            return False
        content = hit.content or ""
        if len(content) > cap:
            marker = "\n… [truncated; provenance kept]"
            cut = max(80, cap - len(marker))
            content = content[:cut].rstrip() + marker
            truncated = True
            if len(content) > cap:
                content = content[:cap]
        packed.append(
            RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=content,
                provenance=hit.provenance,
                score=hit.score,
                reasons=list(hit.reasons),
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=dict(hit.metadata),
            )
        )
        used += len(content) + len(hit.provenance or "") + 8
        kind_quota[kind] = kind_quota.get(kind, 0) + 1
        packed_ids.add(hit.hit_id)
        return True

    # Pass 1: diversify kinds (max 2 each). Pass 2: fill remaining budget by score.
    for hit in ranked:
        _try_pack(hit, enforce_kind_cap=True)
    for hit in ranked:
        _try_pack(hit, enforce_kind_cap=False)

    dropped = max(0, len(hits) - len(packed))
    labels: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for hit in packed:
        pretty = str((hit.metadata or {}).get("provenance_label") or provenance_label(hit)).strip()
        raw = str(hit.provenance or "").strip()
        label = pretty or raw
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        labels.append({"kind": str(hit.kind), "label": label, "score": f"{hit.score:.3f}"})
        # Keep pretty label on the hit for context headers / UI.
        hit.metadata = {**(hit.metadata or {}), "provenance_label": label}

    return packed, {
        "packed_hits": len(packed),
        "dropped_hits": dropped,
        "used_chars": used,
        "max_chars_total": max_chars_total,
        "provenance_labels": labels,
        "kind_counts": dict(kind_quota),
        "truncated": truncated or dropped > 0,
        "notes": notes[:12] + (["non_dumping_pack_applied"] if packed or hits else ["non_dumping_empty"]),
    }


def merge_rank(
    lexical: list[RetrievalHit],
    semantic: list[RetrievalHit],
    *,
    lexical_weight: float = 0.55,
    semantic_weight: float = 0.45,
    limit: int = 8,
) -> RetrievalResult:
    """Combine lexical and semantic lists with explicit weights + dedupe/diversity."""
    by_id: dict[str, RetrievalHit] = {}
    for hit in lexical:
        merged = RetrievalHit(
            hit_id=hit.hit_id,
            kind=hit.kind,
            content=hit.content,
            provenance=hit.provenance,
            score=hit.score * lexical_weight,
            reasons=list(hit.reasons) + [f"rank:lexical*{lexical_weight}"],
            workspace_id=hit.workspace_id,
            source_version=hit.source_version,
            status=hit.status,
            metadata=dict(hit.metadata),
        )
        by_id[hit.hit_id] = merged
    for hit in semantic:
        if hit.hit_id in by_id:
            existing = by_id[hit.hit_id]
            existing.score += hit.score * semantic_weight
            existing.reasons.extend(list(hit.reasons) + [f"rank:semantic*{semantic_weight}"])
        else:
            by_id[hit.hit_id] = RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=hit.content,
                provenance=hit.provenance,
                score=hit.score * semantic_weight,
                reasons=list(hit.reasons) + [f"rank:semantic*{semantic_weight}"],
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=dict(hit.metadata),
            )
    merged_list = list(by_id.values())
    deduped, dropped = dedupe_hits(merged_list)
    method = "hybrid" if lexical and semantic else ("lexical" if lexical else ("semantic" if semantic else "empty"))
    return RetrievalResult(
        hits=deduped[: max(limit * 3, limit)],
        method=method,
        lexical_count=len(lexical),
        semantic_count=len(semantic),
        deduped=dropped,
        notes=[] if semantic else ["semantic_unavailable_lexical_fallback"],
    )


def provenance_label(hit: RetrievalHit) -> str:
    """Human-readable provenance label for UI rails and context headers."""
    title = str((hit.metadata or {}).get("title") or "").strip()
    scope = str((hit.metadata or {}).get("scope") or "").strip()
    heading = str((hit.metadata or {}).get("heading") or "").strip()
    base = hit.provenance or f"{hit.kind}:{hit.hit_id}"
    if hit.kind == "memory":
        label = title or base
        if scope:
            return f"memory · {label} ({scope})"
        return f"memory · {label}"
    if hit.kind == "knowledge":
        parts = [title or base]
        if heading:
            parts.append(heading[:80])
        if hit.provenance and hit.provenance not in parts[0]:
            parts.append(hit.provenance)
        return "knowledge · " + " · ".join(parts[:3])
    if title:
        return f"{hit.kind} · {title}"
    return f"{hit.kind} · {base}"


def rerank_hits(
    query: str,
    hits: list[RetrievalHit],
    *,
    limit: int = 8,
) -> list[RetrievalHit]:
    """Second-pass local rerank: term density, title boost, anti-dump length penalty.

    Does not require embeddings. Prefers concise, query-aligned passages over long dumps.
    """
    q_tokens = tokenize(query)
    q_unique = list(dict.fromkeys(q_tokens))
    if not hits:
        return []
    if not q_unique:
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]

    reranked: list[RetrievalHit] = []
    for hit in hits:
        title = str((hit.metadata or {}).get("title") or "")
        heading = str((hit.metadata or {}).get("heading") or "")
        blob = f"{title}\n{heading}\n{hit.content}"
        c_tokens = tokenize(blob)
        if not c_tokens:
            continue
        overlap = [token for token in q_unique if token in set(c_tokens)]
        coverage = len(overlap) / max(1, len(q_unique))
        # Density: how concentrated query terms are (penalize huge sparse dumps).
        density = len(overlap) / math.sqrt(max(1, len(c_tokens)))
        title_hits = sum(1 for token in q_unique if token in set(tokenize(title)))
        title_boost = 0.18 * title_hits
        # Soft length penalty after ~900 chars of content.
        length_penalty = max(0.0, (len(hit.content) - 900) / 4000.0) * 0.25
        scope = str((hit.metadata or {}).get("scope") or "")
        scope_boost = 0.05 if scope == "project" else (0.08 if scope == "global" else 0.0)
        final = hit.score + (0.55 * coverage) + (0.35 * density) + title_boost + scope_boost - length_penalty
        reasons = list(hit.reasons) + [
            f"rerank:coverage:{coverage:.2f}",
            f"rerank:density:{density:.2f}",
        ]
        if title_boost:
            reasons.append(f"rerank:title_boost:{title_boost:.2f}")
        if length_penalty:
            reasons.append(f"rerank:length_penalty:{length_penalty:.2f}")
        meta = dict(hit.metadata)
        meta["provenance_label"] = provenance_label(hit)
        reranked.append(
            RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=hit.content,
                provenance=hit.provenance,
                score=final,
                reasons=reasons,
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=meta,
            )
        )
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked[:limit]


def budget_hit_contents(
    hits: list[RetrievalHit],
    *,
    max_total_chars: int,
    max_per_hit_chars: int = 1200,
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    """Clip retrieved passages under a shared character budget (non-dumping)."""
    if max_total_chars <= 0:
        return [], {"kept": 0, "dropped": len(hits), "used_chars": 0, "truncated": bool(hits)}
    kept: list[RetrievalHit] = []
    used = 0
    dropped = 0
    truncated = 0
    for hit in hits:
        label = str((hit.metadata or {}).get("provenance_label") or provenance_label(hit))
        overhead = len(label) + 48
        remain = max_total_chars - used - overhead
        if remain < 120:
            dropped += 1
            continue
        content = hit.content or ""
        limit = min(max_per_hit_chars, remain)
        if len(content) > limit:
            clipped = content[: max(80, limit - 40)]
            boundary = max(clipped.rfind("\n"), clipped.rfind(". "), clipped.rfind("; "))
            if boundary > 60:
                clipped = clipped[: boundary + 1]
            content = clipped.rstrip() + f"\n… [truncated; {label}]"
            truncated += 1
        meta = dict(hit.metadata)
        meta["provenance_label"] = label
        kept.append(
            RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=content,
                provenance=hit.provenance,
                score=hit.score,
                reasons=list(hit.reasons),
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=meta,
            )
        )
        used += overhead + len(content)
    return kept, {
        "kept": len(kept),
        "dropped": dropped,
        "used_chars": used,
        "truncated": truncated,
        "max_total_chars": max_total_chars,
    }


def apply_filters(hits: list[RetrievalHit], filters: RetrievalFilters | None) -> list[RetrievalHit]:
    if not filters:
        return hits
    result: list[RetrievalHit] = []
    for hit in hits:
        if filters.workspace_id and hit.workspace_id and hit.workspace_id != filters.workspace_id:
            continue
        if filters.source_kinds and hit.kind not in filters.source_kinds:
            continue
        if filters.document_version and hit.source_version and hit.source_version != filters.document_version:
            continue
        if filters.status_in and hit.status and hit.status not in filters.status_in:
            continue
        if filters.allowed_uris and hit.provenance not in filters.allowed_uris:
            continue
        result.append(hit)
    return result


EmbeddingFn = Callable[[str], list[float] | None]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_score_texts(
    query: str,
    candidates: list[RetrievalHit],
    embed: EmbeddingFn,
) -> list[RetrievalHit]:
    """Optional semantic scoring. Returns empty when embeddings unavailable."""
    q_vec = embed(query)
    if not q_vec:
        return []
    scored: list[RetrievalHit] = []
    for hit in candidates:
        vec = embed(hit.content[:4000])
        if not vec:
            continue
        if len(vec) != len(q_vec):
            # Never mix unequal embedding dimensions into one cosine score.
            continue
        score = cosine(q_vec, vec)
        if score <= 0:
            continue
        scored.append(
            RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=hit.content,
                provenance=hit.provenance,
                score=score,
                reasons=[f"semantische_overeenkomst:{score:.3f}"],
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=dict(hit.metadata),
            )
        )
    return scored


def semantic_score_indexed(
    query: str,
    candidates: list[RetrievalHit],
    *,
    embed_query: EmbeddingFn,
    lookup_vector: Callable[[str], list[float] | None],
) -> list[RetrievalHit]:
    """Score candidates via query embed + persistent index vectors.

    Returns empty when the query embed fails or no indexed vectors are usable —
    callers must fall back to lexical. Dimension mismatches are skipped, never mixed.
    """
    q_vec = embed_query(query)
    if not q_vec:
        return []
    scored: list[RetrievalHit] = []
    for hit in candidates:
        try:
            vec = lookup_vector(hit.hit_id)
        except Exception:
            continue
        if not vec:
            continue
        if len(vec) != len(q_vec):
            continue
        score = cosine(q_vec, vec)
        if score <= 0:
            continue
        scored.append(
            RetrievalHit(
                hit_id=hit.hit_id,
                kind=hit.kind,
                content=hit.content,
                provenance=hit.provenance,
                score=score,
                reasons=[f"semantische_index:{score:.3f}"],
                workspace_id=hit.workspace_id,
                source_version=hit.source_version,
                status=hit.status,
                metadata=dict(hit.metadata),
            )
        )
    return scored


def build_lexical_hits_from_records(
    query: str,
    records: list[dict[str, Any]],
    *,
    kind: SourceKind,
    content_key: str = "content",
    title_key: str = "title",
    id_key: str = "id",
    provenance_key: str | None = None,
    workspace_key: str = "workspace_id",
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for index, record in enumerate(records):
        title = str(record.get(title_key) or "")
        content = str(record.get(content_key) or record.get("summary") or "")
        heading = str(record.get("heading") or "")
        blob = f"{title}\n{heading}\n{content}".strip()
        score, reasons = lexical_score(query, blob)
        if score <= 0:
            continue
        rid = str(record.get(id_key) or index)
        if provenance_key:
            prov = str(record.get(provenance_key) or record.get("uri") or f"{kind}:{rid}")
        else:
            prov = str(record.get("uri") or f"{kind}:{rid}")
        hits.append(
            RetrievalHit(
                hit_id=f"{kind}-{rid}",
                kind=kind,
                content=blob[:2000],
                provenance=prov,
                score=score,
                reasons=reasons,
                workspace_id=str(record.get(workspace_key)) if record.get(workspace_key) else None,
                source_version=str(record.get("content_hash") or record.get("version") or "") or None,
                status=str(record.get("status")) if record.get("status") is not None else None,
                metadata={
                    "title": title,
                    "heading": heading,
                    "scope": str(record.get("scope") or "") or None,
                    "collection": str(record.get("collection") or "") or None,
                },
            )
        )
    return hits


class EmbeddingIndexState:
    """Track embedding model + index version for resumable rebuilds.

    Embeddings are invalidated when content hash, model id, or index version changes.
    """

    def __init__(self, *, embedding_model: str | None = None, index_version: int = 1) -> None:
        self.embedding_model: str | None = embedding_model
        self.index_version: int = int(index_version)
        self.fingerprints: dict[str, str] = {}  # source_id -> content hash
        self.embedding_keys: dict[str, str] = {}  # source_id -> embedding_key
        self.deleted: set[str] = set()

    def embedding_key_for(self, content_hash: str) -> str | None:
        if not self.embedding_model:
            return None
        from reasoning.knowledge_freshness import embedding_key

        return embedding_key(
            content_hash=content_hash,
            model_id=self.embedding_model,
            index_version=self.index_version,
        )

    def needs_reindex(self, source_id: str, content_hash: str) -> bool:
        if source_id in self.deleted:
            return True
        if self.fingerprints.get(source_id) != content_hash:
            return True
        expected = self.embedding_key_for(content_hash)
        if expected is None:
            # Semantic unavailable — lexical still works; no embedding reindex required.
            return False
        return self.embedding_keys.get(source_id) != expected

    def mark_indexed(self, source_id: str, content_hash: str) -> None:
        self.fingerprints[source_id] = content_hash
        key = self.embedding_key_for(content_hash)
        if key:
            self.embedding_keys[source_id] = key
        self.deleted.discard(source_id)

    def mark_deleted(self, source_id: str) -> None:
        self.deleted.add(source_id)
        self.fingerprints.pop(source_id, None)
        self.embedding_keys.pop(source_id, None)

    def set_model(self, model_id: str | None) -> dict[str, Any]:
        changed = model_id != self.embedding_model
        self.embedding_model = model_id
        if changed:
            self.index_version += 1
            self.embedding_keys.clear()
        return {
            "embedding_model": self.embedding_model,
            "index_version": self.index_version,
            "model_changed": changed,
            "semantic_available": bool(self.embedding_model),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "embedding_model": self.embedding_model,
            "index_version": self.index_version,
            "fingerprints": dict(self.fingerprints),
            "embedding_keys": dict(self.embedding_keys),
            "deleted": sorted(self.deleted),
            "semantic_available": bool(self.embedding_model),
        }
