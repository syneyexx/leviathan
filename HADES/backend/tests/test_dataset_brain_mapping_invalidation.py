from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_brain import DatasetBrainManager
from dataset_brain_worker import run as run_brain_worker
from platform_db import PlatformDatabase
from training_routes import mount_training_routes
from training_service import TrainingWorkspace


class _FakeDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_settings(self) -> dict[str, str]:
        return {"file_read_policy": "allow", "network_policy": "allow"}


class DatasetBrainMappingInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "hades.db"
        self.training_root = self.root / "training"
        self.workspace = TrainingWorkspace(self.training_root)
        self.platform = PlatformDatabase(str(self.db_path))
        self.platform.initialize()
        self.source = self.root / "mapping.jsonl"
        rows = [
            {"instruction": "Explain oldmappingmarker", "output": "oldmappingmarker answer"},
            {"text": "newmappingmarker public text"},
        ]
        self.source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.dataset = self.workspace.register_local(self.source, name="Mapping invalidation")
        self.manager = DatasetBrainManager(self.training_root, self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_job(self) -> None:
        job = self.manager.create_job(dataset_id=self.dataset["id"], launch=False)
        job_path = self.manager.jobs_dir / str(job["id"]) / "job.json"
        self.assertEqual(run_brain_worker(job_path), 0)

    def test_mapping_change_hides_old_fts_until_reindex(self) -> None:
        self._run_job()
        before = self.manager.status(self.dataset["id"])
        snapshot = Path(str(before["snapshot_path"]))
        self.assertEqual(before["status"], "ready")
        self.assertTrue(snapshot.is_file())
        self.assertTrue(self.platform.search_knowledge("oldmappingmarker", limit=4))

        app = FastAPI()
        app.include_router(mount_training_routes({"database": _FakeDatabase(self.db_path)}))
        client = TestClient(app)
        changed = client.put(
            f"/training/datasets/{self.dataset['id']}/mapping",
            json={"text_field": "text"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["mapping"]["text_field"], "text")

        stale = self.manager.status(self.dataset["id"])
        self.assertEqual(stale["status"], "stale_mapping")
        self.assertTrue(snapshot.is_file())
        self.assertEqual(self.platform.search_knowledge("oldmappingmarker", limit=4), [])
        self.assertEqual(self.platform.search_knowledge("newmappingmarker", limit=4), [])

        self._run_job()
        ready = self.manager.status(self.dataset["id"])
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(self.platform.search_knowledge("newmappingmarker", limit=4))
        self.assertEqual(self.platform.search_knowledge("oldmappingmarker", limit=4), [])


if __name__ == "__main__":
    unittest.main()
