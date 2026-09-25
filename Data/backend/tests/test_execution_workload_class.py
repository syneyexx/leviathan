"""W2 — Heavy workload classification (INLINE_SAFE / EXTERNAL_*)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    ExecutionWorkloadClass,
    api_may_execute_inline,
    build_default_catalog,
    classify_capability,
    is_external_required,
    normalize_capability_metadata,
)
from Data.modules.execution.workload import (
    KNOWN_INLINE_SAFE,
    externalize_api_enabled,
    parse_execution_class,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.store import JobStore


class ParseClassTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(parse_execution_class("inline"), ExecutionWorkloadClass.INLINE_SAFE)
        self.assertEqual(parse_execution_class("heavy"), ExecutionWorkloadClass.EXTERNAL_REQUIRED)
        self.assertEqual(
            parse_execution_class("EXTERNAL_PREFERRED"),
            ExecutionWorkloadClass.EXTERNAL_PREFERRED,
        )


class ClassifyCapabilityTests(unittest.TestCase):
    def test_explicit_metadata_wins(self) -> None:
        cls = classify_capability(
            "research.advance",
            metadata={"execution_class": "INLINE_SAFE"},
        )
        self.assertEqual(cls, ExecutionWorkloadClass.INLINE_SAFE)

    def test_external_worker_capabilities_required(self) -> None:
        for cap in (
            "research.advance",
            "source_ingestion.process",
            "dataset.process",
            "knowledge.prepare",
            "embedding.batch",
            "evaluation.run",
            "training.control",
            "model_download.start",
            "mcp.call",
            "provider.http",
        ):
            with self.subTest(cap=cap):
                self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)
                self.assertEqual(
                    classify_capability(cap),
                    ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                )
                self.assertTrue(is_external_required(cap))

    def test_pdf_parser_required(self) -> None:
        self.assertEqual(
            classify_capability("file.parse_pdf"),
            ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        )

    def test_inline_safe_known(self) -> None:
        for cap in KNOWN_INLINE_SAFE:
            with self.subTest(cap=cap):
                self.assertEqual(
                    classify_capability(cap),
                    ExecutionWorkloadClass.INLINE_SAFE,
                )

    def test_browser_preferred(self) -> None:
        self.assertEqual(
            classify_capability("browser.navigate"),
            ExecutionWorkloadClass.EXTERNAL_PREFERRED,
        )

    def test_normalize_metadata_sets_execution_class(self) -> None:
        meta = normalize_capability_metadata(
            {"worker_kind": "research"},
            capability_id="research.advance",
        )
        self.assertEqual(meta["execution_class"], "EXTERNAL_REQUIRED")
        meta2 = normalize_capability_metadata({}, capability_id="compute.numeric")
        self.assertEqual(meta2["execution_class"], "INLINE_SAFE")


class CatalogClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_default_catalog()

    def test_fabric_caps_expose_external_required(self) -> None:
        for cap_id in (
            "research.advance",
            "source_ingestion.process",
            "dataset.process",
            "file.parse_pdf",
        ):
            with self.subTest(cap_id=cap_id):
                definition = self.catalog.get(cap_id)
                assert definition is not None
                self.assertEqual(definition.execution_class(), "EXTERNAL_REQUIRED")
                pub = definition.public_dict()
                self.assertEqual(pub["execution_class"], "EXTERNAL_REQUIRED")
                self.assertEqual(pub["metadata"]["execution_class"], "EXTERNAL_REQUIRED")

    def test_compute_numeric_inline(self) -> None:
        definition = self.catalog.get("compute.numeric")
        assert definition is not None
        self.assertEqual(definition.execution_class(), "INLINE_SAFE")


class ApiMayExecuteInlineTests(unittest.TestCase):
    def test_externalize_true_blocks_required(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            self.assertTrue(externalize_api_enabled())
            self.assertFalse(api_may_execute_inline("research.advance"))
            self.assertTrue(api_may_execute_inline("compute.numeric"))

    def test_developer_mode_allows_inline(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "0"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            self.assertTrue(api_may_execute_inline("research.advance"))

    def test_worker_process_allows_inline(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_WORKER_ID": "research-0-test",
            },
            clear=False,
        ):
            self.assertTrue(api_may_execute_inline("file.parse_pdf"))


class GatewayRespectsClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_default_catalog()
        self.gateway = ExecutionGateway(catalog=self.catalog)

    def tearDown(self) -> None:
        os.environ.pop("LEVIATHAN_WORKER_ID", None)

    def test_api_rejects_external_required_pdf(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            result = self.gateway.execute(
                CapabilityRequest(
                    capability_id="file.parse_pdf",
                    arguments={"path": "/tmp/x.pdf"},
                    requested_by="api",
                )
            )
            self.assertEqual(result.status, CapabilityStatus.REJECTED)
            self.assertIn("EXTERNAL_REQUIRED", result.error or "")
            # Telemetry reason path uses worker_required
            self.assertTrue(
                "worker" in (result.error or "").lower()
                or "EXTERNAL_REQUIRED" in (result.error or "")
            )

    def test_worker_can_dispatch_past_classification_gate(self) -> None:
        """Worker process passes classification; may still fail later (no pdf / path)."""
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_WORKER_ID": "general-0-test",
            },
            clear=False,
        ):
            result = self.gateway.execute(
                CapabilityRequest(
                    capability_id="file.parse_pdf",
                    arguments={"path": "/tmp/does-not-exist.pdf"},
                    requested_by="worker",
                )
            )
            # Must not be the classification rejection.
            self.assertNotIn("EXTERNAL_REQUIRED and must run", result.error or "")

    def test_inline_safe_still_runs(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            # file.read requires approval? READ is auto-allowed. Missing path → validation.
            result = self.gateway.execute(
                CapabilityRequest(capability_id="compute.numeric", arguments={"operation": "add"})
            )
            # May complete or fail on missing function executor — but not worker_required.
            self.assertNotIn("EXTERNAL_REQUIRED and must run", result.error or "")


class JobRuntimeEnqueueObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.runtime = JobRuntime(self.store, self.gateway, ResourceManager(2))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enqueue_emits_job_queued_not_worker_started(self) -> None:
        from Data.modules.workers.events import WorkerEventEmitter, set_worker_event_emitter
        import io

        buf = io.StringIO()
        set_worker_event_emitter(WorkerEventEmitter(stream=buf, enable_structured=False))
        try:
            job = self.runtime.enqueue(
                capability_id="research.advance",
                arguments={"project_id": "p1"},
                metadata={"topic": "Neuromorphic computing"},
            )
            text = buf.getvalue()
            self.assertIn("[JOB]", text)
            self.assertIn("ingepland", text)
            self.assertIn("Neuromorphic computing", text)
            self.assertIn(job.job_id[:8], text)
            self.assertNotIn("gestart", text)
        finally:
            set_worker_event_emitter(None)


if __name__ == "__main__":
    unittest.main()
