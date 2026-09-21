"""Atomic neural-memory checkpoints.

Manifest publication uses temp + fsync + os.replace. Integrity hash covers the
payload bytes so corruption fails closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from neural.config import NeuralMemoryConfig
from neural.deps import require_torch
from neural.errors import NeuralCheckpointCorrupt, NeuralCheckpointIncompatible
from neural.memory import NeuralMemory


# V2: embedding-backed production memory. Schema 1 (toy dim=32) checkpoints
# must fail closed when loaded against schema 2 / embedding-dim configs.
SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.json"
WEIGHTS_NAME = "weights.pt"
LATEST_NAME = "latest.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(data)
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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(path, raw)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class NeuralMemoryCheckpointStore:
    """Filesystem checkpoint store with last-known-good + candidate separation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.good_dir = self.root / "good"
        self.candidate_dir = self.root / "candidate"
        self.good_dir.mkdir(parents=True, exist_ok=True)
        self.candidate_dir.mkdir(parents=True, exist_ok=True)

    def _checkpoint_dir(self, checkpoint_id: str, *, candidate: bool) -> Path:
        base = self.candidate_dir if candidate else self.good_dir
        return base / checkpoint_id

    def save(
        self,
        memory: NeuralMemory,
        *,
        checkpoint_id: str,
        parent_checkpoint: str | None = None,
        candidate: bool = True,
        extra_metrics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        torch = require_torch()
        target = self._checkpoint_dir(checkpoint_id, candidate=candidate)
        target.mkdir(parents=True, exist_ok=True)
        weights_path = target / WEIGHTS_NAME
        payload = {
            "slow": memory.slow.state_dict(),
            "fast": memory.fast.state_dict(),
            "replay_keys": [t.detach().cpu() for t in memory._replay_keys],
            "replay_values": [t.detach().cpu() for t in memory._replay_values],
            "replay_ids": list(memory._replay_ids),
            "association_count": memory._association_count,
            "write_count": memory._write_count,
            "read_count": memory._read_count,
            "rollback_count": memory._rollback_count,
        }
        # Write weights to a temp file then replace.
        tmp_weights = target / f".{WEIGHTS_NAME}.tmp"
        torch.save(payload, tmp_weights)
        with tmp_weights.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_weights, weights_path)
        integrity = _sha256_file(weights_path)
        metrics = memory.metrics().to_dict()
        if extra_metrics:
            metrics.update(dict(extra_metrics))
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "architecture_version": memory.config.architecture_version,
            "checkpoint_id": checkpoint_id,
            "created_at": utc_now(),
            "parent_checkpoint": parent_checkpoint,
            "dim": memory.config.dim,
            "hidden_dim": memory.config.hidden_dim,
            "dtype": "float32",
            "config": memory.config.to_dict(),
            "metrics": metrics,
            "integrity_hash": integrity,
            "weights_file": WEIGHTS_NAME,
            "candidate": candidate,
        }
        _atomic_write_json(target / MANIFEST_NAME, manifest)
        pointer = {
            "checkpoint_id": checkpoint_id,
            "path": str(target),
            "candidate": candidate,
            "updated_at": utc_now(),
            "integrity_hash": integrity,
        }
        pointer_name = "latest_candidate.json" if candidate else LATEST_NAME
        _atomic_write_json(self.root / pointer_name, pointer)
        return manifest

    def load(
        self,
        checkpoint_id: str | None = None,
        *,
        candidate: bool = False,
        expected_config: NeuralMemoryConfig | None = None,
    ) -> NeuralMemory:
        if checkpoint_id is None:
            pointer_path = self.root / ("latest_candidate.json" if candidate else LATEST_NAME)
            if not pointer_path.is_file():
                raise NeuralCheckpointCorrupt("latest checkpoint pointer missing", detail={"path": str(pointer_path)})
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            checkpoint_id = str(pointer["checkpoint_id"])
            candidate = bool(pointer.get("candidate", candidate))
        target = self._checkpoint_dir(str(checkpoint_id), candidate=candidate)
        manifest_path = target / MANIFEST_NAME
        weights_path = target / WEIGHTS_NAME
        if not manifest_path.is_file() or not weights_path.is_file():
            raise NeuralCheckpointCorrupt(
                "checkpoint files missing",
                detail={"dir": str(target)},
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise NeuralCheckpointCorrupt("manifest JSON corrupt", detail={"error": str(exc)}) from exc
        if int(manifest.get("schema_version", -1)) != SCHEMA_VERSION:
            raise NeuralCheckpointIncompatible(
                "unsupported checkpoint schema",
                detail={"got": manifest.get("schema_version"), "expected": SCHEMA_VERSION},
            )
        integrity = _sha256_file(weights_path)
        if integrity != str(manifest.get("integrity_hash") or ""):
            raise NeuralCheckpointCorrupt(
                "checkpoint integrity hash mismatch",
                detail={"expected": manifest.get("integrity_hash"), "got": integrity},
            )
        cfg = NeuralMemoryConfig.from_dict(dict(manifest.get("config") or {}))
        if expected_config is not None:
            if expected_config.dim != cfg.dim or expected_config.architecture_version != cfg.architecture_version:
                raise NeuralCheckpointIncompatible(
                    "checkpoint incompatible with expected model/memory config",
                    detail={
                        "expected_dim": expected_config.dim,
                        "got_dim": cfg.dim,
                        "expected_arch": expected_config.architecture_version,
                        "got_arch": cfg.architecture_version,
                    },
                )
        torch = require_torch()
        try:
            payload = torch.load(weights_path, map_location="cpu", weights_only=True)
        except TypeError:
            # Older torch without weights_only=
            payload = torch.load(weights_path, map_location="cpu")
        except Exception as exc:  # noqa: BLE001
            raise NeuralCheckpointCorrupt("weights unreadable", detail={"error": str(exc)}) from exc

        memory = NeuralMemory(cfg)
        try:
            memory.slow.load_state_dict(payload["slow"])
            memory.fast.load_state_dict(payload["fast"])
        except Exception as exc:  # noqa: BLE001
            raise NeuralCheckpointIncompatible("state_dict load failed", detail={"error": str(exc)}) from exc
        memory._replay_keys = [t.to(memory.device) for t in payload.get("replay_keys", [])]
        memory._replay_values = [t.to(memory.device) for t in payload.get("replay_values", [])]
        memory._replay_ids = list(payload.get("replay_ids", []))
        memory._association_count = int(payload.get("association_count", 0))
        memory._write_count = int(payload.get("write_count", 0))
        memory._read_count = int(payload.get("read_count", 0))
        memory._rollback_count = int(payload.get("rollback_count", 0))
        return memory

    def promote_candidate(self, checkpoint_id: str) -> dict[str, Any]:
        """Promote a validated candidate to last-known-good via copy + pointer publish."""
        src = self._checkpoint_dir(checkpoint_id, candidate=True)
        if not (src / MANIFEST_NAME).is_file():
            raise NeuralCheckpointCorrupt("candidate missing", detail={"id": checkpoint_id})
        # Re-validate integrity before promotion.
        memory = self.load(checkpoint_id, candidate=True)
        return self.save(
            memory,
            checkpoint_id=checkpoint_id,
            parent_checkpoint=checkpoint_id,
            candidate=False,
            extra_metrics={"promoted_from_candidate": True},
        )

    def reject_candidate(self, checkpoint_id: str) -> None:
        target = self._checkpoint_dir(checkpoint_id, candidate=True)
        if target.exists():
            for child in sorted(target.glob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
            try:
                target.rmdir()
            except OSError:
                pass
