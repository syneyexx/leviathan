"""Adversarial / honesty tests for autonomous trading research closed loop."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from Data.modules.market_sim.chart_perception import (
    ChartObservation,
    chart_observation_schema,
    render_chart_snapshot,
    validate_chart_observation,
)
from Data.modules.market_sim.learning_fitness import (
    derive_expectancy_metrics,
    ranks_by_expectancy_not_win_rate,
)
from Data.modules.market_sim.research_cycle import (
    deduplicate_candidate_specs,
    run_research_generation_cycle,
    _validate_dsl_spec,
)
from Data.modules.market_sim.research_hypothesis import (
    assert_falsification_immutable,
    new_research_hypothesis,
)
from Data.modules.market_sim.research_perception import build_research_perception
from Data.modules.market_sim.trading_live_guard import LiveTradingGuard
from Data.modules.market_sim.types import CausalityViolation, MarketSimError


def _bars(n: int = 30, *, start: datetime | None = None) -> list[dict]:
    dt0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    out: list[dict] = []
    for i in range(n):
        ts = (dt0 + timedelta(hours=i)).isoformat()
        px = 100.0 + i * 0.5
        out.append(
            {
                "ts": ts,
                "open": px,
                "high": px + 1,
                "low": px - 0.5,
                "close": px + 0.3,
                "volume": 100.0,
            }
        )
    return out


class PerceptionCausalityTests(unittest.TestCase):
    def test_a_future_bar_leak_rejected_by_as_of(self) -> None:
        bars = _bars(10)
        as_of = bars[4]["ts"]
        with self.assertRaises(CausalityViolation) as ctx:
            build_research_perception(
                bars=bars,
                as_of=as_of,
                symbol="BTCUSDT",
                timeframe="1h",
            )
        self.assertIn("future bar", str(ctx.exception).lower())


class ChartCausalityTests(unittest.TestCase):
    def test_b_chart_future_leak_rejected(self) -> None:
        bars = _bars(12)
        as_of = bars[5]["ts"]
        with self.assertRaises(CausalityViolation) as ctx:
            render_chart_snapshot(
                bars=bars,
                symbol="BTCUSDT",
                timeframe="1h",
                as_of=as_of,
                start_ts=bars[0]["ts"],
                end_ts=bars[8]["ts"],
            )
        msg = str(ctx.exception).lower()
        self.assertTrue("future" in msg or "exceeds as_of" in msg)


class ChartVisionDegradeTests(unittest.TestCase):
    def test_c_no_chart_model_vision_unavailable_cycle_continues(self) -> None:
        result = run_research_generation_cycle(
            perception_snapshot={
                "regime": "trend",
                "symbols": ["BTCUSDT"],
                "timeframe": "1h",
                "as_of": "2024-01-05T00:00:00+00:00",
                "features": {"trend": "up"},
            },
            objective_text="Search for breakout edge after compression",
            model_complete=None,
            enable_chart_vision=True,
            vision_capability_status="UNAVAILABLE",
            as_of="2024-01-05T00:00:00+00:00",
            now="2024-01-05T00:00:00+00:00",
            lab_id="lab-adv",
        )
        self.assertEqual(result.chart_status, "UNAVAILABLE")
        self.assertIsNotNone(result.hypothesis)
        self.assertGreaterEqual(len(result.author_proposals), 1)
        events = [e.get("type") for e in result.public_events]
        self.assertIn("research_cycle.perception", events)


class DslRejectTests(unittest.TestCase):
    def test_d_malformed_dsl_rejected(self) -> None:
        ok, reason, normalized = _validate_dsl_spec(
            {
                "family": "not_a_real_family",
                "entry_rules": {"version": 3, "kind": "not_a_real_family"},
                "parameters": {},
            }
        )
        self.assertFalse(ok)
        self.assertIsNone(normalized)
        self.assertIn("unsupported family", reason)

    def test_e_arbitrary_python_in_strategy_rejected(self) -> None:
        ok, reason, normalized = _validate_dsl_spec(
            {
                "family": "ma_cross",
                "entry_rules": {
                    "version": 3,
                    "kind": "ma_cross",
                    "eval": "os.system('rm -rf /')",
                    "parameters": {"fast_ma": 5, "slow_ma": 20},
                },
                "exit_rules": {"kind": "ma_cross"},
                "parameters": {"fast_ma": 5, "slow_ma": 20},
            }
        )
        self.assertFalse(ok)
        self.assertIsNone(normalized)
        self.assertIn("arbitrary code", reason.lower())


class ExpectancyHonestyTests(unittest.TestCase):
    def test_f_high_win_rate_negative_expectancy_loses_to_case2(self) -> None:
        # CASE1: high win-rate trap (negative expectancy)
        case1 = {
            "win_rate": 0.9,
            "average_win": 1.0,
            "average_loss": 20.0,
            "trade_count": 100,
            "net_expectancy": -1.1,
            "total_return_pct": -5.0,
            "max_drawdown_pct": 15.0,
        }
        # CASE2: lower win-rate, positive expectancy
        case2 = {
            "win_rate": 0.4,
            "average_win": 5.0,
            "average_loss": 1.0,
            "trade_count": 100,
            "net_expectancy": 1.4,
            "total_return_pct": 12.0,
            "max_drawdown_pct": 8.0,
        }
        e1 = derive_expectancy_metrics(case1)
        self.assertTrue(
            e1["truth"]["high_win_rate_negative_expectancy_is_not_profitable"]
        )
        ranked = ranks_by_expectancy_not_win_rate(case1, case2)
        self.assertEqual(ranked["winner"], "b")
        self.assertTrue(ranked["case_a_is_win_rate_trap"])
        self.assertTrue(ranked["truth"]["win_rate_not_authority"])


class CandidateDedupTests(unittest.TestCase):
    def test_g_duplicate_candidate_dedup(self) -> None:
        spec = {
            "family": "breakout",
            "entry_rules": {
                "version": 3,
                "kind": "breakout",
                "parameters": {"period": 20},
            },
            "exit_rules": {"kind": "breakout"},
            "parameters": {"period": 20},
            "risk_rules": {"max_position_pct": 25},
        }
        ok, _, normalized = _validate_dsl_spec(spec)
        self.assertTrue(ok)
        assert normalized is not None
        ch = normalized["content_hash"]
        novel, dups = deduplicate_candidate_specs(
            [normalized, dict(normalized), dict(normalized)],
            existing_hashes=set(),
        )
        self.assertEqual(len(novel), 1)
        self.assertEqual(len(dups), 2)
        novel2, dups2 = deduplicate_candidate_specs(
            [dict(normalized)],
            existing_hashes={ch},
        )
        self.assertEqual(novel2, [])
        self.assertEqual(len(dups2), 1)
        self.assertEqual(dups2[0].get("reason"), "content_hash_seen")


class LiveGuardTests(unittest.TestCase):
    def test_h_live_order_blocked(self) -> None:
        guard = LiveTradingGuard()
        status = guard.public_status()
        self.assertEqual(status["LIVE_TRADING_AVAILABLE"], "BLOCKED")
        self.assertTrue(status["agent_cannot_enable"])
        with self.assertRaises(MarketSimError) as ctx:
            guard.place_live_order(symbol="BTCUSDT", side="BUY", qty=1)
        self.assertEqual(ctx.exception.code, "LIVE_TRADING_BLOCKED")


class ChartObservationAuthorityTests(unittest.TestCase):
    def test_i_vlm_cannot_place_orders(self) -> None:
        schema = chart_observation_schema()
        props = schema.get("properties") or {}
        order_keys = {
            "order",
            "orders",
            "place_order",
            "order_intent",
            "can_place_orders",
            "order_authority",
            "broker",
            "live_order",
        }
        for key in order_keys:
            self.assertNotIn(key, props)
        self.assertTrue((schema.get("truth") or {}).get("chart_advisory_only"))

        raw = {
            "observation_id": "obs-1",
            "chart_artifact_id": "art-1",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "as_of": "2024-01-05T00:00:00+00:00",
            "visible_window": {
                "start_ts": "2024-01-01T00:00:00+00:00",
                "end_ts": "2024-01-05T00:00:00+00:00",
            },
            "market_structure": "range",
            "trend_visual": "sideways",
            "volatility_visual": "low",
            "compression_expansion": "compression",
            "breakout_or_failed_breakout": "none",
            "support_resistance_candidates": [],
            "volume_pattern": "flat",
            "notable_pattern_candidates": ["triangle"],
            "uncertainty": 0.4,
            "confidence": 0.5,
            "rationale_summary": "Advisory pattern labels only",
            "evidence_refs": ["chart:art-1"],
            "model_id": "vision-test",
            "model_revision": "r0",
            "render_spec_hash": "abc",
            "created_at": "2024-01-05T00:00:00+00:00",
        }
        obs = validate_chart_observation(raw)
        public = obs.public_dict()
        self.assertTrue(public["truth"]["chart_advisory_only"])
        self.assertTrue(public["truth"]["pattern_labels_are_hypotheses"])
        for key in order_keys:
            self.assertNotIn(key, public)
        # ChartObservation has no place_order / order methods
        self.assertFalse(hasattr(ChartObservation, "place_order"))
        self.assertFalse(hasattr(obs, "place_live_order"))


class FalsificationImmutabilityTests(unittest.TestCase):
    def test_j_falsification_criteria_immutable_after_create(self) -> None:
        hyp = new_research_hypothesis(
            statement="Compression breakouts have edge.",
            created_at="2024-01-01T00:00:00+00:00",
            falsification_criteria=[
                "net_expectancy_after_costs <= 0 on validation",
                "max_drawdown exceeds acceptance policy",
            ],
        )
        self.assertTrue(hyp.falsification_frozen)
        with self.assertRaises(ValueError) as ctx:
            assert_falsification_immutable(
                hyp,
                proposed_criteria=["post-hoc loosened threshold"],
            )
        self.assertIn("FALSIFICATION_IMMUTABLE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
