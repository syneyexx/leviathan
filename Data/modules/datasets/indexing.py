"""Index dataset versions into KnowledgeStore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.knowledge import KnowledgeStore

from .materialize import load_materialized_jsonl
from .types import CanonicalRecord, DatasetError


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
    records: list[CanonicalRecord],
    *,
    dataset_id: str,
    version_id: str,
    scope: str = "dataset",
    max_records: int | None = None,
) -> dict[str, Any]:
    """Upsert each record as a knowledge document with dataset provenance."""
    knowledge.initialize()
    selected = records if max_records is None else records[:max_records]
    doc_ids: list[str] = []
    chunk_total = 0
    for rec in selected:
        text = _record_document_text(rec)
        if not text.strip():
            continue
        # Stable document id ties knowledge row to dataset record
        document_id = f"dataset:{dataset_id}:{version_id}:{rec.id}"
        title = f"dataset/{dataset_id}/{rec.id}"
        trust = {
            "trust": "dataset",
            "datasetId": dataset_id,
            "versionId": version_id,
            "recordId": rec.id,
            "scope": scope,
            "split": rec.split,
        }
        doc = knowledge.upsert_document(
            title=title,
            content=text,
            source=f"dataset:{scope}",
            document_id=document_id,
            trust_metadata=trust,
        )
        doc_ids.append(doc.document_id)
        chunks = knowledge.list_chunks(doc.document_id)
        chunk_total += len(chunks)
    return {
        "documentCount": len(doc_ids),
        "chunkCount": chunk_total,
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
    records = load_materialized_jsonl(path)
    return index_records(
        knowledge,
        records,
        dataset_id=dataset_id,
        version_id=version_id,
        scope=scope,
        max_records=max_records,
    )
