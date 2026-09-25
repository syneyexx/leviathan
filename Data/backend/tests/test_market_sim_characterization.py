"""Phase T0 characterization tests for Market Sim defects D1–D31 (Master Program v4).

Each test is tagged with its defect ID. Passing tests document *current*
defective behaviour (T0 leaves the tree green). Companion tests assert the
*desired* post-fix contract and are marked ``expectedFailure`` until the
fixing phase converts them into regressions.

No feature/fix code belongs in this file — characterization only.
"""

from __future__ import annotations

import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MIGRATIONS
from Data.modules.market_sim.accounting import WalletBook, money
from Data.modules.market_sim.capabilities import build_market_capabilities
from Data.modules.market_sim.causality import SimulationClock, assert_no_future
from Data.modules.market_sim.engine import SimulationEngine
from Data.modules.market_sim.execution import NextBarFillModel, OrderIntent, make_intent
from Data.modules.market_sim.experiments import evaluate_acceptance, walk_forward_splits
from Data.modules.market_sim.fill_model import FillModel
from Data.modules.market_sim.metrics import compute_metrics
from Data.modules.market_sim.multi_engine import MultiAgentEngine
from Data.modules.market_sim.ohlcv import _normalize_ts, load_ohlcv, validate_ohlcv_file
from Data.modules.market_sim.paper_broker import LocalPaperBroker
from Data.modules.market_sim.portfolio import Portfolio
from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import (
    Bar,
    MetricStatus,
    OrderType,
    SimFill,
    SimRun,
)
from Data.modules.trading.stub import TradingStub


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


def _bars(n: int = 10) -> list[Bar]:
    out: list[Bar] = []
    for i in range(n):
        day = i // 2 + 1
        hour = 10 if i % 2 == 0 else 14
        ts = f"2024-01-{day:02d}T{hour:02d}:00:00+00:00"
        px = 100.0 + i
        out.append(Bar(ts=ts, open=px, high=px + 1, low=px - 1, close=px + 0.5, volume=1_000_000))
    return out


def _run(**kwargs: object) -> SimRun:
    base: dict = dict(
        run_id="run-char",
        status="QUEUED",
        source_id="src",
        strategy_id="strat",
        strategy_version=1,
        symbol="BTCUSDT",
        timeframe="1h",
        start_ts="",
        end_ts="",
        data_hash=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        seed=42,
        initial_cash=100_000.0,
        cash=100_000.0,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    base.update(kwargs)
    return SimRun(**base)  # type: ignore[arg-type]


def _store(tmp: str | Path) -> MarketSimStore:
    store = MarketSimStore(Path(tmp) / "leviathan.db")
    store.initialize()
    return store


# ---------------------------------------------------------------------------
# D1 — Sharpe/Sortino mis-annualized
# ---------------------------------------------------------------------------


class D1AnnualizationCharacterization(unittest.TestCase):
    def test_d1_current_default_is_daily_252(self) -> None:
        sig = inspect.signature(compute_metrics)
        self.assertEqual(sig.parameters["periods_per_year"].default, 252.0)

    def test_d1_current_engines_omit_periods_per_year(self) -> None:
        engine_src = inspect.getsource(SimulationEngine._finalize_metrics)
        multi_src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertNotIn("periods_per_year", engine_src)
        self.assertNotIn("periods_per_year", multi_src)

    @unittest.expectedFailure  # D1 — fixed in Phase T1
    def test_d1_desired_engines_pass_timeframe_annualization(self) -> None:
        engine_src = inspect.getsource(SimulationEngine._finalize_metrics)
        multi_src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertIn("periods_per_year", engine_src)
        self.assertIn("periods_per_year", multi_src)


# ---------------------------------------------------------------------------
# D2 — Win rate / profit factor UNMEASURED without round-trip ledger
# ---------------------------------------------------------------------------


class D2WinRateCharacterization(unittest.TestCase):
    def test_d2_current_simfill_omits_realized_delta(self) -> None:
        fill = SimFill(
            fill_id="f1",
            run_id="r",
            bar_index=1,
            ts="t",
            side="SELL",
            qty=1.0,
            price=100.0,
            fee=0.1,
            slippage=0.0,
            agent_id="a",
            rationale="",
            status="FILLED",
            created_at=utc_now(),
        )
        self.assertNotIn("realized_delta", fill.public_dict())

    def test_d2_current_metrics_unmeasured_without_realized_delta(self) -> None:
        equity = [100.0, 101.0, 102.0]
        fills = [{"side": "SELL", "qty": 1, "price": 101, "fee": 0.1}]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0)
        self.assertEqual(m["win_rate"]["status"], MetricStatus.UNMEASURED.value)
        self.assertEqual(m["profit_factor"]["status"], MetricStatus.UNMEASURED.value)

    @unittest.expectedFailure  # D2 — fixed in Phase T1
    def test_d2_desired_simfill_carries_realized_delta(self) -> None:
        fill = SimFill(
            fill_id="f1",
            run_id="r",
            bar_index=1,
            ts="t",
            side="SELL",
            qty=1.0,
            price=110.0,
            fee=0.1,
            slippage=0.0,
            agent_id="a",
            rationale="",
            status="FILLED",
            created_at=utc_now(),
        )
        self.assertIn("realized_delta", fill.public_dict())


# ---------------------------------------------------------------------------
# D3 — RiskGuard.orders_today never resets
# ---------------------------------------------------------------------------


