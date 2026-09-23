"""Canonicalize heterogeneous rows into CanonicalRecord schema."""

from __future__ import annotations

import csv
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.hashing import sha256_text

from .formats import detect_format
from .types import CANONICAL_SCHEMA_VERSION, CanonicalRecord, DetectedFormat, DatasetError


TEXT_KEYS = (
    "text",
    "content",
    "body",
    "prompt",
    "input",
    "question",
    "document",
    "passage",
    "review",
    "comment",
    "sentence",
    "utterance",
    "response",
    "completion",
    "instruction",
    "article",
)
ID_KEYS = ("id", "uid", "uuid", "example_id", "row_id")
LABEL_KEYS = ("label", "labels", "target", "output", "answer", "category")
MESSAGES_KEYS = ("messages", "conversations", "dialogue")

# Large JSON arrays above this size use streaming ijson.
_LARGE_JSON_BYTES = 8 * 1024 * 1024


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
        lower = key.lower()
        for k, v in data.items():
            if str(k).lower() == lower and v is not None:
                return v
    return None


def _stable_id(seed: str) -> str:
    return sha256_text(seed)[:16]


def _parquet_batch_rows() -> int:
    raw = (os.getenv("LEVIATHAN_HF_PARQUET_BATCH_ROWS") or "").strip()
    try:
        value = int(raw) if raw else 16_384
    except ValueError:
        value = 16_384
    return max(512, min(65_536, value))


