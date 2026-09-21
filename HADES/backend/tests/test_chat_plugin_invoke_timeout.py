"""Chat autonomous plugin invoke must use Control Plane timeout, not a magic 120."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MAIN_PY = BACKEND / "main.py"
PLATFORM_CORE = BACKEND / "platform_services_core.py"


class ChatPluginInvokeTimeoutTests(unittest.TestCase):
    def test_run_model_invoke_does_not_hardcode_120(self) -> None:
        source = MAIN_PY.read_text(encoding="utf-8")
        # Locate the autonomous Chat _invoke helper inside run_model_with_optional_tool.
        start = source.index("def _invoke(plugin_id: str, tool_name: str, arguments: dict[str, Any])")
        chunk = source[start : start + 1800]
        self.assertIn("plugin_manager.invoke(", chunk)
        self.assertNotRegex(chunk, r"arguments,\s*120\s*,")
        # Must pass None so PluginManager resolves plugins.invoke_timeout_seconds.
        self.assertRegex(chunk, r"arguments,\s*None\s*,")

    def test_plugin_manager_resolves_none_timeout_from_control_plane(self) -> None:
        source = PLATFORM_CORE.read_text(encoding="utf-8")
        self.assertIn("def invoke(", source)
        self.assertIn('plugins.invoke_timeout_seconds', source)
        self.assertIn("if timeout is None:", source)
        # Ensure the default fallback remains documented as 120 only as registry default.
        self.assertTrue(
            re.search(r'_setting\(\s*"plugins\.invoke_timeout_seconds"\s*,\s*120\s*\)', source),
            "PluginManager must resolve invoke timeout via control plane when None",
        )

    def test_main_source_parses(self) -> None:
        ast.parse(MAIN_PY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
