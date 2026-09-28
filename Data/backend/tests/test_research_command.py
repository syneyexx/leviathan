"""Research Command composition: session lifecycle, paper boundary, public reasoning."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import apply_pending_domain_migrations, domain_schema_version, ensure_domain_schema
from Data.modules.common.database_domains import DatabaseDomain
from Data.modules.market_sim.orchestra.service import TradingOrchestraError, TradingOrchestraService
from Data.modules.market_sim.orchestra.store import OrchestraStore
from Data.modules.market_sim.orchestra.types import NewsFeed, NewsItem
from Data.modules.market_sim.research_command.service import ResearchCommandError, ResearchCommandService


def _orchestra() -> dict:
    return {
        "orchestraId": "orch-1",
        "name": "Desk",
        "mandate": {
            "universe": ["BTCUSD"],
            "paperCapital": 100000,
            "maxSymbolExposurePct": 25,
            "maxGrossExposurePct": 100,
            "perTradeRiskPct": 1,
            "maxOrdersPerDay": 20,
            "maxDrawdownPct": 20,
            "cannotEnableLive": True,
        },
        "mandateFingerprint": "abc",
        "members": [
            {
                "agentId": "agent-1",
                "name": "Desk · News",
                "kind": "trading",
                "role": "news_analyst",
                "enabled": True,
                "health": "ok",
            }
        ],
        "truth": {
            "paper_only": True,
            "live_trading": "BLOCKED",
            "risk_authority": "risk_guard_deterministic",
        },
        "autonomyLevel": "A0",
        "readiness": {"state": "UNMEASURED", "reason": "no sealed run"},
        "decisionStats": {"total": 0, "byStage": {}, "riskRejections": 0},
    }


class FakeTrading:
    def __init__(self, store: OrchestraStore) -> None:
        self.store = store
        self.enabled = True
        self.fleet = object()
        self.decisions: list[dict] = []
        self.missions: list[dict] = []

    def get_orchestra(self, orchestra_id: str) -> dict:
        if orchestra_id != "orch-1":
            raise TradingOrchestraError("ORCHESTRA_NOT_FOUND", orchestra_id, http_status=404)
        return _orchestra()

    def list_orchestras(self) -> list[dict]:
        return [self.get_orchestra("orch-1")]

    def list_missions(self, orchestra_id: str, *, limit: int = 20) -> list[dict]:
        return list(self.missions)

    def list_decisions(self, *, orchestra_id: str | None = None, limit: int = 80) -> list[dict]:
        return list(self.decisions)

    def list_news(self, *, as_of: str | None = None, feed_id: str | None = None, limit: int = 40) -> list[dict]:
        return [item.public_dict() for item in self.store.list_items(as_of=as_of, feed_id=feed_id, limit=limit)]

    def list_signals(self, *, as_of: str | None = None, instrument: str | None = None, limit: int = 40) -> list[dict]:
        return []

    def list_feeds(self) -> list[dict]:
        return [feed.public_dict() for feed in self.store.list_feeds()]

    def summary(self) -> dict:
        return {
            "enabled": True,
            "fleetBound": True,
            "model": "scripted",
            "modelAvailable": False,
            "externalized": False,
            "jobRuntimeBound": False,
            "feeds": 0,
            "feedsEnabled": 0,
        }


class FakePortfolios:
    def __init__(self) -> None:
        self.rows = {
            "pf-paper": {
                "portfolio_id": "pf-paper",
                "name": "Paper book",
                "mode": "PAPER",
                "broker_mode": "local_paper",
                "status": "CREATED",
                "kill_switch": False,
                "base_currency": "USD",
                "cash": "100000",
                "equity": "100000",
                "realized_pnl": "0",
                "settings": {"daily_loss_limit_pct": 4},
            },
            "pf-live": {
                "portfolio_id": "pf-live",
                "name": "Live",
                "mode": "LIVE",
                "broker_mode": "live",
                "status": "CREATED",
                "kill_switch": False,
                "base_currency": "USD",
                "cash": "1",
                "settings": {},
            },
        }
        self.positions: list[dict] = []
        self.stale = False
        self.unrealized = "0"
        self.started: list[str] = []
        self.paused: list[str] = []
        self.flattened: list[str] = []
        self.killed: list[bool] = []

    def get_portfolio(self, portfolio_id: str) -> dict | None:
        row = self.rows.get(portfolio_id)
        return dict(row) if row else None

    def list_portfolios(self, limit: int = 30) -> list[dict]:
        return [dict(row) for row in self.rows.values()]

    def dashboard(self, portfolio_id: str) -> dict:
        row = self.rows[portfolio_id]
        return {
            "portfolio": row,
            "kpis": {
                "total_equity": "100000",
                "cash_balance": "80000" if self.positions else "100000",
                "daily_pnl": "12" if not self.stale else "999",
                "unrealized_pnl": self.unrealized,
                "realized_pnl": "3",
                "available_buying_power": "80000",
                "stale": self.stale,
            },
            "positions": list(self.positions),
            "exposure": {"leverage": 1.2 if self.positions and not self.stale else 0},
            "market_status": {"stale": self.stale, "marks": {}},
            "recent_transactions": [
                {
                    "transaction_id": "tx-1",
                    "symbol": "ETHUSD",
                    "side": "SELL",
                    "qty": "1",
                    "price": "10",
                    "result": "CLOSED",
                    "timestamp": "2024-01-02T00:00:00+00:00",
                }
            ],
        }

    def start(self, portfolio_id: str) -> dict:
        self.started.append(portfolio_id)
        self.rows[portfolio_id]["status"] = "RUNNING"
        return self.rows[portfolio_id]

    def pause(self, portfolio_id: str) -> dict:
        self.paused.append(portfolio_id)
        self.rows[portfolio_id]["status"] = "PAUSED"
        return self.rows[portfolio_id]

    def kill_switch(self, portfolio_id: str, *, armed: bool = True) -> dict:
        self.killed.append(armed)
        self.rows[portfolio_id]["kill_switch"] = armed
        return self.rows[portfolio_id]

    def flatten_all(self, portfolio_id: str) -> dict:
        self.flattened.append(portfolio_id)
        self.positions = []
        return {"flattened": 1, "truth": {"paper_only": True, "not_live_money": True}}


class FakePlane:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.resumed: list[str] = []
        self.labs = {
            "lab-1": {
                "lab_id": "lab-1",
                "name": "Search",
                "status": "CREATED",
                "candidates": [
                    {
                        "candidate_id": "c1",
                        "generation": 1,
                        "strategy_id": "strat-measured",
                        "strategy_version": 2,
                        "status": "TRAIN_COMPLETED",
                        "hypothesis": "Recorded lab hypothesis",
                        "metadata": {"stage_results": {"VAL": {"fitness_score": 0.41}}},
                    }
                ],
            }
        }

    def list_agent_labs(self, *, limit: int = 20) -> list[dict]:
        return list(self.labs.values())

    def get_agent_lab(self, lab_id: str) -> dict:
        if lab_id not in self.labs:
            raise KeyError(lab_id)
        return self.labs[lab_id]

    def get_lab_generations(self, lab_id: str) -> dict:
        return {"current_generation": 1, "generation_summaries": [{"generation": 1, "best_train_fitness": 0.2}]}

    def get_lab_candidates(self, lab_id: str) -> dict:
        return {"candidates": self.labs[lab_id]["candidates"]}

    def start_agent_lab(self, lab_id: str) -> dict:
        self.started.append(lab_id)
        self.labs[lab_id]["status"] = "RUNNING"
        return {"lab_id": lab_id, "status": "RUNNING"}

    def resume_agent_lab(self, lab_id: str) -> dict:
        self.resumed.append(lab_id)
        return {"lab_id": lab_id, "status": "RUNNING"}


class ResearchCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = OrchestraStore(Path(self.tmp.name) / "market.db")
        self.store.initialize()
        self.trading = FakeTrading(self.store)
        self.portfolios = FakePortfolios()
        self.plane = FakePlane()
        self.service = ResearchCommandService(
            store=self.store,
            trading=self.trading,
            portfolios=self.portfolios,
            plane=self.plane,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_start_pause_and_mission_gate(self) -> None:
        started = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper", lab_id="lab-1")
        self.assertEqual(started["session"]["state"], "RUNNING")
        self.assertEqual(started["liveTrading"], "BLOCKED")
        self.assertEqual(self.portfolios.started, ["pf-paper"])
        again = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertTrue(again["idempotent"])
        paused = self.service.pause(session_id=started["session"]["sessionId"])
        self.assertEqual(paused["session"]["state"], "PAUSED")
        self.assertFalse(paused["missionsCancelled"])
        self.assertEqual(self.portfolios.paused, ["pf-paper"])
        with self.assertRaises(TradingOrchestraError) as raised:
            self.service.assert_missions_allowed("orch-1")
        self.assertEqual(raised.exception.code, "SESSION_PAUSED")
        resumed = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertEqual(resumed["session"]["state"], "RUNNING")

    def test_launch_mission_blocker_runs_before_fleet(self) -> None:
        orchestra = TradingOrchestraService(store=self.store, enabled=True)

        def _block(_orchestra_id: str) -> None:
            raise TradingOrchestraError("SESSION_PAUSED", "paused", http_status=409)

        orchestra.mission_blocker = _block
        with self.assertRaises(TradingOrchestraError) as raised:
            orchestra.launch_mission("orch-1", kind="news_digest")
        self.assertEqual(raised.exception.code, "SESSION_PAUSED")

    def test_flatten_is_paper_only_and_idempotent_without_positions(self) -> None:
        started = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        session_id = started["session"]["sessionId"]
        with self.assertRaises(ResearchCommandError) as missing:
            self.service.flatten(session_id=session_id, confirm="")
        self.assertEqual(missing.exception.code, "CONFIRMATION_REQUIRED")
        idle = self.service.flatten(session_id=session_id, confirm="FLATTEN_PAPER")
        self.assertEqual(idle["flattened"], 0)
        self.assertTrue(idle["idempotent"])
        self.assertFalse(idle["calledOwner"])
        self.assertEqual(self.portfolios.flattened, [])
        self.portfolios.positions = [
            {
                "position_id": "pos-1",
                "symbol": "BTCUSD",
                "side": "LONG",
                "qty": "1",
                "avg_entry_price": "10",
                "mark_price": "11",
                "unrealized_pnl": "1",
                "pnl_pct": "10",
                "status": "OPEN",
            }
        ]
        done = self.service.flatten(session_id=session_id, confirm="FLATTEN_PAPER")
        self.assertEqual(self.portfolios.flattened, ["pf-paper"])
        self.assertTrue(done["calledOwner"])
        self.assertEqual(done["liveTrading"], "BLOCKED")
        with self.assertRaises(ResearchCommandError) as live:
            self.service.start(orchestra_id="orch-1", portfolio_id="pf-live")
        self.assertEqual(live.exception.code, "LIVE_MONEY_BLOCKED")

    def test_stale_marks_do_not_become_measured_pnl(self) -> None:
        self.portfolios.stale = True
        self.portfolios.unrealized = "999"
        self.portfolios.positions = [
            {
                "position_id": "pos-1",
                "symbol": "BTCUSD",
                "side": "LONG",
                "qty": "1",
                "avg_entry_price": "10",
                "mark_price": "999",
                "unrealized_pnl": "999",
                "pnl_pct": "99",
                "status": "OPEN",
            }
        ]
        snap = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertEqual(snap["portfolio"]["unrealizedPnl"]["measurement"], "UNMEASURED")
        self.assertEqual(snap["positions"]["open"][0]["pnl"]["measurement"], "UNMEASURED")
        self.assertEqual(snap["positions"]["open"][0]["mark"]["measurement"], "UNMEASURED")
        blob = json.dumps(snap["positions"])
        self.assertNotIn("999", blob)
        closed = snap["positions"]["closed"][0]
        self.assertEqual(closed["pnl"]["measurement"], "UNMEASURED")
        self.assertEqual(closed["state"], "CLOSED")

    def test_public_stream_drops_private_reasoning_and_future_news(self) -> None:
        self.store.insert_items(
            [
                NewsItem(
                    item_id="past",
                    feed_id="feed",
                    source="wire",
                    url="https://example.test/past",
                    title="Past",
                    summary="",
                    content_hash="h-past",
                    published_at="2020-01-01T00:00:00+00:00",
                    fetched_at="2020-01-01T00:00:00+00:00",
                    available_at="2020-01-01T00:00:00+00:00",
                ),
                NewsItem(
                    item_id="future",
                    feed_id="feed",
                    source="wire",
                    url="https://example.test/future",
                    title="FUTURE_LEAK",
                    summary="",
                    content_hash="h-future",
                    published_at="2099-01-01T00:00:00+00:00",
                    fetched_at="2099-01-01T00:00:00+00:00",
                    available_at="2099-01-01T00:00:00+00:00",
                ),
            ]
        )
        self.trading.decisions = [
            {
                "decisionId": "d1",
                "orchestraId": "orch-1",
                "missionId": None,
                "agentId": "agent-1",
                "role": "signal_analyst",
                "stage": "proposal",
                "asOf": "2024-01-01T00:00:00+00:00",
                "payload": {
                    "instrument": "BTCUSD",
                    "direction": "long",
                    "rationale": "public rationale",
                    "chain_of_thought": "SECRET_COT_SHOULD_NOT_LEAK",
                    "hidden_reasoning": "SECRET_HIDDEN",
                },
                "parentDecisionId": None,
                "modelId": None,
                "promptArtifactId": "prompt-private",
                "outputArtifactId": "output-private",
                "mandateFingerprint": "abc",
                "createdAt": "2024-01-01T00:00:00+00:00",
            }
        ]
        snap = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper", as_of="2024-06-01T00:00:00+00:00")
        blob = json.dumps(snap)
        self.assertNotIn("SECRET_COT_SHOULD_NOT_LEAK", blob)
        self.assertNotIn("SECRET_HIDDEN", blob)
        self.assertNotIn("prompt-private", blob)
        self.assertNotIn("FUTURE_LEAK", blob)
        self.assertIn("public rationale", blob)
        titles = [item["title"] for item in snap["watching"]["news"]]
        self.assertEqual(titles, ["Past"])
        self.assertEqual(snap["thesis"]["source"], "trade_orchestra_proposal")
        self.assertEqual(snap["thesis"]["confidence"]["measurement"], "UNMEASURED")
        self.assertEqual(snap["truth"]["liveTrading"], "BLOCKED")
        self.assertEqual(snap["truth"]["privateChainOfThought"], "NOT_EXPOSED")

    def test_empty_thesis_and_no_fake_generation(self) -> None:
        snap = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertFalse(snap["thesis"]["present"])
        self.assertIsNone(snap["thesis"]["primary"])
        self.assertEqual(snap["intent"]["present"], False)
        self.assertEqual(snap["strategyEvolution"]["rows"], [])
        self.assertEqual(snap["strategyEvolution"]["currentGeneration"]["measurement"], "UNMEASURED")
        blob = json.dumps(snap["strategyEvolution"])
        self.assertNotIn("Generation 7", blob)
        self.assertNotIn("Momentum Fractal", blob)
        evolved = self.service.start_evolution(lab_id="lab-1")
        self.assertEqual(evolved["action"], "start_agent_lab")
        self.assertEqual(self.plane.started, ["lab-1"])
        bound = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper", lab_id="lab-1")
        self.assertEqual(bound["strategyEvolution"]["rows"][0]["variant"], "strat-measured")
        self.assertEqual(bound["strategyEvolution"]["rows"][0]["validationScore"]["measurement"], "MEASURED")
        self.assertEqual(bound["strategyEvolution"]["rows"][0]["paperPnl"]["measurement"], "UNMEASURED")
        self.assertEqual(bound["strategyEvolution"]["rows"][0]["generation"], 1)

    def test_agent_estimate_is_not_measured_validation(self) -> None:
        self.trading.decisions = [
            {
                "decisionId": "d1",
                "orchestraId": "orch-1",
                "agentId": "agent-1",
                "role": "signal_analyst",
                "stage": "proposal",
                "asOf": "2024-01-01T00:00:00+00:00",
                "payload": {"instrument": "BTCUSD", "direction": "long", "confidence": 0.42, "rationale": "edge note"},
                "createdAt": "2024-01-01T00:00:00+00:00",
            }
        ]
        snap = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertEqual(snap["thesis"]["confidence"]["measurement"], "AGENT_ESTIMATE")
        self.assertEqual(snap["thesis"]["confidence"]["value"], 0.42)
        self.assertEqual(snap["thesis"]["measuredValidation"]["measurement"], "UNMEASURED")
        self.assertEqual(snap["team"]["members"][0]["telemetry"], "UNMEASURED")
        self.assertNotIn("percent", json.dumps(snap["team"]))

    def test_guardrails_use_mandate_and_not_safe_without_risk_authority(self) -> None:
        snap = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertEqual(snap["guardrails"]["perTradeRiskPct"]["value"], 1)
        self.assertEqual(snap["guardrails"]["dailyLossLimitPct"]["value"], 4)
        self.assertEqual(snap["guardrails"]["liveTrading"], "BLOCKED")
        self.assertEqual(snap["guardrails"]["riskGuard"], "ENABLED")
        self.assertNotEqual(snap["session"]["safety"], "SAFE")
        started = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        running = self.service.snapshot(session_id=started["session"]["sessionId"])
        self.assertEqual(running["session"]["safety"], "SAFE")
        self.assertEqual(running["session"]["state"], "RUNNING")
        broken = dict(_orchestra())
        broken["truth"] = {"paper_only": True, "live_trading": "BLOCKED", "risk_authority": "missing"}

        def _broken(_orchestra_id: str) -> dict:
            return broken

        self.trading.get_orchestra = _broken  # type: ignore[method-assign]
        unsafe = self.service.snapshot(orchestra_id="orch-1", portfolio_id="pf-paper")
        self.assertEqual(unsafe["session"]["safety"], "NOT_SAFE")
        self.assertEqual(unsafe["guardrails"]["riskGuard"], "UNAVAILABLE")

    def test_kill_switch_pauses_without_flatten(self) -> None:
        started = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        armed = self.service.kill_switch(session_id=started["session"]["sessionId"], armed=True)
        self.assertEqual(self.portfolios.killed, [True])
        self.assertFalse(armed["flattened"])
        self.assertEqual(self.portfolios.flattened, [])
        self.assertEqual(armed["session"]["state"], "PAUSED")
        self.assertEqual(armed["liveTrading"], "BLOCKED")

    def test_watch_requires_explicit_reason(self) -> None:
        started = self.service.start(orchestra_id="orch-1", portfolio_id="pf-paper")
        with self.assertRaises(ResearchCommandError) as raised:
            self.service.add_watch(session_id=started["session"]["sessionId"], symbol="ETHUSD", reason="  ")
        self.assertEqual(raised.exception.code, "WATCH_REASON_REQUIRED")
        saved = self.service.add_watch(
            session_id=started["session"]["sessionId"],
            symbol="ethusd",
            reason="Operator added after the digest.",
        )
        symbols = [item["symbol"] for item in saved["session"]["watch"]]
        self.assertIn("ETHUSD", symbols)

    def test_migration_preserves_news_and_is_market_only(self) -> None:
        self.store.upsert_feed(
            NewsFeed(
                feed_id="feed-keep",
                name="Keep",
                url="https://example.test/rss",
                created_at="2024-01-01T00:00:00+00:00",
                updated_at="2024-01-01T00:00:00+00:00",
            )
        )
        path = self.store.db_path
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM schema_migrations WHERE version >= 5")
            conn.execute("DROP TABLE IF EXISTS market_research_command_sessions")
            conn.commit()
        self.assertEqual(domain_schema_version(path), 4)
        applied = apply_pending_domain_migrations(path, DatabaseDomain.MARKET)
        self.assertIn(5, applied)
        self.assertTrue(_table(path, "market_research_command_sessions"))
        with sqlite3.connect(path) as conn:
            name = conn.execute("SELECT name FROM market_news_feeds WHERE feed_id='feed-keep'").fetchone()[0]
        self.assertEqual(name, "Keep")
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control.db"
            ensure_domain_schema(control, DatabaseDomain.CONTROL)
            self.assertFalse(_table(control, "market_research_command_sessions"))


def _table(path: Path, name: str) -> bool:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    return row is not None


class ResearchCommandSourceTests(unittest.TestCase):
    def test_service_does_not_place_live_orders_or_own_a_learner(self) -> None:
        text = (
            Path(__file__).resolve().parents[3] / "Data/modules/market_sim/research_command/service.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("place_live_order", text)
        self.assertNotIn("propose_generation", text)
        self.assertNotIn("research_command.db", text)
        self.assertIn("PortfolioService", text)
        self.assertIn("LIVE_MONEY_BLOCKED", text)


if __name__ == "__main__":
    unittest.main()
