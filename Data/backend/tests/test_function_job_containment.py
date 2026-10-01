"""Regression: FunctionRuntime timeout + JobStore idempotent create races."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from Data.modules.function_runtime import (
    FunctionCallStatus,
    FunctionDefinition,
    FunctionRegistry,
    FunctionRuntime,
    LifecycleMode,
    SideEffect,
)
from Data.modules.jobs.store import JobStore


def _hang(**_kwargs):
    time.sleep(30)
    return {"ok": True}


class FunctionRuntimeTimeoutTests(unittest.TestCase):
    def test_timeout_does_not_block_on_pool_shutdown(self) -> None:
        registry = FunctionRegistry()
        registry.register(
            FunctionDefinition(
                id="test.hang",
                name="Hang",
                version="1.0.0",
                description="hangs",
                entrypoint="Data.backend.tests.test_function_job_containment:_hang",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
                timeout_seconds=0.2,
                lifecycle_mode=LifecycleMode.ON_DEMAND,
                side_effects=(SideEffect.READ,),
            )
        )
        # Resolve via direct callable injection to avoid import path issues.
        runtime = FunctionRuntime(registry, max_concurrency=1, warm_cache_size=0)

        def _resolve(definition):
            return _hang, False

        runtime._resolve_callable = _resolve  # type: ignore[method-assign]
        started = time.perf_counter()
        result = runtime.execute("test.hang", {})
        elapsed = time.perf_counter() - started
        self.assertEqual(result.status, FunctionCallStatus.TIMEOUT)
        self.assertLess(elapsed, 5.0, msg="must not wait for hung thread via pool contextmanager")
        self.assertTrue(result.telemetry.get("uncertain"))
        self.assertTrue(result.telemetry.get("work_may_continue"))
        self.assertEqual(result.telemetry.get("timeout_seconds"), 0.2)


class JobStoreIdempotencyRaceTests(unittest.TestCase):
    def test_concurrent_create_same_key_reuses_one_job(self) -> None:
        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.db")
            store.initialize()
            barrier = threading.Barrier(8)
            results: list = []
            lock = threading.Lock()

            def worker() -> None:
                barrier.wait(timeout=5)
                job = store.create(
                    capability_id="test.cap",
                    arguments={"n": 1},
                    idempotency_key="race-key-1",
                    requested_by="test",
                )
                with lock:
                    results.append(job.job_id)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertEqual(len(results), 8)
            self.assertEqual(len(set(results)), 1)


if __name__ == "__main__":
    unittest.main()
