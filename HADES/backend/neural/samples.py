"""Dataset Brain → neural-memory sample compiler (Phase 2).

Streams safe records from offline Dataset Brain snapshots. Does not load whole
datasets into RAM. Reuses:

- ``format_training_example`` (training_service)
- ``redact_secrets`` (gen2.flight_recorder) — same as Dataset Brain indexing
- hidden-reasoning exclusion set (aligned with dataset_brain_worker)
- source/mapping fingerprints from Dataset Brain ``manifest.json``

Does not train and does not execute dataset content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from neural.errors import NeuralError

# Keep aligned with dataset_brain_worker / training_worker.
HIDDEN_RECORD_KEYS = frozenset(
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

CancelCheck = Callable[[], bool]


class NeuralSampleType(str, Enum):
    INSTRUCTION_RESPONSE = "instruction_response"
    CONTEXT_CONTINUATION = "context_continuation"
    QUERY_ANSWER = "query_answer"
    CODE_PATCH = "code_patch"
    ADJACENT_WINDOW = "adjacent_window"
    UNKNOWN_TEXT = "unknown_text"


@dataclass(frozen=True)
class NeuralSample:
    sample_id: str
    sample_type: NeuralSampleType
    text: str
    source_dataset_id: str
    source_fingerprint: str
    row_index: int
    split: str  # train | eval
    mapping_fingerprint: str | None = None
    brain_manifest_fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sample_type"] = self.sample_type.value
        return payload


class NeuralSampleCompileError(NeuralError):
    code = "neural_sample_compile_error"


class NeuralSampleCompileCancelled(NeuralError):
    code = "neural_sample_compile_cancelled"


def _stable_hash(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8", "ignore")).hexdigest()


def strip_hidden_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if str(key).lower() not in HIDDEN_RECORD_KEYS}


def redact_sample_text(text: str) -> str:
    """Apply the same secret redaction used by Dataset Brain indexing."""
    from gen2.flight_recorder import redact_secrets

    redacted = redact_secrets(text)
    return str(redacted).strip() if redacted is not None else ""


def infer_sample_type(row: Mapping[str, Any], mapping: Mapping[str, Any] | None = None) -> NeuralSampleType:
    mapping = mapping or {}
    if str(mapping.get("text_field") or "").strip():
        return NeuralSampleType.UNKNOWN_TEXT
    if row.get("instruction") and row.get("output"):
        return NeuralSampleType.INSTRUCTION_RESPONSE
    if (row.get("query") or row.get("question")) and (row.get("answer") or row.get("response")):
        return NeuralSampleType.QUERY_ANSWER
    if row.get("problem_statement") and row.get("patch"):
        return NeuralSampleType.CODE_PATCH
    if row.get("prompt") and row.get("completion"):
        return NeuralSampleType.CONTEXT_CONTINUATION
    if row.get("text"):
        return NeuralSampleType.UNKNOWN_TEXT
    return NeuralSampleType.ADJACENT_WINDOW


def deterministic_split(sample_id: str, *, eval_ratio: float = 0.1) -> str:
    """Stable train/eval split from sample identity (no leakage via random shuffle)."""
    if eval_ratio <= 0:
        return "train"
    if eval_ratio >= 1:
        return "eval"
    digest = hashlib.sha256(sample_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "eval" if bucket < eval_ratio else "train"


def iter_jsonl_rows(
    path: Path,
    *,
    max_rows: int | None = None,
    start_after_row: int = 0,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Stream JSONL objects. ``start_after_row`` skips line numbers ``<=`` that value."""
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if line_no <= start_after_row:
                continue
            if max_rows is not None and count >= max_rows:
                return
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise NeuralSampleCompileError(
                    f"invalid JSONL at line {line_no}",
                    detail={"path": str(path), "line": line_no, "error": str(exc)},
                ) from exc
            if not isinstance(row, dict):
                raise NeuralSampleCompileError(
                    f"JSONL row must be object at line {line_no}",
                    detail={"path": str(path), "line": line_no},
                )
            yield line_no, row
            count += 1


