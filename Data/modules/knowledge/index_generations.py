"""Atomic Brain/index generation pointers.

Chat must only observe a complete generation: either N or N+1 after atomic switch.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IndexGenerationRegistry:
    """Filesystem-backed active index generation pointer with crash-safe switch."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active_path = self.root / "ACTIVE"
        self._gens = self.root / "generations"
        self._gens.mkdir(parents=True, exist_ok=True)

    def begin_generation(self) -> str:
        with self._lock:
            gen_id = f"gen-{uuid.uuid4().hex[:12]}"
            path = self._gens / gen_id
            path.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                path / "STATUS",
                json.dumps({"state": "BUILDING", "started_at": _utc()}, ensure_ascii=False),
            )
            return gen_id

    def generation_dir(self, gen_id: str) -> Path:
        return self._gens / gen_id

    def write_manifest(self, gen_id: str, manifest: dict[str, Any]) -> Path:
        path = self.generation_dir(gen_id) / "manifest.json"
        payload = {
            **manifest,
            "generation_id": gen_id,
            "validated_at": _utc(),
            "state": "READY",
        }
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(
            self.generation_dir(gen_id) / "STATUS",
            json.dumps({"state": "READY", "ready_at": _utc()}, ensure_ascii=False),
        )
        return path

    def activate(self, gen_id: str) -> None:
        """Atomically switch the active generation pointer after READY validation."""
        with self._lock:
            status_path = self.generation_dir(gen_id) / "STATUS"
            if not status_path.exists():
                raise RuntimeError(f"generation {gen_id} has no STATUS")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("state") != "READY":
                raise RuntimeError(f"generation {gen_id} is not READY (state={status.get('state')})")
            manifest_path = self.generation_dir(gen_id) / "manifest.json"
            if not manifest_path.exists():
                raise RuntimeError(f"generation {gen_id} missing manifest")
            # Pointer file swap is atomic on POSIX; on Windows atomic_write_text uses replace.
            atomic_write_text(self._active_path, gen_id + "\n")

    def active_generation(self) -> str | None:
        with self._lock:
            if not self._active_path.exists():
                return None
            return self._active_path.read_text(encoding="utf-8").strip() or None

    def retire(self, gen_id: str) -> None:
        with self._lock:
            active = self.active_generation()
            if gen_id == active:
                raise RuntimeError("cannot retire the active generation")
            status = self.generation_dir(gen_id) / "STATUS"
            if status.exists():
                atomic_write_text(
                    status,
                    json.dumps({"state": "RETIRED", "retired_at": _utc()}, ensure_ascii=False),
                )
