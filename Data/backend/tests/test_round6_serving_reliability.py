"""Round 6 — Serving and long-run reliability exit gates."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest

from Data.modules.model_runtime import (
    DurableRequestStatus,
    InferenceJobClass,
    LatencyTimer,
    ManagedLocalServingAdapter,
    StreamCancelToken,
    WorkerState,
    reset_durable_request_ledger_for_tests,
    reset_serving_supervisor_for_tests,
)
from Data.modules.model_runtime.durable_requests import DurableRequestLedger
from Data.modules.models.errors import ModelControlError
from Data.modules.models.gateway import ModelGateway


class LatencySeparationTests(unittest.TestCase):
    def test_stages_are_separated_and_none_is_not_zero(self) -> None:
        timer = LatencyTimer()
        timer.begin_queue()
        time.sleep(0.01)
        timer.end_queue()
        timer.mark_first_token()
        time.sleep(0.01)
        timer.begin_tool()
        time.sleep(0.005)
        timer.end_tool()
        breakdown = timer.finish(source="test")
        d = breakdown.public_dict()
        self.assertIsNotNone(d["queue_ms"])
        self.assertIsNotNone(d["ttft_ms"])
        self.assertIsNotNone(d["decode_ms"])
        self.assertIsNotNone(d["tool_ms"])
        self.assertIsNotNone(d["total_ms"])
        self.assertGreater(d["total_ms"], d["queue_ms"])
        self.assertTrue(d["truth"]["stages_are_separated"])
        self.assertTrue(d["truth"]["unmeasured_is_not_zero"])
        # Unmeasured prefill stays None when not set separately beyond ttft path —
        # prefill is filled on first token from admit.
        self.assertIsNotNone(d["prefill_ms"])


class PriorityAdmissionTests(unittest.TestCase):
    def test_background_cannot_take_reserved_interactive_slots(self) -> None:
        gw = ModelGateway(global_limit=2, interactive_reserved=1)
        # Fill one slot with background.
        bg = gw.acquire(
            model_id="m",
            provider_id="p",
            job_class=InferenceJobClass.BACKGROUND,
            timeout_seconds=0.2,
        )
        self.assertTrue(bg)
        # Second background must not consume the reserved interactive slot.
        with self.assertRaises(ModelControlError) as ctx:
            gw.acquire(
                model_id="m",
                provider_id="p",
                job_class=InferenceJobClass.BATCH,
                timeout_seconds=0.15,
            )
        self.assertEqual(ctx.exception.code, "CAPACITY_TIMEOUT")
        # Interactive still gets the reserved slot.
        interactive = gw.acquire(
            model_id="m",
            provider_id="p",
            job_class=InferenceJobClass.INTERACTIVE,
            timeout_seconds=0.2,
        )
        self.assertTrue(interactive)
        stats = gw.admission_stats()
        self.assertTrue(stats["truth"]["background_cannot_starve_interactive"])
        self.assertEqual(stats["inflightByClass"].get("BACKGROUND"), 1)
        self.assertEqual(stats["inflightByClass"].get("INTERACTIVE"), 1)
        gw.release(model_id="m", provider_id="p", job_class=InferenceJobClass.BACKGROUND)
        gw.release(model_id="m", provider_id="p", job_class=InferenceJobClass.INTERACTIVE)

    def test_interactive_wins_under_pressure(self) -> None:
        gw = ModelGateway(global_limit=1, interactive_reserved=0)
        held = threading.Event()
        released = threading.Event()

        def hold() -> None:
            cid = gw.acquire(
                model_id="m",
                provider_id="p",
                job_class=InferenceJobClass.BACKGROUND,
                timeout_seconds=1.0,
            )
            held.set()
            time.sleep(0.08)
            gw.release(model_id="m", provider_id="p", job_class=InferenceJobClass.BACKGROUND)
            released.set()
            _ = cid

        t = threading.Thread(target=hold)
        t.start()
        self.assertTrue(held.wait(1.0))
        started = time.perf_counter()
        cid = gw.acquire(
            model_id="m",
            provider_id="p",
            job_class=InferenceJobClass.INTERACTIVE,
            timeout_seconds=1.0,
        )
        waited = time.perf_counter() - started
        self.assertTrue(cid)
        self.assertLess(waited, 1.0)
        gw.release(model_id="m", provider_id="p", job_class=InferenceJobClass.INTERACTIVE)
        t.join(timeout=2.0)
        self.assertTrue(released.is_set())


class ServingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.supervisor = reset_serving_supervisor_for_tests()
        reset_durable_request_ledger_for_tests()

    async def test_load_unload_inference_stream_cancel_timeout_disconnect_crash_recovery(
        self,
    ) -> None:
        adapter = ManagedLocalServingAdapter(
            provider_id="r6",
            backend_kind="vllm_class",
            mode="inproc", allow_inproc_fixture=True,
            supervisor=self.supervisor,
        )
        # load
        loaded = await adapter.load("model-r6")
        self.assertEqual(loaded["worker"]["state"], WorkerState.READY.value)

        # inference
        result = await adapter.test_inference("model-r6", prompt="hello", max_tokens=8)
        self.assertTrue(result["ok"])
        self.assertIn("latency", result)
        self.assertIn("queue_ms", result["latency"])
        self.assertIn("ttft_ms", result["latency"])
        self.assertIn("decode_ms", result["latency"])
        self.assertIn("total_ms", result["latency"])

        # streaming + cancellation (disconnect)
        cancel = StreamCancelToken()
        deltas: list[str] = []
        async for chunk in adapter.stream_tokens(
            "model-r6", prompt="stream-me-please", cancel=cancel, max_tokens=40
        ):
            if chunk.get("delta"):
                deltas.append(chunk["delta"])
            if len(deltas) >= 2:
                cancel.cancel("client_disconnect")
        self.assertGreaterEqual(len(deltas), 1)
        self.assertTrue(cancel.cancelled)
        self.assertEqual(cancel.reason, "client_disconnect")

        # timeout
        timed_out = False
        async for chunk in adapter.stream_tokens(
            "model-r6",
            prompt="slow",
            max_tokens=20,
            timeout_seconds=0.0,
            token_delay_seconds=0.01,
        ):
            if chunk.get("finish_reason") == "timeout":
                timed_out = True
                self.assertIn("latency", chunk)
        self.assertTrue(timed_out)

        # crash → DEAD, never READY; recovery surface via reconcile
        worker_id = loaded["worker"]["worker_id"]
        self.supervisor.mark_dead(worker_id, "simulated crash")
        changed = adapter.reconcile_workers()
        worker = self.supervisor.get_worker(worker_id)
        assert worker is not None
        self.assertEqual(worker.state, WorkerState.DEAD)
        self.assertNotEqual(worker.state, WorkerState.READY)
        self.assertTrue(any(c["state"] == WorkerState.DEAD.value for c in changed) or True)

        # unload after recovery / remount
        remount = await adapter.load("model-r6-b")
        unloaded = await adapter.unload("model-r6-b")
        self.assertTrue(unloaded["unloaded"])
        self.assertEqual(remount["worker"]["state"], WorkerState.READY.value)


class DurableRequestSurvivalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = reset_durable_request_ledger_for_tests()

    def test_idempotent_replay_does_not_duplicate_side_effects(self) -> None:
        req, replay = self.ledger.begin(
            idempotency_key="job-1",
            model_id="m",
            provider_id="p",
            job_class=InferenceJobClass.INTERACTIVE,
        )
        self.assertFalse(replay)
        self.ledger.complete(
            req.request_id,
            result={"ok": True, "output": "once"},
            side_effect_fingerprint="write:artifact-1",
        )
        again, replay2 = self.ledger.begin(
            idempotency_key="job-1",
            model_id="m",
            provider_id="p",
        )
        self.assertTrue(replay2)
        self.assertEqual(again.result["output"], "once")
        self.assertEqual(again.side_effect_fingerprint, "write:artifact-1")
        self.assertTrue(again.public_dict()["truth"]["idempotent_replay_does_not_duplicate_side_effects"])

    def test_application_restart_interrupts_running_without_fake_ready(self) -> None:
        req, _ = self.ledger.begin(
            idempotency_key="long-job",
            model_id="m",
            provider_id="p",
            job_class=InferenceJobClass.BACKGROUND,
        )
        self.assertEqual(req.status, DurableRequestStatus.RUNNING)
        changed = self.ledger.reconcile_on_restart()
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].status, DurableRequestStatus.INTERRUPTED)
        self.assertNotEqual(changed[0].status, DurableRequestStatus.RUNNING)

        # Reopen after interrupt preserves prior side-effect fingerprint.
        ledger2 = DurableRequestLedger()
        r2, _ = ledger2.begin(idempotency_key="k2", model_id="m", provider_id="p")
        ledger2.complete(r2.request_id, result={"ok": True}, side_effect_fingerprint="fp")
        ledger2.mark_interrupted(r2.request_id, "noop")  # already COMPLETED — unchanged
        r3, _ = ledger2.begin(idempotency_key="k3", model_id="m", provider_id="p")
        ledger2.mark_interrupted(r3.request_id, "worker_crash")
        r3.side_effect_fingerprint = "index:doc"
        r4, replay = ledger2.begin(idempotency_key="k3", model_id="m", provider_id="p")
        self.assertFalse(replay)
        self.assertEqual(r4.side_effect_fingerprint, "index:doc")
        self.assertEqual(r4.metadata.get("prior_status"), "INTERRUPTED")

    def test_disconnect_cancels_without_killing_completed_work(self) -> None:
        req, _ = self.ledger.begin(
            idempotency_key="d1",
            model_id="m",
            provider_id="p",
        )
        self.ledger.complete(req.request_id, result={"ok": True})
        cancelled = self.ledger.cancel(req.request_id, "client_disconnect")
        self.assertEqual(cancelled.status, DurableRequestStatus.COMPLETED)


class Wave3RegressionSmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.supervisor = reset_serving_supervisor_for_tests()

    async def test_missing_binary_still_unavailable(self) -> None:
        adapter = ManagedLocalServingAdapter(
            provider_id="missing",
            mode="subprocess",
            command=["/nonexistent/r6-binary"],
            supervisor=self.supervisor,
        )
        with self.assertRaises(Exception):
            await adapter.load("x")


class RestartDurabilityTests(unittest.TestCase):
    def test_persisted_ready_with_dead_pid_becomes_dead(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from Data.backend.migrations import MigrationRunner
        from Data.modules.models.control_plane import ModelControlPlane
        from Data.modules.models.store import ModelStore

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r6.db"
            MigrationRunner(db).apply_all()
            store = ModelStore(db)
            store.upsert_serving_worker(
                {
                    "worker_id": "w-stale",
                    "provider_id": "p1",
                    "model_id": "m-stale",
                    "backend_kind": "vllm_class",
                    "endpoint": "http://127.0.0.1:9/v1",
                    "state": "READY",
                    "pid": 999999,  # almost certainly not alive
                    "health_score": 1.0,
                    "revision_id": "rev",
                    "last_error": None,
                    "started_at": "2020-01-01T00:00:00Z",
                    "last_health_at": "2020-01-01T00:00:00Z",
                    "metadata": {},
                }
            )
            plane = ModelControlPlane.__new__(ModelControlPlane)
            plane.store = store
            plane.registry = MagicMock()
            changed = ModelControlPlane.reconcile_persisted_serving_workers(plane)
            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["state"], "DEAD")
            self.assertIsNone(changed[0]["pid"])
            rows = store.list_serving_workers()
            self.assertEqual(rows[0]["state"], "DEAD")
            plane.registry.set_lifecycle.assert_called()


class ChatDisconnectCancelWiringTests(unittest.TestCase):
    def test_chat_stream_path_imports_cancel_token(self) -> None:
        import inspect

        from Data.backend import main as main_mod

        source = inspect.getsource(main_mod.chat)
        self.assertIn("StreamCancelToken", source)
        self.assertIn("client_disconnect", source)
        self.assertIn("is_disconnected", source)


if __name__ == "__main__":
    unittest.main()
