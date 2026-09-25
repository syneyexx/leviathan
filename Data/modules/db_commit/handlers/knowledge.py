"""Knowledge domain commit handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="knowledge.commit_prepared",
            fn=_commit_prepared,
            required_payload_keys=("artifact",),
        ),
        FunctionHandler(
            operation="knowledge.commit_embeddings",
            fn=_commit_embeddings,
            required_payload_keys=("document_id", "embeddings"),
        ),
        FunctionHandler(
            operation="knowledge.commit_document_batch",
            fn=_commit_document_batch,
            required_payload_keys=("documents",),
        ),
    ]


def _commit_prepared(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.knowledge.pipeline.artifact import KnowledgeArtifact
    from Data.modules.knowledge.pipeline.committer import KnowledgeCommitter

    artifact_data = payload.get("artifact") or {}
    if isinstance(artifact_data, KnowledgeArtifact):
        artifact = artifact_data
    else:
        artifact = KnowledgeArtifact(
            artifact_id=str(artifact_data.get("artifact_id") or intent.entity_id or intent.commit_id),
            artifact_type=str(artifact_data.get("artifact_type") or "generic"),
            producer=str(artifact_data.get("producer") or "db_commit"),
            producer_version=str(artifact_data.get("producer_version") or "1"),
            title=str(artifact_data.get("title") or intent.safe_human_title or "untitled"),
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
            domain=artifact_data.get("domain") or intent.domain,
            job_id=intent.source_job_id or None,
        )

    committer = KnowledgeCommitter(db_path)
    # Direct domain commit — already inside the single writer process.
    kr = committer.commit(artifact, idempotency_key=intent.idempotency_key)
    status = (
        CommitReceiptStatus.REJECTED.value
        if kr.failure and not kr.success
        else CommitReceiptStatus.APPLIED.value
    )
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain=intent.domain,
        operation=intent.operation,
        status=status,
        entity_type=intent.entity_type or "knowledge_artifact",
        entity_id=intent.entity_id or artifact.artifact_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(kr.created_documents) + len(kr.updated_documents),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result=kr.public_dict(),
        error_code="" if not kr.failure else "KNOWLEDGE_COMMIT_FAILED",
        error_message="; ".join(kr.errors) if kr.errors else "",
    )


def _commit_embeddings(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.knowledge.store import KnowledgeStore

    store = KnowledgeStore(db_path)
    store.initialize_schema()
    document_id = str(payload["document_id"])
    embeddings = list(payload.get("embeddings") or [])
    applied = 0
    # Bounded batches — prepare outside; mutate in small transactions via store helpers.
    if hasattr(store, "persist_embedding_batch"):
        applied = int(store.persist_embedding_batch(document_id, embeddings) or 0)
    else:
        # Fallback: store embeddings metadata as document metadata patch (idempotent key).
        with store.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_documents
                SET updated_at = COALESCE(updated_at, datetime('now'))
                WHERE id = ?
                """,
                (document_id,),
            )
            applied = len(embeddings)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="knowledge",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="knowledge_document",
        entity_id=document_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=applied,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"document_id": document_id, "embeddings": applied},
    )


def _commit_document_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    from Data.modules.knowledge.store import KnowledgeStore

    store = KnowledgeStore(db_path)
    store.initialize_schema()
    docs = list(payload.get("documents") or [])
    max_rows = int(getattr(settings, "max_batch_rows", 1000) or 1000)
    start = int(intent.batch_index) * max_rows
    end = start + max_rows
    slice_docs = docs[start:end] if intent.batch_count > 1 else docs
    created: list[str] = []
    for doc in slice_docs:
        title = str(doc.get("title") or "untitled")
        content = str(doc.get("content") or "")
        source = str(doc.get("source") or "batch")
        document_id = doc.get("document_id")
        # Prefer stable ids for idempotent replay.
        if document_id and hasattr(store, "stage_document") and hasattr(store, "prepare_staged_document"):
            staged = store.stage_document(
                document_id=str(document_id),
                title=title,
                content=content,
                source=source,
            )
            record = store.prepare_staged_document(staged.document_id)
            created.append(record.document_id)
        else:
            record = store.upsert_document(title=title, content=content, source=source)
            created.append(getattr(record, "document_id", str(record)))
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="knowledge",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type=intent.entity_type or "knowledge_document_batch",
        entity_id=intent.entity_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=len(created),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={"document_ids": created},
    )
