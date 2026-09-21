from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from app_lifecycle import RuntimeBag, startup


class _Database:
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


class _PlatformDatabase(_Database):
    def recover_running_tool_calls(self) -> None:
        return None

    def list_research_projects(self):
        return []


class _Runner:
    def set_concurrency(self, _value: int) -> None:
        return None

    def schedule(self, _task_id: str) -> None:
        return None

    async def schedule_ticker(self) -> None:
        return None


class _FailingLeaseStore:
    def set_persist_path(self, _path: Path) -> None:
        raise RuntimeError("corrupt lease recovery state")

    def reclaim_stale(self):
        raise AssertionError("reclaim_stale must not run after load failure")

    def restore_control_from_tasks(self, _tasks):
        raise AssertionError("restore_control_from_tasks must not run after load failure")


class AppLifecycleLeaseRecoveryHonestyTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_fails_closed_when_execution_lease_state_cannot_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core = _Database(root / "core.db")
            platform = _PlatformDatabase(root / "platform.db")
            runner = _Runner()
            notes: list[str] = []
            rt = RuntimeBag(
                database=core,
                platform_db=platform,
                plugin_manager=SimpleNamespace(reconcile_services=lambda: None),
                runner=runner,
                trading_bot=SimpleNamespace(list_runs=lambda _limit: []),
                schedule_service=SimpleNamespace(),
                execution_leases=_FailingLeaseStore(),
                claim_register=SimpleNamespace(set_db_path=lambda _path: None),
                shared_budget_pool=SimpleNamespace(configure=lambda _cfg: None),
                sync_model_gateway=lambda _settings: None,
                build_research_runner=lambda: SimpleNamespace(schedule=lambda _id: None),
                build_trading_runner=lambda: SimpleNamespace(schedule=lambda _id: None),
                ensure_platform_services=lambda: None,
                init_control_service=lambda _db, _platform: SimpleNamespace(
                    global_values=lambda: {},
                    shared_budget_config=lambda: {},
                ),
                data_root=root,
                notes=notes,
            )

            with self.assertRaisesRegex(RuntimeError, "execution lease recovery"):
                await startup(rt)

            self.assertTrue(any(note.startswith("lease_restore_failed:") for note in notes))


if __name__ == "__main__":
    unittest.main()
