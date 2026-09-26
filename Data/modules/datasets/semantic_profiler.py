"""Bounded evidence collection for dataset semantic profiling.

Uses streaming iterators only — never loads a full materialized corpus.
Sample payloads are DATA evidence (prompt-injection safe: never execute).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .materialize import iter_version_records
from .types import CanonicalRecord, DatasetError, DatasetRecord, DatasetVersion


DEFAULT_MAX_SAMPLE_ROWS = 32
DEFAULT_MAX_SAMPLE_BYTES = 64 * 1024
DEFAULT_MAX_FILES_INSPECTED = 8
DEFAULT_MAX_PROFILE_BYTES = 256 * 1024
DEFAULT_MAX_WALL_TIME = 5.0


@dataclass
class ProfilerLimits:
    max_sample_rows: int = DEFAULT_MAX_SAMPLE_ROWS
    max_sample_bytes: int = DEFAULT_MAX_SAMPLE_BYTES
    max_files_inspected: int = DEFAULT_MAX_FILES_INSPECTED
    max_profile_bytes: int = DEFAULT_MAX_PROFILE_BYTES
    max_wall_time: float = DEFAULT_MAX_WALL_TIME


@dataclass
class BoundedDatasetEvidence:
    """Typed, size-bounded profile evidence for deterministic / model enrichment."""

    dataset_id: str
    version_id: str | None = None
    filename: str | None = None
    source_type: str | None = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    format_name: str | None = None
    schema: dict[str, Any] = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    row_count: int | None = None
    byte_size: int | None = None
    content_hash: str | None = None
    trading_classification: dict[str, Any] | None = None
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    sample_texts: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    truncated: bool = False
    limits: dict[str, Any] = field(default_factory=dict)
    truth: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "versionId": self.version_id,
            "filename": self.filename,
            "sourceType": self.source_type,
            "description": self.description,
            "metadata": dict(self.metadata),
            "format": self.format_name,
            "schema": dict(self.schema),
            "columns": list(self.columns),
            "rowCount": self.row_count,
            "byteSize": self.byte_size,
            "contentHash": self.content_hash,
            "tradingClassification": dict(self.trading_classification)
            if isinstance(self.trading_classification, dict)
            else None,
            "sampleRows": list(self.sample_rows),
            "sampleTexts": list(self.sample_texts),
            "filesInspected": list(self.files_inspected),
            "truncated": bool(self.truncated),
            "limits": dict(self.limits),
            "truth": {
                "samplesAreDataOnly": True,
                "neverExecuteSampleContent": True,
                "streamingOnly": True,
                "notFullCorpusLoad": True,
                **dict(self.truth),
            },
        }


class BoundedDatasetProfiler:
    """Collect bounded evidence for semantic naming / categorization."""

    def __init__(self, limits: ProfilerLimits | None = None) -> None:
        self.limits = limits or ProfilerLimits()

    def profile(
        self,
        *,
        dataset: DatasetRecord | Mapping[str, Any],
        version: DatasetVersion | Mapping[str, Any] | None = None,
        record_iter: Iterator[CanonicalRecord] | None = None,
        storage_path: Path | str | None = None,
        trading_classification: Mapping[str, Any] | None = None,
        files: list[Mapping[str, Any]] | None = None,
        max_record_bytes: int | None = None,
    ) -> BoundedDatasetEvidence:
        started = time.monotonic()
        limits = self.limits
        ds = _as_mapping(dataset)
        ver = _as_mapping(version) if version is not None else {}

        dataset_id = str(ds.get("dataset_id") or ds.get("datasetId") or "").strip()
        if not dataset_id:
            raise DatasetError("dataset_id required for profiling", code="profile_missing_id")

        version_id = _opt_str(ver.get("version_id") or ver.get("versionId"))
        filename = _opt_str(
            ds.get("original_filename")
            or ds.get("originalFilename")
            or ds.get("name")
        )
        source_type = _opt_str(ds.get("source_type") or ds.get("sourceType"))
        if hasattr(ds.get("source_type"), "value"):
            source_type = str(ds["source_type"].value)
        description = str(ds.get("description") or "")
        metadata = dict(ds.get("metadata") or {}) if isinstance(ds.get("metadata"), dict) else {}
        format_name = _format_name(ds, ver)
        schema = dict(ver.get("schema") or {}) if isinstance(ver.get("schema"), dict) else {}
        columns = _extract_columns(schema, metadata)
        row_count = _opt_int(ver.get("row_count") if ver.get("row_count") is not None else ds.get("row_count") or ds.get("rowCount"))
        byte_size = _opt_int(ver.get("byte_size") if ver.get("byte_size") is not None else ds.get("byte_size") or ds.get("byteSize"))
        content_hash = _opt_str(
            ver.get("content_hash")
            or ver.get("contentHash")
            or ds.get("content_hash")
            or ds.get("contentHash")
        )

        trade_blob: dict[str, Any] | None = None
        if isinstance(trading_classification, Mapping):
            trade_blob = dict(trading_classification)
        else:
            for blob in (
                (ver.get("metadata") or {}).get("classification")
                if isinstance(ver.get("metadata"), dict)
                else None,
                metadata.get("classification"),
            ):
                if isinstance(blob, dict):
                    trade_blob = dict(blob)
                    break

        files_inspected: list[str] = []
        sample_rows: list[dict[str, Any]] = []
        sample_texts: list[str] = []
        truncated = False
        sample_bytes = 0
        profile_bytes = 0

        # Inspect a bounded number of companion file paths (names only + tiny peek).
        for item in (files or [])[: limits.max_files_inspected]:
            path_str = _opt_str(item.get("path") if isinstance(item, Mapping) else None)
            if not path_str:
                continue
            files_inspected.append(path_str)
            profile_bytes += len(path_str.encode("utf-8"))
            if profile_bytes >= limits.max_profile_bytes:
                truncated = True
                break

        storage = storage_path or ver.get("storage_path") or ver.get("storagePath")
        iterator: Iterator[CanonicalRecord] | None = record_iter
        if iterator is None and storage:
            try:
                iterator = iter_version_records(
                    Path(str(storage)),
                    max_record_bytes=max_record_bytes,
                    format_hint=_opt_str(schema.get("storageFormat") or schema.get("format")),
                )
            except DatasetError:
                iterator = None
                truncated = True

        if iterator is not None:
            for rec in iterator:
                if time.monotonic() - started > limits.max_wall_time:
                    truncated = True
                    break
                if len(sample_rows) >= limits.max_sample_rows:
                    truncated = True
                    break
                if sample_bytes >= limits.max_sample_bytes or profile_bytes >= limits.max_profile_bytes:
                    truncated = True
                    break
                row = _record_to_sample(rec)
                encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
                row_bytes = len(encoded.encode("utf-8"))
                if sample_bytes + row_bytes > limits.max_sample_bytes and sample_rows:
                    truncated = True
                    break
                sample_rows.append(row)
                sample_bytes += row_bytes
                profile_bytes += row_bytes
                text = str(row.get("text") or "").strip()
                if text:
                    # Cap individual text snippets.
                    sample_texts.append(text[:2000])
                # Discover columns from first rows when schema empty.
                if not columns:
                    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                    for key in meta.keys():
                        if str(key) not in columns and str(key) not in {"source", "provenance"}:
                            columns.append(str(key))
                    labels = row.get("labels")
                    if isinstance(labels, dict):
                        for key in labels.keys():
                            if str(key) not in columns:
                                columns.append(str(key))

        evidence = BoundedDatasetEvidence(
            dataset_id=dataset_id,
            version_id=version_id,
            filename=filename,
            source_type=source_type,
            description=description,
            metadata=_safe_metadata(metadata),
            format_name=format_name,
            schema=schema,
            columns=list(columns),
            row_count=row_count,
            byte_size=byte_size,
            content_hash=content_hash,
            trading_classification=trade_blob,
            sample_rows=sample_and_mark_data(sample_rows),
            sample_texts=list(sample_texts),
            files_inspected=files_inspected,
            truncated=truncated,
            limits={
                "maxSampleRows": limits.max_sample_rows,
                "maxSampleBytes": limits.max_sample_bytes,
                "maxFilesInspected": limits.max_files_inspected,
                "maxProfileBytes": limits.max_profile_bytes,
                "maxWallTime": limits.max_wall_time,
            },
            truth={
                "elapsedSeconds": round(time.monotonic() - started, 4),
                "sampleByteSize": sample_bytes,
            },
        )
        return evidence

    def profile_from_service(
        self,
        *,
        get_dataset: Callable[[str], DatasetRecord],
        get_version: Callable[[str], DatasetVersion],
        iter_records: Callable[[str], Iterator[CanonicalRecord]],
        dataset_id: str,
        version_id: str,
        trading_classification: Mapping[str, Any] | None = None,
        list_files: Callable[[str], list[Any]] | None = None,
    ) -> BoundedDatasetEvidence:
        ds = get_dataset(dataset_id)
        ver = get_version(version_id)
        files_payload: list[Mapping[str, Any]] = []
        if list_files is not None:
            for f in list_files(dataset_id)[: self.limits.max_files_inspected]:
                if hasattr(f, "public_dict"):
                    files_payload.append(f.public_dict())
                elif isinstance(f, Mapping):
                    files_payload.append(f)
        return self.profile(
            dataset=ds,
            version=ver,
            record_iter=iter_records(version_id),
            trading_classification=trading_classification,
            files=files_payload,
        )


def sample_and_mark_data(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark samples as inert DATA — consumers must never execute content."""
    out: list[dict[str, Any]] = []
    for row in rows:
        marked = dict(row)
        marked["_dataOnly"] = True
        marked["_doNotExecute"] = True
        out.append(marked)
    return out


