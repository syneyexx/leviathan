"""Job-scoped ephemeral scratch manager for external-memory algorithms."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.paths import PathEscapeError, path_under_root, safe_join

from .storage_authority import StorageClass, assert_no_competing_domain_db
from .types import DatasetError


SCRATCH_MANIFEST = "scratch-manifest.json"
DEFAULT_MAX_SCRATCH_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_GRACE_SECONDS = 3600


@dataclass
class ScratchSession:
    job_id: str
    root: Path
    created_at: float
    storage_class: str = StorageClass.EPHEMERAL_SCRATCH.value

    def path(self, *parts: str) -> Path:
        return safe_join(self.root, *parts)

    def byte_count(self) -> int:
        total = 0
        if not self.root.exists():
            return 0
        for p in self.root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def write_manifest(self, **extra: Any) -> None:
        payload = {
            "schemaVersion": 1,
            "jobId": self.job_id,
            "createdAt": self.created_at,
            "storageClass": self.storage_class,
            "byteCount": self.byte_count(),
            "truth": {
                "ephemeralScratch": True,
                "notCanonicalAuthority": True,
            },
            **extra,
        }
        atomic_write_text(self.root / SCRATCH_MANIFEST, json.dumps(payload, indent=2, sort_keys=True) + "\n")


class ScratchManager:
    """Governed per-job scratch under corpus/scratch/<job-id>/."""

    def __init__(
        self,
        scratch_root: Path,
        *,
        max_scratch_bytes: int = DEFAULT_MAX_SCRATCH_BYTES,
    ) -> None:
        self.scratch_root = Path(scratch_root)
        self.max_scratch_bytes = int(max_scratch_bytes)
        ensure_dir(self.scratch_root)

    def open_session(self, job_id: str) -> ScratchSession:
        safe_id = str(job_id).strip()
        if not safe_id or ".." in safe_id or "/" in safe_id or "\\" in safe_id:
            raise DatasetError("Invalid scratch job id", code="invalid_scratch_job_id")
        root = safe_join(self.scratch_root, safe_id)
        ensure_dir(root)
        session = ScratchSession(job_id=safe_id, root=root, created_at=time.time())
        session.write_manifest()
        return session

    def cleanup_session(self, job_id: str) -> bool:
        safe_id = str(job_id).strip()
        root = safe_join(self.scratch_root, safe_id)
        if not root.exists():
            return False
        if not path_under_root(self.scratch_root, root):
            raise PathEscapeError(f"Scratch path escapes root: {root}")
        shutil.rmtree(root, ignore_errors=True)
        return True

    def reconcile(
        self,
        *,
        active_job_ids: set[str] | None = None,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Remove stale scratch dirs not owned by active jobs past grace period."""
        active = {str(x) for x in (active_job_ids or set())}
        ts = time.time() if now is None else float(now)
        removed: list[str] = []
        retained: list[str] = []
        if not self.scratch_root.exists():
            return {"removed": removed, "retained": retained, "scanned": 0}
        scanned = 0
        for child in self.scratch_root.iterdir():
            if not child.is_dir():
                continue
            scanned += 1
            job_id = child.name
            if job_id in active:
                retained.append(job_id)
                continue
            age = ts - child.stat().st_mtime
            if age < grace_seconds:
                retained.append(job_id)
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed.append(job_id)
        return {"removed": removed, "retained": retained, "scanned": scanned}

    def assert_within_quota(self, session: ScratchSession) -> None:
        used = session.byte_count()
        if used > self.max_scratch_bytes:
            raise DatasetError(
                f"Scratch quota exceeded: {used} > {self.max_scratch_bytes}",
                code="SCRATCH_LIMIT_EXCEEDED",
                details={"byteCount": used, "maxScratchBytes": self.max_scratch_bytes},
            )

    def ephemeral_sqlite_path(self, session: ScratchSession, name: str = "dedupe.sqlite") -> Path:
        """Job-scoped ephemeral SQLite — NEVER a competing domain authority."""
        path = session.path(name)
        assert_no_competing_domain_db(path)
        # Use a non-forbidden name under scratch
        if path.name.lower() in {
            "knowledge.db",
            "trading.db",
            "simulation.db",
            "datasets.db",
            "control.db",
        }:
            raise DatasetError("Forbidden scratch DB name", code="forbidden_scratch_db")
        return path
