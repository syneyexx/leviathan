"""P0: Coding Agent must not rewrite unrelated correct files (F01/F02)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_agent import ExploreHit, _heuristic_fix_from_failing_assert, _heuristic_initial_edits


class HeuristicNegativeScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        (self.root / "billing.py").write_text(
            "def subtract(a, b):\n    return a - b\n",
            encoding="utf-8",
        )
        (self.root / "users.py").write_text(
            "def create_user(name):\n    return {'user_name': name}\n",
            encoding="utf-8",
        )
        (self.root / "dates.py").write_text(
            "def parse_date(value):\n    raise ValueError('bad date')\n",
            encoding="utf-8",
        )
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_dates.py").write_text(
            "import unittest\nfrom dates import parse_date\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_parse(self):\n"
            "        self.assertEqual(parse_date('2020-01-01'), '2020-01-01')\n",
            encoding="utf-8",
        )

    def test_unrelated_date_failure_does_not_touch_billing_or_users(self) -> None:
        failing = (
            "FAIL: test_parse (tests.test_dates.T)\n"
            "Traceback (most recent call last):\n"
            '  File "tests/test_dates.py", line 6, in test_parse\n'
            "    self.assertEqual(parse_date('2020-01-01'), '2020-01-01')\n"
            "AssertionError: ValueError('bad date') raised\n"
        )
        edits = _heuristic_fix_from_failing_assert(self.root, failing)
        paths = {e.path for e in edits}
        self.assertNotIn("billing.py", paths)
        self.assertNotIn("users.py", paths)
        billing = (self.root / "billing.py").read_text(encoding="utf-8")
        users = (self.root / "users.py").read_text(encoding="utf-8")
        self.assertIn("return a - b", billing)
        self.assertIn("'user_name': name", users)

    def test_initial_edits_without_real_failure_do_not_rewrite_fixtures(self) -> None:
        (self.root / "codec.py").write_text(
            "import json\ndef dumps(obj):\n    return str(obj)\n",
            encoding="utf-8",
        )
        edits = _heuristic_initial_edits(
            self.root,
            "fix the bug in the project",
            [ExploreHit(path="codec.py", reason="explore", score=1.0)],
        )
        self.assertEqual(edits, [])

    def test_or_true_pattern_removed_from_source(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "coding_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("or True", src)
        self.assertNotIn("synthetic_fail", src)
        self.assertNotIn("E01: dumps", src)
        self.assertNotIn("E08: hidden", src)


if __name__ == "__main__":
    unittest.main()
