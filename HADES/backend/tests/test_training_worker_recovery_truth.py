from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training_service import TrainingWorkspace


class TrainingWorkerRecoveryTruthTests(unittest.TestCase):
    def test_dead_worker_pid_is_not_reported_as_active(self) -> None:
        """A dead trainer must not remain durably labelled running forever."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = TrainingWorkspace(Path(temp_dir) / "training")
            job_id = "train_deadbeefdeadbeef"
            job_dir = workspace.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            (job_dir / "job.json").write_text(
                json.dumps(
                    {
                        "id": job_id,
                        "dataset_id": "ds_deadbeefdeadbeef",
                        "status": "running",
                        "pid": 2_147_483_647,
                        "created_at": "2026-09-13T00:00:00+00:00",
                        "updated_at": "2026-09-13T00:00:00+00:00",
                        "started_at": "2026-09-13T00:00:00+00:00",
                        "finished_at": None,
                        "error": None,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            item = workspace.get_job(job_id)

            self.assertNotIn(item.get("status"), {"queued", "running", "cancelling"})
            self.assertIsNotNone(item.get("finished_at"))
            self.assertTrue(item.get("error"))


if __name__ == "__main__":
    unittest.main()
