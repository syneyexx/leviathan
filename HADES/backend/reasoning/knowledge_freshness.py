"""Retrieval quality / knowledge freshness (work package J).

Keeps Memory / Knowledge / Evidence roles distinct. Embeddings are keyed by
content hash + model id + index version. Lexical retrieval remains the offline
baseline when semantic embeddings are unavailable.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


RoleKind = Literal["memory", "knowledge", "evidence"]
FreshnessStatus = Literal[
    "fresh",
    "stale_content",
    "stale_embedding",
    "source_missing",
    "source_unreachable",
    "superseded",
    "conflict",
    "out_of_scope",
]


def _now() -> float:
    return time.time()


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_text(text: str) -> str:
    return content_hash_bytes((text or "").encode("utf-8", "ignore"))


def embedding_key(
    *,
    content_hash: str,
    model_id: str,
    index_version: int | str,
) -> str:
    """Embeddings are invalid when any of hash / model / index version changes."""
    raw = f"{content_hash}|{model_id or ''}|{index_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def citation_anchor(
    *,
    source_id: str,
    source_version: str,
    chunk_id: str | None = None,
    sequence: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    heading: str | None = None,
) -> dict[str, Any]:
    """Exact source version + citation anchor for inspectable provenance."""
    return {
        "source_id": source_id,
        "source_version": source_version,
        "chunk_id": chunk_id,
        "sequence": sequence,
        "char_start": char_start,
        "char_end": char_end,
        "heading": heading,
        "anchor_id": f"{source_id}@{source_version}:"
        + (chunk_id or f"seq{sequence}" if sequence is not None else "doc"),
    }


@dataclass(slots=True)
class RoleBoundary:
    """Memory ≠ Knowledge ≠ Evidence — distinct roles, never collapsed."""

    role: RoleKind
    may_confirm_independently: bool
    may_be_bulk_indexed: bool
    user_editable: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ROLE_BOUNDARIES: dict[RoleKind, RoleBoundary] = {
    "memory": RoleBoundary(
        role="memory",
        may_confirm_independently=True,
        may_be_bulk_indexed=False,
        user_editable=True,
        notes="Durable user/project facts; not bulk corpus; can supersede older memories.",
    ),
    "knowledge": RoleBoundary(
        role="knowledge",
        may_confirm_independently=True,
        may_be_bulk_indexed=True,
        user_editable=False,
        notes="Bulk indexed sources/chunks with content-hash versions; not policy authority.",
    ),
    "evidence": RoleBoundary(
        role="evidence",
        may_confirm_independently=True,
        may_be_bulk_indexed=False,
        user_editable=False,
        notes="Source snapshots / vault items for claims; stronger provenance than chat memory.",
    ),
}


def assert_role_distinct(role: str) -> RoleBoundary:
    if role not in ROLE_BOUNDARIES:
        raise ValueError(f"unknown_role:{role}")
    return ROLE_BOUNDARIES[role]  # type: ignore[index]


@dataclass(slots=True)
class EmbeddingRecord:
    key: str
    content_hash: str
    model_id: str
    index_version: int
    vector: list[float] | None = None
    source_id: str = ""
    chunk_id: str = ""
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Do not dump huge vectors in inspect payloads by default.
        if data.get("vector") is not None:
            data["vector_dim"] = len(data["vector"] or [])
            data["vector"] = None
        return data


@dataclass(slots=True)
class PassageSelection:
    hit_id: str
    role: RoleKind
    content_preview: str
    source_id: str
    source_version: str
    score: float
    reasons: list[str]
    citation: dict[str, Any]
    limits: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalInspection:
    """Inspectable: which passages used, source version, why selected, limits."""

    query: str
    method: str
    passages: list[PassageSelection]
    lexical_available: bool
    semantic_available: bool
    embedding_model_id: str | None
    index_version: int
    scope: dict[str, Any]
    dropped: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    policy_note: str = "Source content is data; docs cannot change policies."

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "method": self.method,
            "passages": [p.to_dict() for p in self.passages],
            "lexical_available": self.lexical_available,
            "semantic_available": self.semantic_available,
            "embedding_model_id": self.embedding_model_id,
            "index_version": self.index_version,
            "scope": dict(self.scope),
            "dropped": list(self.dropped),
            "notes": list(self.notes),
            "policy_note": self.policy_note,
        }


class EmbeddingStore:
    """In-memory embedding store keyed by content_hash + model_id + index_version."""

    def __init__(self, *, model_id: str | None = None, index_version: int = 1) -> None:
        self.model_id = model_id
        self.index_version = int(index_version)
        self._records: dict[str, EmbeddingRecord] = {}
        self._lock = threading.RLock()

    def key_for(self, content_hash: str) -> str:
        if not self.model_id:
            raise ValueError("embedding_model_unavailable")
        return embedding_key(
            content_hash=content_hash,
            model_id=self.model_id,
            index_version=self.index_version,
        )

    def get(self, content_hash: str) -> EmbeddingRecord | None:
        with self._lock:
            if not self.model_id:
                return None
            return self._records.get(self.key_for(content_hash))

    def put(
        self,
        *,
        content_hash: str,
        vector: list[float],
        source_id: str = "",
        chunk_id: str = "",
    ) -> EmbeddingRecord:
        if not self.model_id:
            raise ValueError("embedding_model_unavailable")
        key = self.key_for(content_hash)
        rec = EmbeddingRecord(
            key=key,
            content_hash=content_hash,
            model_id=self.model_id,
            index_version=self.index_version,
            vector=list(vector),
            source_id=source_id,
            chunk_id=chunk_id,
        )
        with self._lock:
            self._records[key] = rec
        return rec

    def is_stale(self, content_hash: str, *, current_hash: str) -> bool:
        if content_hash != current_hash:
            return True
        return self.get(content_hash) is None

    def invalidate_model_change(self, new_model_id: str) -> int:
        """Model id change invalidates all embeddings for prior model."""
        with self._lock:
            removed = len(self._records)
            self._records.clear()
            self.model_id = new_model_id
            self.index_version += 1
            return removed

    def bump_index_version(self) -> int:
        with self._lock:
            self._records.clear()
            self.index_version += 1
            return self.index_version

    def semantic_available(self) -> bool:
        return bool(self.model_id)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "model_id": self.model_id,
                "index_version": self.index_version,
                "count": len(self._records),
                "semantic_available": self.semantic_available(),
            }


@dataclass(slots=True)
class SourceVersionRecord:
    source_id: str
    uri: str
    content_hash: str
    role: RoleKind
    local_path: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    status: str = "ready"
    chunk_hashes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    conflicts_with: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeFreshnessService:
    """Track source versions, stale chunks, reimport idempotency, scope, ingestion cancel."""

    def __init__(self, *, embedding_store: EmbeddingStore | None = None) -> None:
        self.embeddings = embedding_store or EmbeddingStore()
        self._sources: dict[str, SourceVersionRecord] = {}
        self._by_uri: dict[str, str] = {}  # uri -> source_id
        self._lock = threading.RLock()
        self._ingest_jobs: dict[str, dict[str, Any]] = {}

    def upsert_source(
        self,
        *,
        uri: str,
        content: str,
        role: RoleKind = "knowledge",
        source_id: str | None = None,
        local_path: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        chunks: list[str] | None = None,
    ) -> dict[str, Any]:
        assert_role_distinct(role)
        digest = content_hash_text(content)
        chunk_hashes = [content_hash_text(c) for c in (chunks or [])]
        with self._lock:
            existing_id = self._by_uri.get(uri)
            if existing_id and existing_id in self._sources:
                prev = self._sources[existing_id]
                if prev.content_hash == digest and prev.chunk_hashes == chunk_hashes and prev.status == "ready":
                    return {
                        "source": prev.to_dict(),
                        "unchanged": True,
                        "reimported": False,
                        "stale_chunks_replaced": 0,
                    }
                # Content changed → new version; mark prior superseded conceptually via hash update.
                prev_hash = prev.content_hash
                prev.content_hash = digest
                prev.chunk_hashes = chunk_hashes
                prev.local_path = local_path or prev.local_path
                prev.project_id = project_id if project_id is not None else prev.project_id
                prev.conversation_id = conversation_id if conversation_id is not None else prev.conversation_id
                prev.status = "ready"
                prev.updated_at = _now()
                # Drop stale embeddings for old hash.
                stale = 0
                if self.embeddings.model_id and prev_hash != digest:
                    stale = 1
                return {
                    "source": prev.to_dict(),
                    "unchanged": False,
                    "reimported": True,
                    "stale_chunks_replaced": max(stale, len(chunk_hashes)),
                    "previous_content_hash": prev_hash,
                }

            sid = source_id or f"src_{uuid.uuid4().hex[:12]}"
            rec = SourceVersionRecord(
                source_id=sid,
                uri=uri,
                content_hash=digest,
                role=role,
                local_path=local_path,
                project_id=project_id,
                conversation_id=conversation_id,
                chunk_hashes=chunk_hashes,
            )
            self._sources[sid] = rec
            self._by_uri[uri] = sid
            return {
                "source": rec.to_dict(),
                "unchanged": False,
                "reimported": False,
                "stale_chunks_replaced": 0,
            }

    def assess_freshness(
        self,
        source_id: str,
        *,
        current_file_hash: str | None = None,
        file_exists: bool | None = None,
        file_reachable: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self._sources.get(source_id)
            if not rec:
                return {"status": "source_missing", "source_id": source_id}
            status: FreshnessStatus = "fresh"
            notes: list[str] = []
            if file_exists is False:
                status = "source_missing"
                notes.append("local_path_deleted")
            elif file_reachable is False:
                status = "source_unreachable"
                notes.append("local_path_unreachable")
            elif current_file_hash and current_file_hash != rec.content_hash:
                status = "stale_content"
                notes.append("content_hash_mismatch")
            elif rec.superseded_by:
                status = "superseded"
                notes.append(f"superseded_by:{rec.superseded_by}")
            elif rec.conflicts_with:
                status = "conflict"
                notes.append("conflicting_sources")
            elif self.embeddings.semantic_available():
                for ch in rec.chunk_hashes:
                    if self.embeddings.get(ch) is None:
                        status = "stale_embedding"
                        notes.append("missing_embedding_for_chunk")
                        break
            return {
                "status": status,
                "source_id": source_id,
                "content_hash": rec.content_hash,
                "role": rec.role,
                "notes": notes,
                "source": rec.to_dict(),
            }

    def mark_superseded(self, source_id: str, *, by_source_id: str, reason: str = "") -> dict[str, Any]:
        with self._lock:
            rec = self._sources.get(source_id)
            if not rec:
                raise KeyError(source_id)
            rec.superseded_by = by_source_id
            rec.status = "superseded"
            rec.updated_at = _now()
            newer = self._sources.get(by_source_id)
            return {
                "source": rec.to_dict(),
                "superseded_by": by_source_id,
                "newer": newer.to_dict() if newer else None,
                "reason": reason,
            }

    def mark_conflict(self, source_id: str, other_source_id: str) -> dict[str, Any]:
        with self._lock:
            a = self._sources.get(source_id)
            b = self._sources.get(other_source_id)
            if not a or not b:
                raise KeyError("source_not_found")
            if other_source_id not in a.conflicts_with:
                a.conflicts_with.append(other_source_id)
            if source_id not in b.conflicts_with:
                b.conflicts_with.append(source_id)
            a.updated_at = _now()
            b.updated_at = _now()
            return {"a": a.to_dict(), "b": b.to_dict(), "status": "conflict"}

    def filter_scope(
        self,
        source_ids: list[str],
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
        roles: list[RoleKind] | None = None,
    ) -> dict[str, Any]:
        kept: list[str] = []
        dropped: list[dict[str, Any]] = []
        with self._lock:
            for sid in source_ids:
                rec = self._sources.get(sid)
                if not rec:
                    dropped.append({"source_id": sid, "reason": "missing"})
                    continue
                if roles and rec.role not in roles:
                    dropped.append({"source_id": sid, "reason": "role_filter", "role": rec.role})
                    continue
                if project_id and rec.project_id and rec.project_id != project_id:
                    dropped.append({"source_id": sid, "reason": "out_of_project_scope"})
                    continue
                if conversation_id and rec.conversation_id and rec.conversation_id != conversation_id:
                    dropped.append({"source_id": sid, "reason": "out_of_conversation_scope"})
                    continue
                if rec.superseded_by:
                    dropped.append({"source_id": sid, "reason": "superseded", "by": rec.superseded_by})
                    continue
                kept.append(sid)
        return {"kept": kept, "dropped": dropped, "project_id": project_id, "conversation_id": conversation_id}

    def start_bulk_ingest(self, *, paths: list[str], job_id: str | None = None) -> dict[str, Any]:
        jid = job_id or f"ingest_{uuid.uuid4().hex[:10]}"
        with self._lock:
            self._ingest_jobs[jid] = {
                "id": jid,
                "status": "running",
                "paths": list(paths),
                "cursor": 0,
                "completed": [],
                "errors": [],
                "cancel_requested": False,
                "created_at": _now(),
                "updated_at": _now(),
            }
        return dict(self._ingest_jobs[jid])

    def ingest_next(self, job_id: str, *, read_text) -> dict[str, Any]:
        """Process one path; honor cancel; resumable from cursor."""
        with self._lock:
            job = self._ingest_jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.get("cancel_requested") or job.get("status") == "cancelled":
                job["status"] = "cancelled"
                job["updated_at"] = _now()
                return {"job": dict(job), "done": True, "cancelled": True}
            if job["cursor"] >= len(job["paths"]):
                job["status"] = "completed"
                job["updated_at"] = _now()
                return {"job": dict(job), "done": True, "cancelled": False}
            path = job["paths"][job["cursor"]]
        try:
            text = read_text(path)
            result = self.upsert_source(uri=f"file:{path}", content=text, role="knowledge", local_path=path)
            with self._lock:
                job = self._ingest_jobs[job_id]
                job["completed"].append({"path": path, "source_id": result["source"]["source_id"], "unchanged": result.get("unchanged")})
                job["cursor"] += 1
                job["updated_at"] = _now()
                done = job["cursor"] >= len(job["paths"])
                if done:
                    job["status"] = "completed"
                return {"job": dict(job), "done": done, "cancelled": False, "last": result}
        except Exception as exc:
            with self._lock:
                job = self._ingest_jobs[job_id]
                job["errors"].append({"path": path, "error": str(exc)})
                job["cursor"] += 1
                job["updated_at"] = _now()
                done = job["cursor"] >= len(job["paths"])
                if done and not job.get("cancel_requested"):
                    job["status"] = "completed"
                return {"job": dict(job), "done": done, "cancelled": False, "error": str(exc)}

    def cancel_bulk_ingest(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._ingest_jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            job["cancel_requested"] = True
            if job["status"] == "running":
                job["status"] = "cancel_requested"
            job["updated_at"] = _now()
            return dict(job)

    def resume_bulk_ingest(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._ingest_jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job["status"] in {"completed"}:
                return dict(job)
            job["cancel_requested"] = False
            job["status"] = "running"
            job["updated_at"] = _now()
            return dict(job)

    def get_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._ingest_jobs.get(job_id)
            return dict(job) if job else None

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._sources.get(source_id)
            return rec.to_dict() if rec else None


def preserve_critical_user_conditions(
    items: list[dict[str, Any]],
    *,
    max_chars: int,
) -> dict[str, Any]:
    """Context budgets must keep critical user conditions even when truncating knowledge."""
    critical_kinds = {"user_constraint", "system_policy", "critical_condition"}
    critical = [i for i in items if i.get("kind") in critical_kinds or i.get("trusted") or i.get("critical")]
    other = [i for i in items if i not in critical]

    kept: list[dict[str, Any]] = []
    used = 0
    dropped: list[dict[str, Any]] = []
    notes: list[str] = []

    for item in critical:
        size = len(str(item.get("content") or "")) + 32
        if used + size > max_chars and kept:
            # Still force-keep critical by truncating content if needed.
            remain = max(80, max_chars - used - 16)
            clipped = dict(item)
            content = str(item.get("content") or "")
            if len(content) > remain:
                clipped["content"] = content[: remain - 20] + "\n… [critical retained]"
                notes.append(f"critical_truncated:{item.get('item_id')}")
            kept.append(clipped)
            used = max_chars
            continue
        kept.append(item)
        used += size

    for item in other:
        size = len(str(item.get("content") or "")) + 32
        if used + size > max_chars:
            dropped.append({"item_id": item.get("item_id"), "kind": item.get("kind"), "reason": "budget"})
            continue
        kept.append(item)
        used += size

    critical_kept = sum(1 for i in kept if i.get("kind") in critical_kinds or i.get("trusted") or i.get("critical"))
    return {
        "kept": kept,
        "dropped": dropped,
        "used_chars": used,
        "max_chars": max_chars,
        "critical_kept": critical_kept,
        "critical_total": len(critical),
        "notes": notes + (["critical_user_conditions_preserved"] if critical_kept == len(critical) else ["critical_partial"]),
        "ok": critical_kept == len(critical) or max_chars <= 0,
    }


def build_retrieval_inspection(
    *,
    query: str,
    hits: list[dict[str, Any]],
    method: str,
    embedding_store: EmbeddingStore,
    scope: dict[str, Any] | None = None,
    max_passages: int = 8,
    dropped: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
) -> RetrievalInspection:
    passages: list[PassageSelection] = []
    for hit in hits[:max_passages]:
        role = str(hit.get("kind") or hit.get("role") or "knowledge")
        if role not in ROLE_BOUNDARIES:
            role = "knowledge"
        source_id = str(hit.get("source_id") or hit.get("provenance") or hit.get("hit_id") or "")
        source_version = str(hit.get("source_version") or hit.get("content_hash") or "")
        chunk_id = str(hit.get("chunk_id") or hit.get("hit_id") or "")
        content = str(hit.get("content") or "")
        passages.append(
            PassageSelection(
                hit_id=str(hit.get("hit_id") or chunk_id),
                role=role,  # type: ignore[arg-type]
                content_preview=content[:240],
                source_id=source_id,
                source_version=source_version,
                score=float(hit.get("score") or 0),
                reasons=list(hit.get("reasons") or []),
                citation=citation_anchor(
                    source_id=source_id,
                    source_version=source_version,
                    chunk_id=chunk_id,
                    sequence=hit.get("sequence"),
                    heading=str(hit.get("heading") or (hit.get("metadata") or {}).get("heading") or "") or None,
                ),
                limits={"max_passages": max_passages, "preview_chars": 240},
            )
        )
    semantic = embedding_store.semantic_available()
    effective_method = method
    extra_notes = list(notes or [])
    if not semantic and method in {"semantic", "hybrid"}:
        effective_method = "lexical"
        extra_notes.append("semantic_unavailable_lexical_fallback")
    return RetrievalInspection(
        query=query,
        method=effective_method,
        passages=passages,
        lexical_available=True,
        semantic_available=semantic,
        embedding_model_id=embedding_store.model_id,
        index_version=embedding_store.index_version,
        scope=dict(scope or {}),
        dropped=list(dropped or []),
        notes=extra_notes,
    )


def measure_retrieval_quality(
    *,
    cases: list[dict[str, Any]],
    retrieve_fn,
) -> dict[str, Any]:
    """Measure on a small versioned Q/source set. Returns inspectable metrics."""
    results = []
    hits_at_1 = 0
    hits_at_3 = 0
    for case in cases:
        query = str(case.get("query") or "")
        expected_source = str(case.get("expected_source_version") or case.get("expected_source_id") or "")
        inspection = retrieve_fn(query, case)
        passages = inspection.get("passages") if isinstance(inspection, dict) else inspection.to_dict().get("passages")
        passages = passages or []
        versions = [str(p.get("source_version") or p.get("source_id") or "") for p in passages]
        ids = [str(p.get("source_id") or "") for p in passages]
        ok1 = bool(versions and (expected_source in {versions[0], ids[0]}))
        ok3 = expected_source in set(versions[:3]) or expected_source in set(ids[:3])
        hits_at_1 += int(ok1)
        hits_at_3 += int(ok3)
        results.append(
            {
                "query": query,
                "expected": expected_source,
                "hit_at_1": ok1,
                "hit_at_3": ok3,
                "top_versions": versions[:3],
                "method": (inspection.get("method") if isinstance(inspection, dict) else inspection.method),
            }
        )
    n = max(1, len(cases))
    return {
        "cases": len(cases),
        "hit_at_1": hits_at_1 / n,
        "hit_at_3": hits_at_3 / n,
        "results": results,
        "note": "Small versioned fixture metric; not a claim of production IR quality.",
    }


# Default process store for optional wiring.
default_freshness = KnowledgeFreshnessService()
