"""Coding execution externalization — architecture + security regressions."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.coding.execution_gate import (
    allow_inprocess_execution,
    normalize_runner_value,
    runners_externalized,
)
from Data.modules.coding.git_ops import validate_remote
from Data.modules.coding.map_cache import get_cached_map, put_cached_map
from Data.modules.coding.process import kill_process_tree, run_argv
from Data.modules.coding.semantic_map import SemanticMapBuilder
from Data.modules.coding.service import CodingControlPlane
from Data.modules.coding.store import CodingStore
from Data.modules.coding.types import CodingError, Mission, SessionStatus
from Data.modules.coding.verify_ops import run_verification
from Data.modules.coding.worker import CodingWorker, process_coding_job
from Data.modules.coding.workspace import search_files
from Data.modules.coding.workspace_gen import capture_workspace_generation
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.workers.pools import pool_for_capability


CODING_HEAVY = (
    "coding.advance",
    "coding.run_tests",
    "coding.test",
    "coding.semantic_map.build",
    "coding.verify",
    "coding.git.clone",
    "coding.git.fetch",
    "coding.git.update",
    "coding.git.checkout",
    "coding.repo.analyze",
)


class CodingPoolOwnershipTests(unittest.TestCase):
    def test_heavy_caps_owned_by_coding_pool(self) -> None:
        for cap in CODING_HEAVY:
            self.assertEqual(pool_for_capability(cap), "coding", msg=cap)
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )

    def test_small_reads_remain_inline(self) -> None:
        self.assertEqual(
            classify_capability("git.status"),
            ExecutionWorkloadClass.INLINE_SAFE,
        )
        self.assertEqual(
            classify_capability("git.diff", metadata={"execution_class": "INLINE_SAFE"}),
            ExecutionWorkloadClass.INLINE_SAFE,
        )

    def test_api_cannot_inline_heavy_when_externalized(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            for cap in ("coding.advance", "coding.run_tests", "coding.semantic_map.build"):
                self.assertFalse(api_may_execute_inline(cap), msg=cap)


class CodingEntrypointNoDualClaimTests(unittest.TestCase):
    def test_entrypoint_source_does_not_call_process_next(self) -> None:
        path = Path("Data/modules/workers/entrypoints/coding.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    calls.append(func.attr)
                elif isinstance(func, ast.Name):
                    calls.append(func.id)
        self.assertIn("process_coding_job", calls)
        self.assertNotIn("process_next", calls)

    def test_process_coding_job_executes_claimed_advance(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "c.db"
        MigrationRunner(db).apply_all()
        ws = root / "ws"
        ws.mkdir()
        store = CodingStore(db)
        store.initialize()
        session = store.create_session(
            user_goal="x",
            workspace_root=str(ws),
            mission=Mission.GENERIC,
            status=SessionStatus.RUNNING,
        )
        job_store = JobStore(db)
        job_store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        runtime = JobRuntime(job_store, gateway, ResourceManager(2))
        job = runtime.enqueue(
            capability_id="coding.advance",
            arguments={"session_id": session.session_id},
            requested_by="test",
            worker_pool="coding",
        )
        claimed = job_store.claim_next_queued(
            worker_id="coding-test-1",
            capability_ids={"coding.advance"},
            worker_pool="coding",
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.job_id, job.job_id)

        class FakeLoop:
            def run_round(self, session_id, approval_ids=None):
                from Data.modules.coding.types import LoopResult

                s = store.get_session(session_id)
                store.update_session(session_id, status=SessionStatus.COMPLETED, round_count=1)
                s2 = store.get_session(session_id)
                return LoopResult(status=SessionStatus.COMPLETED, session=s2, error=None)

        class Plane:
            store = store
            loop = FakeLoop()
            job_runtime = runtime
            settings = None

        ctx = {
            "job_store": job_store,
            "job_runtime": runtime,
            "worker_id": "coding-test-1",
            "coding_service": Plane(),
        }
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKER_ID": "coding-test-1"}, clear=False):
            out = process_coding_job(ctx, claimed)
        self.assertEqual(out.get("status"), "COMPLETED")
        refreshed = job_store.get(job.job_id)
        self.assertEqual(refreshed.state, JobState.COMPLETED)


class NoBackgroundApiWorkerTests(unittest.TestCase):
    def test_start_background_noop_when_externalized(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "c.db"
        MigrationRunner(db).apply_all()
        store = CodingStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        settings = mock.Mock()
        settings.features.agents_enabled = True
        settings.features.coding_enabled = True
        settings.coding.workspace = Path(tmp.name) / "ws"
        settings.coding.workspace.mkdir(exist_ok=True)
        plane = CodingControlPlane(
            store,
            gateway=gateway,
            settings=settings,
            agents_enabled=True,
            coding_enabled=True,
        )
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_CODING_RUNNER": "fabric",
                "LEVIATHAN_CODING_ALLOW_INPROCESS_TEST": "0",
            },
            clear=False,
        ):
            # Even under pytest, explicit fabric + allow=0 should no-op.
            # allow gate uses pytest OR env; force both closed via monkeypatch.
            with mock.patch(
                "Data.modules.coding.execution_gate.inprocess_execution_explicitly_allowed",
                return_value=False,
            ):
                plane.start_background()
                self.assertIsNone(plane.worker._thread)


class ApprovalResumeEnqueueTests(unittest.TestCase):
    def test_approval_resume_does_not_call_run_round_when_job_runtime_bound(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "c.db"
        MigrationRunner(db).apply_all()
        ws = Path(tmp.name) / "ws"
        ws.mkdir()
        store = CodingStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        job_store = JobStore(db)
        job_store.initialize()
        runtime = JobRuntime(job_store, gateway, ResourceManager(2))
        settings = mock.Mock()
        settings.features.agents_enabled = True
        settings.features.coding_enabled = True
        settings.coding.workspace = ws
        plane = CodingControlPlane(
            store,
            gateway=gateway,
            settings=settings,
            agents_enabled=True,
            coding_enabled=True,
            job_runtime=runtime,
        )
        session = store.create_session(
            user_goal="write",
            workspace_root=str(ws),
            mission=Mission.SCAFFOLD,
            status=SessionStatus.WAITING_APPROVAL,
            pending_capability={"capability_id": "file.write", "arguments": {"path": "a.py"}},
        )
        boom = mock.Mock(side_effect=AssertionError("run_round must not run on API"))
        plane.loop.run_round = boom  # type: ignore[method-assign]
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            plane.start_turn(session.session_id, approval_id="apr-1")
        boom.assert_not_called()
        jobs = [j for j in job_store.list_jobs(limit=20) if j.capability_id == "coding.advance"]
        self.assertTrue(jobs)
        self.assertEqual(jobs[0].arguments.get("approval_id"), "apr-1")


class SemanticMapExternalTests(unittest.TestCase):
    def test_cached_read_and_enqueue_refresh(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "c.db"
        MigrationRunner(db).apply_all()
        ws = root / "ws"
        ws.mkdir()
        (ws / "a.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        store = CodingStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        job_store = JobStore(db)
        job_store.initialize()
        runtime = JobRuntime(job_store, gateway, ResourceManager(2))
        settings = mock.Mock()
        settings.features.agents_enabled = True
        settings.features.coding_enabled = True
        settings.coding.workspace = ws
        plane = CodingControlPlane(
            store,
            gateway=gateway,
            settings=settings,
            agents_enabled=True,
            coding_enabled=True,
            job_runtime=runtime,
        )
        smap = SemanticMapBuilder(ws).build()
        put_cached_map(
            db,
            workspace_root=str(ws.resolve()),
            generated_at=smap.generated_at,
            content_hash=smap.content_fingerprint(),
            payload=smap.public_dict(),
            generation_fingerprint=capture_workspace_generation(ws).fingerprint,
            status="ready",
        )
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            out = plane.semantic_map(workspace_root=str(ws))
        self.assertTrue(out.get("cached"))
        self.assertIsNotNone(out.get("map"))

    def test_incremental_and_truncation_truth(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name) / "ws"
        ws.mkdir()
        (ws / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
        (ws / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
        first = SemanticMapBuilder(ws, max_files=10).build()
        self.assertGreaterEqual(first.file_count if hasattr(first, "file_count") else len(first.files), 1)
        second = SemanticMapBuilder(ws, max_files=10).build(previous=first)
        self.assertTrue(second.incremental)
        tiny = SemanticMapBuilder(ws, max_files=1).build()
        self.assertTrue(tiny.limits.get("truncated"))
        self.assertGreaterEqual(int(tiny.limits.get("discovered_files") or 0), 1)


class ProcessAndSearchTests(unittest.TestCase):
    def test_argv_metacharacters_remain_data(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = Path(tmp.name)
        result = run_argv(
            ["python", "-c", "print('; rm -rf /')"],
            cwd=cwd,
            timeout_seconds=10,
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("; rm -rf /", result.stdout)

    def test_timeout_status(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = run_argv(
            ["python", "-c", "import time; time.sleep(5)"],
            cwd=Path(tmp.name),
            timeout_seconds=0.3,
        )
        self.assertEqual(result.status, "TIMEOUT")
        self.assertEqual(result.exit_code, 124)

    def test_streaming_search_no_whole_file_read(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        big = ws / "big.txt"
        big.write_text("alpha\n" + ("noise\n" * 1000) + "needle here\n", encoding="utf-8")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("no read_bytes")):
            out = search_files(ws, "needle")
        self.assertTrue(any("needle" in (h.get("text") or "") for h in out["hits"]))


class GitSecurityTests(unittest.TestCase):
    def test_rejects_option_shaped_and_file_remote(self) -> None:
        with self.assertRaises(CodingError):
            validate_remote("--upload-pack=evil")
        with self.assertRaises(CodingError):
            validate_remote("file:///etc/passwd")
        with self.assertRaises(CodingError):
            validate_remote("/tmp/repo.git")

    def test_accepts_https(self) -> None:
        self.assertTrue(validate_remote("https://example.com/org/repo.git").startswith("https://"))


class VerifyOpsTests(unittest.TestCase):
    def test_missing_tool_is_tool_unavailable(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = run_verification(
            phase="lint",
            workspace_root=Path(tmp.name),
            tool="not-a-real-linter",
        )
        self.assertEqual(out["status"], "TOOL_UNAVAILABLE")
        self.assertFalse(out["executed"])

    def test_pytest_receipt(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        test_file = ws / "test_ok.py"
        test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        out = run_verification(
            phase="test",
            workspace_root=ws,
            selector=str(test_file),
            tool="pytest",
            timeout_seconds=60,
        )
        self.assertTrue(out.get("executed"))
        self.assertIn(out.get("status"), {"PASSED", "FAILED", "TOOL_UNAVAILABLE"})
        if out.get("status") == "PASSED":
            self.assertTrue(out.get("passed"))
            self.assertEqual(out.get("exit_code"), 0)


class SessionClaimFenceTests(unittest.TestCase):
    def test_production_process_next_refuses_without_allow(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "c.db"
        MigrationRunner(db).apply_all()
        store = CodingStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        from Data.modules.coding.loop import CodingLoop

        loop = CodingLoop(store, gateway=gateway, agents_enabled=True, coding_enabled=True)
        worker = CodingWorker(store, loop, settings=None)
        with mock.patch(
            "Data.modules.coding.worker.allow_inprocess_execution",
            return_value=False,
        ):
            self.assertFalse(worker.process_next())


class ArchitectureAstGuardTests(unittest.TestCase):
    def test_routes_do_not_call_run_round_or_builder_build(self) -> None:
        path = Path("Data/backend/routes/coding.py")
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        attrs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                attrs.add(node.attr)
        self.assertNotIn("run_round", attrs)
        self.assertNotIn("SemanticMapBuilder", attrs)

    def test_service_resume_source_enqueues(self) -> None:
        path = Path("Data/modules/coding/service.py")
        src = path.read_text(encoding="utf-8")
        # Production path must enqueue; inline run_round only behind allow gate.
        self.assertIn("enqueue_advance", src)
        self.assertIn("refuse_inline_coding", src)


if __name__ == "__main__":
    unittest.main()