class D3OrdersPerDayCharacterization(unittest.TestCase):
    def test_d3_current_orders_today_never_rolls(self) -> None:
        guard = RiskGuard(RiskLimits(max_orders_per_day=2))
        book = WalletBook()
        w = book.ensure_agent("a1", initial_cash=10_000)
        for i in range(2):
            intent = make_intent(
                run_id="r",
                agent_id="a1",
                wallet_id=w.wallet_id,
                side="BUY",
                qty=1,
                decision_bar_index=i,
                decision_ts=f"t{i}",
                info_version=f"iv{i}",
            )
            decision = guard.evaluate_intent(intent, wallet=w, price=100.0)
            self.assertTrue(decision.allowed, decision.reason)
            guard.orders_today += 1
        intent3 = make_intent(
            run_id="r",
            agent_id="a1",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=1,
            decision_bar_index=3,
            decision_ts="2024-01-02T10:00:00+00:00",
            info_version="iv3",
        )
        decision3 = guard.evaluate_intent(intent3, wallet=w, price=100.0)
        self.assertFalse(decision3.allowed)
        self.assertEqual(guard.orders_today, 2)
        self.assertFalse(hasattr(guard, "roll_day"))
        self.assertFalse(hasattr(guard, "on_bar_timestamp"))

    @unittest.expectedFailure  # D3 — fixed in Phase T1
    def test_d3_desired_per_simulated_day_rollover_api(self) -> None:
        guard = RiskGuard(RiskLimits(max_orders_per_day=2))
        self.assertTrue(
            callable(getattr(guard, "on_bar_timestamp", None))
            or callable(getattr(guard, "roll_day", None))
        )


# ---------------------------------------------------------------------------
# D4 — Default sizing ~1% notional
# ---------------------------------------------------------------------------


class D4SizingCharacterization(unittest.TestCase):
    def test_d4_current_default_sizes_tiny_notional(self) -> None:
        guard = RiskGuard(RiskLimits(per_trade_risk_pct=1.0, max_position_pct=25.0))
        book = WalletBook()
        w = book.ensure_agent("a1", initial_cash=100_000)
        intent = make_intent(
            run_id="r",
            agent_id="a1",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=None,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="iv",
        )
        decision = guard.evaluate_intent(intent, wallet=w, price=100.0)
        self.assertTrue(decision.allowed, decision.reason)
        notional = float(decision.sized_qty) * 100.0
        self.assertLess(notional, 6_000.0)
        self.assertAlmostEqual(notional, 1_000.0, delta=50.0)

    @unittest.expectedFailure  # D4 — fixed in Phase T1
    def test_d4_desired_explicit_sizing_model_on_run(self) -> None:
        run = _run()
        payload = run.public_dict()
        self.assertTrue(
            "sizing_model" in payload or "sizing_model" in (run.metadata or {})
        )


# ---------------------------------------------------------------------------
# D5 — Dual fill models; partial remainder dropped
# ---------------------------------------------------------------------------


class D5FillModelCharacterization(unittest.TestCase):
    def test_d5_current_two_fill_models_exist(self) -> None:
        self.assertTrue(inspect.isclass(FillModel))
        self.assertTrue(inspect.isclass(NextBarFillModel))
        legacy = FillModel(fee_bps=10, slippage_bps=5)
        nxt = NextBarFillModel(fee_bps=10, slippage_bps=5, max_participation=0.1)
        self.assertNotEqual(type(legacy).__module__, type(nxt).__module__)

    def test_d5_current_partial_marks_intent_filled_drops_remainder(self) -> None:
        book = WalletBook()
        w = book.ensure_agent("a1", initial_cash=500)
        intent = make_intent(
            run_id="r",
            agent_id="a1",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=100,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="iv",
        )
        model = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0)
        result = model.execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(result.filled)
        self.assertLess(float(result.qty), 100.0)
        self.assertEqual(intent.status, "filled")
        self.assertNotEqual(intent.status, "working")

    @unittest.expectedFailure  # D5 — fixed in Phase T1
    def test_d5_desired_partial_leaves_working_remainder(self) -> None:
        book = WalletBook()
        w = book.ensure_agent("a1", initial_cash=500)
        intent = make_intent(
            run_id="r",
            agent_id="a1",
            wallet_id=w.wallet_id,
            side="BUY",
            qty=100,
            decision_bar_index=0,
            decision_ts="t0",
            info_version="iv",
        )
        model = NextBarFillModel(fee_bps=0, slippage_bps=0, max_participation=1.0)
        result = model.execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(result.filled)
        self.assertEqual(intent.status, "working")
        remaining = money(intent.qty) - money(result.qty)
        self.assertGreater(remaining, 0)


# ---------------------------------------------------------------------------
# D6 — Resume / soft lease
# ---------------------------------------------------------------------------


class D6ResumeCharacterization(unittest.TestCase):
    def test_d6_current_multi_prepare_resets_wallets_and_rewinds_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            engine = MultiAgentEngine(store)
            run = _run(
                bar_index=5,
                cash=50_000.0,
                agents=[
                    {
                        "agent_id": "a1",
                        "role": "analyst",
                        "authority": {"may_order": True},
                    }
                ],
                metadata={
                    "game_mode": "individual",
                    "agent_initial_cash": 100_000,
                    "wallet_snapshot": {"a1": {"cash": "50000", "position_qty": "1"}},
                },
            )
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertEqual(state.clock.index, 4)
            wallet = next(iter(state.book.wallets.values()))
            self.assertEqual(float(wallet.cash), 100_000.0)

    def test_d6_current_claim_sets_worker_pid_without_lease_expiry(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            run = _run(run_id="lease-1", status="QUEUED")
            store.create_run(run)
            claimed = store.claim_next_runnable()
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed.worker_pid, os.getpid())
            claimed.status = "RUNNING"
            store.update_run(claimed)
            again = store.claim_next_runnable()
            self.assertIsNone(again)

    @unittest.expectedFailure  # D6 — fixed in Phase T1/T5
    def test_d6_desired_expired_lease_reclaimable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            self.assertTrue(
                hasattr(store, "heartbeat_run_lease") or hasattr(store, "expire_stale_leases")
            )


