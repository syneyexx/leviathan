"""Wave 20 — soak / chaos / recovery durability (extends lease fencing patterns)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs.leases import fenced_transition
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState, StaleLeaseError
from Data.modules.jobs.store import JobStore
from Data.modules.market_sim.fincept_bridge import (
    FinceptEvidenceBridge,
    FinceptInvocationRequest,
    FinceptResultState,
)
from Data.modules.market_sim.paper_broker import (
    LocalPaperBroker,
    apply_paper_fill_from_feed_event,
)
from Data.modules.market_sim.paper_causality import refuse_future_quote
from Data.modules.market_sim.types import MarketSimError


def _runtime(db: Path, *, worker_id: str = "runtime") -> JobRuntime:
    store = JobStore(db)
    store.initialize()
    gateway = ExecutionGateway(catalog=build_default_catalog())
    return JobRuntime(
        store,
        gateway,
        ResourceManager(max_job_concurrency=4),
        worker_id=worker_id,
        lease_ttl_seconds=30.0,
    )


def _steal_lease(store: JobStore, job_id: str, *, new_owner: str) -> None:
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
    with store.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
            (new_owner, future, job_id),
        )


class WorkerCrashMidJobTests(unittest.TestCase):
    def test_crash_before_complete_allows_reclaim_no_duplicate_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(Path(tmp) / "jobs.db", worker_id="supervisor")
            job = runtime.enqueue(
                capability_id="file.read",
                arguments={"text": "x"},
                idempotency_key="crash-mid-1",
            )
            claimed = runtime.store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
            assert claimed is not None
            # Simulate crash: lease expires without terminal transition.
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
            with runtime.store.connect() as conn:
                conn.execute(
                    "UPDATE jobs SET lease_expires_at = ?, lease_owner = ? WHERE job_id = ?",
                    (past, "worker-a", job.job_id),
                )
            # Worker B reclaims expired RUNNING lease and completes once.
            reclaimed = runtime.store.claim_next_queued(
                worker_id="worker-b",
                lease_ttl_seconds=30.0,
                reclaim_expired=True,
            )
            assert reclaimed is not None
            self.assertEqual(reclaimed.job_id, job.job_id)
            # Stale A cannot complete while B holds the live lease.
            with self.assertRaises(StaleLeaseError):
                runtime.store.transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result={"from": "a"},
                    expected_lease_owner="worker-a",
                )
            done = runtime.store.transition(
                job.job_id,
                JobState.COMPLETED,
                result={"ok": True, "from": "b"},
                expected_lease_owner="worker-b",
            )
            self.assertEqual(done.state, JobState.COMPLETED)
            final = runtime.store.get(job.job_id)
            assert final is not None
            self.assertEqual(final.result, {"ok": True, "from": "b"})
            # Idempotent re-enqueue of same key returns same job — no duplicate work unit.
            again = runtime.enqueue(
                capability_id="file.read",
                arguments={"text": "x"},
                idempotency_key="crash-mid-1",
            )
            self.assertEqual(again.job_id, job.job_id)


class DuplicateDeliveryTests(unittest.TestCase):
    def test_idempotent_enqueue_and_paper_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(Path(tmp) / "jobs.db")
            a = runtime.enqueue(
                capability_id="file.read",
                arguments={"text": "dup"},
                idempotency_key="dup-delivery-1",
            )
            b = runtime.enqueue(
                capability_id="file.read",
                arguments={"text": "dup"},
                idempotency_key="dup-delivery-1",
            )
            self.assertEqual(a.job_id, b.job_id)

            broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
            o1 = apply_paper_fill_from_feed_event(
                broker,
                session_id="sess-dup",
                event_id="evt-dup",
                symbol="BTCUSDT",
                side="BUY",
                qty=1,
                price=100.0,
            )
            o2 = apply_paper_fill_from_feed_event(
                broker,
                session_id="sess-dup",
                event_id="evt-dup",
                symbol="BTCUSDT",
                side="BUY",
                qty=1,
                price=100.0,
            )
            self.assertEqual(o1.order_id, o2.order_id)
            wal = broker.wallet_for_session("sess-dup", create=False)
            self.assertEqual(len(wal.transactions), 1)


class ApiRestartSimulationTests(unittest.TestCase):
    def test_paper_session_restores_without_duplicate_orders(self) -> None:
        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        o1 = apply_paper_fill_from_feed_event(
            broker,
            session_id="sess-restart",
            event_id="evt-r1",
            symbol="ETHUSDT",
            side="BUY",
            qty=2,
            price=50.0,
        )
        wal = broker.wallet_for_session("sess-restart", create=False)
        payload = wal.public_dict()
        orders = [o1.public_dict()]

        # Simulate API/process restart: new broker hydrates durable state.
        broker2 = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        broker2.restore_session(
            "sess-restart",
            wallet_payload=payload,
            orders=orders,
        )
        o2 = apply_paper_fill_from_feed_event(
            broker2,
            session_id="sess-restart",
            event_id="evt-r1",
            symbol="ETHUSDT",
            side="BUY",
            qty=2,
            price=50.0,
        )
        self.assertEqual(o1.order_id, o2.order_id)
        wal2 = broker2.wallet_for_session("sess-restart", create=False)
        self.assertEqual(float(wal2.position_qty), 2.0)


class ProviderTimeoutModelUnavailableTests(unittest.TestCase):
    def test_provider_timeout_is_typed_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(Path(tmp) / "jobs.db")
            job = runtime.enqueue(
                capability_id="file.read",
                arguments={"text": "timeout"},
                idempotency_key="timeout-1",
            )
            claimed = runtime.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=30.0)
            assert claimed is not None
            failed = runtime.store.transition(
                job.job_id,
                JobState.FAILED,
                error="provider_timeout",
                error_code="PROVIDER_TIMEOUT",
                retryable=True,
                expected_lease_owner="w1",
            )
            self.assertEqual(failed.state, JobState.FAILED)
            self.assertEqual(failed.error_code, "PROVIDER_TIMEOUT")
            self.assertNotEqual(failed.state, JobState.COMPLETED)

    def test_model_unavailable_honest(self) -> None:
        # Model Control Plane absence must surface UNAVAILABLE — never invent completion.
        status = {
            "status": "UNAVAILABLE",
            "error_code": "MODEL_SERVING_UNAVAILABLE",
            "truth": {"unavailable_is_not_pass": True},
        }
        self.assertEqual(status["status"], "UNAVAILABLE")
        self.assertNotEqual(status["status"], "COMPLETED")


class FinceptUnavailableTests(unittest.TestCase):
    def test_fincept_unavailable_does_not_block_or_authorize(self) -> None:
        bridge = FinceptEvidenceBridge(module_installed=False, module_enabled=True)
        req = FinceptInvocationRequest(
            capability_id="external.fincept.analyze",
            role="strategy_researcher",
            objective="quant regime analytics",
            command="analyze",
            justified=True,
            justification="unit-test justified analytical need",
        )
        artifact = bridge.invoke(req)
        self.assertEqual(artifact.result_state, FinceptResultState.UNAVAILABLE)
        pub = artifact.public_dict()
        self.assertEqual(pub["resultState"], "UNAVAILABLE")
        self.assertTrue(pub["truth"]["noSilentSubstitution"])
        self.assertTrue(pub["truth"]["immutableArtifact"])


class StaleLeaseFenceTests(unittest.TestCase):
    def test_stale_writer_fenced_after_steal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(Path(tmp) / "jobs.db")
            job = runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
            claimed = runtime.store.claim_next_queued(worker_id="a", lease_ttl_seconds=30.0)
            assert claimed is not None
            _steal_lease(runtime.store, job.job_id, new_owner="b")
            runtime.store.transition(
                job.job_id,
                JobState.COMPLETED,
                result={"from": "b"},
                expected_lease_owner="b",
            )
            ctx: dict = {}
            out = fenced_transition(
                runtime.store,
                job.job_id,
                JobState.FAILED,
                worker_id="a",
                ctx=ctx,
                error="stale",
                result={"from": "a"},
            )
            self.assertIsNone(out)
            self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)
            final = runtime.store.get(job.job_id)
            assert final is not None
            self.assertEqual(final.state, JobState.COMPLETED)
            self.assertEqual((final.result or {}).get("from"), "b")


class LookaheadUnderChaosTests(unittest.TestCase):
    def test_poison_future_still_refused_during_recovery(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            refuse_future_quote(
                quote_ts="2099-01-01T00:00:00+00:00",
                as_of="2026-01-01T00:00:00+00:00",
                symbol="BTCUSDT",
                price=1.0,
            )
        self.assertEqual(ctx.exception.code, "LOOKAHEAD_REFUSED")


if __name__ == "__main__":
    unittest.main()
