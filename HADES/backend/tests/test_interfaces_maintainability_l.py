"""Work package L — interfaces / maintainability characterization tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from app_lifecycle import RuntimeBag, shutdown as lifecycle_shutdown, startup as lifecycle_startup
from brain_graph import assemble_brain_graph
from database import Database
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, WebResearchService


class BrainGraphExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db_path = root / "core.db"
        self.database = Database(str(db_path))
        self.database.initialize()
        self.platform_db = PlatformDatabase(str(root / "platform.db"))
        self.platform_db.initialize()
        self.database.save_memory(
            {"title": "L mem", "content": "body", "collection": "Tests", "tags": ["l"], "summary": "sum", "source": "test"}
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_assemble_includes_layout_flags_and_counts(self) -> None:
        payload = assemble_brain_graph(
            database=self.database,
            platform_db=self.platform_db,
            soft_cap=50,
            view_id="default",
        )
        self.assertIn("counts", payload)
        self.assertIn("available", payload["counts"])
        self.assertIn("included", payload["counts"])
        self.assertIn("truncated", payload["counts"])
        self.assertTrue(any(str(n.get("id", "")).startswith("memory_") for n in payload["nodes"]))
        mem = next(n for n in payload["nodes"] if str(n.get("id", "")).startswith("memory_"))
        self.assertFalse(mem.get("content_editable"))
        self.assertTrue(mem.get("layout_movable"))

    def test_brain_route_uses_extracted_module_via_api(self) -> None:
        main.database = self.database
        main.runner = main.TaskRunner()
        main.platform_db = self.platform_db
        main.ensure_platform_services()
        main.knowledge = KnowledgeService(main.platform_db, Path(self.tmp.name))
        main.web_research = WebResearchService(main.knowledge)
        with TestClient(main.app) as client:
            brain = client.get("/api/brain")
            self.assertEqual(brain.status_code, 200, brain.text)
            body = brain.json()
            self.assertIn("layout", body)
            self.assertIn("relation_kinds", body)
            models = client.get("/api/models/gateway")
            self.assertEqual(models.status_code, 200, models.text)
            self.assertIn("gateway", models.json())


class LifecycleHelperTests(unittest.TestCase):
    def test_startup_shutdown_without_second_manager(self) -> None:
        # Ensure only FastAPI lifespan owns lifecycle — helpers are pure functions.
        self.assertTrue(callable(lifecycle_startup))
        self.assertTrue(callable(lifecycle_shutdown))
        self.assertFalse(hasattr(main, "LifecycleManager"))
        # app_lifecycle must not import main (no cycle).
        mod = importlib.import_module("app_lifecycle")
        self.assertNotIn("main", getattr(mod, "__dict__", {}))

    def test_runtime_bag_roundtrip_minimal(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            db = Database(str(root / "core.db"))
            db.initialize()
            pdb = PlatformDatabase(str(root / "platform.db"))
            pdb.initialize()

            class _DummyRunner:
                def set_concurrency(self, _: int) -> None:
                    return None

                def schedule(self, _: str) -> None:
                    return None

                async def schedule_ticker(self):
                    while True:
                        await asyncio.sleep(3600)

                async def shutdown(self) -> None:
                    return None

            class _DummyPM:
                def reconcile_services(self) -> None:
                    return None

            class _DummyBot:
                def list_runs(self, _: int):
                    return []

            class _DummyLeases:
                def set_persist_path(self, _: Path) -> None:
                    return None

                def reclaim_stale(self):
                    return []

                def restore_control_from_tasks(self, _):
                    return {}

            class _DummyClaims:
                def set_db_path(self, _: Path) -> None:
                    return None

            class _DummyBudget:
                def configure(self, _: object) -> None:
                    return None

            class _DummyControl:
                def global_values(self):
                    return {"max_concurrent_tasks": 1}

                def shared_budget_config(self):
                    return {}

            class _DummyResearch:
                def schedule(self, _: str) -> None:
                    return None

                async def shutdown(self) -> None:
                    return None

            rt = RuntimeBag(
                database=db,
                platform_db=pdb,
                plugin_manager=_DummyPM(),
                runner=_DummyRunner(),
                trading_bot=_DummyBot(),
                schedule_service=object(),
                execution_leases=_DummyLeases(),
                claim_register=_DummyClaims(),
                shared_budget_pool=_DummyBudget(),
                sync_model_gateway=lambda _settings: None,
                build_research_runner=lambda: _DummyResearch(),
                build_trading_runner=lambda: _DummyResearch(),
                ensure_platform_services=lambda: None,
                init_control_service=lambda _d, _p: _DummyControl(),
                data_root=root,
            )

            async def _run() -> None:
                await lifecycle_startup(rt)
                self.assertIsNotNone(rt.schedule_ticker)
                await lifecycle_shutdown(rt)
                self.assertIsNone(rt.schedule_ticker)

            asyncio.run(_run())
        finally:
            tmp.cleanup()


class OpenApiExportSmokeTests(unittest.TestCase):
    def test_export_tool_builds_focused_document(self) -> None:
        tools = Path(__file__).resolve().parents[2] / "tools" / "export_openapi.py"
        self.assertTrue(tools.is_file())
        # Import as module by path.
        import importlib.util

        spec = importlib.util.spec_from_file_location("export_openapi", tools)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        doc = mod.build_openapi_document(main.app)
        schemas = doc["components"]["schemas"]
        for name in ("BrainGraphResponse", "ModelsGatewayResponse", "ApiErrorBody", "PageMeta"):
            self.assertIn(name, schemas)
        self.assertTrue(any(p.startswith("/api/brain") for p in doc["paths"]))
        self.assertTrue(any(p.startswith("/api/models") for p in doc["paths"]))

    def test_full_openapi_schema_resolves_coding_build_bodies(self) -> None:
        """Regression: nested BuildPlanInput must not stay a Query ForwardRef."""
        main.app.openapi_schema = None
        spec = main.app.openapi()
        self.assertIn("openapi", spec)
        plan = spec["paths"]["/api/build/plan"]["post"]
        self.assertIn("requestBody", plan)
        query_names = {
            item.get("name")
            for item in (plan.get("parameters") or [])
            if item.get("in") == "query"
        }
        self.assertNotIn("edits", query_names)
        self.assertNotIn("goal", query_names)
        schema_names = spec.get("components", {}).get("schemas", {})
        self.assertTrue(
            any("BuildPlan" in name for name in schema_names),
            msg=f"expected BuildPlan schema, got {sorted(schema_names)[:20]}",
        )


if __name__ == "__main__":
    unittest.main()