# ---------------------------------------------------------------------------
# D7 — Data hash not verified at prepare
# ---------------------------------------------------------------------------


class D7DataHashCharacterization(unittest.TestCase):
    def test_d7_prepare_refuses_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            engine = SimulationEngine(store)
            run = _run(data_hash="definitely-not-the-file-hash", bar_index=0)
            with self.assertRaises(Exception):
                engine.prepare(run, bars_path=str(FIXTURE))

    def test_d7_prepare_accepts_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            engine = SimulationEngine(store)
            file_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
            run = _run(data_hash=file_hash, bar_index=0)
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertGreater(len(state.clock.bars), 0)


# ---------------------------------------------------------------------------
# D8 — Persistence / memory hot path
# ---------------------------------------------------------------------------


class D8PersistenceCharacterization(unittest.TestCase):
    def test_d8_current_connect_opens_fresh_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            src = inspect.getsource(store.connect)
            self.assertIn("sqlite3.connect", src)
            self.assertFalse(hasattr(store, "begin_slice"))

    def test_d8_current_list_equity_silently_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            run = _run(run_id="eq-1")
            store.create_run(run)
            for i in range(100):
                store.add_equity_point(run.run_id, i, f"t{i}", 100.0 + i, 100.0, 0.0)
            rows = store.list_equity(run.run_id, limit=10)
            self.assertEqual(len(rows), 10)

    def test_d8_current_load_ohlcv_returns_full_list(self) -> None:
        bars = load_ohlcv(FIXTURE)
        self.assertIsInstance(bars, list)
        self.assertGreater(len(bars), 100)

    def test_d8_current_multi_finalize_reloads_equity(self) -> None:
        src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertIn("list_equity", src)

    @unittest.expectedFailure  # D8 — fixed in Phase T1/T2
    def test_d8_desired_streaming_bars_api(self) -> None:
        from Data.modules.market_sim import ohlcv as ohlcv_mod

        self.assertTrue(
            hasattr(ohlcv_mod, "iter_ohlcv") or hasattr(ohlcv_mod, "stream_ohlcv")
        )


# ---------------------------------------------------------------------------
# D9 — Ingestion shallow / timestamp pitfalls
# ---------------------------------------------------------------------------


class D9IngestCharacterization(unittest.TestCase):
    def test_d9_yyyymmdd_parses_as_calendar_date(self) -> None:
        ts = _normalize_ts("20240115")
        self.assertTrue(ts.startswith("2024-01-15"))

    def test_d9_duplicate_timestamps_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T00:00:00+00:00,1.5,2.5,1,2,10\n",
                encoding="utf-8",
            )
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)

    def test_d9_microsecond_epoch_handled(self) -> None:
        us = "1704067200000000"  # 2024-01-01 approx in microseconds
        ts = _normalize_ts(us)
        year = int(ts[:4])
        self.assertEqual(year, 2024)

    def test_d9_current_ohlc_inconsistency_invalidates_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n"
                "2024-01-01T01:00:00+00:00,1,0.5,2,1,10\n",
                encoding="utf-8",
            )
            result = validate_ohlcv_file(path)
            self.assertFalse(result.ok)


# ---------------------------------------------------------------------------
# D10 — SimulationClock.bars public; lex compare
# ---------------------------------------------------------------------------


class D10ClockCharacterization(unittest.TestCase):
    def test_d10_future_bars_unreachable_via_market_view(self) -> None:
        bars = _bars(5)
        clock = SimulationClock(bars=bars)
        clock.advance()
        # Engine may still hold full series; agents use MarketView.
        from Data.modules.market_sim.types import CausalityViolation
        from Data.modules.market_sim.causality import MarketView

        view = MarketView(clock=clock)
        with self.assertRaises(CausalityViolation):
            view.bar_at(4)
        with self.assertRaises(CausalityViolation):
            clock.observe(4)

    def test_d10_assert_no_future_is_datetime_aware(self) -> None:
        src = inspect.getsource(assert_no_future)
        self.assertIn("compare_ts", src)
        from Data.modules.market_sim.types import CausalityViolation

        with self.assertRaises(CausalityViolation):
            assert_no_future(["2025-01-01T00:00:00+00:00"], "2024-01-01T00:00:00+00:00")

    def test_d10_bounded_market_view_hides_future(self) -> None:
        from Data.modules.market_sim import causality as causality_mod

        self.assertTrue(hasattr(causality_mod, "MarketView"))
        bars = _bars(5)
        clock = SimulationClock(bars=bars)
        clock.advance()
        view = causality_mod.MarketView(clock=clock)
        self.assertEqual(view.visible_count(), 1)
        self.assertFalse(view.has_future_access())


# ---------------------------------------------------------------------------
# D11 — Caller-supplied metrics accepted as evidence
# ---------------------------------------------------------------------------


