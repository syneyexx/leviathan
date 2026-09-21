from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from Data.modules.function_runtime import (
    FunctionCallStatus,
    FunctionDefinition,
    FunctionRegistry,
    FunctionRuntime,
    LifecycleMode,
    SideEffect,
    build_default_registry,
)


class FunctionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure cold start for representative modules.
        for name in list(sys.modules):
            if name.startswith("Data.functions."):
                del sys.modules[name]
        self.registry = build_default_registry()
        self.runtime = FunctionRuntime(self.registry, max_concurrency=2, warm_cache_size=1)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def test_builtins_registered_without_importing_implementations(self) -> None:
        self.assertIn("text_file_read", self.registry)
        self.assertIn("csv_inspector", self.registry)
        self.assertIn("pdf_parser", self.registry)
        self.assertNotIn("Data.functions.text_file_read", sys.modules)
        self.assertNotIn("Data.functions.csv_inspector", sys.modules)
        self.assertNotIn("Data.functions.pdf_parser", sys.modules)

    def test_text_file_read_lazy_loads_then_unloads(self) -> None:
        path = self.root / "note.txt"
        path.write_text("hello leviathan", encoding="utf-8")
        self.assertNotIn("Data.functions.text_file_read", sys.modules)

        result = self.runtime.execute("text_file_read", {"path": str(path)})
        self.assertEqual(result.status, FunctionCallStatus.COMPLETED)
        assert result.output is not None
        self.assertIn("hello leviathan", result.output["content"])
        self.assertTrue(result.telemetry.get("lazy_loaded"))

        # ON_DEMAND cleanup must unload implementation module.
        self.assertNotIn("Data.functions.text_file_read", sys.modules)
        self.assertGreaterEqual(self.runtime.telemetry["unloads"], 1)

    def test_csv_inspector(self) -> None:
        path = self.root / "data.csv"
        path.write_text("name,value\na,1\nb,2\n", encoding="utf-8")
        result = self.runtime.execute("csv_inspector", {"path": str(path), "max_rows": 5})
        self.assertEqual(result.status, FunctionCallStatus.COMPLETED)
        assert result.output is not None
        self.assertEqual(result.output["header"], ["name", "value"])
        self.assertEqual(result.output["sample_row_count"], 2)

    def test_validation_rejects_missing_args(self) -> None:
        result = self.runtime.execute("text_file_read", {})
        self.assertEqual(result.status, FunctionCallStatus.REJECTED)
        self.assertIn("Missing required argument", result.error or "")

    def test_pdf_parser_honest_failure_without_pypdf(self) -> None:
        path = self.root / "doc.pdf"
        path.write_bytes(b"%PDF-1.4\n%fake\n")
        result = self.runtime.execute("pdf_parser", {"path": str(path)})
        # Either COMPLETED (if pypdf installed) or FAILED with honest message.
        if result.status == FunctionCallStatus.COMPLETED:
            self.assertIsNotNone(result.output)
        else:
            self.assertEqual(result.status, FunctionCallStatus.FAILED)
            self.assertIn("pypdf", (result.error or "").lower())

    def test_timeout(self) -> None:
        registry = FunctionRegistry()
        registry.register(
            FunctionDefinition(
                id="slow",
                name="Slow",
                version="1.0.0",
                description="timeout probe",
                entrypoint="Data.backend.tests._slow_fn:run",
                input_schema={"type": "object", "required": [], "properties": {}},
                output_schema={"type": "object", "properties": {}},
                lifecycle_mode=LifecycleMode.ON_DEMAND,
                side_effects=(SideEffect.READ,),
                timeout_seconds=0.05,
            )
        )
        # Inline module for slow function
        import types

        mod = types.ModuleType("Data.backend.tests._slow_fn")

        def run() -> dict:
            import time

            time.sleep(1.0)
            return {"ok": True}

        mod.run = run  # type: ignore[attr-defined]
        sys.modules["Data.backend.tests._slow_fn"] = mod

        runtime = FunctionRuntime(registry, max_concurrency=1)
        result = runtime.execute("slow", {})
        self.assertEqual(result.status, FunctionCallStatus.TIMEOUT)
        runtime.shutdown()

    def test_cancel_unknown_call_returns_false(self) -> None:
        self.assertFalse(self.runtime.cancel("missing-call"))


if __name__ == "__main__":
    unittest.main()
