from __future__ import annotations

import unittest
from unittest.mock import patch

from run_leases import ExecutionLeaseStore


class RunLeaseExpiryTests(unittest.TestCase):
    def test_expired_holder_cannot_renew_before_reclaim_pass(self) -> None:
        leases = ExecutionLeaseStore()
        with patch("run_leases.time.time", return_value=100.0):
            first = leases.acquire("resource", worker_id="worker-a", ttl_s=5.0)
        self.assertTrue(first["ok"])

        with patch("run_leases.time.time", return_value=106.0):
            renewed = leases.renew(
                "resource",
                worker_id="worker-a",
                ttl_s=5.0,
                fence_token=first["fence_token"],
                generation=first["generation"],
            )
            self.assertFalse(renewed["ok"])
            self.assertEqual(renewed["reason"], "expired")

            takeover = leases.compare_and_set_holder(
                "resource",
                expected_worker_id=None,
                new_worker_id="worker-b",
                ttl_s=5.0,
            )
        self.assertTrue(takeover["ok"])
        self.assertGreater(takeover["generation"], first["generation"])

    def test_live_holder_can_still_renew(self) -> None:
        leases = ExecutionLeaseStore()
        with patch("run_leases.time.time", return_value=200.0):
            first = leases.acquire("resource", worker_id="worker-a", ttl_s=10.0)
        with patch("run_leases.time.time", return_value=205.0):
            renewed = leases.renew(
                "resource",
                worker_id="worker-a",
                ttl_s=10.0,
                fence_token=first["fence_token"],
                generation=first["generation"],
            )
        self.assertTrue(renewed["ok"])
        self.assertEqual(renewed["lease"]["expires_at"], 215.0)


if __name__ == "__main__":
    unittest.main()
