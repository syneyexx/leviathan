"""Local embedding provider (LM Studio OpenAI-compatible) + persistent index.

Embeddings are optional. Lexical retrieval remains the working baseline when the
provider is unconfigured, unreachable, or returns unusable vectors.

Schema/dimension mismatches are rejected — unequal dimensions are never mixed
silently into one index or cosine score.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

import httpx

from reasoning.knowledge_freshness import content_hash_text, embedding_key
from reasoning.retrieval import EmbeddingIndexState


class EmbeddingError(RuntimeError):
    """Base error for local embedding failures."""

    code: str = "embedding_error"

    def __init__(self, message: str, *, code: str | None = None, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.detail = dict(detail or {})


class DimensionMismatchError(EmbeddingError):
    code = "dimension_mismatch"


class EmbeddingSchemaError(EmbeddingError):
    code = "embedding_schema_error"


class EmbeddingUnavailable(EmbeddingError):
    code = "embedding_unavailable"


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *[float(x) for x in vector])


def _unpack_vector(blob: bytes, dimension: int) -> list[float]:
    expected = dimension * 4
    if len(blob) != expected:
        raise DimensionMismatchError(
            f"Stored embedding blob size {len(blob)} does not match dimension {dimension}",
            detail={"blob_bytes": len(blob), "dimension": dimension},
        )
    return list(struct.unpack(f"<{dimension}f", blob))


@dataclass
class LocalEmbeddingProvider:
    """Sync HTTP client for LM Studio ``POST /embeddings``.

    Designed for the retrieval path (sync callbacks). Pass ``http_client`` in
    tests to mock the transport without a live LM Studio.
    """

    base_url: str
    api_key: str = "lm-studio"
    model_id: str = ""
    timeout_s: float = 30.0
    max_batch_size: int = 16
    expected_dimension: int | None = None
    http_client: httpx.Client | None = None
    _owned_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = str(self.base_url or "").rstrip("/")
        self.model_id = str(self.model_id or "").strip()
        self.max_batch_size = max(1, int(self.max_batch_size))
        self.timeout_s = float(self.timeout_s)

    def _client(self) -> httpx.Client:
        if self.http_client is not None:
            return self.http_client
        self.http_client = httpx.Client(
            timeout=self.timeout_s,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        self._owned_client = True
        return self.http_client

    def close(self) -> None:
        if self._owned_client and self.http_client is not None:
            self.http_client.close()
            self.http_client = None
            self._owned_client = False

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model_id)

    def embeddings_url(self) -> str:
        # Accept either .../v1 or a bare host; OpenAI-compatible path is /embeddings
        # under the same base LM Studio already uses for /chat/completions.
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/embeddings"
        return urljoin(base + "/", "embeddings")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise EmbeddingUnavailable("embedding_model_unconfigured")
        cleaned = [str(t or "") for t in texts]
        if not cleaned:
            return []
        out: list[list[float]] = []
        for start in range(0, len(cleaned), self.max_batch_size):
            batch = cleaned[start : start + self.max_batch_size]
            out.extend(self._embed_batch(batch))
        return out

    def embed_one(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        if not vectors:
            raise EmbeddingUnavailable("empty_embedding_response")
        return vectors[0]

    def try_embed_one(self, text: str) -> list[float] | None:
        """Best-effort single embed for retrieval callbacks — never raises."""
        try:
            return self.embed_one(text)
        except EmbeddingError:
            return None
        except Exception:
            return None

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model_id, "input": texts if len(texts) > 1 else texts[0]}
        try:
            response = self._client().post(self.embeddings_url(), json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailable(
                f"embedding_timeout_after_{self.timeout_s}s",
                detail={"timeout_s": self.timeout_s},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingUnavailable(
                f"embedding_http_{exc.response.status_code}",
                detail={"status_code": exc.response.status_code, "body": (exc.response.text or "")[:400]},
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise EmbeddingUnavailable(f"embedding_request_failed:{exc}") from exc
        return self._parse_response(body, expected_count=len(texts))

    def _parse_response(self, body: Any, *, expected_count: int) -> list[list[float]]:
        if not isinstance(body, dict):
            raise EmbeddingSchemaError("embedding_response_not_object")
        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingSchemaError(
                "embedding_response_missing_data",
                detail={"keys": sorted(body.keys()) if isinstance(body, dict) else []},
            )
        # OpenAI schema may return items out of order — sort by index when present.
        indexed: list[tuple[int, list[float]]] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingSchemaError("embedding_item_not_object")
            emb = item.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise EmbeddingSchemaError("embedding_vector_missing_or_empty")
            try:
                vector = [float(x) for x in emb]
            except (TypeError, ValueError) as exc:
                raise EmbeddingSchemaError("embedding_vector_non_numeric") from exc
            if any(x != x or x in {float("inf"), float("-inf")} for x in vector):
                raise EmbeddingSchemaError("embedding_vector_non_finite")
            idx = item.get("index", i)
            try:
                idx_i = int(idx)
            except (TypeError, ValueError):
                idx_i = i
            indexed.append((idx_i, vector))
        indexed.sort(key=lambda pair: pair[0])
        vectors = [vec for _, vec in indexed]
        if len(vectors) != expected_count:
            raise EmbeddingSchemaError(
                "embedding_count_mismatch",
                detail={"expected": expected_count, "got": len(vectors)},
            )
        self._lock_dimension(vectors)
        return vectors

    def _lock_dimension(self, vectors: list[list[float]]) -> None:
        dims = {len(v) for v in vectors}
        if len(dims) != 1:
            raise DimensionMismatchError(
                "batch_contains_unequal_dimensions",
                detail={"dimensions": sorted(dims)},
            )
        dim = next(iter(dims))
        if dim <= 0:
            raise EmbeddingSchemaError("embedding_dimension_zero")
        if self.expected_dimension is None:
            self.expected_dimension = dim
            return
        if dim != self.expected_dimension:
            raise DimensionMismatchError(
                "embedding_dimension_mismatch",
                detail={"expected": self.expected_dimension, "got": dim, "model_id": self.model_id},
            )


@dataclass
class IndexedSource:
    source_id: str
    content: str
    role: str = "knowledge"  # memory | knowledge | evidence — kept distinct
    content_hash: str | None = None

    def digest(self) -> str:
        return self.content_hash or content_hash_text(self.content)


class PersistentEmbeddingIndex:
    """SQLite-backed, resumable embedding index with delete/invalidation.

    Memory / Knowledge / Evidence stay distinct via ``role``. Deleted sources are
    tombstoned and never returned as current. Model or dimension changes bump
    ``index_version`` so unequal spaces are not mixed.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        model_id: str | None = None,
        index_version: int = 1,
        dimension: int | None = None,
    ) -> None:
        self.path = str(path)
        self.model_id = (model_id or None)
        self.index_version = int(index_version)
        self.dimension = dimension
        self._lock = threading.RLock()
        self.state = EmbeddingIndexState(embedding_model=self.model_id, index_version=self.index_version)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_meta()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS embedding_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS embeddings (
                    source_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    index_version INTEGER NOT NULL,
                    dimension INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    embedding_key TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (source_id, model_id, index_version)
                );
                CREATE TABLE IF NOT EXISTS embedding_deleted (
                    source_id TEXT PRIMARY KEY,
                    deleted_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_embeddings_hash
                    ON embeddings(content_hash, model_id, index_version);
                """
            )
            conn.commit()

    def _load_meta(self) -> None:
        with self._connect() as conn:
            rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM embedding_meta")}
        if self.model_id is None and rows.get("model_id"):
            self.model_id = rows["model_id"] or None
        if rows.get("index_version"):
            try:
                stored_ver = int(rows["index_version"])
                if self.model_id and rows.get("model_id") == self.model_id:
                    self.index_version = max(self.index_version, stored_ver)
            except ValueError:
                pass
        if self.dimension is None and rows.get("dimension"):
            try:
                self.dimension = int(rows["dimension"])
            except ValueError:
                pass
        self.state = EmbeddingIndexState(embedding_model=self.model_id, index_version=self.index_version)
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT source_id, content_hash FROM embeddings WHERE model_id = ? AND index_version = ?",
                (self.model_id or "", self.index_version),
            ):
                self.state.mark_indexed(row["source_id"], row["content_hash"])
            for row in conn.execute("SELECT source_id FROM embedding_deleted"):
                self.state.mark_deleted(row["source_id"])

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO embedding_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def configure_model(self, model_id: str | None, *, dimension: int | None = None) -> dict[str, Any]:
        """Switch embedding model / dimension — bumps index version on change.

        Persist meta first; only then mutate live state. A failed write must leave
        the in-memory index unchanged (no silent half-applied model switch).
        """
        with self._lock:
            model_id = (model_id or "").strip() or None
            changed = model_id != self.model_id
            next_dimension = int(dimension) if dimension is not None else self.dimension
            dim_changed = (
                dimension is not None
                and self.dimension is not None
                and int(dimension) != self.dimension
            )
            next_version = self.index_version + 1 if (changed or dim_changed) else self.index_version

            with self._connect() as conn:
                self._set_meta(conn, "model_id", model_id or "")
                self._set_meta(conn, "index_version", str(next_version))
                if next_dimension is not None:
                    self._set_meta(conn, "dimension", str(next_dimension))
                conn.commit()

            # Persistence succeeded — apply live mutation.
            if changed or dim_changed:
                self.index_version = next_version
                self.state = EmbeddingIndexState(embedding_model=model_id, index_version=next_version)
            else:
                self.state.set_model(model_id)
            self.model_id = model_id
            if dimension is not None:
                self.dimension = next_dimension
            return {
                "model_id": self.model_id,
                "index_version": self.index_version,
                "dimension": self.dimension,
                "model_changed": changed,
                "dimension_changed": dim_changed,
                "semantic_available": bool(self.model_id),
            }

    def mark_deleted(self, source_id: str) -> None:
        with self._lock:
            self.state.mark_deleted(source_id)
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO embedding_deleted(source_id, deleted_at) VALUES(?, ?) "
                    "ON CONFLICT(source_id) DO UPDATE SET deleted_at = excluded.deleted_at",
                    (source_id, time.time()),
                )
                conn.execute(
                    "DELETE FROM embeddings WHERE source_id = ?",
                    (source_id,),
                )
                conn.commit()

    def is_deleted(self, source_id: str) -> bool:
        return source_id in self.state.deleted

    def get_vector(self, source_id: str) -> list[float] | None:
        """Return current vector for a non-deleted source, or None."""
        with self._lock:
            if not self.model_id or source_id in self.state.deleted:
                return None
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT vector, dimension FROM embeddings "
                    "WHERE source_id = ? AND model_id = ? AND index_version = ?",
                    (source_id, self.model_id, self.index_version),
                ).fetchone()
            if not row:
                return None
            if self.dimension is not None and int(row["dimension"]) != self.dimension:
                raise DimensionMismatchError(
                    "stored_dimension_mismatch",
                    detail={"expected": self.dimension, "got": int(row["dimension"]), "source_id": source_id},
                )
            return _unpack_vector(row["vector"], int(row["dimension"]))

    def put_vector(
        self,
        *,
        source_id: str,
        content_hash: str,
        vector: list[float],
        role: str = "knowledge",
    ) -> dict[str, Any]:
        if role not in {"memory", "knowledge", "evidence"}:
            raise ValueError(f"invalid_embedding_role:{role}")
        if not self.model_id:
            raise EmbeddingUnavailable("embedding_model_unavailable")
        dim = len(vector)
        if dim <= 0:
            raise EmbeddingSchemaError("embedding_dimension_zero")
        if self.dimension is None:
            self.dimension = dim
        elif dim != self.dimension:
            raise DimensionMismatchError(
                "index_rejects_unequal_dimension",
                detail={"expected": self.dimension, "got": dim, "source_id": source_id},
            )
        key = embedding_key(
            content_hash=content_hash,
            model_id=self.model_id,
            index_version=self.index_version,
        )
        blob = _pack_vector(vector)
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM embedding_deleted WHERE source_id = ?", (source_id,))
                conn.execute(
                    "INSERT INTO embeddings("
                    "source_id, content_hash, model_id, index_version, dimension, role, vector, embedding_key, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(source_id, model_id, index_version) DO UPDATE SET "
                    "content_hash=excluded.content_hash, dimension=excluded.dimension, "
                    "role=excluded.role, vector=excluded.vector, embedding_key=excluded.embedding_key, "
                    "updated_at=excluded.updated_at",
                    (
                        source_id,
                        content_hash,
                        self.model_id,
                        self.index_version,
                        dim,
                        role,
                        blob,
                        key,
                        time.time(),
                    ),
                )
                self._set_meta(conn, "model_id", self.model_id)
                self._set_meta(conn, "index_version", str(self.index_version))
                self._set_meta(conn, "dimension", str(self.dimension))
                conn.commit()
            self.state.mark_indexed(source_id, content_hash)
        return {
            "source_id": source_id,
            "content_hash": content_hash,
            "dimension": dim,
            "index_version": self.index_version,
            "role": role,
            "embedding_key": key,
        }

    def needs_reindex(self, source_id: str, content_hash: str) -> bool:
        return self.state.needs_reindex(source_id, content_hash)

    def build_incremental(
        self,
        sources: Iterable[IndexedSource],
        embed: Callable[[str], list[float]],
        *,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Resumable index build — skips unchanged hashes; stops after ``limit`` embeds."""
        indexed = 0
        skipped = 0
        deleted_skipped = 0
        errors: list[str] = []
        for source in sources:
            if limit is not None and indexed >= limit:
                break
            if source.source_id in self.state.deleted:
                deleted_skipped += 1
                continue
            digest = source.digest()
            if not self.needs_reindex(source.source_id, digest):
                skipped += 1
                continue
            try:
                vector = embed(source.content[:8000])
                self.put_vector(
                    source_id=source.source_id,
                    content_hash=digest,
                    vector=vector,
                    role=source.role if source.role in {"memory", "knowledge", "evidence"} else "knowledge",
                )
                indexed += 1
            except DimensionMismatchError as exc:
                errors.append(f"{source.source_id}:{exc}")
                break
            except Exception as exc:  # noqa: BLE001 — build continues for other sources
                errors.append(f"{source.source_id}:{exc}")
        return {
            "indexed": indexed,
            "skipped_unchanged": skipped,
            "deleted_skipped": deleted_skipped,
            "errors": errors[:20],
            "model_id": self.model_id,
            "index_version": self.index_version,
            "dimension": self.dimension,
            "resumable": True,
        }

    def current_source_ids(self, *, role: str | None = None) -> list[str]:
        """Non-deleted source ids for the active model/index version."""
        with self._lock:
            if not self.model_id:
                return []
            sql = (
                "SELECT source_id FROM embeddings WHERE model_id = ? AND index_version = ? "
                "AND source_id NOT IN (SELECT source_id FROM embedding_deleted)"
            )
            params: list[Any] = [self.model_id, self.index_version]
            if role:
                sql += " AND role = ?"
                params.append(role)
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [r["source_id"] for r in rows]

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "path": self.path,
                "model_id": self.model_id,
                "index_version": self.index_version,
                "dimension": self.dimension,
                "indexed_count": len(self.state.fingerprints),
                "deleted_count": len(self.state.deleted),
                "semantic_available": bool(self.model_id),
            }


