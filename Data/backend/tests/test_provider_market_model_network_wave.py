"""Provider / market_feed / model acquisition externalization wave tests."""

from __future__ import annotations

import ast
import hashlib
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.execution.workload import ExecutionWorkloadClass, classify_capability
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.jobs.states import JobState
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.model_download.executor import ModelDownloadExecutor
from Data.modules.models.import_service import ImportService
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore
from Data.modules.observations import ObservationStore
from Data.modules.provider_io.endpoint_locality import (
    EndpointLocality,
    classify_endpoint_locality,
)
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


def _job_runtime(db: Path) -> JobRuntime:
    artifacts = ArtifactStore(db, db.parent / "artifacts")
    artifacts.initialize()
    knowledge = KnowledgeStore(db, data_root=db.parent / "c", chunk_max_chars=200, chunk_overlap=20)
    knowledge.initialize()
    (db.parent / "c").mkdir(parents=True, exist_ok=True)
    fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
    approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
    approvals.store.initialize()
    obs = ObservationStore(db)
    obs.initialize()
    gateway = ExecutionGateway(
        catalog=build_default_catalog(),
        function_runtime=fn,
        knowledge_retriever=HybridRetriever(knowledge),
        artifact_store=artifacts,
        approval_checker=approvals,
        observation_store=obs,
    )
    jobs = JobRuntime(JobStore(db), gateway, ResourceManager(2))
    jobs.store.initialize()
    return jobs


class ProviderMarketModelPoolRoutingTests(unittest.TestCase):
    def test_capability_pool_map(self) -> None:
        cases = {
            "provider.http": "provider_io",
            "provider.chat.complete": "provider_io",
            "provider.chat.stream": "provider_io",
            "provider.market.fetch": "provider_io",
            "provider.hf.list": "provider_io",
            "provider.alpaca.paper": "provider_io",
            "provider.market.stream": "market_feed",
            "provider.market.stream.stop": "market_feed",
            "model_download.start": "model_download",
            "model_import.local": "model_download",
        }
        for cap, pool in cases.items():
            self.assertEqual(pool_for_capability(cap), pool, msg=cap)
            self.assertNotEqual(pool, "general", msg=cap)

    def test_market_stream_not_claimed_by_provider_io_prefix(self) -> None:
        self.assertEqual(pool_for_capability("provider.market.stream"), "market_feed")
        self.assertNotEqual(pool_for_capability("provider.market.stream"), "provider_io")

    def test_external_required_and_steal_fence(self) -> None:
        for cap in (
            "provider.http",
            "provider.chat.complete",
            "provider.chat.stream",
            "provider.market.fetch",
            "provider.market.stream",
            "model_download.start",
            "model_import.local",
        ):
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)

    def test_pool_bounds(self) -> None:
        self.assertEqual(POOL_CATALOG["provider_io"].max_count, 8)
        self.assertEqual(POOL_CATALOG["market_feed"].max_count, 4)
        self.assertEqual(POOL_CATALOG["model_download"].max_count, 2)
        self.assertIn("model_import.local", POOL_CATALOG["model_download"].job_kinds)


class SchedulerSpecialistRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jobs = _job_runtime(self.root / "s.db")
        self.store = ScheduleStore(self.root / "s.db")
        self.store.initialize()
        self.runner = ScheduleRunner(self.store, jobs=self.jobs)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _fire(self, cap: str) -> str:
        self.store.create(
            name=f"sched-{cap}",
            target_kind=ScheduleTargetKind.JOB,
            target_ref=cap,
            interval_seconds=3600,
            target_payload={"arguments": {}},
            start_after_seconds=0,
        )
        fired = self.runner.tick_enqueue_only()
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["ok"])
        job = self.jobs.get(fired[0]["job_id"])
        assert job is not None
        return str(job.worker_pool)

    def test_scheduled_provider_and_model_route_to_specialists(self) -> None:
        self.assertEqual(self._fire("provider.chat.complete"), "provider_io")
        # Clear due schedules by advancing — create fresh store jobs for remaining.
        for cap, pool in (
            ("provider.market.fetch", "provider_io"),
            ("model_download.start", "model_download"),
            ("provider.market.stream", "market_feed"),
            ("model_import.local", "model_download"),
        ):
            # Reset schedule due state via new runner tick with new schedule names.
            self.store.create(
                name=f"again-{cap}",
                target_kind=ScheduleTargetKind.JOB,
                target_ref=cap,
                interval_seconds=3600,
                target_payload={"arguments": {"download_id": "x", "repository_id": "r"} if "download" in cap else {"path": "/tmp/x"}},
                start_after_seconds=0,
            )
            fired = self.runner.tick_enqueue_only()
            self.assertTrue(any(r.get("ok") for r in fired), msg=cap)
            job_id = next(r["job_id"] for r in fired if r.get("ok"))
            job = self.jobs.get(job_id)
            assert job is not None
            self.assertEqual(job.worker_pool, pool, msg=cap)
            self.assertNotEqual(job.worker_pool, "general", msg=cap)
            self.assertNotEqual(job.worker_pool, "scheduler", msg=cap)


class EndpointLocalityTests(unittest.TestCase):
    def test_loopback_is_local(self) -> None:
        for url in (
            "http://127.0.0.1:1234/v1",
            "http://localhost:11434",
            "http://[::1]:8080/v1",
        ):
            self.assertEqual(
                classify_endpoint_locality(url),
                EndpointLocality.LOCAL_TRUSTED,
                msg=url,
            )

    def test_public_cloud_is_remote(self) -> None:
        self.assertEqual(
            classify_endpoint_locality("https://api.openai.com/v1"),
            EndpointLocality.REMOTE,
        )

    def test_allow_private_hosts_payload_does_not_grant_trust(self) -> None:
        # Classification ignores caller flags — private LAN without config is REMOTE.
        self.assertEqual(
            classify_endpoint_locality("http://10.0.0.5:8080/v1"),
            EndpointLocality.REMOTE,
        )


class ModelImportExternalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "m.db"
        MigrationRunner(self.db).apply_all()
        self.store = ModelStore(self.db)
        self.registry = ModelRegistry(self.store)
        self.allowed = self.root / "models"
        self.allowed.mkdir()
        self.imports = ImportService(
            self.store, self.registry, allowed_roots=[self.allowed]
        )
        self._prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
        else:
            os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = self._prev
        self.tmp.cleanup()

    def _gguf(self, name: str = "toy.gguf") -> Path:
        target = self.allowed / name
        # Minimal GGUF magic + padding
        target.write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\0" * 64)
        return target

    def test_inline_dev_path_when_externalize_off(self) -> None:
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "0"
        path = self._gguf()
        result = self.imports.enqueue_local_import(str(path))
        self.assertEqual(result["executed_via"], "inline_dev")
        self.assertIn("model", result)
        self.assertTrue(result["model"]["id"].startswith("imported:"))

    def test_externalize_without_runtime_fails_closed(self) -> None:
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        path = self._gguf()
        from Data.modules.models.errors import ModelControlError

        with self.assertRaises(ModelControlError) as ctx:
            self.imports.enqueue_local_import(str(path))
        self.assertEqual(ctx.exception.code, "MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE")
        self.assertEqual(ctx.exception.http_status, 503)

    def test_streaming_fingerprint_no_read_bytes(self) -> None:
        path = self._gguf("big.gguf")
        # Instrument to ensure ImportService never calls Path.read_bytes.
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("no read_bytes")):
            fp = ImportService.fingerprint_file(path, measure_hash=True)
        self.assertEqual(fp["hash_status"], "MEASURED")
        self.assertEqual(fp["sha256"], hashlib.sha256(path.open("rb").read()).hexdigest())

    def test_worker_local_import_registers(self) -> None:
        path = self._gguf("worker.gguf")
        jobs = _job_runtime(self.root / "jobs.db")
        job = jobs.enqueue(
            capability_id="model_import.local",
            arguments={
                "import_id": "imp-1",
                "path": str(path),
                "allowed_roots": [str(self.allowed)],
                "source": "local_file",
            },
            worker_pool="model_download",
        )
        claimed = jobs.store.claim_next_queued(
            worker_id="md-1",
            worker_pool="model_download",
            lease_ttl_seconds=30.0,
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        executor = ModelDownloadExecutor(db_path=self.db)
        ctx = {
            "job_store": jobs.store,
            "worker_id": "md-1",
            "lease_owner": claimed.lease_owner or "md-1",
            "lease_ttl_seconds": 30.0,
        }
        result = executor.execute_job(ctx, claimed)
        self.assertEqual(result.get("status"), "succeeded")
        self.assertTrue(str(result.get("model_id", "")).startswith("imported:"))
        refreshed = jobs.get(job.job_id)
        assert refreshed is not None
        self.assertEqual(refreshed.state, JobState.COMPLETED)

    def test_changed_during_import(self) -> None:
        path = self._gguf("mutate.gguf")
        resolved = self.imports.validate_import_path(str(path))
        from Data.modules.models.errors import ModelControlError

        real_stat = Path.stat
        calls = {"n": 0}

        def _stat(self, *a, **k):
            st = real_stat(self, *a, **k)
            if self == resolved:
                calls["n"] += 1
                if calls["n"] >= 2:
                    return mock.Mock(
                        st_size=st.st_size + 1,
                        st_mtime_ns=st.st_mtime_ns + 1,
                        st_mode=st.st_mode,
                        st_mtime=st.st_mtime,
                    )
            return st

        with mock.patch.object(Path, "stat", _stat):
            with self.assertRaises(ModelControlError) as ctx:
                self.imports._register_verified(resolved, measure_hash=True)
        self.assertEqual(ctx.exception.code, "MODEL_CHANGED_DURING_IMPORT")


class ArchitectureNoControlPlaneNetworkAstTests(unittest.TestCase):
    def test_models_import_route_does_not_call_import_local_path_sync(self) -> None:
        path = Path("Data/backend/routes/models.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found_enqueue = False
        found_direct = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "import_model":
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "enqueue_local_import":
                        found_enqueue = True
                    if isinstance(child, ast.Attribute) and child.attr == "import_local_path":
                        found_direct = True
        self.assertTrue(found_enqueue)
        self.assertFalse(found_direct)

    def test_scheduler_does_not_hardcode_general_pool(self) -> None:
        src = Path("Data/modules/schedules/runner.py").read_text(encoding="utf-8")
        self.assertNotIn('worker_pool="general"', src)
        self.assertIn("pool_for_capability", src)

    def test_ollama_adapter_pull_does_not_httpx(self) -> None:
        src = Path("Data/modules/models/providers/ollama.py").read_text(encoding="utf-8")
        # pull() body must not open AsyncClient
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "pull":
                body_src = ast.get_source_segment(src, node) or ""
                self.assertNotIn("AsyncClient", body_src)
                self.assertIn("model_download", body_src.lower())


class ProviderFailClosedFacadeTests(unittest.TestCase):
    def test_submit_without_ready_workers_raises(self) -> None:
        from Data.modules.provider_io.errors import ProviderError
        from Data.modules.provider_io.facade import ProviderExecutionClient

        with tempfile.TemporaryDirectory() as td:
            jobs = _job_runtime(Path(td) / "p.db")
            client = ProviderExecutionClient(jobs)
            with mock.patch(
                "Data.modules.provider_io.readiness.provider_io_workers_ready",
                return_value=False,
            ):
                with self.assertRaises(ProviderError) as ctx:
                    client.submit(
                        provider="openai",
                        capability="chat.complete",
                        payload={"endpoint": "https://api.openai.com/v1", "messages": []},
                    )
            self.assertEqual(ctx.exception.code.value, "PROVIDER_EXECUTION_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
