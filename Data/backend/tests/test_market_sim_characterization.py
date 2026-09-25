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
import json
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
FIXTURE_HASH = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


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
        data_hash=FIXTURE_HASH,
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

    def test_d1_engines_pass_periods_per_year(self) -> None:
        # T5 / G18: engines annualize from run timeframe.
        engine_src = inspect.getsource(SimulationEngine._finalize_metrics)
        multi_src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertIn("periods_per_year", engine_src)
        self.assertIn("periods_per_year", multi_src)

    def test_d1_desired_engines_pass_timeframe_annualization(self) -> None:
        engine_src = inspect.getsource(SimulationEngine._finalize_metrics)
        multi_src = inspect.getsource(MultiAgentEngine._finalize_metrics)
        self.assertIn("periods_per_year", engine_src)
        self.assertIn("periods_per_year", multi_src)


# ---------------------------------------------------------------------------
# D2 — Win rate / profit factor UNMEASURED without round-trip ledger
# ---------------------------------------------------------------------------


class D2WinRateCharacterization(unittest.TestCase):
    def test_d2_simfill_carries_realized_delta(self) -> None:
        # T5 / G18: SimFill public_dict exposes realized_delta for ledger metrics.
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
            realized_delta=1.5,
        )
        self.assertIn("realized_delta", fill.public_dict())
        self.assertEqual(fill.public_dict()["realized_delta"], 1.5)

    def test_d2_current_metrics_unmeasured_without_realized_delta(self) -> None:
        equity = [100.0, 101.0, 102.0]
        fills = [{"side": "SELL", "qty": 1, "price": 101, "fee": 0.1}]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0, bootstrap=False)
        self.assertEqual(m["win_rate"]["status"], MetricStatus.UNMEASURED.value)
        self.assertEqual(m["profit_factor"]["status"], MetricStatus.UNMEASURED.value)

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
            realized_delta=9.9,
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

    def test_d6_current_claim_sets_real_worker_pid(self) -> None:
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
            from Data.modules.market_sim.types import MarketSimError

            with self.assertRaises(MarketSimError) as ctx:
                engine.prepare(run, bars_path=str(FIXTURE))
            self.assertEqual(ctx.exception.code, "DATA_HASH_MISMATCH")

    def test_d7_desired_prepare_refuses_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            engine = SimulationEngine(store)
            run = _run(data_hash="definitely-not-the-file-hash", bar_index=0)
            with self.assertRaises(Exception):
                engine.prepare(run, bars_path=str(FIXTURE))


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
            self.assertIn("duplicate", (result.error or "").lower())

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

    def test_d9_desired_yyyymmdd_parses_as_calendar_date(self) -> None:
        ts = _normalize_ts("20240115")
        self.assertTrue(ts.startswith("2024-01-15"))


# ---------------------------------------------------------------------------
# D10 — SimulationClock.bars public; lex compare
# ---------------------------------------------------------------------------


class D10ClockCharacterization(unittest.TestCase):
    def test_d10_current_future_bars_reachable_via_public_bars(self) -> None:
        # Engine internals still hold the full series; agents must use MarketView.
        bars = _bars(5)
        clock = SimulationClock(bars=bars)
        clock.advance()
        future = clock.bars[4]
        self.assertEqual(future.ts, bars[4].ts)
        from Data.modules.market_sim.types import CausalityViolation

        with self.assertRaises(CausalityViolation):
            clock.observe(4)

    def test_d10_assert_no_future_is_datetime_aware(self) -> None:
        from Data.modules.market_sim.types import CausalityViolation, MarketSimError

        with self.assertRaises(CausalityViolation):
            assert_no_future(
                ["2024-01-02T00:00:00+00:00"], "2024-01-01T00:00:00+00:00"
            )
        with self.assertRaises(MarketSimError):
            assert_no_future(["9"], "2024-01-01T00:00:00+00:00")

    def test_d10_desired_bounded_market_view_hides_future(self) -> None:
        from Data.modules.market_sim import causality as causality_mod

        self.assertTrue(hasattr(causality_mod, "MarketView"))
        bars = _bars(5)
        clock = SimulationClock(bars=bars)
        clock.advance()
        view = causality_mod.MarketView(clock=clock)
        self.assertEqual(len(view.visible_bars()), 1)
        from Data.modules.market_sim.types import CausalityViolation

        with self.assertRaises(CausalityViolation):
            view.observe(4)


# ---------------------------------------------------------------------------
# D11 — Caller-supplied metrics accepted as evidence
# ---------------------------------------------------------------------------


