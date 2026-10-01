"""Wave 1–2: Research execution-plane fail-closed invariants."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.research.execution_gate import (
    WorkerMeasuredState,
    allow_inprocess_research_execution,
    probe_research_worker_availability,
    refuse_inline_research,
    resolve_execution_mode,
    runners_externalized,
)
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import ResearchError, ResearchStatus
from Data.modules.research.service import ResearchService
from Data.modules.research.web import UnconfiguredWebProvider
from Data.modules.research.worker import _fence_reason


class ExecutionGateTests(unittest.TestCase):
    def test_externalize_true_is_external(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            self.assertEqual(resolve_execution_mode(), "external")
            self.assertTrue(runners_externalized())
            self.assertFalse(allow_inprocess_research_execution())

    def test_settings_exception_fails_closed_to_external(self) -> None:
        env = {
            "LEVIATHAN_WORKERS_EXTERNALIZE_API": "",
            "LEVIATHAN_RESEARCH_RUNNER": "",
            "LEVIATHAN_RESEARCH_ALLOW_INPROCESS_TEST": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            with mock.patch(
                "Data.modules.workers.settings.load_worker_settings",
                side_effect=RuntimeError("boom"),
            ):
                with mock.patch(
                    "Data.modules.research.execution_gate.pytest_session_active",
                    return_value=False,
                ):
                    with mock.patch(
                        "Data.modules.research.execution_gate.inprocess_execution_explicitly_allowed",
                        return_value=False,
                    ):
                        self.assertEqual(resolve_execution_mode(), "external")

    def test_probe_exception_is_unknown_not_available(self) -> None:
        with mock.patch(
            "Data.modules.workers.settings.load_worker_settings",
            side_effect=RuntimeError("registry down"),
        ):
            av = probe_research_worker_availability(db_path=Path("/tmp/x.db"), runners_are_external=True)
        self.assertEqual(av.worker_state, WorkerMeasuredState.UNKNOWN)
        self.assertFalse(av.worker_measured)
        self.assertTrue(av.can_enqueue)
        self.assertIn("probe failed", av.wait_reason or "")

    def test_refuse_inline_raises_typed_error(self) -> None:
        with self.assertRaises(ResearchError) as ctx:
            refuse_inline_research(reason="job_runtime_unbound", capability="research.advance")
        self.assertEqual(ctx.exception.code, "RESEARCH_RUNTIME_UNAVAILABLE")
        self.assertEqual(ctx.exception.http_status, 503)


class ExternalFailClosedServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "r.db"
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _planned(self):
        p = self.service.create_project(topic="fail closed", depth="quick", execution_mode="custom")
        # plan() is sync deterministic — allowed even without runtime in tests when not external
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "0"}, clear=False):
            return self.service.plan(p.project_id)

    def test_enqueue_run_external_without_job_runtime_refuses_spawn(self) -> None:
        planned = self._planned()
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            with mock.patch.object(self.service, "_spawn_run") as spawn:
                with self.assertRaises(ResearchError) as ctx:
                    self.service.enqueue_run(planned.project_id)
                self.assertEqual(ctx.exception.code, "RESEARCH_RUNTIME_UNAVAILABLE")
                spawn.assert_not_called()

    def test_add_url_external_without_job_runtime_refuses_inline(self) -> None:
        planned = self._planned()
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            with mock.patch.object(self.service, "_fetch_url_source_inline") as inline:
                with self.assertRaises(ResearchError) as ctx:
                    self.service.add_url_source(planned.project_id, "https://example.com/a")
                self.assertEqual(ctx.exception.code, "RESEARCH_RUNTIME_UNAVAILABLE")
                inline.assert_not_called()

    def test_regenerate_report_external_without_job_runtime_refuses_inline(self) -> None:
        planned = self._planned()
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            with mock.patch.object(self.service, "_regenerate_report_inline") as inline:
                with self.assertRaises(ResearchError) as ctx:
                    self.service.regenerate_report(planned.project_id)
                self.assertEqual(ctx.exception.code, "RESEARCH_RUNTIME_UNAVAILABLE")
                inline.assert_not_called()

    def test_spawn_run_refused_when_externalized(self) -> None:
        planned = self._planned()
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            with self.assertRaises(ResearchError) as ctx:
                self.service._spawn_run(planned.project_id, deepen=False, extra_rounds=0, resume=False)
            self.assertEqual(ctx.exception.code, "RESEARCH_RUNTIME_UNAVAILABLE")


class FenceReasonTests(unittest.TestCase):
    def test_cancel_and_lease_lost_distinguished(self) -> None:
        cancel_flag = threading.Event()
        lease_flag = threading.Event()
        ctx = {
            "job_cancel_check": cancel_flag.is_set,
            "lease_lost": lease_flag,
        }
        self.assertIsNone(_fence_reason(ctx))
        cancel_flag.set()
        self.assertEqual(_fence_reason(ctx), "cancel")
        cancel_flag.clear()
        lease_flag.set()
        self.assertEqual(_fence_reason(ctx), "lease_lost")


class PlanProvenanceTests(unittest.TestCase):
    def test_plan_exposes_enrichment_provenance(self) -> None:
        from Data.modules.research.budgets import budget_for_depth
        from Data.modules.research.planner import build_plan
        from Data.modules.research.types import ResearchDepth, ResearchProject, ResearchStatus
        from Data.modules.research.store import utc_now

        project = ResearchProject(
            project_id="p1",
            title="t",
            topic="SQLite WAL durability",
            objective="",
            status=ResearchStatus.DRAFT,
            depth=ResearchDepth.QUICK,
            budget=budget_for_depth(ResearchDepth.QUICK),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        plan = build_plan(project)
        self.assertIn("plan_provenance", plan.public_dict())
        self.assertIn(plan.plan_provenance.get("enrichment"), {"succeeded", "error", "not_attempted"})


class ConnectDatasetAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ResearchStore(self.root / "d.db")
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_client_indexed_true_rejected_when_canonical_registered(self) -> None:
        project = self.service.create_project(topic="ds", depth="quick")
        fake_ds = mock.Mock()
        fake_ds.learning_state_for_dataset.return_value = {
            "canonicalState": "REGISTERED",
            "learned": False,
            "versionId": "v1",
            "usableIndexId": None,
        }
        self.service.dataset_service = fake_ds
        with self.assertRaises(ResearchError) as ctx:
            self.service.connect_dataset(
                project.project_id,
                dataset_id="ds1",
                indexed=True,
            )
        self.assertEqual(ctx.exception.code, "DATASET_NOT_LEARNED")

    def test_learned_canonical_connects(self) -> None:
        project = self.service.create_project(topic="ds", depth="quick")
        fake_ds = mock.Mock()
        fake_ds.learning_state_for_dataset.return_value = {
            "canonicalState": "LEARNED",
            "learned": True,
            "versionId": "v1",
            "usableIndexId": "idx1",
            "indexId": "idx1",
        }
        self.service.dataset_service = fake_ds
        out = self.service.connect_dataset(
            project.project_id,
            dataset_id="ds1",
            indexed=False,  # advisory false must not block when canonical LEARNED
        )
        self.assertEqual(len(out.connected_datasets), 1)
        self.assertEqual(out.connected_datasets[0]["canonical_state"], "LEARNED")
        self.assertTrue(out.connected_datasets[0]["indexed"])


class UrlReservedSourceLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ResearchStore(self.root / "u.db")
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_execute_fetch_url_marks_reserved_failed_on_error(self) -> None:
        from Data.modules.research.types import (
            BrainStatus,
            ParseStatus,
            ResearchSource,
            SourceType,
        )
        from Data.modules.research.store import utc_now
        import uuid

        project = self.service.create_project(topic="url", depth="quick")
        source_id = str(uuid.uuid4())
        pending = ResearchSource(
            source_id=source_id,
            project_id=project.project_id,
            source_type=SourceType.WEB_PAGE,
            original_uri="https://example.com/x",
            canonical_uri="https://example.com/x",
            title="https://example.com/x",
            parse_status=ParseStatus.PENDING,
            brain_status=BrainStatus.PENDING,
            provenance={"pending_fetch": True},
            metadata={"fetch_status": "PENDING"},
            created_at=utc_now(),
        )
        self.store.upsert_source(pending)
        with self.assertRaises(ResearchError):
            self.service.execute_fetch_url(
                project.project_id,
                "https://example.com/x",
                source_id=source_id,
            )
        stored = self.store.get_source(source_id)
        assert stored is not None
        self.assertEqual(stored.parse_status, ParseStatus.FAILED)
        self.assertEqual(stored.metadata.get("fetch_status"), "FAILED")


if __name__ == "__main__":
    unittest.main()
