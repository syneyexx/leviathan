from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_agent import BuildAgentService, BuildRunResult


class BuildAgentResultPersistenceHonestyTests(unittest.TestCase):
    @staticmethod
    def _fail_result_write(real_write_text):
        def fail_result_write(path: Path, data: str, *args, **kwargs):  # noqa: ANN001
            if path.name == "result.json":
                raise OSError("simulated durable result write failure")
            return real_write_text(path, data, *args, **kwargs)

        return fail_result_write

    def test_result_persistence_error_is_not_silently_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = BuildAgentService(root)
            result = BuildRunResult(
                run_id="build_persist_fixture",
                status="verified",
                baseline_commit=None,
                baseline_hashes={},
                work_root=str(root / "work"),
                planned_edits=[],
                applied_edits=[],
                diff_text="",
            )

            real_write_text = Path.write_text
            with patch.object(Path, "write_text", new=self._fail_result_write(real_write_text)):
                with self.assertRaises(OSError):
                    service._persist_result(result)

    def test_repair_loop_does_not_return_verified_when_result_cannot_be_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            service = BuildAgentService(root / "hades-data")
            passing_test = {
                "suite": "fixture",
                "command": ["fixture-test"],
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "status": "passed",
                "started_at": "fixture",
                "finished_at": "fixture",
                "executed": True,
            }

            real_write_text = Path.write_text
            with patch.object(service, "run_tests", return_value=passing_test):
                with patch.object(Path, "write_text", new=self._fail_result_write(real_write_text)):
                    result = service.run_repair_loop(
                        source,
                        [],
                        test_suite="unittest",
                        max_attempts=1,
                        goal="persistence honesty fixture",
                    )

            self.assertEqual(result.status, "failed")
            self.assertIn("result_persistence_failed", result.error or "")
            self.assertFalse((service.runs_root / result.run_id / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