def brain_manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Stable identity over provenance fields that must match a compile run."""
    payload = {
        "dataset_id": manifest.get("dataset_id"),
        "source_fingerprint": manifest.get("source_fingerprint"),
        "mapping_fingerprint": manifest.get("mapping_fingerprint"),
        "snapshot_path": manifest.get("snapshot_path"),
        "materialized_rows": manifest.get("materialized_rows"),
        "materialized_complete": manifest.get("materialized_complete"),
        "snapshot_bytes": manifest.get("snapshot_bytes"),
    }
    return _stable_hash(payload)


@dataclass
class NeuralSampleCompiler:
    """Compile Dataset Brain snapshot rows into neural training samples."""

    dataset_id: str
    source_fingerprint: str
    mapping: dict[str, Any] = field(default_factory=dict)
    eval_ratio: float = 0.1
    max_rows: int | None = None
    start_after_row: int = 0
    mapping_fingerprint_expected: str | None = None
    brain_manifest_fp: str | None = None
    apply_redaction: bool = True

    def __post_init__(self) -> None:
        text_field = str(self.mapping.get("text_field") or "").strip()
        if text_field and text_field.lower() in HIDDEN_RECORD_KEYS:
            raise NeuralSampleCompileError(
                "hidden-reasoning column cannot be used as neural text_field",
                detail={"text_field": text_field},
            )
        if self.start_after_row < 0:
            raise NeuralSampleCompileError("start_after_row must be >= 0")
        if self.mapping_fingerprint_expected is not None:
            got = self.mapping_fingerprint
            if got != self.mapping_fingerprint_expected:
                raise NeuralSampleCompileError(
                    "mapping fingerprint mismatch vs Dataset Brain manifest",
                    detail={"expected": self.mapping_fingerprint_expected, "got": got},
                )

    @property
    def mapping_fingerprint(self) -> str:
        return _stable_hash(self.mapping)

    @classmethod
    def from_dataset_brain(
        cls,
        training_root: str | Path,
        dataset_id: str,
        *,
        eval_ratio: float = 0.1,
        max_rows: int | None = None,
        start_after_row: int = 0,
        apply_redaction: bool = True,
    ) -> "NeuralSampleCompiler":
        """Build a compiler bound to a materialized Dataset Brain snapshot."""
        from dataset_brain import read_manifest
        from training_service import TrainingWorkspace

        root = Path(training_root).expanduser().resolve()
        manifest = read_manifest(root, dataset_id)
        if not manifest:
            raise NeuralSampleCompileError(
                "Dataset Brain manifest missing",
                detail={"dataset_id": dataset_id, "training_root": str(root)},
            )
        if not manifest.get("materialized_complete"):
            raise NeuralSampleCompileError(
                "Dataset Brain snapshot is not fully materialized",
                detail={
                    "dataset_id": dataset_id,
                    "status": manifest.get("status"),
                    "materialized_complete": manifest.get("materialized_complete"),
                },
            )
        snapshot = Path(str(manifest.get("snapshot_path") or "")).expanduser()
        if not snapshot.is_file():
            raise NeuralSampleCompileError(
                "Dataset Brain snapshot file missing",
                detail={"snapshot_path": str(snapshot)},
            )
        source_fp = str(manifest.get("source_fingerprint") or "").strip()
        if not source_fp:
            raise NeuralSampleCompileError(
                "Dataset Brain manifest lacks source_fingerprint",
                detail={"dataset_id": dataset_id},
            )
        workspace = TrainingWorkspace(root)
        try:
            dataset = workspace.get_dataset(dataset_id)
        except KeyError as exc:
            raise NeuralSampleCompileError(
                "dataset metadata missing for Brain snapshot",
                detail={"dataset_id": dataset_id},
            ) from exc
        mapping = dict(dataset.get("mapping") or {})
        mapping_fp = str(manifest.get("mapping_fingerprint") or "").strip() or None
        return cls(
            dataset_id=dataset_id,
            source_fingerprint=source_fp,
            mapping=mapping,
            eval_ratio=eval_ratio,
            max_rows=max_rows,
            start_after_row=start_after_row,
            mapping_fingerprint_expected=mapping_fp,
            brain_manifest_fp=brain_manifest_fingerprint(manifest),
            apply_redaction=apply_redaction,
        )

    def compile_row(self, row_index: int, row: Mapping[str, Any]) -> NeuralSample | None:
        from training_service import format_training_example

        safe = strip_hidden_fields(row)
        text = format_training_example(safe, self.mapping).strip()
        if not text:
            return None
        if self.apply_redaction:
            text = redact_sample_text(text)
            if not text:
                return None
        sample_type = infer_sample_type(safe, self.mapping)
        sample_id = f"{self.dataset_id}:{row_index}:{_stable_hash(text)[:16]}"
        split = deterministic_split(sample_id, eval_ratio=self.eval_ratio)
        return NeuralSample(
            sample_id=sample_id,
            sample_type=sample_type,
            text=text,
            source_dataset_id=self.dataset_id,
            source_fingerprint=self.source_fingerprint,
            row_index=row_index,
            split=split,
            mapping_fingerprint=self.mapping_fingerprint,
            brain_manifest_fingerprint=self.brain_manifest_fp,
            metadata={
                "chars": len(text),
                "redacted": bool(self.apply_redaction),
            },
        )

    def iter_snapshot(
        self,
        snapshot_path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> Iterator[NeuralSample]:
        path = Path(snapshot_path)
        if not path.is_file():
            raise NeuralSampleCompileError("snapshot missing", detail={"path": str(path)})
        for row_index, row in iter_jsonl_rows(
            path,
            max_rows=self.max_rows,
            start_after_row=self.start_after_row,
        ):
            if cancel_check is not None and cancel_check():
                raise NeuralSampleCompileCancelled(
                    "neural sample compile cancelled",
                    detail={"last_row_index": row_index},
                )
            sample = self.compile_row(row_index, row)
            if sample is None:
                continue
            yield sample
