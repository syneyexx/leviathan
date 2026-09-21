"""Tests for LAN worker compute fabric MVP (work package O)."""

from __future__ import annotations

import multiprocessing
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.compute_fabric import (
    COMPUTE_JOB_TYPES,
    LanWorkerServer,
    cancel_job,
    dispatch_job,
    distributed_fabric_status,
    execute_typed_job,
    idempotent_remote_dispatch,
    pair_remote_node,
    recover_expired_leases,
    worker_status,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


def _worker_process_main(queue: multiprocessing.Queue, secret: str, node_id: str, fingerprint: str) -> None:
    server = LanWorkerServer(
        node_id=node_id,
        shared_secret=secret,
        fingerprint=fingerprint,
        host="127.0.0.1",
        port=0,
        capabilities={
            "job_types": ["document_chunk", "document_preprocess", "ping", "heartbeat", "local_info"],
            "protocol_version": 1,
        },
    )
    url = server.start()
    queue.put({"base_url": url})
    # Keep alive until parent kills us / queue sentinel
    while True:
        time.sleep(0.2)
        try:
            msg = queue.get_nowait()
        except Exception:
            continue
        if msg == "stop":
            server.stop()
            break


class ComputeFabricLanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name)
        self.store = Gen2Store(str(self.data_root / "compute.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_document_chunk_local(self) -> None:
        text = "Alpha paragraph.\n\n" + ("Beta word " * 40) + "\n\nGamma end."
        result = execute_typed_job("document_chunk", {"text": text, "target_chars": 120})
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["chunk_count"], 1)
        self.assertTrue(result["result_hash"])
        self.assertFalse(result["unbounded_shell"])
        self.assertIn("document_chunk", COMPUTE_JOB_TYPES)

    def test_unpaired_remote_not_endless_queue(self) -> None:
        from gen2.compute_fabric import ensure_local_node

        ensure_local_node(self.store, self.data_root)
        self.store.upsert_node(
            {
                "id": "node_remote_x",
                "name": "remote-x",
                "role": "worker",
                "status": "online",
                "capabilities": {},
                "load": {},
                "last_heartbeat": "2099-01-01T00:00:00Z",
            }
        )
        job = dispatch_job(
            self.store,
            self.data_root,
            payload={"op": "ping"},
            node_id="node_remote_x",
            prefer_local_fallback=False,
        )
        self.assertIn(job["status"], {"blocked", "unavailable"})
        self.assertNotEqual(job["status"], "queued")
        note = str((job.get("result") or {}).get("note") or "")
        self.assertTrue("not_queued" in note or job.get("error"))

    def test_network_policy_blocks_without_queue(self) -> None:
        from gen2.compute_fabric import ensure_local_node

        ensure_local_node(self.store, self.data_root)
        paired = pair_remote_node(
            self.store,
            self.data_root,
            node_id="worker_net",
            base_url="http://127.0.0.1:9",
            shared_secret="secret",
        )
        self.assertTrue(paired["ok"])
        job = dispatch_job(
            self.store,
            self.data_root,
            payload={"type": "document_chunk", "text": "hi"},
            node_id="worker_net",
            network_allowed=False,
            prefer_local_fallback=True,
        )
        # Local fallback completes; remote path was blocked by policy.
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["executed_on"], "node_local_fallback")
        self.assertEqual(job["result"]["fallback_reason"], "network_policy_blocked")

    def test_pairing_and_same_host_worker_process(self) -> None:
        secret = "test-shared-secret-value"
        node_id = "worker_proc_1"
        from gen2.compute_fabric import _sha256_text

        fingerprint = _sha256_text(f"{node_id}:{secret}")[:32]
        queue: multiprocessing.Queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=_worker_process_main,
            args=(queue, secret, node_id, fingerprint),
        )
        proc.start()
        try:
            info = queue.get(timeout=10)
            base_url = info["base_url"]
            pair_remote_node(
                self.store,
                self.data_root,
                node_id=node_id,
                name="lan-worker",
                base_url=base_url,
                shared_secret=secret,
                fingerprint=fingerprint,
                capabilities={
                    "job_types": ["document_chunk", "ping", "heartbeat", "local_info"],
                    "protocol_version": 1,
                },
            )
            text = "Document one.\n\nDocument two has more words for chunking purposes."
            job = dispatch_job(
                self.store,
                self.data_root,
                payload={"type": "document_chunk", "text": text, "target_chars": 40},
                node_id=node_id,
                prefer_local_fallback=False,
            )
            self.assertEqual(job["status"], "completed", job)
            self.assertEqual(job["result"]["executed_on"], node_id)
            self.assertGreaterEqual(job["result"]["chunk_count"], 1)
            self.assertTrue(job["result"].get("result_hash"))

            # Idempotency
            first = idempotent_remote_dispatch(
                self.store,
                self.data_root,
                payload={"type": "ping"},
                node_id=node_id,
                idempotency_key="idem-1",
                prefer_local_fallback=False,
            )
            self.assertEqual(first["status"], "completed")
            replay = idempotent_remote_dispatch(
                self.store,
                self.data_root,
                payload={"type": "ping"},
                node_id=node_id,
                idempotency_key="idem-1",
            )
            self.assertTrue(replay.get("idempotent_replay"))

            status = worker_status(self.store, self.data_root)
            self.assertGreaterEqual(len(status["paired_workers"]), 1)
            self.assertFalse(status["physical_multi_machine_verified"])

            fabric = distributed_fabric_status(self.data_root)
            self.assertTrue(fabric["implemented_lan_worker_mvp"])
            self.assertFalse(fabric["unbounded_remote_shell"])
            self.assertFalse(fabric["cloud_account_required"])
        finally:
            try:
                queue.put("stop")
            except Exception:
                pass
            proc.terminate()
            proc.join(timeout=5)

    def test_cancel_and_lease_recovery(self) -> None:
        from gen2.compute_fabric import ensure_local_node, lease_remote_job

        ensure_local_node(self.store, self.data_root)
        job = self.store.create_remote_job(
            {"node_id": "node_local", "status": "queued", "payload": {"type": "ping"}}
        )
        lease_remote_job(self.store, job["id"], node_id="node_local", lease_seconds=1)
        # Force expiry
        leased = self.store.get_remote_job(job["id"])
        result = dict(leased.get("result") or {})
        result["lease"]["expires_at"] = time.time() - 10
        self.store.update_remote_job(job["id"], result=result, status="leased")
        recovered = recover_expired_leases(self.store)
        self.assertTrue(any(j["id"] == job["id"] for j in recovered))
        self.assertEqual(self.store.get_remote_job(job["id"])["status"], "queued")

        cancelled = cancel_job(self.store, job["id"], data_root=self.data_root)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_services_document_chunk(self) -> None:
        svc = Gen2Services(self.store, data_root=self.data_root)
        job = svc.dispatch_job(payload={"type": "document_chunk", "text": "A\n\nB\n\nC", "target_chars": 10})
        self.assertEqual(job["status"], "completed")
        self.assertGreaterEqual(job["result"]["chunk_count"], 1)


if __name__ == "__main__":
    unittest.main()