def dict_to_canonical(
    data: dict[str, Any],
    *,
    index: int,
    source: str,
    split: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> CanonicalRecord:
    raw_id = _pick(data, ID_KEYS)
    text_val = _pick(data, TEXT_KEYS)
    messages = _pick(data, MESSAGES_KEYS)
    labels_raw = _pick(data, LABEL_KEYS)

    if isinstance(messages, list):
        msgs = [m for m in messages if isinstance(m, dict)]
    else:
        msgs = None

    text = ""
    if isinstance(text_val, str):
        text = text_val
    elif text_val is not None and msgs is None:
        text = str(text_val)

    if not text and msgs:
        # Derive text from last assistant/user message for indexing/token stats.
        parts = []
        for msg in msgs:
            role = str(msg.get("role") or "")
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(f"{role}: {content}" if role else content)
        text = "\n".join(parts)

    # CSV/Parquet rows without a known text column: synthesize from string fields.
    if not text and msgs is None:
        synthesized: list[str] = []
        for k, v in data.items():
            if str(k).lower() in {*(x.lower() for x in ID_KEYS), "split", "metadata"}:
                continue
            if isinstance(v, str) and v.strip():
                synthesized.append(v.strip())
        if synthesized:
            text = "\n".join(synthesized)

    labels: dict[str, Any] | None = None
    if isinstance(labels_raw, dict):
        labels = dict(labels_raw)
    elif labels_raw is not None:
        labels = {"value": labels_raw}

    meta = {
        k: v
        for k, v in data.items()
        if k not in {*ID_KEYS, *TEXT_KEYS, *LABEL_KEYS, *MESSAGES_KEYS, "split", "metadata"}
    }
    if isinstance(data.get("metadata"), dict):
        meta = {**meta, **data["metadata"]}
    if provenance:
        # Compact provenance — avoid duplicating huge blobs per row.
        meta = {**meta, "source": {**meta.get("source", {}), **provenance} if isinstance(meta.get("source"), dict) else provenance}

    row_id = str(raw_id) if raw_id is not None else _stable_id(f"{source}:{index}:{text[:200]}")
    row_split = str(data["split"]) if data.get("split") is not None else split
    return CanonicalRecord(
        id=row_id,
        text=text,
        messages=msgs,
        labels=labels,
        metadata=meta,
        split=row_split,
    )


def _arrow_value_to_python(value: Any) -> Any:
    if value is None:
        return None
    # pyarrow scalars / nested
    if hasattr(value, "as_py"):
        try:
            return value.as_py()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def iter_parquet_canonical(
    path: Path,
    *,
    source: str,
    split: str | None = None,
    provenance: dict[str, Any] | None = None,
    batch_rows: int | None = None,
) -> Iterator[CanonicalRecord]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise DatasetError(
            "pyarrow is required for Parquet dataset import",
            code="missing_dependency",
            http_status=500,
        ) from exc

    batch_rows = batch_rows or _parquet_batch_rows()
    pf = pq.ParquetFile(path)
    index = 0
    for batch in pf.iter_batches(batch_size=batch_rows):
        columns = batch.column_names
        # Convert column-wise to row dicts without materializing the whole file.
        col_arrays = {name: batch.column(i) for i, name in enumerate(columns)}
        n = batch.num_rows
        for row_i in range(n):
            data = {name: _arrow_value_to_python(col_arrays[name][row_i]) for name in columns}
            # Drop pure-null keys noise? keep all for provenance of schema
            clean = {k: v for k, v in data.items() if v is not None or k.lower() in ID_KEYS}
            if not any(isinstance(v, (str, list, dict)) or v is not None for v in clean.values()):
                index += 1
                continue
            yield dict_to_canonical(
                clean if clean else data,
                index=index,
                source=source,
                split=split,
                provenance=provenance,
            )
            index += 1


def iter_json_array_streaming(
    path: Path,
    *,
    source: str,
    split: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> Iterator[CanonicalRecord]:
    try:
        import ijson
    except ImportError as exc:
        raise DatasetError(
            "ijson is required for streaming large JSON arrays",
            code="missing_dependency",
            http_status=500,
        ) from exc

    with path.open("rb") as handle:
        # Try top-level array items first
        try:
            parser = ijson.items(handle, "item")
            idx = 0
            yielded = False
            for item in parser:
                yielded = True
                if isinstance(item, dict):
                    yield dict_to_canonical(item, index=idx, source=source, split=split, provenance=provenance)
                else:
                    yield CanonicalRecord(
                        id=_stable_id(f"{source}:{idx}"),
                        text=str(item),
                        split=split,
                        metadata={"source": provenance} if provenance else {},
                    )
                idx += 1
            if yielded:
                return
        except Exception:  # noqa: BLE001
            pass

    # Common wrappers: data / rows / examples / items
    for prefix in ("data.item", "rows.item", "examples.item", "items.item"):
        with path.open("rb") as handle:
            try:
                idx = 0
                found = False
                for item in ijson.items(handle, prefix):
                    found = True
                    if isinstance(item, dict):
                        yield dict_to_canonical(item, index=idx, source=source, split=split, provenance=provenance)
                    else:
                        yield CanonicalRecord(
                            id=_stable_id(f"{source}:{idx}"),
                            text=str(item),
                            split=split,
                            metadata={"source": provenance} if provenance else {},
                        )
                    idx += 1
                if found:
                    return
            except Exception:  # noqa: BLE001
                continue

    # Small-object fallback
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, dict):
        yield dict_to_canonical(data, index=0, source=source, split=split, provenance=provenance)
        return
    raise DatasetError("JSON root must be object or array", code="invalid_json")


def iter_canonical_from_path(
    path: Path,
    *,
    fmt: DetectedFormat | None = None,
    split: str | None = None,
    provenance: dict[str, Any] | None = None,
    source_name: str | None = None,
) -> Iterator[CanonicalRecord]:
    path = Path(path)
    detection = detect_format(path) if fmt is None else None
    resolved = fmt or (detection.format if detection else DetectedFormat.UNKNOWN)
    source = source_name or path.name

    if resolved == DetectedFormat.PARQUET:
        yield from iter_parquet_canonical(
            path, source=source, split=split, provenance=provenance
        )
        return

    if resolved == DetectedFormat.JSONL:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DatasetError(
                        f"Invalid JSONL at {source} line {idx + 1}: {exc}",
                        code="invalid_jsonl",
                    ) from exc
                if isinstance(obj, dict):
                    yield dict_to_canonical(
                        obj, index=idx, source=source, split=split, provenance=provenance
                    )
                else:
                    yield CanonicalRecord(
                        id=_stable_id(f"{source}:{idx}"),
                        text=str(obj),
                        split=split,
                        metadata={"source": provenance} if provenance else {},
                    )
        return

    if resolved == DetectedFormat.JSON:
        size = path.stat().st_size if path.exists() else 0
        if size >= _LARGE_JSON_BYTES:
            yield from iter_json_array_streaming(
                path, source=source, split=split, provenance=provenance
            )
            return
        # Small JSON — still avoid loading via path.read_text for multi-GB;
        # size gate above handles large files.
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    yield dict_to_canonical(
                        item, index=idx, source=source, split=split, provenance=provenance
                    )
                else:
                    yield CanonicalRecord(
                        id=_stable_id(f"{source}:{idx}"),
                        text=str(item),
                        split=split,
                        metadata={"source": provenance} if provenance else {},
                    )
        elif isinstance(data, dict):
            for key in ("data", "rows", "examples", "items"):
                if isinstance(data.get(key), list):
                    for idx, item in enumerate(data[key]):
                        if isinstance(item, dict):
                            yield dict_to_canonical(
                                item, index=idx, source=source, split=split, provenance=provenance
                            )
                        else:
                            yield CanonicalRecord(
                                id=_stable_id(f"{source}:{idx}"),
                                text=str(item),
                                split=split,
                                metadata={"source": provenance} if provenance else {},
                            )
                    return
            yield dict_to_canonical(data, index=0, source=source, split=split, provenance=provenance)
        else:
            raise DatasetError("JSON root must be object or array", code="invalid_json")
        return

    if resolved in {DetectedFormat.CSV, DetectedFormat.TSV}:
        delimiter = "\t" if resolved == DetectedFormat.TSV else ","
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for idx, row in enumerate(reader):
                cleaned = {k: (v if v is not None else "") for k, v in row.items() if k is not None}
                yield dict_to_canonical(
                    cleaned, index=idx, source=source, split=split, provenance=provenance
                )
        return

    if resolved in {DetectedFormat.TXT, DetectedFormat.MD, DetectedFormat.UNKNOWN}:
        text = path.read_text(encoding="utf-8", errors="replace")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text] if text.strip() else []
        for idx, para in enumerate(paragraphs):
            yield CanonicalRecord(
                id=_stable_id(f"{source}:{idx}:{para[:120]}"),
                text=para,
                split=split,
                metadata={
                    "sourceFormat": resolved.value,
                    **({"source": provenance} if provenance else {}),
                },
            )
        return

    raise DatasetError(f"Unsupported format: {resolved}", code="unsupported_format")


