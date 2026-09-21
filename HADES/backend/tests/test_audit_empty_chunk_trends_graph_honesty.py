"""Empty document chunk, MC trends/asof/JIT, workflow metrics, graphrag stdout honesty."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class EmptyChunkTrendsGraphHonestyTests(unittest.TestCase):
    def test_document_chunk_empty_text_not_ok(self) -> None:
        from gen2.compute_fabric import execute_typed_job

        empty = execute_typed_job("document_chunk", {"text": "   ", "target_chars": 80})
        self.assertFalse(empty.get("ok"))
        self.assertEqual(empty.get("error"), "empty_document_text")
        self.assertEqual(empty.get("chunk_count"), 0)

        preprocess = execute_typed_job("document_preprocess", {"text": "", "target_chars": 80})
        self.assertFalse(preprocess.get("ok"))
        self.assertEqual(preprocess.get("error"), "empty_document_text")

    def test_mission_control_trends_asof_jit_gates(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.message("Trends: 0 human ratings")', page)
        self.assertIn('toast.message("As-of: 0 beliefs")', page)
        self.assertIn('toast.message("JIT panel: 0 grants")', page)
        self.assertNotIn('toast.success("Trends geladen")', page)
        self.assertNotIn('toast.success("As-of geladen")', page)
        self.assertNotIn('toast.success("JIT panel geladen")', page)

    def test_workflows_metrics_empty_message(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "workflows-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.message("Geen workflow runs/metrics")', page)
        self.assertNotIn('toast.success("Metrics vernieuwd")', page)

    def test_as_of_beliefs_empty_not_ok(self) -> None:
        from gen2.store import Gen2Store
        from gen2.temporal_graph import as_of_beliefs
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            result = as_of_beliefs(store, entity_id="missing", as_of="2099-01-01T00:00:00Z")
            self.assertFalse(result.get("ok"))
            self.assertEqual(result.get("error"), "no_beliefs")
            self.assertEqual(result.get("count"), 0)

    def test_graphrag_empty_stdout_fails_for_init_index_query(self) -> None:
        path = ROOT / "plugins" / "graphrag" / "hades_bridge.py"
        spec = importlib.util.spec_from_file_location("graphrag_bridge_audit", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for argv in (
            ["hades_bridge.py", "query", "--root", "/tmp", "--query", "q"],
            ["hades_bridge.py", "init", "--root", "/tmp/graphrag-empty"],
            ["hades_bridge.py", "index", "--root", "/tmp/graphrag-empty"],
        ):
            with mock.patch.object(
                mod,
                "run",
                return_value={"command": ["graphrag"], "exit_code": 0, "stdout": "", "stderr": ""},
            ), mock.patch.object(sys, "argv", argv), mock.patch(
                "sys.stdout", new_callable=io.StringIO
            ) as out:
                code = mod.main()
            payload = json.loads(out.getvalue())
            self.assertFalse(payload.get("ok"), argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("empty graphrag", str(payload.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