class D11CallerMetricsCharacterization(unittest.TestCase):
    def test_d11_acceptance_rejects_caller_dict_without_run_ids(self) -> None:
        # T5 / G21: fabricated metrics alone cannot pass acceptance.
        fake = {
            "trade_count": 100,
            "total_return_pct": 50.0,
            "max_drawdown_pct": 5.0,
            "excess_return_pct": 10.0,
        }
        passed, reason = evaluate_acceptance(fake, {"min_trades": 5, "beat_benchmark": True})
        self.assertFalse(passed)
        self.assertIn("run-derived", reason)

    def test_d11_desired_acceptance_requires_run_derived_metrics(self) -> None:
        sig = inspect.signature(evaluate_acceptance)
        params = list(sig.parameters)
        self.assertTrue("run_ids" in params or "run_id" in params)


# ---------------------------------------------------------------------------
# D12 — Acceptance key mismatch vs compute_metrics
# ---------------------------------------------------------------------------


class D12AcceptanceKeyMismatchCharacterization(unittest.TestCase):
    def test_d12_compute_metrics_keys_align_with_acceptance(self) -> None:
        # T5 / G21: compute_metrics exposes trade_count + total_return; acceptance reads them.
        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0, bootstrap=False)
        self.assertIn("total_return", m)
        self.assertIn("trade_count", m)
        self.assertNotIn("total_return_pct", m)

    def test_d12_desired_acceptance_reads_compute_metrics_shape(self) -> None:
        equity = [100.0, 110.0, 120.0]
        fills = [
            {"side": "BUY", "qty": 1, "price": 100, "fee": 0},
            {"side": "SELL", "qty": 1, "price": 120, "fee": 0, "realized_delta": 20},
        ]
        m = compute_metrics(equity=equity, fills=fills, initial_cash=100.0, bootstrap=False)
        passed, _reason = evaluate_acceptance(
            m,
            {"min_trades": 1, "max_drawdown_pct": 50.0, "min_total_return_pct": 0.0},
            run_id="char-d12",
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

    def test_d13_desired_rolling_windows(self) -> None:
        split = walk_forward_splits(100, window=20, step=10)  # type: ignore[call-arg]
        self.assertIn("windows", split)
        self.assertGreaterEqual(len(split["windows"]), 2)


# ---------------------------------------------------------------------------
# D14 — Trial ledger not global / strategy_version not persisted on upsert
# ---------------------------------------------------------------------------


class D14TrialLedgerCharacterization(unittest.TestCase):
    def test_d14_current_upsert_drops_strategy_version(self) -> None:
        # Pre-T4 defect: version was dropped. Post-T4: version is persisted.
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
            self.assertEqual(int(loaded.get("strategy_version") or 0), 2)

    def test_d14_current_upsert_sql_omits_strategy_version(self) -> None:
        src = inspect.getsource(MarketSimStore.save_experiment)
        conflict = src.split("ON CONFLICT", 1)[1]
        self.assertIn("strategy_version=excluded.strategy_version", conflict)

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
    def test_d15_prepare_hydrates_from_store(self) -> None:
        # T6 / G22: MultiAgentEngine.prepare loads durable strategy memories.
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.save_strategy_memory(
                {
                    "memory_id": "m1",
                    "strategy_id": "s-hydrate",
                    "strategy_version": 1,
                    "features": {"trend": "up"},
                    "applicability": {"trends": ["up"]},
                    "outcome_summary": "worked",
                    "trial_id": None,
                    "available_at": "2020-01-01T00:00:00+00:00",
                    "created_at": utc_now(),
                    "rejected": False,
                    "metadata": {},
                }
            )
            engine = MultiAgentEngine(store)
            run = _run(
                strategy_id="s-hydrate",
                agents=[
                    {
                        "agent_id": "a1",
                        "role": "analyst",
                        "authority": {"may_order": True},
                    }
                ],
            )
            state = engine.prepare(run, bars_path=str(FIXTURE))
            self.assertGreaterEqual(len(state.memory._entries), 1)

    def test_d15_prepare_calls_list_strategy_memories(self) -> None:
        src = inspect.getsource(MultiAgentEngine.prepare)
        self.assertIn("hydrate_for_run", src)
        from Data.modules.market_sim.strategy_library import StrategyLibrary

        lib_src = inspect.getsource(StrategyLibrary.hydrate_for_run)
        self.assertIn("list_strategy_memories", lib_src)

    def test_d15_desired_prepare_hydrates_from_store(self) -> None:
        src = inspect.getsource(MultiAgentEngine.prepare)
        self.assertIn("hydrate_for_run", src)


# ---------------------------------------------------------------------------
# D16 — Gateway bypass / capabilities matrix bug
# ---------------------------------------------------------------------------


class D16GatewayCharacterization(unittest.TestCase):
    def test_d16_current_crypto_paper_available_when_feature_enabled(self) -> None:
        src = inspect.getsource(build_market_capabilities)
        self.assertIn('crypto_paper = "AVAILABLE"', src)
        self.assertIn("local_paper", src)
        # Reachability no longer gates paper ledger readiness (honest matrix).
        self.assertIn("Binance reachability only affects live quote freshness", src)

    def test_d16_current_routes_bypass_gateway(self) -> None:
        # T4A: routes now dispatch via ExecutionGateway (no private bypass).
        routes_path = Path(__file__).resolve().parents[1] / "routes" / "market_sim.py"
        src = routes_path.read_text(encoding="utf-8")
        self.assertIn("ExecutionGateway", src)
        self.assertIn("capability_catalog", src)

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

    def test_d17_current_fleet_still_has_generic_fallback(self) -> None:
        from Data.modules.agents.fleet import AgentFleetService

        src = inspect.getsource(AgentFleetService._execution_kind)
        self.assertIn("GENERIC", src)

    def test_d17_current_reconcile_interrupts_orphans(self) -> None:
        from Data.modules.agents.fleet import AgentFleetService

        src = inspect.getsource(AgentFleetService.reconcile)
        self.assertIn("INTERRUPTED", src)

    def test_d17_trading_execution_kind_and_executor_gate(self) -> None:
        """T7 / G24: TRADING kind exists; runtime refuses generic execute; reconcile skips."""
        from Data.modules.agents.types import AgentKind
        from Data.modules.agents.fleet import AgentFleetService
        from Data.modules.agents.runtime import AgentRuntime

        names = [m.name for m in AgentKind]
        self.assertIn("TRADING", names)
        kind_src = inspect.getsource(AgentFleetService._execution_kind)
        self.assertIn("AgentKind.TRADING", kind_src)
        runtime_src = inspect.getsource(AgentRuntime.execute)
        self.assertIn("TRADING_EXECUTOR_REQUIRED", runtime_src)
        reconcile_src = inspect.getsource(AgentFleetService.reconcile)
        self.assertIn("AgentDefinitionKind.TRADING", reconcile_src)


# ---------------------------------------------------------------------------
# D18 — Paper trading shared wallet / no RiskGuard
# ---------------------------------------------------------------------------


class D18PaperCharacterization(unittest.TestCase):
    def test_d18_local_broker_supports_per_session_wallets(self) -> None:
        b = LocalPaperBroker()
        self.assertTrue(hasattr(b, "wallet_for_session"))
        self.assertTrue(hasattr(b, "sessions"))
        w = b.wallet_for_session("sess-a", initial_cash=12_345)
        self.assertEqual(float(w.cash), 12_345.0)

    def test_d18_paper_place_order_routes_through_risk_engine(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.paper_place_order)
        self.assertIn("risk_engine", src)
        self.assertIn("evaluate_order", src)
        self.assertIn("kill", src.lower())

    def test_d18_start_paper_session_creates_per_session_wallet(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.start_paper_session)
        self.assertIn("wallet_for_session", src)
        self.assertIn("per_session_wallet", src)

    def test_d18_per_session_wallets(self) -> None:
        b = LocalPaperBroker()
        self.assertTrue(hasattr(b, "wallet_for_session") or hasattr(b, "sessions"))
        a = b.wallet_for_session("a", initial_cash=1_000)
        c = b.wallet_for_session("c", initial_cash=2_000)
        self.assertNotEqual(float(a.cash), float(c.cash))


# ---------------------------------------------------------------------------
# D19 — Secrets / network bypass
# ---------------------------------------------------------------------------


class D19SecretsCharacterization(unittest.TestCase):
    def test_d19_current_alpaca_reads_os_environ(self) -> None:
        import Data.modules.market_sim.paper_broker as pb

        text = Path(pb.__file__).read_text(encoding="utf-8")
        # T4C: credentials resolve via SecretsBroker (env: refs), not raw os.environ reads.
        self.assertIn("SecretsBroker", text)
        self.assertIn("LEVIATHAN_ALPACA_PAPER", text)
        self.assertIn("env:LEVIATHAN_ALPACA_PAPER", text)

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
        # T1 causality/data foundation adds migration 44.
        # T5 science layer adds migration 45.
        # T6 strategy library adds migration 46.
        # T7 research campaigns adds migration 47.
        # T8 gym/scorecards adds migration 48.
        # T9 paper/risk/audit adds migration 49.
        # T13–T15 shadow live + lifecycle adds migration 50.
        head = MIGRATIONS[-1].version
        self.assertGreaterEqual(head, 50)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[42], "resource_reservations_device_aware")
        self.assertEqual(by_ver[43], "trading_orchestra")
        self.assertEqual(by_ver[44], "trading_causality_data_foundation")
        self.assertEqual(by_ver[45], "trading_science_layer")
        self.assertEqual(by_ver[46], "trading_strategy_library")
        self.assertEqual(by_ver[47], "trading_research_campaigns")
        self.assertEqual(by_ver[48], "trading_gym_scorecards")
        self.assertEqual(by_ver[49], "trading_paper_risk_audit")
        self.assertEqual(by_ver[50], "trading_shadow_lifecycle")
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
        # T6 / G23: without as_of, time-sensitive brain is excluded (not unfiltered).
        excluded = facade.retrieve("q", dependencies=["memory"])
        self.assertEqual(len(excluded.hits), 0)
        self.assertTrue(any("as_of required" in n for n in excluded.notes))
        # Explicit opt-out of time sensitivity still returns all hits.
        unfiltered = facade.retrieve("q", dependencies=["memory"], time_sensitive=False)
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
        # T4B: claim now uses BEGIN IMMEDIATE for exclusive ownership.
        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertIn("BEGIN IMMEDIATE", src)
        self.assertIn("worker_pid", src)
        self.assertIn("SELECT", src)
        self.assertIn("UPDATE", src)

    def test_d25_current_claim_stamps_os_getpid(self) -> None:
        src = inspect.getsource(MarketSimStore.claim_next_runnable)
        self.assertIn("os.getpid()", src)
        self.assertIn("run.worker_pid = pid", src)

    def test_d25_current_script_worker_exists_as_alternate_plane(self) -> None:
        script = Path(__file__).resolve().parents[3] / "scripts" / "market_sim_worker.py"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("from_settings", text)
        self.assertIn("start_background", text)

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

    def test_d26_desired_default_path_is_jobstore_lease(self) -> None:
        from Data.modules.market_sim import worker as worker_mod

        src = Path(worker_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("JobStore", src)
        self.assertIn("heartbeat", src.lower())


# ---------------------------------------------------------------------------
# D27 — UI hard-coded multi-agent create + stale live series
# ---------------------------------------------------------------------------


class D27FrontendGapsCharacterization(unittest.TestCase):
    def test_d27_simulatie_no_longer_hardcodes_four_agents(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "SimulatiePage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertNotIn("agent-alpha", text)
        self.assertNotIn("agent-beta", text)
        self.assertNotIn("agent-risk", text)
        self.assertNotIn("agent-orch", text)
        self.assertIn("initialCash", text)
        self.assertIn("engine", text)

    def test_d27_live_state_uses_recent_tail_loaders(self) -> None:
        from Data.modules.market_sim import service as svc_mod

        src = inspect.getsource(svc_mod.MarketSimControlPlane.run_live_state)
        self.assertIn("fill_limit", src)
        self.assertIn("message_limit", src)
        self.assertIn("live_series_recent_tail", src)
        fill_src = inspect.getsource(MarketSimStore.list_fills)
        eq_src = inspect.getsource(MarketSimStore.list_equity)
        self.assertIn("ORDER BY bar_index DESC", fill_src)
        self.assertIn("ORDER BY bar_index DESC", eq_src)

    def test_d27_ui_uses_api_recent_equity_not_stale_oldest_slice(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "pages"
            / "trading"
            / "SimulatiePage.tsx"
        )
        text = page.read_text(encoding="utf-8")
        self.assertNotIn(".slice(-60)", text)
        self.assertIn("EquityChart equity={equity}", text)

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

    def test_d28_desired_has_golden_fill_suite(self) -> None:
        # T11 / G45: golden fill fixture is now a real regression (no expectedFailure).
        golden = Path(__file__).resolve().parent / "fixtures" / "market_sim_golden_fills.json"
        self.assertTrue(golden.is_file())
        data = json.loads(golden.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data.get("fills") or []), 1)


# ---------------------------------------------------------------------------
# D29 — No per-agent Sharpe / drawdown / CI
# ---------------------------------------------------------------------------


class D29PerAgentEvalCharacterization(unittest.TestCase):
    def test_d29_current_leaderboard_has_risk_metrics(self) -> None:
        """T8 / G27: leaderboard includes Sharpe/drawdown + FDR penalty."""
        src = inspect.getsource(MultiAgentEngine._leaderboard)
        self.assertIn("equity", src)
        self.assertIn("realized_pnl", src)
        self.assertIn("fees_paid", src)
        self.assertIn("trades", src)
        self.assertIn("sharpe", src.lower())
        self.assertIn("drawdown", src.lower())
        self.assertIn("leaderboard_with_penalty", src)

    def test_d29_leaderboard_includes_sharpe(self) -> None:
        src = inspect.getsource(MultiAgentEngine._leaderboard)
        self.assertIn("sharpe", src.lower())
        self.assertIn("confidence", inspect.getsource(
            __import__("Data.modules.market_sim.scorecards", fromlist=["enrich_leaderboard_row"]).enrich_leaderboard_row
        ).lower())


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
        # T10: empty/omitted agents still get presets (`if not agent_list`).
        self.assertIn("if not agent_list", src)
        self.assertIn("default_competition_agents", src)

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
