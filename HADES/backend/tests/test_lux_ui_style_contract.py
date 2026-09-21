"""Lux Atelier is the default UI shell; FINALBETA is an optional Phase 1 variant."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import DEFAULT_SETTINGS

ROOT = Path(__file__).resolve().parents[1]


class LuxUiStyleContractTests(unittest.TestCase):
    def test_default_settings_use_lux(self) -> None:
        self.assertEqual(DEFAULT_SETTINGS.get("ui_style"), "lux")

    def test_settings_input_literal_includes_lux_finalbeta_and_legacy(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('Literal["lux", "finalbeta", "classic", "obsidian", "beta", "beta2"]', source)
        self.assertIn(
            'ui_style: Literal["lux", "finalbeta", "classic", "obsidian", "beta", "beta2"] = "lux"',
            source,
        )

    def test_control_registry_default_is_lux(self) -> None:
        source = (ROOT / "control" / "definitions.py").read_text(encoding="utf-8")
        self.assertIn('"lux"', source)
        self.assertIn('"finalbeta"', source)
        self.assertIn('["lux", "finalbeta", "classic", "obsidian", "beta", "beta2"]', source)
        tree = ast.parse(source)
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("create_default_registry", names)


if __name__ == "__main__":
    unittest.main()
