"""Acceptance tests for LEVIATHAN market simulation (causal, multi-agent, brain)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.market_sim import (
    CausalityViolation,
    MarketSimControlPlane,
    MarketSimError,
    SimulationClock,
)
from Data.modules.market_sim.brain_hooks import BrainFacade
from Data.modules.market_sim.causality import SimulationClock as Clock
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.ohlcv import load_ohlcv, validate_ohlcv_file
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar, RunStatus, SourceStatus


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


class _KnowledgeStub:
    def search_lexical(self, query: str, limit: int = 3):
        return [
            {
                "document_id": "doc-1",
                "title": "BTC regime note",
                "content": f"Historical analogy for {query[:40]}",
                "score": 0.8,
            }
        ]


class _MemoryStub:
    def search(self, query: str, *, limit: int = 3):
        return [{"memory_id": "m1", "content": "Past sim lesson: respect risk", "kind": "episodic"}]


class _NeuroStub:
    def assess(self, text: str):
        class A:
            def public_dict(self):
                return {"enabled": True, "signals": [], "advisory": True}

        return A()


class CausalityTests(unittest.TestCase):
    def test_future_read_fails(self) -> None:
        bars = [
            Bar("2024-01-01T00:00:00+00:00", 1, 2, 0.5, 1.5, 10),
            Bar("2024-01-01T01:00:00+00:00", 1.5, 2.5, 1.0, 2.0, 10),
            Bar("2024-01-01T02:00:00+00:00", 2.0, 3.0, 1.5, 2.5, 10),
        ]
        clock = Clock(bars=bars)
        clock.advance()  # index 0
        clock.observe(0)
        with self.assertRaises(CausalityViolation):
            clock.observe(1)
        self.assertEqual(clock.violations, 1)

    def test_window_never_includes_future(self) -> None:
        bars = [
            Bar(f"2024-01-01T{i:02d}:00:00+00:00", float(i), float(i) + 1, float(i) - 1, float(i) + 0.5, 1)
            for i in range(10)
        ]
        clock = Clock(bars=bars)
        for _ in range(5):
            clock.advance()
        window = clock.window(3)
        self.assertEqual(len(window), 3)
        self.assertEqual(window[-1].ts, clock.current_ts)
        self.assertTrue(all(b.ts <= clock.current_ts for b in window))


class MarketSimIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.markets = self.root / "markets"
        self.markets.mkdir(parents=True)
        # Copy fixture into markets root
        dest = self.markets / "BTCUSDT_1h.csv"
        dest.write_bytes(FIXTURE.read_bytes())
        self.db = self.root / "leviathan.db"
        self.store = MarketSimStore(self.db)
        self.store.initialize()
        self.data = MarketDataStore(self.store, self.markets)
        self.brain = BrainFacade(
            knowledge=_KnowledgeStub(),  # type: ignore[arg-type]
            memory=_MemoryStub(),  # type: ignore[arg-type]
            neuro=_NeuroStub(),  # type: ignore[arg-type]
        )
        # Adapt knowledge stub via facade expecting search — wrap
        from Data.modules.market_sim.brain_hooks import adapt_knowledge_store, adapt_memory_store

        self.brain = BrainFacade(
            knowledge=adapt_knowledge_store(_KnowledgeStub()),
            memory=adapt_memory_store(_MemoryStub()),
            neuro=_NeuroStub(),
        )
        self.settings = mock.Mock()
        self.settings.features.market_sim_enabled = True
        self.settings.market_sim.markets_root = self.markets
        self.settings.database_path = self.db
        self.svc = MarketSimControlPlane(
            self.store,
            self.data,
            enabled=True,
            brain=self.brain,
        )
        self.svc.engine.deliberation.brain = self.brain

    def tearDown(self) -> None:
        self.svc.stop_background()
        self.tmp.cleanup()

    def test_feature_flag_off(self) -> None:
        self.svc.enabled = False
        with self.assertRaises(MarketSimError) as ctx:
            self.svc.list_strategies()
        self.assertEqual(ctx.exception.code, "FEATURE_DISABLED")

    def test_validate_and_scan_real_csv(self) -> None:
        validation = validate_ohlcv_file(self.markets / "BTCUSDT_1h.csv")
        self.assertTrue(validation.ok)
        self.assertGreater(validation.bar_count, 100)
        sources = self.svc.scan_market_data()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], SourceStatus.READY.value)
        self.assertEqual(sources[0]["symbol"], "BTCUSDT")

    def test_path_escape_refused(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            self.svc.register_market_data("../outside.csv")
        self.assertEqual(ctx.exception.code, "PATH_ESCAPE")

    def test_strategy_save_load_version_fork(self) -> None:
        created = self.svc.create_strategy(
            name="MA Cross BTC",
            description="Baseline trend",
            parameters={"fast_ma": 8, "slow_ma": 21},
            tags=["btc", "trend"],
        )
        sid = created["strategy"]["strategy_id"]
        detail = self.svc.get_strategy(sid)
        self.assertEqual(detail["strategy"]["name"], "MA Cross BTC")
        self.assertEqual(len(detail["versions"]), 1)
        v2 = self.svc.version_strategy(sid, parameters={"fast_ma": 5, "slow_ma": 20}, changelog="faster")
        self.assertEqual(v2["strategy"]["current_version"], 2)
        fork = self.svc.fork_strategy(sid, name="Forked")
        self.assertNotEqual(fork["strategy"]["strategy_id"], sid)
        self.assertEqual(fork["strategy"]["name"], "Forked")

    def test_deterministic_replay_same_fills(self) -> None:
        sources = self.svc.scan_market_data()
        source_id = sources[0]["source_id"]
        strat = self.svc.create_strategy(name="det", parameters={"fast_ma": 5, "slow_ma": 15})
        sid = strat["strategy"]["strategy_id"]

        def run_once(seed: int) -> list[dict]:
            run = self.svc.create_run(
                source_id=source_id,
                strategy_id=sid,
                seed=seed,
                start_ts="2024-01-01T00:00:00+00:00",
                end_ts="2024-01-05T00:00:00+00:00",
                deliberation_every_n=50,  # mostly single-strategy path
                agents=[],  # no multi-agent for pure determinism of strategy path
            )
            run_id = run["run_id"]
            self.svc.start_run(run_id)
            # Drain until complete
            for _ in range(200):
                self.svc.worker.process_next()
                current = self.svc.get_run(run_id)
                if current["status"] in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                }:
                    break
            live = self.svc.run_live_state(run_id)
            self.assertEqual(live["run"]["causality_violations"], 0)
            self.assertEqual(live["run"]["status"], RunStatus.COMPLETED.value)
            return live["fills"]

        fills_a = run_once(7)
        fills_b = run_once(7)
        self.assertEqual(
            [(f["side"], f["qty"], f["price"], f["bar_index"]) for f in fills_a],
            [(f["side"], f["qty"], f["price"], f["bar_index"]) for f in fills_b],
        )

    def test_multi_agent_deliberation_persists_messages_and_brain(self) -> None:
        sources = self.svc.scan_market_data()
        source_id = sources[0]["source_id"]
        strat = self.svc.create_strategy(
            name="multi",
            brain_dependencies=["knowledge", "memory", "neuro"],
        )
        from Data.modules.market_sim.types import AgentRole, AgentConfig

        agents = [
            AgentConfig(
                agent_id=f"agent-{role.value}",
                role=role.value,
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=strat["strategy"]["current_version"],
                label=role.value.replace("_", " ").title(),
            ).public_dict()
            for role in (AgentRole.TREND, AgentRole.MEAN_REVERSION, AgentRole.RISK_OFFICER)
        ]
        run = self.svc.create_run(
            source_id=source_id,
            strategy_id=strat["strategy"]["strategy_id"],
            start_ts="2024-01-01T00:00:00+00:00",
            end_ts="2024-01-03T12:00:00+00:00",
            deliberation_every_n=1,
            decision_cadence="every_n_bars",
            agents=agents,
            seed=1,
        )
        run_id = run["run_id"]
        self.svc.start_run(run_id)
        for _ in range(300):
            self.svc.worker.process_next()
            current = self.svc.get_run(run_id)
            if current["status"] == RunStatus.COMPLETED.value:
                break
        live = self.svc.run_live_state(run_id, message_limit=500)
        self.assertEqual(live["run"]["status"], RunStatus.COMPLETED.value)
        self.assertEqual(live["run"]["causality_violations"], 0)
        self.assertGreater(len(live["messages"]), 0)
        kinds = {m["kind"] for m in live["messages"]}
        self.assertIn("proposal", kinds)
        self.assertIn("decision", kinds)
        # Brain was exercised
        self.assertGreater(live["run"]["brain_hits"] + live["run"]["brain_misses"], 0)
        self.assertGreater(live["run"]["brain_hits"], 0)
        metrics = live["run"]["metrics"]
        self.assertIn("total_return", metrics)
        self.assertIn("buy_and_hold_return", metrics)
        self.assertEqual(metrics["causality_violations"]["value"], 0)

    def test_step_pause_controls(self) -> None:
        sources = self.svc.scan_market_data()
        strat = self.svc.create_strategy(name="step")
        run = self.svc.create_run(
            source_id=sources[0]["source_id"],
            strategy_id=strat["strategy"]["strategy_id"],
            start_ts="2024-01-01T00:00:00+00:00",
            end_ts="2024-01-10T00:00:00+00:00",
            agents=[],
            deliberation_every_n=100,
        )
        run_id = run["run_id"]
        stepped = self.svc.step_run(run_id)
        self.assertIn(stepped["status"], {RunStatus.PAUSED.value, RunStatus.STEPPING.value, RunStatus.RUNNING.value})
        self.assertGreaterEqual(stepped["bar_index"], 0)
        paused = self.svc.pause_run(run_id) if stepped["status"] != RunStatus.PAUSED.value else stepped
        # Ensure pause sticks
        current = self.svc.get_run(run_id)
        if current["status"] not in {RunStatus.PAUSED.value, RunStatus.COMPLETED.value}:
            self.svc.pause_run(run_id)
            current = self.svc.get_run(run_id)
        self.assertIn(current["status"], {RunStatus.PAUSED.value, RunStatus.COMPLETED.value})


class OhlcvLoaderTests(unittest.TestCase):
    def test_load_fixture(self) -> None:
        bars = load_ohlcv(FIXTURE)
        self.assertGreater(len(bars), 100)
        self.assertTrue(all(bars[i].ts <= bars[i + 1].ts for i in range(len(bars) - 1)))


if __name__ == "__main__":
    unittest.main()
