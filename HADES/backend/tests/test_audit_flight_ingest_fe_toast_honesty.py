"""Flight ingest and knowledge file short-circuit empty-success honesty."""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FlightIngestNoEventsHonestyTests(unittest.TestCase):
    def test_no_events_returns_ok_false(self) -> None:
        from gen2.eval_lab import ingest_flight_recorder_run

        store = MagicMock()
        store.list_run_events.return_value = []
        store.save_eval_run.return_value = {
            "id": "eval-empty",
            "status": "unmeasured",
            "summary": {"reason": "no_events"},
        }
        result = ingest_flight_recorder_run(store, "missing-run")
        self.assertIs(result.get("ok"), False)
        self.assertEqual(result.get("error"), "no_events")
        store.save_eval_run.assert_called_once()


class IngestFileEmptyChunksHonestyTests(unittest.TestCase):
    def test_ready_unchanged_requires_chunks(self) -> None:
        import platform_services_core as core

        source = inspect.getsource(core.KnowledgeService.ingest_file)
        self.assertIn("Stale ready+empty must not short-circuit", source)
        self.assertIn("list_knowledge_chunks", source)


class MissionControlToastHonestyTests(unittest.TestCase):
    def test_mission_control_gates_eval_flight_sandbox_toasts(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "components"
            / "hades"
            / "pages"
            / "mission-control-page.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("Flight ingest mislukt", page)
        self.assertIn("Flight replay mislukt", page)
        self.assertIn('status === "PASS"', page)
        self.assertIn("failed > 0 || (passed <= 0 && passRate <= 0)", page)
        self.assertNotIn('toast.success(String(report.status || "selftest"))', page)
        self.assertNotIn('toast.success("Flight ingest voltooid");\n                  })', page)


if __name__ == "__main__":
    unittest.main()
