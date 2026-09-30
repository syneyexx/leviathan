"""model_runtime cold-start / scale-to-zero enqueue contract tests.

Proves the historical deadlock is fixed:
  require-READY-before-enqueue + scale-to-zero → no queue demand → never wakes.

Preferred contract: cold but supervisor-backed pools ACCEPT queued jobs so
Worker Fabric demand gating can spawn the singleton worker.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from Data.modules.model_runtime.facade import ModelRuntimeClient
from Data.modules.model_runtime.readiness import (
    ModelRuntimePoolAvailability,
    model_runtime_can_accept_jobs,
    model_runtime_readiness_snapshot,
    model_runtime_workers_ready,
)
from Data.modules.models.errors import MODEL_RUNTIME_UNAVAILABLE, ModelControlError
from Data.modules.workers.protocol import SupervisorHealth, WorkerInstanceState
from Data.modules.workers.registry import WorkerRegistry
from Data.modules.workers.settings import WorkerSettings


def _future_iso(seconds: float = 60.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def _past_iso(seconds: float = 60.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


class ModelRuntimeColdStartReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "control.db"
        self.registry = WorkerRegistry(self.db_path)
        self.registry.initialize()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _settings(self, **overrides) -> WorkerSettings:
        base = {
            "enabled": True,
            "supervisor_enabled": True,
            "scale_to_zero_enabled": True,
            "pool_counts": {"model_runtime": 1},
        }
        base.update(overrides)
        return WorkerSettings(**base)

    def _write_supervisor_lease(
        self,
        *,
        health: str = SupervisorHealth.RUNNING.value,
        holder_id: str = "supervisor-1",
        holder_pid: int = 4242,
        expires_at: str | None = None,
        degraded_reason: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expires = expires_at or _future_iso(30)

        def _do() -> None:
            with self.registry.connect() as conn:
                self.registry._ensure_lease_health_columns(conn)
                conn.execute(
                    """
                    INSERT INTO supervisor_leases(
                        lease_id, holder_id, holder_pid, process_start_identity,
                        acquired_at, expires_at, last_heartbeat_at,
                        health_state, consecutive_tick_failures, last_tick_error,
                        restart_count, degraded_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, ?)
                    ON CONFLICT(lease_id) DO UPDATE SET
                        holder_id=excluded.holder_id,
                        holder_pid=excluded.holder_pid,
                        process_start_identity=excluded.process_start_identity,
                        acquired_at=excluded.acquired_at,
                        expires_at=excluded.expires_at,
                        last_heartbeat_at=excluded.last_heartbeat_at,
                        health_state=excluded.health_state,
                        degraded_reason=excluded.degraded_reason
                    """,
                    (
                        "generic-worker-supervisor",
                        holder_id,
                        holder_pid,
                        "test",
                        now,
                        expires,
                        now,
                        health,
                        degraded_reason,
                    ),
                )

        from Data.modules.workers.sqlite_support import run_with_busy_retry

        run_with_busy_retry(_do)

    def test_cold_pool_with_healthy_supervisor_accepts_jobs(self) -> None:
        self._write_supervisor_lease()
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ), mock.patch(
            "Data.modules.common.process.pid_is_alive",
            return_value=True,
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertEqual(snap["poolState"], ModelRuntimePoolAvailability.COLD.value)
            self.assertTrue(snap["acceptJobs"])
            self.assertTrue(snap["cold"])
            self.assertFalse(snap["warm"])
            self.assertTrue(model_runtime_can_accept_jobs(self.db_path))
            # Warm-only helper remains false — cold is not READY.
            self.assertFalse(model_runtime_workers_ready(self.db_path))

    def test_warm_worker_ready(self) -> None:
        self._write_supervisor_lease()
        from Data.modules.workers.protocol import WorkerRegistration

        self.registry.upsert(
            WorkerRegistration(
                worker_id="model_runtime-0",
                pool_id="model_runtime",
                slot=0,
                pid=9999,
                process_start_identity="test",
                state=WorkerInstanceState.READY,
            )
        )
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ), mock.patch(
            "Data.modules.common.process.pid_is_alive",
            return_value=True,
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertEqual(snap["poolState"], ModelRuntimePoolAvailability.READY.value)
            self.assertTrue(snap["acceptJobs"])
            self.assertTrue(model_runtime_workers_ready(self.db_path))

    def test_supervisor_absent_refuses(self) -> None:
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertEqual(
                snap["poolState"],
                ModelRuntimePoolAvailability.SUPERVISOR_UNAVAILABLE.value,
            )
            self.assertFalse(snap["acceptJobs"])
            self.assertFalse(model_runtime_can_accept_jobs(self.db_path))

    def test_supervisor_expired_refuses(self) -> None:
        self._write_supervisor_lease(expires_at=_past_iso(10))
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ), mock.patch(
            "Data.modules.common.process.pid_is_alive",
            return_value=True,
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertFalse(snap["acceptJobs"])
            self.assertIn("expired", snap["reason"])

    def test_parent_bootstrap_degraded_refuses(self) -> None:
        self._write_supervisor_lease(
            health=SupervisorHealth.DEGRADED.value,
            holder_id="parent-bootstrap",
            holder_pid=0,
            degraded_reason="supervisor restart budget exhausted",
        )
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertFalse(snap["acceptJobs"])

    def test_pool_disabled_refuses(self) -> None:
        self._write_supervisor_lease()
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(pool_counts={"model_runtime": 0}),
        ), mock.patch(
            "Data.modules.common.process.pid_is_alive",
            return_value=True,
        ):
            snap = model_runtime_readiness_snapshot(self.db_path)
            self.assertEqual(snap["poolState"], ModelRuntimePoolAvailability.DISABLED.value)
            self.assertFalse(snap["acceptJobs"])

    def test_facade_enqueue_allowed_when_cold(self) -> None:
        self._write_supervisor_lease()
        enqueued: list[dict] = []

        class FakeJobRuntime:
            store = type("S", (), {"path": self.db_path})()

            def enqueue(self, **kwargs):
                enqueued.append(kwargs)
                return type("Job", (), {"job_id": "j1", "state": "QUEUED"})()

        client = ModelRuntimeClient(FakeJobRuntime())
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ), mock.patch(
            "Data.modules.common.process.pid_is_alive",
            return_value=True,
        ):
            job = client.submit_load(model_id="m1", options={"contextLength": 4096})
            self.assertEqual(getattr(job, "job_id", None), "j1")
            self.assertEqual(len(enqueued), 1)
            self.assertEqual(enqueued[0]["worker_pool"], "model_runtime")

    def test_facade_enqueue_refuses_without_supervisor(self) -> None:
        class FakeJobRuntime:
            store = type("S", (), {"path": self.db_path})()

            def enqueue(self, **kwargs):  # pragma: no cover
                raise AssertionError("must not enqueue")

        client = ModelRuntimeClient(FakeJobRuntime())
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=self._settings(),
        ):
            with self.assertRaises(ModelControlError) as ctx:
                client.submit_load(model_id="m1")
            self.assertEqual(ctx.exception.code, MODEL_RUNTIME_UNAVAILABLE)
            self.assertIn("supervisor", ctx.exception.message.lower())

    def test_scale_to_zero_desired_wakes_on_queued(self) -> None:
        # Eligible pools still wake on demand; model_runtime is now exempt (warm).
        settings = self._settings()
        self.assertFalse(settings.is_scale_to_zero_eligible("model_runtime"))
        self.assertEqual(
            settings.scale_to_zero_desired(
                "model_runtime", queued=0, busy=0, idle_seconds=9999, configured=1
            ),
            1,
        )
        # Research remains demand-gated.
        self.assertTrue(settings.is_scale_to_zero_eligible("research"))
        self.assertEqual(
            settings.scale_to_zero_desired(
                "research", queued=0, busy=0, idle_seconds=9999, configured=1
            ),
            0,
        )
        self.assertEqual(
            settings.scale_to_zero_desired(
                "research", queued=1, busy=0, idle_seconds=0, configured=1
            ),
            1,
        )

    def test_model_runtime_remains_singleton(self) -> None:
        from Data.modules.workers.pools import POOL_CATALOG

        defn = POOL_CATALOG["model_runtime"]
        self.assertEqual(defn.max_count, 1)
        self.assertEqual(defn.default_count, 1)

    def test_model_runtime_exempt_from_scale_to_zero(self) -> None:
        settings = self._settings()
        self.assertIn("model_runtime", settings.scale_to_zero_exempt_pools)
        self.assertFalse(settings.is_scale_to_zero_eligible("model_runtime"))


if __name__ == "__main__":
    unittest.main()
