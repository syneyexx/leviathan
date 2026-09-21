from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training_service import TrainingWorkspace


class TrainingJobRecoveryTruthTests(unittest.TestCase):
    def test_dead_training_worker_is_not_reported_as_active_forever(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "training"
            workspace = TrainingWorkspace(root)
            job_id = "train_0123456789abcdef"
            job_dir = workspace.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            (job_dir / "job.json").write_text(
                json.dumps(
                    {
                        "id": job_id,
                        "dataset_id": "ds_0123456789abcdef",
                        "status": "running",
                        "pid": 999_999_999,
                        "created_at": "2026-09-13T00:00:00+00:00",
                        "updated_at": "2026-09-13T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            job = workspace.get_job(job_id)
            self.assertNotIn(job["status"], {"queued", "running", "cancelling"}, job)


if __name__ == "__main__":
    unittest.main()
