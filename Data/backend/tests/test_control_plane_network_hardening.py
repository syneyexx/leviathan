"""Control Plane final network hardening — model download + Alpaca + MCP isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.execution import build_default_catalog
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.jobs.resources import ResourceManager
from Data.modules.model_download.errors import ModelDownloadError, ModelDownloadErrorCode
from Data.modules.model_download.executor import ModelDownloadExecutor, disk_preflight
from Data.modules.model_download.facade import ModelDownloadClient
from Data.modules.models.contracts import DownloadState
from Data.modules.models.downloads import DownloadManager
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.facade import ProviderExecutionClient
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


def _prepare_db(path: Path) -> JobStore:
    MigrationRunner(path).apply_all()
    store = JobStore(path)
    store.initialize()
    return store


class _FakeHFHandler(BaseHTTPRequestHandler):
    delay_seconds = 0.0
    stall = False
    status_override: int | None = None
    body = b"MODELBYTES" * 10000  # ~100KB
    calls = 0

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        type(self).calls += 1
        path = self.path.split("?", 1)[0]
        if self.status_override is not None:
            self.send_response(self.status_override)
            self.end_headers()
            return
        if path.endswith("/tree/main") or "/tree/" in path:
            payload = json.dumps(
                [{"path": "model.gguf", "type": "file", "size": len(self.body)}]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.stall:
            time.sleep(5.0)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        # Range support
        range_hdr = self.headers.get("Range")
        start = 0
        if range_hdr and range_hdr.startswith("bytes="):
            try:
                start = int(range_hdr.split("=", 1)[1].split("-", 1)[0] or 0)
            except ValueError:
                start = 0
        data = self.body[start:]
        status = 206 if start > 0 else 200
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        if start > 0:
            self.send_header(
                "Content-Range", f"bytes {start}-{len(self.body) - 1}/{len(self.body)}"
            )
        self.end_headers()
        # Slow chunked write for responsiveness tests
        chunk = 4096
        for i in range(0, len(data), chunk):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            self.wfile.write(data[i : i + chunk])


class _FakeAlpacaHandler(BaseHTTPRequestHandler):
    delay_seconds = 0.5
    calls = 0

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        type(self).calls += 1
        time.sleep(self.delay_seconds)
        length = int(self.headers.get("Content-Length") or 0)
        _ = self.rfile.read(length)
        payload = json.dumps(
            {"id": "ord-1", "status": "filled", "filled_avg_price": "100.0"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        type(self).calls += 1
        time.sleep(self.delay_seconds)
        payload = json.dumps({"equity": "100000", "cash": "100000", "status": "ACTIVE"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _start_server(handler_cls) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


class PoolRoutingHardeningTests(unittest.TestCase):
    def test_new_pools_and_capabilities(self) -> None:
        self.assertIn("model_download", POOL_CATALOG)
        self.assertIn("mcp_execution", POOL_CATALOG)
        self.assertEqual(pool_for_capability("model_download.start"), "model_download")
        self.assertEqual(pool_for_capability("mcp.call"), "mcp_execution")
        self.assertEqual(pool_for_capability("provider.alpaca.paper"), "provider_io")
        self.assertIn("model_download.start", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("mcp.call", EXTERNAL_WORKER_CAPABILITIES)
        self.assertIn("provider.alpaca.paper", EXTERNAL_WORKER_CAPABILITIES)
        catalog = build_default_catalog()
        self.assertIsNotNone(catalog.get("model_download.start"))
        self.assertIsNotNone(catalog.get("mcp.call"))
        self.assertIsNotNone(catalog.get("provider.alpaca.paper"))


class ModelDownloadExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "md.db"
        self.store = _prepare_db(self.db)
        from Data.modules.execution import ExecutionGateway

        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(8),
        )
        _FakeHFHandler.calls = 0
        _FakeHFHandler.delay_seconds = 0.0
        _FakeHFHandler.stall = False
        _FakeHFHandler.status_override = None
        self.server, self.base = _start_server(_FakeHFHandler)
        self.executor = ModelDownloadExecutor(db_path=self.db)
        # Point HF URLs at fake server via monkeypatch of stream URL construction
        self._orig_http = self.executor._http

    def tearDown(self) -> None:
        self.executor.close()
        self.server.shutdown()
        self.tmp.cleanup()

    def _patch_hf_urls(self):
        """Rewrite huggingface.co URLs to the local fake server."""
        import httpx

        real_client = httpx.Client(timeout=30.0, follow_redirects=True)
        base = self.base

        class ProxyClient:
            def head(self, url, **kwargs):
                return real_client.head(url.replace("https://huggingface.co", base), **kwargs)

            def get(self, url, **kwargs):
                return real_client.get(url.replace("https://huggingface.co", base), **kwargs)

            def stream(self, method, url, **kwargs):
                return real_client.stream(
                    method, url.replace("https://huggingface.co", base), **kwargs
                )

            def close(self):
                real_client.close()

        self.executor._client = ProxyClient()  # type: ignore[assignment]
        return real_client

    def test_download_succeeds_and_registers_model(self) -> None:
        self._patch_hf_urls()
        model_store = ModelStore(self.db)
        download_id = "dl-1"
        dest = self.executor.download_root / "org__model" / "main"
        dest.mkdir(parents=True)
        model_store.upsert_download(
            {
                "download_id": download_id,
                "state": DownloadState.QUEUED.value,
                "source": "huggingface",
                "repository_id": "org/model",
                "revision": "main",
                "destination": str(dest),
            }
        )
        job = self.runtime.enqueue(
            capability_id="model_download.start",
            arguments={
                "download_id": download_id,
                "source": "huggingface",
                "repository_id": "org/model",
                "revision": "main",
                "destination": str(dest),
                "credential_ref": "none",
            },
            worker_pool="model_download",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="model_download", worker_id="t1", lease_ttl_seconds=60.0
        )
        assert claimed is not None
        result = self.executor.execute_job(
            {
                "job_store": self.store,
                "worker_id": "t1",
                "lease_ttl_seconds": 60.0,
            },
            claimed,
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["worker_pid"], os.getpid())
        row = model_store.get_download(download_id)
        assert row is not None
        self.assertEqual(row["state"], DownloadState.COMPLETED.value)
        self.assertGreater(row["bytes_downloaded"] or 0, 0)
        self.assertIsNotNone(row["speed_bps"])
        # Partial must not remain as final
        self.assertTrue((dest / "model.gguf").is_file())
        self.assertFalse((dest / "model.gguf.part").exists())
        # Registered only after verify
        models = model_store.list_models()
        self.assertTrue(any(m["model_id"] == "imported:model" for m in models))

    def test_disk_preflight_fails_early(self) -> None:
        with self.assertRaises(ModelDownloadError) as ctx:
            disk_preflight(
                target_dir=Path(self.tmp.name),
                bytes_total=10**18,
                bytes_already=0,
            )
        self.assertEqual(ctx.exception.code, ModelDownloadErrorCode.MODEL_DOWNLOAD_STORAGE_FULL)

    def test_http_404_maps_to_source_unavailable(self) -> None:
        self._patch_hf_urls()
        _FakeHFHandler.status_override = 404
        model_store = ModelStore(self.db)
        download_id = "dl-404"
        dest = self.executor.download_root / "org__missing" / "main"
        dest.mkdir(parents=True)
        model_store.upsert_download(
            {
                "download_id": download_id,
                "state": DownloadState.QUEUED.value,
                "source": "huggingface",
                "repository_id": "org/missing",
                "revision": "main",
                "destination": str(dest),
            }
        )
        job = self.runtime.enqueue(
            capability_id="model_download.start",
            arguments={
                "download_id": download_id,
                "source": "huggingface",
                "repository_id": "org/missing",
                "revision": "main",
                "destination": str(dest),
                "filename": "model.gguf",
                "credential_ref": "none",
            },
            worker_pool="model_download",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="model_download", worker_id="t404", lease_ttl_seconds=60.0
        )
        assert claimed is not None
        result = self.executor.execute_job(
            {"job_store": self.store, "worker_id": "t404", "lease_ttl_seconds": 60.0},
            claimed,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["error"]["code"],
            ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE.value,
        )


class ModelDownloadProcessIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "iso.db"
        self.store = _prepare_db(self.db)
        from Data.modules.execution import ExecutionGateway

        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(8),
        )
        _FakeHFHandler.calls = 0
        _FakeHFHandler.delay_seconds = 0.02
        _FakeHFHandler.status_override = None
        self.server, self.base = _start_server(_FakeHFHandler)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.tmp.cleanup()

    def test_transfer_pid_differs_from_control_plane(self) -> None:
        control_pid = os.getpid()
        model_store = ModelStore(self.db)
        download_id = "dl-iso"
        # Match executor download_root (= db.parent / model_downloads)
        dest = self.db.parent / "model_downloads" / "org__model" / "main"
        dest.mkdir(parents=True)
        model_store.upsert_download(
            {
                "download_id": download_id,
                "state": DownloadState.QUEUED.value,
                "source": "huggingface",
                "repository_id": "org/model",
                "revision": "main",
                "destination": str(dest),
            }
        )
        job = self.runtime.enqueue(
            capability_id="model_download.start",
            arguments={
                "download_id": download_id,
                "source": "huggingface",
                "repository_id": "org/model",
                "revision": "main",
                "destination": str(dest),
                "credential_ref": "none",
                "fake_base": self.base,
            },
            worker_pool="model_download",
            timeout_seconds=60,
        )

        worker_script = f"""
