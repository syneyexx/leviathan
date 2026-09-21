"""Characterization tests for Gen2 Compute Fabric extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.compute_fabric import (
    COMPUTE_JOB_TYPES,
    cancel_job,
    discover_nodes,
    dispatch_job,
    ensure_local_node,
    heartbeat,
)
from gen2.services import COMPUTE_JOB_TYPES as SERVICES_COMPUTE_JOB_TYPES
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class ComputeFabricModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name)
        self.store = Gen2Store(str(self.data_root / "compute.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_job_types_honest_and_reexported(self) -> None:
        self.assertEqual(COMPUTE_JOB_TYPES["ping"], "inspect")
        self.assertEqual(COMPUTE_JOB_TYPES["local_info"], "execute")
        self.assertEqual(COMPUTE_JOB_TYPES["heartbeat"], "execute")
        self.assertEqual(COMPUTE_JOB_TYPES["document_chunk"], "execute")
        self.assertIs(SERVICES_COMPUTE_JOB_TYPES, COMPUTE_JOB_TYPES)
        self.assertNotIn("shell", COMPUTE_JOB_TYPES)
        self.assertNotIn("remote_shell", COMPUTE_JOB_TYPES)

    def test_ensure_local_node_and_heartbeat(self) -> None:
        node = ensure_local_node(self.store, self.data_root)
        self.assertEqual(node["id"], "node_local")
        self.assertEqual(node["status"], "online")
        self.assertEqual(node["capabilities"]["storage"], str(self.data_root))
        beat = heartbeat(self.store, self.data_root)
        self.assertEqual(beat["id"], "node_local")
        self.assertEqual(beat["status"], "online")
        self.assertIn("last_heartbeat", beat)

    def test_discover_and_local_ping(self) -> None:
        nodes = discover_nodes(self.store, self.data_root)
        self.assertTrue(any(n["id"] == "node_local" for n in nodes))
        job = dispatch_job(self.store, self.data_root, payload={"op": "ping"})
        self.assertEqual(job["status"], "completed")
        result = job["result"]
        self.assertEqual(result["mode"], "inspect")
        self.assertEqual(result["executed_on"], "node_local")
        self.assertFalse(result["cloud_required"])
        self.assertEqual(result["note"], "inspect_only_no_side_effects")

    def test_local_info_and_heartbeat_jobs(self) -> None:
        ensure_local_node(self.store, self.data_root)
        info = dispatch_job(self.store, self.data_root, payload={"type": "local_info"})
        self.assertEqual(info["status"], "completed")
        self.assertEqual(info["result"]["mode"], "execute")
        self.assertEqual(info["result"]["info"]["data_root"], str(self.data_root))
        hb = dispatch_job(self.store, self.data_root, payload={"job_type": "heartbeat"})
        self.assertEqual(hb["status"], "completed")
        self.assertEqual(hb["result"]["node"]["id"], "node_local")

    def test_unsupported_job_type_fails_honestly(self) -> None:
        ensure_local_node(self.store, self.data_root)
        job = dispatch_job(self.store, self.data_root, payload={"op": "slow"})
        self.assertEqual(job["status"], "failed")
        self.assertTrue(str(job.get("error") or "").startswith("unsupported_job_type:"))
        self.assertEqual(job["result"]["mode"], "rejected")
        self.assertEqual(set(job["result"]["supported_types"]), set(COMPUTE_JOB_TYPES.keys()))

    def test_remote_unpaired_blocked_not_queued(self) -> None:
        ensure_local_node(self.store, self.data_root)
        self.store.upsert_node(
            {
                "id": "node_remote_a",
                "name": "remote-a",
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
            node_id="node_remote_a",
            prefer_local_fallback=False,
        )
        self.assertIn(job["status"], {"blocked", "unavailable"})
        self.assertNotEqual(job["status"], "queued")
        self.assertNotEqual((job.get("result") or {}).get("note"), "remote_dispatch_not_implemented")

    def test_cancel_job(self) -> None:
        ensure_local_node(self.store, self.data_root)
        job = self.store.create_remote_job(
            {"node_id": "node_local", "status": "queued", "payload": {"x": 1}}
        )
        out = cancel_job(self.store, job["id"])
        self.assertEqual(out["status"], "cancelled")
        # Terminal jobs are returned unchanged.
        again = cancel_job(self.store, job["id"])
        self.assertEqual(again["status"], "cancelled")

    def test_services_delegate_facade(self) -> None:
        svc = Gen2Services(self.store, data_root=self.data_root)
        nodes = svc.discover_nodes()
        self.assertTrue(any(n["id"] == "node_local" for n in nodes))
        job = svc.dispatch_job(payload={"op": "ping"})
        self.assertEqual(job["status"], "completed")
        bad = svc.dispatch_job(payload={"op": "slow"})
        self.assertEqual(bad["status"], "failed")
        queued = self.store.create_remote_job(
            {"node_id": "node_local", "status": "queued", "payload": {"y": 2}}
        )
        cancelled = svc.cancel_job(queued["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        events = svc.flight_log(job["id"])
        self.assertTrue(
            any(
                e["event_type"] in {"TOOL", "TOOL_STARTED"}
                or (e.get("payload") or {}).get("_event_type_alias") == "TOOL_STARTED"
                for e in events
            )
        )


if __name__ == "__main__":
    unittest.main()
