"""Wave 25 / 30 / 31 / 36 — hypothesis identity, control-room projections, paper E2E."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.experiments import (
    HYPOTHESIS_STATUSES,
    MarketHypothesis,
    bind_hypothesis_id,
    market_hypothesis_from_mapping,
    new_market_hypothesis,
    validate_hypothesis_status,
)
from Data.modules.market_sim.institutional_core.control_room import (
    build_control_room_snapshot,
    build_data_plane_projections,
    build_research_projections,
)
from Data.modules.market_sim.institutional_core.persistence import InstitutionalRepository
from Data.modules.market_sim.learning_candidates import proposal_from_spec
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir(exist_ok=True)
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane


class HypothesisIdentityW25Tests(unittest.TestCase):
    def test_status_vocabulary(self) -> None:
        expected = {
            "PROPOSED",
            "TESTING",
            "SUPPORTED",
            "FRAGILE",
            "CONTRADICTED",
            "REJECTED",
            "STALE",
        }
        self.assertEqual(set(HYPOTHESIS_STATUSES), expected)
        for s in expected:
            self.assertEqual(validate_hypothesis_status(s), s)
        with self.assertRaises(ValueError):
            validate_hypothesis_status("PASS")  # MeasurementState ≠ lifecycle
        with self.assertRaises(ValueError):
            validate_hypothesis_status("UNMEASURED")

    def test_dataclass_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MarketSimStore(Path(td) / "lev.db")
            store.initialize()
            hyp = new_market_hypothesis(
                observation="spread widens after funding",
                rationale="inventory pressure",
                mechanism="mean_reversion",
                falsifiable_prediction="zscore>2 then revert within 6h",
                created_by="researcher",
                created_at="2026-01-01T00:00:00+00:00",
                universe=["BTCUSDT"],
                regime_scope=["high_vol"],
                required_data=["ohlcv", "funding"],
                expected_failure_conditions=["regime_shift"],
            )
            self.assertIsInstance(hyp, MarketHypothesis)
            self.assertEqual(hyp.status, "PROPOSED")
            self.assertTrue(hyp.public_dict()["truth"]["status_is_lifecycle_not_measurement"])

            saved = store.save_market_hypothesis(hyp.public_dict())
            loaded = store.get_market_hypothesis(saved["hypothesis_id"])
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["hypothesis_id"], hyp.hypothesis_id)
            self.assertEqual(loaded["status"], "PROPOSED")
            listed = store.list_market_hypotheses(limit=10)
            self.assertTrue(any(h["hypothesis_id"] == hyp.hypothesis_id for h in listed))

    def test_bind_candidate_metadata(self) -> None:
        meta = bind_hypothesis_id({}, "hyp-123")
        self.assertEqual(meta["hypothesis_id"], "hyp-123")
        cand = proposal_from_spec(
            {
                "entry_rules": {"kind": "ma_cross", "fast": 5, "slow": 20},
                "exit_rules": {"kind": "hold"},
                "parameters": {},
                "hypothesis_id": "hyp-abc",
            },
            generation=1,
            strategy_id="s1",
            strategy_version=1,
            method="SEED",
        )
        self.assertEqual(cand.metadata.get("hypothesis_id"), "hyp-abc")
        self.assertEqual(cand.public_dict().get("hypothesis_id"), "hyp-abc")

    def test_from_mapping_roundtrip(self) -> None:
        raw = {
            "hypothesis_id": "h1",
            "parent_hypothesis_id": None,
            "observation": "o",
            "rationale": "r",
            "mechanism": "m",
            "falsifiable_prediction": "p",
            "universe": ["A"],
            "regime_scope": [],
            "required_data": [],
            "expected_failure_conditions": [],
            "created_by": "t",
            "created_at": "t0",
            "status": "TESTING",
            "evidence_refs": ["e1"],
        }
        hyp = market_hypothesis_from_mapping(raw)
        self.assertEqual(hyp.status, "TESTING")
        self.assertEqual(hyp.evidence_refs, ["e1"])


class ControlRoomProjectionsW30Tests(unittest.TestCase):
    def test_bounded_qualification_and_cert_projections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MarketSimStore(Path(td) / "lev.db")
            store.initialize()
            store.create_qualification_run(
                {
                    "qualification_id": "q1",
                    "policy_id": "pol1",
                    "trial_family_id": "tf1",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "strategy_hash": "sh",
                    "source_id": "src",
                    "dataset_hash": "dh",
                    "git_sha": "g",
                    "code_version": "1",
                    "seed": 1,
                    "status": "RUNNING",
                    "decision": None,
                    "blockers": ["LOW_SAMPLE"],
                    "warnings": [],
                    "provenance_hash": "ph",
                    "idempotency_key": "idem-q1",
                }
            )
            store.save_dataset_certification(
                {
                    "certification_id": "cert1",
                    "dataset_id": "ds1",
                    "dataset_version_id": "dv1",
                    "dataset_hash": "dh1",
                    "certification_state": "CERTIFIED",
                    "pit_state": "PASS",
                    "survivorship_state": "PASS",
                    "certification_hash": "ch1",
                }
            )
            research = build_research_projections(store, limit=20)
            self.assertEqual(research["qualificationRunsCount"], 1)
            self.assertEqual(research["qualificationRuns"][0]["qualificationId"], "q1")
            self.assertIn("LOW_SAMPLE", research["rejectionReasons"])
            data = build_data_plane_projections(store, limit=20)
            self.assertEqual(data["certificationCount"], 1)
            self.assertIn("PASS", data["pitStates"])
            snap = build_control_room_snapshot(
                generated_at="2026-01-01T00:00:00+00:00",
                store=store,
            )
            body = snap.public_dict()
            self.assertIn("research", body)
            self.assertIn("dataPlane", body)
            self.assertEqual(body["research"]["qualificationRunsCount"], 1)
            self.assertTrue(body["truth"]["projections_bounded"])
            run = body["research"]["qualificationRuns"][0]
            self.assertIn("blockers", run)
            self.assertIn("LOW_SAMPLE", run["blockers"])
            self.assertIn("updatedAt", run)
            self.assertIn("byImplementation", body["gaps"])
            self.assertEqual(
                sum(body["gaps"]["byImplementation"].values()),
                body["gaps"]["count"],
            )
            self.assertIn("certifiedAt", body["dataPlane"]["certifications"][0])


class ModelRiskPersistenceW31Tests(unittest.TestCase):
    def test_register_execution_model_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = InstitutionalRepository(Path(td) / "lev.db")
            repo.ensure_schema()
            row = repo.register_execution_model_candidate(
                model_id="exec.vwap",
                version="1.0.0",
                owner="trading",
                intended_use="execution",
            )
            self.assertEqual(row["approval_state"], "CANDIDATE")
            loaded = repo.get_model_governance("exec.vwap", "1.0.0")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["approval_state"], "CANDIDATE")
            self.assertEqual(loaded["validation_state"], "UNVALIDATED")


class PaperCalibrationE2EW36Tests(unittest.TestCase):
    def test_paper_order_flatten_zero_exposure_no_live_broker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            live_broker = MagicMock(name="live_broker")
            # Ensure live path is never selected / called
            plane.providers.get.side_effect = lambda pid=None, **kw: (
                (_ for _ in ()).throw(AssertionError("live broker must not be called"))
                if pid in ("live", "live_broker")
                else MagicMock(
                    status=MagicMock(return_value=MagicMock(reachable=True, latency_ms=1)),
                    fetch_quote=MagicMock(
                        return_value={"price": 100.0, "symbol": "BTCUSDT"}
                    ),
                )
            )

            pf = plane.create_portfolio(
                name="W36 Paper E2E",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "max_position_pct": 25,
                    "per_trade_risk_pct": 5,
                    "asset_concentration_pct": 40,
                    "max_symbol_exposure_pct": 40,
                    "max_leverage": 1.0,
                    "max_drawdown_pct": 15,
                },
            )
            pid = pf["portfolio_id"]
            self.assertEqual(pf.get("mode") or "PAPER", "PAPER")
            self.assertNotIn(str(pf.get("broker_mode") or "").lower(), {"live", "live_broker"})

            # Safe limits applied
            self.assertLessEqual(float(pf["settings"]["max_position_pct"]), 25)
            self.assertLessEqual(float(pf["settings"]["max_leverage"]), 1.0)

            plane.start_portfolio(pid)
            filled = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=1.0,
                client_order_id="w36-open-1",
            )
            self.assertEqual(filled["order"]["status"], "filled", filled)
            # RiskGuard path: oversized order must be blocked
            blocked = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=10_000.0,
                client_order_id="w36-oversized",
            )
            self.assertIn(
                str(blocked["order"].get("status") or "").lower(),
                {"blocked", "rejected", "failed"},
                blocked,
            )

            out = plane.portfolio_flatten_all(pid)
            self.assertEqual(out["pause_state"], "PAUSED")
            self.assertTrue(out["kill_switch"])
            self.assertTrue(out["truth"]["paper_only"])
            self.assertEqual(len(out.get("remaining_positions") or []), 0)

            pf2 = plane.get_portfolio(pid)
            self.assertEqual(pf2["status"], "PAUSED")
            self.assertTrue(pf2["kill_switch"])
            meta = dict(pf2.get("metadata") or {})
            self.assertTrue(
                meta.get("flatten_armed")
                or meta.get("no_new_exposure_reason") == "flatten_all"
                or pf2["settings"].get("allow_new_positions") is False
            )

            # Flatten ends no-new-exposure — new BUY refused
            refused = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.1,
                client_order_id="w36-after-flatten",
            )
            self.assertEqual(refused.get("code"), "NO_NEW_EXPOSURE")
            self.assertIn("no_new_exposure", str(refused["order"].get("reject_reason") or ""))

            # Live broker creation still blocked
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_portfolio(name="Live", broker_mode="live_broker")
            self.assertIn("LIVE", str(ctx.exception.code).upper())
            live_broker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
