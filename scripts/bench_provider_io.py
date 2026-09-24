#!/usr/bin/env python3
"""Reproducible provider_io responsiveness benchmark (fake local provider only).

Measures Control Plane job-store poll latency while provider work is delayed.
Does not call paid external APIs. Prints measured values only.
"""

from __future__ import annotations

import json
import os
import socket
import statistics
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    delay = float(os.environ.get("BENCH_PROVIDER_DELAY", "1.0"))
    concurrency = int(os.environ.get("BENCH_CONCURRENCY", "4"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: A003
            return

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            time.sleep(delay)
            body = json.dumps(
                {
                    "id": "bench",
                    "model": "fake",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 1},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/v1"

    from Data.modules.execution import ExecutionGateway, build_default_catalog
    from Data.modules.jobs.resources import ResourceManager
    from Data.modules.jobs.runtime import JobRuntime
    from Data.modules.jobs.store import JobStore
    from Data.modules.provider_io.executor import ProviderIoExecutor

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "bench.db"
        store = JobStore(db)
        store.initialize()
        runtime = JobRuntime(
            store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(32),
        )
        jobs = []
        for i in range(concurrency):
            jobs.append(
                runtime.enqueue(
                    capability_id="provider.chat.complete",
                    arguments={
                        "provider": "bench",
                        "capability": "chat.complete",
                        "allow_private_hosts": True,
                        "credential_ref": "none",
                        "payload": {
                            "endpoint": base,
                            "messages": [{"role": "user", "content": f"n{i}"}],
                        },
                    },
                    worker_pool="provider_io",
                )
            )

        def worker_loop(wid: str) -> None:
            ex = ProviderIoExecutor(db_path=str(db))
            try:
                while True:
                    claimed = store.claim_next_for_pool(
                        pool_id="provider_io", worker_id=wid, lease_ttl_seconds=60
                    )
                    if claimed is None:
                        # Check if all done
                        if all(
                            (store.get(j.job_id) or j).state.value
                            in {"COMPLETED", "FAILED", "CANCELLED"}
                            for j in jobs
                        ):
                            return
                        time.sleep(0.02)
                        continue
                    ex.execute_job(
                        {
                            "job_store": store,
                            "settings": type("S", (), {"database_path": db})(),
                            "worker_id": wid,
                            "lease_ttl_seconds": 60.0,
                        },
                        claimed,
                    )
            finally:
                ex.close()

        workers = [
            threading.Thread(target=worker_loop, args=(f"w{i}",), daemon=True)
            for i in range(min(2, concurrency))
        ]
        for w in workers:
            w.start()

        light_ms: list[float] = []
        t0 = time.perf_counter()
        while True:
            t_a = time.perf_counter()
            _ = store.get(jobs[0].job_id)
            light_ms.append((time.perf_counter() - t_a) * 1000.0)
            states = [(store.get(j.job_id) or j).state.value for j in jobs]
            if all(s in {"COMPLETED", "FAILED", "CANCELLED"} for s in states):
                break
            if time.perf_counter() - t0 > delay * concurrency + 30:
                break
            time.sleep(0.01)

        for w in workers:
            w.join(timeout=5)
        wall = time.perf_counter() - t0
        light_ms.sort()
        p50 = light_ms[len(light_ms) // 2] if light_ms else None
        p95 = light_ms[max(0, int(len(light_ms) * 0.95) - 1)] if light_ms else None
        report = {
            "provider_delay_seconds": delay,
            "concurrency": concurrency,
            "worker_threads": len(workers),
            "wall_seconds": round(wall, 3),
            "control_plane_get_samples": len(light_ms),
            "control_plane_get_p50_ms": round(p50, 3) if p50 is not None else None,
            "control_plane_get_p95_ms": round(p95, 3) if p95 is not None else None,
            "control_plane_get_max_ms": round(max(light_ms), 3) if light_ms else None,
            "mean_ms": round(statistics.mean(light_ms), 3) if light_ms else None,
            "job_states": [
                (store.get(j.job_id) or j).state.value for j in jobs
            ],
            "note": "Provider latency is synthetic; benefit is Control Plane responsiveness.",
        }
        print(json.dumps(report, indent=2))
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
