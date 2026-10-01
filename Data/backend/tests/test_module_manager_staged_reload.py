"""Phase 1.7 / 1.8 — killable process containment + staged module reload."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from Data.modules.module_manager import (
    ModuleContext,
    ModuleManager,
    ModuleManagerError,
    ModuleStatus,
)
from Data.modules.module_manager.killable_exec import KillableModuleExecutor
from Data.modules.module_manager.types import (
    ModuleHealth,
    ModuleIsolation,
    ModuleManifest,
    ModuleResult,
)
from Data.modules.neuro.echo_module import create_echo_module


class _FlakyInitModule:
    """Factory-controlled module used to fail staging without touching active."""

    fail_init = False
    fail_health = False
    instances: list[Any] = []

    def __init__(self) -> None:
        self._ready = False
        self.shutdown_called = False
        self._manifest = ModuleManifest(
            module_id="test.staged",
            name="Staged",
            version="1.0.0",
            entrypoint="Data.backend.tests.test_module_manager_staged_reload:create_flaky",
            hot_reload=True,
            isolation=ModuleIsolation.INPROC,
            side_effects=("READ",),
        )
        type(self).instances.append(self)

    @property
    def manifest(self) -> ModuleManifest:
        return self._manifest

    def initialize(self, ctx: ModuleContext) -> None:
        if type(self).fail_init:
            raise RuntimeError("init boom")
        self._ready = True

    def execute(self, operation: str, arguments: Mapping[str, Any]) -> ModuleResult:
        return ModuleResult(
            module_id="test.staged",
            operation=operation,
            status="COMPLETED",
            output={"ok": True},
        )

    def shutdown(self) -> None:
        self.shutdown_called = True
        self._ready = False

    def health(self) -> ModuleHealth:
        if type(self).fail_health:
            raise RuntimeError("health boom")
        return ModuleHealth(
            module_id="test.staged",
            status=ModuleStatus.READY if self._ready else ModuleStatus.LOADED,
            detail="ok",
        )


def create_flaky() -> _FlakyInitModule:
    return _FlakyInitModule()


class KillableContainmentTests(unittest.TestCase):
    def test_killable_executor_timeout_terminates_process(self) -> None:
        # Use a hanging script via a fake entrypoint that sleeps.
        # Echo module finishes immediately — use a custom hang factory below.
        executor = KillableModuleExecutor(timeout_seconds=0.4)
        started = time.monotonic()
        result = executor.execute(
            entrypoint="Data.backend.tests.test_module_manager_staged_reload:create_hanging",
            operation="sleep",
            arguments={},
            context={},
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result.status, "TIMEOUT")
        self.assertTrue(result.process_killed or result.fenced)
        self.assertLess(elapsed, 5.0)
        self.assertIn("timeout", (result.error or "").lower())

    def test_inline_safe_echo_does_not_use_thread_pool(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True, execute_timeout_seconds=5.0)
        manager.register_instance(create_echo_module(), ready=True)
        # Patch ThreadPoolExecutor to ensure it is never used.
        with mock.patch("concurrent.futures.ThreadPoolExecutor") as pool:
            result = manager.execute("neuro.echo", "ping", {"message": "hi"})
            pool.assert_not_called()
        self.assertEqual(result.status, "COMPLETED")

    def test_subprocess_isolation_uses_killable_path(self) -> None:
        manager = ModuleManager(
            discovery_roots=(),
            enabled=True,
            allow_subprocess_isolation=True,
            execute_timeout_seconds=30.0,
        )
        echo = create_echo_module()
        managed = manager.register_instance(echo, ready=True)
        # Force SUBPROCESS isolation on the frozen manifest via replace.
        managed.manifest = ModuleManifest(
            module_id=managed.manifest.module_id,
            name=managed.manifest.name,
            version=managed.manifest.version,
            entrypoint="Data.modules.neuro.echo_module:create_echo_module",
            capabilities=managed.manifest.capabilities,
            isolation=ModuleIsolation.SUBPROCESS,
            hot_reload=managed.manifest.hot_reload,
            side_effects=managed.manifest.side_effects,
            metadata=dict(managed.manifest.metadata or {}),
        )
        result = manager.execute("neuro.echo", "ping", {"message": "iso"})
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual((result.output or {}).get("echo"), "iso")
        self.assertGreaterEqual(int(manager.telemetry.get("subprocess_executes", 0)), 1)


class _HangingModule:
    def __init__(self) -> None:
        self._manifest = ModuleManifest(
            module_id="test.hang",
            name="Hang",
            version="0.0.1",
            entrypoint="Data.backend.tests.test_module_manager_staged_reload:create_hanging",
            isolation=ModuleIsolation.SUBPROCESS,
            side_effects=("EXECUTE",),
        )

    @property
    def manifest(self) -> ModuleManifest:
        return self._manifest

    def initialize(self, ctx: ModuleContext) -> None:
        return None

    def execute(self, operation: str, arguments: Mapping[str, Any]) -> ModuleResult:
        time.sleep(30)
        return ModuleResult(module_id="test.hang", operation=operation, status="COMPLETED")

    def shutdown(self) -> None:
        return None

    def health(self) -> ModuleHealth:
        return ModuleHealth(module_id="test.hang", status=ModuleStatus.READY)


def create_hanging() -> _HangingModule:
    return _HangingModule()


class StagedReloadTests(unittest.TestCase):
    def setUp(self) -> None:
        _FlakyInitModule.fail_init = False
        _FlakyInitModule.fail_health = False
        _FlakyInitModule.instances = []

    def _manager_with_staged(self) -> ModuleManager:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        module = create_flaky()
        managed = manager.register_instance(module, ready=True)
        # Point entrypoint at factory for reload staging.
        managed.manifest = ModuleManifest(
            module_id="test.staged",
            name="Staged",
            version="1.0.0",
            entrypoint="Data.backend.tests.test_module_manager_staged_reload:create_flaky",
            hot_reload=True,
            isolation=ModuleIsolation.INPROC,
            side_effects=("READ",),
        )
        return manager

    def test_successful_staged_reload_bumps_generation(self) -> None:
        manager = self._manager_with_staged()
        before = manager.get("test.staged")
        assert before is not None
        old_instance = before.instance
        old_gen = before.generation
        reloaded = manager.reload("test.staged", ModuleContext())
        self.assertEqual(reloaded.status, ModuleStatus.READY)
        self.assertEqual(reloaded.generation, old_gen + 1)
        self.assertIsNot(reloaded.instance, old_instance)
        self.assertTrue(getattr(old_instance, "shutdown_called", False))

    def test_failing_init_leaves_old_untouched(self) -> None:
        manager = self._manager_with_staged()
        before = manager.get("test.staged")
        assert before is not None
        old_instance = before.instance
        old_gen = before.generation
        _FlakyInitModule.fail_init = True
        with self.assertRaises(ModuleManagerError) as ctx:
            manager.reload("test.staged", ModuleContext())
        err = str(ctx.exception).lower()
        self.assertTrue("staging" in err or "init boom" in err or "start_failed" in err)
        after = manager.get("test.staged")
        assert after is not None
        self.assertIs(after.instance, old_instance)
        self.assertEqual(after.generation, old_gen)
        self.assertEqual(after.status, ModuleStatus.READY)
        self.assertFalse(getattr(old_instance, "shutdown_called", False))

    def test_failing_health_leaves_old_untouched(self) -> None:
        manager = self._manager_with_staged()
        before = manager.get("test.staged")
        assert before is not None
        old_instance = before.instance
        old_gen = before.generation
        _FlakyInitModule.fail_health = True
        with self.assertRaises(ModuleManagerError) as ctx:
            manager.reload("test.staged", ModuleContext())
        self.assertIn("health", str(ctx.exception).lower())
        after = manager.get("test.staged")
        assert after is not None
        self.assertIs(after.instance, old_instance)
        self.assertEqual(after.generation, old_gen)
        self.assertFalse(getattr(old_instance, "shutdown_called", False))

    def test_activation_blocked_when_jobs_active(self) -> None:
        manager = self._manager_with_staged()
        manager.register_job("test.staged", "job-1")
        before = manager.get("test.staged")
        assert before is not None
        old_instance = before.instance
        with self.assertRaises(ModuleManagerError) as ctx:
            manager.reload("test.staged", ModuleContext())
        self.assertIn("jobs active", str(ctx.exception).lower())
        after = manager.get("test.staged")
        assert after is not None
        self.assertIs(after.instance, old_instance)
        self.assertFalse(getattr(old_instance, "shutdown_called", False))

    def test_hot_reload_false_refused(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        echo = create_echo_module()
        managed = manager.register_instance(echo, ready=True)
        managed.manifest = ModuleManifest(
            module_id=managed.manifest.module_id,
            name=managed.manifest.name,
            version=managed.manifest.version,
            entrypoint=managed.manifest.entrypoint,
            hot_reload=False,
            isolation=ModuleIsolation.INPROC,
            side_effects=("READ",),
        )
        with self.assertRaises(ModuleManagerError):
            manager.reload("neuro.echo", ModuleContext())

    def test_execute_generation_fence(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        manager.register_instance(create_echo_module(), ready=True)
        with self.assertRaises(ModuleManagerError) as ctx:
            manager.execute("neuro.echo", "ping", {"message": "x"}, expected_generation=999)
        self.assertIn("generation", str(ctx.exception).lower())


class ManifestDiskReloadTests(unittest.TestCase):
    def test_reload_reads_new_manifest_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "echo"
            root.mkdir(parents=True)
            manifest = {
                "module_id": "neuro.echo",
                "name": "Neuro Echo Module",
                "version": "0.1.0",
                "entrypoint": "Data.modules.neuro.echo_module:create_echo_module",
                "hot_reload": True,
                "capabilities": [
                    {
                        "capability_id": "neuro.echo.ping",
                        "name": "ping",
                        "side_effects": ["READ"],
                    }
                ],
            }
            path = root / "module.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("neuro.echo", ModuleContext())
            before = manager.get("neuro.echo")
            assert before is not None
            gen = before.generation
            # Bump version on disk then reload.
            manifest["version"] = "0.2.0"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            reloaded = manager.reload("neuro.echo", ModuleContext())
            self.assertEqual(reloaded.manifest.version, "0.2.0")
            self.assertEqual(reloaded.generation, gen + 1)


if __name__ == "__main__":
    unittest.main()
