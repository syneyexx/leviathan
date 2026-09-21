from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset_brain import DatasetBrainManager
from training_service import TrainingWorkspace


class DatasetBrainRecoveryTruthTests(unittest.TestCase):
    def test_interrupted_job_wins_over_stale_active_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            training_root = root / "training"
            source = root / "dataset.jsonl"
            source.write_text('{"text":"alpha"}\n{"text":"beta"}\n', encoding="utf-8")

            workspace = TrainingWorkspace(training_root)
            dataset = workspace.register_local(source, name="Recovery truth")
            manager = DatasetBrainManager(training_root, root / "hades.db")
            job = manager.create_job(dataset_id=dataset["id"], launch=False)
            self.assertEqual(job["status"], "queued")

            # status() reconciles the dead/no-PID active job to interrupted. Force
            # the best-effort manifest compensation to fail: read-side truth must
            # still come from the durable reconciled job, not stale manifest state.
            with patch("dataset_brain.write_manifest", side_effect=OSError("manifest unavailable")):
                state = manager.status(dataset["id"])

            self.assertEqual(state["status"], "interrupted")
            self.assertEqual(state["latest_job_id"], job["id"])
            self.assertIsNone(state.get("active_job_id"))


if __name__ == "__main__":
    unittest.main()
