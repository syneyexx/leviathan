"""Shard-based resumable ingestion with content-addressed files (U262/U276)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .streaming_io import DEFAULT_IO_CHUNK_BYTES, hash_file_streaming, stream_copy_and_hash


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash_bytes(data: bytes) -> str:
    """Hash an in-memory buffer (tests / tiny metadata only — not large shards)."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class ShardSpec:
    shard_id: str
    source_path: str
    index: int
    expected_hash: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "source_path": self.source_path,
            "index": self.index,
            "expected_hash": self.expected_hash,
        }


@dataclass
class ShardIngestCheckpoint:
    """Verified shard/hash cursor — resume must not guess offsets alone (U276)."""

    plan_id: str
    next_index: int
    completed: list[dict[str, Any]] = field(default_factory=list)
    status: str = "in_progress"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "next_index": self.next_index,
            "completed": list(self.completed),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ShardIngestCheckpoint":
        raw = dict(data or {})
        return cls(
            plan_id=str(raw.get("plan_id") or ""),
            next_index=int(raw.get("next_index") or 0),
            completed=list(raw.get("completed") or []),
            status=str(raw.get("status") or "in_progress"),
        )


@dataclass
class ShardIngestPlan:
    plan_id: str
    shards: list[ShardSpec]
    dest_dir: str
    created_at: str = field(default_factory=_utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "shards": [s.public_dict() for s in self.shards],
            "dest_dir": self.dest_dir,
            "created_at": self.created_at,
            "truth": {
                "shard_based_resumable_ingestion": True,
                "content_addressed_files": True,
            },
        }


def build_shard_plan(sources: list[Path], dest_dir: Path) -> ShardIngestPlan:
    shards: list[ShardSpec] = []
    for idx, src in enumerate(sources):
        shards.append(
            ShardSpec(
                shard_id=f"shard_{idx:04d}",
                source_path=str(src),
                index=idx,
            )
        )
    return ShardIngestPlan(
        plan_id=f"sip_{uuid.uuid4().hex[:12]}",
        shards=shards,
        dest_dir=str(dest_dir),
    )


def _completed_entry_for_index(
    completed: list[dict[str, Any]], index: int
) -> dict[str, Any] | None:
    for entry in completed:
        if int(entry.get("index", -1)) == index:
            return entry
    return None


def verify_completed_shard_entry(
    entry: dict[str, Any],
    *,
    shard: ShardSpec | None = None,
    plan_id: str | None = None,
) -> None:
    """Raise if a checkpoint-completed shard artifact is missing or corrupt."""
    if plan_id is not None and entry.get("plan_id") and entry["plan_id"] != plan_id:
        raise ValueError(
            f"checkpoint entry plan_id mismatch for shard index={entry.get('index')}"
        )
    if shard is not None:
        if entry.get("shard_id") and entry["shard_id"] != shard.shard_id:
            raise ValueError(
                f"checkpoint shard_id mismatch at index={shard.index}: "
                f"{entry.get('shard_id')} != {shard.shard_id}"
            )
        if int(entry.get("index", -1)) != shard.index:
            raise ValueError(
                f"checkpoint index mismatch: entry={entry.get('index')} shard={shard.index}"
            )
    out_path = Path(str(entry.get("path") or ""))
    if not out_path.is_file():
        raise ValueError(
            f"verified checkpoint artifact missing: {out_path} (index={entry.get('index')})"
        )
    expected_hash = str(entry.get("content_hash") or "")
    expected_bytes = entry.get("bytes")
    digest, size = hash_file_streaming(out_path)
    if expected_hash and digest != expected_hash:
        raise ValueError(
            f"verified checkpoint hash mismatch at {out_path}: "
            f"expected={expected_hash} observed={digest}"
        )
    if expected_bytes is not None and int(expected_bytes) != size:
        raise ValueError(
            f"verified checkpoint size mismatch at {out_path}: "
            f"expected={expected_bytes} observed={size}"
        )
    if shard is not None and shard.expected_hash and shard.expected_hash != digest:
        raise ValueError(f"hash mismatch for {shard.shard_id}")


