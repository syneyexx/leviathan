"""Background worker that turns registered datasets into HADES' offline brain.

Two durable phases are used:
1. materialize source records as local JSONL under HADES;
2. project safe text into the existing Knowledge Library, then atomically publish its
   FTS rows so normal Chat/Tasks retrieval can search it.

The worker is resumable and memory-bounded and performs no model training. Raw
selected records remain in the local snapshot. Searchable text re-redacts likely
secrets and explicit hidden-reasoning columns are excluded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx

from dataset_brain import brain_dir, read_manifest, utc_now, write_brain_job_state, write_manifest
from gen2.flight_recorder import redact_secrets
from platform_db import PlatformDatabase
from platform_services_core import chunk_text
from training_service import HF_DATASET_SERVER, TrainingWorkspace, format_training_example

MAX_JSONL_ROW_CHARS = 16 * 1024 * 1024
HF_PAGE_ROWS = 100
CHECKPOINT_ROWS = 1_000
SEQUENCE_STRIDE = 1_000_000
MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024
_HIDDEN_RECORD_KEYS = frozenset(
    {
        "reasoning",
        "chain_of_thought",
        "chain-of-thought",
        "cot",
        "thought",
        "thoughts",
        "scratchpad",
        "internal_reasoning",
        "analysis",
    }
)


def _cancel_requested(job_path: Path) -> bool:
    return (job_path.parent / "cancel.requested").is_file()


def _ensure_disk_headroom(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path.parent).free
    if free < MIN_FREE_BYTES:
        raise OSError(
            f"Te weinig vrije schijfruimte voor veilige Brain-import: {free} bytes vrij; "
            "minimaal 5 GiB reserve vereist."
        )


def _stable_hash(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8", "ignore")).hexdigest()


def _source_fingerprint(dataset: dict[str, Any]) -> str:
    source_type = str(dataset.get("source_type") or "")
    if source_type == "huggingface":
        src = dict(dataset.get("source") or {})
        payload = {
            "source_type": source_type,
            "dataset_id": src.get("dataset_id"),
            "config": src.get("config"),
            "split": src.get("split"),
            "row_count": dataset.get("row_count"),
        }
    else:
        path = Path(str(dataset.get("path") or "")).expanduser().resolve()
        stat = path.stat() if path.is_file() else None
        payload = {
            "source_type": source_type,
            "path": str(path),
            "size": stat.st_size if stat else None,
            "mtime_ns": stat.st_mtime_ns if stat else None,
        }
    return _stable_hash(payload)


def _mapping_fingerprint(dataset: dict[str, Any]) -> str:
    return _stable_hash(dict(dataset.get("mapping") or {}))


@contextmanager
def _brain_connection(db: PlatformDatabase) -> Iterator[sqlite3.Connection]:
    """Batch connection without PlatformDatabase's per-close WAL TRUNCATE.

    Dataset indexing can create millions of rows. Checkpointing/truncating WAL after
    every batch would dominate the import, while ordinary HADES connections keep their
    existing behavior. This worker still commits each bounded batch independently.
    """
    conn = sqlite3.connect(db.path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        line_no = 0
        while True:
            line = handle.readline(MAX_JSONL_ROW_CHARS + 1)
            if not line:
                return
            line_no += 1
            if len(line) > MAX_JSONL_ROW_CHARS and not line.endswith("\n"):
                raise ValueError(f"JSONL-regel {line_no} is groter dan 16 MB.")
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Ongeldige JSONL op regel {line_no}: {exc.msg}.") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL-regel {line_no} is geen object.")
            yield value


def _iter_local_rows(dataset: dict[str, Any]) -> Iterator[dict[str, Any]]:
    path = Path(str(dataset.get("path") or "")).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Datasetbestand bestaat niet meer: {path}")
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        yield from _iter_jsonl(path)
        return
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(MAX_JSONL_ROW_CHARS)
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                if not reader.fieldnames:
                    raise ValueError("CSV/TSV heeft geen kolomkoppen.")
                for row in reader:
                    yield dict(row)
        finally:
            csv.field_size_limit(previous)
        return
    if suffix == ".json":
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("JSON-array >256 MB is niet streaming-veilig; converteer naar JSONL of Parquet.")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = (value.get("data") or value.get("rows")) if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("JSON-dataset moet een array zijn, of een object met data/rows.")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("JSON-dataset bevat een record dat geen object is.")
            yield row
        return
    if suffix == ".parquet":
        if importlib.util.find_spec("pyarrow") is None:
            raise RuntimeError("Parquet Brain-indexering vereist pyarrow (optionele training dependency).")
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=512):
            for row in batch.to_pylist():
                if isinstance(row, dict):
                    yield row
        return
    raise ValueError(f"Niet-ondersteund datasetformaat: {suffix or '(geen extensie)'}.")


def _iter_hf_viewer_rows(dataset: dict[str, Any], start: int, token: str | None) -> Iterator[dict[str, Any]]:
    """Page exact Dataset Viewer rows from an absolute source-row offset.

    Viewer responses marked ``partial`` or containing truncated cells are rejected:
    an offline Brain snapshot must never silently represent only part of a dataset.
    """
    source = dict(dataset.get("source") or {})
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    offset = max(0, int(start))
    with httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True, headers=headers) as client:
        while True:
            response = client.get(
                f"{HF_DATASET_SERVER}/rows",
                params={
                    "dataset": source.get("dataset_id"),
                    "config": source.get("config"),
                    "split": source.get("split"),
                    "offset": offset,
                    "length": HF_PAGE_ROWS,
                },
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Hugging Face rows API gaf HTTP {response.status_code} bij offset {offset}.")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Hugging Face rows API gaf geen bruikbaar object terug.")
            if bool(payload.get("partial")):
                raise RuntimeError(
                    "Hugging Face Dataset Viewer rapporteert partial=true; volledige Brain-materialisatie "
                    "vereist de optionele 'datasets' streaming dependency."
                )
            raw_rows = payload.get("rows")
            if not isinstance(raw_rows, list):
                raise RuntimeError("Hugging Face rows API gaf geen bruikbare rows terug.")
            raw_count = len(raw_rows)
            if raw_count == 0:
                return
            for item in raw_rows:
                if not isinstance(item, dict):
                    continue
                truncated_cells = item.get("truncated_cells")
                if isinstance(truncated_cells, list) and truncated_cells:
                    raise RuntimeError(
                        "Hugging Face Dataset Viewer heeft cellen afgekapt; HADES weigert een onvolledige "
                        "offline Brain-snapshot. Installeer de optionele 'datasets' streaming dependency."
                    )
                row = item.get("row")
                if isinstance(row, dict):
                    yield row
            # Offset tracks source rows, not only rows we happened to render.
            offset += raw_count
            total = payload.get("num_rows_total")
            if isinstance(total, int) and offset >= total:
                return


def _iter_hf_rows(dataset: dict[str, Any], start: int, token: str | None) -> Iterator[dict[str, Any]]:
    """Prefer HF Datasets streaming; safely fall back from the original checkpoint.

    Fallback is allowed only before the first *new* row has been emitted. The absolute
    resume offset is kept immutable so a failure after ``stream.skip(resume_start)`` can
    never restart Dataset Viewer at row 0 and duplicate the local snapshot.
    """
    resume_start = max(0, int(start))
    if importlib.util.find_spec("datasets") is not None:
        source = dict(dataset.get("source") or {})
        emitted = 0
        try:
            from datasets import load_dataset  # type: ignore[import-not-found]

            stream = load_dataset(
                str(source.get("dataset_id") or ""),
                name=str(source.get("config") or ""),
                split=str(source.get("split") or ""),
                streaming=True,
                token=token or None,
            )
            skip_applied = False
            if resume_start and hasattr(stream, "skip"):
                stream = stream.skip(resume_start)
                skip_applied = True
            for index, row in enumerate(stream):
                if not skip_applied and index < resume_start:
                    continue
                if isinstance(row, dict):
                    emitted += 1
                    yield dict(row)
            return
        except Exception as exc:
            if emitted:
                raise RuntimeError(
                    f"Hugging Face streaming stopte na {emitted} nieuwe rijen; "
                    "checkpoint behouden, geen onveilige fallback."
                ) from exc
            print(
                f"[HADES BRAIN] datasets streaming viel terug op Dataset Viewer vanaf rij "
                f"{resume_start}: {type(exc).__name__}: {exc}",
                flush=True,
            )
    yield from _iter_hf_viewer_rows(dataset, resume_start, token)


def _serialize_row(row: dict[str, Any]) -> bytes:
    text = json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)
    encoded = (text + "\n").encode("utf-8")
    if len(encoded) > MAX_JSONL_ROW_CHARS:
        raise ValueError("Datasetrecord is groter dan 16 MB en wordt niet stil afgekapt.")
    return encoded


def _brain_text(row: dict[str, Any], mapping: dict[str, Any]) -> str:
    explicit = str(mapping.get("text_field") or "").strip()
    if explicit and explicit.lower() in _HIDDEN_RECORD_KEYS:
        raise ValueError("Een hidden-reasoning kolom kan niet als Brain-tekstkolom worden geïndexeerd.")
    safe_row = {key: value for key, value in row.items() if str(key).lower() not in _HIDDEN_RECORD_KEYS}
    rendered = format_training_example(safe_row, mapping).strip()
    if not rendered:
        return ""
    redacted = redact_secrets(rendered)
    return str(redacted).strip() if redacted is not None else ""


def _clear_source_chunks(db: PlatformDatabase, source_id: str) -> None:
    with _brain_connection(db) as conn:
        conn.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))


def _clear_source_fts(db: PlatformDatabase, source_id: str) -> None:
    with _brain_connection(db) as conn:
        conn.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))


def _publish_fts(db: PlatformDatabase, source_id: str, title: str) -> int:
    """Atomically make a fully built chunk set searchable."""
    with _brain_connection(db) as conn:
        conn.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))
        conn.execute(
            """INSERT INTO knowledge_fts(chunk_id,source_id,title,heading,content)
               SELECT id,source_id,?,heading,content
               FROM knowledge_chunks
               WHERE source_id=?
               ORDER BY sequence""",
            (title, source_id),
        )
        row = conn.execute("SELECT COUNT(*) AS n FROM knowledge_fts WHERE source_id=?", (source_id,)).fetchone()
    return int(row["n"] if row else 0)


def _ensure_chunk_hash_index(db: PlatformDatabase) -> None:
    with _brain_connection(db) as conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_hash "
            "ON knowledge_chunks(source_id, content_hash)"
        )


def _append_chunks(db: PlatformDatabase, *, source_id: str, chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    inserted = 0
    with _brain_connection(db) as conn:
        for chunk in chunks:
            content = str(chunk.get("content") or "").strip()
            digest = str(chunk.get("content_hash") or "")
            if not content or not digest:
                continue
            exists = conn.execute(
                "SELECT id FROM knowledge_chunks WHERE source_id=? AND content_hash=? LIMIT 1",
                (source_id, digest),
            ).fetchone()
            if exists:
                continue
            try:
                cursor = conn.execute(
                    """INSERT INTO knowledge_chunks
                       (id,source_id,sequence,heading,content,content_hash,token_estimate,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        str(chunk["id"]),
                        source_id,
                        int(chunk["sequence"]),
                        str(chunk.get("heading") or ""),
                        content,
                        digest,
                        int(chunk.get("token_estimate") or max(1, len(content) // 4)),
                        utc_now(),
                    ),
                )
            except sqlite3.IntegrityError:
                continue
            inserted += int(bool(cursor.rowcount))
    return inserted


def _source_chunk_count(db: PlatformDatabase, source_id: str) -> int:
    with _brain_connection(db) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM knowledge_chunks WHERE source_id=?", (source_id,)).fetchone()
    return int(row["n"] if row else 0)


def _checkpoint(
    job_path: Path,
    training_root: Path,
    dataset_id: str,
    *,
    status: str,
    phase: str,
    materialized_rows: int,
    indexed_rows: int,
    chunks_indexed: int,
    progress: float,
    source_id: str | None = None,
    **extra: Any,
) -> None:
    common = {
        "status": status,
        "phase": phase,
        "materialized_rows": materialized_rows,
        "indexed_rows": indexed_rows,
        "chunks_indexed": chunks_indexed,
        "progress": max(0.0, min(1.0, float(progress))),
        **extra,
    }
    if source_id is not None:
        common["source_id"] = source_id
    write_brain_job_state(job_path, common)
    write_manifest(training_root, dataset_id, common)


def _read_job(job_path: Path) -> dict[str, Any]:
    with job_path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Brain job.json is geen object.")
    return value


def _reset_materialization(
    training_root: Path,
    dataset_id: str,
    snapshot: Path,
    source_fp: str,
    mapping_fp: str,
) -> dict[str, Any]:
    snapshot.unlink(missing_ok=True)
    return write_manifest(
        training_root,
        dataset_id,
        {
            "status": "materializing",
            "phase": "materializing",
            "materialized_rows": 0,
            "materialized_complete": False,
            "snapshot_bytes": 0,
            "indexed_rows": 0,
            "chunks_indexed": 0,
            "source_fingerprint": source_fp,
            "mapping_fingerprint": mapping_fp,
            "snapshot_path": str(snapshot),
            "error": None,
        },
    )


def _materialize(
    *,
    job_path: Path,
    training_root: Path,
    dataset: dict[str, Any],
    manifest: dict[str, Any],
    token: str | None,
) -> dict[str, Any]:
    dataset_id = str(dataset["id"])
    target_dir = brain_dir(training_root, dataset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot = target_dir / "data.jsonl"
    _ensure_disk_headroom(snapshot)
    source_fp = _source_fingerprint(dataset)
    mapping_fp = _mapping_fingerprint(dataset)
    rematerialize = bool(_read_job(job_path).get("rematerialize"))
    if rematerialize or manifest.get("source_fingerprint") != source_fp:
        manifest = _reset_materialization(training_root, dataset_id, snapshot, source_fp, mapping_fp)
    if manifest.get("materialized_complete") and snapshot.is_file():
        return manifest

    start = max(0, int(manifest.get("materialized_rows") or 0))
    checkpoint_bytes = max(0, int(manifest.get("snapshot_bytes") or 0))
    if start:
        if not snapshot.is_file() or checkpoint_bytes <= 0 or snapshot.stat().st_size < checkpoint_bytes:
            manifest = _reset_materialization(training_root, dataset_id, snapshot, source_fp, mapping_fp)
            start = 0
            checkpoint_bytes = 0
        else:
            with snapshot.open("r+b") as trim:
                trim.truncate(checkpoint_bytes)
    elif snapshot.exists() and snapshot.stat().st_size:
        snapshot.unlink()

    source_type = str(dataset.get("source_type") or "")
    if source_type == "huggingface":
        rows: Iterable[dict[str, Any]] = _iter_hf_rows(dataset, start, token)
        iterator_skips_resume = True
    else:
        rows = _iter_local_rows(dataset)
        iterator_skips_resume = False

    known_total = dataset.get("row_count") if isinstance(dataset.get("row_count"), int) else None
    written = start
    mode = "ab" if start else "wb"
    with snapshot.open(mode) as handle:
        for source_index, row in enumerate(rows):
            if not iterator_skips_resume and source_index < start:
                continue
            if _cancel_requested(job_path):
                handle.flush()
                os.fsync(handle.fileno())
                raise InterruptedError("cancelled")
            handle.write(_serialize_row(row))
            written += 1
            if written % CHECKPOINT_ROWS == 0:
                handle.flush()
                os.fsync(handle.fileno())
                _ensure_disk_headroom(snapshot)
                fraction = (written / known_total) if known_total and known_total > 0 else 0.0
                _checkpoint(
                    job_path,
                    training_root,
                    dataset_id,
                    status="running",
                    phase="materializing",
                    materialized_rows=written,
                    indexed_rows=int(manifest.get("indexed_rows") or 0),
                    chunks_indexed=int(manifest.get("chunks_indexed") or 0),
                    progress=min(0.45, max(0.01, fraction * 0.45)),
                    snapshot_path=str(snapshot),
                    snapshot_bytes=handle.tell(),
                    source_fingerprint=source_fp,
                )
        handle.flush()
        os.fsync(handle.fileno())
        final_bytes = handle.tell()

    return write_manifest(
        training_root,
        dataset_id,
        {
            "status": "indexing",
            "phase": "indexing",
            "materialized_rows": written,
            "materialized_complete": True,
            "snapshot_bytes": final_bytes,
            "snapshot_path": str(snapshot),
            "source_fingerprint": source_fp,
            "mapping_fingerprint": mapping_fp,
            "error": None,
        },
    )


def _index_snapshot(
    *,
    job_path: Path,
    training_root: Path,
    dataset: dict[str, Any],
    manifest: dict[str, Any],
    db: PlatformDatabase,
) -> dict[str, Any]:
    dataset_id = str(dataset["id"])
    snapshot = Path(str(manifest.get("snapshot_path") or "")).expanduser().resolve()
    if not snapshot.is_file() or not manifest.get("materialized_complete"):
        raise RuntimeError("Dataset snapshot is niet volledig gematerialiseerd.")
    _ensure_disk_headroom(db.path)

    source_fp = str(manifest.get("source_fingerprint") or _source_fingerprint(dataset))
    mapping_fp = _mapping_fingerprint(dataset)
    rebuild = bool(_read_job(job_path).get("rebuild_index"))
    uri = f"dataset://{dataset_id}"
    title = f"Dataset · {dataset.get('name') or dataset_id}"
    existing = db.get_knowledge_source_by_uri("dataset", uri)
    prior_metadata = (existing or {}).get("metadata") if isinstance((existing or {}).get("metadata"), dict) else {}
    prior_mapping = str(prior_metadata.get("mapping_fingerprint") or "")
    indexed_rows = 0 if (rebuild or prior_mapping != mapping_fp) else max(0, int(manifest.get("indexed_rows") or 0))

    source = db.upsert_knowledge_source(
        title=title,
        source_type="dataset",
        uri=uri,
        local_path=str(snapshot),
        content_hash=_stable_hash({"source": source_fp, "rows": manifest.get("materialized_rows")}),
        metadata={
            "role": "knowledge",
            "content_is_data_not_policy": True,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name"),
            "dataset_source_type": dataset.get("source_type"),
            "mapping": dict(dataset.get("mapping") or {}),
            "mapping_fingerprint": mapping_fp,
            "source_fingerprint": source_fp,
            "offline_snapshot": True,
            "retrieval_redacted": True,
            "hidden_reasoning_columns_excluded": True,
            "snapshot_path": str(snapshot),
        },
        status="indexing",
    )
    source_id = str(source["id"])
    _ensure_chunk_hash_index(db)
    # No incomplete generation may stay visible through ordinary retrieval.
    _clear_source_fts(db, source_id)
    if indexed_rows == 0:
        _clear_source_chunks(db, source_id)
        write_manifest(training_root, dataset_id, {"indexed_rows": 0, "chunks_indexed": 0, "source_id": source_id})

    mapping = dict(dataset.get("mapping") or {})
    total_rows = max(0, int(manifest.get("materialized_rows") or 0))
    processed = indexed_rows
    chunks_total = _source_chunk_count(db, source_id)
    pending: list[dict[str, Any]] = []

    for row_index, row in enumerate(_iter_jsonl(snapshot)):
        if row_index < indexed_rows:
            continue
        if _cancel_requested(job_path):
            raise InterruptedError("cancelled")
        rendered = _brain_text(row, mapping)
        if rendered:
            language = str(row.get("lang") or row.get("language") or "").strip()
            pieces = chunk_text(rendered)
            if len(pieces) >= SEQUENCE_STRIDE:
                raise ValueError(f"Datasetrecord {row_index + 1} levert te veel chunks op.")
            for part_index, piece in enumerate(pieces):
                content = str(piece.get("content") or "").strip()
                if not content:
                    continue
                digest = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
                identity = hashlib.sha256(
                    f"{dataset_id}:{row_index}:{part_index}:{digest}".encode("utf-8")
                ).hexdigest()[:24]
                heading = f"{dataset.get('name') or dataset_id} · record {row_index + 1}"
                if language:
                    heading += f" · {language[:40]}"
                pending.append(
                    {
                        "id": f"dschunk_{identity}",
                        "sequence": row_index * SEQUENCE_STRIDE + part_index,
                        "heading": heading,
                        "content": content,
                        "content_hash": digest,
                        "token_estimate": int(piece.get("token_estimate") or max(1, len(content) // 4)),
                    }
                )
        processed = row_index + 1
        if len(pending) >= CHECKPOINT_ROWS or processed % CHECKPOINT_ROWS == 0:
            chunks_total += _append_chunks(db, source_id=source_id, chunks=pending)
            pending.clear()
            _ensure_disk_headroom(db.path)
            fraction = (processed / total_rows) if total_rows else 0.0
            _checkpoint(
                job_path,
                training_root,
                dataset_id,
                status="running",
                phase="indexing",
                materialized_rows=total_rows,
                indexed_rows=processed,
                chunks_indexed=chunks_total,
                progress=0.45 + min(0.49, fraction * 0.49),
                source_id=source_id,
                mapping_fingerprint=mapping_fp,
                snapshot_path=str(snapshot),
                snapshot_bytes=int(manifest.get("snapshot_bytes") or snapshot.stat().st_size),
            )

    if pending:
        chunks_total += _append_chunks(db, source_id=source_id, chunks=pending)
    if total_rows and processed < total_rows:
        raise RuntimeError(f"Snapshot eindigde onverwacht op rij {processed}/{total_rows}.")
    if chunks_total <= 0:
        raise RuntimeError("Dataset bevat na formattering geen doorzoekbare tekstchunks.")

    _checkpoint(
        job_path,
        training_root,
        dataset_id,
        status="running",
        phase="publishing_fts",
        materialized_rows=total_rows,
        indexed_rows=processed,
        chunks_indexed=chunks_total,
        progress=0.96,
        source_id=source_id,
    )
    published = _publish_fts(db, source_id, title)
    if published != chunks_total:
        raise RuntimeError(f"FTS-publicatie mismatch: {published}/{chunks_total} chunks gepubliceerd.")

    final_source = db.upsert_knowledge_source(
        title=title,
        source_type="dataset",
        uri=uri,
        local_path=str(snapshot),
        content_hash=_stable_hash({"source": source_fp, "rows": total_rows}),
        metadata={
            "role": "knowledge",
            "content_is_data_not_policy": True,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name"),
            "dataset_source_type": dataset.get("source_type"),
            "mapping": mapping,
            "mapping_fingerprint": mapping_fp,
            "source_fingerprint": source_fp,
            "offline_snapshot": True,
            "retrieval_redacted": True,
            "hidden_reasoning_columns_excluded": True,
            "snapshot_path": str(snapshot),
            "materialized_rows": total_rows,
            "indexed_rows": processed,
            "chunks_indexed": chunks_total,
        },
        status="ready",
    )
    return write_manifest(
        training_root,
        dataset_id,
        {
            "status": "ready",
            "phase": "completed",
            "progress": 1.0,
            "materialized_rows": total_rows,
            "materialized_complete": True,
            "indexed_rows": processed,
            "chunks_indexed": chunks_total,
            "source_id": final_source.get("id"),
            "mapping_fingerprint": mapping_fp,
            "source_fingerprint": source_fp,
            "snapshot_path": str(snapshot),
            "snapshot_bytes": int(manifest.get("snapshot_bytes") or snapshot.stat().st_size),
            "error": None,
            "active_job_id": None,
            "finished_at": utc_now(),
        },
    )


def _hide_partial_index(db: PlatformDatabase, dataset_id: str) -> None:
    try:
        source = db.get_knowledge_source_by_uri("dataset", f"dataset://{dataset_id}")
        if source and str(source.get("status") or "") != "ready":
            _clear_source_fts(db, str(source["id"]))
    except Exception:
        pass


def run(job_path: Path) -> int:
    job_path = job_path.expanduser().resolve()
    job = _read_job(job_path)
    training_root = Path(str(job["training_root"])).expanduser().resolve()
    workspace = TrainingWorkspace(training_root)
    dataset = workspace.get_dataset(str(job["dataset_id"]))
    dataset_id = str(dataset["id"])
    db = PlatformDatabase(str(job["database_path"]))
    db.initialize()
    token = os.environ.get("HF_TOKEN") or None
    try:
        write_brain_job_state(
            job_path,
            {
                "status": "running",
                "phase": "starting",
                "pid": os.getpid(),
                "started_at": job.get("started_at") or utc_now(),
                "error": None,
            },
        )
        write_manifest(
            training_root,
            dataset_id,
            {"status": "running", "active_job_id": job.get("id"), "error": None},
        )
        print(f"[HADES BRAIN] Dataset: {dataset.get('name') or dataset_id}", flush=True)
        print(f"[HADES BRAIN] Offline root: {brain_dir(training_root, dataset_id)}", flush=True)
        if _cancel_requested(job_path):
            raise InterruptedError("cancelled")
        manifest = read_manifest(training_root, dataset_id) or {}
        manifest = _materialize(
            job_path=job_path,
            training_root=training_root,
            dataset=dataset,
            manifest=manifest,
            token=token,
        )
        if _cancel_requested(job_path):
            raise InterruptedError("cancelled")
        manifest = _index_snapshot(
            job_path=job_path,
            training_root=training_root,
            dataset=dataset,
            manifest=manifest,
            db=db,
        )
        write_brain_job_state(
            job_path,
            {
                "status": "completed",
                "phase": "completed",
                "progress": 1.0,
                "materialized_rows": manifest.get("materialized_rows", 0),
                "indexed_rows": manifest.get("indexed_rows", 0),
                "chunks_indexed": manifest.get("chunks_indexed", 0),
                "source_id": manifest.get("source_id"),
                "finished_at": utc_now(),
                "error": None,
            },
        )
        print(
            f"[HADES BRAIN] Klaar: {manifest.get('indexed_rows', 0)} rijen / "
            f"{manifest.get('chunks_indexed', 0)} chunks.",
            flush=True,
        )
        return 0
    except InterruptedError:
        _hide_partial_index(db, dataset_id)
        current = read_manifest(training_root, dataset_id) or {}
        write_manifest(
            training_root,
            dataset_id,
            {"status": "cancelled", "active_job_id": None, "error": None},
        )
        write_brain_job_state(
            job_path,
            {
                "status": "cancelled",
                "phase": str(current.get("phase") or "cancelled"),
                "progress": float(current.get("progress") or 0.0),
                "finished_at": utc_now(),
                "error": None,
            },
        )
        print("[HADES BRAIN] Geannuleerd; checkpoint blijft beschikbaar voor resume.", flush=True)
        return 0
    except BaseException as exc:
        _hide_partial_index(db, dataset_id)
        error = f"{type(exc).__name__}: {exc}"
        try:
            write_manifest(
                training_root,
                dataset_id,
                {"status": "failed", "active_job_id": None, "error": error[:4000]},
            )
            write_brain_job_state(
                job_path,
                {"status": "failed", "error": error[:4000], "finished_at": utc_now()},
            )
        except Exception:
            pass
        print(f"[HADES BRAIN] MISLUKT: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES offline dataset brain worker")
    parser.add_argument("--job", required=True, help="Pad naar brain job.json")
    args = parser.parse_args()
    return run(Path(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
