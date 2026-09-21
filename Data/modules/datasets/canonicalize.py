"""Canonicalize heterogeneous rows into CanonicalRecord schema."""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.hashing import sha256_text

from .formats import detect_format
from .types import CANONICAL_SCHEMA_VERSION, CanonicalRecord, DetectedFormat, DatasetError


TEXT_KEYS = ("text", "content", "body", "prompt", "input", "question", "document", "passage")
ID_KEYS = ("id", "uid", "uuid", "example_id", "row_id")
LABEL_KEYS = ("label", "labels", "target", "output", "answer", "category")
MESSAGES_KEYS = ("messages", "conversations", "dialogue")


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


def dict_to_canonical(data: dict[str, Any], *, index: int, source: str) -> CanonicalRecord:
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

    labels: dict[str, Any] | None = None
    if isinstance(labels_raw, dict):
        labels = dict(labels_raw)
    elif labels_raw is not None:
        labels = {"value": labels_raw}

    meta = {k: v for k, v in data.items() if k not in {*ID_KEYS, *TEXT_KEYS, *LABEL_KEYS, *MESSAGES_KEYS, "split", "metadata"}}
    if isinstance(data.get("metadata"), dict):
        meta = {**meta, **data["metadata"]}

    row_id = str(raw_id) if raw_id is not None else _stable_id(f"{source}:{index}:{text[:200]}")
    split = str(data["split"]) if data.get("split") is not None else None
    return CanonicalRecord(
        id=row_id,
        text=text,
        messages=msgs,
        labels=labels,
        metadata=meta,
        split=split,
    )


def iter_canonical_from_path(
    path: Path,
    *,
    fmt: DetectedFormat | None = None,
) -> Iterator[CanonicalRecord]:
    path = Path(path)
    detection = detect_format(path) if fmt is None else None
    resolved = fmt or (detection.format if detection else DetectedFormat.UNKNOWN)
    source = path.name

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
                        f"Invalid JSONL at line {idx + 1}: {exc}",
                        code="invalid_jsonl",
                    ) from exc
                if isinstance(obj, dict):
                    yield dict_to_canonical(obj, index=idx, source=source)
                else:
                    yield CanonicalRecord(id=_stable_id(f"{source}:{idx}"), text=str(obj))
        return

    if resolved == DetectedFormat.JSON:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    yield dict_to_canonical(item, index=idx, source=source)
                else:
                    yield CanonicalRecord(id=_stable_id(f"{source}:{idx}"), text=str(item))
        elif isinstance(data, dict):
            # Common HF-ish shapes: {"data": [...]} or single object
            for key in ("data", "rows", "examples", "items"):
                if isinstance(data.get(key), list):
                    for idx, item in enumerate(data[key]):
                        if isinstance(item, dict):
                            yield dict_to_canonical(item, index=idx, source=source)
                        else:
                            yield CanonicalRecord(id=_stable_id(f"{source}:{idx}"), text=str(item))
                    return
            yield dict_to_canonical(data, index=0, source=source)
        else:
            raise DatasetError("JSON root must be object or array", code="invalid_json")
        return

    if resolved in {DetectedFormat.CSV, DetectedFormat.TSV}:
        delimiter = "\t" if resolved == DetectedFormat.TSV else ","
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for idx, row in enumerate(reader):
                cleaned = {k: (v if v is not None else "") for k, v in row.items() if k is not None}
                yield dict_to_canonical(cleaned, index=idx, source=source)
        return

    if resolved in {DetectedFormat.TXT, DetectedFormat.MD, DetectedFormat.UNKNOWN}:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Paragraph split for plain text / markdown corpora
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text] if text.strip() else []
        for idx, para in enumerate(paragraphs):
            yield CanonicalRecord(
                id=_stable_id(f"{source}:{idx}:{para[:120]}"),
                text=para,
                metadata={"sourceFormat": resolved.value},
            )
        return

    raise DatasetError(f"Unsupported format: {resolved}", code="unsupported_format")


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
