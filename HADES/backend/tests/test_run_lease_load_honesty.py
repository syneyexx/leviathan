from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from run_leases import ExecutionLeaseStore


class ExecutionLeaseLoadHonestyTests(unittest.TestCase):
    def test_corrupt_persisted_lease_state_is_not_silently_treated_as_empty(self) -> None:
        """Durable fencing state must fail closed when its persisted JSON is corrupt."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "execution_leases.json"
            path.write_text('{"leases": {broken json', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "unreadable or corrupt"):
                ExecutionLeaseStore(path)

    def test_valid_persisted_lease_state_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "execution_leases.json"
            path.write_text(
                json.dumps(
                    {
                        "leases": {
                            "task:1": {
                                "resource_id": "task:1",
                                "worker_id": "worker-a",
                                "expires_at": 123.0,
                                "fence_token": "fence_test",
                                "generation": 4,
                            }
                        },
                        "control": {
                            "task:1": {"pause_requested": True, "paused": False}
                        },
                        "generations": {"task:1": 4},
                    }
                ),
                encoding="utf-8",
            )

            store = ExecutionLeaseStore(path)
            snapshot = store.dump()

            self.assertEqual(snapshot["generations"]["task:1"], 4)
            self.assertEqual(snapshot["leases"]["task:1"]["worker_id"], "worker-a")
            self.assertTrue(snapshot["control"]["task:1"]["pause_requested"])


if __name__ == "__main__":
    unittest.main()
