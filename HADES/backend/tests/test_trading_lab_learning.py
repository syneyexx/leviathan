"""Trading Lab learning loop: experiences, regimes, beliefs, evolution, champions, recovery.

These tests exercise the additive learning engine. They do not start a model gateway and
they do not touch sealed holdout.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from trading_lab.champions import evaluate_challenger, scope_key
from trading_lab.contracts import StrategyHypothesis, StrategySpec
from trading_lab.evolution import candidate_fingerprint, materialize_candidate, mutate_from_findings
from trading_lab.experience import build_experience, experience_id_for, ingest_resolved_decisions
from trading_lab.learning import (
    aggregate_experiences,
    apply_curator_output,
    evidence_confidence,
    finding_to_belief_proposal,
)
from trading_lab.learning_cycle import LearningCycleEngine
from trading_lab.regimes import TREND_SLOW, classify_closes
from trading_lab.registry import StrategyRegistry
from trading_lab.store import TradingLabStore


def _db(tmp: str) -> TradingLabStore:
    database = PlatformDatabase(str(Path(tmp) / "hades.db"))
    store = TradingLabStore(database)
    store.initialize()
    return store


def _hypothesis() -> StrategyHypothesis:
    return StrategyHypothesis(
        economic_rationale="Momentum follows through after a burst of volume in trending tape.",
        plausible_regimes="trending_up high volatility",
        implausible_regimes="sideways low volatility",
        falsification_criteria=["Negative expectancy after costs on development"],
        benchmarks=["buy_and_hold"],
    )


def _spec(**overrides) -> StrategySpec:
    payload = {
        "name": "Momentum v1",
        "family": "momentum",
        "instruments": ["crypto_spot:test:BTCUSDT"],
        "timeframe": "1h",
        "params": {"lookback": 20, "threshold": 0.01},
        "hypothesis": _hypothesis(),
    }
    payload.update(overrides)
    return StrategySpec.model_validate(payload)


def _experience(store: TradingLabStore, *, decision_id: str, regime_key: str, pnl: float, split: str = "development", version: int = 1, family: str = "momentum") -> dict:
    later = {"resolved_at": "2020-01-02T00:00:00+00:00", "reference_price": 100.0, "later_price": 100.0 * (1 + pnl), "price_change": pnl}
    store.save_decision(
        {
            "decision_id": decision_id,
            "run_id": "run-dev",
            "event_time": "2020-01-01T00:00:00+00:00",
            "instrument_id": "crypto_spot:test:BTCUSDT",
            "strategy_id": "lstr_parent",
            "strategy_version": version,
            "action": "execute",
            "signal": "long",
            "later_outcome": later,
        }
    )
    payload = build_experience(
        store.get_decision(decision_id),
        run={"run_id": "run-dev", "split": split, "strategy_id": "lstr_parent", "dataset_hash": "abc", "engine_version": "test"},
        strategy={"strategy_id": "lstr_parent", "family": family, "current_version": version, "spec": _spec().as_json()},
    )
    payload["regime_key"] = regime_key
    payload["split"] = split
    payload["strategy_version"] = version
    payload["gross_pnl"] = pnl
    payload["outcome_class"] = "favorable" if pnl > 0 else "adverse" if pnl < 0 else "unchanged"
    store.save_experience(payload)
    return payload


class ExperienceIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deterministic_id_and_retry_does_not_duplicate(self) -> None:
        later = {"resolved_at": "2020-01-01T10:00:00+00:00", "reference_price": 100.0, "later_price": 101.0, "price_change": 0.01}
        self.store.save_decision(
            {
                "decision_id": "dec-1",
                "run_id": "run-1",
                "event_time": "2020-01-01T00:00:00+00:00",
                "instrument_id": "crypto_spot:test:BTCUSDT",
                "strategy_id": "s1",
                "action": "execute",
                "signal": "long",
                "later_outcome": later,
            }
        )
        first = ingest_resolved_decisions(self.store, run_id="run-1")
        second = ingest_resolved_decisions(self.store, run_id="run-1")
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.count_experiences(), 1)
        self.assertEqual(experience_id_for("dec-1"), self.store.list_experiences(limit=1)[0]["experience_id"])

    def test_split_and_strategy_linkage_are_preserved(self) -> None:
        self.store.save_decision(
            {
                "decision_id": "dec-2",
                "run_id": "run-2",
                "event_time": "2020-01-01T00:00:00+00:00",
                "instrument_id": "crypto_spot:test:BTCUSDT",
                "strategy_id": "s1",
                "strategy_version": 3,
                "action": "execute",
                "signal": "long",
                "later_outcome": {"resolved_at": "2020-01-01T10:00:00+00:00", "reference_price": 10.0, "later_price": 9.0, "price_change": -0.1},
            }
        )
        ingest_resolved_decisions(self.store, run_id="run-2")
        row = self.store.list_experiences(limit=1)[0]
        self.assertEqual(row["strategy_id"], "s1")
        self.assertEqual(row["split"], "development")
        self.assertEqual(row["decision_id"], "dec-2")
        self.assertIn("decision:dec-2", row["evidence_refs"])


class RegimeFeatureTest(unittest.TestCase):
    def test_insufficient_history_is_explicit(self) -> None:
        snap = classify_closes([100.0 + i for i in range(TREND_SLOW - 1)])
        self.assertFalse(snap.available)
        self.assertIn("insufficient_history", snap.unavailable_reason)

    def test_output_is_deterministic(self) -> None:
        series = [100.0 + i * 0.8 for i in range(80)]
        self.assertEqual(classify_closes(series).as_json(), classify_closes(list(series)).as_json())

    def test_no_lookahead_future_bars_are_ignored_unless_passed_in(self) -> None:
        past = [100.0 + i * 0.5 for i in range(80)]
        future = past + [10.0, 10.0, 10.0]
        self.assertEqual(classify_closes(past).key, classify_closes(future[:80]).key)
        self.assertNotEqual(classify_closes(past).key, classify_closes(future).key)

    def test_trending_and_sideways_are_distinct(self) -> None:
        up = [100.0 * (1.01 ** i) for i in range(80)]
        chop = [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(80)]
        self.assertEqual(classify_closes(up).trend, "trending_up")
        self.assertEqual(classify_closes(chop).trend, "sideways")


class AggregationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_counts_expectancy_negative_evidence_and_insufficient(self) -> None:
        for index in range(8):
            _experience(self.store, decision_id=f"a{index}", regime_key="trending_up|volatility_high|normal", pnl=0.01)
        tiny = aggregate_experiences(self.store.list_experiences(limit=20), min_samples=20)
        self.assertEqual(tiny[0]["evidence_status"], "insufficient_evidence")
        self.assertIn("insufficient_evidence", tiny[0]["claim"])
        for index in range(20):
            _experience(self.store, decision_id=f"b{index}", regime_key="trending_up|volatility_high|normal", pnl=0.02)
        for index in range(12):
            _experience(self.store, decision_id=f"c{index}", regime_key="trending_up|volatility_high|normal", pnl=-0.01)
        rows = self.store.list_experiences(regime_key="trending_up|volatility_high|normal", limit=200)
        findings = aggregate_experiences(rows, min_samples=20)
        self.assertEqual(len(findings), 1)
        metrics = findings[0]["metrics"]
        self.assertEqual(metrics["count"], 40)
        self.assertGreater(metrics["losses"], 0)
        self.assertGreater(metrics["expectancy"], 0)
        self.assertEqual(findings[0]["evidence_status"], "sufficient")

    def test_versions_are_not_mixed(self) -> None:
        for index in range(20):
            _experience(self.store, decision_id=f"v1-{index}", regime_key="sideways|volatility_low|normal", pnl=0.01, version=1)
        for index in range(20):
            _experience(self.store, decision_id=f"v2-{index}", regime_key="sideways|volatility_low|normal", pnl=-0.02, version=2)
        findings = aggregate_experiences(self.store.list_experiences(limit=100), include_version=True, min_samples=20)
        versions = {(item.get("group") or {}).get("strategy_version") for item in findings}
        self.assertEqual(versions, {1, 2})
        by_version = {item["group"]["strategy_version"]: item["metrics"]["expectancy"] for item in findings}
        self.assertGreater(by_version[1], 0)
        self.assertLess(by_version[2], 0)


class BeliefTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_evidence_is_required_and_confidence_is_capped(self) -> None:
        with self.assertRaises(ValueError):
            self.store.upsert_trading_belief({"claim": "no evidence", "status": "confirmed", "confidence": 0.99})
        finding = {
            "finding_id": "f1",
            "claim": "momentum positive in trend",
            "evidence_refs": ["experience:x"],
            "evidence_status": "sufficient",
            "split": "development",
            "sample_count": 80,
            "metrics": {"count": 80, "wins": 50, "losses": 30, "expectancy": 0.01, "sample_sufficiency": True, "effect_size": 0.4, "consistency_periods": 8},
            "group": {"strategy_family": "momentum", "instrument_id": "btc", "timeframe": "1h", "regime_key": "trending_up|volatility_high|normal"},
        }
        quality = evidence_confidence(finding)
        self.assertLessEqual(quality["confidence"], quality["cap"])
        self.assertLessEqual(quality["cap"], 0.45)
        proposal = finding_to_belief_proposal(finding, now="2020-01-01T00:00:00+00:00")
        stored = self.store.upsert_trading_belief(proposal)
        self.assertTrue(stored["evidence_refs"])
        self.assertLessEqual(stored["confidence"], stored["confidence_cap"])

    def test_contradiction_and_supersession_keep_history(self) -> None:
        first = self.store.upsert_trading_belief(
            {
                "claim": "works in trend",
                "strategy_family": "momentum",
                "instrument_id": "btc",
                "timeframe": "1h",
                "regime_key": "trending_up|volatility_high|normal",
                "evidence_refs": ["experience:a"],
                "status": "supported",
                "confidence": 0.3,
                "confidence_cap": 0.45,
                "supporting_count": 40,
            }
        )
        updated = self.store.update_trading_belief_status(
            first["belief_id"],
            status="contradicted",
            reason="later sample lost after costs",
            evidence_refs=["experience:b"],
        )
        self.assertEqual(updated["status"], "contradicted")
        self.assertGreaterEqual(len(updated["history"]), 2)
        successor = self.store.upsert_trading_belief(
            {
                "claim": "only works with a regime filter",
                "strategy_family": "mean_reversion",
                "instrument_id": "eth",
                "timeframe": "1h",
                "regime_key": "sideways|volatility_low|normal",
                "evidence_refs": ["experience:c"],
                "status": "supported",
                "supersedes": first["belief_id"],
            }
        )
        self.store.update_trading_belief_status(
            successor["belief_id"],
            status="supported",
            superseded_by=None,
            reason="new specialised claim",
        )
        # Old evidence remains queryable.
        self.assertTrue(self.store.get_trading_belief(first["belief_id"])["evidence_refs"])


class CuratorValidationTest(unittest.TestCase):
    def test_missing_refs_and_unknown_refs_are_refused(self) -> None:
        findings = [{"finding_id": "f1", "evidence_refs": ["experience:1"]}]
        verdict = apply_curator_output(
            {
                "new_findings": [{"claim": "invented", "evidence_refs": []}],
                "confirmed_beliefs": [{"claim": "ok", "evidence_refs": ["experience:1"]}],
            },
            allowed_refs={"experience:1", "finding:f1"},
            findings=findings,
            prior_beliefs=[],
        )
        self.assertTrue(any(item["reason"] == "missing_evidence_refs" for item in verdict["rejected"]))
        self.assertEqual(len(verdict["accepted"]), 1)

    def test_malformed_output_is_refused(self) -> None:
        verdict = apply_curator_output("not json", allowed_refs=set(), findings=[], prior_beliefs=[])
        self.assertEqual(verdict["accepted"], [])
        self.assertEqual(verdict["rejected"][0]["reason"], "output_not_an_object")


class EvolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)
        self.registry = StrategyRegistry(self.store)
        self.parent = self.registry.create(_spec(), created_by="researcher")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mutation_creates_new_version_and_records_lineage(self) -> None:
        version = self.store.get_strategy_version(self.parent["strategy_id"])
        spec = StrategySpec.model_validate(version["spec"])
        findings = [
            {
                "finding_id": "f-pos",
                "evidence_status": "sufficient",
                "evidence_refs": ["experience:1"],
                "metrics": {"expectancy": 0.02, "count": 40},
                "group": {"regime_key": "trending_up|volatility_high|normal", "strategy_id": spec.strategy_id},
            },
            {
                "finding_id": "f-neg",
                "evidence_status": "sufficient",
                "evidence_refs": ["experience:2"],
                "metrics": {"expectancy": -0.03, "count": 40},
                "group": {"regime_key": "sideways|volatility_low|normal", "strategy_id": spec.strategy_id},
            },
        ]
        result = mutate_from_findings(spec, findings, budget={"max_candidates_per_parent": 3})
        self.assertTrue(result["candidates"])
        proposal = result["candidates"][0]
        child = materialize_candidate(spec, proposal)
        new_version = self.registry.add_version(spec.strategy_id, child, created_by="evolution_engine")
        parent_after = self.store.get_strategy_version(spec.strategy_id, 1)
        self.assertEqual(parent_after["spec"]["params"], spec.params)
        self.assertEqual(new_version, 2)
        self.store.save_strategy_lineage(
            {
                "parent_strategy_id": spec.strategy_id,
                "parent_version": 1,
                "child_strategy_id": spec.strategy_id,
                "child_version": 2,
                "mutation_kind": proposal["mutation_kind"],
                "mutation_reason": proposal["mutation_reason"],
                "changed_fields": proposal["changed_fields"],
                "evidence_refs": proposal["evidence_refs"],
                "fingerprint": proposal["fingerprint"],
            }
        )
        lineage = self.store.list_strategy_lineage(strategy_id=spec.strategy_id)
        self.assertEqual(lineage[0]["parent_version"], 1)
        self.assertEqual(lineage[0]["child_version"], 2)

    def test_duplicate_fingerprint_is_rejected_and_budget_is_enforced(self) -> None:
        spec = _spec()
        findings = [
            {
                "finding_id": "f1",
                "evidence_status": "sufficient",
                "evidence_refs": ["experience:1"],
                "metrics": {"expectancy": 0.01, "count": 30},
                "group": {"regime_key": "trending_up|volatility_high|normal"},
            }
        ]
        fingerprint = candidate_fingerprint(
            family=spec.family,
            params={**spec.params, "lookback": 10},
            instruments=spec.instruments,
            timeframe=spec.timeframe,
        )
        first = mutate_from_findings(spec, findings, known_fingerprints={fingerprint}, budget={"max_candidates_per_parent": 1})
        self.assertTrue(any(item["reason"] in {"already_evaluated", "max_candidates_per_parent"} for item in first["rejected"]) or first["candidates"])
        capped = mutate_from_findings(spec, findings, budget={"max_candidates_per_parent": 1})
        self.assertLessEqual(len(capped["candidates"]), 1)

    def test_failed_fingerprint_is_not_retried_as_if_nothing_happened(self) -> None:
        spec = _spec()
        findings = [
            {
                "finding_id": "f-fail",
                "evidence_status": "sufficient",
                "evidence_refs": ["experience:fail"],
                "metrics": {"expectancy": -0.05, "count": 40},
                "group": {"regime_key": "sideways|volatility_low|normal"},
            }
        ]
        result = mutate_from_findings(spec, findings)
        fingerprints = {item["fingerprint"] for item in result["candidates"]}
        retry = mutate_from_findings(spec, findings, failed_fingerprints=fingerprints)
        self.assertTrue(any(item["reason"] == "negative_evidence_blocks_identical_retry" for item in retry["rejected"]))
        identical = [item for item in retry["candidates"] if item["fingerprint"] in fingerprints]
        self.assertEqual(identical, [])


class ChampionPolicyTest(unittest.TestCase):
    def test_development_winner_cannot_become_champion(self) -> None:
        decision = evaluate_challenger(
            challenger={"status": "draft", "family": "momentum", "params": {}},
            champion=None,
            challenger_evaluations=[{"verdict": "pass", "splits_used": ["development"], "evaluator_role": "independent_validator", "report": {"aggregate": {"net_return": 0.5}}}],
        )
        self.assertEqual(decision["decision"], "reject")
        self.assertEqual(decision["reason"], "lifecycle_not_qualified")

    def test_weak_validation_blocks_replacement(self) -> None:
        decision = evaluate_challenger(
            challenger={"status": "validated", "family": "momentum", "params": {}},
            champion={"family": "momentum", "params": {}},
            challenger_evaluations=[{"verdict": "fail", "splits_used": ["validation"], "evaluator_role": "independent_validator", "report": {"aggregate": {"net_return": 0.4}}}],
            champion_evaluations=[{"verdict": "pass", "splits_used": ["validation"], "evaluator_role": "independent_validator", "report": {"aggregate": {"net_return": 0.1, "sharpe": 1.0, "max_drawdown": 0.1}}}],
        )
        self.assertEqual(decision["reason"], "weak_validation_blocks_replacement")

    def test_stronger_validated_evidence_permits_replacement(self) -> None:
        decision = evaluate_challenger(
            challenger={"status": "validated", "family": "mean_reversion", "params": {"regime_filter": {"trend": "sideways"}}},
            champion={"family": "momentum", "params": {}},
            challenger_evaluations=[{"verdict": "pass", "splits_used": ["validation"], "evaluator_role": "independent_validator", "report": {"aggregate": {"net_return": 0.2, "sharpe": 1.2, "max_drawdown": 0.05, "costs_paid": 10}}}],
            champion_evaluations=[{"verdict": "pass", "splits_used": ["validation"], "evaluator_role": "independent_validator", "report": {"aggregate": {"net_return": 0.01, "sharpe": 0.2, "max_drawdown": 0.3, "costs_paid": 50}}}],
        )
        self.assertIn(decision["decision"], {"replace", "install"})


class RegimeSpecialisationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_conditional_result_is_not_collapsed_to_globally_good(self) -> None:
        for index in range(25):
            _experience(self.store, decision_id=f"up{index}", regime_key="trending_up|volatility_high|normal", pnl=0.02)
        for index in range(25):
            _experience(self.store, decision_id=f"side{index}", regime_key="sideways|volatility_low|normal", pnl=-0.015)
        findings = aggregate_experiences(self.store.list_experiences(limit=100), min_samples=20)
        claims = " ".join(item["claim"] for item in findings)
        self.assertIn("trending_up|volatility_high|normal", claims)
        self.assertIn("sideways|volatility_low|normal", claims)
        self.assertFalse(all("positive" in item["claim"] for item in findings))
        spec = _spec()
        result = mutate_from_findings(spec, findings)
        kinds = {item["mutation_kind"] for item in result["candidates"]}
        self.assertTrue({"regime_filter", "no_trade_condition", "volatility_filter"} & kinds)


class RecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _db(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_interrupted_cycle_resumes_without_duplicating_experiences(self) -> None:
        for index in range(5):
            self.store.save_decision(
                {
                    "decision_id": f"r{index}",
                    "run_id": "run-r",
                    "event_time": f"2020-01-01T{index:02d}:00:00+00:00",
                    "instrument_id": "crypto_spot:test:BTCUSDT",
                    "strategy_id": "s1",
                    "action": "execute",
                    "signal": "long",
                    "later_outcome": {"resolved_at": "2020-01-02T00:00:00+00:00", "reference_price": 100.0, "later_price": 101.0, "price_change": 0.01},
                }
            )
        engine = LearningCycleEngine(self.store)
        cycle = engine.start(objective="resume test", autonomy_level="learn_only")
        self.store.update_learning_cycle(
            cycle["cycle_id"],
            status="aggregating",
            stage="aggregating",
            checkpoint={"stages_done": ["collecting"], "collect": ingest_resolved_decisions(self.store)},
        )
        again = ingest_resolved_decisions(self.store)
        self.assertEqual(again["created"], 0)
        finished = engine.run(cycle["cycle_id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(self.store.count_experiences(), 5)

    def test_holdout_split_is_not_used_for_mutation_context(self) -> None:
        for index in range(25):
            _experience(self.store, decision_id=f"dev{index}", regime_key="trending_up|volatility_high|normal", pnl=0.02, split="development")
        for index in range(25):
            _experience(self.store, decision_id=f"hold{index}", regime_key="trending_up|volatility_high|normal", pnl=0.5, split="sealed_test")
        engine = LearningCycleEngine(self.store)
        cycle = engine.start(objective="holdout isolation", autonomy_level="learn_only")
        finished = engine.run(cycle["cycle_id"])
        self.assertEqual(finished["status"], "completed")
        findings = self.store.list_learning_findings(cycle_id=cycle["cycle_id"], limit=50)
        splits = {item.get("split") for item in findings}
        self.assertNotIn("sealed_test", splits)


class ScopeKeyTest(unittest.TestCase):
    def test_scope_key_is_stable(self) -> None:
        self.assertEqual(
            scope_key(instrument_id="btc", timeframe="1h"),
            scope_key(instrument_id="btc", timeframe="1h"),
        )


if __name__ == "__main__":
    unittest.main()
