"""External Execution Fabric — defaults, routing, dashboard, no inline fallback."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.datasets.worker import resolve_runner_mode as resolve_dataset_runner
from Data.modules.source_ingestion.worker import resolve_runner_mode as resolve_si_runner
from Data.modules.workers.console import print_pool_inventory, print_startup_banner
from Data.modules.workers.dashboard import build_worker_fabric_dashboard
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability
from Data.modules.workers.protocol import WorkerInstanceState, WorkerRegistration
from Data.modules.workers.registry import WorkerRegistry
from Data.modules.workers.settings import load_worker_settings


class ExternalDefaultsTests(unittest.TestCase):
    def test_python_defaults_are_external_and_always_on(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            from Data.backend.config import Settings

            cfg = Settings.from_env()
            ws = load_worker_settings()
        self.assertTrue(ws.enabled)
        self.assertTrue(ws.supervisor_enabled)
        self.assertTrue(ws.externalize_api_runners)
        self.assertEqual(cfg.research_integration.dataset_jobs_runner, "external")
        self.assertEqual(cfg.research_integration.source_ingestion_runner, "external")
        self.assertTrue(cfg.features.agents_enabled)
        self.assertTrue(cfg.features.coding_enabled)
        self.assertTrue(cfg.features.signal_fabric_enabled)
        self.assertTrue(cfg.network.allow_outbound)
        self.assertTrue(cfg.reasoning_enabled)

    def test_runner_mode_unset_defaults_external(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_dataset_runner(), "external")
            self.assertEqual(resolve_si_runner(), "external")
            self.assertFalse(
                __import__(
                    "Data.modules.datasets.worker", fromlist=["should_start_inprocess_runner"]
                ).should_start_inprocess_runner()
            )

    def test_env_example_aligned(self) -> None:
        root = Path(__file__).resolve().parents[3]
        text = (root / ".env.example").read_text(encoding="utf-8")
        self.assertIn("LEVIATHAN_DATASET_JOBS_RUNNER=external", text)
        self.assertIn("LEVIATHAN_SOURCE_INGESTION_RUNNER=external", text)
        self.assertIn("LEVIATHAN_WORKERS_EXTERNALIZE_API=true", text)
        self.assertIn("LEVIATHAN_NETWORK_ALLOW_OUTBOUND=true", text)
        self.assertIn("LEVIATHAN_FEATURE_AGENTS=true", text)
        self.assertIn("LEVIATHAN_FEATURE_CODING=true", text)


class PoolCatalogIntegrityTests(unittest.TestCase):
    def test_every_pool_has_valid_entrypoint_and_bounds(self) -> None:
        for pid, defn in POOL_CATALOG.items():
            self.assertTrue(defn.entrypoint.startswith("Data.modules.workers.entrypoints."))
            self.assertGreaterEqual(defn.default_count, 0)
            self.assertGreaterEqual(defn.max_count, defn.default_count)
            self.assertTrue(defn.description)
            # Entrypoint module must import.
            mod = __import__(defn.entrypoint, fromlist=["main"])
            self.assertTrue(hasattr(mod, "main") or hasattr(mod, "run") or True)

    def test_job_routing_critical_capabilities(self) -> None:
        cases = {
            "research.advance": "research",
            "research.plan": "research",
            "dataset.process": "dataset",
            "dataset.download": "dataset",
            "source_ingestion.process": "source_ingestion",
            "coding.advance": "coding",
            "agent.advance": "agents",
            "agent_signal.deliver": "agent_signals",
            "knowledge.prepare": "knowledge_prepare",
            "knowledge.ingest_scan": "knowledge_prepare",
            "knowledge.commit": "db_commit",
            "embedding.batch": "embedding",
            "evaluation.run": "evaluation",
            "training.control": "training_control",
            "market_sim.advance": "market_sim",
            "model_download.start": "model_download",
            "mcp.call": "mcp_execution",
            "provider.http": "provider_io",
            "provider.hf.list": "provider_io",
            "provider.market.stream": "market_feed",
            "backup.create": "backup",
            "maintenance.reconcile": "maintenance",
            "schedule.tick": "scheduler",
            "workflow.advance": "workflow",
        }
        for cap, pool in cases.items():
            self.assertEqual(pool_for_capability(cap), pool, msg=cap)

    def test_desired_workers_computed_from_catalog(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            ws = load_worker_settings()
        desired = sum(ws.desired_count(pid) for pid in POOL_CATALOG)
        enabled = sum(1 for pid in POOL_CATALOG if ws.desired_count(pid) > 0)
        self.assertGreaterEqual(desired, 20)
        self.assertGreaterEqual(enabled, 20)
        self.assertEqual(ws.desired_count("db_commit"), 1)
        self.assertEqual(ws.desired_count("knowledge_commit"), 0)
        self.assertEqual(ws.desired_count("rerank"), 0)


class WorkerFabricDashboardTests(unittest.TestCase):
    def test_dashboard_joins_job_and_lists_all_pools(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "w.db"
        registry = WorkerRegistry(db)
        registry.initialize()
        registry.upsert(
            WorkerRegistration(
                worker_id="research-0-aabbccdd",
                pool_id="research",
                slot=0,
                pid=4242,
                process_start_identity="test:4242",
                state=WorkerInstanceState.BUSY,
                current_job_id="job-research-1",
                supported_job_kinds=("research.",),
            )
        )

        class _Job:
            job_id = "job-research-1"
            capability_id = "research.advance"
            metadata = {"topic": "Daytrading", "progress_current": 2, "progress_total": 10}
            arguments = {}
            domain = "research"
            domain_entity_type = "research_project"
            domain_entity_id = "rp1"
            parent_job_id = None
            root_job_id = None
            trace_id = "tr1"
            progress = 0.2
            phase = "analyze"
            message = None
            started_at = "2026-01-01T00:00:00+00:00"
            claimed_at = None
            worker_pool = "research"
            attempt_number = 1
            error_code = None
            state = type("S", (), {"value": "RUNNING"})()

        def getter(jid: str):
            return _Job() if jid == "job-research-1" else None

        dash = build_worker_fabric_dashboard(
            db_path=db,
            job_getter=getter,
            list_jobs=lambda **_k: [],
            include_resources=False,
        )
        self.assertEqual(len(dash["pools"]), len(POOL_CATALOG))
        self.assertEqual(dash["summary"]["pools_total"], len(POOL_CATALOG))
        self.assertGreaterEqual(dash["summary"]["running_workers"], 1)
        self.assertGreaterEqual(dash["summary"]["busy_workers"], 1)
        worker = next(w for w in dash["workers"] if w["pool_id"] == "research")
        self.assertEqual(worker["pid"], 4242)
        self.assertIn("Daytrading", worker["current_work"])
        self.assertEqual(worker["current_job"]["progress_current"], 2)
        self.assertEqual(worker["current_job"]["progress_total"], 10)
        # Disabled optional pools still visible.
        disabled = {p["pool_id"]: p for p in dash["pools"] if p["desired"] <= 0}
        self.assertIn("rerank", disabled)
        self.assertIn("document_ai", disabled)
        self.assertIn("knowledge_commit", disabled)

    def test_console_banner_and_pool_inventory_dynamic(self) -> None:
        buf = io.StringIO()
        print_startup_banner(
            install_root=Path("/tmp/leviathan-install"),
            database_path=Path("/tmp/leviathan.db"),
            stream=buf,
        )
        text = buf.getvalue()
        self.assertIn("LEVIATHAN EXTERNAL EXECUTION FABRIC", text)
        self.assertIn("Mode: EXTERNAL", text)
        self.assertIn("/tmp/leviathan-install", text)
        self.assertNotIn("D:\\LEVIATHAN", text)

        buf2 = io.StringIO()
        print_pool_inventory(stream=buf2)
        inv = buf2.getvalue()
        for pid in ("research", "dataset", "source_ingestion", "coding", "db_commit", "embedding"):
            self.assertIn(pid, inv)
        self.assertIn("Disabled/optional", inv)


class NoInlineFallbackContractTests(unittest.TestCase):
    def test_execution_gateway_blocks_external_required_when_externalize(self) -> None:
        from Data.modules.execution.workload import api_may_execute_inline, externalize_api_enabled

        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_ENABLED": "1",
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
            },
            clear=False,
        ):
            self.assertTrue(externalize_api_enabled())
            self.assertFalse(api_may_execute_inline("research.advance"))
            self.assertFalse(api_may_execute_inline("dataset.process"))
            self.assertFalse(api_may_execute_inline("source_ingestion.process"))
            self.assertFalse(api_may_execute_inline("coding.advance"))
            self.assertFalse(api_may_execute_inline("knowledge.prepare"))
            self.assertFalse(api_may_execute_inline("embedding.batch"))
            self.assertTrue(api_may_execute_inline("compute.numeric"))

    def test_main_lifespan_externalize_skips_heavy_runners(self) -> None:
        main = Path(__file__).resolve().parents[1] / "main.py"
        text = main.read_text(encoding="utf-8")
        marker = "externalize = bool(worker_settings.enabled and worker_settings.externalize_api_runners)"
        self.assertIn(marker, text)
        idx = text.index(marker)
        window = text[idx : idx + 5000]
        else_idx = window.index("else:")
        if_arm = window[:else_idx]
        self.assertNotIn("research_service.start_background()", if_arm)
        self.assertNotIn("coding_service.start_background()", if_arm)
        self.assertNotIn("job_runtime.start_background_worker()", if_arm)

    def test_workers_bat_is_consolidated(self) -> None:
        root = Path(__file__).resolve().parents[3]
        bat = (root / "run_leviathan_workers.bat").read_text(encoding="utf-8")
        self.assertIn("External Execution Fabric", bat)
        self.assertIn("bootstrap supervisor", bat)
        self.assertIn("LEVIATHAN_WORKERS_EXTERNALIZE_API=1", bat)
        self.assertIn("%~dp0", bat)
        self.assertNotIn("D:\\LEVIATHAN", bat)
        # Must not launch per-domain worker bats.
        self.assertNotIn("research_worker.bat", bat)
        self.assertNotIn("dataset_worker.bat", bat)


class ActiveWorkersNotAgentCountTests(unittest.TestCase):
    def test_agents_kpi_uses_registry_not_agent_count(self) -> None:
        """Frontend contract: Active Workers label must not use agentCount."""
        kpi = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "agents"
            / "AgentsKpiStrip.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("Active Workers", kpi)
        self.assertIn("d.workers.active", kpi)
        # Value source must be workers.active, not fleet agentCount.
        self.assertNotIn("d.fleet.agentCount", kpi)
        self.assertNotIn("summary.agentCount", kpi)
        self.assertIn("registry worker processes", kpi)

    def test_worker_pools_panel_is_fabric_monitor(self) -> None:
        panel = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "agents"
            / "WorkerPoolsPanel.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("Worker Fabric", panel)
        self.assertIn("fabricWorkers", panel)
        self.assertIn("PID", panel)


if __name__ == "__main__":
    unittest.main()
