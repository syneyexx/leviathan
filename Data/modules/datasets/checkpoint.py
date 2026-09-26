"""Bounded streaming job checkpoints for large native/Python data-plane jobs (W171).

Metadata only — never huge payloads. Stored as a small JSON file under job scratch
(or manifests), with an optional compact mirror on the job row for UI/API.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, TypeVar

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file

T = TypeVar("T")

CHECKPOINT_PROTOCOL_VERSION = 1
CHECKPOINT_FILENAME = "streaming-checkpoint.json"
DEFAULT_CHECKPOINT_EVERY = 256
UNMEASURED = "UNMEASURED"

BACKEND_PYTHON_STREAMING = "python_streaming"
BACKEND_RUST_NATIVE = "rust_native"


def normalize_backend_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    upper = text.upper().replace("-", "_")
    if upper in {"PYTHON_STREAMING", "PYTHON", "PYTHONSTREAMING"}:
        return BACKEND_PYTHON_STREAMING
    if upper in {"RUST_NATIVE", "RUST", "NATIVE", "RUSTNATIVE"}:
        return BACKEND_RUST_NATIVE
    lower = text.lower().replace("-", "_")
    if lower in {BACKEND_PYTHON_STREAMING, BACKEND_RUST_NATIVE}:
        return lower
    return lower


def compute_input_hash(path: Path | str | None, *, fallback: str | None = None) -> str:
    if fallback:
        return str(fallback)
    if path is None:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    return sha256_file(p)


def _canonical_options(options: dict[str, Any] | None) -> Any:
    if not options:
        return {}
    try:
        return json.loads(json.dumps(options, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return {"_repr": repr(options)[:500]}


def compute_operation_fingerprint(
    *,
    input_hash: str,
    operation: str,
    options: dict[str, Any] | None = None,
) -> str:
    payload = {
        "inputHash": str(input_hash or ""),
        "operation": str(operation or ""),
        "options": _canonical_options(options),
        "protocolVersion": CHECKPOINT_PROTOCOL_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or value == UNMEASURED:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metric_or_unmeasured(value: Any) -> int | float | str:
    """Never coerce missing measurements to 0 — that lies."""
    if value is None or value == "" or value == UNMEASURED:
        return UNMEASURED
    if isinstance(value, str) and value.upper() == UNMEASURED:
        return UNMEASURED
    try:
        if isinstance(value, bool):
            return UNMEASURED
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        if "." in text:
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return UNMEASURED


@dataclass
class StreamingJobCheckpoint:
    input_hash: str
    operation: str
    phase: str
    records_processed: int = 0
    byte_offset: int | None = None
    protocol_version: int = CHECKPOINT_PROTOCOL_VERSION
    fingerprint: str = ""
    options_hash: str = ""
    backend: str | None = None
    updated_at: float = field(default_factory=time.time)
    peak_memory: int | str | None = UNMEASURED
    memory_budget: int | str | None = UNMEASURED
    spill_bytes: int | str | None = UNMEASURED
    throughput: float | str | None = UNMEASURED
    duration_ms: float | str | None = UNMEASURED
    resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "protocolVersion": int(self.protocol_version),
            "inputHash": self.input_hash,
            "operation": self.operation,
            "phase": self.phase,
            "recordsProcessed": int(self.records_processed),
            "byteOffset": self.byte_offset,
            "fingerprint": self.fingerprint,
            "optionsHash": self.options_hash,
            "backend": self.backend,
            "updatedAt": self.updated_at,
            "peakMemory": self.peak_memory if self.peak_memory is not None else UNMEASURED,
            "memoryBudget": self.memory_budget if self.memory_budget is not None else UNMEASURED,
            "spillBytes": self.spill_bytes if self.spill_bytes is not None else UNMEASURED,
            "throughput": self.throughput if self.throughput is not None else UNMEASURED,
            "durationMs": self.duration_ms if self.duration_ms is not None else UNMEASURED,
            "resumed": bool(self.resumed),
            "truth": {
                "boundedMetadataOnly": True,
                "notHugeDbBlob": True,
                "byteOffsetOnlyWhenSafe": True,
                "unmeasuredIsNotZero": True,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StreamingJobCheckpoint":
        raw = dict(data or {})
        return cls(
            input_hash=str(raw.get("inputHash") or raw.get("input_hash") or ""),
            operation=str(raw.get("operation") or ""),
            phase=str(raw.get("phase") or "unknown"),
            records_processed=int(raw.get("recordsProcessed") or raw.get("records_processed") or 0),
            byte_offset=_optional_int(raw.get("byteOffset", raw.get("byte_offset"))),
            protocol_version=int(
                raw.get("protocolVersion") or raw.get("protocol_version") or CHECKPOINT_PROTOCOL_VERSION
            ),
            fingerprint=str(raw.get("fingerprint") or ""),
            options_hash=str(raw.get("optionsHash") or raw.get("options_hash") or ""),
            backend=normalize_backend_label(raw.get("backend")),
            updated_at=float(raw.get("updatedAt") or raw.get("updated_at") or time.time()),
            peak_memory=_metric_or_unmeasured(raw.get("peakMemory", raw.get("peak_memory"))),
            memory_budget=_metric_or_unmeasured(raw.get("memoryBudget", raw.get("memory_budget"))),
            spill_bytes=_metric_or_unmeasured(raw.get("spillBytes", raw.get("spill_bytes"))),
            throughput=_metric_or_unmeasured(raw.get("throughput")),
            duration_ms=_metric_or_unmeasured(raw.get("durationMs", raw.get("duration_ms"))),
            resumed=bool(raw.get("resumed")),
        )


def checkpoint_file_path(scratch_or_manifests: Path) -> Path:
    return Path(scratch_or_manifests) / CHECKPOINT_FILENAME


def save_checkpoint(root: Path, checkpoint: StreamingJobCheckpoint) -> Path:
    ensure_dir(root)
    path = checkpoint_file_path(root)
    checkpoint.updated_at = time.time()
    atomic_write_text(path, json.dumps(checkpoint.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def load_checkpoint(root: Path) -> StreamingJobCheckpoint | None:
    path = checkpoint_file_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return StreamingJobCheckpoint.from_dict(data)


def invalidate_checkpoint(root: Path) -> bool:
    path = checkpoint_file_path(root)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def can_resume(
    existing: StreamingJobCheckpoint | None,
    *,
    fingerprint: str,
    input_hash: str,
) -> bool:
    if existing is None:
        return False
    if int(existing.protocol_version) != CHECKPOINT_PROTOCOL_VERSION:
        return False
    if not fingerprint or existing.fingerprint != fingerprint:
        return False
    if input_hash and existing.input_hash and existing.input_hash != input_hash:
        return False
    return existing.records_processed >= 0


def resolve_resume_skip(
    existing: StreamingJobCheckpoint | None,
    *,
    fingerprint: str,
    input_hash: str,
) -> tuple[int, bool]:
    if can_resume(existing, fingerprint=fingerprint, input_hash=input_hash):
        assert existing is not None
        return int(existing.records_processed), True
    return 0, False


def observability_fields(
    *,
    backend: str | None,
    phase: str | None = None,
    records_processed: int | None = None,
    peak_memory: int | str | None = None,
    memory_budget: int | str | None = None,
    spill_bytes: int | str | None = None,
    throughput: float | str | None = None,
    duration_ms: float | str | None = None,
    resumed: bool = False,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "backend": normalize_backend_label(backend),
        "phase": phase,
        "recordsProcessed": records_processed,
        "peakMemory": _metric_or_unmeasured(peak_memory),
        "memoryBudget": _metric_or_unmeasured(memory_budget),
        "spillBytes": _metric_or_unmeasured(spill_bytes),
        "throughput": _metric_or_unmeasured(throughput),
        "durationMs": _metric_or_unmeasured(duration_ms),
        "resumed": bool(resumed),
        "fallbackReason": fallback_reason,
    }


def throughput_records_per_sec(records: int, duration_ms: float | None) -> float | str:
    if duration_ms is None or duration_ms <= 0 or records < 0:
        return UNMEASURED
    return round(float(records) / (float(duration_ms) / 1000.0), 3)


def iter_skip_then_count(
    records: Iterable[T],
    *,
    skip: int = 0,
    on_progress: Callable[[int], None] | None = None,
    every: int = DEFAULT_CHECKPOINT_EVERY,
) -> Iterator[T]:
    n = 0
    every_n = max(1, int(every))
    for rec in records:
        n += 1
        if n <= skip:
            if on_progress is not None and n % every_n == 0:
                on_progress(n)
            continue
        yield rec
        if on_progress is not None and n % every_n == 0:
            on_progress(n)
    if on_progress is not None:
        on_progress(n)


def build_checkpoint(
    *,
    input_hash: str,
    operation: str,
    options: dict[str, Any] | None = None,
    phase: str = "running",
    records_processed: int = 0,
    byte_offset: int | None = None,
    backend: str | None = None,
    memory_budget: int | str | None = UNMEASURED,
    peak_memory: int | str | None = UNMEASURED,
    spill_bytes: int | str | None = UNMEASURED,
    throughput: float | str | None = UNMEASURED,
    duration_ms: float | str | None = UNMEASURED,
    resumed: bool = False,
) -> StreamingJobCheckpoint:
    options_blob = json.dumps(_canonical_options(options), sort_keys=True, separators=(",", ":"))
    options_hash = hashlib.sha256(options_blob.encode("utf-8")).hexdigest()
    fingerprint = compute_operation_fingerprint(
        input_hash=input_hash,
        operation=operation,
        options=options,
    )
    return StreamingJobCheckpoint(
        input_hash=input_hash,
        operation=operation,
        phase=phase,
        records_processed=int(records_processed),
        byte_offset=byte_offset,
        protocol_version=CHECKPOINT_PROTOCOL_VERSION,
        fingerprint=fingerprint,
        options_hash=options_hash,
        backend=normalize_backend_label(backend),
        peak_memory=_metric_or_unmeasured(peak_memory),
        memory_budget=_metric_or_unmeasured(memory_budget),
        spill_bytes=_metric_or_unmeasured(spill_bytes),
        throughput=_metric_or_unmeasured(throughput),
        duration_ms=_metric_or_unmeasured(duration_ms),
        resumed=resumed,
    )
