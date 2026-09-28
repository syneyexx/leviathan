"""Knowledge domain commit handlers — typed COMMIT_WRITE only (no arbitrary SQL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now
from Data.modules.knowledge.store import (
    DocumentMissingError,
    KnowledgeStore,
    StaleKnowledgeGenerationError,
)
from Data.modules.knowledge.types import IngestStatus


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="knowledge.commit_prepared",
            fn=_commit_prepared,
            required_payload_keys=("artifact",),
        ),
        FunctionHandler(
            operation="knowledge.commit_embeddings",
            fn=_commit_embeddings_legacy,
            required_payload_keys=("document_id", "embeddings"),
        ),
        FunctionHandler(
            operation="knowledge.upsert_chunk_embeddings",
            fn=_upsert_chunk_embeddings,
            required_payload_keys=("document_id", "embeddings"),
        ),
        FunctionHandler(
            operation="knowledge.replace_chunks",
            fn=_replace_chunks,
            required_payload_keys=("document_id", "expected_content_hash", "chunks"),
        ),
        FunctionHandler(
            operation="knowledge.finalize_document",
            fn=_finalize_document,
            required_payload_keys=("document_id",),
        ),
        FunctionHandler(
            operation="knowledge.commit_document_batch",
            fn=_commit_document_batch,
            required_payload_keys=("documents",),
        ),
    ]


def _store(db_path: Path) -> KnowledgeStore:
    store = KnowledgeStore(db_path)
    store.initialize_schema()
    return store


def _reject(
    intent: CommitIntent,
    *,
    entity_id: str,
    error_code: str,
    error_message: str,
) -> CommitReceipt:
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="knowledge",
        operation=intent.operation,
        status=CommitReceiptStatus.REJECTED.value,
        entity_type=intent.entity_type or "knowledge_document",
        entity_id=entity_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        error_code=error_code,
        error_message=error_message[:500],
    )


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

    store = _store(db_path)
    committer = KnowledgeCommitter(db_path, knowledge_store=store)
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


def _replace_chunks(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    store = _store(db_path)
    document_id = str(payload["document_id"])
    expected = str(payload.get("expected_content_hash") or "")
    chunks = list(payload.get("chunks") or [])
    title = str(payload.get("title") or "")
    source = str(payload.get("source") or "manual")
    finalize = bool(payload.get("finalize", True))
    fts_body = str(payload.get("document_content_for_fts") or "")
    try:
        result = store.apply_replace_chunks(
            document_id=document_id,
            expected_content_hash=expected,
            title=title,
            chunks=chunks,
            source=source,
            finalize=finalize,
            document_content_for_fts=fts_body,
        )
    except StaleKnowledgeGenerationError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=str(exc),
        )
    except DocumentMissingError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=f"document missing/deleted: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_COMMIT_FAILED",
            error_message=str(exc),
        )
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
        record_count=int(result.get("chunks") or 0),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result=result,
    )


def _upsert_chunk_embeddings(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    store = _store(db_path)
    document_id = str(payload["document_id"])
    embeddings = list(payload.get("embeddings") or [])
    expected = payload.get("expected_content_hash")
    finalize = bool(payload.get("finalize", False))
    try:
        applied = store.persist_embedding_batch(
            document_id,
            embeddings,
            expected_content_hash=str(expected) if expected else None,
            finalize=finalize,
        )
    except StaleKnowledgeGenerationError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=str(exc),
        )
    except DocumentMissingError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=str(exc),
        )
    except ValueError as exc:
        code = "EMBEDDING_DIMENSION_MISMATCH" if "DIMENSION" in str(exc).upper() else "EMBEDDING_FAILED"
        return _reject(intent, entity_id=document_id, error_code=code, error_message=str(exc))
    except Exception as exc:  # noqa: BLE001
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_COMMIT_FAILED",
            error_message=str(exc),
        )
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
        record_count=int(applied),
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={"document_id": document_id, "embeddings": applied, "finalized": finalize},
    )


def _commit_embeddings_legacy(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Compat alias → knowledge.upsert_chunk_embeddings."""
    return _upsert_chunk_embeddings(intent, payload, db_path, settings)


def _finalize_document(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    store = _store(db_path)
    document_id = str(payload["document_id"])
    expected = payload.get("expected_content_hash")
    status_raw = str(payload.get("status") or IngestStatus.READY.value)
    try:
        status = IngestStatus(status_raw)
    except ValueError:
        status = IngestStatus.READY
    try:
        record = store.finalize_document(
            document_id,
            expected_content_hash=str(expected) if expected else None,
            status=status,
            title=str(payload.get("title") or ""),
            content_for_fts=str(payload.get("content_for_fts") or ""),
            error=payload.get("error"),
        )
    except StaleKnowledgeGenerationError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=str(exc),
        )
    except DocumentMissingError as exc:
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_STALE_GENERATION",
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return _reject(
            intent,
            entity_id=document_id,
            error_code="KNOWLEDGE_COMMIT_FAILED",
            error_message=str(exc),
        )
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
        record_count=1,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"document_id": document_id, "status": record.status.value},
    )


def _commit_document_batch(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Stage bounded document metadata only — never chunk/embed inside db_commit."""
    store = _store(db_path)
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
        staged = store.stage_document(
            document_id=str(document_id) if document_id else None,
            title=title,
            content=content,
            source=source,
        )
        created.append(staged.document_id)
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
        result={"document_ids": created, "staged_only": True},
    )
