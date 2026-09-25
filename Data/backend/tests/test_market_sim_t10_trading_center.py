"""T10 — Trading Center UI: run builder, real data, action matrix, typed contracts."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
SIM_PAGE = FRONTEND / "pages" / "trading" / "SimulatiePage.tsx"
ACTION_MATRIX = FRONTEND / "pages" / "trading" / "actionMatrix.ts"
CLIENT = FRONTEND / "api" / "client.ts"


class RunBuilderUiTests(unittest.TestCase):
    def test_simulatie_exposes_run_builder_options(self) -> None:
        text = SIM_PAGE.read_text(encoding="utf-8")
        self.assertIn("initialCash", text)
        self.assertIn("engine", text)
        self.assertNotIn("agent-alpha", text)
        self.assertNotIn("agent-beta", text)
        self.assertNotIn("agent-risk", text)
        self.assertNotIn("agent-orch", text)

    def test_create_run_uses_backend_multi_agent_presets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            # Minimal READY source via control plane helpers if fixtures exist.
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, markets)
            svc = MarketSimControlPlane(store, data, enabled=True)
            opts = svc.run_builder_options()
            self.assertTrue(opts["truth"]["agents_from_backend_presets"])
            engines = {e["id"] for e in opts["engines"]}
            self.assertIn("multi_agent", engines)
            self.assertIn("single", engines)
            multi = next(e for e in opts["engines"] if e["id"] == "multi_agent")
            agents = multi["default_agents"]
            self.assertTrue(any(a["agent_id"] == "agent-alpha" for a in agents))


class LiveSeriesRecentTailTests(unittest.TestCase):
    def test_store_list_fills_uses_recent_tail(self) -> None:
        fill_src = inspect.getsource(MarketSimStore.list_fills)
        self.assertIn("ORDER BY bar_index DESC", fill_src)
        self.assertIn("LIMIT ?", fill_src)
        eq_src = inspect.getsource(MarketSimStore.list_equity)
        self.assertIn("ORDER BY bar_index DESC", eq_src)

    def test_live_state_truth_marks_recent_tail(self) -> None:
        src = inspect.getsource(MarketSimControlPlane.run_live_state)
        self.assertIn("live_series_recent_tail", src)
        self.assertIn("fill_limit", src)


class ActionMatrixTests(unittest.TestCase):
    def test_action_matrix_file_complete(self) -> None:
        text = ACTION_MATRIX.read_text(encoding="utf-8")
        for needed in (
            "sim.runs.create",
            "paper.sessions.create",
            "paper.forward.start",
            "risk.status",
            "security.posture",
            "TRADING_ACTION_MATRIX",
        ):
            self.assertIn(needed, text)

    def test_matrix_api_methods_exist_on_client(self) -> None:
        matrix = ACTION_MATRIX.read_text(encoding="utf-8")
        client = CLIENT.read_text(encoding="utf-8")
        # Extract apiMethod: "name" occurrences
        import re

        methods = re.findall(r'apiMethod:\s*"([A-Za-z0-9_]+)"', matrix)
        self.assertGreaterEqual(len(methods), 20)
        for name in methods:
            self.assertIn(f"{name}(", client, msg=f"missing api.{name}")


class TypedContractTests(unittest.TestCase):
    def test_client_exposes_t9_t10_typed_methods(self) -> None:
        client = CLIENT.read_text(encoding="utf-8")
        for name in (
            "marketSimRunBuilder",
            "startPaperForward",
            "paperForwardTick",
            "marketSimRiskStatus",
            "marketSimAuditVerify",
            "marketSimSecurityPosture",
            "engine?:",
            "initialCash?:",
        ):
            self.assertIn(name, client)


if __name__ == "__main__":
    unittest.main()