import os, sys
sys.path.insert(0, {os.getcwd()!r})
from pathlib import Path
import httpx
from Data.modules.jobs.store import JobStore
from Data.modules.model_download.executor import ModelDownloadExecutor

db = Path({str(self.db)!r})
base = {self.base!r}
store = JobStore(db)
store.initialize()
claimed = store.claim_next_for_pool(pool_id="model_download", worker_id=f"iso-{{os.getpid()}}", lease_ttl_seconds=60.0)
assert claimed is not None
ex = ModelDownloadExecutor(db_path=str(db))
real = httpx.Client(timeout=30.0, follow_redirects=True)
class Proxy:
    def head(self, url, **kw):
        return real.head(url.replace("https://huggingface.co", base), **kw)
    def get(self, url, **kw):
        return real.get(url.replace("https://huggingface.co", base), **kw)
    def stream(self, method, url, **kw):
        return real.stream(method, url.replace("https://huggingface.co", base), **kw)
    def close(self):
        real.close()
ex._client = Proxy()
ctx = {{"job_store": store, "worker_id": f"iso-{{os.getpid()}}", "lease_ttl_seconds": 60.0}}
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
        light_ok = 0
        deadline = time.monotonic() + 20.0
        latencies: list[float] = []
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            _ = self.store.get(job.job_id)
            latencies.append(time.monotonic() - t0)
            light_ok += 1
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
        self.assertIn("STATUS succeeded", stdout)
        worker_pid = None
        for line in stdout.splitlines():
            if line.startswith("RESULT_PID"):
                worker_pid = int(line.split()[-1])
        self.assertIsNotNone(worker_pid)
        self.assertNotEqual(worker_pid, control_pid)
        self.assertGreaterEqual(light_ok, 1)
        # Control plane polls stayed responsive (no multi-second stalls)
        self.assertLess(max(latencies), 1.0)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)


class DownloadManagerNoInlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "mgr.db"
        MigrationRunner(self.db).apply_all()
        self.model_store = ModelStore(self.db)
        self.registry = ModelRegistry(self.model_store)
        self.mgr = DownloadManager(
            self.model_store,
            self.registry,
            download_root=Path(self.tmp.name) / "dl",
            allow_outbound=True,
            job_runtime=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refuses_without_job_runtime(self) -> None:
        import asyncio
        from Data.modules.models.errors import ModelControlError

        with self.assertRaises(ModelControlError) as ctx:
            asyncio.run(self.mgr.start_huggingface(repository_id="org/model"))
        self.assertEqual(
            ctx.exception.code,
            ModelDownloadErrorCode.MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE.value,
        )


class AlpacaNoControlPlaneFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LEVIATHAN_ALPACA_PAPER_KEY_ID"] = "PKTEST"
        os.environ["LEVIATHAN_ALPACA_PAPER_SECRET"] = "SECRETEST"
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        self.db = Path(self.tmp.name) / "alp.db"
        self.store = _prepare_db(self.db)
        from Data.modules.execution import ExecutionGateway

        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(8),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("LEVIATHAN_ALPACA_PAPER_KEY_ID", None)
        os.environ.pop("LEVIATHAN_ALPACA_PAPER_SECRET", None)

    def test_alpaca_refuses_when_workers_down(self) -> None:
        from Data.modules.market_sim.paper_broker import AlpacaPaperBroker
        from Data.modules.market_sim.types import MarketSimError

        broker = AlpacaPaperBroker(job_runtime=self.runtime)
        with self.assertRaises(MarketSimError) as ctx:
            broker.account()
        self.assertEqual(ctx.exception.code, "PROVIDER_EXECUTION_UNAVAILABLE")

    def test_alpaca_executes_in_worker_process(self) -> None:
        from Data.modules.provider_io.adapters import alpaca_paper as alpaca_mod
        from Data.modules.provider_io.executor import ProviderIoExecutor

        server, base = _start_server(_FakeAlpacaHandler)
        self.addCleanup(server.shutdown)
        control_pid = os.getpid()
        # Point adapter at fake server
        original_base = alpaca_mod.PAPER_BASE
        alpaca_mod.PAPER_BASE = base
        self.addCleanup(lambda: setattr(alpaca_mod, "PAPER_BASE", original_base))

        job = self.runtime.enqueue(
            capability_id="provider.alpaca.paper",
            arguments={
                "provider": "alpaca_paper",
                "capability": "alpaca.paper",
                "credential_ref": "alpaca_paper",
                "payload": {"action": "account"},
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
from Data.modules.provider_io.adapters import alpaca_paper as m
m.PAPER_BASE = {base!r}
db = Path({str(self.db)!r})
store = JobStore(db)
store.initialize()
claimed = store.claim_next_for_pool(pool_id="provider_io", worker_id=f"alp-{{os.getpid()}}", lease_ttl_seconds=60.0)
assert claimed is not None
ex = ProviderIoExecutor(db_path=str(db))
ctx = {{"job_store": store, "worker_id": f"alp-{{os.getpid()}}", "lease_ttl_seconds": 60.0}}
result = ex.execute_job(ctx, claimed)
ex.close()
print("RESULT_PID", result.get("worker_pid"))
print("STATUS", result.get("status"))
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", worker_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.getcwd(),
            env={**os.environ},
        )
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
        self.assertIn("STATUS succeeded", stdout)
        worker_pid = int(
            [ln for ln in stdout.splitlines() if ln.startswith("RESULT_PID")][0].split()[-1]
        )
        self.assertNotEqual(worker_pid, control_pid)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)

    def test_market_import_refuses_silent_fallback(self) -> None:
        from Data.modules.market_sim.types import MarketSimError

        # Minimal stub service path: call import_provider_data logic via a light fake
        class FakeService:
            enabled = True
            job_runtime = self.runtime
            data = mock.MagicMock()
            data.markets_root = Path(self.tmp.name)
            providers = mock.MagicMock()
            store = mock.MagicMock()

            def _require_enabled(self):
                return None

            @staticmethod
            def _runners_externalized():
                return True

        # Import the real method by binding
        from Data.modules.market_sim.service import MarketSimControlPlane

        # Use a real lightweight instance via from_settings is heavy; call unbound with stub attrs
        svc = MarketSimControlPlane.__new__(MarketSimControlPlane)
        svc.enabled = True
        svc.job_runtime = self.runtime
        svc.data = mock.MagicMock()
        svc.data.markets_root = Path(self.tmp.name)
        svc.providers = mock.MagicMock()
        svc.store = mock.MagicMock()
        with self.assertRaises(MarketSimError) as ctx:
            MarketSimControlPlane.import_provider_data(
                svc, provider_id="binance_public", symbol="BTCUSDT", timeframe="1d"
            )
        self.assertEqual(ctx.exception.code, "PROVIDER_EXECUTION_UNAVAILABLE")
        svc.providers.import_to_csv.assert_not_called()


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_downloads_module_has_no_httpx_execution(self) -> None:
        src = Path("Data/modules/models/downloads.py").read_text(encoding="utf-8")
        self.assertNotIn("httpx", src)
        self.assertNotIn("asyncio.create_task", src)
        self.assertIn("ModelDownloadClient", src)

    def test_paper_broker_has_no_direct_urllib_alpaca(self) -> None:
        src = Path("Data/modules/market_sim/paper_broker.py").read_text(encoding="utf-8")
        self.assertNotIn("urllib.request", src)
        self.assertIn("PROVIDER_EXECUTION_UNAVAILABLE", src)
        self.assertIn("provider_io", src)


if __name__ == "__main__":
    unittest.main()