class D11CallerMetricsCharacterization(unittest.TestCase):
    def test_d11_current_evaluate_acceptance_trusts_caller_dict(self) -> None:
        fake = {
            "trade_count": 100,
            "total_return_pct": 50.0,
            "max_drawdown_pct": 5.0,
            "excess_return_pct": 10.0,
        }
        passed, reason = evaluate_acceptance(fake, {"min_trades": 5, "beat_benchmark": True})
        self.assertTrue(passed, reason)

    @unittest.expectedFailure  # D11 — fixed in Phase T4
    def test_d11_desired_acceptance_requires_run_derived_metrics(self) -> None:
        sig = inspect.signature(evaluate_acceptance)
        params = list(sig.parameters)
        self.assertTrue("run_ids" in params or "run_id" in params)


# ---------------------------------------------------------------------------
# D12 — Acceptance key mismatch vs compute_metrics
# ---------------------------------------------------------------------------


class D12AcceptanceKeyMismatchCharacterization(unittest.TestCase):
    def test_d12_current_real_metrics_fail_acceptance_by_key_mismatch(self) -> None:
        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0)
        self.assertIn("total_return", m)
        self.assertNotIn("total_return_pct", m)
        self.assertNotIn("trade_count", m)
        passed, reason = evaluate_acceptance(m, {"min_trades": 1, "max_drawdown_pct": 50.0})
        self.assertFalse(passed)
        self.assertIn("insufficient trades", reason)

    @unittest.expectedFailure  # D12 — fixed in Phase T4
    def test_d12_desired_acceptance_reads_compute_metrics_shape(self) -> None:
        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0)
        m_with_trades = {**m, "trade_count": {"status": "MEASURED", "value": 1}}
        passed, _reason = evaluate_acceptance(
            m_with_trades,
            {"min_trades": 1, "max_drawdown_pct": 50.0, "min_total_return_pct": 0.0},
        )
        self.assertTrue(passed)


# ---------------------------------------------------------------------------
# D13 — Walk-forward never executed
# ---------------------------------------------------------------------------


class D13WalkForwardCharacterization(unittest.TestCase):
    def test_d13_current_single_split_no_windows(self) -> None:
        bars = _bars(100)
        split = walk_forward_splits("2024-01-01T00:00:00+00:00", "2024-02-20T00:00:00+00:00", bars)
        self.assertIn("design", split)
        self.assertIn("validation", split)
        self.assertIn("test", split)
        self.assertNotIn("windows", split)

    @unittest.expectedFailure  # D13 — fixed in Phase T4
    def test_d13_desired_rolling_windows(self) -> None:
        split = walk_forward_splits(100, window=20, step=10)  # type: ignore[call-arg]
        self.assertIn("windows", split)
        self.assertGreaterEqual(len(split["windows"]), 2)


# ---------------------------------------------------------------------------
# D14 — Trial ledger not global / strategy_version not persisted on upsert
# ---------------------------------------------------------------------------


class D14TrialLedgerCharacterization(unittest.TestCase):
    def test_d14_current_upsert_drops_strategy_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
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
                "created_at": utc_now(),
                "finished_at": None,
                "metadata": {},
            }
            store.save_experiment(trial)
            trial2 = dict(trial)
            trial2["status"] = "passed"
            trial2["strategy_version"] = 2
            trial2["results"] = {"ok": True}
            trial2["finished_at"] = utc_now()
            store.save_experiment(trial2)
            loaded = store.list_experiments(strategy_id="s1")[0]
            self.assertNotEqual(int(loaded.get("strategy_version") or 0), 2)

    def test_d14_current_upsert_sql_omits_strategy_version(self) -> None:
        src = inspect.getsource(MarketSimStore.save_experiment)
        # ON CONFLICT update list must not include strategy_version today.
        conflict = src.split("ON CONFLICT", 1)[1]
        self.assertNotIn("strategy_version=excluded.strategy_version", conflict)

    @unittest.expectedFailure  # D14 — fixed in Phase T4
    def test_d14_desired_append_only_or_version_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            self.assertTrue(
                hasattr(store, "append_trial") or hasattr(store, "count_trials")
            )


# ---------------------------------------------------------------------------
# D15 — Strategy memory disconnected from multi engine
# ---------------------------------------------------------------------------


class D15MemoryCharacterization(unittest.TestCase):
    def test_d15_current_multi_prepare_memory_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            engine = MultiAgentEngine(store)
            run = _run(
                agents=[
                    {
                        "agent_id": "a1",
                        "role": "analyst",
                        "authority": {"may_order": True},
                    }
                ],
            )
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertEqual(len(state.memory._entries), 0)

    def test_d15_current_prepare_does_not_hydrate(self) -> None:
        src = inspect.getsource(MultiAgentEngine.prepare)
        self.assertNotIn("list_strategy_memories", src)

    @unittest.expectedFailure  # D15 — fixed in Phase T7
    def test_d15_desired_prepare_hydrates_from_store(self) -> None:
        src = inspect.getsource(MultiAgentEngine.prepare)
        self.assertIn("list_strategy_memories", src)


# ---------------------------------------------------------------------------
# D16 — Gateway bypass / capabilities matrix bug
# ---------------------------------------------------------------------------


