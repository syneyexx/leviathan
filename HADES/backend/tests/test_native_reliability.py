"""Additional native bridge reliability tests: timeout cancel, crash recovery, overload honesty."""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_runtime import NativeRuntimeClient, NativeRuntimeError, locate_native_executable, set_native_client

REPO = Path(__file__).resolve().parents[2]
NATIVE_BIN = locate_native_executable(REPO) or (REPO / "runtime" / "native" / "hades_native_runtime")
HAS_BIN = NATIVE_BIN.is_file() if isinstance(NATIVE_BIN, Path) else False


@unittest.skipUnless(HAS_BIN, "native binary required")
class NativeReliabilityTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_native_client(None)

    def test_timeout_attempts_cancel(self) -> None:
        client = NativeRuntimeClient(executable=Path(NATIVE_BIN), mode="auto", repo=REPO)
        self.assertTrue(client.ensure_started())
        cancelled = {"hit": False}
        original = client._transport.call

        def wrapped(method, params=None, *, timeout_s=None, on_timeout=None):
            if method == "process.cancel":
                cancelled["hit"] = True
            return original(method, params, timeout_s=timeout_s, on_timeout=on_timeout)

        client._transport.call = wrapped  # type: ignore[method-assign]
        with self.assertRaises(NativeRuntimeError) as ctx:
            # Very short Python waiter vs long native sleep — must cancel native job
            client.call(
                "process.run",
                {
                    "executable": "/bin/sh",
                    "argv": ["-c", "sleep 5"],
                    "timeout_ms": 10000,
                    "job_id": "py-timeout-cancel-1",
                },
                timeout_s=0.2,
            )
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertTrue(cancelled["hit"], "Python timeout must attempt process.cancel")
        client.shutdown()

    def test_health_exposes_executor_fields(self) -> None:
        client = NativeRuntimeClient(executable=Path(NATIVE_BIN), mode="auto", repo=REPO)
        self.assertTrue(client.ensure_started())
        health = client.health()
        self.assertIn("active_jobs", health)
        caps = client.capabilities()
        self.assertTrue(caps.get("bounded_executor"))
        self.assertFalse(caps.get("memory_limit"))  # honest: not implemented
        status = client.status()
        self.assertIsNotNone(status.generation)
        client.shutdown()

    def test_crash_marks_pending_failed(self) -> None:
        client = NativeRuntimeClient(executable=Path(NATIVE_BIN), mode="auto", repo=REPO)
        self.assertTrue(client.ensure_started())
        errors: list[BaseException] = []

        def slow():
            try:
                client.call(
                    "process.run",
                    {"executable": "/bin/sh", "argv": ["-c", "sleep 8"], "timeout_ms": 20000, "job_id": "crash-job"},
                    timeout_s=15,
                )
            except BaseException as exc:  # noqa: BLE001 — collect for assertion
                errors.append(exc)

        t = threading.Thread(target=slow)
        t.start()
        time.sleep(0.15)
        # Kill companion underneath the client
        proc = client._supervisor._proc  # noqa: SLF001
        self.assertIsNotNone(proc)
        assert proc is not None
        proc.kill()
        t.join(timeout=10)
        self.assertTrue(errors, "pending RPC must fail when native crashes")
        self.assertIsInstance(errors[0], NativeRuntimeError)
        recon = client.reconcile_services_after_restart()
        self.assertTrue(recon.get("requires_reconciliation"))
        client.shutdown()


if __name__ == "__main__":
    unittest.main()
