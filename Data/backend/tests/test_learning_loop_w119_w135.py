"""W119–W135 learning loop: StrategyMemory ↔ Brain ↔ Orchestra ↔ Paper ↔ Postmortem.

Deterministic end-to-end. Mocks only external LLM/network.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from Data.backend.migrations import MigrationRunner
from Data.modules.agents import AgentDefinitionKind, AgentFleetService, AgentFleetStore, AgentRuntime
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.market_sim.experiments import build_strategy_memory_record
from Data.modules.market_sim.orchestra import Mandate, MissionKind, TradingOrchestraService
from Data.modules.market_sim.orchestra.executors import (
    ExecutionContext,
    run_execution_agent,
    run_risk_officer,
)
from Data.modules.market_sim.orchestra.model_adapter import ScriptedTradingModel, UnavailableTradingModel
from Data.modules.market_sim.orchestra.store import OrchestraStore, utc_now
from Data.modules.market_sim.orchestra.types import DecisionRecord
from Data.modules.market_sim.role_knowledge import RoleAwareTradingKnowledge
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.trading_brain import TradingBrainAdapter, TradingRetrievalRequest


def _csv(path: Path, n: int = 60) -> None:
    lines = ["timestamp,open,high,low,close,volume"]
    price = 100.0
    for i in range(n):
        price += 0.5
        day = 1 + i // 24
        hour = i % 24
        lines.append(
            f"2024-01-{day:02d}T{hour:02d}:00:00+00:00,{price},{price + 1},{price - 1},{price + 0.2},1000"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeData:
    def __init__(self, sources):
        self._sources = sources

    def list_sources(self, limit: int = 1000):
        return self._sources

    def absolute_path_for(self, source):
        return Path(source.path)


class _Src:
    def __init__(self, symbol: str, path: Path):
        self.symbol = symbol
        self.timeframe = "1h"
        self.status = "ready"
        self.path = str(path)


class _FakePlane:
    def __init__(self, sources, store: MarketSimStore, portfolios: Any | None = None):
        self.data = _FakeData(sources)
        self.store = store
        self.portfolios = portfolios


class _Memory:
    def __init__(self):
        self.records = []

    def create(self, **kwargs):
        self.records.append(kwargs)
        return {"memory_id": f"mem-{len(self.records)}"}


class _PaperPortfolio:
    """Minimal paper portfolio router — still RiskGuard-gated via caller."""

    def __init__(self):
        self.orders: list[dict[str, Any]] = []
        self._pid = "pf-paper-1"
        self._rows = [
            {
                "portfolio_id": self._pid,
                "orchestra_id": None,
                "mode": "PAPER",
                "broker_mode": "local_paper",
                "cash": 50_000,
                "equity": 50_000,
            }
        ]

    def list_portfolios(self, *, limit: int = 50):
        return list(self._rows)[:limit]

    def get_portfolio(self, portfolio_id: str):
        for r in self._rows:
            if r["portfolio_id"] == portfolio_id:
                return dict(r)
        raise KeyError(portfolio_id)

    def create_portfolio(self, **kwargs):
        row = {
            "portfolio_id": self._pid,
            "orchestra_id": kwargs.get("orchestra_id"),
            "mode": "PAPER",
            "broker_mode": kwargs.get("broker_mode") or "local_paper",
            "cash": float(kwargs.get("initial_equity") or 50_000),
            "equity": float(kwargs.get("initial_equity") or 50_000),
        }
        self._rows = [row]
        return row

    def place_order(self, portfolio_id, **kwargs):
        if kwargs.get("broker_mode") in ("live", "live_broker"):
            raise RuntimeError("LIVE_MONEY_BLOCKED")
        order = {
            "order_id": f"ord-{len(self.orders)+1}",
            "status": "filled",
            "avg_price": 110.0,
            "price": 110.0,
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side"),
            "qty": kwargs.get("qty"),
            "decision_id": kwargs.get("decision_id"),
        }
        self.orders.append({"portfolio_id": portfolio_id, **kwargs, "order": order})
        return {"order": order, "portfolio": self.get_portfolio(portfolio_id)}


class LearningLoopW135Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "lev.db"
        MigrationRunner(self.db).apply_all()
        self.ms_store = MarketSimStore(self.db)
        self.orch_store = OrchestraStore(self.db)
        self.csv = self.root / "BTCUSD_1h.csv"
        _csv(self.csv)
        self.memory = _Memory()
        self.paper = _PaperPortfolio()
        self.plane = _FakePlane([_Src("BTCUSD", self.csv)], self.ms_store, portfolios=self.paper)

        def _lister(*, as_of_ts=None, strategy_id=None, limit=50):
            return self.ms_store.list_strategy_memories(
                strategy_id=strategy_id, as_of_ts=as_of_ts, limit=limit
            )

        self.adapter = TradingBrainAdapter(strategy_memory_lister=_lister)
        self.role_knowledge = RoleAwareTradingKnowledge(self.adapter)
        gateway = ExecutionGateway(catalog=build_default_catalog())
        self.fleet = AgentFleetService(
            AgentFleetStore(self.db), AgentRuntime(gateway=gateway, agents_enabled=True)
        )
        self.fleet.initialize(seed_defaults=True)
        self.service = TradingOrchestraService(
            store=self.orch_store,
            market_plane=self.plane,
            model=UnavailableTradingModel(),
            memory=self.memory,
            role_knowledge=self.role_knowledge,
            trading_brain_adapter=self.adapter,
            enabled=True,
        )
        self.service.bind_fleet(self.fleet)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_w135_negative_memory_to_orchestra_paper_postmortem_loop(self) -> None:
        # --- C) Sim experiment bad regime → durable StrategyMemory (negative) ---
        learned_at = "2024-01-01T12:00:00+00:00"
        mem = build_strategy_memory_record(
            strategy_id="mom-bad-regime",
            strategy_version=1,
            outcome_summary="rejected: drawdown 40% in down_high regime — momentum failure",
            rejected=True,
            available_at=learned_at,
            created_at=learned_at,
            trial_id="trial-bad-1",
            features={"regime": "down_high", "trend": "down", "volatility": "high"},
            applicability={"regimes": ["down_high"], "trends": ["down"]},
            origin="complete_experiment",
            epistemic_state="REJECTED",
            # TRAIN-era negative memory remains adaptive-retrievable; holdout/sealed is not.
            validation_stage="train",
        )
        self.ms_store.save_strategy_memory(mem)
        mid = mem["memory_id"]

        # PIT: before available_at → invisible
        early = self.adapter.retrieve(
            TradingRetrievalRequest(
                query="momentum down_high regime failure",
                decision_as_of="2024-01-01T00:00:00+00:00",
                max_hits=5,
            ),
            prefer_negative=True,
        )
        self.assertTrue(early.miss or all(h.document_id != mid for h in early.hits))

        # --- A) TradingBrainAdapter retrieves StrategyMemory with provenance ---
        later_as_of = "2024-01-03T00:00:00+00:00"
        result = self.adapter.retrieve(
            TradingRetrievalRequest(
                query="momentum down_high regime failure rejected",
                decision_as_of=later_as_of,
                regime="down_high",
                max_hits=5,
            ),
            prefer_negative=True,
        )
        self.assertFalse(result.miss)
        hit = next(h for h in result.hits if h.document_id == mid)
        self.assertTrue(hit.rejected)
        self.assertTrue(hit.contradictory)
        self.assertEqual(hit.origin, "complete_experiment")
        self.assertEqual(hit.epistemic_state, "REJECTED")
        self.assertEqual(hit.validation_stage, "train")
        self.assertEqual(hit.strategy_id, "mom-bad-regime")
        self.assertEqual(hit.available_at, learned_at)

        # Critic/Risk surface negative experience
        critic_payload = self.role_knowledge.retrieve_for_role(
            "critic",
            "challenge this attractive momentum backtest",
            decision_as_of=later_as_of,
            regime="down_high",
        )
        self.assertGreaterEqual(critic_payload["negativeExperienceCount"], 1)
        self.assertIn(mid, critic_payload["evidenceRefs"])

        # --- B) Orchestra decision path binds evidence refs ---
        def _responder(messages, role):
            if role == "signal_analyst":
                return {
                    "instrument": "BTCUSD",
                    "direction": "long",
                    "confidence": 0.85,
                    "horizon": "days",
                    "rationale": "trend up despite prior regime failures",
                    "featureRefs": ["sma10"],
                }
            if role == "critic":
                return {
                    "verdict": "weaken",
                    "counterargument": "prior rejected momentum in down_high",
                    "riskFlags": ["prior_negative_experience"],
                    "confidenceAdjustment": -0.05,
                }
            if role == "postmortem_agent":
                return {
                    "claim": "respect prior rejected momentum regimes",
                    "evidenceRefs": [],
                    "appliesTo": ["BTCUSD", "down_high"],
                    "confidence": 0.4,
                }
            return {}

        self.service.bind_model(ScriptedTradingModel(responder=_responder))
        desk = self.service.create_orchestra(
            {"name": "Learn Desk", "mandate": {"universe": ["BTCUSD"], "paperCapital": 50_000}}
        )
        oid = desk["orchestraId"]
        self.paper._rows[0]["orchestra_id"] = oid

        mission = self.service.launch_mission(oid, kind="deliberation_round", as_of=later_as_of)
        self.assertEqual(mission["status"], "completed", mission)
        result = mission["result"]
        self.assertEqual(result["liveTrading"], "BLOCKED")
        row = result["instruments"][0]
        self.assertTrue(row.get("allowed"), row)
        decisions = {
            d["decisionId"]: d
            for d in self.service.list_decisions(mission_id=mission["missionId"], limit=100)
        }
        critique = decisions[row["critique"]]
        risk = decisions[row["risk"]]
        intent = decisions[row["intent"]]

        self.assertIn("evidenceRefs", critique["payload"])
        self.assertTrue(
            mid in (critique["payload"].get("evidenceRefs") or [])
            or mid in (risk["payload"].get("evidenceRefs") or []),
            msg=f"expected {mid} in critique/risk evidenceRefs; critique={critique['payload'].get('evidenceRefs')} risk={risk['payload'].get('evidenceRefs')}",
        )
        self.assertTrue(risk["payload"].get("knowledgeIsNotAuthority"))
        self.assertEqual(risk["payload"].get("authority"), "risk_guard_deterministic")
        self.assertIn("expectation", risk["payload"])

        # Paper path through mandate+RiskGuard (mock portfolio)
        self.assertTrue(intent["payload"].get("routed"), intent["payload"])
        self.assertEqual(intent["payload"].get("liveTrading"), "BLOCKED")
        self.assertIn(
            intent["payload"].get("status"),
            {"paper_routed_filled", "paper_routed", "paper_routed_blocked"},
        )
        if intent["payload"].get("status") == "paper_routed_filled":
            self.assertIn("predictionError", intent["payload"])
            pe = intent["payload"]["predictionError"]
            self.assertIn("expectedReturnSign", pe)
            self.assertIn("signAgreement", pe)

        # --- D) Postmortem → AGENT_PROPOSED lesson → StrategyMemory ---
        # Clear model budget: rebind for postmortem
        self.service.bind_model(ScriptedTradingModel(responder=_responder))
        pm = self.service.launch_mission(oid, kind="post_mortem", as_of=later_as_of)
        self.assertEqual(pm["status"], "completed", pm)
        lesson = pm["result"]["lesson"]
        self.assertEqual(lesson["trust"], "agent_proposed")
        self.assertEqual(lesson["epistemicState"], "AGENT_PROPOSED")
        self.assertFalse(lesson.get("historicalDecisionsRewritten", True))
        self.assertTrue(lesson.get("evidenceRefs"))
        self.assertTrue(lesson.get("memoryId") or lesson.get("strategyMemoryId"))

        # Subsequent retrieval sees the postmortem lesson (as_of >= available_at when learned)
        smid = lesson.get("strategyMemoryId")
        self.assertTrue(smid, lesson)
        rows = self.ms_store.list_strategy_memories(limit=20)
        lesson_row = next((r for r in rows if r["memory_id"] == smid), None)
        self.assertIsNotNone(lesson_row)
        self.assertEqual(lesson_row["metadata"].get("epistemic_state"), "AGENT_PROPOSED")
        self.assertEqual(lesson_row["metadata"].get("origin"), "orchestra_postmortem")
        after = lesson_row["available_at"]
        retrieved = self.role_knowledge.retrieve_for_role(
            "postmortem",
            "lessons from prior rejected trials orchestra postmortem",
            decision_as_of=after,
        )
        refs = retrieved.get("evidenceRefs") or []
        self.assertTrue(
            smid in refs
            or any(
                c.get("citation", {}).get("documentId") == smid
                for c in retrieved.get("citations") or []
            ),
            msg={"refs": refs, "smid": smid, "citations": retrieved.get("citations")},
        )

    def test_f_memory_brain_cannot_bypass_riskguard_or_live(self) -> None:
        """F) Knowledge/memory cannot call unsafe execution; RiskGuard still gates."""
        adapter = TradingBrainAdapter()
        # Adapter has no place_order / execute — advisory only.
        self.assertFalse(hasattr(adapter, "place_order"))
        self.assertFalse(hasattr(adapter, "execute"))
        rk = RoleAwareTradingKnowledge(adapter)
        self.assertFalse(hasattr(rk, "place_order"))

        # RiskGuard rejects oversized intent even if "brain says buy".
        from Data.modules.market_sim.accounting import WalletLedger
        from Data.modules.market_sim.orchestra.types import DecisionRecord
        from decimal import Decimal

        ctx = ExecutionContext(
            orchestra_id="o-bypass",
            mission_id=None,
            mandate=Mandate.from_dict(
                {
                    "universe": ["BTCUSD"],
                    "paperCapital": 10_000,
                    "maxSymbolExposurePct": 1.0,
                    "perTradeRiskPct": 0.1,
                    "maxOrdersPerDay": 1,
                }
            ),
            as_of="2024-01-03T00:00:00+00:00",
            mission_kind=MissionKind.DELIBERATION_ROUND,
            model=UnavailableTradingModel(),
            store=self.orch_store,
            role_knowledge=self.role_knowledge,
            paper_router=lambda intent: (_ for _ in ()).throw(RuntimeError("should_not_route_if_blocked")),
        )
        agent = type("A", (), {"agent_id": "risk-1"})()
        proposal = DecisionRecord(
            decision_id="dec-prop",
            orchestra_id="o-bypass",
            mission_id=None,
            agent_id="sig",
            role="signal_analyst",
            stage="proposal",
            as_of=ctx.as_of,
            payload={
                "instrument": "BTCUSD",
                "direction": "long",
                "confidence": 0.99,
                "rationale": "brain said so",
                "evidenceRefs": ["fake-memory"],
            },
            parent_decision_id=None,
            model_id=None,
            prompt_artifact_id=None,
            output_artifact_id=None,
            mandate_fingerprint=ctx.mandate.fingerprint(),
            created_at=utc_now(),
        )
        wallet = WalletLedger(wallet_id="w", owner_id="o", owner_kind="paper", cash=Decimal("10000"))
        risk = run_risk_officer(ctx, agent, proposal=proposal, critique=None, wallet=wallet, price=100.0)
        # Either blocked by risk or sized tiny — never live, and paper_router not required if HOLD.
        self.assertEqual(risk.payload.get("authority"), "risk_guard_deterministic")
        self.assertTrue(risk.payload.get("knowledgeIsNotAuthority"))
        intent = run_execution_agent(ctx, agent, risk=risk)
        self.assertEqual(intent.payload.get("liveTrading"), "BLOCKED")
        if not risk.payload.get("allowed"):
            self.assertEqual(intent.payload.get("status"), "no_order")
            self.assertFalse(intent.payload.get("routed"))


class StrategyMemoryBrainArrowTests(unittest.TestCase):
    def test_complete_experiment_style_memory_has_provenance(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            learned = "2024-06-01T00:00:00+00:00"
            entry = build_strategy_memory_record(
                strategy_id="s1",
                strategy_version=2,
                outcome_summary="accepted on holdout",
                rejected=False,
                available_at=learned,
                origin="complete_experiment",
                epistemic_state="MEASURED",
                validation_stage="holdout",
                features={"regime": "up_low"},
            )
            store.save_strategy_memory(entry)
            rows = store.list_strategy_memories(as_of_ts=learned, limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["metadata"]["origin"], "complete_experiment")
            self.assertFalse(rows[0]["rejected"])
            # Future leakage guard
            self.assertEqual(store.list_strategy_memories(as_of_ts="2020-01-01T00:00:00+00:00"), [])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
