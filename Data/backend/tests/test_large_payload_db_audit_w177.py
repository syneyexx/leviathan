"""W177 — large-payload DB audit script produces report JSON."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "audit_large_db_payloads.py"
SUMMARY = ROOT / "Data" / "backend" / "tests" / "large_payload_db_audit.summary.json"


class LargePayloadDbAuditTests(unittest.TestCase):
    def test_script_runs_and_report_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lev-w177-") as tmp:
            db = Path(tmp) / "audit.db"
            out = Path(tmp) / "large_payload_db_audit.json"
            with sqlite3.connect(db) as conn:
                conn.execute(
                    """
                    CREATE TABLE datasets (
                        dataset_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        raw_path TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE knowledge_documents (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO datasets VALUES (?, ?, ?, ?)",
                    ("d1", "demo", "/tmp/corpus/x.jsonl", '{"k":1}'),
                )
                conn.execute(
                    "INSERT INTO knowledge_documents VALUES (?, ?, ?)",
                    ("k1", "t", "x" * 1000),
                )
                conn.execute(
                    """
                    CREATE TABLE knowledge_chunk_embeddings (
                        chunk_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO knowledge_chunk_embeddings VALUES (?, ?)",
                    ("c1", b"\x00" * 128),
                )
                conn.commit()

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--db",
                    str(db),
                    "--out",
                    str(out),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertTrue(out.is_file())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report.get("databaseExists"))
            self.assertIn("summary", report)
            self.assertTrue(report.get("truth", {}).get("knowledgeStoreRedesignSkipped"))
            classes = {c["table"]: c for c in report["columns"]}
            self.assertTrue(classes)  # at least one column audited
            by_key = {(c["table"], c["column"]): c for c in report["columns"]}
            self.assertEqual(by_key[("datasets", "raw_path")]["classification"], "metadata_sized")
            self.assertEqual(by_key[("datasets", "raw_path")]["role"], "file_ref")
            self.assertEqual(
                by_key[("knowledge_documents", "content")]["classification"], "unbounded"
            )
            self.assertEqual(
                by_key[("knowledge_chunk_embeddings", "embedding")]["classification"],
                "reasonable",
            )

            # Committed evidence is the bounded summary only (no raw firehose).
            self.assertTrue(SUMMARY.is_file())
            summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
            self.assertEqual(summary.get("artifactKind"), "bounded_summary")
            self.assertTrue(summary.get("truth", {}).get("rawScanNotCommitted"))


if __name__ == "__main__":
    unittest.main()
