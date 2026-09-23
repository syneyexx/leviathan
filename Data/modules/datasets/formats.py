"""Format detection for dataset files (jsonl/json/csv/tsv/txt/md)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .types import DetectedFormat, FormatDetection


def _sniff_delimiter(sample: str) -> str | None:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        return dialect.delimiter
    except csv.Error:
        return None


def _looks_like_json_array(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("[")


def _looks_like_json_object(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{")


def _jsonl_score(lines: list[str]) -> tuple[float, dict[str, Any]]:
    if not lines:
        return 0.0, {"reason": "empty"}
    ok = 0
    objects = 0
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        ok += 1
        if isinstance(parsed, dict):
            objects += 1
    ratio = ok / len(lines)
    details = {"parsedLines": ok, "objectLines": objects, "sampleLines": len(lines)}
    if ratio >= 0.9 and objects >= max(1, int(0.5 * len(lines))):
        return min(0.99, 0.7 + 0.3 * ratio), details
    if ratio >= 0.7:
        return 0.55 + 0.2 * ratio, details
    return ratio * 0.4, details


def detect_format(path: Path, *, sample_bytes: int = 64_000) -> FormatDetection:
    """Detect dataset format from path suffix + content sniffing."""
    path = Path(path)
    suffix = path.suffix.lower().lstrip(".")
    suffix_map = {
        "jsonl": DetectedFormat.JSONL,
        "ndjson": DetectedFormat.JSONL,
        "json": DetectedFormat.JSON,
        "csv": DetectedFormat.CSV,
        "tsv": DetectedFormat.TSV,
        "txt": DetectedFormat.TXT,
        "md": DetectedFormat.MD,
        "markdown": DetectedFormat.MD,
        "parquet": DetectedFormat.PARQUET,
    }
    suffix_hint = suffix_map.get(suffix)

    # Parquet is binary — do not UTF-8 sniff as text.
    if suffix_hint == DetectedFormat.PARQUET or suffix == "parquet":
        details: dict[str, Any] = {"suffixHint": suffix}
        try:
            raw = path.read_bytes()[:4]
            if raw == b"PAR1":
                return FormatDetection(
                    format=DetectedFormat.PARQUET,
                    confidence=0.99,
                    details={**details, "magic": "PAR1"},
                )
        except OSError as exc:
            return FormatDetection(
                format=DetectedFormat.PARQUET,
                confidence=0.5,
                details={**details, "error": str(exc)},
            )
        return FormatDetection(format=DetectedFormat.PARQUET, confidence=0.85, details=details)

    try:
        raw = path.read_bytes()[:sample_bytes]
    except OSError as exc:
        return FormatDetection(
            format=suffix_hint or DetectedFormat.UNKNOWN,
            confidence=0.2 if suffix_hint else 0.0,
            details={"error": str(exc)},
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    stripped = text.strip()
    if not stripped:
        return FormatDetection(
            format=suffix_hint or DetectedFormat.UNKNOWN,
            confidence=0.15 if suffix_hint else 0.0,
            details={"reason": "empty_file"},
        )

    lines = [ln for ln in text.splitlines() if ln.strip()]
    scores: dict[DetectedFormat, tuple[float, dict[str, Any]]] = {}

    # JSONL
    jl_score, jl_details = _jsonl_score(lines[:50])
    scores[DetectedFormat.JSONL] = (jl_score, jl_details)

    # JSON array / object
    if _looks_like_json_array(text) or _looks_like_json_object(text):
        try:
            parsed = json.loads(text if len(raw) < sample_bytes else text)
            if isinstance(parsed, list):
                scores[DetectedFormat.JSON] = (
                    0.95,
                    {"kind": "array", "length": len(parsed)},
                )
            elif isinstance(parsed, dict):
                # Prefer jsonl when many top-level object lines already scored high
                scores[DetectedFormat.JSON] = (0.75, {"kind": "object", "keys": list(parsed)[:20]})
        except json.JSONDecodeError:
            # Partial sample — still a hint
            if _looks_like_json_array(text):
                scores[DetectedFormat.JSON] = (0.45, {"kind": "array_partial"})

    # CSV / TSV
    delim = _sniff_delimiter("\n".join(lines[:20]))
    if delim == "\t" or suffix == "tsv":
        conf = 0.9 if suffix == "tsv" else 0.7
        scores[DetectedFormat.TSV] = (conf, {"delimiter": "\\t"})
    if delim == "," or suffix == "csv":
        conf = 0.9 if suffix == "csv" else 0.65
        scores[DetectedFormat.CSV] = (conf, {"delimiter": ","})

    # Markdown vs plain text
    md_markers = sum(1 for ln in lines[:40] if ln.lstrip().startswith(("#", "-", "*", ">")) or "](" in ln)
    if md_markers >= 2 or suffix in {"md", "markdown"}:
        scores[DetectedFormat.MD] = (
            0.85 if suffix in {"md", "markdown"} else min(0.7, 0.3 + 0.1 * md_markers),
            {"headingOrListLines": md_markers},
        )
    if suffix == "txt" or DetectedFormat.TXT not in scores:
        scores[DetectedFormat.TXT] = (
            0.55 if suffix == "txt" else 0.25,
            {"lineCount": len(lines)},
        )

    # Boost suffix hint
    if suffix_hint and suffix_hint in scores:
        base, details = scores[suffix_hint]
        scores[suffix_hint] = (min(0.99, base + 0.15), {**details, "suffixHint": suffix})

    best_fmt, (best_score, best_details) = max(scores.items(), key=lambda item: item[1][0])
    if best_score < 0.2:
        return FormatDetection(
            format=suffix_hint or DetectedFormat.UNKNOWN,
            confidence=best_score,
            details=best_details,
        )
    return FormatDetection(format=best_fmt, confidence=round(best_score, 4), details=best_details)
