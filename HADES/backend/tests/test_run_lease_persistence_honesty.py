from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_leases import ExecutionLeaseStore


class RunLeasePersistenceHonestyTests(unittest.TestCase):
    def test_acquire_does_not_claim_success_when_durable_write_fails(self) -> None:
        """A configured crash-recovery lease must not become RAM-only silently."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ExecutionLeaseStore(Path(temp_dir) / "execution_leases.json")
            try:
                with patch.object(Path, "write_text", side_effect=OSError("disk unavailable")):
                    result = store.acquire("resource", worker_id="worker-a", ttl_s=60.0)
            except OSError:
                self.assertIsNone(store.lease_snapshot("resource"))
                return

            self.assertFalse(result.get("ok"), result)
            self.assertIsNone(store.lease_snapshot("resource"))


if __name__ == "__main__":
    unittest.main()
