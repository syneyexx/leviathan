"""WAVE 1 — Module lifecycle truth: cheap snapshots, allowed_actions, job receipts."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleStatus
from Data.modules.module_manager.manager import ManagedModule, _HEALTH_STALE_SECONDS
from Data.modules.module_manager.types import ModuleHealth, ModuleManifest
from Data.modules.neuro.echo_module import create_echo_module


class SnapshotHealthTruthTests(unittest.TestCase):
    def test_public_dict_does_not_call_live_health(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        calls = {"n": 0}
        original = managed.instance.health

        def counting_health():
            calls["n"] += 1
            return original()

        managed.instance.health = counting_health  # type: ignore[method-assign]
        payload = managed.public_dict()
        self.assertEqual(calls["n"], 0)
        self.assertIsNone(payload["health"])
        self.assertEqual(payload["health_freshness"], "UNMEASURED")
        self.assertTrue(payload["truth"]["snapshot_health_is_cached_not_live"])

    def test_explicit_health_caches_for_snapshot(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        manager.register_instance(create_echo_module(), ready=True)
        health = manager.health("neuro.echo")
        self.assertIsInstance(health, ModuleHealth)
        managed = manager.get("neuro.echo")
        assert managed is not None
        self.assertIsNotNone(managed.last_health)
        self.assertEqual(managed._health_freshness(), "FRESH")
        snap = managed.public_dict()
        self.assertEqual(snap["health"]["freshness"], "FRESH")
        self.assertEqual(snap["health"]["status"], health.status.value)

    def test_stale_health_is_not_presented_as_healthy(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        managed.last_health = {
            "module_id": "neuro.echo",
            "status": "READY",
            "detail": "ok",
            "telemetry": {},
        }
        # Force age past stale threshold.
        managed.last_health_at = time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00",
            time.gmtime(time.time() - _HEALTH_STALE_SECONDS - 5),
        )
        self.assertEqual(managed._health_freshness(), "STALE")
        payload = managed.public_dict()
        self.assertEqual(payload["health"]["status"], "STALE")
        self.assertEqual(payload["health"]["freshness"], "STALE")


class AllowedActionsProjectionTests(unittest.TestCase):
    def test_server_projects_allowed_actions(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        # Echo is first-party without external adapter — lifecycle limited.
        actions = managed.allowed_actions(manager_enabled=True)
        self.assertIn("allowed", actions)
        self.assertIn("blocked_reasons", actions)
        snap = manager.public_snapshot()
        row = snap["modules"][0]
        self.assertIn("allowed_actions", row)
        self.assertTrue(snap["truth"]["allowed_actions_are_server_projected"])

    def test_feature_flag_off_blocks_all_actions(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=False)
        managed = manager.register_instance(create_echo_module(), ready=True)
        actions = managed.allowed_actions(manager_enabled=False)
        for key, value in actions["allowed"].items():
            self.assertFalse(value, key)
            self.assertIn(key, actions["blocked_reasons"])

    def test_external_discovered_can_install(self) -> None:
        manifest = ModuleManifest(
            module_id="ext.demo",
            name="Demo",
            version="0.1.0",
            entrypoint="x:y",
            metadata={"external": {"adapter": "CLI", "source": {"type": "git", "ref": "main"}}},
        )
        managed = ManagedModule(manifest=manifest, status=ModuleStatus.DISCOVERED)
        actions = managed.allowed_actions(manager_enabled=True)["allowed"]
        self.assertTrue(actions["can_install"])
        self.assertFalse(actions["can_execute"])


class UpdateEvidencePersistenceTests(unittest.TestCase):
    def test_check_update_persists_on_managed_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "echo"
            root.mkdir(parents=True)
            manifest = {
                "module_id": "neuro.echo",
                "name": "Neuro Echo Module",
                "version": "0.1.0",
                "entrypoint": "Data.modules.neuro.echo_module:create_echo_module",
                "capabilities": [
                    {
                        "capability_id": "neuro.echo.ping",
                        "name": "ping",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("neuro.echo", ModuleContext())
            result = manager.check_update("neuro.echo")
            self.assertIn("checked_at", result)
            managed = manager.get("neuro.echo")
            assert managed is not None
            self.assertIsNotNone(managed.last_update_check)
            snap = managed.public_dict()
            self.assertEqual(snap["update_evidence"]["module_id"], "neuro.echo")


class LifecycleQueueReceiptTests(unittest.TestCase):
    def test_queue_lifecycle_returns_durable_receipt_fields(self) -> None:
        from Data.backend.routes.modules import _queue_module_lifecycle

        job = MagicMock()
        job.job_id = "job-123"
        job.state = MagicMock(value="QUEUED")
        runtime = MagicMock()
        runtime.enqueue.return_value = job
        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        # Mark as external so public_dict adapter path is exercised.
        managed.manifest = ModuleManifest(
            module_id="neuro.echo",
            name="Neuro Echo Module",
            version="0.1.0",
            entrypoint="Data.modules.neuro.echo_module:create_echo_module",
            metadata={"external": {"adapter": "CLI"}},
        )

        def emit(_name, _payload, **_kwargs):
            return None

        def raise_lifecycle(exc):
            raise exc

        receipt = _queue_module_lifecycle(
            job_runtime=runtime,
            module_id="neuro.echo",
            capability_id="external.module.start",
            action="start",
            emit=emit,
            raise_lifecycle=raise_lifecycle,
            module_manager=manager,
            allow_sync_fallback=False,
        )
        self.assertTrue(receipt["queued"])
        self.assertEqual(receipt["job_id"], "job-123")
        self.assertEqual(receipt["operation"], "start")
        self.assertEqual(receipt["module_id"], "neuro.echo")
        self.assertIn("accepted_at", receipt)
        self.assertEqual(receipt["state"], "QUEUED")
        self.assertTrue(receipt["truth"]["enqueue_is_not_completion"])
        self.assertIn("job-123", manager.active_jobs("neuro.echo"))


class ModuleJobsProjectionTests(unittest.TestCase):
    def test_project_merges_active_and_runtime_jobs(self) -> None:
        from Data.backend.routes.modules import _project_module_jobs

        job = MagicMock()
        job.public_dict.return_value = {
            "job_id": "j1",
            "capability_id": "external.module.start",
            "arguments": {"module_id": "ext.a", "action": "start"},
            "state": "SUCCEEDED",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:01:00+00:00",
            "metadata": {},
        }
        runtime = MagicMock()
        runtime.list.return_value = [job]
        runtime.get.return_value = None
        projected = _project_module_jobs(
            job_runtime=runtime,
            module_id="ext.a",
            active_ids=["j2"],
            limit=20,
        )
        ids = {str(item.get("job_id")) for item in projected}
        self.assertIn("j1", ids)
        self.assertIn("j2", ids)


if __name__ == "__main__":
    unittest.main()
