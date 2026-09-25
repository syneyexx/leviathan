"""P3A — Trading Orchestra cadence + asynchronous DecisionRecord semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.decision_cadence import (
    AsyncDecisionQueue,
    AsyncDecisionRecord,
    CADENCE_DAILY_CLOSE,
    CADENCE_EVERY_N_BARS,
    CADENCE_OFF,
    should_decide_on_bar,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import AgentConfig, AgentRole


class P3ADecisionCadenceTests(unittest.TestCase):
    def test_every_n_bars_gate(self) -> None:
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_EVERY_N_BARS,
                bar_index=0,
                bar_ts="2024-01-01T00:00:00+00:00",
                every_n=5,
            )
        )
        self.assertTrue(
            should_decide_on_bar(
                cadence=CADENCE_EVERY_N_BARS,
                bar_index=5,
                bar_ts="2024-01-01T05:00:00+00:00",
                every_n=5,
            )
        )
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_OFF,
                bar_index=5,
                bar_ts="2024-01-01T05:00:00+00:00",
                every_n=1,
            )
        )

    def test_daily_close_boundary(self) -> None:
        self.assertTrue(
            should_decide_on_bar(
                cadence=CADENCE_DAILY_CLOSE,
                bar_index=10,
                bar_ts="2024-01-02T00:00:00+00:00",
                previous_decision_ts="2024-01-01T23:00:00+00:00",
            )
        )
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_DAILY_CLOSE,
                bar_index=11,
                bar_ts="2024-01-02T01:00:00+00:00",
                previous_decision_ts="2024-01-02T00:00:00+00:00",
            )
        )

    def test_async_decision_queue_causal(self) -> None:
        q = AsyncDecisionQueue()
        q.enqueue(
            AsyncDecisionRecord(
                decision_id="d1",
                as_of="2024-01-02T00:00:00+00:00",
                payload={"side": "buy"},
            )
        )
        q.enqueue(
            AsyncDecisionRecord(
                decision_id="d2",
                as_of="2024-01-05T00:00:00+00:00",
                payload={"side": "sell"},
            )
        )
        applied = q.apply_eligible(as_of="2024-01-03T00:00:00+00:00")
        self.assertEqual([r.decision_id for r in applied], ["d1"])
        self.assertEqual(len(q._pending), 1)
        self.assertTrue(q.public_dict()["truth"]["causal_as_of"])

    def test_create_run_records_cadence_no_default_agents(self) -> None:
        fixture = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "fixtures" / "BTCUSDT_1h_sample.csv"
        if not fixture.exists():
            # fall back to characterization fixture location
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "BTCUSDT_1h_sample.csv"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            # Use any available CSV from repo fixtures
            from Data.backend.tests.test_market_sim_characterization import FIXTURE

            dest = markets / "BTCUSDT_1h.csv"
            dest.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            run = plane.create_run(source_id=sources[0]["source_id"])
            self.assertEqual(run["agents"], [])
            self.assertEqual(run["metadata"]["decision_cadence"], CADENCE_OFF)

            agents = [
                AgentConfig(
                    agent_id="a-trend",
                    role=AgentRole.TREND.value,
                    label="Trend",
                ).public_dict()
            ]
            run2 = plane.create_run(
                source_id=sources[0]["source_id"],
                agents=agents,
                deliberation_every_n=3,
                decision_cadence="every_n_bars",
            )
            self.assertEqual(len(run2["agents"]), 1)
            self.assertEqual(run2["metadata"]["decision_cadence"], "every_n_bars")
            self.assertEqual(run2["deliberation_every_n"], 3)


class P3AOrchestraExecutorGateTests(unittest.TestCase):
    def test_trading_orchestra_registers_fleet_executor(self) -> None:
        src = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "orchestra" / "service.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("register_kind_executor", text)
        self.assertIn("AgentDefinitionKind.TRADING", text)
        self.assertIn("DecisionRecord", open(
            Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "orchestra" / "types.py",
            encoding="utf-8",
        ).read())


if __name__ == "__main__":
    unittest.main()
