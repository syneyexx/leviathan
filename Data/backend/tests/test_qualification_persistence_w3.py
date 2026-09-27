"""Wave 3 — MARKET qualification persistence migration + store CRUD."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import (
    DOMAIN_MIGRATIONS,
    apply_pending_domain_migrations,
    domain_schema_version,
    ensure_domain_schema,
    upgrade_all_databases,
)
from Data.backend.table_ownership import ownership_for
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.market_sim.store import MarketSimStore


REQUIRED_TABLES = (
    "market_qualification_policies",
    "market_qualification_runs",
    "market_qualification_gate_results",
    "market_wfa_folds",
    "market_dataset_certifications",
    "market_strategy_behavior_fingerprints",
    "market_strategy_risk_snapshots",
    "market_execution_calibrations",
    "market_strategy_lifecycle",
)


def _fresh_paths(root: Path) -> DatabasePaths:
    return DatabasePaths(
        control=root / "control.db",
        knowledge=root / "knowledge.db",
        market=root / "market.db",
    )


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r[0] for r in rows}


class QualificationPersistenceWave3Tests(unittest.TestCase):
    def test_domain_migration_catalog_contiguous_v3(self) -> None:
        versions = [m.version for m in DOMAIN_MIGRATIONS]
        self.assertEqual(versions, list(range(2, 2 + len(versions))))
        names = {m.name for m in DOMAIN_MIGRATIONS}
        self.assertIn("market_qualification_authority", names)
        for name in REQUIRED_TABLES:
            self.assertEqual(ownership_for(name), DatabaseDomain.MARKET)

    def test_fresh_install_creates_qualification_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fresh_paths(Path(tmp))
            report = upgrade_all_databases(paths)
            self.assertTrue(report.completed)
            self.assertGreaterEqual(domain_schema_version(paths.market), 3)
            found = _tables(paths.market)
            for name in REQUIRED_TABLES:
                self.assertIn(name, found)
            # MARKET-only DDL — siblings must not get these product tables.
            for name in REQUIRED_TABLES:
                self.assertNotIn(name, _tables(paths.control))
                self.assertNotIn(name, _tables(paths.knowledge))

    def test_upgrade_from_v2_and_idempotent_reapply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market = root / "market.db"
            # Materialize baseline + v2 only by applying migrations manually.
            ensure_domain_schema(market, DatabaseDomain.MARKET)
            # Force schema ledger back to v2 if already at v3 (fresh path applies all).
            ver = domain_schema_version(market)
            self.assertGreaterEqual(ver, 2)
            if ver >= 3:
                # Simulate upgrade-from-v2: wipe v3 ledger entry + drop new tables,
                # then re-apply pending migrations.
                with sqlite3.connect(market) as conn:
                    conn.execute("DELETE FROM schema_migrations WHERE version >= 3")
                    for name in REQUIRED_TABLES:
                        conn.execute(f"DROP TABLE IF EXISTS {name}")
                    conn.commit()
                self.assertEqual(domain_schema_version(market), 2)
            applied = apply_pending_domain_migrations(market, DatabaseDomain.MARKET)
            self.assertIn(3, applied)
            tip = max(m.version for m in DOMAIN_MIGRATIONS)
            self.assertEqual(domain_schema_version(market), tip)
            found = _tables(market)
            for name in REQUIRED_TABLES:
                self.assertIn(name, found)
            # Idempotent re-apply
            again = apply_pending_domain_migrations(market, DatabaseDomain.MARKET)
            self.assertEqual(again, [])
            self.assertEqual(domain_schema_version(market), tip)

    def test_store_crud_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            store = MarketSimStore(db)
            store.initialize()
            self.assertGreaterEqual(domain_schema_version(db), 3)

            store.save_qualification_policy(
                {
                    "policy_id": "pol-1",
                    "version": 1,
                    "name": "default",
                    "policy_hash": "phash1",
                    "policy_json": {"name": "default", "min_trades": 10},
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "created_by": "test",
                    "active": 1,
                }
            )
            pol = store.get_qualification_policy("pol-1")
            assert pol is not None
            self.assertEqual(pol["policy_hash"], "phash1")
            self.assertEqual(pol["policy_json"]["min_trades"], 10)

            store.create_qualification_run(
                {
                    "qualification_id": "q-1",
                    "policy_id": "pol-1",
                    "experiment_id": None,
                    "learning_run_id": None,
                    "candidate_id": "cand-1",
                    "trial_family_id": "fam-1",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "strategy_hash": "sh",
                    "source_id": "src",
                    "dataset_id": "ds",
                    "dataset_version_id": "dsv",
                    "dataset_hash": "dh",
                    "git_sha": "g",
                    "code_version": "c",
                    "seed": 7,
                    "status": "CREATED",
                    "blockers": [],
                    "warnings": [],
                    "provenance_hash": "prov",
                    "sealed_attempt_id": None,
                    "idempotency_key": "idem-q-1",
                }
            )
            run = store.get_qualification_run("q-1")
            assert run is not None
            self.assertEqual(run["trial_family_id"], "fam-1")
            store.update_qualification_run("q-1", {"status": "RUNNING", "blockers": ["x"]})
            run2 = store.get_qualification_run("q-1")
            assert run2 is not None
            self.assertEqual(run2["status"], "RUNNING")
            self.assertEqual(run2["blockers"], ["x"])

            store.upsert_qualification_gate_result(
                {
                    "gate_result_id": "gr-1",
                    "qualification_id": "q-1",
                    "gate_id": "Q01_DATA_CERTIFICATION",
                    "state": "UNMEASURED",
                    "passed": 0,
                    "methodology": "test",
                    "evidence": {"a": 1},
                    "metrics": {},
                    "blockers": ["DATA_PIT_NOT_CERTIFIED"],
                    "warnings": [],
                    "input_hash": "i",
                    "output_hash": "o",
                }
            )
            gates = store.list_qualification_gate_results("q-1")
            self.assertEqual(len(gates), 1)
            self.assertEqual(gates[0]["gate_id"], "Q01_DATA_CERTIFICATION")

            store.upsert_wfa_fold(
                {
                    "fold_id": "f1",
                    "qualification_id": "q-1",
                    "fold_index": 0,
                    "train_start_ts": "2020-01-01",
                    "train_end_ts": "2020-06-01",
                    "test_start_ts": "2020-06-02",
                    "test_end_ts": "2020-12-01",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "frozen_params": {"x": 1},
                    "metrics": {"sharpe": 0.1},
                    "state": "PASS",
                }
            )
            folds = store.list_wfa_folds("q-1")
            self.assertEqual(len(folds), 1)

            store.save_dataset_certification(
                {
                    "certification_id": "cert-1",
                    "dataset_id": "ds",
                    "dataset_version_id": "dsv",
                    "dataset_hash": "dh",
                    "data_type": "OHLCV",
                    "certification_state": "PASS",
                    "pit_state": "PASS",
                    "survivorship_state": "PASS",
                    "revision_state": "PASS",
                    "corporate_action_state": "PASS",
                    "source_id": "src",
                    "license_state": "PASS",
                    "evidence": {},
                    "certification_hash": "chash",
                    "certified_at": "2026-01-01T00:00:00+00:00",
                    "certified_by": "test",
                }
            )
            cert = store.get_dataset_certification(dataset_id="ds", dataset_version_id="dsv")
            assert cert is not None
            self.assertEqual(cert["certification_hash"], "chash")

            store.save_strategy_behavior_fingerprint(
                {
                    "fingerprint_id": "fp-1",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "dataset_version_id": "dsv",
                    "signal_hash": "a",
                    "position_hash": "b",
                    "trade_timing_hash": "c",
                    "return_series_hash": "d",
                    "feature_set_hash": "e",
                    "summary": {"ok": True},
                }
            )
            fp = store.get_strategy_behavior_fingerprint(
                strategy_id="s1", strategy_version=1, dataset_version_id="dsv"
            )
            assert fp is not None
            self.assertEqual(fp["signal_hash"], "a")

            store.save_strategy_risk_snapshot(
                {
                    "snapshot_id": "snap-1",
                    "portfolio_id": "pf-1",
                    "as_of": "2026-01-02T00:00:00+00:00",
                    "strategy_ids": ["s1"],
                    "sample_count": 10,
                    "covariance": {},
                    "correlation": {},
                    "risk_contribution": {},
                    "methodology": "test",
                    "state": "MEASURED",
                    "input_hash": "ih",
                }
            )
            snap = store.latest_strategy_risk_snapshot("pf-1")
            assert snap is not None
            self.assertEqual(snap["snapshot_id"], "snap-1")

            store.save_execution_calibration(
                {
                    "calibration_id": "cal-1",
                    "execution_model_id": "em",
                    "execution_model_version": "1",
                    "source_deployment_ids": [],
                    "sample_count": 3,
                    "parameters": {},
                    "metrics": {},
                    "state": "CALIBRATED",
                    "confidence": {},
                    "input_hash": "ih",
                    "created_by": "test",
                }
            )
            cals = store.list_execution_calibrations(execution_model_id="em")
            self.assertEqual(len(cals), 1)

            store.save_strategy_lifecycle(
                {
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "state": "VALIDATION",
                    "evidence": {"sealed_holdout": "UNMEASURED"},
                    "history": [],
                    "notes": ["wave3"],
                    "qualification_id": "q-1",
                }
            )
            life = store.get_strategy_lifecycle("s1", 1)
            assert life is not None
            self.assertEqual(life["state"], "VALIDATION")

            # Family trial helpers
            store.append_trial(
                {
                    "trial_id": "t1",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "hypothesis": "h",
                    "proposer_agent_id": "p",
                    "data_hash": "dh",
                    "fingerprint": "fp-t1",
                    "status": "DONE",
                    "config": {"trial_family_id": "fam-1", "candidate_id": "c1"},
                    "results": {},
                    "acceptance_criteria": {},
                    "seed": 1,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            )
            store.append_trial(
                {
                    "trial_id": "t2",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "hypothesis": "h",
                    "proposer_agent_id": "p",
                    "data_hash": "dh",
                    "fingerprint": "fp-t2",
                    "status": "DONE",
                    "config": {"trial_family_id": "fam-1", "candidate_id": "c2"},
                    "results": {},
                    "acceptance_criteria": {},
                    "seed": 2,
                    "created_at": "2026-01-01T00:00:01+00:00",
                    "metadata": {},
                }
            )
            self.assertEqual(store.count_trials_for_family("fam-1"), 2)
            self.assertEqual(store.distinct_candidate_count_for_family("fam-1"), 2)
            self.assertEqual(len(store.list_trials_for_family("fam-1")), 2)


if __name__ == "__main__":
    unittest.main()
