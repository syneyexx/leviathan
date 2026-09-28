"""Autonomous paper A3/A4 closed loop — durable deployments, receipts, drift, challenger.

Proves:
- PaperDeployment persisted in MARKET DB
- Shadow observations without orders
- A3/A4 promotion requires resolved IDs (rejects caller booleans)
- Autonomous paper steps with RiskGuard
- Drift → PAPER_OBSERVED memory + challenger spawn
- Live money remains BLOCKED
- No-false-win / insufficient evidence paths
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.autonomous_paper_loop import (
    autonomous_paper_evidence_receipt,
    shadow_evidence_receipt,
)
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.readiness import may_promote_to
from Data.modules.market_sim.sample_adequacy import assess_sample_adequacy, gate_qualification_on_sample
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.strategy_dsl import parse_strategy_spec, validate_strategy_spec
from Data.modules.market_sim.types import StrategyRecord, StrategyStatus, StrategyVersion
from Data.modules.market_sim.exchange_calendars import european_equity_venues, get_venue
from Data.modules.market_sim.paper_family_semantics import fx_convert, refuse_continuous_as_paper
from Data.modules.market_sim.types import MarketSimError


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir()
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    # Unit tests use mocked providers inline — not provider_io workers.
    plane._runners_externalized = staticmethod(lambda: False)  # type: ignore[method-assign]
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1.0)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane


def _seed_strategy(plane: MarketSimControlPlane, strategy_id: str = "strat-a4") -> StrategyVersion:
    record = StrategyRecord(
        strategy_id=strategy_id,
        name="A4 Test Strategy",
        description="test",
        status=StrategyStatus.RESEARCH.value,
        tags=["test"],
        current_version=1,
        content_hash="hash-a4",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        metadata={},
    )
    version = StrategyVersion(
        version_id=f"{strategy_id}-v1",
        strategy_id=strategy_id,
        version=1,
        content_hash="hash-a4-v1",
        parameters={"period": 10},
        entry_rules={"version": 3, "kind": "momentum", "parameters": {"period": 10}},
        exit_rules={"kind": "momentum"},
        risk_rules={},
        required_timeframes=["1D"],
        brain_dependencies=[],
        created_at="2026-01-01T00:00:00+00:00",
        changelog="seed",
        metadata={"applicability": {}},
    )
    plane.store.create_strategy(record, version)
    return version


class AutonomousPaperLoopTests(unittest.TestCase):
    def test_paper_deployment_persisted_and_shadow_observe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            _seed_strategy(plane)
            created = plane.create_and_persist_paper_deployment(
                strategy_id="strat-a4",
                universe=["BTCUSDT"],
                feed_id="binance_public",
                mode="shadow",
                symbol="BTCUSDT",
            )
            self.assertTrue(created["truth"]["persisted"])
            dep_id = created["deployment"]["deployment_id"]
            loaded = plane.get_paper_deployment(dep_id)
            self.assertEqual(loaded["deployment_id"], dep_id)
            self.assertEqual(loaded["mode"], "shadow")
            self.assertEqual(
                plane.resume_paper_sessions_for_strategy("strat-a4")["truth"]["paper_deployment_table"],
                "PERSISTED",
            )
            for _ in range(5):
                obs = plane.shadow_observe_step(dep_id, signal_side="BUY", proposed_qty=1.0, risk_decision="ALLOW")
                self.assertTrue(obs["truth"]["no_paper_order"])
            # Shadow must refuse orders
            from Data.modules.market_sim.autonomous_paper_loop import assert_deployment_ready_for_orders
            from Data.modules.market_sim.paper_deployment import create_paper_deployment
            from Data.modules.market_sim.strategy_asset import from_strategy_record

            asset = from_strategy_record(
                plane.store.get_strategy("strat-a4"),
                version=plane.store.get_strategy_version("strat-a4", 1),
            )
            asset.status = StrategyStatus.RESEARCH.value
            deployment = create_paper_deployment(
                asset=asset,
                universe=["BTCUSDT"],
                feed_id="binance_public",
                available_timeframes={"1D"},
            )
            deployment.metadata["mode"] = "shadow"
            with self.assertRaises(MarketSimError) as ctx:
                assert_deployment_ready_for_orders(deployment)
            self.assertEqual(ctx.exception.code, "SHADOW_NO_ORDERS")

    def test_a3_a4_reject_caller_booleans_require_receipts(self) -> None:
        gate = may_promote_to(
            current="A2",
            target="A3",
            evidence={"paper_shadow_pass": True, "accepted": True},
        )
        self.assertFalse(gate["allowed"])
        self.assertIn("A3_requires_resolved_shadow_run_id", gate.get("missing") or [])

        gate4 = may_promote_to(
            current="A3",
            target="A4",
            evidence={"autonomous_paper_pass": True, "shadow_run_id": "shadow-1"},
        )
        self.assertFalse(gate4["allowed"])
        self.assertIn("A4_requires_resolved_paper_deployment_id", gate4.get("missing") or [])

        insuff = shadow_evidence_receipt(shadow_run_id="s1", observations=[{"observation_id": "o1"}])
        self.assertEqual(insuff["status"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(insuff["paper_shadow_pass"])

    def test_full_shadow_to_autonomous_paper_to_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            _seed_strategy(plane)
            shadow = plane.create_and_persist_paper_deployment(
                strategy_id="strat-a4",
                universe=["BTCUSDT"],
                mode="shadow",
                symbol="BTCUSDT",
                qualification_refs={"sealed_attempt_id": "sealed-1"},
            )
            dep_id = shadow["deployment"]["deployment_id"]
            for i in range(5):
                plane.shadow_observe_step(
                    dep_id,
                    signal_side="BUY" if i % 2 == 0 else "HOLD",
                    proposed_qty=1.0,
                    risk_decision="ALLOW",
                )
            promo_a3 = plane.promote_deployment_autonomy(
                dep_id,
                target_level="A3",
                sealed_attempt_id="sealed-1",
                min_shadow_observations=5,
            )
            self.assertTrue(promo_a3.get("promotable"), promo_a3)

            paper = plane.create_and_persist_paper_deployment(
                strategy_id="strat-a4",
                universe=["BTCUSDT"],
                mode="autonomous_paper",
                symbol="BTCUSDT",
                qualification_refs={"shadow_run_id": shadow["session"]["session_id"]},
            )
            paper_dep = paper["deployment"]["deployment_id"]
            # Attach shadow session id onto paper loop for A4 gate when jumping
            row = plane.store.get_paper_deployment(paper_dep)
            loop = dict(row.get("loop_state_json") or {})
            loop["shadow_session_id"] = shadow["session"]["session_id"]
            loop["shadow_observations"] = list(
                (plane.store.get_paper_deployment(dep_id).get("loop_state_json") or {}).get(
                    "shadow_observations"
                )
                or []
            )
            loop["autonomy_level"] = "A3"
            row["loop_state_json"] = loop
            plane.store.upsert_paper_deployment(row)

            for _ in range(5):
                stepped = plane.autonomous_paper_step(paper_dep, side="HOLD")
                self.assertIn("receipt", stepped)

            promo_a4 = plane.promote_deployment_autonomy(
                paper_dep,
                target_level="A4",
                sealed_attempt_id="sealed-1",
                min_shadow_observations=5,
                min_paper_steps=5,
            )
            self.assertTrue(promo_a4.get("promotable"), promo_a4)
            self.assertEqual(promo_a4["loop"]["autonomy_level"], "A4")

            drift = plane.review_deployment_drift(
                paper_dep,
                baseline_metrics={"total_return_pct": 10.0, "max_drawdown_pct": 5.0},
                observed_metrics={"total_return_pct": 1.0, "max_drawdown_pct": 12.0},
                spawn_challenger=True,
            )
            self.assertEqual(drift["drift"]["status"], "DRIFT_DETECTED")
            self.assertIsNotNone(drift["challenger"])
            self.assertTrue(drift["truth"]["does_not_auto_promote"])

    def test_kill_switch_blocks_autonomous_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            _seed_strategy(plane)
            paper = plane.create_and_persist_paper_deployment(
                strategy_id="strat-a4",
                mode="autonomous_paper",
                symbol="BTCUSDT",
            )
            dep_id = paper["deployment"]["deployment_id"]
            plane.paper_deployment_kill_switch(dep_id, armed=True, reason="test")
            with self.assertRaises(MarketSimError) as ctx:
                plane.autonomous_paper_step(dep_id, side="BUY", qty=1)
            self.assertEqual(ctx.exception.code, "KILL_SWITCH")

    def test_sample_adequacy_rejects_tiny_samples(self) -> None:
        result = assess_sample_adequacy(metrics={"trade_count": 5, "calendar_days": 10})
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(result["adequate"])
        gated = gate_qualification_on_sample(
            metrics={"trade_count": 5, "calendar_days": 10},
            acceptance_passed=True,
        )
        self.assertFalse(gated["passed"])
        self.assertEqual(gated["reason"], "INSUFFICIENT_EVIDENCE")

    def test_dsl_new_primitives_validate(self) -> None:
        for kind in ("momentum", "volatility", "relative_strength", "pairs_spread"):
            spec = parse_strategy_spec({"version": 3, "kind": kind, "parameters": {"period": 14}})
            ok, reason = validate_strategy_spec(spec)
            self.assertTrue(ok, f"{kind}: {reason}")

    def test_european_venues_explicit(self) -> None:
        mics = european_equity_venues()
        for mic in ("XAMS", "XETR", "XLON", "XPAR", "XMIL"):
            self.assertIn(mic, mics)
            v = get_venue(mic)
            self.assertEqual(v.region, "EU")
            self.assertNotEqual(v.timezone, "America/New_York")

    def test_fx_missing_rate_not_one(self) -> None:
        out = fx_convert(amount=100, rate=None)
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertIsNone(out["converted"])
        self.assertTrue(out["truth"]["missing_fx_rate_is_not_1"])

    def test_continuous_futures_refused_for_paper(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            refuse_continuous_as_paper("ES_CONT")
        self.assertEqual(ctx.exception.code, "CONTINUOUS_NOT_PAPER_CONTRACT")

    def test_autonomous_paper_evidence_receipt_hash(self) -> None:
        steps = [{"step_id": f"s{i}", "allowed": True} for i in range(5)]
        receipt = autonomous_paper_evidence_receipt(
            paper_deployment_id="dep-1",
            paper_session_id="sess-1",
            step_receipts=steps,
        )
        self.assertEqual(receipt["status"], "MEASURED")
        self.assertTrue(receipt["autonomous_paper_pass"])
        self.assertIn("receipt_hash", receipt)


class CapabilityModeMatrixTests(unittest.TestCase):
    def test_mode_matrix_present_and_live_blocked(self) -> None:
        from Data.modules.market_sim.capabilities import build_market_capabilities

        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        self.assertIn("mode_matrix", caps)
        self.assertTrue(caps["truth"]["mode_matrix_machine_derived"])
        equity = next(r for r in caps["mode_matrix"] if r["family"] == "equity")
        self.assertEqual(equity["modes"]["AUTONOMOUS_PAPER"], "AVAILABLE")
        self.assertEqual(equity["live_trading"], "BLOCKED")
        options = next(r for r in caps["mode_matrix"] if r["family"] == "options")
        self.assertEqual(options["modes"]["AUTONOMOUS_PAPER"], "NOT_IMPLEMENTED")
        actions = {a["action"] for a in caps["action_matrix"]["actions"]}
        self.assertIn("deploy_shadow_paper", actions)
        self.assertIn("autonomous_paper_step", actions)
        self.assertIn("paper_drift_review", actions)


if __name__ == "__main__":
    unittest.main()
