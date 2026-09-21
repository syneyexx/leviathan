from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_jobs import CodingJobStore


class CodingJobAtomicWriteTests(unittest.TestCase):
    def test_replace_failure_never_truncates_last_valid_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodingJobStore(Path(temp_dir) / "jobs")
            self.addCleanup(store._executor.shutdown, wait=False, cancel_futures=True)
            job_id = "job_atomic"
            job_dir = store._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)
            target = job_dir / "status.json"
            original = {"id": job_id, "status": "queued", "event_seq": 1}
            target.write_text(json.dumps(original), encoding="utf-8")

            real_write_text = Path.write_text

            def crash_on_direct_target_write(path: Path, data: str, *args, **kwargs):
                if path == target:
                    # Model an interrupted non-atomic overwrite: the prior valid
                    # JSON must remain the recovery source after the failure.
                    with path.open("w", encoding="utf-8") as handle:
                        handle.write("{")
                    raise OSError("simulated interrupted fallback write")
                return real_write_text(path, data, *args, **kwargs)

            with patch("coding_jobs.os.replace", side_effect=PermissionError("sharing violation")), \
                 patch("coding_jobs.time.sleep", return_value=None), \
                 patch.object(Path, "write_text", new=crash_on_direct_target_write):
                with self.assertRaises(OSError):
                    store._write(job_id, {"id": job_id, "status": "running", "event_seq": 2})

            recovered = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(recovered, original)


if __name__ == "__main__":
    unittest.main()