def _rewind_checkpoint_to(
    ckpt: ShardIngestCheckpoint, safe_index: int
) -> ShardIngestCheckpoint:
    """Drop completed entries at/after ``safe_index`` and resume from there."""
    kept = [e for e in ckpt.completed if int(e.get("index", -1)) < safe_index]
    ckpt.completed = kept
    ckpt.next_index = safe_index
    ckpt.status = "in_progress"
    return ckpt


def ingest_shards(
    plan: ShardIngestPlan,
    *,
    checkpoint: ShardIngestCheckpoint | None = None,
    cancel_check: Callable[[], bool] | None = None,
    interrupt_after: int | None = None,
    chunk_size: int = DEFAULT_IO_CHUNK_BYTES,
    reverify_completed: bool = True,
) -> tuple[ShardIngestCheckpoint, list[dict[str, Any]]]:
    """Copy shards into content-addressed dest; resume from verified checkpoint.

    Peak memory is O(chunk_size), not O(shard size). Previously completed entries
    are re-verified (exists + content hash + size) before being trusted.
    """
    dest = Path(plan.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ckpt = checkpoint or ShardIngestCheckpoint(plan_id=plan.plan_id, next_index=0)
    if ckpt.plan_id and ckpt.plan_id != plan.plan_id:
        raise ValueError("checkpoint plan_id does not match ingest plan")

    if reverify_completed and ckpt.next_index > 0:
        for shard in plan.shards:
            if shard.index >= ckpt.next_index:
                break
            entry = _completed_entry_for_index(ckpt.completed, shard.index)
            if entry is None:
                _rewind_checkpoint_to(ckpt, shard.index)
                break
            try:
                verify_completed_shard_entry(entry, shard=shard, plan_id=plan.plan_id)
            except ValueError:
                _rewind_checkpoint_to(ckpt, shard.index)
                # Best-effort cleanup of corrupt published artifact
                corrupt = Path(str(entry.get("path") or ""))
                if corrupt.is_file():
                    try:
                        corrupt.unlink()
                    except OSError:
                        pass
                break

    outputs: list[dict[str, Any]] = list(ckpt.completed)
    processed_this_run = 0
    for shard in plan.shards:
        if shard.index < ckpt.next_index:
            continue
        if cancel_check and cancel_check():
            ckpt.status = "cancelled"
            return ckpt, outputs
        if interrupt_after is not None and processed_this_run >= interrupt_after:
            ckpt.status = "interrupted"
            return ckpt, outputs
        src = Path(shard.source_path)
        if not src.is_file():
            raise FileNotFoundError(f"shard source missing: {src}")

        # Hash source first (streaming) so we know the content-addressed name
        # without loading the entire shard into memory.
        digest, size = hash_file_streaming(src, chunk_size=chunk_size)
        if shard.expected_hash and shard.expected_hash != digest:
            raise ValueError(f"hash mismatch for {shard.shard_id}")
        out_path = dest / f"{digest}{src.suffix or '.bin'}"
        if out_path.exists():
            existing_digest, existing_size = hash_file_streaming(
                out_path, chunk_size=chunk_size
            )
            if existing_digest != digest or existing_size != size:
                # Content-address collision with divergent bytes — refuse.
                raise ValueError(
                    f"content-addressed path collision with divergent content: {out_path}"
                )
        else:
            written_digest, written_size = stream_copy_and_hash(
                src, out_path, chunk_size=chunk_size, fsync=True
            )
            if written_digest != digest or written_size != size:
                try:
                    out_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise ValueError(
                    f"stream copy integrity failure for {shard.shard_id}: "
                    f"source={digest}/{size} written={written_digest}/{written_size}"
                )

        entry = {
            "shard_id": shard.shard_id,
            "index": shard.index,
            "content_hash": digest,
            "path": str(out_path),
            "bytes": size,
            "verified_at": _utc_now(),
            "plan_id": plan.plan_id,
        }
        outputs.append(entry)
        ckpt.completed = list(outputs)
        ckpt.next_index = shard.index + 1
        processed_this_run += 1
    ckpt.status = "completed"
    return ckpt, outputs
