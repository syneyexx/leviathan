"""Provider I/O execution plane — unit and acceptance tests.

Uses a local fake HTTP provider. Never calls paid external APIs.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.provider_io.credentials import assert_no_secrets_in_payload, store_ephemeral_token
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.executor import ProviderIoExecutor
from Data.modules.provider_io.facade import ProviderExecutionClient
from Data.modules.provider_io.policy import (
    CircuitBreaker,
    CircuitState,
    DeadlineBudget,
    ProviderPolicyRegistry,
)
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeProviderState:
    def __init__(self) -> None:
        self.delay_seconds = 0.05
        self.fail_count = 0
        self.calls = 0
        self.stream_tokens = ["Hello", ", ", "world"]
        self.lock = threading.Lock()
        self.pids: list[int] = []


FAKE = _FakeProviderState()


class _FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/v1/models"):
            body = b'{"data":[{"id":"fake-model"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        with FAKE.lock:
            FAKE.calls += 1
            FAKE.pids.append(os.getpid())
            fail = FAKE.fail_count > 0
            if fail:
                FAKE.fail_count -= 1
            delay = FAKE.delay_seconds
            tokens = list(FAKE.stream_tokens)
        time.sleep(delay)
        if fail:
            body = b'{"error":{"message":"transient"}}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i, tok in enumerate(tokens):
                chunk = {
                    "id": "chatcmpl-fake",
                    "model": "fake-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": tok},
                            "finish_reason": "stop" if i == len(tokens) - 1 else None,
                        }
                    ],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.01)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        text = "".join(tokens)
        body = json.dumps(
            {
                "id": "chatcmpl-fake",
                "model": "fake-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_fake_server() -> tuple[ThreadingHTTPServer, str]:
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/v1"


class PoolRoutingTests(unittest.TestCase):
    def test_provider_capabilities_map_to_provider_io(self) -> None:
        self.assertEqual(pool_for_capability("provider.http"), "provider_io")
        self.assertEqual(pool_for_capability("provider.chat.complete"), "provider_io")
        self.assertEqual(pool_for_capability("provider.chat.stream"), "provider_io")
        self.assertEqual(pool_for_capability("provider.market.fetch"), "provider_io")
        self.assertEqual(pool_for_capability("provider.hf.list"), "provider_io")
        self.assertEqual(pool_for_capability("provider.alpaca.paper"), "provider_io")
        self.assertEqual(pool_for_capability("model_download.start"), "model_download")
        self.assertEqual(pool_for_capability("mcp.call"), "mcp_execution")

    def test_domain_jobs_not_stolen_by_provider_prefix(self) -> None:
        self.assertEqual(pool_for_capability("research.advance"), "research")
        self.assertEqual(pool_for_capability("dataset.process"), "dataset")
        self.assertEqual(pool_for_capability("source_ingestion.process"), "source_ingestion")
        self.assertEqual(pool_for_capability("embedding.batch"), "embedding")
        self.assertEqual(pool_for_capability("agent.advance"), "agents")

    def test_catalog_contains_provider_io(self) -> None:
        self.assertIn("provider_io", POOL_CATALOG)
        self.assertIn("model_download", POOL_CATALOG)
        self.assertIn("mcp_execution", POOL_CATALOG)
        defn = POOL_CATALOG["provider_io"]
        self.assertEqual(defn.default_count, 2)
        self.assertIn("NETWORK_BOUND", defn.resource_classes)
        self.assertTrue(defn.entrypoint.endswith("provider_io"))
        self.assertEqual(POOL_CATALOG["model_download"].default_count, 1)

    def test_external_capabilities_include_provider(self) -> None:
        self.assertIn("provider.http", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("provider.chat.complete", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("provider.alpaca.paper", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("model_download.start", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("mcp.call", EXTERNAL_WORKER_CAPABILITIES)
        catalog = build_default_catalog()
        self.assertIsNotNone(catalog.get("provider.http"))
        self.assertIsNotNone(catalog.get("provider.chat.stream"))
        self.assertIsNotNone(catalog.get("model_download.start"))
        self.assertIsNotNone(catalog.get("mcp.call"))


class PolicyTests(unittest.TestCase):
    def test_circuit_opens_and_recovers(self) -> None:
        br = CircuitBreaker("demo", failure_threshold=2, cooldown_seconds=0.05)
        br.allow()
        br.record_failure()
        br.allow()
        br.record_failure()
        self.assertEqual(br.state, CircuitState.OPEN)
        with self.assertRaises(ProviderError) as ctx:
            br.allow()
        self.assertEqual(ctx.exception.code, ProviderErrorCode.PROVIDER_CIRCUIT_OPEN)
        time.sleep(0.06)
        br.allow()  # half-open
        self.assertEqual(br.state, CircuitState.HALF_OPEN)
        br.record_success()
        self.assertEqual(br.state, CircuitState.CLOSED)

    def test_deadline_budget_not_reset_per_attempt(self) -> None:
        budget = DeadlineBudget(total_seconds=0.2)
        time.sleep(0.05)
        rem1 = budget.remaining()
        time.sleep(0.05)
        rem2 = budget.remaining()
        self.assertLess(rem2, rem1)
        time.sleep(0.15)
        with self.assertRaises(ProviderError):
            budget.raise_if_exhausted()

    def test_no_retry_after_output(self) -> None:
        reg = ProviderPolicyRegistry()
        err = ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE, "x", retryable=True
        )
        budget = DeadlineBudget(total_seconds=30)
        self.assertFalse(
            reg.should_retry(
                err,
                attempt=0,
                emitted_output=True,
                budget=budget,
                idempotency_class="READ",
            )
        )

    def test_secrets_rejected_in_payload(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_secrets_in_payload({"api_key": "sk-test"})
        with self.assertRaises(ValueError):
            assert_no_secrets_in_payload({"prompt": "sk-live-abcdef"})


class ProviderExecutorUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.store = JobStore(self.db)
        self.store.initialize()
        self.gateway = type("G", (), {"get_capability": lambda self, cid: object()})()
        # Use real catalog for enqueue validation
        from Data.modules.execution import ExecutionGateway

        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(8),
        )
        self.server, self.base = _start_fake_server()
        FAKE.delay_seconds = 0.02
        FAKE.fail_count = 0
        FAKE.calls = 0
        FAKE.pids = []
        os.environ["LEVIATHAN_PROVIDER_CREDENTIAL_DIR"] = str(Path(self.tmp.name) / "creds")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.tmp.cleanup()

    def _ctx(self) -> dict:
        return {
            "job_store": self.store,
            "settings": type("S", (), {"database_path": self.db})(),
            "worker_id": f"test-{os.getpid()}",
            "lease_ttl_seconds": 30.0,
        }

    def test_http_complete_in_executor(self) -> None:
        job = self.runtime.enqueue(
            capability_id="provider.chat.complete",
            arguments={
                "provider": "fake",
                "capability": "chat.complete",
                "model": "fake-model",
                "allow_private_hosts": True,
                "credential_ref": "none",
                "payload": {
                    "endpoint": self.base,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            },
            worker_pool="provider_io",
        )
        # Claim as worker would
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="w1", lease_ttl_seconds=30.0
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            result = executor.execute_job(self._ctx(), claimed)
        finally:
            executor.close()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["content"], "Hello, world")
        self.assertEqual(result["worker_pid"], os.getpid())
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)

    def test_stream_emits_ordered_deltas(self) -> None:
        job = self.runtime.enqueue(
            capability_id="provider.chat.stream",
            arguments={
                "provider": "fake",
                "capability": "chat.stream",
                "streaming": True,
                "allow_private_hosts": True,
                "credential_ref": "none",
                "payload": {
                    "endpoint": self.base,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            },
            worker_pool="provider_io",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="w1", lease_ttl_seconds=30.0
        )
        assert claimed is not None
        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            result = executor.execute_job(self._ctx(), claimed)
        finally:
            executor.close()
        self.assertEqual(result["status"], "succeeded")
        events = executor.stream_store.read_after(job.job_id, 0, limit=50)
        types = [e.event_type.value for e in events]
        self.assertIn("started", types)
        self.assertIn("delta", types)
        self.assertIn("completed", types)
        deltas = [e for e in events if e.event_type.value == "delta"]
        text = "".join(str(e.payload.get("text") or "") for e in deltas)
        self.assertEqual(text, "Hello, world")
        seqs = [e.sequence for e in events]
        self.assertEqual(seqs, sorted(seqs))

    def test_ssrf_blocks_metadata(self) -> None:
        job = self.runtime.enqueue(
            capability_id="provider.http",
            arguments={
                "provider": "evil",
                "capability": "http",
                "payload": {"url": "http://169.254.169.254/latest/meta-data"},
                "credential_ref": "none",
            },
            worker_pool="provider_io",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="w1", lease_ttl_seconds=30.0
        )
        assert claimed is not None
        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            result = executor.execute_job(self._ctx(), claimed)
        finally:
            executor.close()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "SSRF_BLOCKED")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.FAILED)

    def test_retry_on_503_then_success(self) -> None:
        FAKE.fail_count = 1
        job = self.runtime.enqueue(
            capability_id="provider.chat.complete",
            arguments={
                "provider": "fake",
                "capability": "chat.complete",
                "allow_private_hosts": True,
                "credential_ref": "none",
                "payload": {
                    "endpoint": self.base,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            },
            worker_pool="provider_io",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="w1", lease_ttl_seconds=30.0
        )
        assert claimed is not None
        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            result = executor.execute_job(self._ctx(), claimed)
        finally:
            executor.close()
        self.assertEqual(result["status"], "succeeded")
        self.assertGreaterEqual(FAKE.calls, 2)
        self.assertEqual(self.store.get(job.job_id).state, JobState.COMPLETED)  # type: ignore[union-attr]

    def test_ephemeral_credential_not_in_job_json(self) -> None:
        ref = store_ephemeral_token("hf_secret_token_value", prefix="hf")
        self.assertTrue(ref.startswith("ephemeral:"))
        job = self.runtime.enqueue(
            capability_id="provider.http",
            arguments={
                "provider": "huggingface",
                "capability": "http",
                "credential_ref": ref,
                "allow_private_hosts": True,
                "payload": {"url": f"{self.base.replace('/v1', '')}/health", "method": "GET"},
            },
            worker_pool="provider_io",
        )
        raw = json.dumps(job.arguments)
        self.assertNotIn("hf_secret_token_value", raw)


class ProcessIsolationAcceptanceTests(unittest.TestCase):
    """Critical acceptance: provider work PID != control plane PID."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "iso.db"
        self.store = JobStore(self.db)
        self.store.initialize()
        from Data.modules.execution import ExecutionGateway

        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(8),
        )
        self.server, self.base = _start_fake_server()
        FAKE.delay_seconds = 0.3
        FAKE.fail_count = 0
        FAKE.calls = 0
        os.environ["LEVIATHAN_PROVIDER_CREDENTIAL_DIR"] = str(Path(self.tmp.name) / "creds")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.tmp.cleanup()

    def test_provider_executes_in_other_os_process(self) -> None:
        control_pid = os.getpid()
        job = self.runtime.enqueue(
            capability_id="provider.chat.complete",
            arguments={
                "provider": "fake",
                "capability": "chat.complete",
                "allow_private_hosts": True,
                "credential_ref": "none",
                "deadline_seconds": 30,
                "payload": {
                    "endpoint": self.base,
                    "messages": [{"role": "user", "content": "iso"}],
                },
            },
            worker_pool="provider_io",
            timeout_seconds=30,
        )

        worker_script = f"""
import os, sys
sys.path.insert(0, {os.getcwd()!r})
from pathlib import Path
from Data.modules.jobs.store import JobStore
from Data.modules.provider_io.executor import ProviderIoExecutor

db = Path({str(self.db)!r})
store = JobStore(db)
store.initialize()
claimed = store.claim_next_for_pool(pool_id="provider_io", worker_id=f"iso-{{os.getpid()}}", lease_ttl_seconds=60.0)
assert claimed is not None, "no job claimed"
ex = ProviderIoExecutor(db_path=str(db))
ctx = {{"job_store": store, "settings": type("S", (), {{"database_path": db}})(), "worker_id": f"iso-{{os.getpid()}}", "lease_ttl_seconds": 60.0}}
result = ex.execute_job(ctx, claimed)
ex.close()
print("WORKER_PID", os.getpid())
print("RESULT_PID", result.get("worker_pid"))
print("STATUS", result.get("status"))
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", worker_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.getcwd(),
        )

        # While provider work runs, control plane remains responsive (local poll).
        light_ok = 0
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            # Lightweight control-plane operation: DB read + health of fake provider.
            _ = self.store.get(job.job_id)
            try:
                import urllib.request

                with urllib.request.urlopen(
                    self.base.replace("/v1", "") + "/health", timeout=1.0
                ) as resp:
                    if resp.status == 200:
                        light_ok += 1
            except Exception:  # noqa: BLE001
                pass
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        stdout, stderr = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
        self.assertIn("STATUS succeeded", stdout)
        worker_pid = None
        for line in stdout.splitlines():
            if line.startswith("RESULT_PID"):
                worker_pid = int(line.split()[-1])
        self.assertIsNotNone(worker_pid)
        self.assertNotEqual(worker_pid, control_pid)
        self.assertGreaterEqual(light_ok, 1)

        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual(final.result.get("worker_pid"), worker_pid)

    def test_queue_saturation_explicit(self) -> None:
        client = ProviderExecutionClient(self.runtime)
        client.settings = mock.MagicMock(wraps=client.settings)
        # Replace queue capacity
        from Data.modules.provider_io.policy import ProviderIoSettings

        client.settings = ProviderIoSettings(queue_capacity=2)
        # Fill queue without workers
        for i in range(2):
            client.submit(
                provider="fake",
                capability="http",
                payload={"url": f"{self.base.replace('/v1', '')}/health"},
                allow_private_hosts=True,
                credential_ref="none",
            )
        with self.assertRaises(ProviderError) as ctx:
            client.submit(
                provider="fake",
                capability="http",
                payload={"url": f"{self.base.replace('/v1', '')}/health"},
                allow_private_hosts=True,
                credential_ref="none",
            )
        self.assertEqual(ctx.exception.code, ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED)


class BenchmarkSmokeTests(unittest.TestCase):
    """Reproducible local latency smoke — not a paid API benchmark."""

    def test_control_plane_poll_under_provider_delay(self) -> None:
        server, base = _start_fake_server()
        FAKE.delay_seconds = 0.5
        try:
            tmp = tempfile.TemporaryDirectory()
            db = Path(tmp.name) / "b.db"
            store = JobStore(db)
            store.initialize()
            from Data.modules.execution import ExecutionGateway

            runtime = JobRuntime(
                store,
                ExecutionGateway(catalog=build_default_catalog()),
                ResourceManager(8),
            )
            job = runtime.enqueue(
                capability_id="provider.chat.complete",
                arguments={
                    "provider": "fake",
                    "capability": "chat.complete",
                    "allow_private_hosts": True,
                    "credential_ref": "none",
                    "payload": {
                        "endpoint": base,
                        "messages": [{"role": "user", "content": "bench"}],
                    },
                },
                worker_pool="provider_io",
            )
            # Start worker in thread (same process for smoke) — isolation covered above.
            def _run() -> None:
                claimed = store.claim_next_for_pool(
                    pool_id="provider_io", worker_id="bench", lease_ttl_seconds=30
                )
                assert claimed is not None
                ex = ProviderIoExecutor(db_path=str(db))
                try:
                    ex.execute_job(
                        {
                            "job_store": store,
                            "settings": type("S", (), {"database_path": db})(),
                            "worker_id": "bench",
                            "lease_ttl_seconds": 30.0,
                        },
                        claimed,
                    )
                finally:
                    ex.close()

            t = threading.Thread(target=_run)
            t.start()
            latencies = []
            while t.is_alive():
                t0 = time.perf_counter()
                _ = store.get(job.job_id)
                latencies.append((time.perf_counter() - t0) * 1000.0)
                time.sleep(0.02)
            t.join(timeout=10)
            self.assertTrue(latencies)
            p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
            # Control-plane get() should stay well under provider delay (500ms).
            self.assertLess(p95, 100.0, msg=f"p95={p95} latencies={latencies[:10]}")
            tmp.cleanup()
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
