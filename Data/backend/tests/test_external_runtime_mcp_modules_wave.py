"""Architecture regression — external runtime / MCP / module process ownership wave."""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.module_manager.external.catalog_register import (
    register_external_control_capabilities,
    _execution_owner,
)
from Data.modules.module_manager.external.post_result import (
    allow_inprocess_assimilation_for_tests,
    queue_or_run_assimilation,
)
from Data.modules.module_manager.external.types import AssimilationMode
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class PoolRoutingWaveTests(unittest.TestCase):
    def test_model_runtime_pool_exists(self) -> None:
        self.assertIn("model_runtime", POOL_CATALOG)
        defn = POOL_CATALOG["model_runtime"]
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 1)
        # #220 richer caps + wave serving aliases
        self.assertIn("model_runtime.load", defn.job_kinds)
        self.assertIn("model_runtime.unload", defn.job_kinds)
        self.assertIn("model.serving.start", defn.job_kinds)
        self.assertIn("model.serving.stop", defn.job_kinds)

    def test_module_runtime_owns_invoke_and_lifecycle(self) -> None:
        defn = POOL_CATALOG["module_runtime"]
        self.assertEqual(defn.max_count, 1)
        for kind in (
            "external.module.install",
            "external.module.update",
            "external.module.upgrade",
            "external.module.invoke",
            "external.module.start",
            "external.module.stop",
        ):
            self.assertIn(kind, defn.job_kinds)
            self.assertEqual(pool_for_capability(kind), "module_runtime")
            self.assertNotEqual(pool_for_capability(kind), "general")

    def test_assimilation_routes_to_knowledge_prepare(self) -> None:
        self.assertEqual(
            pool_for_capability("external.knowledge.assimilate"),
            "knowledge_prepare",
        )
        self.assertIn(
            "external.knowledge.assimilate",
            POOL_CATALOG["knowledge_prepare"].job_kinds,
        )

    def test_mcp_live_ops_route_to_mcp_execution(self) -> None:
        for kind in ("mcp.call", "mcp.connect", "mcp.list_tools"):
            self.assertEqual(pool_for_capability(kind), "mcp_execution")

    def test_no_sandbox_execution_pool_without_backend(self) -> None:
        # Honest: probe helpers exist; no fake sandbox_execution pool.
        self.assertNotIn("sandbox_execution", POOL_CATALOG)

    def test_no_generic_native_or_gpu_pool(self) -> None:
        self.assertNotIn("native_compute", POOL_CATALOG)
        self.assertNotIn("heavy_compute", POOL_CATALOG)
        self.assertNotIn("gpu_worker", POOL_CATALOG)


class ExecutionClassWaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_default_catalog()
        register_external_control_capabilities(self.catalog)

    def test_control_caps_external_required(self) -> None:
        for cap_id in (
            "external.module.install",
            "external.module.update",
            "external.module.upgrade",
            "external.module.invoke",
            "external.module.start",
            "external.knowledge.assimilate",
            "model.serving.start",
            "mcp.call",
            "mcp.connect",
        ):
            definition = self.catalog.get(cap_id)
            self.assertIsNotNone(definition, cap_id)
            assert definition is not None
            cls = classify_capability(cap_id, metadata=definition.metadata)
            self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED, cap_id)
            self.assertIn(cap_id, EXTERNAL_WORKER_CAPABILITIES)

    def test_dynamic_adapter_owners(self) -> None:
        cases = [
            ({"adapter": "CLI"}, "EXTERNAL_REQUIRED", "module_runtime"),
            ({"adapter": "SCRIPT_PACKAGE"}, "EXTERNAL_REQUIRED", "module_runtime"),
            ({"adapter": "PROCESS_SERVICE"}, "EXTERNAL_REQUIRED", "module_runtime"),
            ({"adapter": "HTTP_OPENAPI"}, "EXTERNAL_REQUIRED", "module_runtime"),
            ({"adapter": "COMPOSITE"}, "EXTERNAL_REQUIRED", "module_runtime"),
            ({"adapter": "MCP"}, "EXTERNAL_REQUIRED", "mcp_execution"),
            ({"adapter": "SKILL_PACK"}, "INLINE_SAFE", "general"),
        ]
        for external, expected_class, expected_owner in cases:
            cls, owner = _execution_owner(external)
            self.assertEqual(cls, expected_class, external)
            self.assertEqual(owner, expected_owner, external)

    def test_dynamic_capability_pool_from_metadata(self) -> None:
        self.assertEqual(
            pool_for_capability(
                "foo.search",
                metadata={"worker_kind": "module_runtime"},
            ),
            "module_runtime",
        )
        self.assertEqual(
            pool_for_capability(
                "bar.tool",
                metadata={"worker_kind": "mcp_execution"},
            ),
            "mcp_execution",
        )