class D16GatewayCharacterization(unittest.TestCase):
    def test_d16_current_crypto_paper_available_with_local_paper(self) -> None:
        src = inspect.getsource(build_market_capabilities)
        self.assertIn('crypto_paper = "AVAILABLE"', src)
        self.assertIn("local_paper", src)

    def test_d16_current_routes_bypass_gateway(self) -> None:
        routes_path = Path(__file__).resolve().parents[1] / "routes" / "market_sim.py"
        src = routes_path.read_text(encoding="utf-8")
        self.assertNotIn("ExecutionGateway", src)
        self.assertNotIn("capability_catalog", src)

    @unittest.expectedFailure  # D16 — fixed in Phase T4A (mutation routes via Gateway)
    def test_d16_desired_side_effect_routes_dispatch_via_gateway(self) -> None:
        routes_path = Path(__file__).resolve().parents[1] / "routes" / "market_sim.py"
        src = routes_path.read_text(encoding="utf-8")
        self.assertIn("ExecutionGateway", src)
        self.assertIn("capability_catalog", src)


# ---------------------------------------------------------------------------
# D17 — Agents are not LLM agents / missions interrupted
# ---------------------------------------------------------------------------


class D17AgentsCharacterization(unittest.TestCase):
    def test_d17_current_deliberation_uses_dsl_not_llm(self) -> None:
        from Data.modules.market_sim import deliberation

        src = Path(deliberation.__file__).read_text(encoding="utf-8")
        self.assertIn("evaluate_strategy", src)
        self.assertNotIn("AgentRuntime", src)

    def test_d17_current_fleet_maps_specialists_to_generic(self) -> None:
        from Data.modules.agents.fleet import AgentFleetService

        src = inspect.getsource(AgentFleetService._execution_kind)
        self.assertIn("GENERIC", src)

    def test_d17_current_reconcile_interrupts_active(self) -> None:
        from Data.modules.agents.fleet import AgentFleetService

        src = inspect.getsource(AgentFleetService.reconcile)
        self.assertIn("INTERRUPTED", src)

    @unittest.expectedFailure  # D17 — fixed in Phase T8
    def test_d17_desired_trading_execution_kind(self) -> None:
        from Data.modules.agents.types import AgentKind

        names = [m.name for m in AgentKind]
        self.assertIn("TRADING", names)


# ---------------------------------------------------------------------------
# D18 — Paper trading shared wallet / no RiskGuard
# ---------------------------------------------------------------------------


class D18PaperCharacterization(unittest.TestCase):
    def test_d18_current_local_broker_single_wallet(self) -> None:
        b = LocalPaperBroker()
        self.assertEqual(float(b.wallet.cash), 100_000.0)
        b.wallet.cash = money(50_000)
        self.assertEqual(float(b.wallet.cash), 50_000.0)

    def test_d18_current_paper_place_order_source_has_no_riskguard(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.paper_place_order)
        self.assertNotIn("RiskGuard", src)
        self.assertIn("kill", src.lower())

    def test_d18_current_start_paper_session_resets_shared_cash(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.start_paper_session)
        self.assertIn("wallet.cash", src)

    @unittest.expectedFailure  # D18 — fixed in Phase T9
    def test_d18_desired_per_session_wallets(self) -> None:
        b = LocalPaperBroker()
        self.assertTrue(hasattr(b, "wallet_for_session") or hasattr(b, "sessions"))


# ---------------------------------------------------------------------------
# D19 — Secrets / network bypass
# ---------------------------------------------------------------------------


class D19SecretsCharacterization(unittest.TestCase):
    def test_d19_current_alpaca_reads_os_environ(self) -> None:
        import Data.modules.market_sim.paper_broker as pb

        text = Path(pb.__file__).read_text(encoding="utf-8")
        self.assertIn("os.environ", text)
        self.assertIn("LEVIATHAN_ALPACA_PAPER", text)
        # HTTP path is ProviderExecutionClient when job_runtime is bound,
        # but credentials still come from env — not SecretsBroker.
        self.assertNotIn("SecretsBroker", text)

    def test_d19_current_live_guard_reads_env(self) -> None:
        import Data.modules.market_sim.trading_live_guard as lg
        from Data.modules.market_sim.trading_live_guard import LiveTradingGuard

        text = Path(lg.__file__).read_text(encoding="utf-8")
        self.assertIn("os.environ", text)
        status = LiveTradingGuard().public_status()
        self.assertEqual(status.get("LIVE_TRADING_AVAILABLE"), "BLOCKED")

    def test_d19_current_providers_use_urllib_directly(self) -> None:
        import Data.modules.market_sim.providers as providers

        text = Path(providers.__file__).read_text(encoding="utf-8")
        self.assertIn("urllib", text)
        self.assertNotIn("SecretsBroker", text)

    @unittest.expectedFailure  # D19 — fixed in Phase T4C
    def test_d19_desired_alpaca_uses_secrets_broker(self) -> None:
        import Data.modules.market_sim.paper_broker as pb

        text = Path(pb.__file__).read_text(encoding="utf-8")
        self.assertIn("SecretsBroker", text)


# ---------------------------------------------------------------------------
# D20 — Product surface gaps
# ---------------------------------------------------------------------------


