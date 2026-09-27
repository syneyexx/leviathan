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


BACKUP_KIND_METADATA_ONLY = "METADATA_ONLY"
BACKUP_KIND_FULL_WITH_CORPUS = "FULL_WITH_CORPUS"

# Three-DB restore terminal states — files cannot be replaced cross-file atomically.
RESTORE_OLD_SET_ACTIVE = "OLD_SET_ACTIVE"
RESTORE_NEW_SET_ACTIVE = "NEW_SET_ACTIVE"
RESTORE_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
RESTORE_JOURNAL_NAME = "restore_journal.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _rel_or_abs(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


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
    # W178 truth — corpus inclusion honesty
    backup_kind: str = BACKUP_KIND_METADATA_ONLY
    corpus_files_included: bool = False
    artifacts_included: bool = False
    is_complete_data_snapshot: bool = False
    corpus_inventory: list[dict[str, Any]] = field(default_factory=list)
    missing_corpus_files: list[dict[str, Any]] = field(default_factory=list)
    # Three-DB set (optional; legacy single-DB backups omit this)
    databases: dict[str, dict[str, Any]] = field(default_factory=dict)
    backup_set_complete: bool = False

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
            "backupKind": self.backup_kind,
            "corpusFilesIncluded": self.corpus_files_included,
            "artifactsIncluded": self.artifacts_included,
            "isCompleteDataSnapshot": self.is_complete_data_snapshot,
            "corpusInventory": list(self.corpus_inventory),
            "missingCorpusFiles": list(self.missing_corpus_files),
            "databases": dict(self.databases),
            "backupSetComplete": self.backup_set_complete,
            "truth": {
                "backup_is_not_cloud_sync": True,
                "restore_requires_explicit_confirm": True,
                "backupKind": self.backup_kind,
                "corpusFilesIncluded": self.corpus_files_included,
                "artifactsIncluded": self.artifacts_included,
                "isCompleteDataSnapshot": self.is_complete_data_snapshot,
                "metadataOnlyIsNotCompleteSnapshot": self.backup_kind == BACKUP_KIND_METADATA_ONLY,
                "corpusInventoryCount": len(self.corpus_inventory),
                "missingCorpusFileCount": len(self.missing_corpus_files),
                "canonicalDatabaseCount": len(self.databases) or 1,
                "backupSetComplete": self.backup_set_complete,
                # BACKUP-002: three SQLite files cannot be replaced as one OS transaction.
                "crossFileRestoreIsNotAtomic": True,
                "corpusInventorySourceDomain": (self.metadata or {}).get(
                    "corpusInventorySourceDomain", "KNOWLEDGE"
                ),
                "restoreTerminalState": (self.metadata or {}).get("restoreTerminalState"),
            },
        }