def _record_to_sample(rec: CanonicalRecord) -> dict[str, Any]:
    payload = {
        "id": rec.id,
        "text": (rec.text or "")[:4000],
        "metadata": _safe_metadata(rec.metadata or {}),
    }
    if rec.labels is not None:
        payload["labels"] = _safe_metadata(rec.labels) if isinstance(rec.labels, dict) else rec.labels
    if rec.messages is not None:
        # Keep messages as opaque data blobs (truncated).
        payload["messages"] = rec.messages[:4] if isinstance(rec.messages, list) else rec.messages
    if rec.split is not None:
        payload["split"] = rec.split
    return payload


def _safe_metadata(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secrets / embeddings / oversized blobs from evidence metadata."""
    banned_keys = {
        "token",
        "tokens",
        "api_key",
        "apiKey",
        "secret",
        "password",
        "embedding",
        "embeddings",
        "vector",
        "vectors",
        "chain_of_thought",
        "chainOfThought",
    }
    out: dict[str, Any] = {}
    for key, value in meta.items():
        lk = str(key).lower()
        if str(key) in banned_keys or lk in banned_keys or "embedding" in lk or "secret" in lk:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 4000:
                out[str(key)] = value[:4000]
            else:
                out[str(key)] = value
        elif isinstance(value, (list, dict)):
            try:
                encoded = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                continue
            if len(encoded) > 8000:
                out[str(key)] = {"_truncated": True, "preview": encoded[:2000]}
            else:
                out[str(key)] = value
    return out


def _extract_columns(schema: Mapping[str, Any], metadata: Mapping[str, Any]) -> list[str]:
    cols: list[str] = []
    for source in (schema.get("columns"), metadata.get("columns"), metadata.get("schemaColumns")):
        if isinstance(source, list):
            for c in source:
                name = str(c).strip()
                if name and name not in cols:
                    cols.append(name)
    fields = schema.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                name = str(f.get("name") or "").strip()
                if name and name not in cols:
                    cols.append(name)
            else:
                name = str(f).strip()
                if name and name not in cols:
                    cols.append(name)
    return cols


def _format_name(ds: Mapping[str, Any], ver: Mapping[str, Any]) -> str | None:
    fmt = ds.get("detected_format") or ds.get("detectedFormat")
    if hasattr(fmt, "value"):
        return str(fmt.value)
    if fmt:
        return str(fmt)
    schema = ver.get("schema") if isinstance(ver.get("schema"), dict) else {}
    return _opt_str(schema.get("storageFormat") or schema.get("format") or ver.get("kind"))


def _as_mapping(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    out: dict[str, Any] = {}
    for key in (
        "dataset_id",
        "version_id",
        "name",
        "description",
        "original_filename",
        "source_type",
        "metadata",
        "provenance",
        "detected_format",
        "row_count",
        "byte_size",
        "content_hash",
        "schema",
        "storage_path",
        "status",
        "kind",
    ):
        if hasattr(obj, key):
            out[key] = getattr(obj, key)
    return out


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
