"""Neural subsystem disabled / optional-dependency contracts.

These tests must pass without requiring a successful neural forward pass when
torch is absent. With torch present they still verify OFF bypass semantics.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class NeuralRuntimeDisabledTests(unittest.TestCase):
    def test_neural_package_imports_without_loading_memory_module(self) -> None:
        # Importing the package surface must not force torch-backed memory.
        import neural

        self.assertTrue(hasattr(neural, "NeuralMode"))
        self.assertTrue(hasattr(neural, "neural_available"))
        self.assertEqual(neural.NeuralMode.OFF.value, "off")

    def test_deps_reports_unavailable_when_torch_missing(self) -> None:
        from neural import deps
        from neural.errors import NeuralDependencyUnavailable

        with mock.patch.object(deps, "neural_available", return_value=False):
            self.assertFalse(deps.neural_available())
            with self.assertRaises(NeuralDependencyUnavailable) as ctx:
                deps.require_torch()
            self.assertEqual(ctx.exception.code, "neural_dependency_unavailable")

    def test_main_does_not_import_neural(self) -> None:
        # Guardrail: production entry must not pull neural package into import graph.
        # reasoning.neural_settings is allowed (lazy, no torch at import).
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertNotIn("import neural\n", text)
        self.assertNotIn("import neural.", text)
        self.assertNotIn("from neural ", text)
        self.assertNotIn("from neural.", text)

    def test_off_mode_bypasses_forward(self) -> None:
        from neural import neural_available

        if not neural_available():
            self.skipTest("torch unavailable")
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.memory import NeuralMemory

        memory = NeuralMemory(NeuralMemoryConfig(dim=16, hidden_dim=32, mode=NeuralMode.OFF, seed=1))
        torch = __import__("torch")
        key = torch.randn(16)
        result = memory.read(key)
        self.assertIsNone(result.value)
        self.assertTrue(result.diagnostics.get("bypassed"))
        write = memory.write(key, key)
        self.assertFalse(write.accepted)
        self.assertEqual(write.reason, "mode_off")
        self.assertEqual(memory.metrics().read_count, 0)
        self.assertEqual(memory.metrics().write_count, 0)


if __name__ == "__main__":
    unittest.main()
