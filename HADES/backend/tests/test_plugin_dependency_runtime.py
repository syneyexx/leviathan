from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_dependency_runtime import DependencyCommandRunner, read_dependency_snapshot, redact_dependency_output


class DependencyCommandRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log_path = self.root / "dependencies.log"
        self.status_path = self.root / "dependencies.status.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_command(self, script: str, *, timeout: int = 5, stall: int = 0):
        runner = DependencyCommandRunner(
            log_path=self.log_path,
            status_path=self.status_path,
            runtime="test",
            command_index=1,
            total_commands=1,
            timeout_seconds=timeout,
            stall_timeout_seconds=stall,
        )
        result = runner.run([sys.executable, "-c", script], cwd=self.root, env=os.environ.copy())
        return result, read_dependency_snapshot(self.log_path, self.status_path)

    def test_streams_stdout_and_stderr_to_bounded_log(self) -> None:
        result, snapshot = self.run_command(
            "import sys; print('dependency-out', flush=True); print('dependency-err', file=sys.stderr, flush=True)"
        )
        self.assertIsNone(result["error"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("dependency-out", result["stdout"])
        self.assertIn("dependency-err", result["stderr"])
        self.assertIn("dependency-out", snapshot["log"])
        self.assertIn("dependency-err", snapshot["log"])
        self.assertEqual(snapshot["state"]["phase"], "command_completed")

    def test_total_timeout_preserves_partial_output(self) -> None:
        result, snapshot = self.run_command(
            "import time; print('before-timeout', flush=True); time.sleep(5)",
            timeout=1,
        )
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["stalled"])
        self.assertIn("before-timeout", result["stdout"])
        self.assertIn("totale timeout", result["error"] or "")
        self.assertEqual(snapshot["state"]["phase"], "failed")

    def test_stall_detection_terminates_silent_process(self) -> None:
        result, snapshot = self.run_command("import time; time.sleep(5)", timeout=5, stall=1)
        self.assertTrue(result["stalled"])
        self.assertFalse(result["timed_out"])
        self.assertIn("lijkt vastgelopen", result["error"] or "")
        self.assertEqual(snapshot["state"]["phase"], "failed")

    def test_redacts_common_secret_shapes(self) -> None:
        safe = redact_dependency_output(
            "token=supersecret password: hunter2 Authorization=abc Bearer bearer-secret"
        )
        self.assertNotIn("supersecret", safe)
        self.assertNotIn("hunter2", safe)
        self.assertNotIn("bearer-secret", safe)
        self.assertGreaterEqual(safe.count("[REDACTED]"), 4)


if __name__ == "__main__":
    unittest.main()
