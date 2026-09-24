"""Architecture guards for the Frontier Execution Fabric.

These tests encode non-negotiable ownership boundaries:
- FastAPI must not spawn heavy domain runners when workers are externalized
- Worker processes must not import Data.backend.main
- Scheduler ticks enqueue only by default
- EscalationPolicy keeps hashing at Tier 0; synthesis+reasoning → Tier 3
- WorkerSupervisor is a singleton lease holder
"""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.compute import ComputeTier, EscalationPolicy
from Data.modules.execution import build_default_catalog
from Data.modules.schedules.runner import ScheduleRunner
from Data.modules.workers.pools import POOL_CATALOG
from Data.modules.workers.settings import WorkerSettings
from Data.modules.workers.supervisor import WorkerSupervisor

REPO_DATA = Path(__file__).resolve().parents[2]
BACKEND_MAIN = REPO_DATA / "backend" / "main.py"
WORKERS_ROOT = REPO_DATA / "modules" / "workers"


def _ast_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
        elif isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
    return out


def _forbids_backend_main(path: Path) -> None:
    for mod in _ast_imports(path):
        if mod == "Data.backend.main" or mod.startswith("Data.backend.main."):
            raise AssertionError(f"{path} imports forbidden module {mod}")


class FabricCapabilityCatalogTests(unittest.TestCase):
    REQUIRED = (
        "research.advance",
        "research.plan",
        "research.retrieve",
        "research.synthesize",
        "research.verify",
        "workflow.advance",
        "schedule.tick",
        "knowledge.prepare",
        "knowledge.commit",
        "embedding.batch",
        "maintenance.reconcile",
        "evaluation.run",
        "training.control",
        "market_sim.advance",
        "backup.create",
        "agent.advance",
    )

    def test_fabric_capabilities_registered(self) -> None:
        ids = {item.id for item in build_default_catalog().list()}
        missing = [cap for cap in self.REQUIRED if cap not in ids]
        self.assertEqual(missing, [], msg=f"missing fabric capabilities: {missing}")


class LifespanExternalizeGuards(unittest.TestCase):
    def test_lifespan_skips_domain_runners_when_externalize(self) -> None:
        """Prefer behavioral check of the lifespan branching helper/source."""
        text = BACKEND_MAIN.read_text(encoding="utf-8")
        self.assertIn("LEVIATHAN_WORKERS_EXTERNALIZE_API", text + str(WORKERS_ROOT))
        # Source-level contract: externalize branch must not call heavy starters.
        # Locate the lifespan block around externalize.
        marker = "externalize = bool(worker_settings.enabled and worker_settings.externalize_api_runners)"
        self.assertIn(marker, text)
        idx = text.index(marker)
        window = text[idx : idx + 2500]
        self.assertIn("if externalize:", window)
        # Positive: recover always runs; heavy starts only in else.
        self.assertIn("research_service.recover()", text)
        else_idx = window.index("else:")
        else_block = window[else_idx:]
        self.assertIn("research_service.start_background()", else_block)
        self.assertIn("coding_service.start_background()", else_block)
        self.assertIn("job_runtime.start_background_worker()", else_block)
        # Negation: the externalize arm must not invoke those starts.
        if_arm = window[:else_idx]
        self.assertNotIn("research_service.start_background()", if_arm)
        self.assertNotIn("coding_service.start_background()", if_arm)
        self.assertNotIn("job_runtime.start_background_worker()", if_arm)

    def test_research_start_background_externalize_does_not_spawn_threads(self) -> None:
        from Data.modules.research.service import ResearchService
        from Data.modules.research.store import ResearchStore
        from Data.modules.research.types import ResearchStatus
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
        from Data.modules.execution import ExecutionGateway, build_default_catalog

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "r.db"
        store = ResearchStore(db)
        store.initialize()
        project = store.create_project(title="t", topic="topic")
        project.status = ResearchStatus.QUEUED
        store.save_project(project)

        job_store = JobStore(db)
        job_store.initialize()
        runtime = JobRuntime(
            job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        service = ResearchService(store, job_runtime=runtime)
        # Avoid constructing heavy runner deps for this unit — stub recover path unused.
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            service.start_background()
        self.assertTrue(
            service._dispatcher_thread is None or not service._dispatcher_thread.is_alive()
        )
        self.assertEqual(service._bg_threads, {})
        jobs = job_store.list(limit=20)
        self.assertTrue(any(j.capability_id == "research.advance" for j in jobs))
        self.assertTrue(
            any(
                (j.idempotency_key or "").startswith(f"research:advance:{project.project_id}:")
                for j in jobs
            )
        )


class WorkerImportGuards(unittest.TestCase):
    def test_loop_and_bootstrap_avoid_backend_main_import(self) -> None:
        _forbids_backend_main(WORKERS_ROOT / "loop.py")
        # bootstrap may reference the uvicorn target string but must not import the module.
        bootstrap = WORKERS_ROOT / "bootstrap.py"
        _forbids_backend_main(bootstrap)
        text = bootstrap.read_text(encoding="utf-8")
        # String form for uvicorn is allowed; module import is not.
        self.assertIn("Data.backend.main:app", text)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertFalse(
                stripped.startswith("from Data.backend.main")
                or stripped.startswith("import Data.backend.main"),
                msg=f"bootstrap imports backend.main: {stripped}",
            )


class ScheduleRunnerGuards(unittest.TestCase):
    def test_tick_default_execute_false(self) -> None:
        sig = inspect.signature(ScheduleRunner.tick)
        param = sig.parameters["execute"]
        self.assertIs(param.default, False)


class EscalationPolicyGuards(unittest.TestCase):
    def test_hashing_stays_tier0(self) -> None:
        decision = EscalationPolicy().decide("hashing")
        self.assertEqual(decision.tier, ComputeTier.DETERMINISTIC)

    def test_synthesis_requires_reasoning_tier3(self) -> None:
        decision = EscalationPolicy().decide("synthesis", requires_reasoning=True)
        self.assertEqual(decision.tier, ComputeTier.MAIN_REASONING)


class WorkerSupervisorLeaseGuards(unittest.TestCase):
    def test_refuses_second_lease(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "s.db"
        settings = WorkerSettings(
            enabled=True,
            supervisor_enabled=True,
            pool_counts={p: 0 for p in POOL_CATALOG},
        )
        first = WorkerSupervisor(db, settings=settings)
        first.start()
        self.addCleanup(lambda: first.stop(grace_seconds=0.2))
        second = WorkerSupervisor(db, settings=settings)
        with self.assertRaises(RuntimeError) as ctx:
            second.start()
        self.assertIn("WORKER_SUPERVISOR_LEASE_HELD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