def iter_canonical_from_sources(
    sources: list[dict[str, Any]],
) -> Iterator[CanonicalRecord]:
    """Yield canonical records from multiple source files in deterministic order.

    Each source dict: path, optional format/split/provenance/sourceName.
    """
    ordered = sorted(sources, key=lambda s: str(s.get("path") or ""))
    for src in ordered:
        path = Path(str(src["path"]))
        fmt_name = src.get("format")
        fmt = DetectedFormat(fmt_name) if fmt_name else None
        split = str(src["split"]) if src.get("split") is not None else None
        provenance = src.get("provenance") if isinstance(src.get("provenance"), dict) else None
        source_name = str(src.get("sourceName") or src.get("relativePath") or path.name)
        yield from iter_canonical_from_path(
            path,
            fmt=fmt,
            split=split,
            provenance=provenance,
            source_name=source_name,
        )


def load_canonical_records(path: Path, *, fmt: DetectedFormat | None = None) -> list[CanonicalRecord]:
    return list(iter_canonical_from_path(path, fmt=fmt))


def canonical_schema_dict() -> dict[str, Any]:
    return {
        "version": CANONICAL_SCHEMA_VERSION,
        "type": "canonical",
        "fields": {
            "id": "string",
            "text": "string",
            "messages": "array<object>|null",
            "labels": "object|null",
            "metadata": "object",
            "split": "string|null",
        },
    }


def new_record_id() -> str:
    return str(uuid.uuid4())
