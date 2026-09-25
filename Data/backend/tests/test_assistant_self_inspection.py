"""GI2 — system.inspect: honest self-inspection, no invented brain %."""

from __future__ import annotations

import unittest

from Data.modules.cognition.system_inspect import (
    UNMEASURED,
    SystemInspectService,
    bind_system_inspect_service,
    get_system_inspect_service,
)
from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.function_runtime import build_default_registry


class SystemInspectServiceTests(unittest.TestCase):
    def test_capability_registered_inline_safe(self) -> None:
        catalog = build_default_catalog()
        definition = catalog.get("system.inspect")
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.provider_ref, "system_inspect")
        self.assertEqual(definition.execution_class(), "INLINE_SAFE")
        self.assertEqual(
            classify_capability("system.inspect"),
            ExecutionWorkloadClass.INLINE_SAFE,
        )
        registry = build_default_registry()
        self.assertIn("system_inspect", registry)

    def test_unwired_service_marks_fields_unmeasured(self) -> None:
        svc = SystemInspectService()
        snap = svc.inspect(scope="application,brain,telemetry")
        self.assertTrue(snap["truth"]["no_model_generated_values"])
        self.assertTrue(snap["truth"]["never_invents_brain_percentage"])
        sections = snap["sections"]
        self.assertEqual(sections["application"]["version"]["status"], UNMEASURED)
        self.assertIsNone(sections["application"]["version"]["value"])
        self.assertIn("reason", sections["application"]["version"])

    def test_no_invented_brain_percentage(self) -> None:
        """brain_percentage may appear only as explicit UNMEASURED — never a number."""
        svc = SystemInspectService(
            brain_status_provider=lambda: {"status": "ready", "hits": 12},
        )
        snap = svc.inspect(scope="brain")
        brain = snap["sections"]["brain"]
        self.assertEqual(brain["hits"]["value"], 12)
        self.assertEqual(brain["status"]["value"], "ready")
        pct = brain["brain_percentage"]
        self.assertIsNone(pct["value"])
        self.assertEqual(pct["status"], UNMEASURED)
        self.assertIn("not_a_supported_metric", pct["reason"])
        # No numeric percentage invented anywhere in the snapshot.
        self.assertNotRegex(str(snap).lower(), r"brain\s*(is\s*)?\d+(\.\d+)?\s*%")

    def test_real_providers_surface_measured_values(self) -> None:
        svc = SystemInspectService(
            application_version_provider=lambda: "9.9.9-test",
            application_commit_provider=lambda: "abc1234",
            active_model_provider=lambda: "model-a",
            model_role_backend_provider=lambda: {"role": "chat", "backend": "llama_cpp"},
            context_window_provider=lambda: 8192,
            cognition_runtime_provider=lambda: {
                "enabled": True,
                "active_runs": 0,
            },
            behavior_profile_provider=lambda: {
                "id": "default",
                "version": "3",
                "hash": "deadbeef",
            },
            brain_status_provider=lambda: {"status": "ready", "hits": 12},
            knowledge_count_provider=lambda: {"count": 5, "turn_hits": 2},
            telemetry_provider=lambda: {
                "dashboard": {"cpuPct": 11.5, "ramPct": 42.0, "gpuPct": None},
                "cpu": {"utilizationPct": 11.5},
                "memory": {"utilizationPct": 42.0},
                "gpu": {"available": False, "devices": []},
                "notes": [],
            },
            context_budget_provider=lambda: {
                "budget_tokens": 1000,
                "used_tokens": 250,
            },
        )
        snap = svc.inspect()
        sections = snap["sections"]
        self.assertEqual(sections["application"]["version"]["value"], "9.9.9-test")
        self.assertEqual(sections["application"]["version"]["status"], "MEASURED")
        self.assertEqual(sections["application"]["commit"]["value"], "abc1234")
        self.assertEqual(sections["model"]["active_model"]["value"], "model-a")
        self.assertEqual(sections["model"]["model_role"]["value"], "chat")
        self.assertEqual(sections["model"]["model_backend"]["value"], "llama_cpp")
        self.assertEqual(sections["model"]["context_window"]["value"], 8192)
        self.assertEqual(sections["behavior"]["hash"]["value"], "deadbeef")
        self.assertEqual(sections["brain"]["hits"]["value"], 12)
        self.assertIsNone(sections["brain"]["brain_percentage"]["value"])
        self.assertEqual(sections["knowledge"]["count"]["value"], 5)
        self.assertEqual(sections["knowledge"]["turn_hits"]["value"], 2)
        self.assertEqual(sections["telemetry"]["cpu"]["value"], 11.5)
        self.assertEqual(sections["telemetry"]["ram"]["value"], 42.0)
        self.assertEqual(sections["telemetry"]["gpu"]["status"], UNMEASURED)
        self.assertEqual(sections["context"]["context_utilization"]["value"], 0.25)

    def test_provider_exception_is_unmeasured_not_fabricated(self) -> None:
        def boom():
            raise RuntimeError("probe failed")

        svc = SystemInspectService(active_model_provider=boom)
        snap = svc.inspect(scope="model")
        field = snap["sections"]["model"]["active_model"]
        self.assertEqual(field["status"], UNMEASURED)
        self.assertIsNone(field["value"])
        self.assertIn("probe failed", field["reason"])

    def test_scope_filters_sections(self) -> None:
        svc = SystemInspectService(application_version_provider=lambda: "1")
        snap = svc.inspect(scope="application")
        self.assertIn("application", snap["sections"])
        self.assertNotIn("brain", snap["sections"])
        self.assertNotIn("fleet", snap["sections"])

    def test_bind_and_function_entrypoint(self) -> None:
        svc = SystemInspectService(
            application_version_provider=lambda: "bound-v",
            brain_status_provider=lambda: {"status": "ready", "hits": 1},
        )
        bind_system_inspect_service(svc)
        self.assertIs(get_system_inspect_service(), svc)
        from Data.functions.system_inspect import run

        out = run(scope="application,brain")
        self.assertEqual(out["sections"]["application"]["version"]["value"], "bound-v")
        self.assertIsNone(out["sections"]["brain"]["brain_percentage"]["value"])
        bind_system_inspect_service(SystemInspectService())


if __name__ == "__main__":
    unittest.main()
