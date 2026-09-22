from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from Data.modules.knowledge.store import KnowledgeStore

from .memory_tiers import NeuroMemoryFacade


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class MemorySnapshot:
    snapshot_id: str
    label: str
    tier: int
    created_at: str
    payload: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "label": self.label,
            "tier": self.tier,
            "created_at": self.created_at,
            "payload": self.payload,
            "truth": {"snapshot_is_not_authority": True},
        }


class NeuroSnapshotStore:
    """Durable Tier0/1 snapshot metadata in the central LEVIATHAN database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS neuro_memory_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    tier INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_neuro_snapshots_tier "
                "ON neuro_memory_snapshots(tier, created_at)"
            )

    def save(self, *, label: str, tier: int, payload: dict[str, Any], snapshot_id: str | None = None) -> MemorySnapshot:
        snap = MemorySnapshot(
            snapshot_id=snapshot_id or str(uuid.uuid4()),
            label=label.strip() or "snapshot",
            tier=int(tier),
            created_at=utc_now(),
            payload=payload,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO neuro_memory_snapshots(snapshot_id, label, tier, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snap.snapshot_id, snap.label, snap.tier, snap.created_at, json.dumps(snap.payload)),
            )
        return snap

    def get(self, snapshot_id: str) -> MemorySnapshot | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM neuro_memory_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return MemorySnapshot(
            snapshot_id=row["snapshot_id"],
            label=row["label"],
            tier=int(row["tier"]),
            created_at=row["created_at"],
            payload=json.loads(row["payload_json"] or "{}"),
        )

    def list(self, *, tier: int | None = None, limit: int = 50) -> list[MemorySnapshot]:
        with self.connect() as conn:
            if tier is None:
                rows = conn.execute(
                    "SELECT * FROM neuro_memory_snapshots ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM neuro_memory_snapshots WHERE tier = ? ORDER BY created_at DESC LIMIT ?",
                    (tier, limit),
                ).fetchall()
        return [
            MemorySnapshot(
                snapshot_id=row["snapshot_id"],
                label=row["label"],
                tier=int(row["tier"]),
                created_at=row["created_at"],
                payload=json.loads(row["payload_json"] or "{}"),
            )
            for row in rows
        ]


class NeuroAbsorbService:
    """Continuous ModelData absorption via existing KnowledgeStore.scan_data_root."""

    def __init__(self, knowledge: KnowledgeStore) -> None:
        self.knowledge = knowledge
        self.telemetry: dict[str, Any] = {"scans": 0, "ingested": 0, "errors": 0}

    def scan_once(self, *, limit: int = 50) -> dict[str, Any]:
        self.telemetry["scans"] += 1
        try:
            records = self.knowledge.scan_data_root(limit=limit)
            self.telemetry["ingested"] += len(records)
            return {
                "ingested": len(records),
                "document_ids": [item.document_id for item in records],
                "telemetry": dict(self.telemetry),
                "truth": {"uses_knowledge_v2_ingest": True, "no_parallel_ingest_pipeline": True},
            }
        except Exception as exc:  # noqa: BLE001
            self.telemetry["errors"] += 1
            return {
                "ingested": 0,
                "error": str(exc),
                "telemetry": dict(self.telemetry),
                "truth": {"uses_knowledge_v2_ingest": True},
            }


@dataclass(frozen=True)
class ContrastiveRetrievalReport:
    available: bool
    method: str
    hits: tuple[dict[str, Any], ...]
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "method": self.method,
            "hits": list(self.hits),
            "detail": self.detail,
            "truth": {"unmeasured_embeddings_are_not_passed": True},
        }


class ContrastiveRetrievalHead:
    """Contrastive retrieval head — real embeddings when provider present; else lexical UNMEASURED."""

    def __init__(
        self,
        facade: NeuroMemoryFacade,
        *,
        embeddings_available: bool = False,
        embedding_provider: Any | None = None,
    ) -> None:
        self.facade = facade
        self.embedding_provider = embedding_provider
        if embedding_provider is not None and hasattr(embedding_provider, "available"):
            self.embeddings_available = bool(embedding_provider.available())
        else:
            self.embeddings_available = embeddings_available

    def _cosine(self, a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na <= 0 or nb <= 0:
            return 0.0
        return float(dot / (na * nb))

    def retrieve(self, query: str, *, tiers: Sequence[int] = (1, 2), limit: int = 5) -> ContrastiveRetrievalReport:
        if not self.facade.enabled:
            return ContrastiveRetrievalReport(
                available=False,
                method="disabled",
                hits=(),
                detail="Neuro memory tiers OFF",
            )
        bundle = self.facade.retrieve(query, tiers=tiers, limit_per_tier=max(limit, 8))
        if self.embeddings_available and self.embedding_provider is not None:
            try:
                q_vec = self.embedding_provider.embed_query(query)
                ranked: list[tuple[float, dict[str, Any]]] = []
                for hit in bundle.hits:
                    try:
                        doc_vec = self.embedding_provider.embed_documents([hit.content])[0]
                    except Exception:  # noqa: BLE001
                        continue
                    sim = self._cosine(q_vec, doc_vec)
                    payload = hit.public_dict()
                    payload["contrastive_score"] = round(sim, 4)
                    ranked.append((sim, payload))
                ranked.sort(key=lambda item: item[0], reverse=True)
                return ContrastiveRetrievalReport(
                    available=True,
                    method="contrastive_vector_infonce_proxy",
                    hits=tuple(item[1] for item in ranked[:limit]),
                    detail="EmbeddingProvider contrastive ranking (InfoNCE-style scoring)",
                )
            except Exception as exc:  # noqa: BLE001
                return ContrastiveRetrievalReport(
                    available=True,
                    method="lexical_proxy_unmeasured_contrastive",
                    hits=tuple(hit.public_dict() for hit in bundle.hits[:limit]),
                    detail=f"Embedding path failed ({exc}) — lexical proxy (UNMEASURED)",
                )
        return ContrastiveRetrievalReport(
            available=True,
            method="lexical_proxy_unmeasured_contrastive",
            hits=tuple(hit.public_dict() for hit in bundle.hits[:limit]),
            detail="Embeddings unavailable — lexical proxy only (contrastive UNMEASURED)",
        )
