"""Index dataset versions into KnowledgeStore (streaming, idempotent, phased).

Pipeline phases (progress is real counts, not fiction):
  source_check → parsing → indexing/chunking → embeddings → relations → verifying → publishing

Embeddings are reported honestly: semantic only when the provider is semantic;
hash/null providers are labeled as lexical / non-semantic fallbacks.

Before IndexStatus.READY, a durable integrity receipt must verify (P1-001).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from Data.modules.common.hashing import sha256_text
from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.hashing import content_sha256
from Data.modules.knowledge.types import IngestStatus

from .materialize import iter_materialized_jsonl
from .knowledge_identity import knowledge_source_for_version, resolve_index_scope
from .relations import (
    RELATION_EXTRACTOR_VERSION,
    build_verified_relation_atoms_for_record,
    relation_input_fingerprint,
)
from .types import CanonicalRecord, DatasetError

ProgressCb = Callable[[dict[str, Any]], None]

# P1-010: never retain unbounded document id lists in memory.
_DOCUMENT_ID_SAMPLE_LIMIT = 20


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


def _progress_rates(started: float, processed: int) -> dict[str, Any]:
    elapsed = max(0.0, time.monotonic() - started)
    rates: dict[str, Any] = {"elapsedSeconds": round(elapsed, 4)}
    if elapsed > 0 and processed > 0:
        rates["recordsPerSecond"] = round(processed / elapsed, 4)
    return rates


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def count_documents_for_source(
    knowledge: KnowledgeStore,
    source: str,
    *,
    status: IngestStatus | None = IngestStatus.READY,
) -> int:
    """Exact COUNT of knowledge documents for a canonical source scope."""
    with knowledge.connect() as conn:
        if hasattr(knowledge, "_ensure_schema"):
            knowledge._ensure_schema(conn)  # noqa: SLF001 — shared store helper
        if status is None:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_documents WHERE source = ?",
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_documents WHERE source = ? AND status = ?",
                (source, status.value),
            ).fetchone()
    return int(row["c"] if row else 0)


def count_chunks_for_source(knowledge: KnowledgeStore, source: str) -> int:
    """Exact COUNT of chunks belonging to documents for a source scope."""
    with knowledge.connect() as conn:
        if hasattr(knowledge, "_ensure_schema"):
            knowledge._ensure_schema(conn)  # noqa: SLF001
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE d.source = ?
            """,
            (source,),
        ).fetchone()
    return int(row["c"] if row else 0)


