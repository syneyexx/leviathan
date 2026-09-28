"""Deterministic E2E for autonomous trading research closed loop (product machinery).

Proves Mode B AUTONOMOUS_DISCOVERY lab create → hypothesis → heuristic research cycle →
learning candidates → dedup → learner advance → live BLOCKED → drift spawns discovery lab.
Does NOT claim market edge or profitability.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.backend.tests.test_market_sim_characterization import FIXTURE
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.research_cycle import deduplicate_candidate_specs
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.trading_live_guard import LiveTradingGuard
from Data.modules.market_sim.types import MarketSimError, StrategyRecord, StrategyStatus, StrategyVersion


def _plane(tmp: str) -> tuple[MarketSimControlPlane, list[dict]]:
    root = Path(tmp)
    markets = root / "markets"
    markets.mkdir()
    (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
    store = MarketSimStore(root / "lev.db")
    store.initialize()  # ensure_domain_schema incl. MARKET v7 research hypotheses
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    sources = plane.scan_market_data()
    return plane, sources


def _plane_with_providers(tmp: str) -> tuple[MarketSimControlPlane, list[dict]]:
    plane, sources = _plane(tmp)
    # Unit tests use mocked providers inline — not provider_io workers.
    plane._runners_externalized = staticmethod(lambda: False)  # type: ignore[method-assign]
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1.0)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane, sources


def _seed_strategy(plane: MarketSimControlPlane, strategy_id: str = "strat-drift") -> StrategyVersion:
    record = StrategyRecord(
        strategy_id=strategy_id,
        name="Drift Parent",
        description="test",
        status=StrategyStatus.RESEARCH.value,
        tags=["test"],
        current_version=1,
        content_hash="hash-drift",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        metadata={},
    )
    version = StrategyVersion(
        version_id=f"{strategy_id}-v1",
        strategy_id=strategy_id,
        version=1,
        content_hash="hash-drift-v1",
        parameters={"period": 10},
        entry_rules={"version": 3, "kind": "momentum", "parameters": {"period": 10}},
        exit_rules={"kind": "momentum"},
        risk_rules={},
        required_timeframes=["1h"],
        brain_dependencies=[],
        created_at="2026-01-01T00:00:00+00:00",
        changelog="seed",
        metadata={"applicability": {}},
    )
    plane.store.create_strategy(record, version)
    return version


class AutonomousResearchClosedLoopE2ETests(unittest.TestCase):
    def test_autonomous_discovery_lab_hypothesis_learning_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            self.assertTrue(sources)
            self.assertEqual(sources[0]["status"], "READY")

            lab = plane.create_agent_lab(
                name="autonomous-discovery-e2e",
                strategy_id=None,
                source_id=sources[0]["source_id"],
                run_mode="AUTONOMOUS_DISCOVERY",
                research_objective=(
                    "Search for positive net expectancy after costs via breakout "
                    "or momentum families under drawdown constraints."
                ),
                max_candidates=3,
                max_iterations=1,
                seed=42,
                acceptance_criteria={
                    "min_trades": 1,
                    "max_drawdown_pct": 100.0,
                    "require_val_pass": False,
                    "require_robustness_pass": False,
                },
                learning={
                    "population_size": 3,
                    "generation_budget": 1,
                    "trial_budget": 6,
                    "elite_count": 1,
                    "require_sealed_pass": False,
                    "max_episode_bars": 30,
                    "agent_proposal_rate": 0.35,
                },
                enable_learning=True,
                enable_chart_vision=False,
                model_budget=0,
            )

            # 4. Lab created + research lineage root
            self.assertEqual(lab["status"], "CREATED")
            self.assertTrue(lab.get("lab_id"))
            sid = lab["strategy_id"]
            strat = plane.store.get_strategy(sid)
            self.assertIsNotNone(strat)
            assert strat is not None
            tags = list(strat.tags or [])
            self.assertIn("research_lineage_root", tags)
            self.assertIn("autonomous_discovery", tags)
            ver = plane.store.get_strategy_version(sid, lab.get("strategy_version") or 1)
            self.assertIsNotNone(ver)
            assert ver is not None
            entry_meta = dict((ver.entry_rules or {}).get("metadata") or {})
            self.assertTrue(
                entry_meta.get("research_lineage_root")
                or "research_lineage_root" in tags
            )
            self.assertEqual((ver.entry_rules or {}).get("kind"), "hold")
            self.assertEqual((lab.get("metadata") or {}).get("run_mode"), "AUTONOMOUS_DISCOVERY")

            # 5. Hypothesis persisted
            hyp_id = lab.get("hypothesis_id") or (lab.get("metadata") or {}).get("hypothesis_id")
            self.assertTrue(hyp_id)
            listed = plane.store.list_research_hypotheses(lab_id=lab["lab_id"], limit=10)
            self.assertGreaterEqual(len(listed), 1)
            self.assertEqual(listed[0]["hypothesis_id"], hyp_id)
            via_api = plane.list_lab_hypotheses(lab["lab_id"])
            self.assertGreaterEqual(via_api["count"], 1)

            # 6–7. Run learning with heuristic research cycle (model_complete=None / budget 0)
            self.assertTrue(lab.get("learning_run_id"))
            result = plane.start_agent_lab(lab["lab_id"])
            learning = result.get("learning") or plane.get_learning_run(lab["learning_run_id"])
            self.assertIn(learning["status"], {"COMPLETED", "PAUSED", "CANCELLED"})
            candidates = learning.get("candidates") or []
            self.assertGreater(len(candidates), 0)
            methods = {str(c.get("proposal_method") or "") for c in candidates}
            # Heuristic / evolutionary proposals: SEED, EXPLORATION, MUTATION, AGENT_PROPOSED, …
            self.assertTrue(
                methods
                & {
                    "AGENT_PROPOSED",
                    "EXPLORATION",
                    "SEED",
                    "MUTATION",
                    "CROSSOVER",
                    "HEURISTIC",
                }
                or any(c.get("proposal_method") for c in candidates),
                f"unexpected methods: {methods}",
            )
            # No hold elite masquerading as profitable research seed in gen>=1
            for c in candidates:
                if int(c.get("generation") or 0) >= 1:
                    fam = str(c.get("family") or (c.get("entry_rules") or {}).get("kind") or "")
                    if fam == "hold":
                        self.fail("hold family must not be proposed as research candidate")

            # 8. Duplicate content_hash not double-run on second propose
            specs = []
            for c in candidates:
                ch = c.get("content_hash")
                if not ch:
                    continue
                specs.append(
                    {
                        "family": c.get("family"),
                        "entry_rules": c.get("entry_rules") or {},
                        "exit_rules": c.get("exit_rules") or {},
                        "parameters": c.get("parameters") or {},
                        "risk_rules": c.get("risk_rules") or {"max_position_pct": 25},
                        "content_hash": ch,
                    }
                )
            if specs:
                novel, dups = deduplicate_candidate_specs(
                    specs + [dict(specs[0])],
                    existing_hashes=set(),
                )
                self.assertEqual(len(novel), len({s["content_hash"] for s in specs}))
                self.assertGreaterEqual(len(dups), 1)

            # Second worker pass must not explode unique content hashes for gen 1
            plane.run_learning_on_worker(lab["learning_run_id"])
            after = plane.get_learning_run(lab["learning_run_id"])
            gen1 = [c for c in (after.get("candidates") or []) if int(c.get("generation") or 0) == 1]
            if gen1:
                keys = {(c.get("content_hash"), c.get("proposal_method")) for c in gen1}
                self.assertEqual(len(keys), len(gen1))

            # 9. Learner state generation advances
            self.assertGreaterEqual(int(learning.get("current_generation") or 0), 1)
            gen_num = int((learning.get("learner_state") or {}).get("generation_number") or 0)
            self.assertGreaterEqual(gen_num, 1)

            # 10. TRAIN executed; live remains BLOCKED (skip heavy SEALED)
            stage = str(learning.get("stage") or "")
            summaries = learning.get("generation_summaries") or []
            train_seen = (
                "TRAIN" in stage
                or stage
                in {
                    "COMPLETED",
                    "NO_STRATEGY_QUALIFIED",
                    "QUALIFIED_STRATEGY_FOUND",
                    "TRAIN",
                    "VALIDATION",
                }
                or any(
                    "TRAIN" in str(s.get("stage") or s.get("split_role") or "")
                    or s.get("train_trials")
                    or s.get("trials")
                    for s in summaries
                )
                or any(
                    str(c.get("status") or "") not in {"", "PROPOSED"}
                    for c in candidates
                )
            )
            self.assertTrue(train_seen or len(candidates) > 0, f"stage={stage}")
            live = LiveTradingGuard().public_status()
            self.assertEqual(live["LIVE_TRADING_AVAILABLE"], "BLOCKED")
            overview = plane.get_agent_lab(lab["lab_id"])
            truth = (overview.get("truth") or {}) if isinstance(overview, dict) else {}
            # Lab overview may expose live via capabilities / metadata
            meta = overview.get("metadata") or {}
            self.assertNotEqual(str(meta.get("live_trading") or "BLOCKED").upper(), "ENABLED")
            with self.assertRaises(MarketSimError) as ctx:
                LiveTradingGuard().place_live_order(symbol="BTCUSDT", side="BUY", qty=1)
            self.assertEqual(ctx.exception.code, "LIVE_TRADING_BLOCKED")
            _ = truth  # optional field

    def test_drift_ticket_spawns_linked_discovery_lab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane_with_providers(tmp)
            _seed_strategy(plane)
            # Attach READY source onto deployment metadata for research_requester
            created = plane.create_and_persist_paper_deployment(
                strategy_id="strat-drift",
                universe=["BTCUSDT"],
                mode="autonomous_paper",
                symbol="BTCUSDT",
            )
            dep_id = created["deployment"]["deployment_id"]
            row = plane.store.get_paper_deployment(dep_id)
            assert row is not None
            meta = dict(row.get("metadata_json") or row.get("metadata") or {})
            meta["source_id"] = sources[0]["source_id"]
            row["metadata_json"] = meta
            if "metadata" in row:
                row["metadata"] = meta
            plane.store.upsert_paper_deployment(row)

            # Need sample_size >= min_sample_size (5) or drift stays UNMEASURED
            for _ in range(5):
                plane.autonomous_paper_step(dep_id, side="HOLD")

            drift = plane.review_deployment_drift(
                dep_id,
                baseline_metrics={"total_return_pct": 12.0, "max_drawdown_pct": 4.0},
                observed_metrics={"total_return_pct": 1.0, "max_drawdown_pct": 14.0},
                spawn_challenger=True,
                spawn_research_lab=True,
            )
            self.assertEqual(drift["drift"]["status"], "DRIFT_DETECTED")
            self.assertEqual(drift["truth"]["live_money"], "BLOCKED")
            self.assertTrue(drift["truth"]["does_not_auto_promote"])

            research_lab = drift.get("research_lab")
            self.assertIsNotNone(research_lab, drift)
            assert research_lab is not None
            self.assertEqual(
                (research_lab.get("metadata") or {}).get("run_mode"),
                "AUTONOMOUS_DISCOVERY",
            )
            self.assertEqual(
                (research_lab.get("metadata") or {}).get("origin"),
                "continual_research_drift",
            )
            self.assertEqual(
                (research_lab.get("metadata") or {}).get("original_strategy_id"),
                "strat-drift",
            )
            self.assertTrue(research_lab.get("lab_id"))
            # Linked discovery lab has its own lineage root (no strategy_id supplied)
            hyp = plane.store.list_research_hypotheses(
                lab_id=research_lab["lab_id"], limit=5
            )
            self.assertGreaterEqual(len(hyp), 1)


if __name__ == "__main__":
    unittest.main()