def provider_from_settings(
    settings: dict[str, Any],
    *,
    http_client: httpx.Client | None = None,
) -> LocalEmbeddingProvider | None:
    """Build a provider when semantic retrieval + model id are configured."""
    if not bool(settings.get("enable_semantic_retrieval")):
        return None
    model_id = str(settings.get("embedding_model_id") or "").strip()
    if not model_id:
        return None
    base = str(settings.get("lm_studio_base_url") or "").rstrip("/")
    if not base:
        return None
    timeout = float(settings.get("request_timeout_seconds") or 30)
    # Embeddings should not hang the whole chat timeout — cap reasonably.
    embed_timeout = min(timeout, float(settings.get("embedding_timeout_seconds") or 30))
    return LocalEmbeddingProvider(
        base_url=base,
        api_key=str(settings.get("lm_studio_api_key") or "lm-studio"),
        model_id=model_id,
        timeout_s=embed_timeout,
        max_batch_size=int(settings.get("embedding_batch_size") or 16),
        http_client=http_client,
    )


def drop_non_current_hits(hits: list[Any], *, deleted_ids: set[str] | None = None) -> list[Any]:
    """Filter retrieval hits that are deleted / non-current."""
    deleted = deleted_ids or set()
    out = []
    for hit in hits:
        status = str(getattr(hit, "status", None) or "").lower()
        if status in {"deleted", "removed", "tombstone", "tombstoned", "superseded"}:
            continue
        hit_id = str(getattr(hit, "hit_id", "") or "")
        # hit_id forms like "knowledge-chunk123"
        source_key = hit_id.split("-", 1)[-1] if "-" in hit_id else hit_id
        if hit_id in deleted or source_key in deleted:
            continue
        meta = getattr(hit, "metadata", None) or {}
        if str(meta.get("deleted") or "").lower() in {"1", "true", "yes"}:
            continue
        out.append(hit)
    return out
