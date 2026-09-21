from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from coding_jobs import CodingJobStore


class CodingJobUnknownTerminalStatusHonestyTests(unittest.TestCase):
    def test_unknown_runner_status_is_not_promoted_to_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodingJobStore(Path(temp_dir), max_workers=1)

            def runner(_payload):
                return {"status": "timeout", "id": "run-timeout", "error": "provider timed out"}

            started = store.start(
                runner=runner,
                params={
                    "source_repo": str(Path(temp_dir)),
                    "goal": "audit fixture",
                    "strategy": "investigate",
                },
            )
            job_id = str(started["id"])
            deadline = time.monotonic() + 2.0
            snapshot = store.get(job_id)
            while snapshot.get("status") in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.01)
                snapshot = store.get(job_id)

            self.assertNotEqual(snapshot.get("status"), "completed")
            self.assertIn(snapshot.get("status"), {"failed", "interrupted"})


if __name__ == "__main__":
    unittest.main()
