"""T4 — Control-plane integration: Gateway, JobStore leases, SecretsBroker."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.types import CapabilityRequest, CapabilityStatus
from Data.modules.jobs.store import JobStore
from Data.modules.market_sim.capabilities import register_market_sim_module_capabilities
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.experiments import evaluate_acceptance, walk_forward_splits
from Data.modules.market_sim.gateway_executor import MarketSimModuleExecutor
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.worker import MarketSimWorker
from Data.modules.security.secrets_broker import SecretsBroker


class GatewayMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        markets = root / "markets"
        markets.mkdir()
        db = root / "db.sqlite"
        store = MarketSimStore(db)
        store.initialize()
        data = MarketDataStore(store, markets)
        self.svc = MarketSimControlPlane(store, data, enabled=True)
        catalog = build_default_catalog()
        self.gateway = ExecutionGateway(
            catalog=catalog,
            module_executor=MarketSimModuleExecutor(self.svc),
        )
        self.svc.bind_execution_gateway(self.gateway)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_strategy_create_via_gateway(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="market_sim.strategy.create",
                arguments={"name": "gw-ma", "parameters": {"fast_ma": 5, "slow_ma": 20}},
                requested_by="api.market_sim",
                idempotency_key="t4-strategy-create-1",
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        out = result.output
        assert isinstance(out, dict)
        inner = out.get("output") or out
        self.assertIn("strategy", inner)
        self.assertTrue(out.get("truth", {}).get("via_execution_gateway"))

    def test_catalog_registers_market_sim_mutations(self) -> None:
        catalog = build_default_catalog()
        self.assertIsNotNone(catalog.get("market_sim.run.start"))
        self.assertIsNotNone(catalog.get("market_sim.paper.order.place"))
        self.assertEqual(
            (catalog.get("market_sim.run.start").metadata or {}).get("approval_mode"),
            "receipt_only",
        )


class JobStoreLeaseTests(unittest.TestCase):
    def test_claim_uses_begin_immediate(self) -> None:
        import inspect

        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertIn("BEGIN IMMEDIATE", src)

    def test_worker_jobstore_heartbeat_path(self) -> None:
        src = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "worker.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("JobStore", text)
        self.assertIn("heartbeat", text.lower())

    def test_worker_binds_job_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "j.sqlite"
            store = MarketSimStore(db)
            store.initialize()
            job_store = JobStore(db)
            worker = MarketSimWorker(
                store,
                mock.Mock(),
                resolve_bars_path=lambda r: "",
                job_store=job_store,
            )
            self.assertEqual(worker.telemetry["lease_model"], "jobstore_lease")


class SecretsBrokerAlpacaTests(unittest.TestCase):
    def test_paper_broker_references_secrets_broker(self) -> None:
        text = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "paper_broker.py"
        src = text.read_text(encoding="utf-8")
        self.assertIn("SecretsBroker", src)
        self.assertIn("env:LEVIATHAN_ALPACA_PAPER", src)

    def test_alpaca_resolves_via_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "s.sqlite"
            broker = SecretsBroker(db)
            broker.initialize()
            os.environ["LEVIATHAN_ALPACA_PAPER_KEY_ID"] = "PKTEST"
            os.environ["LEVIATHAN_ALPACA_PAPER_SECRET"] = "SECRETtest"
            try:
                from Data.modules.market_sim.paper_broker import AlpacaPaperBroker

                alpaca = AlpacaPaperBroker(secrets_broker=broker)
                key, secret = alpaca._resolve_credentials()
                self.assertEqual(key, "PKTEST")
                self.assertEqual(secret, "SECRETtest")
            finally:
                os.environ.pop("LEVIATHAN_ALPACA_PAPER_KEY_ID", None)
                os.environ.pop("LEVIATHAN_ALPACA_PAPER_SECRET", None)


class ExperimentScienceEarlyWins(unittest.TestCase):
    def test_acceptance_reads_compute_metrics_shape(self) -> None:
        from Data.modules.market_sim.metrics import compute_metrics

        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0)
        m_with_trades = {**m, "trade_count": {"status": "MEASURED", "value": 1}}
        passed, reason = evaluate_acceptance(
            m_with_trades,
            {"min_trades": 1, "max_drawdown_pct": 50.0, "min_total_return_pct": 0.0},
            run_id="run-1",
        )
        self.assertTrue(passed, reason)

    def test_rolling_walk_forward_windows(self) -> None:
        split = walk_forward_splits(100, window=20, step=10)
        self.assertIn("windows", split)
        self.assertGreaterEqual(len(split["windows"]), 2)

    def test_trial_append_and_version_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            trial = {
                "trial_id": "t1",
                "strategy_id": "s1",
                "strategy_version": 1,
                "hypothesis": "h",
                "proposer_agent_id": "human",
                "data_hash": "h",
                "fingerprint": "fp1",
                "status": "proposed",
                "config": {},
                "split": {},
                "results": {},
                "acceptance_criteria": {},
                "rejection_reason": "",
                "seed": 42,
                "created_at": "2024-01-01T00:00:00+00:00",
                "finished_at": None,
                "metadata": {},
            }
            store.append_trial(trial)
            self.assertEqual(store.count_trials(), 1)
            trial2 = dict(trial)
            trial2["status"] = "passed"
            trial2["strategy_version"] = 2
            trial2["results"] = {"ok": True}
            trial2["finished_at"] = "2024-01-02T00:00:00+00:00"
            store.save_experiment(trial2)
            loaded = store.list_experiments(strategy_id="s1")[0]
            self.assertEqual(int(loaded.get("strategy_version") or 0), 2)


class BackupTradingTablesTests(unittest.TestCase):
    def test_backup_restore_preserves_market_experiments(self) -> None:
        from Data.modules.backup.service import BackupService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "leviathan.db"
            store = MarketSimStore(db)
            store.initialize()
            store.save_experiment(
                {
                    "trial_id": "bk1",
                    "strategy_id": "s",
                    "strategy_version": 1,
                    "hypothesis": "backup",
                    "proposer_agent_id": "t4",
                    "data_hash": "x",
                    "fingerprint": "fp-bk",
                    "status": "proposed",
                    "config": {},
                    "split": {},
                    "results": {},
                    "acceptance_criteria": {},
                    "rejection_reason": "",
                    "seed": 1,
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "finished_at": None,
                    "metadata": {},
                }
            )
            backup = BackupService(
                database_path=db,
                artifacts_root=root / "artifacts",
                backup_root=root / "backups",
            )
            (root / "artifacts").mkdir(exist_ok=True)
            manifest = backup.create(note="t4-trading")
            # Wipe and restore
            db.unlink()
            restored = backup.restore(manifest.backup_id, confirm=True)
            self.assertEqual(restored.backup_id, manifest.backup_id)
            store2 = MarketSimStore(db)
            trials = store2.list_experiments()
            self.assertEqual(len(trials), 1)
            self.assertEqual(trials[0]["trial_id"], "bk1")


class ObservabilityTradingCategoryTests(unittest.TestCase):
    def test_emit_uses_trading_category(self) -> None:
        events: list[tuple[str, str]] = []

        def _emit(category: str, name: str, payload=None, **kwargs):
            events.append((category, name))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            svc = MarketSimControlPlane(
                store,
                MarketDataStore(store, markets),
                enabled=True,
                observability_emit=_emit,
            )
            svc.create_strategy(name="obs")
            self.assertTrue(events)
            self.assertEqual(events[0][0], "trading")


if __name__ == "__main__":
    unittest.main()
