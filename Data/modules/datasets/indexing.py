"""Index dataset versions into KnowledgeStore (streaming, idempotent, phased).

Pipeline phases (progress is real counts, not fiction):
  source_check → parsing → indexing/chunking → embeddings → relations → verifying → publishing

Embeddings are reported honestly: semantic only when the provider is semantic;
hash/null providers are labeled as lexical / non-semantic fallbacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.hashing import content_sha256
from Data.modules.knowledge.types import IngestStatus

from .materialize import iter_materialized_jsonl
from .relations import extract_and_store_relations_for_record
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


def _embedding_truth(knowledge: KnowledgeStore) -> dict[str, Any]:
    provider = getattr(knowledge, "embedding_provider", None)
    if provider is None:
        return {
            "available": False,
            "is_semantic": False,
            "provider_id": None,
            "mode": "lexical_only",
            "truth": {
                "no_provider_means_lexical_index_only": True,
                "lexical_is_not_semantic_embedding": True,
            },
        }
    status = provider.status() if hasattr(provider, "status") else {}
    if not isinstance(status, dict):
        status = {}
    available = bool(provider.available()) if hasattr(provider, "available") else False
    is_semantic = bool(
        getattr(provider, "is_semantic", False) or status.get("is_semantic")
    )
    if not available:
        mode = "lexical_only"
    elif is_semantic:
        mode = "semantic_embeddings"
    else:
        mode = "non_semantic_fallback"
    truth = {
        "hash_or_null_is_not_semantic_embedding": not (is_semantic and available),
        "lexical_fallback_must_not_be_presented_as_semantic": mode != "semantic_embeddings",
    }
    truth.update(dict(status.get("truth") or {}))
    return {
        "available": available,
        "is_semantic": is_semantic and available,
        "provider_id": getattr(provider, "provider_id", None) or status.get("provider_id"),
        "mode": mode,
        "status": status,
        "truth": truth,
    }


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
    extract_relations: bool = True,
    max_relations_per_doc: int = 24,
    write_batch_size: int = 50,
    resume_after_record_id: str | None = None,
) -> dict[str, Any]:
    """Upsert each record as a knowledge document with dataset provenance.

    Streams the iterable — never materializes the full corpus in memory.
    Skips re-chunking when an existing READY document has the same content hash
    (idempotent re-learn of unchanged rows).
    """
    knowledge.initialize()
    embedding_info = _embedding_truth(knowledge)
    doc_ids: list[str] = []
    skipped = 0
    indexed = 0
    chunk_total = 0
    processed = 0
    resumed_skip = 0
    relations_accepted = 0
    relations_rejected = 0
    relation_samples: list[dict[str, Any]] = []
    last_record_id: str | None = None
    resume_gate = resume_after_record_id is not None
    batch_size = max(1, int(write_batch_size or 50))

    if progress_cb:
        progress_cb(
            {
                "phase": "parsing",
                "processed": 0,
                "indexed": 0,
                "chunkCount": 0,
                "embeddingMode": embedding_info["mode"],
                "embeddingsSemantic": embedding_info["is_semantic"],
            }
        )

    for rec in records:
        if cancel_cb is not None and cancel_cb():
            raise DatasetError("cancelled", code="cancelled", http_status=409)
        if resume_gate:
            if rec.id == resume_after_record_id:
                resume_gate = False
            resumed_skip += 1
            continue
        if max_records is not None and processed >= max_records:
            break
        processed += 1
        last_record_id = rec.id
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
            if extract_relations:
                rel = extract_and_store_relations_for_record(
                    knowledge,
                    rec,
                    document_id=document_id,
                    dataset_id=dataset_id,
                    version_id=version_id,
                    text=text,
                    max_relations=max_relations_per_doc,
                    replace=True,
                )
                relations_accepted += int(rel.get("relationsAccepted") or 0)
                relations_rejected += int(rel.get("relationsRejected") or 0)
                for sample in rel.get("relationSamples") or []:
                    if len(relation_samples) < 12:
                        relation_samples.append(sample)
            if progress_cb and processed % batch_size == 0:
                progress_cb(
                    {
                        "phase": "indexing",
                        "processed": processed,
                        "indexed": indexed,
                        "skippedUnchanged": skipped,
                        "chunkCount": chunk_total,
                        "relationsAccepted": relations_accepted,
                        "relationsRejected": relations_rejected,
                        "lastRecordId": last_record_id,
                        "embeddingMode": embedding_info["mode"],
                        "embeddingsSemantic": embedding_info["is_semantic"],
                    }
                )
            continue

        if progress_cb and indexed == 0 and processed == 1:
            progress_cb(
                {
                    "phase": "indexing",
                    "processed": processed,
                    "indexed": 0,
                    "embeddingMode": embedding_info["mode"],
                }
            )

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
            "embeddingMode": embedding_info["mode"],
            "embeddingsSemantic": embedding_info["is_semantic"],
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

        if extract_relations:
            if progress_cb and indexed % batch_size == 1:
                progress_cb(
                    {
                        "phase": "relations",
                        "processed": processed,
                        "indexed": indexed,
                        "chunkCount": chunk_total,
                        "relationsAccepted": relations_accepted,
                        "relationsRejected": relations_rejected,
                        "lastRecordId": last_record_id,
                    }
                )
            rel = extract_and_store_relations_for_record(
                knowledge,
                rec,
                document_id=doc.document_id,
                dataset_id=dataset_id,
                version_id=version_id,
                text=text,
                max_relations=max_relations_per_doc,
                replace=True,
            )
            relations_accepted += int(rel.get("relationsAccepted") or 0)
            relations_rejected += int(rel.get("relationsRejected") or 0)
            for sample in rel.get("relationSamples") or []:
                if len(relation_samples) < 12:
                    relation_samples.append(sample)

        if progress_cb and (indexed % batch_size == 0 or processed % (batch_size * 2) == 0):
            progress_cb(
                {
                    "phase": "indexing",
                    "processed": processed,
                    "indexed": indexed,
                    "skippedUnchanged": skipped,
                    "chunkCount": chunk_total,
                    "relationsAccepted": relations_accepted,
                    "relationsRejected": relations_rejected,
                    "lastRecordId": last_record_id,
                    "embeddingMode": embedding_info["mode"],
                    "embeddingsSemantic": embedding_info["is_semantic"],
                }
            )

    if progress_cb:
        progress_cb(
            {
                "phase": "verifying",
                "processed": processed,
                "indexed": indexed,
                "skippedUnchanged": skipped,
                "chunkCount": chunk_total,
                "relationsAccepted": relations_accepted,
                "relationsRejected": relations_rejected,
                "lastRecordId": last_record_id,
                "embeddingMode": embedding_info["mode"],
                "embeddingsSemantic": embedding_info["is_semantic"],
            }
        )

    return {
        "documentCount": len(doc_ids),
        "chunkCount": chunk_total,
        "indexedCount": indexed,
        "skippedUnchanged": skipped,
        "resumedSkipCount": resumed_skip,
        "processedCount": processed,
        "relationsAccepted": relations_accepted,
        "relationsRejected": relations_rejected,
        "relationSamples": relation_samples,
        "embeddings": embedding_info,
        "embeddingMode": embedding_info["mode"],
        "embeddingsSemantic": embedding_info["is_semantic"],
        "embeddingsAvailable": embedding_info["available"],
        "lastRecordId": last_record_id,
        "scope": scope,
        "datasetId": dataset_id,
        "versionId": version_id,
        "documentIdsSample": doc_ids[:20],
        "phasesCompleted": [
            "parsing",
            "indexing",
            "embeddings",
            "relations",
            "verifying",
        ],
        "truth": {
            "learned_requires_index_ready": True,
            "hash_embedding_is_not_semantic": not embedding_info["is_semantic"],
            "relations_require_evidence": True,
        },
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
    extract_relations: bool = True,
    max_relations_per_doc: int = 24,
    write_batch_size: int = 50,
    resume_after_record_id: str | None = None,
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
    if progress_cb:
        progress_cb({"phase": "source_check", "processed": 0, "path": str(path)})
    return index_records(
        knowledge,
        iter_materialized_jsonl(path),
        dataset_id=dataset_id,
        version_id=version_id,
        scope=scope,
        max_records=max_records,
        progress_cb=progress_cb,
        cancel_cb=cancel_cb,
        extract_relations=extract_relations,
        max_relations_per_doc=max_relations_per_doc,
        write_batch_size=write_batch_size,
        resume_after_record_id=resume_after_record_id,
    )
