"""Trading specialist must not report ok when paper trading is disabled."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TradingSpecialistDisabledHonestyTests(unittest.TestCase):
    def test_source_marks_disabled_as_not_ok(self) -> None:
        import agent_runtimes as runtimes

        source = inspect.getsource(runtimes.run_trading_specialist)
        self.assertIn("paper_trading_disabled", source)
        self.assertIn('ok=False', source)
        self.assertIn('mode="degraded"', source)

    def test_disabled_paper_returns_not_ok(self) -> None:
        import agent_runtimes as runtimes

        paper = MagicMock()
        paper.state.return_value = {"settings": {"enabled": False}}
        deps = SimpleNamespace(paper_trading=paper, trading_bot=None)
        result = runtimes.run_trading_specialist("koop 1 AAPL", deps)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "paper_trading_disabled")
        self.assertEqual(result.mode, "degraded")


if __name__ == "__main__":
    unittest.main()
