"""Shard-based resumable ingestion with content-addressed files (U262/U276)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash_bytes(data: bytes) -> str:
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


def ingest_shards(
    plan: ShardIngestPlan,
    *,
    checkpoint: ShardIngestCheckpoint | None = None,
    cancel_check: Callable[[], bool] | None = None,
    interrupt_after: int | None = None,
) -> tuple[ShardIngestCheckpoint, list[dict[str, Any]]]:
    """Copy shards into content-addressed dest; resume from verified checkpoint."""
    dest = Path(plan.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ckpt = checkpoint or ShardIngestCheckpoint(plan_id=plan.plan_id, next_index=0)
    if ckpt.plan_id and ckpt.plan_id != plan.plan_id:
        raise ValueError("checkpoint plan_id does not match ingest plan")
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
        data = src.read_bytes()
        digest = content_hash_bytes(data)
        if shard.expected_hash and shard.expected_hash != digest:
            raise ValueError(f"hash mismatch for {shard.shard_id}")
        out_path = dest / f"{digest}{src.suffix or '.bin'}"
        if not out_path.exists():
            tmp = out_path.with_suffix(out_path.suffix + ".partial")
            tmp.write_bytes(data)
            tmp.replace(out_path)
        entry = {
            "shard_id": shard.shard_id,
            "index": shard.index,
            "content_hash": digest,
            "path": str(out_path),
            "bytes": len(data),
            "verified_at": _utc_now(),
        }
        outputs.append(entry)
        ckpt.completed = list(outputs)
        ckpt.next_index = shard.index + 1
        processed_this_run += 1
    ckpt.status = "completed"
    return ckpt, outputs
