from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BackupError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    created_at: str
    database_path: str
    database_sha256: str
    size_bytes: int
    schema_version: int
    artifacts_copied: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "database_path": self.database_path,
            "database_sha256": self.database_sha256,
            "size_bytes": self.size_bytes,
            "schema_version": self.schema_version,
            "artifacts_copied": self.artifacts_copied,
            "metadata": self.metadata,
            "truth": {
                "backup_is_not_cloud_sync": True,
                "restore_requires_explicit_confirm": True,
            },
        }


class BackupService:
    """Create and restore local LEVIATHAN SQLite snapshots.

    Restores never run silently — callers must pass ``confirm=True``.
    """

    def __init__(self, *, database_path: Path, artifacts_root: Path, backup_root: Path) -> None:
        self.database_path = database_path
        self.artifacts_root = artifacts_root
        self.backup_root = backup_root
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def list(self, *, limit: int = 50) -> list[BackupManifest]:
        manifests: list[BackupManifest] = []
        if not self.backup_root.is_dir():
            return manifests
        for path in sorted(self.backup_root.glob("*/manifest.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                manifests.append(
                    BackupManifest(
                        backup_id=str(data["backup_id"]),
                        created_at=str(data["created_at"]),
                        database_path=str(data["database_path"]),
                        database_sha256=str(data["database_sha256"]),
                        size_bytes=int(data["size_bytes"]),
                        schema_version=int(data.get("schema_version") or 0),
                        artifacts_copied=int(data.get("artifacts_copied") or 0),
                        metadata=dict(data.get("metadata") or {}),
                    )
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(manifests) >= max(1, min(limit, 200)):
                break
        return manifests

    def create(self, *, note: str | None = None) -> BackupManifest:
        if not self.database_path.is_file():
            raise BackupError(f"Database not found: {self.database_path}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"backup-{stamp}"
        dest = self.backup_root / backup_id
        if dest.exists():
            raise BackupError(f"Backup already exists: {backup_id}")
        dest.mkdir(parents=True, exist_ok=False)

        db_copy = dest / "leviathan.db"
        self._safe_sqlite_copy(self.database_path, db_copy)
        digest = hashlib.sha256(db_copy.read_bytes()).hexdigest()
        schema_version = self._schema_version(db_copy)

        artifacts_copied = 0
        art_src = self.artifacts_root
        if art_src.is_dir():
            art_dest = dest / "artifacts"
            shutil.copytree(art_src, art_dest)
            artifacts_copied = sum(1 for p in art_dest.rglob("*") if p.is_file())

        manifest = BackupManifest(
            backup_id=backup_id,
            created_at=utc_now(),
            database_path=str(db_copy),
            database_sha256=digest,
            size_bytes=db_copy.stat().st_size,
            schema_version=schema_version,
            artifacts_copied=artifacts_copied,
            metadata={"note": note} if note else {},
        )
        (dest / "manifest.json").write_text(
            json.dumps(manifest.public_dict(), indent=2),
            encoding="utf-8",
        )
        return manifest

    def restore(self, backup_id: str, *, confirm: bool = False) -> BackupManifest:
        if not confirm:
            raise BackupError("Restore refused: confirm=true is required")
        dest = self.backup_root / backup_id
        manifest_path = dest / "manifest.json"
        db_copy = dest / "leviathan.db"
        if not manifest_path.is_file() or not db_copy.is_file():
            raise BackupError(f"Backup not found: {backup_id}")

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = str(data.get("database_sha256") or "")
        actual = hashlib.sha256(db_copy.read_bytes()).hexdigest()
        if expected and actual != expected:
            raise BackupError("Backup database hash mismatch — refusing restore")

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # Replace live DB with verified snapshot.
        tmp = self.database_path.with_suffix(".restore-tmp")
        shutil.copy2(db_copy, tmp)
        tmp.replace(self.database_path)

        art_src = dest / "artifacts"
        if art_src.is_dir():
            if self.artifacts_root.exists():
                shutil.rmtree(self.artifacts_root)
            shutil.copytree(art_src, self.artifacts_root)

        return BackupManifest(
            backup_id=str(data["backup_id"]),
            created_at=str(data["created_at"]),
            database_path=str(self.database_path),
            database_sha256=actual,
            size_bytes=int(data.get("size_bytes") or db_copy.stat().st_size),
            schema_version=int(data.get("schema_version") or 0),
            artifacts_copied=int(data.get("artifacts_copied") or 0),
            metadata={**(data.get("metadata") or {}), "restored_at": utc_now()},
        )

    def _safe_sqlite_copy(self, source: Path, dest: Path) -> None:
        src = sqlite3.connect(str(source), timeout=30)
        try:
            dest_conn = sqlite3.connect(str(dest))
            try:
                src.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src.close()

    def _schema_version(self, db_path: Path) -> int:
        try:
            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations"
                ).fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0
