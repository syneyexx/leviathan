"""Contracts for the read-only backend-host projections."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.host_console import build_host_console_router
from Data.modules.host_console.read_model import (
    build_host_overview,
    build_native_operations_read_model,
    build_source_ingestion_read_model,
    redact_host_text,
)
from Data.modules.jobs.states import JobState
from Data.modules.jobs.types import JobRecord


class _Runtime:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 8765
        self.loopback_only = True


class _Settings:
    def __init__(self, root: Path) -> None:
        self.runtime = _Runtime()
        self.database_path = root / "control.db"
        self.knowledge_database_path = root / "knowledge.db"
        self.control_database_path = self.database_path


class _Job:
    def __init__(self, record: JobRecord | None) -> None:
        self.record = record
        self.gets = 0

    def get(self, job_id: str) -> JobRecord | None:
        self.gets += 1
        if self.record and self.record.job_id == job_id:
            return self.record
        return None


class _Manager:
    def __init__(self) -> None:
        self.calls = 0

    def list_databases(self) -> list[dict]:
        self.calls += 1
        return [
            {
                "domain": "CONTROL",
                "exists": True,
                "health": "OK",
                "readiness": "READY",
                "sizeBytes": 10,
                "schemaVersion": 1,
                "tableCount": 2,
                "journalMode": "wal",
                "path": "/tmp/should-not-be-required",
            },
            {
                "domain": "KNOWLEDGE",
                "exists": False,
                "health": "MISSING",
                "readiness": "MISSING",
                "sizeBytes": 0,
                "schemaVersion": 0,
                "tableCount": "UNMEASURED",
                "journalMode": "UNMEASURED",
            },
            {
                "domain": "MARKET",
                "exists": True,
                "health": "BUSY",
                "readiness": "BUSY",
                "sizeBytes": 4,
                "schemaVersion": 3,
                "tableCount": 1,
                "journalMode": "wal",
            },
        ]


def _seed_container(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE source_ingestion_containers (
            container_source_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            job_id TEXT,
            filename TEXT,
            archive_type TEXT,
            phase TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            compressed_bytes INTEGER NOT NULL DEFAULT 0,
            uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
            progress_json TEXT NOT NULL DEFAULT '{}',
            manifest_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO source_ingestion_containers(
            container_source_id, project_id, job_id, filename, archive_type, phase,
            cancel_requested, compressed_bytes, uncompressed_bytes, progress_json,
            manifest_json, error, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "src-1",
            "proj",
            "job-1",
            "notes.pdf",
            "pdf",
            "parsing",
            0,
            10,
            20,
            json.dumps({"progress_pct": 40, "bytes_per_second": 12.5}),
            "{}",
            "token=super-secret-value",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:01:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO source_ingestion_containers(
            container_source_id, project_id, job_id, filename, archive_type, phase,
            cancel_requested, compressed_bytes, uncompressed_bytes, progress_json,
            manifest_json, error, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "src-2",
            "proj",
            "job-2",
            "done.zip",
            "zip",
            "completed",
            0,
            1,
            2,
            "{}",
            "{}",
            None,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:02:00+00:00",
        ),
    )
    conn.commit()
    conn.close()


class ReadModelTests(unittest.TestCase):
    def test_redacts_secrets(self) -> None:
        text = redact_host_text("Authorization: Bearer abcdefghijk api_key=zzzzzzzz")
        self.assertNotIn("abcdefghijk", text)
        self.assertNotIn("zzzzzzzz", text)
        self.assertIn("[REDACTED]", text)

    def test_ingestion_uses_container_truth_and_does_not_invent_eta(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "control.db"
            _seed_container(db)
            before = db.stat().st_mtime_ns
            settings = _Settings(root)
            record = JobRecord(
                job_id="job-1",
                capability_id="source_ingestion.process",
                arguments={"api_key": "should-not-leak"},
                state=JobState.RUNNING,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:01:00+00:00",
                lease_owner="worker-source-1",
                worker_pool="source_ingestion",
            )
            jobs = _Job(record)
            payload = build_source_ingestion_read_model(settings=settings, job_runtime=jobs, limit=20)
            self.assertEqual(db.stat().st_mtime_ns, before)
            self.assertEqual(payload["counts"]["processing"], 1)
            self.assertEqual(payload["counts"]["completed"], 1)
            self.assertIsNone(payload["jobs"][0]["etaSeconds"] if payload["jobs"][0]["id"] == "src-1" else payload["jobs"][1]["etaSeconds"])
            parsing = next(item for item in payload["jobs"] if item["id"] == "src-1")
            self.assertEqual(parsing["progressPct"], 40.0)
            self.assertEqual(parsing["throughput"], 12.5)
            self.assertEqual(parsing["state"], "RUNNING")
            self.assertEqual(parsing["worker"], "worker-source-1")
            self.assertNotIn("should-not-leak", json.dumps(payload))
            self.assertNotIn("super-secret-value", json.dumps(payload))
            self.assertIsNone(parsing["etaSeconds"])
            self.assertTrue(payload["truth"]["partialIsNotComplete"])

    def test_missing_database_is_empty_not_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = _Settings(Path(tmp))
            payload = build_source_ingestion_read_model(settings=settings, job_runtime=None)
            self.assertEqual(payload["counts"]["completed"], 0)
            self.assertIsNone(payload["overallProgressPct"])
            self.assertEqual(payload["jobs"], [])

    def test_native_build_missing_is_not_available(self) -> None:
        payload = build_native_operations_read_model(
            probe_fn=lambda: {
                "status": "BUILD_MISSING",
                "binaryPath": None,
                "operations": [],
                "detail": "leviathan-data-plane binary not found",
            },
            observability=None,
        )
        self.assertEqual(payload["probe"]["status"], "BUILD_MISSING")
        self.assertFalse(payload["probe"]["available"])
        self.assertFalse(payload["daemon"])
        self.assertEqual(payload["stdoutTail"], [])
        self.assertTrue(payload["truth"]["binaryPathIsNotAvailable"])

    def test_native_path_alone_is_not_available(self) -> None:
        payload = build_native_operations_read_model(
            probe_fn=lambda: {
                "status": "FAILED_HEALTHCHECK",
                "binaryPath": "/opt/leviathan-data-plane",
                "operations": ["parse"],
                "detail": "capabilities exit=1",
            }
        )
        self.assertFalse(payload["probe"]["available"])
        self.assertEqual(payload["probe"]["binaryPath"], "/opt/leviathan-data-plane")

    def test_overview_preserves_database_health_and_watcher(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = _Settings(Path(tmp))
            manager = _Manager()
            payload = build_host_overview(
                settings=settings,
                sqlite_manager=manager,
                probe_fn=lambda: {"status": "DISABLED", "detail": "native compute disabled by settings"},
                version="test",
            )
            self.assertEqual(payload["version"], "test")
            self.assertEqual(payload["runtime"]["port"], 8765)
            domains = [row["domain"] for row in payload["databases"]]
            self.assertEqual(domains, ["CONTROL", "KNOWLEDGE", "MARKET"])
            self.assertEqual(payload["databases"][1]["health"], "MISSING")
            self.assertEqual(payload["databases"][2]["health"], "BUSY")
            self.assertEqual(payload["watcher"]["status"], "NOT_CONFIGURED")
            self.assertEqual(payload["native"]["status"], "DISABLED")
            self.assertFalse(payload["native"]["available"])
            self.assertNotIn("postgres", json.dumps(payload).lower())
            self.assertTrue(payload["truth"]["doesNotMutate"])

    def test_route_contract_is_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "control.db"
            _seed_container(db)
            before = db.read_bytes()
            settings = _Settings(root)
            app = FastAPI()
            app.include_router(
                build_host_console_router(
                    settings=settings,
                    job_runtime=_Job(None),
                    observability=None,
                    sqlite_manager=_Manager(),
                    probe_fn=lambda: {"status": "BUILD_MISSING", "operations": [], "detail": "missing"},
                    version="0-test",
                )
            )
            client = TestClient(app)
            overview = client.get("/api/host/overview")
            ingestion = client.get("/api/host/source-ingestion")
            native = client.get("/api/host/native-operations")
            liveness = client.get("/api/host/liveness")
            self.assertEqual(overview.status_code, 200)
            self.assertEqual(ingestion.status_code, 200)
            self.assertEqual(native.status_code, 200)
            self.assertEqual(liveness.status_code, 200)
            self.assertTrue(liveness.json()["ok"])
            self.assertEqual(overview.json()["databases"][0]["domain"], "CONTROL")
            self.assertEqual(ingestion.json()["counts"]["processing"], 1)
            self.assertEqual(native.json()["probe"]["status"], "BUILD_MISSING")
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(client.post("/api/host/overview").status_code, 405)
            self.assertEqual(client.post("/api/host/liveness").status_code, 405)


if __name__ == "__main__":
    unittest.main()
