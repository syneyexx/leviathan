from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app_lifecycle import RuntimeBag, install_cross_store_integrity_triggers, startup


class _TinyDatabase:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def initialize(self) -> None:
        return None

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def list_tasks(self):
        return []

    def recover_running_tasks(self):
        return []


class _TinyPlatformDatabase(_TinyDatabase):
    def recover_running_tool_calls(self) -> None:
        return None

    def list_research_projects(self):
        return []


class AppLifecycleIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_separate_stores_are_not_treated_as_shared_trigger_failure(self) -> None:
        core = _TinyDatabase(self.root / "core.db")
        platform = _TinyPlatformDatabase(self.root / "platform.db")
        self.assertFalse(install_cross_store_integrity_triggers(core, platform))

    def test_shared_store_missing_required_schema_fails_closed(self) -> None:
        path = self.root / "shared.db"
        core = _TinyDatabase(path)
        platform = _TinyPlatformDatabase(path)
        with core.connection() as db:
            db.execute("CREATE TABLE conversations(id TEXT PRIMARY KEY)")
        with self.assertRaisesRegex(RuntimeError, "mist tabellen"):
            install_cross_store_integrity_triggers(core, platform)

    async def test_startup_propagates_shared_store_trigger_install_failure(self) -> None:
        path = self.root / "shared.db"
        core = _TinyDatabase(path)
        platform = _TinyPlatformDatabase(path)
        notes: list[str] = []
        rt = RuntimeBag(
            database=core,
            platform_db=platform,
            plugin_manager=SimpleNamespace(reconcile_services=lambda: None),
            runner=SimpleNamespace(),
            trading_bot=SimpleNamespace(),
            schedule_service=SimpleNamespace(),
            execution_leases=SimpleNamespace(),
            claim_register=SimpleNamespace(),
            shared_budget_pool=SimpleNamespace(),
            sync_model_gateway=lambda _settings: None,
            build_research_runner=lambda: SimpleNamespace(),
            build_trading_runner=lambda: SimpleNamespace(),
            ensure_platform_services=lambda: None,
            init_control_service=lambda _db, _platform: SimpleNamespace(),
            data_root=self.root,
            notes=notes,
        )
        with mock.patch(
            "app_lifecycle.install_cross_store_integrity_triggers",
            side_effect=RuntimeError("trigger unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "conversation-forget invariant"):
                await startup(rt)
        self.assertTrue(any(note.startswith("cross_store_integrity_trigger_failed:") for note in notes))


if __name__ == "__main__":
    unittest.main()
