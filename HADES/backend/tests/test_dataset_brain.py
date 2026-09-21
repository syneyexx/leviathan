from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_brain import DatasetBrainManager, _pid_alive, read_manifest, write_manifest
from dataset_brain_routes import mount_dataset_brain_routes
from dataset_brain_worker import _mapping_fingerprint, _source_fingerprint, run as run_brain_worker
from platform_db import PlatformDatabase
from training_routes import mount_training_routes
from training_service import TrainingWorkspace
from training_worker import _offline_brain_snapshot


class _FakeDatabase:
    def __init__(self, path: Path, *, file_read_policy: str = "ask", network_policy: str = "ask") -> None:
        self.path = path
        self.values = {"file_read_policy": file_read_policy, "network_policy": network_policy}

    def get_settings(self) -> dict[str, str]:
        return dict(self.values)


class DatasetBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "hades.db"
        self.training_root = self.root / "training"
        self.workspace = TrainingWorkspace(self.training_root)
        self.platform = PlatformDatabase(str(self.db_path))
        self.platform.initialize()
        self.source = self.root / "brain-source.jsonl"
        rows = [
            {"instruction": "Explain alphamarkerxyz subsystem", "output": "alphamarkerxyz uses verified local evidence."},
            {"instruction": "Explain alphamarkerxyz subsystem", "output": "alphamarkerxyz uses verified local evidence."},
            {"text": "secretmarkerxyz api_key=super-secret-value should be redacted from retrieval"},
            {"reasoning": "privatereasonmarkerxyz must not become retrieval", "text": "publicmarkerxyz is safe knowledge"},
        ]
        self.rows = rows
        self.source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.dataset = self.workspace.register_local(self.source, name="Brain regression")
        self.manager = DatasetBrainManager(self.training_root, self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _job_path(self, job: dict[str, object]) -> Path:
        return self.manager.jobs_dir / str(job["id"]) / "job.json"

    def test_pid_probe_is_non_destructive(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertTrue(_pid_alive(process.pid))
            with self.assertRaises(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def test_local_dataset_materializes_indexes_and_is_searchable_offline(self) -> None:
        job = self.manager.create_job(dataset_id=self.dataset["id"], token="hf_must_not_persist", launch=False)
        job_path = self._job_path(job)
        self.assertNotIn("hf_must_not_persist", job_path.read_text(encoding="utf-8"))

        self.assertEqual(run_brain_worker(job_path), 0)
        state = self.manager.status(self.dataset["id"])
        self.assertEqual(state["status"], "ready")
        self.assertTrue(state["materialized_complete"])
        self.assertEqual(state["materialized_rows"], len(self.rows))
        self.assertTrue(state["snapshot_exists"])
        self.assertGreater(state["chunks_indexed"], 0)

        snapshot = Path(state["snapshot_path"])
        raw = snapshot.read_text(encoding="utf-8")
        self.assertIn("super-secret-value", raw)  # raw local source is deliberately preserved
        self.assertIn("privatereasonmarkerxyz", raw)

        alpha = self.platform.search_knowledge("alphamarkerxyz", limit=8)
        self.assertTrue(alpha)
        self.assertEqual(alpha[0]["source_type"], "dataset")
        self.assertEqual(alpha[0]["uri"], f"dataset://{self.dataset['id']}")

        secret = self.platform.search_knowledge("secretmarkerxyz", limit=8)
        self.assertTrue(secret)
        rendered = "\n".join(str(item.get("content") or "") for item in secret)
        self.assertNotIn("super-secret-value", rendered)
        self.assertIn("***REDACTED***", rendered)

        self.assertEqual(self.platform.search_knowledge("privatereasonmarkerxyz", limit=8), [])
        self.assertTrue(self.platform.search_knowledge("publicmarkerxyz", limit=8))

        before = int(state["chunks_indexed"])
        second = self.manager.create_job(dataset_id=self.dataset["id"], launch=False)
        self.assertEqual(run_brain_worker(self._job_path(second)), 0)
        after = self.manager.status(self.dataset["id"])
        self.assertEqual(after["chunks_indexed"], before)
        self.assertEqual(after["materialized_rows"], len(self.rows))
        self.assertEqual(_offline_brain_snapshot(self.dataset, self.training_root), Path(after["snapshot_path"]))

    def test_materialization_resume_truncates_uncheckpointed_tail(self) -> None:
        job = self.manager.create_job(dataset_id=self.dataset["id"], launch=False)
        job_path = self._job_path(job)
        brain_root = self.training_root / "datasets" / self.dataset["id"] / "brain"
        brain_root.mkdir(parents=True, exist_ok=True)
        snapshot = brain_root / "data.jsonl"
        first = (json.dumps(self.rows[0]) + "\n").encode()
        second = (json.dumps(self.rows[1]) + "\n").encode()
        uncheckpointed = (json.dumps(self.rows[2]) + "\n").encode()
        snapshot.write_bytes(first + second + uncheckpointed)
        write_manifest(
            self.training_root,
            self.dataset["id"],
            {
                "status": "materializing",
                "phase": "materializing",
                "materialized_rows": 2,
                "materialized_complete": False,
                "snapshot_path": str(snapshot),
                "snapshot_bytes": len(first + second),
                "source_fingerprint": _source_fingerprint(self.dataset),
                "mapping_fingerprint": _mapping_fingerprint(self.dataset),
            },
        )

        self.assertEqual(run_brain_worker(job_path), 0)
        lines = [line for line in snapshot.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), len(self.rows))
        self.assertEqual([json.loads(line) for line in lines], self.rows)

    def test_hidden_reasoning_mapping_fails_without_publishing_partial_fts(self) -> None:
        self.workspace.update_mapping(self.dataset["id"], text_field="reasoning")
        job = self.manager.create_job(dataset_id=self.dataset["id"], launch=False)
        self.assertEqual(run_brain_worker(self._job_path(job)), 1)
        self.assertEqual(self.platform.search_knowledge("privatereasonmarkerxyz", limit=8), [])
        state = self.manager.status(self.dataset["id"])
        self.assertEqual(state["status"], "failed")

    def test_remove_brain_deletes_snapshot_and_knowledge_projection(self) -> None:
        job = self.manager.create_job(dataset_id=self.dataset["id"], launch=False)
        self.assertEqual(run_brain_worker(self._job_path(job)), 0)
        state = self.manager.status(self.dataset["id"])
        snapshot = Path(state["snapshot_path"])
        self.assertTrue(snapshot.exists())
        self.assertTrue(self.platform.search_knowledge("alphamarkerxyz", limit=4))

        removed = self.manager.remove_dataset_brain(self.dataset["id"], platform_db=self.platform)
        self.assertTrue(removed["removed"])
        self.assertFalse(snapshot.exists())
        self.assertEqual(self.platform.search_knowledge("alphamarkerxyz", limit=4), [])
        self.assertIsNone(read_manifest(self.training_root, self.dataset["id"]))

    def test_brain_route_respects_file_read_policy_before_first_materialization(self) -> None:
        fake_db = _FakeDatabase(self.db_path, file_read_policy="ask")
        # This case isolates file_read approval; subprocess policy is orthogonal.
        fake_db.values["subprocess_policy"] = "allow"
        app = FastAPI()
        app.include_router(mount_dataset_brain_routes({"database": fake_db}))
        client = TestClient(app)

        blocked = client.post(
            f"/training/brain/datasets/{self.dataset['id']}/index",
            json={"approved_file_read": False, "approved_network": False},
        )
        self.assertEqual(blocked.status_code, 409)

        with patch("dataset_brain.DatasetBrainManager.create_job") as create_job:
            create_job.return_value = {"id": "brain_0000000000000000", "status": "running"}
            allowed = client.post(
                f"/training/brain/datasets/{self.dataset['id']}/index",
                json={"approved_file_read": True, "approved_network": False},
            )
        self.assertEqual(allowed.status_code, 201)
        create_job.assert_called_once()

    def test_training_dataset_delete_requires_explicit_brain_removal(self) -> None:
        write_manifest(self.training_root, self.dataset["id"], {"status": "ready"})
        fake_db = _FakeDatabase(self.db_path)
        app = FastAPI()
        app.include_router(mount_training_routes({"database": fake_db}))
        client = TestClient(app)
        result = client.delete(f"/training/datasets/{self.dataset['id']}")
        self.assertEqual(result.status_code, 409)
        self.assertIn("HADES Brain", result.json()["detail"])


if __name__ == "__main__":
    unittest.main()
