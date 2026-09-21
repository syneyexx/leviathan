"""Full workspace backup/restore (distinct from SQLite settings backup).

The existing ``POST /api/settings/backup`` path remains DB-only.
This module creates a separately named full workspace archive with inventory,
manifest (schema/app version, relative paths, hashes, include/exclude),
progress/cancel, concurrent change detection, path-safe extraction, and
explicit secrets handling.

Restore always extracts to an isolated target first; activation of the live
workspace is a separate, explicit step after integrity validation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

ARCHIVE_FORMAT = "hades.workspace_archive.v1"
MIN_SUPPORTED_FORMAT = "hades.workspace_archive.v1"
from settings_secrets import SECRET_SETTING_KEYS
SECRET_FILENAME_MARKERS = ("secret", "credential", ".env", "api_key", "apikey", "token")

# Large / regenerable categories — selectable; excluded by default.
OPTIONAL_LARGE_CATEGORIES = frozenset({"models", "caches", "deps", "uploads"})

# Core categories owned by HADES — included by default.
# Sibling durable stores under data_root (embeddings, effect ledger, claims,
# leases, voice, coding jobs) are included so a "full workspace" restore is honest.
CORE_CATEGORIES = frozenset(
    {
        "database",
        "evidence",
        "artifacts",
        "plugins",
        "knowledge",
        "manifests",
        "embeddings",
        "effect_ledger",
        "claims",
        "leases",
        "voice",
        "coding_jobs",
    }
)

# A full workspace archive is not truthful without the primary HADES database.
# Other core categories are feature-owned and may legitimately not exist yet.
MANDATORY_CATEGORIES = frozenset({"database"})

DEFAULT_EXCLUDE = frozenset(OPTIONAL_LARGE_CATEGORIES)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str = "wsbak") -> str:
    return f"{prefix}_{uuid4().hex[:14]}"


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_secret_path(rel: str) -> bool:
    lowered = rel.replace("\\", "/").lower()
    name = Path(lowered).name
    return any(marker in name for marker in SECRET_FILENAME_MARKERS)


@dataclass
class BackupProgress:
    job_id: str
    phase: str = "queued"
    bytes_done: int = 0
    bytes_total: int = 0
    files_done: int = 0
    files_total: int = 0
    message: str = ""
    error: str | None = None
    cancelled: bool = False
    archive_path: str | None = None
    manifest: dict[str, Any] | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "phase": self.phase,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "message": self.message,
            "error": self.error,
            "cancelled": self.cancelled,
            "archive_path": self.archive_path,
            "manifest": self.manifest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "kind": "full_workspace_archive",
            "not_db_only": True,
        }


class BackupCancelled(Exception):
    """Raised when a backup/restore job is cancelled."""


class WorkspaceBackupService:
    """Create and restore full workspace archives under a data root."""

    def __init__(
        self,
        data_root: Path,
        *,
        db_path: Path | None = None,
        app_version: str = "0.4.1",
        schema_version: int = 1,
        archive_dir: Path | None = None,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.db_path = Path(db_path or (self.data_root / "hades.db")).expanduser().resolve()
        self.app_version = app_version
        self.schema_version = int(schema_version)
        self.archive_dir = Path(archive_dir or (self.data_root / "workspace_archives")).expanduser().resolve()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, BackupProgress] = {}
        self._cancel: set[str] = set()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ inventory

    def inventory(
        self,
        *,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        include_secrets: bool = False,
    ) -> dict[str, Any]:
        include_set = set(include) if include is not None else set(CORE_CATEGORIES)
        exclude_set = set(exclude) if exclude is not None else set(DEFAULT_EXCLUDE)
        # Optional large categories only when explicitly included.
        for cat in OPTIONAL_LARGE_CATEGORIES:
            if cat not in include_set:
                exclude_set.add(cat)
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        missing_required: list[dict[str, str]] = []
        for category, paths in self._category_roots().items():
            if category in exclude_set or category not in include_set:
                continue
            for root in paths:
                if not root.exists():
                    if category in MANDATORY_CATEGORIES:
                        missing_required.append({"category": category, "path": str(root)})
                    continue
                if root.is_file():
                    for entry in self._file_entry(category, root, include_secrets=include_secrets):
                        rel = entry["relative_path"]
                        if rel in seen:
                            continue
                        seen.add(rel)
                        entries.append(entry)
                else:
                    for path in sorted(root.rglob("*")):
                        if path.is_file() and not path.is_symlink():
                            for entry in self._file_entry(category, path, include_secrets=include_secrets):
                                rel = entry["relative_path"]
                                if rel in seen:
                                    continue
                                seen.add(rel)
                                entries.append(entry)
        total_bytes = sum(int(e["size_bytes"]) for e in entries if e.get("included"))
        return {
            "format": ARCHIVE_FORMAT,
            "data_root": str(self.data_root),
            "db_path": str(self.db_path),
            "include": sorted(include_set - exclude_set),
            "exclude": sorted(exclude_set),
            "include_secrets": include_secrets,
            "entries": entries,
            "included_count": sum(1 for e in entries if e.get("included")),
            "excluded_count": sum(1 for e in entries if not e.get("included")),
            "missing_required": missing_required,
            "total_bytes": total_bytes,
            "note": "This inventory is for a full workspace archive, not the DB-only settings backup.",
        }

    def _category_roots(self) -> dict[str, list[Path]]:
        return {
            "database": [self.db_path],
            "evidence": [self.data_root / "evidence"],
            "artifacts": [self.data_root / "artifacts"],
            "plugins": [self.data_root / "plugins"],
            "knowledge": [self.data_root / "knowledge"],
            "manifests": [
                self.data_root / "plugins" / "packages",
            ],
            "embeddings": [self.data_root / "embedding_index.sqlite3"],
            "effect_ledger": [self.data_root / "effect_ledger.db"],
            "claims": [self.data_root / "claims.sqlite"],
            "leases": [self.data_root / "execution_leases.json"],
            "voice": [self.data_root / "voice"],
            "coding_jobs": [self.data_root / "coding_jobs"],
            "uploads": [self.data_root / "uploads"],
            "models": [self.data_root / "models"],
            "caches": [self.data_root / "caches", self.data_root / ".cache"],
            "deps": [self.data_root / "deps", self.data_root / "vendor"],
        }

    def _rel_to_root(self, path: Path) -> str:
        path = path.resolve()
        try:
            return path.relative_to(self.data_root).as_posix()
        except ValueError:
            # DB may live beside data_root; keep a stable archive name.
            if path == self.db_path:
                return "hades.db"
            return f"_external/{path.name}"

    def _file_entry(self, category: str, path: Path, *, include_secrets: bool) -> list[dict[str, Any]]:
        rel = self._rel_to_root(path)
        secret = _is_secret_path(rel) or (category == "database" and False)
        included = True
        reason = None
        if secret and not include_secrets:
            included = False
            reason = "secret_excluded"
        try:
            size = path.stat().st_size
            mtime = path.stat().st_mtime_ns
        except OSError as exc:
            return [{
                "category": category,
                "relative_path": rel,
                "included": False,
                "reason": f"stat_failed:{exc}",
                "size_bytes": 0,
                "mtime_ns": 0,
                "sha256": None,
                "is_secret": secret,
            }]
        return [{
            "category": category,
            "relative_path": rel,
            "absolute_path": str(path),
            "included": included,
            "reason": reason,
            "size_bytes": size,
            "mtime_ns": mtime,
            "sha256": None,  # filled during archive create
            "is_secret": secret,
        }]

    # ------------------------------------------------------------------ jobs

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._cancel.add(job_id)
            job = self._jobs.get(job_id)
            if job:
                job.cancelled = True
                job.phase = "cancelled"
                job.message = "cancelled_by_user"
                job.updated_at = utc_now()
                return job.to_dict()
        return {"job_id": job_id, "phase": "cancelled", "cancelled": True}

    def _check_cancel(self, job_id: str) -> None:
        if job_id in self._cancel:
            raise BackupCancelled(job_id)

    def _update(self, job: BackupProgress, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = utc_now()

    # ------------------------------------------------------------------ backup

    def create_archive(
        self,
        *,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        include_secrets: bool = False,
        redact_settings_secrets: bool = True,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        job_id = new_id()
        job = BackupProgress(job_id=job_id, phase="inventory")
        with self._lock:
            self._jobs[job_id] = job

        try:
            inv = self.inventory(include=include, exclude=exclude, include_secrets=include_secrets)
            missing_required = list(inv.get("missing_required") or [])
            if missing_required:
                categories = ",".join(sorted({str(item.get("category") or "unknown") for item in missing_required}))
                raise FileNotFoundError(f"required backup source missing: {categories}")
            included = [e for e in inv["entries"] if e.get("included")]
            self._update(
                job,
                phase="hashing",
                files_total=len(included),
                bytes_total=sum(int(e["size_bytes"]) for e in included),
                message="inventory_ready",
            )
            if progress_cb:
                progress_cb(job.to_dict())

            # Pre-hash for concurrent change detection.
            pre_hashes: dict[str, str] = {}
            for entry in included:
                self._check_cancel(job_id)
                path = Path(entry["absolute_path"])
                digest = sha256_file(path)
                entry["sha256"] = digest
                pre_hashes[entry["relative_path"]] = digest
                job.files_done += 1
                job.bytes_done += int(entry["size_bytes"])
                job.updated_at = utc_now()

            self._update(job, phase="packing", files_done=0, bytes_done=0, message="writing_archive")
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            archive_path = self.archive_dir / f"hades-workspace-{stamp}-{job_id[-8:]}.hadesws.zip"

            changed: list[str] = []
            missing: list[str] = []
            packed: list[dict[str, Any]] = []

            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for entry in included:
                    self._check_cancel(job_id)
                    rel = entry["relative_path"]
                    path = Path(entry["absolute_path"])
                    if not path.is_file():
                        missing.append(rel)
                        continue
                    try:
                        mtime = path.stat().st_mtime_ns
                        size = path.stat().st_size
                    except OSError:
                        missing.append(rel)
                        continue
                    digest = sha256_file(path)
                    if digest != pre_hashes.get(rel) or mtime != entry.get("mtime_ns") or size != entry.get("size_bytes"):
                        changed.append(rel)
                        # Still pack the current bytes but flag the race.
                        entry["sha256"] = digest
                        entry["mtime_ns"] = mtime
                        entry["size_bytes"] = size
                        entry["concurrent_change"] = True
                    arcname = f"workspace/{rel}"
                    if path == self.db_path and redact_settings_secrets and not include_secrets:
                        # Consistent DB backup into a temp redacted copy when possible.
                        packed_bytes = self._sqlite_backup_bytes(path, redact_secrets=True)
                        zf.writestr(arcname, packed_bytes)
                        entry["sha256"] = sha256_bytes(packed_bytes)
                        entry["size_bytes"] = len(packed_bytes)
                        entry["secrets_policy"] = "redacted_in_settings_table"
                    else:
                        zf.write(path, arcname)
                        if include_secrets and entry.get("is_secret"):
                            entry["secrets_policy"] = "included_explicit"
                        elif entry.get("is_secret"):
                            entry["secrets_policy"] = "included_as_file"
                        else:
                            entry["secrets_policy"] = "not_secret"
                    packed.append({k: v for k, v in entry.items() if k != "absolute_path"})
                    job.files_done += 1
                    job.bytes_done += int(entry["size_bytes"])
                    job.updated_at = utc_now()
                    if progress_cb and job.files_done % 5 == 0:
                        progress_cb(job.to_dict())

                excluded_entries = [
                    {k: v for k, v in e.items() if k != "absolute_path"}
                    for e in inv["entries"]
                    if not e.get("included")
                ]
                manifest = {
                    "format": ARCHIVE_FORMAT,
                    "kind": "full_workspace_archive",
                    "not_db_only": True,
                    "created_at": utc_now(),
                    "app_version": self.app_version,
                    "schema_version": self.schema_version,
                    "job_id": job_id,
                    "include": inv["include"],
                    "exclude": inv["exclude"],
                    "include_secrets": include_secrets,
                    "secrets_policy": (
                        "explicit_include" if include_secrets else "exclude_secret_files_and_redact_db_settings"
                    ),
                    "files": packed,
                    "excluded_files": excluded_entries,
                    "concurrent_changes": changed,
                    "missing_at_pack": missing,
                    "integrity": {
                        "file_count": len(packed),
                        "bytes": sum(int(f["size_bytes"]) for f in packed),
                        "manifest_sha256_of_paths": sha256_bytes(
                            json.dumps([(f["relative_path"], f["sha256"]) for f in packed], sort_keys=True).encode()
                        ),
                    },
                    "db_only_settings_backup_note": (
                        "POST /api/settings/backup remains a separate SQLite-only backup; "
                        "never present that path as a full workspace backup."
                    ),
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

            if missing or changed:
                self._update(
                    job,
                    phase="completed_with_warnings",
                    archive_path=str(archive_path),
                    manifest=manifest,
                    message="archive_written_with_concurrent_or_missing",
                )
            else:
                self._update(
                    job,
                    phase="completed",
                    archive_path=str(archive_path),
                    manifest=manifest,
                    message="archive_written",
                )
            result = job.to_dict()
            if progress_cb:
                progress_cb(result)
            return result
        except BackupCancelled:
            self._update(job, phase="cancelled", cancelled=True, message="cancelled", error="cancelled")
            return job.to_dict()
        except Exception as exc:
            self._update(job, phase="failed", error=str(exc), message="failed")
            return job.to_dict()

    def _sqlite_backup_bytes(self, source: Path, *, redact_secrets: bool) -> bytes:
        """Consistent SQLite backup; optionally redact known secret settings keys."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            src = sqlite3.connect(str(source), timeout=10)
            dst = sqlite3.connect(str(tmp_path), timeout=10)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            if redact_secrets:
                conn = sqlite3.connect(str(tmp_path), timeout=10)
                try:
                    # Prefer app_settings (HADES core); fall back to settings if present.
                    for table in ("app_settings", "settings"):
                        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                        if "key" in cols and "value" in cols:
                            for key in SECRET_SETTING_KEYS:
                                conn.execute(
                                    f"UPDATE {table} SET value=? WHERE key=?",
                                    ("***", key),
                                )
                    # Scoped overrides and history can retain old/new secret values.
                    override_cols = {
                        r[1] for r in conn.execute("PRAGMA table_info(setting_overrides)").fetchall()
                    }
                    if {"key", "value"}.issubset(override_cols):
                        for key in SECRET_SETTING_KEYS:
                            conn.execute(
                                "UPDATE setting_overrides SET value=? WHERE key=?",
                                ('"***"', key),
                            )
                    history_cols = {
                        r[1] for r in conn.execute("PRAGMA table_info(setting_history)").fetchall()
                    }
                    if {"key", "old_value", "new_value"}.issubset(history_cols):
                        for key in SECRET_SETTING_KEYS:
                            conn.execute(
                                "UPDATE setting_history SET old_value=?, new_value=? WHERE key=?",
                                ('"***"', '"***"', key),
                            )
                    conn.commit()
                except sqlite3.Error:
                    # Fail closed: never return a database that claimed secrets were removed.
                    raise
                finally:
                    conn.close()
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ restore

    def restore_to_isolated(
        self,
        archive_path: Path,
        target_dir: Path | None = None,
        *,
        expected_app_version: str | None = None,
    ) -> dict[str, Any]:
        """Extract archive to an isolated directory and validate integrity.

        Never replaces the active workspace. Returns a concrete restore overview.
        """
        archive_path = Path(archive_path).expanduser().resolve()
        if not archive_path.is_file():
            return {
                "ok": False,
                "error": "archive_not_found",
                "path": str(archive_path),
                "active_workspace_untouched": True,
            }

        job_id = new_id("wsrst")
        job = BackupProgress(job_id=job_id, phase="validating_archive")
        with self._lock:
            self._jobs[job_id] = job

        target = Path(target_dir or (self.archive_dir / f"restore-{job_id}")).expanduser().resolve()
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        try:
            manifest = self._read_manifest(archive_path)
            if not manifest:
                raise ValueError("missing_or_invalid_manifest")
            if manifest.get("format") != ARCHIVE_FORMAT:
                # Older / unknown schema — report compatibility failure without touching active workspace.
                if str(manifest.get("format") or "").startswith("hades.workspace_archive."):
                    compat = "older_or_newer_schema"
                else:
                    compat = "unknown_format"
                self._update(job, phase="failed", error=f"incompatible_format:{compat}")
                return {
                    "ok": False,
                    "error": "incompatible_schema",
                    "compatibility": compat,
                    "manifest_format": manifest.get("format"),
                    "supported_format": ARCHIVE_FORMAT,
                    "active_workspace_untouched": True,
                    "job": job.to_dict(),
                }

            schema_v = int(manifest.get("schema_version") or 0)
            if schema_v > self.schema_version:
                self._update(job, phase="failed", error="schema_too_new")
                return {
                    "ok": False,
                    "error": "migration_incompatible",
                    "archive_schema_version": schema_v,
                    "host_schema_version": self.schema_version,
                    "active_workspace_untouched": True,
                    "job": job.to_dict(),
                }

            if expected_app_version and manifest.get("app_version") and manifest["app_version"] != expected_app_version:
                # Soft warning only — still allow isolated restore.
                pass

            self._update(job, phase="extracting", message=str(target))
            self.safe_extract_workspace_zip(archive_path, target)

            workspace_root = target / "workspace"
            if not workspace_root.is_dir():
                # Manifest-only extract failure
                raise ValueError("workspace_payload_missing")

            integrity = self._verify_extracted(workspace_root, manifest)
            overview = self._restore_overview(workspace_root, manifest, integrity)
            overview.update(
                {
                    "ok": integrity["ok"],
                    "job_id": job_id,
                    "isolated_target": str(target),
                    "workspace_root": str(workspace_root),
                    "active_workspace_untouched": True,
                    "activation_required": True,
                    "activation_performed": False,
                    "kind": "full_workspace_restore_preview",
                    "not_db_only": True,
                }
            )
            phase = "validated" if integrity["ok"] else "integrity_failed"
            self._update(job, phase=phase, manifest=manifest, message=phase, archive_path=str(archive_path))
            overview["job"] = job.to_dict()
            return overview
        except Exception as exc:
            # Failed restore must not damage active workspace — only clean isolated target optionally.
            self._update(job, phase="failed", error=str(exc))
            return {
                "ok": False,
                "error": str(exc),
                "isolated_target": str(target),
                "active_workspace_untouched": True,
                "job": job.to_dict(),
            }

    def activate_restored(
        self,
        isolated_workspace_root: Path,
        *,
        confirm: bool = False,
        backup_current: bool = True,
    ) -> dict[str, Any]:
        """Replace active data_root contents from a validated isolated restore.

        Requires confirm=True. Optionally snapshots the current workspace first.
        """
        if not confirm:
            return {"ok": False, "error": "confirm_required", "active_workspace_untouched": True}

        src = Path(isolated_workspace_root).expanduser().resolve()
        if not src.is_dir():
            return {"ok": False, "error": "isolated_root_missing", "active_workspace_untouched": True}

        # Safety: refuse if source looks incomplete (no db).
        if not (src / "hades.db").is_file() and not any(src.glob("*.db")):
            return {"ok": False, "error": "core_database_missing", "active_workspace_untouched": True}

        previous = None
        if backup_current and self.data_root.exists():
            previous = self.data_root.with_name(self.data_root.name + f".pre-restore-{new_id('prev')[-8:]}")
            if previous.exists():
                shutil.rmtree(previous)
            shutil.copytree(self.data_root, previous, dirs_exist_ok=True)

        # Replace category-by-category under data_root (not deleting unrelated host files outside).
        replaced: list[str] = []
        for item in src.iterdir():
            dest = self.data_root / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
            replaced.append(item.name)

        return {
            "ok": True,
            "replaced": replaced,
            "previous_snapshot": str(previous) if previous else None,
            "data_root": str(self.data_root),
            "kind": "full_workspace_activate",
        }

    def _read_manifest(self, archive_path: Path) -> dict[str, Any] | None:
        try:
            with zipfile.ZipFile(archive_path) as zf:
                raw = zf.read("manifest.json")
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def safe_extract_workspace_zip(archive_path: Path, destination: Path) -> None:
        """Path-validated extraction; rejects absolute paths, traversal, symlinks, and zip bombs."""
        from platform_services_core import max_archive_bytes, max_archive_files

        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            archive_file_limit = max_archive_files()
            if archive_file_limit is not None and len(members) > int(archive_file_limit):
                raise ValueError("Archief bevat te veel bestanden.")
            extracted = 0
            for member in members:
                raw = member.filename.replace("\\", "/")
                if not raw or raw.endswith("/"):
                    continue
                if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
                    raise ValueError("unsafe_absolute_path")
                if ".." in Path(raw).parts:
                    raise ValueError("unsafe_path_traversal")
                target = (destination / raw).resolve()
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise ValueError("unsafe_path_escape") from exc
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError("symlink_not_allowed")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        extracted += len(chunk)
                        archive_byte_limit = max_archive_bytes()
                        if archive_byte_limit is not None and extracted > int(archive_byte_limit):
                            raise ValueError("Uitgepakt archief overschrijdt de veiligheidslimiet.")
                        output.write(chunk)

    def _verify_extracted(self, workspace_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        missing: list[str] = []
        mismatch: list[str] = []
        corrupt: list[str] = []
        ok_files = 0
        for entry in manifest.get("files") or []:
            rel = entry.get("relative_path")
            if not rel:
                continue
            path = workspace_root / rel
            if not path.is_file():
                missing.append(rel)
                continue
            digest = sha256_file(path)
            expected = entry.get("sha256")
            if expected and digest != expected:
                corrupt.append(rel)
                continue
            size = path.stat().st_size
            if entry.get("size_bytes") is not None and int(entry["size_bytes"]) != size:
                mismatch.append(rel)
                continue
            ok_files += 1
        return {
            "ok": not missing and not mismatch and not corrupt,
            "verified_files": ok_files,
            "missing": missing,
            "changed_or_size_mismatch": mismatch,
            "corrupt_hash_mismatch": corrupt,
        }

    def _restore_overview(
        self,
        workspace_root: Path,
        manifest: dict[str, Any],
        integrity: dict[str, Any],
    ) -> dict[str, Any]:
        """Concrete product-facing restore overview (what will become available)."""
        db_candidates = list(workspace_root.glob("*.db"))
        has_db = bool(db_candidates)
        evidence = workspace_root / "evidence"
        artifacts = workspace_root / "artifacts"
        knowledge = workspace_root / "knowledge"
        plugins = workspace_root / "plugins"

        conversations = knowledge_sources = evidence_files = artifact_files = None
        core_functions: dict[str, Any] = {"database_openable": False}
        if has_db:
            db_path = db_candidates[0]
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                try:
                    def _count(table: str) -> int | None:
                        try:
                            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                        except sqlite3.Error:
                            return None

                    conversations = _count("conversations")
                    knowledge_sources = _count("knowledge_sources")
                    core_functions["database_openable"] = True
                    core_functions["settings_readable"] = _count("settings") is not None
                    core_functions["messages_readable"] = _count("messages") is not None
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                core_functions["database_error"] = str(exc)

        if evidence.exists():
            evidence_files = sum(1 for p in evidence.rglob("*") if p.is_file())
        if artifacts.exists():
            artifact_files = sum(1 for p in artifacts.rglob("*") if p.is_file())

        return {
            "overview": {
                "app_version": manifest.get("app_version"),
                "schema_version": manifest.get("schema_version"),
                "created_at": manifest.get("created_at"),
                "include": manifest.get("include"),
                "exclude": manifest.get("exclude"),
                "secrets_policy": manifest.get("secrets_policy"),
                "file_count": (manifest.get("integrity") or {}).get("file_count"),
                "conversations": conversations,
                "knowledge_sources": knowledge_sources,
                "evidence_files": evidence_files,
                "artifact_files": artifact_files,
                "plugins_present": plugins.is_dir(),
                "knowledge_present": knowledge.is_dir(),
            },
            "integrity": integrity,
            "core_functions": core_functions,
            "migration_compatible": int(manifest.get("schema_version") or 0) <= self.schema_version,
        }


# Module-level helper used by API wiring.
_default_service: WorkspaceBackupService | None = None
_default_lock = threading.Lock()


def get_workspace_backup_service(
    data_root: Path | None = None,
    *,
    db_path: Path | None = None,
    app_version: str = "0.4.1",
    schema_version: int = 1,
) -> WorkspaceBackupService:
    global _default_service
    with _default_lock:
        if _default_service is None or (data_root and Path(data_root).resolve() != _default_service.data_root):
            if data_root is None:
                data_root = Path(__file__).resolve().parent / "data"
            _default_service = WorkspaceBackupService(
                data_root,
                db_path=db_path,
                app_version=app_version,
                schema_version=schema_version,
            )
        return _default_service
