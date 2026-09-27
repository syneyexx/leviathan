"""Wave 4 — lease fencing helpers fail closed."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from Data.modules.jobs.leases import (
    LeaseFenceError,
    make_lease_bound_checks,
    observe_job_cancel_state,
    require_lease_heartbeat,
)
from Data.modules.jobs.states import JobState


class LeaseFencingTests(unittest.TestCase):
    def test_cancel_state_read_failure_fails_closed(self) -> None:
        store = mock.Mock()
        store.get.side_effect = RuntimeError("db busy")
        ctx: dict = {}
        self.assertTrue(observe_job_cancel_state(store, "j1", worker_id="w1", ctx=ctx))
        self.assertTrue(ctx.get("lease_fenced"))

    def test_missing_job_fails_closed(self) -> None:
        store = mock.Mock()
        store.get.return_value = None
        self.assertTrue(observe_job_cancel_state(store, "j1", worker_id="w1"))

    def test_heartbeat_failure_raises_fence(self) -> None:
        store = mock.Mock()
        store.heartbeat_lease.side_effect = ValueError("lost")
        with self.assertRaises(LeaseFenceError):
            require_lease_heartbeat(store, "j1", worker_id="w1", ttl_seconds=30.0)

    def test_lease_bound_cancel_check_on_owner_mismatch(self) -> None:
        store = mock.Mock()
        store.get.return_value = SimpleNamespace(
            state=JobState.RUNNING,
            lease_owner="other-worker",
        )
        cancel_check, _heartbeat = make_lease_bound_checks(
            {},
            store,
            "j1",
            worker_id="w1",
            ttl_seconds=30.0,
        )
        self.assertTrue(cancel_check())


if __name__ == "__main__":
    unittest.main()
