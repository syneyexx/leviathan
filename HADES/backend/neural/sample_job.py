"""Resumable, cancellable Dataset Brain → neural sample compile jobs.

Filesystem-backed (no FastAPI routes). Follows the same cancel.requested +
atomic job.json pattern used by Dataset Brain / training workers.

Output is a bounded streaming JSONL of NeuralSample records — never a full
in-memory materialization of a large Brain snapshot.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neural.errors import NeuralError
from neural.samples import (
    NeuralSampleCompileCancelled,
    NeuralSampleCompileError,
    NeuralSampleCompiler,
)

COMPILE_JOB_ID_RE = re.compile(r"^nsc_[0-9a-f]{16}$")
JOB_SCHEMA_VERSION = 1
DEFAULT_CHECKPOINT_EVERY = 32


class NeuralSampleJobError(NeuralError):
    code = "neural_sample_job_error"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise NeuralSampleJobError(f"expected JSON object in {path.name}")
    return value


def new_compile_job_id() -> str:
    return f"nsc_{secrets.token_hex(8)}"


class NeuralSampleCompileJob:
    """Compile a Dataset Brain snapshot into a resumable samples JSONL stream."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        if not COMPILE_JOB_ID_RE.fullmatch(job_id):
            raise NeuralSampleJobError("invalid neural sample compile job id", detail={"job_id": job_id})
        return self.root / job_id

    def job_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def samples_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "samples.jsonl"

    def cancel_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "cancel.requested"

    def read_job(self, job_id: str) -> dict[str, Any]:
        path = self.job_path(job_id)
        if not path.is_file():
            raise NeuralSampleJobError("compile job not found", detail={"job_id": job_id})
        return _read_json(path)

    def write_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        path = self.job_path(job_id)
        current = _read_json(path) if path.is_file() else {}
        current.update(updates)
        current["updated_at"] = utc_now()
        _atomic_json(path, current)
        return current

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        self.cancel_path(job_id).write_text("1\n", encoding="utf-8")
        job = self.read_job(job_id)
        if job.get("status") in {"queued", "running"}:
            return self.write_job(job_id, {"status": "cancelling"})
        return job

    def create(
        self,
        *,
        training_root: str | Path,
        dataset_id: str,
        eval_ratio: float = 0.1,
        max_rows: int | None = None,
        max_samples: int | None = None,
        checkpoint_every: int = DEFAULT_CHECKPOINT_EVERY,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a job bound to a materialized Brain snapshot (does not run yet)."""
        from dataset_brain import read_manifest

        training_root = Path(training_root).expanduser().resolve()
        # Validate Brain readiness up front (fail closed).
        compiler = NeuralSampleCompiler.from_dataset_brain(
            training_root,
            dataset_id,
            eval_ratio=eval_ratio,
            max_rows=max_rows,
        )
        manifest = read_manifest(training_root, dataset_id) or {}
        jid = job_id or new_compile_job_id()
        if not COMPILE_JOB_ID_RE.fullmatch(jid):
            raise NeuralSampleJobError("invalid job id", detail={"job_id": jid})
        job_dir = self._job_dir(jid)
        if job_dir.exists():
            raise NeuralSampleJobError("compile job already exists", detail={"job_id": jid})
        job_dir.mkdir(parents=True, exist_ok=False)
        job = {
            "schema_version": JOB_SCHEMA_VERSION,
            "id": jid,
            "status": "queued",
            "dataset_id": dataset_id,
            "training_root": str(training_root),
            "snapshot_path": str(manifest.get("snapshot_path") or ""),
            "source_fingerprint": compiler.source_fingerprint,
            "mapping_fingerprint": compiler.mapping_fingerprint,
            "brain_manifest_fingerprint": compiler.brain_manifest_fp,
            "eval_ratio": float(eval_ratio),
            "max_rows": max_rows,
            "max_samples": max_samples,
            "checkpoint_every": max(1, int(checkpoint_every)),
            "last_row_index": 0,
            "samples_emitted": 0,
            "train_samples": 0,
            "eval_samples": 0,
            "bytes_written": 0,
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "completed_at": None,
        }
        _atomic_json(self.job_path(jid), job)
        (job_dir / "samples.jsonl").write_text("", encoding="utf-8")
        return job

    def run(self, job_id: str) -> dict[str, Any]:
        """Execute or resume a compile job until complete, cancelled, or failed."""
        job = self.read_job(job_id)
        if job.get("status") in {"completed", "cancelled", "failed"}:
            return job

        training_root = Path(str(job["training_root"]))
        dataset_id = str(job["dataset_id"])
        start_after = int(job.get("last_row_index") or 0)
        max_samples = job.get("max_samples")
        max_samples_i = int(max_samples) if max_samples is not None else None
        checkpoint_every = max(1, int(job.get("checkpoint_every") or DEFAULT_CHECKPOINT_EVERY))

        try:
            compiler = NeuralSampleCompiler.from_dataset_brain(
                training_root,
                dataset_id,
                eval_ratio=float(job.get("eval_ratio") or 0.1),
                max_rows=job.get("max_rows"),
                start_after_row=start_after,
                apply_redaction=True,
            )
        except NeuralSampleCompileError as exc:
            return self.write_job(
                job_id,
                {"status": "failed", "error": str(exc), "completed_at": utc_now()},
            )

        # Provenance drift vs job creation must fail closed.
        if compiler.source_fingerprint != job.get("source_fingerprint"):
            return self.write_job(
                job_id,
                {
                    "status": "failed",
                    "error": "source_fingerprint changed since job creation",
                    "completed_at": utc_now(),
                },
            )
        if compiler.mapping_fingerprint != job.get("mapping_fingerprint"):
            return self.write_job(
                job_id,
                {
                    "status": "failed",
                    "error": "mapping_fingerprint changed since job creation",
                    "completed_at": utc_now(),
                },
            )
        if compiler.brain_manifest_fp != job.get("brain_manifest_fingerprint"):
            return self.write_job(
                job_id,
                {
                    "status": "failed",
                    "error": "brain manifest fingerprint changed since job creation",
                    "completed_at": utc_now(),
                },
            )

        snapshot_path = Path(str(job.get("snapshot_path") or ""))
        samples_file = self.samples_path(job_id)
        cancel_file = self.cancel_path(job_id)

        self.write_job(job_id, {"status": "running", "error": None})
        samples_emitted = int(job.get("samples_emitted") or 0)
        train_samples = int(job.get("train_samples") or 0)
        eval_samples = int(job.get("eval_samples") or 0)
        last_row = start_after
        since_checkpoint = 0

        def cancel_check() -> bool:
            return cancel_file.is_file()

        try:
            with samples_file.open("a", encoding="utf-8", newline="\n") as handle:
                for sample in compiler.iter_snapshot(snapshot_path, cancel_check=cancel_check):
                    if max_samples_i is not None and samples_emitted >= max_samples_i:
                        break
                    line = json.dumps(sample.to_dict(), ensure_ascii=False, sort_keys=True)
                    handle.write(line + "\n")
                    samples_emitted += 1
                    if sample.split == "eval":
                        eval_samples += 1
                    else:
                        train_samples += 1
                    last_row = sample.row_index
                    since_checkpoint += 1
                    if since_checkpoint >= checkpoint_every:
                        handle.flush()
                        os.fsync(handle.fileno())
                        self.write_job(
                            job_id,
                            {
                                "status": "running",
                                "last_row_index": last_row,
                                "samples_emitted": samples_emitted,
                                "train_samples": train_samples,
                                "eval_samples": eval_samples,
                                "bytes_written": samples_file.stat().st_size,
                            },
                        )
                        since_checkpoint = 0
                handle.flush()
                os.fsync(handle.fileno())
        except NeuralSampleCompileCancelled:
            self.write_job(
                job_id,
                {
                    "status": "cancelled",
                    "last_row_index": last_row,
                    "samples_emitted": samples_emitted,
                    "train_samples": train_samples,
                    "eval_samples": eval_samples,
                    "bytes_written": samples_file.stat().st_size if samples_file.is_file() else 0,
                    "completed_at": utc_now(),
                    "error": None,
                },
            )
            return self.read_job(job_id)
        except Exception as exc:  # noqa: BLE001 — persist failure truthfully
            self.write_job(
                job_id,
                {
                    "status": "failed",
                    "last_row_index": last_row,
                    "samples_emitted": samples_emitted,
                    "train_samples": train_samples,
                    "eval_samples": eval_samples,
                    "bytes_written": samples_file.stat().st_size if samples_file.is_file() else 0,
                    "error": str(exc)[:4000],
                    "completed_at": utc_now(),
                },
            )
            return self.read_job(job_id)

        return self.write_job(
            job_id,
            {
                "status": "completed",
                "last_row_index": last_row,
                "samples_emitted": samples_emitted,
                "train_samples": train_samples,
                "eval_samples": eval_samples,
                "bytes_written": samples_file.stat().st_size if samples_file.is_file() else 0,
                "completed_at": utc_now(),
                "error": None,
            },
        )

    def iter_emitted_samples(self, job_id: str):
        """Stream previously emitted samples without loading the full file."""
        path = self.samples_path(job_id)
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    yield json.loads(text)
                except json.JSONDecodeError as exc:
                    raise NeuralSampleJobError(
                        "corrupt samples.jsonl",
                        detail={"job_id": job_id, "line": line_no, "error": str(exc)},
                    ) from exc
