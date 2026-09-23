"""Index dataset versions into KnowledgeStore (streaming, idempotent)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.hashing import content_sha256
from Data.modules.knowledge.types import IngestStatus

from .materialize import iter_materialized_jsonl
from .types import CanonicalRecord, DatasetError

ProgressCb = Callable[[dict[str, Any]], None]


def _record_document_text(rec: CanonicalRecord) -> str:
    if rec.text and rec.text.strip():
        return rec.text
    if rec.messages:
        parts = []
        for msg in rec.messages:
            role = msg.get("role") or ""
            content = msg.get("content") or msg.get("text") or ""
            if isinstance(content, str) and content.strip():
                parts.append(f"{role}: {content}" if role else content)
        return "\n".join(parts)
    return ""


def index_records(
    knowledge: KnowledgeStore,
    records: Iterable[CanonicalRecord],
    *,
    dataset_id: str,
    version_id: str,
    scope: str = "dataset",
    max_records: int | None = None,
    progress_cb: ProgressCb | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Upsert each record as a knowledge document with dataset provenance.

    Streams the iterable — never materializes the full corpus in memory.
    Skips re-chunking when an existing READY document has the same content hash
    (idempotent re-learn of unchanged rows).
    """
    knowledge.initialize()
    doc_ids: list[str] = []
    skipped = 0
    indexed = 0
    chunk_total = 0
    processed = 0

    for rec in records:
        if cancel_cb is not None and cancel_cb():
            raise DatasetError("cancelled", code="cancelled", http_status=409)
        if max_records is not None and processed >= max_records:
            break
        processed += 1
        text = _record_document_text(rec)
        if not text.strip():
            continue
        # Stable document id ties knowledge row to dataset record
        document_id = f"dataset:{dataset_id}:{version_id}:{rec.id}"
        digest = content_sha256(text)
        existing = knowledge.get_document(document_id)
        if (
            existing is not None
            and existing.status == IngestStatus.READY
            and existing.content_hash == digest
        ):
            skipped += 1
            doc_ids.append(document_id)
            chunks = knowledge.list_chunks(document_id)
            chunk_total += len(chunks)
            if progress_cb and processed % 50 == 0:
                progress_cb(
                    {
                        "phase": "indexing",
                        "processed": processed,
                        "indexed": indexed,
                        "skippedUnchanged": skipped,
                        "chunkCount": chunk_total,
                    }
                )
            continue

        title = f"dataset/{dataset_id}/{rec.id}"
        trust = {
            "trust": "dataset",
            "datasetId": dataset_id,
            "versionId": version_id,
            "recordId": rec.id,
            "scope": scope,
            "split": rec.split,
            "sourcePath": (rec.metadata or {}).get("sourcePath"),
            "sourceFile": (rec.metadata or {}).get("sourceFile")
            or (rec.metadata or {}).get("sourceName"),
        }
        doc = knowledge.upsert_document(
            title=title,
            content=text,
            source=f"dataset:{scope}",
            document_id=document_id,
            trust_metadata=trust,
            source_type="dataset",
        )
        doc_ids.append(doc.document_id)
        indexed += 1
        chunks = knowledge.list_chunks(doc.document_id)
        chunk_total += len(chunks)
        if progress_cb and (indexed % 25 == 0 or processed % 100 == 0):
            progress_cb(
                {
                    "phase": "indexing",
                    "processed": processed,
                    "indexed": indexed,
                    "skippedUnchanged": skipped,
                    "chunkCount": chunk_total,
                }
            )

    return {
        "documentCount": len(doc_ids),
        "chunkCount": chunk_total,
        "indexedCount": indexed,
        "skippedUnchanged": skipped,
        "scope": scope,
        "datasetId": dataset_id,
        "versionId": version_id,
        "documentIdsSample": doc_ids[:20],
    }


def index_version_file(
    knowledge: KnowledgeStore,
    storage_path: Path,
    *,
    dataset_id: str,
    version_id: str,
    scope: str = "dataset",
    max_records: int | None = None,
    progress_cb: ProgressCb | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    path = Path(storage_path)
    if not path.exists():
        raise DatasetError(
            f"Index storage path does not exist: {path}",
            code="storage_missing",
            http_status=400,
        )
    if not path.is_file():
        raise DatasetError(
            f"Index storage path is not a file: {path}",
            code="storage_not_file",
            http_status=400,
        )
    return index_records(
        knowledge,
        iter_materialized_jsonl(path),
        dataset_id=dataset_id,
        version_id=version_id,
        scope=scope,
        max_records=max_records,
        progress_cb=progress_cb,
        cancel_cb=cancel_cb,
    )