class BackupService:
    """Create and restore local LEVIATHAN SQLite snapshots.

    Restores never run silently — callers must pass ``confirm=True``.

    W178: Backup truth declares whether corpus/dataset files are included.
    Default backups are ``METADATA_ONLY`` (DB + optional artifacts) and must
    never be presented as a complete data snapshot. Optional
    ``include_corpus=True`` copies corpus files when ``corpus_root`` is set.

    Three-DB: when ``database_paths`` is provided, backups include Control,
    Knowledge, and Market as one coherent backup set.
    """

    def __init__(
        self,
        *,
        database_path: Path,
        artifacts_root: Path,
        backup_root: Path,
        corpus_root: Path | None = None,
        database_paths: Any | None = None,
    ) -> None:
        self.database_path = database_path
        self.artifacts_root = artifacts_root
        self.backup_root = backup_root
        self.corpus_root = Path(corpus_root) if corpus_root else None
        self.database_paths = database_paths
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def list(self, *, limit: int = 50) -> list[BackupManifest]:
        manifests: list[BackupManifest] = []
        if not self.backup_root.is_dir():
            return manifests
        for path in sorted(self.backup_root.glob("*/manifest.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                manifests.append(self._manifest_from_dict(data))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(manifests) >= max(1, min(limit, 200)):
                break
        return manifests

    def create(
        self,
        *,
        note: str | None = None,
        include_corpus: bool = False,
    ) -> BackupManifest:
        paths = self._canonical_paths()
        for domain, path in paths.items():
            if not path.is_file():
                raise BackupError(f"{domain} database not found: {path}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"backup-{stamp}"
        dest = self.backup_root / backup_id
        if dest.exists():
            raise BackupError(f"Backup already exists: {backup_id}")
        dest.mkdir(parents=True, exist_ok=False)

        databases: dict[str, dict[str, Any]] = {}
        total_size = 0
        primary_digest = ""
        primary_schema = 0
        for domain, path in paths.items():
            domain_name = domain.lower()
            db_copy = dest / f"leviathan_{domain_name}.db"
            self._safe_sqlite_copy(path, db_copy)
            digest = hashlib.sha256(db_copy.read_bytes()).hexdigest()
            schema_version = self._schema_version(db_copy)
            size = db_copy.stat().st_size
            total_size += size
            databases[domain] = {
                "domain": domain,
                "sourcePath": str(path),
                "backupFile": db_copy.name,
                "sha256": digest,
                "sizeBytes": size,
                "schemaVersion": schema_version,
            }
            if domain == "CONTROL":
                primary_digest = digest
                primary_schema = schema_version
                # Legacy-compatible primary copy name for older restore tools.
                shutil.copy2(db_copy, dest / "leviathan.db")

        # If only one path (legacy mode), also name it leviathan.db
        if len(paths) == 1:
            only = next(iter(paths.values()))
            db_copy = dest / "leviathan.db"
            if not db_copy.is_file():
                self._safe_sqlite_copy(only, db_copy)
                primary_digest = hashlib.sha256(db_copy.read_bytes()).hexdigest()
                primary_schema = self._schema_version(db_copy)
                total_size = db_copy.stat().st_size

        artifacts_copied = 0
        artifacts_included = False
        art_src = self.artifacts_root
        if art_src.is_dir():
            art_dest = dest / "artifacts"
            shutil.copytree(art_src, art_dest)
            artifacts_copied = sum(1 for p in art_dest.rglob("*") if p.is_file())
            artifacts_included = True

        control_copy = dest / "leviathan_control.db"
        if not control_copy.is_file():
            control_copy = dest / "leviathan.db"
        # BACKUP-001: dataset metadata / file refs live in KNOWLEDGE after 3-DB cutover.
        knowledge_copy = dest / "leviathan_knowledge.db"
        inventory_db = knowledge_copy if knowledge_copy.is_file() else control_copy
        inventory_source = "KNOWLEDGE" if knowledge_copy.is_file() else "CONTROL_LEGACY"
        inventory = self._build_corpus_inventory(
            inventory_db if inventory_db.is_file() else dest / "leviathan.db"
        )
        corpus_files_included = False
        backup_kind = BACKUP_KIND_METADATA_ONLY
        is_complete = False

        if include_corpus and self.corpus_root is not None and self.corpus_root.is_dir():
            corpus_dest = dest / "corpus"
            copied = 0
            for entry in inventory:
                rel = entry.get("relativePath") or ""
                src = Path(entry.get("absolutePath") or "")
                if not src.is_file():
                    continue
                target = corpus_dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                entry["includedInBackup"] = True
                entry["backupRelativePath"] = str(Path("corpus") / rel)
                copied += 1
            for path in self.corpus_root.rglob("*"):
                if not path.is_file():
                    continue
                rel = _rel_or_abs(path, self.corpus_root)
                if any(e.get("relativePath") == rel for e in inventory):
                    continue
                try:
                    file_hash = _sha256_file(path)
                    size = path.stat().st_size
                except OSError:
                    continue
                target = corpus_dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                inventory.append(
                    {
                        "relativePath": rel,
                        "absolutePath": str(path),
                        "sha256": file_hash,
                        "sizeBytes": size,
                        "presentAtBackup": True,
                        "includedInBackup": True,
                        "backupRelativePath": str(Path("corpus") / rel),
                        "source": "corpus_tree",
                    }
                )
                copied += 1
            if copied > 0:
                corpus_files_included = True
                backup_kind = BACKUP_KIND_FULL_WITH_CORPUS
                is_complete = True
        else:
            for entry in inventory:
                entry["includedInBackup"] = False
            backup_kind = BACKUP_KIND_METADATA_ONLY
            corpus_files_included = False
            is_complete = False

        meta: dict[str, Any] = {}
        if note:
            meta["note"] = note
        meta["includeCorpusRequested"] = bool(include_corpus)
        meta["corpusRoot"] = str(self.corpus_root) if self.corpus_root else None
        meta["canonicalDatabaseCount"] = len(databases) or 1
        meta["corpusInventorySourceDomain"] = inventory_source
        meta["crossFileRestoreIsNotAtomic"] = True

        manifest = BackupManifest(
            backup_id=backup_id,
            created_at=utc_now(),
            database_path=str(dest / "leviathan.db"),
            database_sha256=primary_digest,
            size_bytes=total_size,
            schema_version=primary_schema,
            artifacts_copied=artifacts_copied,
            metadata=meta,
            backup_kind=backup_kind,
            corpus_files_included=corpus_files_included,
            artifacts_included=artifacts_included,
            is_complete_data_snapshot=is_complete,
            corpus_inventory=inventory,
            missing_corpus_files=[],
            databases=databases,
            backup_set_complete=len(databases) == 3 or len(paths) == 1,
        )
        (dest / "manifest.json").write_text(
            json.dumps(manifest.public_dict(), indent=2),
            encoding="utf-8",
        )
        return manifest

    def _canonical_paths(self) -> dict[str, Path]:
        if self.database_paths is not None:
            return {
                "CONTROL": Path(self.database_paths.control),
                "KNOWLEDGE": Path(self.database_paths.knowledge),
                "MARKET": Path(self.database_paths.market),
            }
        return {"CONTROL": Path(self.database_path)}

    def restore(
        self,
        backup_id: str,
        *,
        confirm: bool = False,
        maintenance_boundary: bool = False,
        inject_crash_after: str | None = None,
    ) -> BackupManifest:
        """Restore a backup set with durable journaling for three-DB cutover.

        BACKUP-002: cross-file replace is not atomic — phases/journal expose
        OLD_SET_ACTIVE / NEW_SET_ACTIVE / RECOVERY_REQUIRED.
        BACKUP-003: live DB files are only replaced when
        ``maintenance_boundary=True``.
        ``inject_crash_after`` is test-only (``before_cutover``, ``after_CONTROL``, …).
        """
        if not confirm:
            raise BackupError("Restore refused: confirm=true is required")
        if not maintenance_boundary:
            raise BackupError(
                "Restore refused: maintenance_boundary=true is required — "
                "refusing to replace DB files under live connections"
            )
        dest = self.backup_root / backup_id
        manifest_path = dest / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError(f"Backup not found: {backup_id}")

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        databases = dict(data.get("databases") or {})
        live_paths = self._canonical_paths()
        journal_path = self.backup_root / RESTORE_JOURNAL_NAME
        crash_at = (inject_crash_after or "").strip() or None

        def _maybe_crash(point: str) -> None:
            if crash_at and crash_at == point:
                # Persist RECOVERY_REQUIRED when mid-cutover; before_cutover stays OLD.
                raise BackupError(f"injected_crash:{point}")

        prior = self._read_restore_journal(journal_path)
        if prior and prior.get("state") == RESTORE_RECOVERY_REQUIRED:
            if prior.get("backup_id") == backup_id:
                return self._resume_restore_journal(journal_path, prior, data)
            raise BackupError(
                f"Restore recovery required for backup {prior.get('backup_id')} — "
                "refusing to start a different restore while mixed revisions may exist"
            )

        restore_terminal = RESTORE_OLD_SET_ACTIVE
        if databases:
            staged: dict[str, Path] = {}
            for domain in live_paths:
                entry = databases.get(domain)
                if not entry:
                    raise BackupError(
                        f"Backup set incomplete: missing {domain} member — refusing restore"
                    )
                db_copy = dest / str(entry.get("backupFile") or "")
                if not db_copy.is_file():
                    raise BackupError(
                        f"Backup set incomplete: {domain} file missing — refusing restore"
                    )
                expected = str(entry.get("sha256") or "")
                actual = hashlib.sha256(db_copy.read_bytes()).hexdigest()
                if expected and actual != expected:
                    raise BackupError(f"{domain} backup hash mismatch — refusing restore")
                staged[domain] = db_copy

            journal: dict[str, Any] = {
                "backup_id": backup_id,
                "started_at": utc_now(),
                "state": RESTORE_OLD_SET_ACTIVE,
                "phase": "VERIFIED",
                "domains": list(live_paths.keys()),
                "replaced": [],
                "pending": list(live_paths.keys()),
                "truth": {
                    "crossFileRestoreIsNotAtomic": True,
                    "mixedRevisionsMustNotResumeNormally": True,
                },
            }
            self._write_restore_journal(journal_path, journal)
            _maybe_crash("before_cutover")

            try:
                staged_live: dict[str, Path] = {}
                for domain, live in live_paths.items():
                    live.parent.mkdir(parents=True, exist_ok=True)
                    pre = live.with_suffix(".pre-restore")
                    if live.is_file():
                        shutil.copy2(live, pre)
                    tmp = live.with_suffix(".restore-tmp")
                    shutil.copy2(staged[domain], tmp)
                    staged_live[domain] = tmp
                journal["phase"] = "FILES_STAGED"
                journal["state"] = RESTORE_OLD_SET_ACTIVE
                self._write_restore_journal(journal_path, journal)

                for domain, live in live_paths.items():
                    journal["phase"] = f"REPLACING_{domain}"
                    journal["state"] = RESTORE_RECOVERY_REQUIRED
                    self._write_restore_journal(journal_path, journal)
                    staged_live[domain].replace(live)
                    journal.setdefault("replaced", []).append(domain)
                    journal["pending"] = [d for d in journal["pending"] if d != domain]
                    self._write_restore_journal(journal_path, journal)
                    _maybe_crash(f"after_{domain}")

                journal["phase"] = "NEW_SET_ACTIVE"
                journal["state"] = RESTORE_NEW_SET_ACTIVE
                journal["completed_at"] = utc_now()
                self._write_restore_journal(journal_path, journal)
            except BackupError as exc:
                # Crash injection or explicit refuse mid-cutover.
                if "injected_crash:" in str(exc):
                    cur = self._read_restore_journal(journal_path) or journal
                    # before_cutover: still OLD_SET_ACTIVE; after_* already RECOVERY_REQUIRED
                    if crash_at and crash_at.startswith("after_"):
                        cur["state"] = RESTORE_RECOVERY_REQUIRED
                        cur["error"] = str(exc)[:500]
                        cur["failed_at"] = utc_now()
                        self._write_restore_journal(journal_path, cur)
                    raise
                raise
            except Exception as exc:
                journal["state"] = RESTORE_RECOVERY_REQUIRED
                journal["error"] = str(exc)[:500]
                journal["failed_at"] = utc_now()
                self._write_restore_journal(journal_path, journal)
                raise BackupError(
                    f"Restore interrupted — state={RESTORE_RECOVERY_REQUIRED}: {exc}"
                ) from exc

            primary_digest = str(
                databases.get("CONTROL", {}).get("sha256") or data.get("database_sha256") or ""
            )
            primary_schema = int(
                databases.get("CONTROL", {}).get("schemaVersion") or data.get("schema_version") or 0
            )
            total_size = sum(int(v.get("sizeBytes") or 0) for v in databases.values())
            backup_set_complete = True
            restore_terminal = RESTORE_NEW_SET_ACTIVE
        else:
            # Legacy single-DB backup compatibility.
            db_copy = dest / "leviathan.db"
            if not db_copy.is_file():
                raise BackupError(f"Backup not found: {backup_id}")
            expected = str(data.get("database_sha256") or "")
            actual = hashlib.sha256(db_copy.read_bytes()).hexdigest()
            if expected and actual != expected:
                raise BackupError("Backup database hash mismatch — refusing restore")
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.database_path.with_suffix(".restore-tmp")
            shutil.copy2(db_copy, tmp)
            tmp.replace(self.database_path)
            primary_digest = actual
            primary_schema = int(data.get("schema_version") or 0)
            total_size = int(data.get("size_bytes") or db_copy.stat().st_size)
            backup_set_complete = False
            databases = {}
            restore_terminal = RESTORE_NEW_SET_ACTIVE
            if journal_path.is_file():
                journal_path.unlink(missing_ok=True)

        art_src = dest / "artifacts"
        if art_src.is_dir():
            if self.artifacts_root.exists():
                shutil.rmtree(self.artifacts_root)
            shutil.copytree(art_src, self.artifacts_root)

        backup_kind = str(
            data.get("backupKind")
            or (data.get("truth") or {}).get("backupKind")
            or BACKUP_KIND_METADATA_ONLY
        )
        corpus_included = bool(
            data.get("corpusFilesIncluded")
            if "corpusFilesIncluded" in data
            else (data.get("truth") or {}).get("corpusFilesIncluded")
        )
        inventory = list(data.get("corpusInventory") or [])

        corpus_backup = dest / "corpus"
        if corpus_included and corpus_backup.is_dir() and self.corpus_root is not None:
            self.corpus_root.mkdir(parents=True, exist_ok=True)
            for path in corpus_backup.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(corpus_backup)
                target = self.corpus_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)

        missing = self._detect_missing_corpus_files(
            inventory=inventory,
            corpus_included_in_backup=corpus_included,
            backup_corpus_dir=corpus_backup if corpus_backup.is_dir() else None,
        )

        is_complete = bool(data.get("isCompleteDataSnapshot")) and not missing
        if backup_kind == BACKUP_KIND_METADATA_ONLY:
            is_complete = False

        meta = {**(data.get("metadata") or {}), "restored_at": utc_now()}
        if missing:
            meta["missingCorpusFilesDetected"] = True
        meta["restoreTerminalState"] = restore_terminal
        meta["crossFileRestoreIsNotAtomic"] = True
        meta["maintenanceBoundaryHonored"] = True
        meta["corpusInventorySourceDomain"] = (data.get("metadata") or {}).get(
            "corpusInventorySourceDomain", "KNOWLEDGE"
        )

        if restore_terminal == RESTORE_NEW_SET_ACTIVE and journal_path.is_file():
            try:
                done = self._read_restore_journal(journal_path) or {}
                done["state"] = RESTORE_NEW_SET_ACTIVE
                done["cleared_for_runtime"] = True
                self._write_restore_journal(journal_path, done)
            except OSError:
                pass

        return BackupManifest(
            backup_id=str(data["backup_id"]),
            created_at=str(data["created_at"]),
            database_path=str(self.database_path),
            database_sha256=primary_digest,
            size_bytes=total_size,
            schema_version=primary_schema,
            artifacts_copied=int(data.get("artifacts_copied") or 0),
            metadata=meta,
            backup_kind=backup_kind,
            corpus_files_included=corpus_included,
            artifacts_included=bool(
                data.get("artifactsIncluded")
                if "artifactsIncluded" in data
                else int(data.get("artifacts_copied") or 0) > 0
            ),
            is_complete_data_snapshot=is_complete,
            corpus_inventory=inventory,
            missing_corpus_files=missing,
            databases=databases,
            backup_set_complete=backup_set_complete,
        )

    def restore_status(self) -> dict[str, Any]:
        """Operator-visible restore journal — mixed revisions ⇒ RECOVERY_REQUIRED."""
        journal_path = self.backup_root / RESTORE_JOURNAL_NAME
        journal = self._read_restore_journal(journal_path)
        if not journal:
            return {
                "state": RESTORE_OLD_SET_ACTIVE,
                "active": False,
                "truth": {"crossFileRestoreIsNotAtomic": True},
            }
        state = str(journal.get("state") or RESTORE_RECOVERY_REQUIRED)
        return {
            "state": state,
            "active": state == RESTORE_RECOVERY_REQUIRED,
            "journal": journal,
            "truth": {
                "crossFileRestoreIsNotAtomic": True,
                "mixedRevisionsMustNotResumeNormally": state == RESTORE_RECOVERY_REQUIRED,
            },
        }

    def _write_restore_journal(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # fsync via replace of fully written temp file
        tmp.replace(path)

    def _read_restore_journal(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def _resume_restore_journal(
        self,
        journal_path: Path,
        journal: dict[str, Any],
        data: dict[str, Any],
    ) -> BackupManifest:
        """Finish pending domain replacements after crash; refuse mixed silent resume."""
        backup_id = str(journal.get("backup_id") or "")
        dest = self.backup_root / backup_id
        databases = dict(data.get("databases") or {})
        live_paths = self._canonical_paths()
        pending = list(journal.get("pending") or [])
        if not pending:
            journal["state"] = RESTORE_NEW_SET_ACTIVE
            journal["phase"] = "RESUMED_COMPLETE"
            journal["completed_at"] = utc_now()
            self._write_restore_journal(journal_path, journal)
        else:
            for domain in list(pending):
                entry = databases.get(domain)
                live = live_paths.get(domain)
                if not entry or live is None:
                    raise BackupError(
                        f"Cannot resume restore: missing {domain} — {RESTORE_RECOVERY_REQUIRED}"
                    )
                db_copy = dest / str(entry.get("backupFile") or "")
                if not db_copy.is_file():
                    raise BackupError(
                        f"Cannot resume restore: {domain} backup file missing — "
                        f"{RESTORE_RECOVERY_REQUIRED}"
                    )
                journal["phase"] = f"RESUMING_{domain}"
                journal["state"] = RESTORE_RECOVERY_REQUIRED
                self._write_restore_journal(journal_path, journal)
                tmp = live.with_suffix(".restore-tmp")
                shutil.copy2(db_copy, tmp)
                tmp.replace(live)
                journal.setdefault("replaced", []).append(domain)
                journal["pending"] = [d for d in journal["pending"] if d != domain]
                self._write_restore_journal(journal_path, journal)
            journal["state"] = RESTORE_NEW_SET_ACTIVE
            journal["phase"] = "RESUMED_COMPLETE"
            journal["completed_at"] = utc_now()
            self._write_restore_journal(journal_path, journal)

        primary_digest = str(
            databases.get("CONTROL", {}).get("sha256") or data.get("database_sha256") or ""
        )
        primary_schema = int(
            databases.get("CONTROL", {}).get("schemaVersion") or data.get("schema_version") or 0
        )
        total_size = sum(int(v.get("sizeBytes") or 0) for v in databases.values())
        meta = {**(data.get("metadata") or {}), "restored_at": utc_now()}
        meta["restoreTerminalState"] = RESTORE_NEW_SET_ACTIVE
        meta["restoreResumed"] = True
        meta["crossFileRestoreIsNotAtomic"] = True
        meta["maintenanceBoundaryHonored"] = True
        return BackupManifest(
            backup_id=str(data["backup_id"]),
            created_at=str(data["created_at"]),
            database_path=str(self.database_path),
            database_sha256=primary_digest,
            size_bytes=total_size or int(data.get("size_bytes") or 0),
            schema_version=primary_schema,
            artifacts_copied=int(data.get("artifacts_copied") or 0),
            metadata=meta,
            backup_kind=str(data.get("backupKind") or BACKUP_KIND_METADATA_ONLY),
            corpus_files_included=bool(data.get("corpusFilesIncluded")),
            artifacts_included=bool(data.get("artifactsIncluded")),
            is_complete_data_snapshot=False,
            corpus_inventory=list(data.get("corpusInventory") or []),
            missing_corpus_files=[],
            databases=databases,
            backup_set_complete=True,
        )

    def _manifest_from_dict(self, data: dict[str, Any]) -> BackupManifest:
        truth = dict(data.get("truth") or {})
        return BackupManifest(
            backup_id=str(data["backup_id"]),
            created_at=str(data["created_at"]),
            database_path=str(data["database_path"]),
            database_sha256=str(data["database_sha256"]),
            size_bytes=int(data["size_bytes"]),
            schema_version=int(data.get("schema_version") or 0),
            artifacts_copied=int(data.get("artifacts_copied") or 0),
            metadata=dict(data.get("metadata") or {}),
            backup_kind=str(
                data.get("backupKind") or truth.get("backupKind") or BACKUP_KIND_METADATA_ONLY
            ),
            corpus_files_included=bool(
                data.get("corpusFilesIncluded")
                if "corpusFilesIncluded" in data
                else truth.get("corpusFilesIncluded", False)
            ),
            artifacts_included=bool(
                data.get("artifactsIncluded")
                if "artifactsIncluded" in data
                else int(data.get("artifacts_copied") or 0) > 0
            ),
            is_complete_data_snapshot=bool(
                data.get("isCompleteDataSnapshot")
                if "isCompleteDataSnapshot" in data
                else truth.get("isCompleteDataSnapshot", False)
            ),
            corpus_inventory=list(data.get("corpusInventory") or []),
            missing_corpus_files=list(data.get("missingCorpusFiles") or []),
            databases=dict(data.get("databases") or {}),
            backup_set_complete=bool(
                data.get("backupSetComplete")
                if "backupSetComplete" in data
                else truth.get("backupSetComplete", False)
            ),
        )

    def _build_corpus_inventory(self, db_path: Path) -> list[dict[str, Any]]:
        """Relative inventory of dataset/corpus paths referenced by the DB."""
        paths: list[tuple[str, str]] = []  # (absolute, source)
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                for sql, source in (
                    ("SELECT storage_path AS p FROM dataset_versions WHERE storage_path IS NOT NULL", "dataset_versions.storage_path"),
                    ("SELECT raw_path AS p FROM datasets WHERE raw_path IS NOT NULL", "datasets.raw_path"),
                    ("SELECT path AS p FROM dataset_files WHERE path IS NOT NULL", "dataset_files.path"),
                ):
                    try:
                        for row in conn.execute(sql):
                            raw = row["p"]
                            if raw:
                                paths.append((str(raw), source))
                    except sqlite3.Error:
                        continue
        except sqlite3.Error:
            return []

        inventory: list[dict[str, Any]] = []
        seen: set[str] = set()
        for abs_str, source in paths:
            path = Path(abs_str)
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            rel = _rel_or_abs(path, self.corpus_root) if self.corpus_root else str(path)
            present = path.is_file()
            entry: dict[str, Any] = {
                "relativePath": rel,
                "absolutePath": str(path),
                "sha256": None,
                "sizeBytes": None,
                "presentAtBackup": present,
                "includedInBackup": False,
                "source": source,
            }
            if present:
                try:
                    entry["sha256"] = _sha256_file(path)
                    entry["sizeBytes"] = path.stat().st_size
                except OSError:
                    entry["presentAtBackup"] = False
            inventory.append(entry)
        return inventory

    def _detect_missing_corpus_files(
        self,
        *,
        inventory: list[dict[str, Any]],
        corpus_included_in_backup: bool,
        backup_corpus_dir: Path | None,
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for entry in inventory:
            rel = str(entry.get("relativePath") or "")
            abs_path = Path(str(entry.get("absolutePath") or ""))
            live_ok = abs_path.is_file()
            if self.corpus_root is not None and rel and not live_ok:
                candidate = self.corpus_root / rel
                live_ok = candidate.is_file()
                if live_ok:
                    abs_path = candidate

            in_backup = False
            if corpus_included_in_backup and backup_corpus_dir is not None and rel:
                in_backup = (backup_corpus_dir / rel).is_file()

            if live_ok:
                continue
            # File missing on live disk after restore
            reason = "missing_after_metadata_only_restore"
            if corpus_included_in_backup and not in_backup:
                reason = "listed_in_inventory_but_absent_from_backup_corpus"
            elif not entry.get("presentAtBackup", True):
                reason = "missing_at_backup_time"
            missing.append(
                {
                    "relativePath": rel,
                    "absolutePath": str(abs_path),
                    "sha256": entry.get("sha256"),
                    "reason": reason,
                    "includedInBackup": bool(entry.get("includedInBackup")),
                }
            )
        return missing

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
