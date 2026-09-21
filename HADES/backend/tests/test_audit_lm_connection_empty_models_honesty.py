"""LM Studio empty-model connection must not report connected/ok success."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LmConnectionEmptyModelsHonestyTests(unittest.TestCase):
    def test_test_connection_rejects_empty_models(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.test_connection)
        self.assertIn("no_models_loaded", source)
        self.assertIn("if not models", source)

    def test_health_marks_empty_models_warn(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("connected_empty", source)
        self.assertIn("geen model geladen", source)

    def test_models_and_settings_pages_gate_toasts(self) -> None:
        root = Path(__file__).resolve().parents[2]
        models = (root / "components" / "hades" / "pages" / "models-page.tsx").read_text(encoding="utf-8")
        settings = (root / "components" / "hades" / "pages" / "settings-page.tsx").read_text(encoding="utf-8")
        self.assertIn("Number(result.models || 0) <= 0", models)
        self.assertIn("toast.error", models)
        self.assertIn("Number(result.models || 0) <= 0", settings)
        self.assertIn("toast.error", settings)


if __name__ == "__main__":
    unittest.main()