class D20ProductSurfaceCharacterization(unittest.TestCase):
    def test_d20_current_orderintent_has_no_limit_price(self) -> None:
        fields = OrderIntent.__dataclass_fields__
        self.assertNotIn("limit_price", fields)
        self.assertNotIn("order_type", fields)
        self.assertTrue(hasattr(OrderType, "LIMIT"))

    def test_d20_current_portfolio_unrealized_pnl_stub(self) -> None:
        p = Portfolio(cash=10_000.0)
        p.position_qty = 2.0
        p.avg_entry = 50.0
        p.equity_curve.append(10_100.0)
        self.assertEqual(p.unrealized_pnl, 0.0)

    def test_d20_current_options_futures_forex_not_implemented(self) -> None:
        caps = build_market_capabilities(
            feature_enabled=True, binance_reachable=True, local_paper=True
        )
        statuses = {m["family"]: m for m in caps["markets"]}
        for family in ("options", "futures", "forex"):
            # InstrumentFamily values may be uppercase/lowercase — match case-insensitively.
            match = next(
                (v for k, v in statuses.items() if family in str(k).lower()),
                None,
            )
            self.assertIsNotNone(match, family)
            assert match is not None
            self.assertEqual(match["HISTORICAL_SIM_AVAILABLE"], "NOT_IMPLEMENTED")

    def test_d20_trading_stub_always_refuses(self) -> None:
        stub = TradingStub()
        result = stub.place_order(symbol="AAPL", side="BUY", quantity=1)
        self.assertFalse(result.accepted)

    @unittest.expectedFailure  # D20 — later phases
    def test_d20_desired_orderintent_carries_order_type_and_limit(self) -> None:
        fields = OrderIntent.__dataclass_fields__
        self.assertIn("order_type", fields)
        self.assertIn("limit_price", fields)


# ---------------------------------------------------------------------------
# D21 — Migration head drift
# ---------------------------------------------------------------------------


class D21MigrationHeadCharacterization(unittest.TestCase):
    def test_d21_current_real_head_tracks_migrations(self) -> None:
        # After Frontier Program F1 (trade orchestras): head is 43+.
        # Characterize against live MIGRATIONS rather than a frozen constant.
        head = MIGRATIONS[-1].version
        self.assertGreaterEqual(head, 43)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[42], "resource_reservations_device_aware")
        self.assertEqual(by_ver[43], "trading_orchestra")
        self.assertEqual(by_ver[44], "trading_causality_data_foundation")
        versions = [m.version for m in MIGRATIONS]
        self.assertEqual(versions, list(range(1, head + 1)))

    def test_d21_current_test_migrations_tracks_head(self) -> None:
        path = Path(__file__).resolve().parent / "test_migrations.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("current_version(conn), head)", text)

    def test_d21_trading_center_migration_exists_at_34(self) -> None:
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[34], "trading_center")
        self.assertEqual(by_ver[16], "market_sim")

    def test_d21_desired_migration_test_matches_real_head(self) -> None:
        # D21 drift (stale assert 32) was fixed on main — desired contract now holds.
        path = Path(__file__).resolve().parent / "test_migrations.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("head = MIGRATIONS[-1].version", text)
        self.assertIn("current_version(conn), head)", text)


# ---------------------------------------------------------------------------
# D22 — Brain retrieval not time-filtered
# ---------------------------------------------------------------------------


class D22BrainAsOfCharacterization(unittest.TestCase):
    # D22 fixed by the Frontier Program (trade orchestras): retrieve() accepts ``as_of``
    # and drops hits whose timestamp is newer than the decision time.

    def test_d22_retrieve_accepts_as_of(self) -> None:
        from Data.modules.market_sim.brain_hooks import BrainFacade

        sig = inspect.signature(BrainFacade.retrieve)
        self.assertIn("as_of", sig.parameters)

    def test_d22_retrieve_source_has_time_filter(self) -> None:
        from Data.modules.market_sim import brain_hooks

        src = inspect.getsource(brain_hooks.BrainFacade.retrieve)
        self.assertIn("as_of", src)

    def test_d22_as_of_drops_future_hits(self) -> None:
        from Data.modules.market_sim.brain_hooks import BrainFacade

        class _Mem:
            def search(self, query: str, *, limit: int = 3) -> list[dict]:
                return [
                    {"id": "old", "created_at": "2024-01-01T00:00:00+00:00"},
                    {"id": "new", "created_at": "2025-01-01T00:00:00+00:00"},
                ]

        facade = BrainFacade(memory=_Mem())
        out = facade.retrieve("q", dependencies=["memory"], as_of="2024-06-01T00:00:00+00:00")
        self.assertEqual([h["id"] for h in out.hits], ["old"])
        self.assertTrue(any("as_of filter dropped 1" in n for n in out.notes))
        unfiltered = facade.retrieve("q", dependencies=["memory"])
        self.assertEqual(len(unfiltered.hits), 2)


# ---------------------------------------------------------------------------
# D23 — Providers: no pagination / urllib / unlabeled adjustment
# ---------------------------------------------------------------------------


class D23ProvidersCharacterization(unittest.TestCase):
    def test_d23_current_binance_caps_at_1000_no_pagination(self) -> None:
        import Data.modules.market_sim.providers as providers

        text = Path(providers.__file__).read_text(encoding="utf-8")
        self.assertIn("min(max(limit, 1), 1000)", text)
        # No pagination loop in the Binance historical fetch body.
        binance_src = inspect.getsource(providers.BinancePublicProvider)
        self.assertIn("1000", binance_src)
        self.assertNotIn("while True", binance_src)

    def test_d23_current_binance_quote_is_last_price_only(self) -> None:
        from Data.modules.market_sim.providers import BinancePublicProvider

        src = inspect.getsource(BinancePublicProvider.fetch_quote)
        self.assertIn("ticker/price", src)
        self.assertNotIn("bid", src.lower())
        self.assertNotIn("ask", src.lower())

    def test_d23_current_csv_local_takes_first_glob(self) -> None:
        from Data.modules.market_sim.providers import CsvLocalProvider

        src = inspect.getsource(CsvLocalProvider)
        self.assertIn("candidates[0]", src)

    @unittest.expectedFailure  # D23 — fixed in Phase T2D
    def test_d23_desired_binance_paginates_beyond_1000(self) -> None:
        from Data.modules.market_sim.providers import BinancePublicProvider

        src = inspect.getsource(BinancePublicProvider)
        self.assertTrue("while True" in src or "pagination" in src.lower())