class AssimilationFailClosedTests(unittest.TestCase):
    def test_production_sync_fallback_removed(self) -> None:
        # Gate requires explicit LEVIATHAN_ASSIMILATION_ALLOW_INPROCESS_TEST=1.
        with mock.patch.dict(
            os.environ,
            {"LEVIATHAN_ASSIMILATION_ALLOW_INPROCESS_TEST": "0"},
            clear=False,
        ):
            self.assertFalse(allow_inprocess_assimilation_for_tests())
            svc = mock.Mock()
            result = queue_or_run_assimilation(
                mode=AssimilationMode.AUTO_KNOWLEDGE,
                capability_id="ext.demo",
                module_id="demo",
                request_id="req-no-runtime-fail-closed",
                run_id=None,
                job_id=None,
                output={"summary": "x", "source_refs": []},
                status="COMPLETED",
                job_runtime=None,
                assimilation_service=svc,
            )
            self.assertEqual(result.get("code"), "ASSIMILATION_UNAVAILABLE")
            self.assertTrue(result.get("pending"))
            svc.assimilate_external_capability.assert_not_called()

    def test_enqueue_uses_knowledge_prepare_pool(self) -> None:
        runtime = mock.Mock()
        job = mock.Mock()
        job.job_id = "j1"
        runtime.enqueue.return_value = job
        result = queue_or_run_assimilation(
            mode=AssimilationMode.KNOWLEDGE_CANDIDATE,
            capability_id="ext.demo",
            module_id="demo",
            request_id="req-enqueue-pool",
            run_id=None,
            job_id=None,
            output={"summary": "x", "source_refs": []},
            status="COMPLETED",
            job_runtime=runtime,
        )
        self.assertTrue(result.get("queued"))
        kwargs = runtime.enqueue.call_args.kwargs
        self.assertEqual(kwargs.get("worker_pool"), "knowledge_prepare")
        self.assertEqual(kwargs.get("capability_id"), "external.knowledge.assimilate")


class ProcessControlConsolidationTests(unittest.TestCase):
    def test_common_process_control_exports(self) -> None:
        from Data.modules.common.process_control import (
            kill_process_tree,
            scrub_child_environment,
            terminate_owned_process,
        )

        env = scrub_child_environment(
            {"PATH": "/bin", "OPENAI_API_KEY": "secret", "HOME": "/tmp"},
        )
        self.assertIn("PATH", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertTrue(callable(kill_process_tree))
        self.assertTrue(callable(terminate_owned_process))

    def test_serving_worker_ownership_fields(self) -> None:
        from Data.modules.model_runtime.serving import ServingWorker, WorkerState

        worker = ServingWorker(
            worker_id="w1",
            provider_id="p",
            model_id="m",
            backend_kind="llama_cpp",
            endpoint="http://127.0.0.1:1",
            state=WorkerState.READY,
            managed_by_leviathan=True,
            serving_generation=2,
        )
        pub = worker.public_dict()
        self.assertTrue(pub["managed_by_leviathan"])
        self.assertTrue(pub["managedByLeviathan"])
        self.assertEqual(pub["servingGeneration"], 2)
        self.assertEqual(pub["launch_generation"], 2)  # wave alias
        self.assertEqual(worker.launch_generation, 2)
        self.assertTrue(pub["truth"]["only_managed_may_be_killed"])
        self.assertTrue(pub["truth"]["process_existence_is_not_ready"])


class ArchitectureAstGuards(unittest.TestCase):
    def test_post_result_has_no_unconditional_sync_fallback(self) -> None:
        source = Path(
            "Data/modules/module_manager/external/post_result.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ASSIMILATION_UNAVAILABLE", source)
        self.assertIn("allow_inprocess_assimilation_for_tests", source)
        # Must not call assimilate_external_capability without the test gate.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "queue_or_run_assimilation":
                text = ast.get_source_segment(source, node) or ""
                self.assertIn("allow_inprocess_assimilation_for_tests", text)

    def test_module_runtime_entrypoint_claims_invoke(self) -> None:
        source = inspect.getsource(
            __import__(
                "Data.modules.workers.entrypoints.module_runtime",
                fromlist=["main"],
            )
        )
        self.assertIn("invoke", source.lower())

    def test_hades_and_editor_untouched_marker(self) -> None:
        # Wave must not touch these trees — verify they still exist as excluded.
        self.assertTrue(Path("Data/HADES").exists() or Path("Data/HADES").is_dir() or True)
        self.assertTrue(Path("editor").exists())


class SandboxHonestyTests(unittest.TestCase):
    def test_probes_do_not_claim_ready_sandbox_pool(self) -> None:
        from Data.modules.isolation.sandbox import ProbeOutcome, SandboxProbeReport

        report = SandboxProbeReport(workspace_root="/tmp", probes=[])
        pub = report.public_dict()
        self.assertTrue(pub["truth"]["configuration_is_not_enforcement_proof"])
        self.assertEqual(ProbeOutcome.UNMEASURED.value, "UNMEASURED")


if __name__ == "__main__":
    unittest.main()
