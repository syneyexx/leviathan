"""Tests for full workspace backup/restore (work package M)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from workspace_backup import ARCHIVE_FORMAT, WorkspaceBackupService


def _seed_workspace(root: Path) -> Database:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "hades.db"
    db = Database(str(db_path))
    db.initialize()
    conv = db.create_conversation("Backup Test Chat", model_id="local-model")
    db.add_message(conv["id"], "user", "hello workspace")
    db.add_message(conv["id"], "assistant", "hi there")
    db.update_settings({"lm_studio_api_key": "super-secret-key", "language": "nl"})

    (root / "evidence" / "web").mkdir(parents=True, exist_ok=True)
    (root / "evidence" / "web" / "snap1.txt").write_text("evidence-body", encoding="utf-8")
    (root / "evidence" / "api_key.secret").write_text("TOKEN=abc", encoding="utf-8")
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "artifacts" / "report.md").write_text("# artifact", encoding="utf-8")
    (root / "knowledge" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "raw" / "doc.txt").write_text("knowledge text for chunks", encoding="utf-8")
    (root / "plugins" / "sources").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "sources" / "plugin.json").write_text('{"id":"demo"}', encoding="utf-8")
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "huge.bin").write_bytes(b"x" * 1024)
    (root / "caches").mkdir(parents=True, exist_ok=True)
    (root / "caches" / "tmp.cache").write_text("cache", encoding="utf-8")
    return db


class WorkspaceBackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data"
        self.db = _seed_workspace(self.root)
        self.svc = WorkspaceBackupService(self.root, db_path=self.root / "hades.db", app_version="0.4.1", schema_version=1)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inventory_excludes_large_and_secrets_by_default(self) -> None:
        inv = self.svc.inventory()
        cats = set(inv["include"])
        self.assertIn("database", cats)
        self.assertIn("evidence", cats)
        self.assertNotIn("models", cats)
        self.assertNotIn("caches", cats)
        excluded_rels = {e["relative_path"] for e in inv["entries"] if not e["included"]}
        self.assertTrue(any("secret" in r or r.endswith(".env") for r in excluded_rels))
        self.assertIn("full workspace archive", inv["note"].lower())

    def test_backup_restore_isolated_usable_overview(self) -> None:
        result = self.svc.create_archive()
        self.assertIn(result["phase"], {"completed", "completed_with_warnings"})
        self.assertTrue(result["not_db_only"])
        self.assertEqual(result["kind"], "full_workspace_archive")
        archive = Path(result["archive_path"])
        self.assertTrue(archive.is_file())

        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["format"], ARCHIVE_FORMAT)
        self.assertTrue(manifest["not_db_only"])
        self.assertIn("database", manifest["include"])
        # models excluded by default
        packed = {f["relative_path"] for f in manifest["files"]}
        self.assertTrue(any(p.endswith("hades.db") or p == "hades.db" for p in packed))
        self.assertFalse(any(p.startswith("models/") for p in packed))

        # Secrets redacted in DB copy
        with zipfile.ZipFile(archive) as zf:
            db_name = next(n for n in zf.namelist() if n.endswith("hades.db"))
            db_bytes = zf.read(db_name)
        tmp_db = Path(self.temp.name) / "check.db"
        tmp_db.write_bytes(db_bytes)
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", ("lm_studio_api_key",)).fetchone()
        conn.close()
        self.assertEqual(row[0], "***")

        restore = self.svc.restore_to_isolated(archive)
        self.assertTrue(restore["ok"], restore)
        self.assertTrue(restore["active_workspace_untouched"])
        self.assertTrue(restore["activation_required"])
        overview = restore["overview"]
        self.assertGreaterEqual(overview["conversations"] or 0, 1)
        self.assertGreaterEqual(overview["evidence_files"] or 0, 1)
        self.assertGreaterEqual(overview["artifact_files"] or 0, 1)
        self.assertTrue(restore["core_functions"]["database_openable"])
        self.assertTrue(restore["migration_compatible"])

        # Active workspace still intact before activate
        self.assertTrue((self.root / "hades.db").is_file())
        self.assertEqual(
            self.db.count_conversations(),
            2,  # welcome seed + Backup Test Chat
        )

    def test_failed_restore_does_not_damage_active(self) -> None:
        marker = self.root / "artifacts" / "report.md"
        before = marker.read_text(encoding="utf-8")
        bad = Path(self.temp.name) / "missing.hadesws.zip"
        out = self.svc.restore_to_isolated(bad)
        self.assertFalse(out["ok"])
        self.assertTrue(out["active_workspace_untouched"])
        self.assertEqual(marker.read_text(encoding="utf-8"), before)

    def test_corrupt_and_changed_detected(self) -> None:
        result = self.svc.create_archive()
        archive = Path(result["archive_path"])
        # Build a corrupt archive by rewriting a file with wrong hash in manifest.
        corrupt = Path(self.temp.name) / "corrupt.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(corrupt, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "manifest.json":
                    manifest = json.loads(data)
                    if manifest["files"]:
                        manifest["files"][0]["sha256"] = "0" * 64
                    data = json.dumps(manifest).encode()
                dst.writestr(info, data)
        restore = self.svc.restore_to_isolated(corrupt)
        self.assertFalse(restore["ok"])
        self.assertTrue(restore["integrity"]["corrupt_hash_mismatch"] or restore["integrity"]["missing"])
        self.assertTrue(restore["active_workspace_untouched"])

    def test_unsafe_archive_paths_rejected(self) -> None:
        evil = Path(self.temp.name) / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": ARCHIVE_FORMAT,
                        "schema_version": 1,
                        "app_version": "0.4.1",
                        "files": [],
                        "integrity": {"file_count": 0},
                    }
                ),
            )
            zf.writestr("../escape.txt", "nope")
        target = Path(self.temp.name) / "extract"
        with self.assertRaises(ValueError):
            WorkspaceBackupService.safe_extract_workspace_zip(evil, target)

    def test_older_schema_incompatible(self) -> None:
        old = Path(self.temp.name) / "old.zip"
        with zipfile.ZipFile(old, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "hades.workspace_archive.v0",
                        "schema_version": 0,
                        "app_version": "0.1.0",
                        "files": [],
                    }
                ),
            )
            zf.writestr("workspace/hades.db", b"not-a-db")
        out = self.svc.restore_to_isolated(old)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "incompatible_schema")
        self.assertTrue(out["active_workspace_untouched"])

    def test_future_schema_migration_blocked(self) -> None:
        fut = Path(self.temp.name) / "future.zip"
        with zipfile.ZipFile(fut, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": ARCHIVE_FORMAT,
                        "schema_version": 99,
                        "app_version": "9.9.9",
                        "files": [],
                    }
                ),
            )
        out = self.svc.restore_to_isolated(fut)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "migration_incompatible")
        self.assertTrue(out["active_workspace_untouched"])

    def test_cancel_backup(self) -> None:
        from workspace_backup import BackupProgress

        job_id = "wsbak_manual"
        self.svc._jobs[job_id] = BackupProgress(job_id=job_id, phase="packing")
        out = self.svc.cancel(job_id)
        self.assertTrue(out["cancelled"])
        self.assertEqual(out["phase"], "cancelled")

    def test_db_only_route_note_contract(self) -> None:
        # Characterization: service kind must never claim db-only is full workspace.
        result = self.svc.create_archive(include=["database"])
        self.assertTrue(result["not_db_only"])
        self.assertEqual(result["manifest"]["kind"], "full_workspace_archive")
        self.assertIn("settings/backup", result["manifest"]["db_only_settings_backup_note"])


if __name__ == "__main__":
    unittest.main()