# ---------------------------------------------------------------------------
# D24 — InstrumentSpec unused / unknown defaults to equity
# ---------------------------------------------------------------------------


class D24InstrumentsCharacterization(unittest.TestCase):
    def test_d24_current_infer_family_defaults_unknown_to_equity(self) -> None:
        from Data.modules.market_sim.instruments import InstrumentFamily, infer_family

        self.assertEqual(infer_family("UNKNOWNXYZ"), InstrumentFamily.EQUITY)

    def test_d24_current_fill_and_risk_do_not_use_instrument_spec(self) -> None:
        fill_src = Path(
            __import__("Data.modules.market_sim.fill_model", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        exec_src = Path(
            __import__("Data.modules.market_sim.execution", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        risk_src = Path(
            __import__("Data.modules.market_sim.risk_guard", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        for src in (fill_src, exec_src, risk_src):
            self.assertNotIn("InstrumentSpec", src)
            self.assertNotIn("spec_for_symbol", src)

    def test_d24_current_qty_quantize_is_8_decimals(self) -> None:
        from Data.modules.market_sim import accounting

        self.assertEqual(accounting.MONEY_QUANT, __import__("decimal").Decimal("0.00000001"))

    @unittest.expectedFailure  # D24 — fixed in Phase T3B
    def test_d24_desired_unknown_family_refused(self) -> None:
        from Data.modules.market_sim.instruments import infer_family

        with self.assertRaises(Exception):
            infer_family("UNKNOWNXYZ")


# ---------------------------------------------------------------------------
# D25 — Worker double-claim race / soft lease
# ---------------------------------------------------------------------------


class D25WorkerClaimCharacterization(unittest.TestCase):
    def test_d25_current_claim_has_no_begin_immediate(self) -> None:
        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertNotIn("BEGIN IMMEDIATE", src)
        self.assertIn("worker_pid", src)
        self.assertIn("SELECT", src)
        self.assertIn("UPDATE", src)

    def test_d25_current_claim_stamps_os_pid(self) -> None:
        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertIn("os.getpid()", src)
        self.assertNotIn("run.worker_pid = 1", src)

    def test_d25_current_script_worker_exists_as_alternate_plane(self) -> None:
        script = Path(__file__).resolve().parents[3] / "scripts" / "market_sim_worker.py"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("from_settings", text)
        self.assertIn("start_background", text)

    @unittest.expectedFailure  # D25 — fixed in Phase T4B
    def test_d25_desired_claim_uses_immediate_transaction(self) -> None:
        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertIn("BEGIN IMMEDIATE", src)


# ---------------------------------------------------------------------------
# D26 — JobRuntime integration only partial / default soft lease
# ---------------------------------------------------------------------------


class D26JobRuntimeCharacterization(unittest.TestCase):
    def test_d26_current_market_sim_advance_is_external_capability(self) -> None:
        from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES

        self.assertIn("market_sim.advance", EXTERNAL_WORKER_CAPABILITIES)

    def test_d26_current_service_has_enqueue_and_soft_daemon(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = Path(svc_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("enqueue_advance", src)
        self.assertIn("start_background", src)
        self.assertIn("LEVIATHAN_MARKET_SIM_RUNNER", src)

    def test_d26_current_worker_process_run_soft_stamps_pid(self) -> None:
        from Data.modules.market_sim import worker as worker_mod

        src = inspect.getsource(worker_mod.MarketSimWorker.process_run)
        self.assertIn("worker_pid", src)

    @unittest.expectedFailure  # D26 — fixed in Phase T4B (default path)
    def test_d26_desired_default_path_is_jobstore_lease(self) -> None:
        from Data.modules.market_sim import worker as worker_mod

        src = Path(worker_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("JobStore", src)
        self.assertIn("heartbeat", src.lower())


# ---------------------------------------------------------------------------
# D27 — UI hard-coded multi-agent create + stale live series
# ---------------------------------------------------------------------------


class D27FrontendGapsCharacterization(unittest.TestCase):
    def test_d27_current_simulatie_hardcodes_four_agents(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "SimulatiePage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertIn("agent-alpha", text)
        self.assertIn("agent-beta", text)
        self.assertIn("agent-risk", text)
        self.assertIn("agent-orch", text)
        self.assertIn("gameMode: \"individual_competition\"", text)
        self.assertIn("useState(42)", text)

    def test_d27_current_live_state_oldest_first_limits(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.run_live_state)
        self.assertIn("fill_limit", src)
        self.assertIn("message_limit", src)
        # Store loaders use ASC LIMIT — oldest N, not tail.
        fill_src = inspect.getsource(MarketSimStore.list_fills)
        eq_src = inspect.getsource(MarketSimStore.list_equity)
        self.assertIn("ASC", fill_src)
        self.assertIn("ASC", eq_src)

    def test_d27_current_ui_slices_equity_tail_window(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "SimulatiePage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertIn("equity.slice(-60)", text)

    @unittest.expectedFailure  # D27 — fixed in Phase T10A
    def test_d27_desired_simulatie_exposes_run_builder_options(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "SimulatiePage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertIn("initialCash", text)
        self.assertIn("engine", text)
        self.assertNotIn("agent-alpha", text)


# ---------------------------------------------------------------------------
# D28 — Weak tests
# ---------------------------------------------------------------------------


class D28WeakTestsCharacterization(unittest.TestCase):
    def test_d28_current_determinism_window_is_short_fixture_slice(self) -> None:
        path = Path(__file__).resolve().parent / "test_market_sim.py"
        text = path.read_text(encoding="utf-8")
        # Determinism test uses a ~4-day window on the ~100-bar fixture, not multi-year.
        self.assertIn('start_ts="2024-01-01T00:00:00+00:00"', text)
        self.assertIn('end_ts="2024-01-05T00:00:00+00:00"', text)
        self.assertIn("test_deterministic_replay_same_fills", text)

    def test_d28_current_demo_accepts_running(self) -> None:
        path = Path(__file__).resolve().parent / "test_trading_center.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("RUNNING", text)
        self.assertIn("COMPLETED", text)

    def test_d28_current_experiments_use_hand_typed_metrics(self) -> None:
        path = Path(__file__).resolve().parent / "test_trading_center.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("total_return_pct", text)
        self.assertIn("complete_experiment", text)

    @unittest.expectedFailure  # D28 — strengthened across fixing phases / T11
    def test_d28_desired_has_golden_fill_suite(self) -> None:
        golden = Path(__file__).resolve().parent / "fixtures" / "market_sim_golden_fills.json"
        self.assertTrue(golden.is_file())


# ---------------------------------------------------------------------------
# D29 — No per-agent Sharpe / drawdown / CI
# ---------------------------------------------------------------------------


class D29PerAgentEvalCharacterization(unittest.TestCase):
    def test_d29_current_leaderboard_lacks_risk_metrics(self) -> None:
        src = inspect.getsource(MultiAgentEngine._leaderboard)
        self.assertIn("equity", src)
        self.assertIn("realized_pnl", src)
        self.assertIn("fees_paid", src)
        self.assertIn("trades", src)
        self.assertNotIn("sharpe", src.lower())
        self.assertNotIn("drawdown", src.lower())
        self.assertNotIn("confidence", src.lower())

    @unittest.expectedFailure  # D29 — fixed in Phase T1A / T8D
    def test_d29_desired_leaderboard_includes_sharpe(self) -> None:
        src = inspect.getsource(MultiAgentEngine._leaderboard)
        self.assertIn("sharpe", src.lower())


# ---------------------------------------------------------------------------
# D30 — Commit-reveal weaker than claimed
# ---------------------------------------------------------------------------


class D30CommitRevealCharacterization(unittest.TestCase):
    def test_d30_current_info_version_hashes_closes_tail_only(self) -> None:
        from Data.modules.market_sim.commit_reveal import freeze_info_version

        src = inspect.getsource(freeze_info_version)
        self.assertIn("closes_tail", src)
        self.assertIn("closes[-64:]", src)
        self.assertNotIn("memory", src)
        self.assertNotIn("portfolio", src)

    def test_d30_current_multi_engine_pokes_protocol_open(self) -> None:
        src = Path(
            __import__("Data.modules.market_sim.multi_engine", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        self.assertIn("protocol._open = None", src)

    def test_d30_current_risk_veto_mutates_committed_intent_side(self) -> None:
        src = inspect.getsource(MultiAgentEngine._commit_round)
        self.assertIn("d.intent.side = OrderSide.HOLD.value", src)

    @unittest.expectedFailure  # D30 — fixed in Phase T1D
    def test_d30_desired_veto_is_separate_immutable_event(self) -> None:
        src = inspect.getsource(MultiAgentEngine._commit_round)
        self.assertNotIn("d.intent.side = OrderSide.HOLD.value", src)
        self.assertIn("override", src.lower())


# ---------------------------------------------------------------------------
# D31 — Decision cadence implicit / default multi-agent
# ---------------------------------------------------------------------------


class D31CadenceCharacterization(unittest.TestCase):
    def test_d31_current_default_roles_are_trend_mean_risk(self) -> None:
        from Data.modules.market_sim.types import AgentRole, DEFAULT_AGENT_ROLES

        self.assertEqual(
            DEFAULT_AGENT_ROLES,
            (AgentRole.TREND, AgentRole.MEAN_REVERSION, AgentRole.RISK_OFFICER),
        )

    def test_d31_current_create_run_injects_default_agents_when_omitted(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.create_run)
        self.assertIn("DEFAULT_AGENT_ROLES", src)
        self.assertIn("deliberation_every_n", src)
        self.assertIn("if agent_list is None", src)

    def test_d31_current_legacy_alternates_deliberation_and_raw(self) -> None:
        src = inspect.getsource(SimulationEngine.step_once)
        # Legacy: deliberation on every Nth bar, raw strategy otherwise.
        self.assertIn("deliberation_every_n", src)
        self.assertIn("should_deliberate", src)
        self.assertIn("evaluate_strategy", src)

    def test_d31_current_multi_decides_only_every_n(self) -> None:
        src = inspect.getsource(MultiAgentEngine.step_once)
        self.assertIn("deliberation_every_n", src)
        self.assertIn("should_decide", src)

    @unittest.expectedFailure  # D31 — fixed in Phase T1D
    def test_d31_desired_cadence_is_explicit_recorded_param_only(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.create_run)
        # No silent injection of default multi-agent roster when agents omitted.
        self.assertNotIn("DEFAULT_AGENT_ROLES", src)


if __name__ == "__main__":
    unittest.main()
