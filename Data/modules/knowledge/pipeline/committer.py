"""Single serialized knowledge commit lane — concurrency default 1."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .artifact import KnowledgeArtifact
from .curator import KnowledgeCurator, PlacementDecision


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CommitReceipt:
    commit_id: str
    artifact_id: str
    plan_id: str | None
    idempotency_key: str | None
    created_documents: list[str] = field(default_factory=list)
    updated_documents: list[str] = field(default_factory=list)
    dedupe_skips: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    atlas_updates: list[str] = field(default_factory=list)
    success: bool = False
    partial: bool = False
    failure: bool = False
    errors: list[str] = field(default_factory=list)
    placement: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "commit_id": self.commit_id,
            "artifact_id": self.artifact_id,
            "plan_id": self.plan_id,
            "idempotency_key": self.idempotency_key,
            "created_documents": list(self.created_documents),
            "updated_documents": list(self.updated_documents),
            "dedupe_skips": list(self.dedupe_skips),
            "rejections": list(self.rejections),
            "atlas_updates": list(self.atlas_updates),
            "success": self.success,
            "partial": self.partial,
            "failure": self.failure,
            "errors": list(self.errors),
            "placement": dict(self.placement),
        }


class KnowledgeCommitter:
    """Canonical promotion through KnowledgeAssimilationService / KnowledgeStore."""

    _locks: dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(
        self,
        db_path: Path,
        *,
        assimilation_service: Any | None = None,
        knowledge_store: Any | None = None,
        concurrency: int = 1,
    ) -> None:
        self.db_path = Path(db_path)
        self.assimilation = assimilation_service
        self.knowledge = knowledge_store
        self.concurrency = max(1, int(concurrency))
        self.curator = KnowledgeCurator()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        key = str(self.db_path.resolve())
        with KnowledgeCommitter._locks_guard:
            if key not in KnowledgeCommitter._locks:
                KnowledgeCommitter._locks[key] = threading.Lock()
        self._lock = KnowledgeCommitter._locks[key]

    @classmethod
    def from_env(cls, ctx: dict[str, Any]) -> KnowledgeCommitter:
        settings = ctx["settings"]
        return cls(settings.database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_commit_receipts (
                    commit_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    idempotency_key TEXT,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_commit_idempotency "
                "ON knowledge_commit_receipts(idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )

    def commit_job(self, job: Any) -> dict[str, Any]:
        args = dict(getattr(job, "arguments", None) or {})
        artifact_data = args.get("artifact") or {}
        if isinstance(artifact_data, KnowledgeArtifact):
            artifact = artifact_data
        else:
            artifact = KnowledgeArtifact(
                artifact_id=str(artifact_data.get("artifact_id") or uuid.uuid4()),
                artifact_type=str(artifact_data.get("artifact_type") or "generic"),
                producer=str(artifact_data.get("producer") or "worker"),
                producer_version=str(artifact_data.get("producer_version") or "1"),
                title=str(artifact_data.get("title") or "untitled"),
                summary=str(artifact_data.get("summary") or ""),
                content_inline=artifact_data.get("content_inline"),
                content_digest=artifact_data.get("content_digest"),
                content_ref=artifact_data.get("content_ref"),
                provenance=dict(artifact_data.get("provenance") or {}),
                claims=list(artifact_data.get("claims") or []),
                topics=list(artifact_data.get("topics") or []),
                suggested_destinations=list(artifact_data.get("suggested_destinations") or []),
                security_flags=list(artifact_data.get("security_flags") or []),
                confidence=artifact_data.get("confidence"),
                domain=artifact_data.get("domain"),
                job_id=getattr(job, "job_id", None),
            )
        idem = args.get("idempotency_key") or getattr(job, "idempotency_key", None)
        receipt = self.commit(artifact, idempotency_key=idem)
        return receipt.public_dict()

    def commit(
        self,
        artifact: KnowledgeArtifact,
        *,
        idempotency_key: str | None = None,
        plan_id: str | None = None,
    ) -> CommitReceipt:
        self.initialize()
        if idempotency_key:
            existing = self._get_by_idempotency(idempotency_key)
            if existing is not None:
                return existing

        placement = self.curator.place(artifact)
        receipt = CommitReceipt(
            commit_id=str(uuid.uuid4()),
            artifact_id=artifact.artifact_id,
            plan_id=plan_id,
            idempotency_key=idempotency_key,
            placement=placement.public_dict(),
        )

        with self._lock:
            if placement.destination == "reject":
                receipt.rejections.append(placement.reason)
                receipt.failure = True
                receipt.errors.append(placement.reason)
                self._persist(receipt)
                return receipt

            if placement.destination == "hold_disputed":
                receipt.rejections.append("held_disputed")
                receipt.partial = True
                receipt.success = True
                self._persist(receipt)
                return receipt

            try:
                if self.assimilation is not None and hasattr(
                    self.assimilation, "assimilate_artifact"
                ):
                    result = self.assimilation.assimilate_artifact(artifact)
                    receipt.created_documents = list(result.get("created") or [])
                    receipt.updated_documents = list(result.get("updated") or [])
                    receipt.dedupe_skips = list(result.get("dedupe_skips") or [])
                elif self.knowledge is not None and artifact.content_inline:
                    # Dedupe by content digest when KnowledgeStore supports it
                    digest = artifact.content_digest
                    existing_id = None
                    if digest and hasattr(self.knowledge, "find_by_content_hash"):
                        existing_id = self.knowledge.find_by_content_hash(digest)
                    if existing_id:
                        receipt.dedupe_skips.append(str(existing_id))
                        receipt.updated_documents.append(str(existing_id))
                    elif hasattr(self.knowledge, "upsert_document"):
                        doc_id = self.knowledge.upsert_document(
                            title=artifact.title,
                            content=artifact.content_inline,
                            source=artifact.source_ref or artifact.producer,
                            metadata={
                                "artifact_id": artifact.artifact_id,
                                "provenance": artifact.provenance,
                            },
                        )
                        receipt.created_documents.append(str(doc_id))
                    elif hasattr(self.knowledge, "add_document"):
                        doc_id = self.knowledge.add_document(
                            title=artifact.title,
                            content=artifact.content_inline,
                            source=artifact.source_ref or artifact.producer,
                        )
                        receipt.created_documents.append(str(doc_id))
                    else:
                        receipt.errors.append("knowledge_store_write_unavailable")
                        receipt.failure = True
                        self._persist(receipt)
                        return receipt
                else:
                    # No store bound — record intentional dry commit for worker wiring tests
                    receipt.created_documents.append(f"dry:{artifact.artifact_id}")
                receipt.success = not receipt.failure
            except Exception as exc:  # noqa: BLE001
                receipt.failure = True
                receipt.errors.append(str(exc))
            self._persist(receipt)
        return receipt

    def _persist(self, receipt: CommitReceipt) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_commit_receipts(
                    commit_id, artifact_id, idempotency_key, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    receipt.commit_id,
                    receipt.artifact_id,
                    receipt.idempotency_key,
                    json.dumps(receipt.public_dict()),
                    utc_now(),
                ),
            )

    def _get_by_idempotency(self, key: str) -> CommitReceipt | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM knowledge_commit_receipts WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row["receipt_json"])
        return CommitReceipt(
            commit_id=data["commit_id"],
            artifact_id=data["artifact_id"],
            plan_id=data.get("plan_id"),
            idempotency_key=data.get("idempotency_key"),
            created_documents=list(data.get("created_documents") or []),
            updated_documents=list(data.get("updated_documents") or []),
            dedupe_skips=list(data.get("dedupe_skips") or []),
            rejections=list(data.get("rejections") or []),
            atlas_updates=list(data.get("atlas_updates") or []),
            success=bool(data.get("success")),
            partial=bool(data.get("partial")),
            failure=bool(data.get("failure")),
            errors=list(data.get("errors") or []),
            placement=dict(data.get("placement") or {}),
        )
