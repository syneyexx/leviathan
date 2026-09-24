"""Trading Center expansion tests — multi-wallet, commit-reveal, causality, demos."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim import MarketSimControlPlane, SimulationClock
from Data.modules.market_sim.accounting import WalletBook, money
from Data.modules.market_sim.capabilities import build_market_capabilities
from Data.modules.market_sim.commit_reveal import CommitRevealProtocol, freeze_info_version
from Data.modules.market_sim.execution import NextBarFillModel, make_intent
from Data.modules.market_sim.experiments import (
    StrategyMemoryIndex,
    StrategyMemoryEntry,
    evaluate_acceptance,
    market_features_from_closes,
    strategy_matches_regime,
)
from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits
from Data.modules.market_sim.roles import default_competition_agents
from Data.modules.market_sim.types import Bar, RunStatus
from Data.modules.trading.stub import TradingStub


FIXTURE_CRYPTO = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"
FIXTURE_EQUITY = Path(__file__).resolve().parent / "fixtures" / "market_data" / "AAPL_1d.csv"


def _plane(tmp: Path) -> MarketSimControlPlane:
    class S:
        class features:
            market_sim_enabled = True

        class market_sim:
            markets_root = tmp / "markets"
            bars_per_slice = 50
            default_initial_cash = 100_000.0

        database_path = tmp / "leviathan.db"

    return MarketSimControlPlane.from_settings(S())


class NextBarFillTests(unittest.TestCase):
    def test_decision_not_filled_on_same_close(self) -> None:
        intent = make_intent(
            run_id="r1",
            agent_id="a1",
            wallet_id="w1",
            side="BUY",
            qty=1,
            decision_bar_index=5,
            decision_ts="t5",
            info_version="iv",
        )
        self.assertEqual(intent.eligible_bar_index, 6)
        book = WalletBook()
        w = book.ensure_agent("a1", initial_cash=10_000)
        model = NextBarFillModel(fee_bps=0, slippage_bps=0)
        # Same bar index as decision → rejected by causality guard
        result = model.execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=5
        )
        self.assertFalse(result.filled)
        self.assertIn("not yet eligible", result.detail)
        # Next bar open OK
        intent2 = make_intent(
            run_id="r1", agent_id="a1", wallet_id=w.wallet_id, side="BUY", qty=1,
            decision_bar_index=5, decision_ts="t5", info_version="iv2",
        )
        result2 = model.execute_intent(
            wallet=w, intent=intent2, fill_open=101.0, bar_volume=1e9, fill_bar_index=6
        )
        self.assertTrue(result2.filled)
        self.assertEqual(float(result2.price), 101.0)


class CommitRevealTests(unittest.TestCase):
    def test_no_post_commit_revision(self) -> None:
        proto = CommitRevealProtocol()
        rnd = proto.begin_round(
            run_id="r", bar_index=1, clock_ts="t", closes=[1, 2, 3], now="n"
        )
        proto.commit_decision(
            agent_id="a1", role="trend", side="BUY", qty=1, wallet_id="w",
            sealed_at="n", rationale="x",
        )
        with self.assertRaises(RuntimeError):
            proto.commit_decision(
                agent_id="a1", role="trend", side="SELL", qty=1, wallet_id="w",
                sealed_at="n2", rationale="changed mind",
            )
        proto.seal(sealed_at="n")
        with self.assertRaises(RuntimeError):
            proto.commit_decision(
                agent_id="a2", role="trend", side="BUY", qty=1, wallet_id="w2",
                sealed_at="n3",
            )
        self.assertEqual(rnd.phase, "sealed")

    def test_info_version_stable(self) -> None:
        a = freeze_info_version(run_id="r", bar_index=1, closes=[1.0, 2.0], ts="t")
        b = freeze_info_version(run_id="r", bar_index=1, closes=[1.0, 2.0], ts="t")
        c = freeze_info_version(run_id="r", bar_index=2, closes=[1.0, 2.0], ts="t")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class RiskGuardTests(unittest.TestCase):
    def test_override_keys_blocked(self) -> None:
        guard = RiskGuard(RiskLimits())
        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10000)
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=1,
            decision_bar_index=0, decision_ts="t", info_version="i",
            metadata={"bypass_risk": True, "approved_by_model": True},
        )
        d = guard.evaluate_intent(intent, wallet=w, price=100)
        self.assertFalse(d.allowed)
        self.assertIn("override_attempt_rejected", d.reason)

    def test_kill_switch_blocks_new_exposure(self) -> None:
        guard = RiskGuard(RiskLimits())
        guard.arm_kill_switch("test")
        book = WalletBook()
        w = book.ensure_agent("a", initial_cash=10000)
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=1,
            decision_bar_index=0, decision_ts="t", info_version="i",
        )
        d = guard.evaluate_intent(intent, wallet=w, price=100)
        self.assertFalse(d.allowed)


class MemoryCausalityTests(unittest.TestCase):
    def test_future_memory_not_visible(self) -> None:
        idx = StrategyMemoryIndex()
        idx.add(
            StrategyMemoryEntry(
                memory_id="m1",
                strategy_id="s",
                strategy_version=1,
                features={"trend": "up"},
                applicability={},
                outcome_summary="future knowledge",
                trial_id=None,
                created_at="2024-06-01T00:00:00+00:00",
                available_at="2024-06-01T00:00:00+00:00",
            )
        )
        hits = idx.search(as_of_ts="2024-01-01T00:00:00+00:00", features={"trend": "up"})
        self.assertEqual(hits, [])
        hits2 = idx.search(as_of_ts="2024-07-01T00:00:00+00:00", features={"trend": "up"})
        self.assertEqual(len(hits2), 1)


class RegimeMatchTests(unittest.TestCase):
    def test_no_conditions_means_not_recognized(self) -> None:
        m = strategy_matches_regime({}, market_features_from_closes([1, 2, 3, 4, 5, 6]))
        self.assertFalse(m["matched"])

    def test_explicit_match(self) -> None:
        feats = {"trend": "up", "volatility": "low", "regime": "up_low"}
        m = strategy_matches_regime(
            {"trends": ["up"], "volatilities": ["low"]}, feats
        )
        self.assertTrue(m["matched"])


class CapabilitiesTests(unittest.TestCase):
    def test_options_not_claimed(self) -> None:
        caps = build_market_capabilities(feature_enabled=True, binance_reachable=True)
        by_family = {m["family"]: m for m in caps["markets"]}
        self.assertEqual(by_family["options"]["HISTORICAL_SIM_AVAILABLE"], "NOT_IMPLEMENTED")
        self.assertEqual(by_family["equity"]["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")
        self.assertEqual(by_family["crypto_spot"]["LIVE_TRADING_AVAILABLE"], "BLOCKED")
        self.assertEqual(by_family["equity"]["LIVE_TRADING_AVAILABLE"], "BLOCKED")


class LiveBlockedTests(unittest.TestCase):
    def test_trading_stub_refuses(self) -> None:
        r = TradingStub().place_order(symbol="AAPL", side="BUY", quantity=1)
        self.assertFalse(r.accepted)


class WalletIsolationTests(unittest.TestCase):
    def test_agents_cannot_spend_each_others_cash(self) -> None:
        book = WalletBook()
        a = book.ensure_agent("alpha", initial_cash=1000)
        b = book.ensure_agent("beta", initial_cash=1000)
        a.apply_buy(qty=1, price=100, fee=0, tx_id="t1")
        self.assertEqual(float(a.cash), 900)
        self.assertEqual(float(b.cash), 1000)
        self.assertEqual(float(b.position_qty), 0)


class MultiAgentDemoTests(unittest.TestCase):
    def _run_family(self, family: str) -> dict:
        self.assertTrue(FIXTURE_CRYPTO.exists())
        self.assertTrue(FIXTURE_EQUITY.exists())
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            return plane.run_market_demo(family=family, bars_limit=80)

    def test_crypto_demo_chain(self) -> None:
        result = self._run_family("crypto_spot")
        self.assertEqual(result["family"], "crypto_spot")
        run = result["run"]
        self.assertIn(run["status"], {RunStatus.COMPLETED.value, RunStatus.STOPPED.value, RunStatus.RUNNING.value})
        wallets = result["wallets"] or (run.get("metadata") or {}).get("wallets")
        self.assertIsNotNone(wallets)
        agent_wallets = [w for w in wallets["wallets"] if w["owner_kind"] == "agent"]
        self.assertGreaterEqual(len(agent_wallets), 2)
        # Isolated wallets
        ids = {w["owner_id"] for w in agent_wallets}
        self.assertIn("agent-alpha", ids)
        self.assertIn("agent-beta", ids)
        messages = result["messages"]
        commits = [m for m in messages if m.get("kind") == "commit"]
        self.assertGreaterEqual(len(commits), 2)
        # Causality
        self.assertEqual(run.get("causality_violations", 0), 0)
        # Events show intent → later fill schedule
        events = result["events_sample"]
        intents = [e for e in events if e["kind"] == "order_intent"]
        for intent_ev in intents:
            payload = intent_ev["payload"]
            self.assertEqual(payload["eligible_bar_index"], payload["decision_bar_index"] + 1)

    def test_equity_demo_chain(self) -> None:
        result = self._run_family("equity")
        self.assertEqual(result["family"], "equity")
        wallets = result["wallets"] or (result["run"].get("metadata") or {}).get("wallets")
        agent_wallets = [w for w in wallets["wallets"] if w["owner_kind"] == "agent"]
        self.assertGreaterEqual(len(agent_wallets), 2)
        commits = [m for m in result["messages"] if m.get("kind") == "commit"]
        self.assertGreaterEqual(len(commits), 1)
        caps = result["capabilities"]
        equity = next(m for m in caps["markets"] if m["family"] == "equity")
        self.assertEqual(equity["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")
        self.assertEqual(equity["LIVE_TRADING_AVAILABLE"], "BLOCKED")

    def test_two_agents_independent_orders_and_strategy_recall(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            demo = plane.run_market_demo(family="crypto_spot", bars_limit=60)
            run_id = demo["run"]["run_id"]
            fills = demo["fills"]
            agents_with_fills = {f["agent_id"] for f in fills if f.get("agent_id")}
            # Not required that both filled, but wallets remain separate regardless
            wallets = demo["wallets"]["wallets"]
            alpha = next(w for w in wallets if w["owner_id"] == "agent-alpha")
            beta = next(w for w in wallets if w["owner_id"] == "agent-beta")
            self.assertNotEqual(alpha["wallet_id"], beta["wallet_id"])

            # Learning cycle: propose experiment, complete reject/pass, memory causal
            source_id = demo["source"]["source_id"]
            strategy_id = demo["strategy"]["strategy"]["strategy_id"]
            trial = plane.propose_experiment(
                strategy_id=strategy_id,
                hypothesis="fast MA wins on this fixture",
                proposer_agent_id="agent-beta",
                source_id=source_id,
                acceptance_criteria={"min_trades": 1000},  # force reject
            )
            done = plane.complete_experiment(
                trial["trial_id"],
                metrics={"trade_count": 2, "total_return_pct": {"value": 1.0, "status": "MEASURED"},
                         "max_drawdown_pct": {"value": 5.0, "status": "MEASURED"}},
            )
            self.assertEqual(done["status"], "rejected")
            mems = plane.store.list_strategy_memories(strategy_id=strategy_id)
            self.assertGreaterEqual(len(mems), 1)
            self.assertTrue(mems[0]["rejected"])

            # Paper session (local) — may lack live quote offline; still creates session
            session = plane.start_paper_session(
                symbol="BTCUSDT",
                strategy_id=strategy_id,
                broker_id="local_paper",
                provider_id="csv_local",
            )
            self.assertEqual(session["metadata"]["mode"], "live_paper")
            self.assertTrue(session["metadata"]["truth"]["not_live_money"])
            # Kill switch
            killed = plane.paper_kill_switch(session["session_id"], armed=True)
            self.assertTrue(killed["kill_switch"])
            live = plane.live_guard.public_status()
            self.assertEqual(live["LIVE_TRADING_AVAILABLE"], "BLOCKED")
            _ = run_id, agents_with_fills


class PaperIdempotencyTests(unittest.TestCase):
    def test_local_paper_idempotent_client_id(self) -> None:
        from Data.modules.market_sim.paper_broker import LocalPaperBroker

        broker = LocalPaperBroker(fee_bps=0, slippage_bps=0)
        o1 = broker.place(symbol="AAPL", side="BUY", qty=1, client_order_id="cid-1", price_hint=10)
        o2 = broker.place(symbol="AAPL", side="BUY", qty=1, client_order_id="cid-1", price_hint=10)
        self.assertEqual(o1.order_id, o2.order_id)
        self.assertEqual(len(broker.wallet.transactions), 1)


class AcceptanceHelperTests(unittest.TestCase):
    def test_small_sample_rejected(self) -> None:
        ok, reason = evaluate_acceptance(
            {"trade_count": 1, "total_return_pct": 50, "max_drawdown_pct": 1},
            {"min_trades": 5},
        )
        self.assertFalse(ok)
        self.assertIn("insufficient trades", reason)


if __name__ == "__main__":
    unittest.main()
