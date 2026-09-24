"""Regression tests — Research 1% freeze / external execution ownership."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.states import JobState
from Data.modules.knowledge import KnowledgeStore
from Data.modules.research import ResearchService, ResearchStatus, UnconfiguredWebProvider
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import ResearchPhase
from Data.modules.research.worker import process_research_job
from Data.modules.workers.admission import ResourceAdmission
from Data.modules.workers.loop import run_pool_loop
from Data.modules.workers.registry import WorkerRegistry
from Data.modules.workers.settings import WorkerSettings


def _runtime(db: Path) -> JobRuntime:
    store = JobStore(db)
    store.initialize()
    return JobRuntime(
        store,
        ExecutionGateway(catalog=build_default_catalog()),
        ResourceManager(4),
        lease_ttl_seconds=2.0,
    )


class ResearchOnePercentFreezeRegression(unittest.TestCase):
    """Mandatory: QUEUED must not no-op when the external worker claims the job."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "leviathan.db"
        self.data_root = self.root / "corpus"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)
        self.service = ResearchService(
            self.store,
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=self.job_runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _planned_project(self):
        project = self.service.create_project(
            topic="Widget Alpha launch year",
            depth="quick",
            allow_web=False,
            execution_mode="custom",
            budget_overrides={"rounds": 1, "research_workers": 1, "max_sources": 4},
        )
        return self.service.plan(project.project_id)

    def test_old_run_path_would_no_op_on_queued(self) -> None:
        """Document the bug: service.run(background=False) on QUEUED returns early."""
        planned = self._planned_project()
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            queued = self.service.run(planned.project_id, background=True)
        self.assertEqual(queued.status, ResearchStatus.QUEUED)
        self.assertGreaterEqual(queued.progress_pct, 1.0)
        # Bug path: run(background=False) treats QUEUED as ACTIVE → no coordinator.
        with mock.patch.object(
            self.service.runner.coordinator, "run", wraps=self.service.runner.coordinator.run
        ) as coord:
            again = self.service.run(planned.project_id, background=False)
        self.assertEqual(again.status, ResearchStatus.QUEUED)
        coord.assert_not_called()

    def test_execute_queued_run_invokes_coordinator(self) -> None:
        planned = self._planned_project()
        self.knowledge.upsert_document(
            title="Widget Alpha",
            content="Widget Alpha was launched in 2020 by Acme Corp.",
            source="press",
        )
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            queued = self.service.run(planned.project_id, background=True)
        self.assertEqual(queued.status, ResearchStatus.QUEUED)
        jobs = [
            j
            for j in self.job_runtime.store.list(limit=20)
            if j.capability_id == "research.advance"
        ]
        self.assertEqual(len(jobs), 1)

        with mock.patch.object(
            self.service.runner.coordinator, "run", wraps=self.service.runner.coordinator.run
        ) as coord:
            result = self.service.execute_queued_run(
                planned.project_id,
                job_id=jobs[0].job_id,
                worker_id="test-worker",
            )
        coord.assert_called_once()
        self.assertNotEqual(result.status, ResearchStatus.QUEUED)
        self.assertIsNotNone(result.active_run_id)
        workers = self.store.list_workers(planned.project_id)
        self.assertGreaterEqual(len(workers), 1)
        self.assertGreater(result.progress_pct, 1.0)

    def test_worker_process_research_job_uses_execute_not_run(self) -> None:
        planned = self._planned_project()
        self.knowledge.upsert_document(
            title="Widget Alpha",
            content="Widget Alpha was launched in 2020 by Acme Corp.",
            source="press",
        )
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            self.service.run(planned.project_id, background=True)
        job = next(
            j
            for j in self.job_runtime.store.list(limit=20)
            if j.capability_id == "research.advance"
        )
        self.job_runtime.store.transition(job.job_id, JobState.RUNNING)
        ctx = {
            "job_store": self.job_runtime.store,
            "job_runtime": self.job_runtime,
            "research_service": self.service,
            "worker_id": "research-test",
        }
        with mock.patch.object(
            self.service.runner.coordinator, "run", wraps=self.service.runner.coordinator.run
        ) as coord:
            process_research_job(ctx, job)
        coord.assert_called_once()
        project = self.service.get_project(planned.project_id)
        self.assertNotEqual(project.status, ResearchStatus.QUEUED)


class ResearchDuplicateStartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "d.db"
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=self.job_runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_duplicate_start_idempotent(self) -> None:
        project = self.service.create_project(topic="dup", depth="quick", execution_mode="custom")
        self.service.plan(project.project_id)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            a = self.service.run(project.project_id, background=True)
            b = self.service.run(project.project_id, background=True)
        self.assertEqual(a.status, ResearchStatus.QUEUED)
        self.assertEqual(b.status, ResearchStatus.QUEUED)
        jobs = [
            j
            for j in self.job_runtime.store.list(limit=50)
            if j.capability_id == "research.advance"
            and getattr(j, "domain_entity_id", None) == project.project_id
        ]
        self.assertEqual(len(jobs), 1)
        # execute once → one ResearchRun; second execute is idempotent.
        self.service.execute_queued_run(project.project_id, job_id=jobs[0].job_id)
        mid = self.service.get_project(project.project_id)
        run_id = mid.active_run_id
        self.assertIsNotNone(run_id)
        # Second execute while not QUEUED is rejected / idempotent for active states.
        if mid.status in {
            ResearchStatus.RESEARCHING,
            ResearchStatus.SYNTHESIZING,
            ResearchStatus.CANCELLING,
        }:
            again = self.service.execute_queued_run(project.project_id, job_id=jobs[0].job_id)
            self.assertEqual(again.active_run_id, run_id)
        else:
            # Already finished — execute_queued_run must not start another run.
            with self.assertRaises(Exception):
                self.service.execute_queued_run(project.project_id, job_id=jobs[0].job_id)
        with self.store.connect() as conn:
            n = int(
                conn.execute(
                    "SELECT COUNT(*) FROM research_runs WHERE project_id = ?",
                    (project.project_id,),
                ).fetchone()[0]
            )
        self.assertEqual(n, 1)


class ResearchTwoWorkerRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "race.db"
        self.data_root = self.root / "corpus"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeStore(self.db, data_root=self.data_root)
        self.knowledge.initialize()
        self.knowledge.upsert_document(
            title="Seed",
            content="The sealed vault contains exactly forty-two golden keys.",
            source="seed",
        )
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)
        self.service = ResearchService(
            self.store,
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=self.job_runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_two_workers_race_one_owner(self) -> None:
        project = self.service.create_project(
            topic="golden keys",
            depth="quick",
            execution_mode="custom",
            budget_overrides={"rounds": 1, "research_workers": 1},
        )
        self.service.plan(project.project_id)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            self.service.run(project.project_id, background=True)

        results: list[ResearchStatus] = []
        barrier = threading.Barrier(2)

        def _worker(wid: str) -> None:
            barrier.wait(timeout=5)
            # Claim CAS is pid-based; simulate distinct claim attempts via store CAS
            # by calling execute_queued_run from two threads (same pid — second should
            # see RESEARCHING after first claim and return idempotently).
            out = self.service.execute_queued_run(
                project.project_id, job_id="job-race", worker_id=wid
            )
            results.append(out.status)

        t1 = threading.Thread(target=_worker, args=("w1",))
        t2 = threading.Thread(target=_worker, args=("w2",))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)
        latest = self.store.get_latest_run(project.project_id)
        self.assertIsNotNone(latest)
        # Exactly one ResearchRun created.
        with self.store.connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM research_runs WHERE project_id = ?",
                (project.project_id,),
            ).fetchone()[0]
        self.assertEqual(int(n), 1)

    def test_claim_cas_rejects_second_owner(self) -> None:
        project = self.service.create_project(topic="cas", depth="quick")
        project.status = ResearchStatus.QUEUED
        project.phase = ResearchPhase.PLANNING
        self.store.save_project(project)
        ok1 = self.store.claim_queued_execution(project.project_id, worker_pid=111, kernel_job_id="j1")
        ok2 = self.store.claim_queued_execution(project.project_id, worker_pid=222, kernel_job_id="j2")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        loaded = self.store.get_project(project.project_id)
        assert loaded is not None
        self.assertEqual(loaded.worker_pid, 111)
        self.assertEqual(loaded.kernel_job_id, "j1")
        self.assertEqual(loaded.status, ResearchStatus.RESEARCHING)


class JobLeaseHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "lease.db"
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(self.db)
        # Ensure worker settings see our db via settings load — loop uses load_settings.
        self._prev = {
            "LEVIATHAN_WORKERS_LEASE_TTL_SECONDS": os.environ.get(
                "LEVIATHAN_WORKERS_LEASE_TTL_SECONDS"
            ),
            "LEVIATHAN_WORKERS_HEARTBEAT_SECONDS": os.environ.get(
                "LEVIATHAN_WORKERS_HEARTBEAT_SECONDS"
            ),
            "LEVIATHAN_WORKERS_POLL_SECONDS": os.environ.get("LEVIATHAN_WORKERS_POLL_SECONDS"),
        }
        os.environ["LEVIATHAN_WORKERS_LEASE_TTL_SECONDS"] = "1"
        os.environ["LEVIATHAN_WORKERS_HEARTBEAT_SECONDS"] = "0.3"
        os.environ["LEVIATHAN_WORKERS_POLL_SECONDS"] = "0.2"

    def tearDown(self) -> None:
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.environ.pop("LEVIATHAN_DATABASE_PATH", None)
        self.tmp.cleanup()

    def test_long_handler_keeps_lease_alive(self) -> None:
        runtime = _runtime(self.db)
        job = runtime.enqueue(
            capability_id="research.advance",
            arguments={"project_id": "p-long", "action": "advance"},
            requested_by="test",
            domain="research",
            domain_entity_id="p-long",
            worker_pool="research",
            idempotency_key="research:advance:p-long:long",
        )

        def slow_handler(ctx, claimed):
            # Exceed lease TTL (1s) substantially; heartbeat must renew.
            time.sleep(3.5)
            # Lease must still be held by this worker.
            row = ctx["job_store"].get(claimed.job_id)
            self.assertEqual(row.lease_owner, ctx["worker_id"])
            ctx["job_store"].transition(
                claimed.job_id, JobState.COMPLETED, result={"ok": True}
            )
            return {"ok": True}

        with mock.patch(
            "Data.modules.workers.loop.load_worker_settings",
            return_value=WorkerSettings(
                enabled=True,
                heartbeat_seconds=0.3,
                lease_ttl_seconds=1.0,
                poll_seconds=0.2,
                pool_counts={"research": 1},
            ),
        ), mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context",
            return_value={
                "settings": mock.Mock(database_path=self.db, resources=mock.Mock(max_job_concurrency=2)),
                "job_store": runtime.store,
                "job_runtime": runtime,
                "gateway": runtime.gateway,
                "registry": WorkerRegistry(self.db),
                "admission": ResourceAdmission(self.db),
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=0.3,
                    lease_ttl_seconds=1.0,
                    poll_seconds=0.2,
                    pool_counts={"research": 1},
                ),
            },
        ):
            ctx_registry = WorkerRegistry(self.db)
            ctx_registry.initialize()
            admission = ResourceAdmission(self.db)
            admission.initialize()

            def _ctx():
                return {
                    "settings": mock.Mock(
                        database_path=self.db,
                        resources=mock.Mock(max_job_concurrency=2),
                    ),
                    "job_store": runtime.store,
                    "job_runtime": runtime,
                    "gateway": runtime.gateway,
                    "registry": ctx_registry,
                    "admission": admission,
                    "worker_settings": WorkerSettings(
                        heartbeat_seconds=0.3,
                        lease_ttl_seconds=1.0,
                        poll_seconds=0.2,
                        pool_counts={"research": 1},
                    ),
                }

            with mock.patch(
                "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
            ):
                processed = run_pool_loop(
                    pool_id="research",
                    handler=slow_handler,
                    once=True,
                    max_jobs=1,
                )
        self.assertEqual(processed, 1)
        final = runtime.store.get(job.job_id)
        self.assertEqual(final.state, JobState.COMPLETED)

    def test_lost_lease_self_fences(self) -> None:
        runtime = _runtime(self.db)
        job = runtime.enqueue(
            capability_id="research.advance",
            arguments={"project_id": "p-lost", "action": "advance"},
            requested_by="test",
            domain="research",
            domain_entity_id="p-lost",
            worker_pool="research",
            idempotency_key="research:advance:p-lost:lost",
        )
        saw_fence = threading.Event()

        def handler(ctx, claimed):
            # Force authoritative lease expiry (cannot steal a live lease via acquire).
            with runtime.store.connect() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET lease_expires_at = ?, lease_owner = ?
                    WHERE job_id = ?
                    """,
                    ("2000-01-01T00:00:00+00:00", "thief", claimed.job_id),
                )
            deadline = time.time() + 5
            while time.time() < deadline:
                if ctx["job_cancel_check"]():
                    saw_fence.set()
                    break
                time.sleep(0.05)
            return {"fenced": True}

        registry = WorkerRegistry(self.db)
        registry.initialize()
        admission = ResourceAdmission(self.db)
        admission.initialize()

        def _ctx():
            return {
                "settings": mock.Mock(
                    database_path=self.db,
                    resources=mock.Mock(max_job_concurrency=2),
                ),
                "job_store": runtime.store,
                "job_runtime": runtime,
                "gateway": runtime.gateway,
                "registry": registry,
                "admission": admission,
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=0.2,
                    lease_ttl_seconds=2.0,
                    poll_seconds=0.1,
                    pool_counts={"research": 1},
                ),
            }

        with mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
        ), mock.patch(
            "Data.modules.workers.loop.load_worker_settings",
            return_value=WorkerSettings(
                heartbeat_seconds=0.2,
                lease_ttl_seconds=2.0,
                poll_seconds=0.1,
                pool_counts={"research": 1},
            ),
        ):
            run_pool_loop(pool_id="research", handler=handler, once=True, max_jobs=1)
        self.assertTrue(saw_fence.is_set())


class ExternalModelAndBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "brain.db"
        self.data_root = self.root / "corpus"
        self.data_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_process_safe_model_caller_invokes_role(self) -> None:
        from Data.backend.config import load_settings
        from Data.backend.migrations import MigrationRunner
        from Data.modules.models.store import ModelStore
        from Data.modules.models.worker_client import build_process_safe_model_caller

        MigrationRunner(self.db).apply_all()
        from dataclasses import replace

        settings = replace(load_settings(), database_path=self.db)

        store = ModelStore(self.db)
        store.upsert_provider(
            {
                "provider_id": "local",
                "name": "Local",
                "provider_type": "openai_compatible",
                "endpoint": "http://127.0.0.1:9",
                "enabled": True,
                "capabilities": {},
            }
        )
        store.upsert_model(
            {
                "model_id": "test-research-model",
                "display_name": "test-research-model",
                "provider_id": "local",
                "source": "local",
                "lifecycle_state": "available",
                "health": "unknown",
                "active": True,
                "endpoint": "http://127.0.0.1:9",
                "metadata": {
                    "provider_model_id": "test-research-model",
                    "roles": ["research", "chat"],
                },
                "tags": ["research", "chat"],
            }
        )
        store.set_active_model("test-research-model")
        store.save_router_config(
            {
                "fallback_order": ["test-research-model"],
                "role_overrides": {"research": "test-research-model"},
                "cloud_fallback_allowed": False,
            }
        )

        caller = build_process_safe_model_caller(settings)
        self.assertTrue(getattr(caller, "__process_safe_client__", False))

        async def _fake_complete(*_a, **_k):
            return {"text": "ok from model", "usage": {}, "usage_source": "test"}

        client = caller.__wrapped_client__
        with mock.patch.object(client.llm, "complete_messages", side_effect=_fake_complete):
            out = caller(
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                role="researcher",
                domain="research",
                model_role="research",
            )
        self.assertIn("ok from model", out["text"])
        self.assertEqual(out.get("transport"), "process_safe_model_client")

    def test_external_worker_context_sees_seeded_brain(self) -> None:
        from Data.backend.config import load_settings
        from Data.modules.research.worker_context import build_research_worker_context

        base = load_settings()
        settings = mock.MagicMock()
        settings.database_path = self.db
        settings.knowledge = mock.Mock(
            data_root=str(self.data_root),
            embedding_provider="hash",
            embedding_model="hash",
            hash_dimensions=64,
        )
        settings.network = mock.Mock(allow_outbound=False)
        settings.resources = mock.Mock(max_job_concurrency=2, max_model_concurrency=2)
        settings.research_integration = getattr(base, "research_integration", mock.Mock())
        settings.llm_base_url = getattr(base, "llm_base_url", "http://127.0.0.1:9")
        settings.llm_api_key = getattr(base, "llm_api_key", None)

        knowledge = KnowledgeStore(
            self.db,
            data_root=self.data_root,
            embedding_provider=None,
        )
        knowledge.initialize()
        knowledge.upsert_document(
            title="Brain seed",
            content="LEVIATHAN one brain marker UNIQUE_TOKEN_ZX9",
            source="seed",
        )

        with mock.patch(
            "Data.modules.models.worker_client.build_process_safe_model_caller",
            side_effect=RuntimeError("no model in test"),
        ):
            ctx = build_research_worker_context(settings=settings)
        service = ctx["research_service"]
        self.assertIsNotNone(service.knowledge)
        hits = service.local.search("UNIQUE_TOKEN_ZX9", limit=5)
        text_blob = " ".join(
            getattr(h, "content", None)
            or getattr(h, "span_text", None)
            or str(h.public_dict() if hasattr(h, "public_dict") else h)
            for h in hits
        )
        self.assertIn("UNIQUE_TOKEN_ZX9", text_blob)


class ImportFailureAndWorkerUnavailableTests(unittest.TestCase):
    def test_import_failure_marks_job_failed_not_completed(self) -> None:
        from Data.modules.workers.entrypoints import research as research_ep

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "imp.db"
        runtime = _runtime(db)
        job = runtime.enqueue(
            capability_id="research.advance",
            arguments={"project_id": "p1", "action": "advance"},
            requested_by="test",
            worker_pool="research",
            idempotency_key="research:advance:p1:imp",
        )
        runtime.store.transition(job.job_id, JobState.RUNNING)
        ctx = {"job_store": runtime.store}
        with mock.patch.dict(
            "sys.modules",
            {"Data.modules.research.worker": None},
        ):
            # Force ImportError by making the import raise.
            with mock.patch(
                "builtins.__import__",
                side_effect=ImportError("forced"),
            ):
                # Directly exercise the except ImportError path via the handler body.
                pass

        # Call the handler with a patched import inside the function.
        real_handler = research_ep._handler

        def _boom_import(name, *args, **kwargs):
            if name == "Data.modules.research.worker" or name.endswith("research.worker"):
                raise ImportError("forced research import failure")
            return mock.DEFAULT

        with mock.patch(
            "Data.modules.workers.entrypoints.research.process_research_job",
            create=True,
        ):
            # Patch the import statement used inside _handler.
            import builtins

            orig = builtins.__import__

            def _imp(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "Data.modules.research.worker" or (
                    fromlist and "process_research_job" in fromlist and "research" in name
                ):
                    raise ImportError("forced research import failure")
                if name == "Data.modules.research.worker":
                    raise ImportError("forced research import failure")
                return orig(name, globals, locals, fromlist, level)

            # Simpler: patch the from-import by replacing the module attribute path.
            with mock.patch(
                "Data.modules.research.worker.process_research_job",
                side_effect=ImportError("forced"),
            ):
                # The entrypoint imports process_research_job inside try; simulate by
                # invoking the FAILED path directly as the entrypoint would.
                runtime.store.transition(
                    job.job_id,
                    JobState.FAILED,
                    error="Research handler import failed: forced",
                    result={"import_error": True, "deferred_domain": False},
                )

        # Exercise the real entrypoint ImportError branch.
        job2 = runtime.enqueue(
            capability_id="research.advance",
            arguments={"project_id": "p2", "action": "advance"},
            requested_by="test",
            worker_pool="research",
            idempotency_key="research:advance:p2:imp",
        )
        runtime.store.transition(job2.job_id, JobState.RUNNING)

        import types
        import sys

        # Remove module so `from Data.modules.research.worker import ...` raises.
        saved = sys.modules.get("Data.modules.research.worker")
        sys.modules["Data.modules.research.worker"] = types.ModuleType("broken")  # type: ignore
        # Make attribute missing to trigger ImportError on from-import... actually
        # from-import of missing attr is ImportError.
        del sys.modules["Data.modules.research.worker"]
        sys.modules["Data.modules.research.worker"] = None  # type: ignore
        try:
            result = research_ep._handler(ctx, job2)
        finally:
            if saved is not None:
                sys.modules["Data.modules.research.worker"] = saved
            else:
                sys.modules.pop("Data.modules.research.worker", None)

        refreshed = runtime.store.get(job2.job_id)
        self.assertEqual(refreshed.state, JobState.FAILED)
        self.assertNotIn("deferred_domain", (refreshed.result or {}))
        self.assertIn("error", result)

    def test_worker_pool_zero_sets_wait_reason(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "w.db"
        store = ResearchStore(db)
        store.initialize()
        runtime = _runtime(db)
        service = ResearchService(
            store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=root / "snapshots",
            reports_root=root / "reports",
            sources_root=root / "sources",
            job_runtime=runtime,
        )
        project = service.create_project(topic="wait", depth="quick")
        service.plan(project.project_id)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}), mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            return_value=WorkerSettings(enabled=True, pool_counts={"research": 0}),
        ):
            queued = service.run(project.project_id, background=True)
        self.assertEqual(queued.status, ResearchStatus.QUEUED)
        self.assertIsNotNone(queued.wait_reason)
        self.assertIn("waiting for research worker", queued.wait_reason or "")


class ResearchReconcileTests(unittest.TestCase):
    def test_reconcile_missing_job_and_false_completed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "rec.db"
        store = ResearchStore(db)
        store.initialize()
        runtime = _runtime(db)
        service = ResearchService(
            store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=root / "snapshots",
            reports_root=root / "reports",
            sources_root=root / "sources",
            job_runtime=runtime,
        )
        project = service.create_project(topic="stuck", depth="quick")
        project.status = ResearchStatus.QUEUED
        project.phase = ResearchPhase.PLANNING
        project.progress_pct = 1.0
        store.save_project(project)

        # B: no kernel job → enqueue
        fixed = service.reconcile_queued_projects()
        self.assertIn(project.project_id, fixed)
        loaded = store.get_project(project.project_id)
        assert loaded is not None
        self.assertIsNotNone(loaded.kernel_job_id)
        job = runtime.store.get(loaded.kernel_job_id)
        self.assertIsNotNone(job)

        # C: falsely COMPLETED with no ResearchRun → re-enqueue
        runtime.store.transition(job.job_id, JobState.RUNNING)
        runtime.store.transition(job.job_id, JobState.COMPLETED, result={"deferred_domain": True})
        loaded.status = ResearchStatus.QUEUED
        loaded.progress_pct = 1.0
        loaded.active_run_id = None
        store.save_project(loaded)
        fixed2 = service.reconcile_queued_projects()
        self.assertIn(project.project_id, fixed2)
        loaded2 = store.get_project(project.project_id)
        assert loaded2 is not None
        self.assertNotEqual(loaded2.kernel_job_id, job.job_id)
        new_job = runtime.store.get(loaded2.kernel_job_id)
        self.assertEqual(new_job.state, JobState.QUEUED)


if __name__ == "__main__":
    unittest.main()
