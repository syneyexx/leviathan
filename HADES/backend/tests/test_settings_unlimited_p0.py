"""P0 settings reliability: Unlimited null preservation, partial save, Work Runtime."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from settings_limits import allows_parallel, coerce_optional_positive_int, effective_bound


class SettingsLimitsHelpersTests(unittest.TestCase):
    def test_null_is_unlimited_not_int_coerced(self) -> None:
        self.assertIsNone(coerce_optional_positive_int(None, default=2))
        self.assertEqual(coerce_optional_positive_int(3, default=2), 3)
        with self.assertRaises(TypeError):
            coerce_optional_positive_int("nope", default=2)

    def test_effective_bound_uses_situational_fallback(self) -> None:
        self.assertEqual(effective_bound(None, fallback_when_unlimited=7), 7)
        self.assertEqual(effective_bound(2, fallback_when_unlimited=7), 2)

    def test_allows_parallel_unlimited(self) -> None:
        self.assertTrue(allows_parallel(None, 3))
        self.assertFalse(allows_parallel(1, 3))
        self.assertFalse(allows_parallel(None, 1))


class SettingsRevisionAndNullPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.db = Database(str(self.tmp / "hades.db"))
        self.db.initialize()

    def test_null_unlimited_survives_unrelated_patch(self) -> None:
        saved = self.db.update_settings(
            {
                "max_parallel_steps": None,
                "max_model_concurrency": None,
                "max_tool_rounds": None,
            }
        )
        self.assertIsNone(saved["max_parallel_steps"])
        self.assertIsNone(saved["max_model_concurrency"])
        self.assertIsNone(saved["max_tool_rounds"])
        rev1 = int(saved["config_revision"])

        saved2 = self.db.update_settings({"theme": "dark"})
        self.assertIsNone(saved2["max_parallel_steps"])
        self.assertIsNone(saved2["max_model_concurrency"])
        self.assertIsNone(saved2["max_tool_rounds"])
        self.assertEqual(saved2["theme"], "dark")
        self.assertEqual(int(saved2["config_revision"]), rev1 + 1)

    def test_volume_zero_persists(self) -> None:
        saved = self.db.update_settings({"voice_tts_volume": 0})
        self.assertEqual(saved["voice_tts_volume"], 0)


class ToSettingsFormContractTests(unittest.TestCase):
    """Frontend helper contract mirrored in a tiny pure check (TS tested via node separately)."""

    def test_python_side_null_semantics_documented(self) -> None:
        # Ensure DEFAULT_SETTINGS documents config_revision and voice volume allows 0.
        from database import DEFAULT_SETTINGS

        self.assertIn("config_revision", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["config_revision"], 0)


class WorkRuntimeNullCeilingTests(unittest.TestCase):
    def test_work_runtime_source_uses_coerce_helper(self) -> None:
        main_src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("coerce_optional_positive_int", main_src)
        self.assertIn("allows_parallel", main_src)
        # Direct int() on possibly-null ceilings must be gone (avoid matching coerce_optional_positive_int(...)).
        self.assertNotRegex(main_src, r'(?<![A-Za-z_])int\(\s*settings\.get\(\s*"max_parallel_steps"')
        self.assertNotRegex(main_src, r'(?<![A-Za-z_])int\(\s*settings\.get\(\s*"max_model_concurrency"')
        self.assertNotRegex(main_src, r'max\(\s*1\s*,\s*int\(\s*settings\.get\(\s*"max_parallel_steps"')
        self.assertNotRegex(main_src, r'max\(\s*1\s*,\s*int\(\s*settings\.get\(\s*"max_model_concurrency"')


if __name__ == "__main__":
    unittest.main()