def count_relation_atoms_for_source(knowledge: KnowledgeStore, source: str) -> int:
    """Exact COUNT of relation atoms for documents under a source scope."""
    with knowledge.connect() as conn:
        if hasattr(knowledge, "_ensure_schema"):
            knowledge._ensure_schema(conn)  # noqa: SLF001
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM directional_relation_atoms a
            JOIN knowledge_documents d ON d.id = a.document_id
            WHERE d.source = ?
            """,
            (source,),
        ).fetchone()
    return int(row["c"] if row else 0)


def sample_document_ids_for_source(
    knowledge: KnowledgeStore,
    source: str,
    *,
    limit: int = _DOCUMENT_ID_SAMPLE_LIMIT,
) -> list[str]:
    docs = knowledge.list_documents_by_source(source, limit=max(0, int(limit)), offset=0)
    return [d.document_id for d in docs]


def classify_verification_evidence(
    *,
    present_docs_exact: bool,
    present_chunks_exact: bool,
    relations_exact: bool,
    sampled_presence: bool = False,
) -> str:
    """Honest evidence class: EXACT / SAMPLED / UNMEASURED."""
    if present_docs_exact and present_chunks_exact and relations_exact:
        return "EXACT"
    if sampled_presence or present_docs_exact or present_chunks_exact:
        return "SAMPLED"
    return "UNMEASURED"


def build_index_integrity_receipt(
    *,
    dataset_id: str,
    version_id: str,
    source_fingerprint: str,
    index_id: str,
    expected_records: int | None,
    unique_document_count: int | None,
    present_document_count: int | None,
    chunk_count: int | None,
    present_chunk_count: int | None,
    embedding_mode: str | None,
    embeddings_semantic: bool | None,
    relations_accepted: int | None,
    relations_rejected: int | None,
    present_relation_count: int | None,
    manifest_hash: str | None,
    evidence_class: str,
    verification_status: str,
    verification_errors: list[str] | None = None,
    completed_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Durable index integrity receipt (P1-001)."""
    receipt = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "versionId": version_id,
        "sourceFingerprint": source_fingerprint,
        "indexId": index_id,
        "expectedRecords": expected_records,
        "uniqueDocumentCount": unique_document_count,
        "presentDocumentCount": present_document_count,
        "chunkCount": chunk_count,
        "presentChunkCount": present_chunk_count,
        "embeddingMode": embedding_mode,
        "embeddingsSemantic": embeddings_semantic,
        "relationsAccepted": relations_accepted,
        "relationsRejected": relations_rejected,
        "presentRelationCount": present_relation_count,
        "manifestHash": manifest_hash,
        "completedAt": completed_at or _utc_now_iso(),
        "evidenceClass": evidence_class,
        "verificationStatus": verification_status,
        "verificationErrors": list(verification_errors or []),
        "truth": {
            "ready_requires_verification_pass": True,
            "evidence_class_must_be_honest": True,
            "unmeasured_is_not_pass": True,
            "lexical_is_not_semantic": not bool(embeddings_semantic),
        },
    }
    if extra:
        receipt["extra"] = dict(extra)
    return receipt


