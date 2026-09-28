"""Submit typed Knowledge COMMIT_WRITE intents (never arbitrary SQL).

Production: CommitProducer → db_commit singleton.
Tests / explicit allow: apply via the same allowlisted handlers (no second writer).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Data.modules.db_commit.domain_submit import producer_for
from Data.modules.db_commit.producer import SubmitResult
from Data.modules.db_commit.types import CommitPriority, CommitReceipt, CommitReceiptStatus, utc_now
from Data.modules.knowledge.execution_gate import inline_execution_explicitly_allowed

ALLOW_INLINE_COMMIT_ENV = "LEVIATHAN_DB_COMMIT_INLINE"


def _inline_commit_allowed() -> bool:
    raw = (os.environ.get(ALLOW_INLINE_COMMIT_ENV) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return inline_execution_explicitly_allowed()


def _apply_via_registry(
    db_path: Path,
    *,
    operation: str,
    payload: dict[str, Any],
    intent: Any,
) -> CommitReceipt:
    from Data.modules.db_commit.handlers.registry import build_default_registry
    from Data.modules.db_commit.receipts import CommitReceiptStore
    from Data.modules.db_commit.settings import load_db_commit_settings

    registry = build_default_registry()
    handler = registry.get(operation)
    settings = load_db_commit_settings()
    receipt = handler.apply(intent, payload, db_path=Path(db_path), settings=settings)
    # Persist receipt so retries short-circuit via idempotency.
    store = CommitReceiptStore(db_path)
    store.initialize()
    store.persist(receipt)
    return receipt


def submit_knowledge_replace_chunks(
    db_path: Path | str,
    *,
    document_id: str,
    expected_content_hash: str,
    title: str,
    chunks: list[dict[str, Any]],
    source: str = "manual",
    finalize: bool = True,
    title_content_fts: str | None = None,
    document_content_for_fts: str | None = None,
    source_job_id: str = "",
    idempotency_key: str | None = None,
    apply_inline_if_allowed: bool = True,
) -> SubmitResult:
    payload = {
        "document_id": document_id,
        "expected_content_hash": expected_content_hash,
        "title": title,
        "source": source,
        "chunks": chunks,
        "finalize": bool(finalize),
        "title_content_fts": title_content_fts if title_content_fts is not None else title,
        "document_content_for_fts": document_content_for_fts or "",
    }
    producer = producer_for(db_path, domain="knowledge")
    result = producer.submit(
        operation="knowledge.replace_chunks",
        domain="knowledge",
        payload=payload,
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="knowledge_document",
        entity_id=document_id,
        safe_human_title=title,
        source_job_id=source_job_id,
        record_count_hint=len(chunks),
        allow_critical=True,
    )
    if (
        apply_inline_if_allowed
        and result.accepted
        and not result.committed
        and _inline_commit_allowed()
    ):
        receipt = _apply_via_registry(
            Path(db_path),
            operation="knowledge.replace_chunks",
            payload=payload,
            intent=result.intent,
        )
        return SubmitResult(
            ack_status="ALREADY_APPLIED",
            commit_id=result.commit_id,
            intent=result.intent,
            receipt=receipt,
            message="applied inline (test/allow)",
        )
    return result


def submit_knowledge_chunk_embeddings(
    db_path: Path | str,
    *,
    document_id: str,
    expected_content_hash: str,
    embeddings: list[dict[str, Any]],
    provider_id: str = "",
    finalize: bool = False,
    source_job_id: str = "",
    idempotency_key: str | None = None,
    apply_inline_if_allowed: bool = True,
) -> SubmitResult:
    payload = {
        "document_id": document_id,
        "expected_content_hash": expected_content_hash,
        "embeddings": embeddings,
        "provider_id": provider_id,
        "finalize": bool(finalize),
    }
    producer = producer_for(db_path, domain="knowledge")
    result = producer.submit(
        operation="knowledge.upsert_chunk_embeddings",
        domain="knowledge",
        payload=payload,
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="knowledge_document",
        entity_id=document_id,
        safe_human_title=document_id,
        source_job_id=source_job_id,
        record_count_hint=len(embeddings),
        allow_critical=True,
    )
    if (
        apply_inline_if_allowed
        and result.accepted
        and not result.committed
        and _inline_commit_allowed()
    ):
        receipt = _apply_via_registry(
            Path(db_path),
            operation="knowledge.upsert_chunk_embeddings",
            payload=payload,
            intent=result.intent,
        )
        return SubmitResult(
            ack_status="ALREADY_APPLIED",
            commit_id=result.commit_id,
            intent=result.intent,
            receipt=receipt,
            message="applied inline (test/allow)",
        )
    return result


def submit_knowledge_finalize(
    db_path: Path | str,
    *,
    document_id: str,
    expected_content_hash: str,
    status: str = "READY",
    title: str = "",
    content_for_fts: str = "",
    source_job_id: str = "",
    idempotency_key: str | None = None,
    apply_inline_if_allowed: bool = True,
    error: str | None = None,
) -> SubmitResult:
    payload = {
        "document_id": document_id,
        "expected_content_hash": expected_content_hash,
        "status": status,
        "title": title,
        "content_for_fts": content_for_fts,
        "error": error,
    }
    producer = producer_for(db_path, domain="knowledge")
    result = producer.submit(
        operation="knowledge.finalize_document",
        domain="knowledge",
        payload=payload,
        idempotency_key=idempotency_key,
        priority=CommitPriority.P2_DOMAIN,
        entity_type="knowledge_document",
        entity_id=document_id,
        safe_human_title=title or document_id,
        source_job_id=source_job_id,
        record_count_hint=1,
        allow_critical=True,
    )
    if (
        apply_inline_if_allowed
        and result.accepted
        and not result.committed
        and _inline_commit_allowed()
    ):
        receipt = _apply_via_registry(
            Path(db_path),
            operation="knowledge.finalize_document",
            payload=payload,
            intent=result.intent,
        )
        return SubmitResult(
            ack_status="ALREADY_APPLIED",
            commit_id=result.commit_id,
            intent=result.intent,
            receipt=receipt,
            message="applied inline (test/allow)",
        )
    return result


def stale_generation_receipt(
    *,
    commit_id: str,
    idempotency_key: str,
    document_id: str,
    message: str,
) -> CommitReceipt:
    return CommitReceipt(
        commit_id=commit_id,
        idempotency_key=idempotency_key or commit_id,
        domain="knowledge",
        operation="knowledge.replace_chunks",
        status=CommitReceiptStatus.REJECTED.value,
        entity_type="knowledge_document",
        entity_id=document_id,
        applied_at=utc_now(),
        error_code="KNOWLEDGE_STALE_GENERATION",
        error_message=message,
    )