def verify_index_integrity(
    knowledge: KnowledgeStore,
    *,
    dataset_id: str,
    version_id: str,
    source_fingerprint: str,
    index_id: str,
    outcome: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    expected_records: int | None = None,
    scope: str | None = None,
    sample_limit: int = _DOCUMENT_ID_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Verify durable index evidence before READY. Failure ⇒ not READY.

    Evidence classification is honest:
      - EXACT when store COUNTs match indexing outcome
      - SAMPLED when only sample presence is checked
      - UNMEASURED when counts cannot be obtained
    """
    knowledge.initialize()
    resolved_scope = scope or knowledge_source_for_version(dataset_id, version_id)
    unique_docs = int(outcome.get("documentCount") or 0)
    reported_chunks = int(outcome.get("chunkCount") or 0)
    relations_accepted = int(outcome.get("relationsAccepted") or 0)
    relations_rejected = int(outcome.get("relationsRejected") or 0)
    embedding_mode = outcome.get("embeddingMode")
    embeddings_semantic = outcome.get("embeddingsSemantic")
    if expected_records is None:
        expected_records = int(outcome.get("processedCount") or unique_docs)

    manifest_hash = None
    if manifest is not None:
        manifest_hash = sha256_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str)
        )

    errors: list[str] = []
    present_docs: int | None = None
    present_chunks: int | None = None
    present_relations: int | None = None
    docs_exact = False
    chunks_exact = False
    relations_exact = False
    sampled_ok = False

    try:
        present_docs = count_documents_for_source(knowledge, resolved_scope)
        docs_exact = True
        if present_docs != unique_docs:
            errors.append(
                f"present_document_count={present_docs} != unique_document_count={unique_docs}"
            )
    except Exception as exc:  # noqa: BLE001 — degrade to UNMEASURED honestly
        errors.append(f"document_count_unmeasured: {exc}")

    try:
        present_chunks = count_chunks_for_source(knowledge, resolved_scope)
        chunks_exact = True
        if present_chunks != reported_chunks:
            errors.append(
                f"present_chunk_count={present_chunks} != chunk_count={reported_chunks}"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"chunk_count_unmeasured: {exc}")

    try:
        present_relations = count_relation_atoms_for_source(knowledge, resolved_scope)
        relations_exact = True
        # Accepted relations should be present; allow skipped-unchanged to inflate store.
        if present_relations < relations_accepted:
            errors.append(
                f"present_relation_count={present_relations} < relations_accepted={relations_accepted}"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"relation_count_unmeasured: {exc}")

    # Bounded sample: confirm at least one reported sample id is present when any docs exist.
    sample_ids = list(outcome.get("documentIdsSample") or [])[:sample_limit]
    if sample_ids:
        missing_sample = 0
        checked = 0
        for doc_id in sample_ids:
            checked += 1
            doc = knowledge.get_document(doc_id)
            if doc is None or doc.status != IngestStatus.READY:
                missing_sample += 1
        sampled_ok = missing_sample == 0 and checked > 0
        if missing_sample:
            errors.append(f"sample_missing_documents={missing_sample}/{checked}")
    elif unique_docs == 0:
        sampled_ok = True
    else:
        # No sample retained — do not claim sampled presence.
        sampled_ok = False

    evidence = classify_verification_evidence(
        present_docs_exact=docs_exact,
        present_chunks_exact=chunks_exact,
        relations_exact=relations_exact,
        sampled_presence=sampled_ok and not (docs_exact and chunks_exact and relations_exact),
    )

    # UNMEASURED core counts cannot PASS.
    if not docs_exact or not chunks_exact:
        if "document_count_unmeasured" in str(errors) or "chunk_count_unmeasured" in str(errors):
            evidence = "UNMEASURED" if evidence == "UNMEASURED" else evidence
        if not docs_exact or not chunks_exact:
            # Force fail-closed when we cannot measure presence.
            if not any("unmeasured" in e for e in errors):
                errors.append("core_counts_incomplete")
            verification_status = "FAIL"
        else:
            verification_status = "FAIL" if errors else "PASS"
    else:
        verification_status = "FAIL" if errors else "PASS"

    if evidence == "UNMEASURED":
        verification_status = "FAIL"
        if not any("unmeasured" in e for e in errors):
            errors.append("evidence_unmeasured_cannot_pass")

    if not source_fingerprint:
        errors.append("missing_source_fingerprint")
        verification_status = "FAIL"

    if not index_id:
        errors.append("missing_index_id")
        verification_status = "FAIL"

    receipt = build_index_integrity_receipt(
        dataset_id=dataset_id,
        version_id=version_id,
        source_fingerprint=str(source_fingerprint or ""),
        index_id=index_id,
        expected_records=expected_records,
        unique_document_count=unique_docs,
        present_document_count=present_docs,
        chunk_count=reported_chunks,
        present_chunk_count=present_chunks,
        embedding_mode=str(embedding_mode) if embedding_mode is not None else None,
        embeddings_semantic=bool(embeddings_semantic) if embeddings_semantic is not None else None,
        relations_accepted=relations_accepted,
        relations_rejected=relations_rejected,
        present_relation_count=present_relations,
        manifest_hash=manifest_hash,
        evidence_class=evidence,
        verification_status=verification_status,
        verification_errors=errors,
        extra={
            "scope": resolved_scope,
            "sampleChecked": len(sample_ids),
            "sampleOk": sampled_ok,
        },
    )
    return receipt


def index_records(
    knowledge: KnowledgeStore,
    records: Iterable[CanonicalRecord],
    *,
    dataset_id: str,
    version_id: str,
    scope: str | None = None,
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

    Knowledge ``source`` is the canonical contract
    ``dataset:<dataset_id>:<version_id>`` (see knowledge_identity.py).

    P1-012: if ``resume_after_record_id`` is set but never found, fails closed
    instead of silently skipping the whole corpus.
    """
    knowledge.initialize()
    scope = resolve_index_scope(
        dataset_id=dataset_id,
        version_id=version_id,
        requested_scope=scope,
    )
    embedding_info = _embedding_truth(knowledge)
    # P1-010: count + bounded sample — never unbounded doc_ids list.
    document_count = 0
    document_ids_sample: list[str] = []
    skipped = 0
    indexed = 0
    chunk_total = 0
    processed = 0
    resumed_skip = 0
    relations_accepted = 0
    relations_rejected = 0
    relations_skipped_unchanged = 0
    relation_samples: list[dict[str, Any]] = []
    last_record_id: str | None = None
    resume_gate = resume_after_record_id is not None
    resume_marker_found = resume_after_record_id is None
    batch_size = max(1, int(write_batch_size or 50))
    started = time.monotonic()
    pending_relation_writes: list[
        tuple[str, list[dict[str, Any]], str]
    ] = []  # (document_id, atoms, fingerprint)
    relation_tx_count = 0

    def _note_document(document_id: str) -> None:
        nonlocal document_count
        document_count += 1
        if len(document_ids_sample) < _DOCUMENT_ID_SAMPLE_LIMIT:
            document_ids_sample.append(document_id)

    def _emit(phase: str, **extra: Any) -> None:
        if not progress_cb:
            return
        payload = {
            "phase": phase,
            "processed": processed,
            "indexed": indexed,
            "skippedUnchanged": skipped,
            "chunkCount": chunk_total,
            "relationsAccepted": relations_accepted,
            "relationsRejected": relations_rejected,
            "relationsSkippedUnchanged": relations_skipped_unchanged,
            "lastRecordId": last_record_id,
            "embeddingMode": embedding_info["mode"],
            "embeddingsSemantic": embedding_info["is_semantic"],
            "relationTransactionCount": relation_tx_count,
            **_progress_rates(started, processed),
        }
        payload.update(extra)
        progress_cb(payload)

    def _flush_relation_batch(*, force: bool = False) -> None:
        nonlocal relation_tx_count, relations_accepted
        if not pending_relation_writes:
            return
        if not force and len(pending_relation_writes) < batch_size:
            return
        batch = pending_relation_writes[:]
        pending_relation_writes.clear()
        replacements = [(doc_id, atoms) for doc_id, atoms, _fp in batch]
        knowledge.replace_relation_atoms_batch(replacements)
        relation_tx_count += 1
        for doc_id, _atoms, fingerprint in batch:
            knowledge.merge_document_trust_metadata(
                doc_id,
                {
                    "relationInputFingerprint": fingerprint,
                    "relationExtractorVersion": RELATION_EXTRACTOR_VERSION,
                },
            )

    if progress_cb:
        progress_cb(
            {
                "phase": "parsing",
                "processed": 0,
                "indexed": 0,
                "chunkCount": 0,
                "embeddingMode": embedding_info["mode"],
                "embeddingsSemantic": embedding_info["is_semantic"],
                **_progress_rates(started, 0),
            }
        )

    for rec in records:
        if cancel_cb is not None and cancel_cb():
            _flush_relation_batch(force=True)
            raise DatasetError("cancelled", code="cancelled", http_status=409)
        if resume_gate:
            if rec.id == resume_after_record_id:
                resume_gate = False
                resume_marker_found = True
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
        fingerprint = relation_input_fingerprint(
            rec,
            content_hash=digest,
            dataset_id=dataset_id,
            version_id=version_id,
        )
        existing = knowledge.get_document(document_id)
        if (
            existing is not None
            and existing.status == IngestStatus.READY
            and existing.content_hash == digest
        ):
            skipped += 1
            _note_document(document_id)
            chunks = knowledge.list_chunks(document_id)
            chunk_total += len(chunks)
            if extract_relations:
                prior_fp = (existing.trust_metadata or {}).get("relationInputFingerprint")
                atom_count = knowledge.count_relation_atoms_for_document(document_id)
                if prior_fp == fingerprint and atom_count > 0:
                    relations_skipped_unchanged += 1
                else:
                    built = build_verified_relation_atoms_for_record(
                        rec,
                        document_id=document_id,
                        dataset_id=dataset_id,
                        version_id=version_id,
                        text=text,
                        max_relations=max_relations_per_doc,
                    )
                    relations_accepted += int(built.get("relationsAccepted") or 0)
                    relations_rejected += int(built.get("relationsRejected") or 0)
                    for sample in built.get("relationSamples") or []:
                        if len(relation_samples) < 12:
                            relation_samples.append(sample)
                    pending_relation_writes.append(
                        (document_id, list(built.get("atoms") or []), fingerprint)
                    )
                    _flush_relation_batch(force=False)
            if progress_cb and processed % batch_size == 0:
                _emit("indexing")
            continue

        if progress_cb and indexed == 0 and processed == 1:
            _emit("indexing")

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
            "relationInputFingerprint": fingerprint,
            "relationExtractorVersion": RELATION_EXTRACTOR_VERSION,
        }
        doc = knowledge.upsert_document(
            title=title,
            content=text,
            source=scope,
            document_id=document_id,
            trust_metadata=trust,
            source_type="dataset",
        )
        _note_document(doc.document_id)
        indexed += 1
        chunks = knowledge.list_chunks(doc.document_id)
        chunk_total += len(chunks)

        if extract_relations:
            if progress_cb and indexed % batch_size == 1:
                _emit("relations")
            built = build_verified_relation_atoms_for_record(
                rec,
                document_id=doc.document_id,
                dataset_id=dataset_id,
                version_id=version_id,
                text=text,
                max_relations=max_relations_per_doc,
            )
            relations_accepted += int(built.get("relationsAccepted") or 0)
            relations_rejected += int(built.get("relationsRejected") or 0)
            for sample in built.get("relationSamples") or []:
                if len(relation_samples) < 12:
                    relation_samples.append(sample)
            pending_relation_writes.append(
                (doc.document_id, list(built.get("atoms") or []), fingerprint)
            )
            _flush_relation_batch(force=False)

        if progress_cb and (indexed % batch_size == 0 or processed % (batch_size * 2) == 0):
            _emit("indexing")

    _flush_relation_batch(force=True)

    # P1-012: resume marker missing must fail safe (not skip whole corpus).
    if resume_after_record_id is not None and not resume_marker_found:
        raise DatasetError(
            f"Resume marker not found in corpus: {resume_after_record_id!r}",
            code="resume_marker_missing",
            http_status=409,
            details={
                "resumeAfterRecordId": resume_after_record_id,
                "resumedSkipCount": resumed_skip,
                "processedCount": processed,
            },
        )

    if progress_cb:
        _emit("verifying")

    return {
        "documentCount": document_count,
        "chunkCount": chunk_total,
        "indexedCount": indexed,
        "skippedUnchanged": skipped,
        "resumedSkipCount": resumed_skip,
        "processedCount": processed,
        "relationsAccepted": relations_accepted,
        "relationsRejected": relations_rejected,
        "relationsSkippedUnchanged": relations_skipped_unchanged,
        "relationTransactionCount": relation_tx_count,
        "relationSamples": relation_samples,
        "embeddings": embedding_info,
        "embeddingMode": embedding_info["mode"],
        "embeddingsSemantic": embedding_info["is_semantic"],
        "embeddingsAvailable": embedding_info["available"],
        "lastRecordId": last_record_id,
        "scope": scope,
        "datasetId": dataset_id,
        "versionId": version_id,
        "documentIdsSample": list(document_ids_sample),
        **_progress_rates(started, processed),
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
            "relation_writes_are_batched_transactions": True,
            "unchanged_relation_skip_requires_fingerprint_match": True,
            "document_ids_are_bounded_sample": True,
            "resume_marker_missing_fails_closed": True,
        },
    }


def index_version_file(
    knowledge: KnowledgeStore,
    storage_path: Path,
    *,
    dataset_id: str,
    version_id: str,
    scope: str | None = None,
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
