"""W23/W26/W28 — qualification API, learning honesty, forward evidence policy."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.market_sim import build_market_sim_router
from Data.modules.market_sim.institutional_core.assurance import (
    FORBIDDEN_OWNER_CLASS_NAMES,
    scan_forbidden_owner_classes,
    scan_qualification_authority_uniqueness,
)
from Data.modules.market_sim.learning_runtime import _finalize_qualified
from Data.modules.market_sim.learning_types import LearningObjectiveSpec, StrategyLearningRun
from Data.modules.market_sim.paper_forward_drift import (
    ForwardEvidencePolicy,
    classify_drift,
    evaluate_forward_evidence,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


class ForwardEvidencePolicyW26Tests(unittest.TestCase):
    def test_five_observations_never_pass(self) -> None:
        policy = ForwardEvidencePolicy()
        out = evaluate_forward_evidence(
            policy=policy,
            closed_trades=5,
            observations=5,
            elapsed_seconds=60.0,
            effective_sample_size=5,
        )
        self.assertNotEqual(out["state"], "PASS")
        self.assertFalse(out["passed"])
        self.assertEqual(out["state"], "INSUFFICIENT_HISTORY")
        self.assertIn("MIN_OBSERVATIONS", out["blockers"])
        self.assertTrue(out["truth"]["five_steps_alone_never_pass"])

    def test_classify_drift_insufficient_not_forced(self) -> None:
        out = classify_drift(sample_size=1, alpha_drifted=True, min_sample_size=5)
        self.assertEqual(out["class"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(out["auto_disable"])
        self.assertTrue(out["truth"]["no_single_sample_auto_disable"])

    def test_classify_execution_drift_when_measured(self) -> None:
        out = classify_drift(
            sample_size=40,
            execution_gap_bps=50.0,
            max_execution_gap_bps=10.0,
            alpha_drifted=False,
        )
        self.assertEqual(out["class"], "EXECUTION_DRIFT")
        self.assertFalse(out["auto_disable"])


class LearningFinalizeHonestyW28Tests(unittest.TestCase):
    def test_finalize_sets_institutional_qualified_false(self) -> None:
        store = SimpleNamespace(
            upsert_learning_run=MagicMock(side_effect=lambda row: row),
            get_agent_lab=MagicMock(return_value=None),
        )
        plane = SimpleNamespace(store=store, _emit_event=MagicMock())
        run = StrategyLearningRun(
            learning_run_id="lr_test_1",
            strategy_id="s1",
            objective_spec=LearningObjectiveSpec(objective_id="obj_test"),
            metadata={},
        )
        out = _finalize_qualified(plane, run, "cand_abc")
        meta = out["metadata"]
        self.assertEqual(meta["lab_finalist"], "cand_abc")
        self.assertFalse(meta["institutional_qualified"])
        self.assertTrue(meta["qualification_required"])
        self.assertFalse(meta["ready_for_shadow"])
        self.assertEqual(meta["note"], "learner_cannot_set_authoritative_qualified")
        self.assertEqual(out["qualified_candidate"], "cand_abc")
        self.assertNotIn("qualification_id", meta)
        events = [c.args[0] for c in plane._emit_event.call_args_list]
        self.assertIn("strategy.finalist_found", events)
        self.assertIn("strategy.qualified", events)


class AssuranceForbiddenW23Tests(unittest.TestCase):
    def test_forbidden_includes_qualification_v2_aliases(self) -> None:
        for name in (
            "QualificationAuthorityV2",
            "QualificationEngineV2",
            "StatsV2",
            "SecondQualificationAuthority",
        ):
            self.assertIn(name, FORBIDDEN_OWNER_CLASS_NAMES)

    def test_scan_detects_forbidden_qualification_v2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "evil.py"
            bad.write_text(
                "class QualificationAuthorityV2:\n    pass\n",
                encoding="utf-8",
            )
            scan = scan_forbidden_owner_classes([root])
            self.assertFalse(scan["ok"])
            names = {h.get("className") for h in scan["hits"]}
            self.assertIn("QualificationAuthorityV2", names)

    def test_qualification_authority_uniqueness_canonical_only(self) -> None:
        market_sim = Path(__file__).resolve().parents[2] / "modules" / "market_sim"
        scan = scan_qualification_authority_uniqueness([market_sim])
        self.assertTrue(scan["ok"], scan)
        self.assertEqual(len(scan["canonical"]), 1)
        self.assertFalse(scan["duplicates"])
        # AST sanity: forbidden names are not defined as classes in tree
        tree = ast.parse((market_sim / "qualification.py").read_text(encoding="utf-8"))
        class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        self.assertIn("QualificationAuthority", class_names)
        self.assertNotIn("QualificationAuthorityV2", class_names)


class QualificationServiceApiW23Tests(unittest.TestCase):
    def test_reproduce_incomplete_provenance_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MarketSimStore(Path(td) / "m.db")
            store.initialize()
            store.save_experiment(
                {
                    "trial_id": "exp_incomplete",
                    "strategy_id": "s1",
                    "strategy_version": 1,
                    "hypothesis": "h",
                    "proposer_agent_id": "a1",
                    "data_hash": "",
                    "fingerprint": "fp1",
                    "status": "passed",
                    "config": {},
                    "split": {},
                    "results": {},
                    "acceptance_criteria": {},
                    "seed": 7,
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            )
            from Data.modules.market_sim.data_store import MarketDataStore
            from Data.modules.market_sim.service import MarketSimControlPlane

            markets = Path(td) / "markets"
            markets.mkdir()
            plane = MarketSimControlPlane(
                store=store,
                data=MarketDataStore(store, markets),
                enabled=True,
            )
            out = plane.reproduce_experiment("exp_incomplete")
            self.assertFalse(out["reproduced"])
            self.assertFalse(out["match"])
            self.assertIn("REPRODUCIBILITY_INCOMPLETE", out["blockers"])

            with self.assertRaises(MarketSimError) as ctx:
                plane.reproduce_experiment("missing_exp")
            self.assertEqual(ctx.exception.code, "EXPERIMENT_NOT_FOUND")

    def test_create_qualification_run_rejects_caller_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MarketSimStore(Path(td) / "m.db")
            store.initialize()
            from Data.modules.market_sim.data_store import MarketDataStore
            from Data.modules.market_sim.service import MarketSimControlPlane

            markets = Path(td) / "markets"
            markets.mkdir()
            plane = MarketSimControlPlane(
                store=store,
                data=MarketDataStore(store, markets),
                enabled=True,
            )
            with self.assertRaises(MarketSimError) as ctx:
                plane.create_qualification_run(
                    strategy_id="s1",
                    strategy_version=1,
                    strategy_hash="s" * 64,
                    source_id="src1",
                    dataset_hash="d" * 64,
                    git_sha="a" * 40,
                    code_version="1.0.0",
                    seed=1,
                    trial_family_id="fam1",
                    extra={"passed": True},
                    enqueue=False,
                )
            self.assertEqual(ctx.exception.code, "CALLER_BOOLEAN_NOT_AUTHORITY")

    def test_qualification_routes_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = MarketSimStore(Path(td) / "m.db")
            store.initialize()
            from Data.modules.market_sim.data_store import MarketDataStore
            from Data.modules.market_sim.service import MarketSimControlPlane

            markets = Path(td) / "markets"
            markets.mkdir()
            plane = MarketSimControlPlane(
                store=store,
                data=MarketDataStore(store, markets),
                enabled=True,
            )
            app = FastAPI()
            app.include_router(build_market_sim_router(plane))
            client = TestClient(app)

            missing = client.get("/api/market-sim/qualification-runs/does-not-exist")
            self.assertEqual(missing.status_code, 404)

            bad = client.post(
                "/api/market-sim/qualification-runs",
                json={
                    "strategyId": "s1",
                    "strategyVersion": 1,
                    "strategyHash": "s" * 64,
                    "sourceId": "src1",
                    "datasetHash": "d" * 64,
                    "gitSha": "a" * 40,
                    "codeVersion": "1.0.0",
                    "seed": 1,
                    "trialFamilyId": "fam1",
                    "extra": {"qualified": True},
                    "enqueue": False,
                    "allowInlineDev": False,
                },
            )
            self.assertEqual(bad.status_code, 400)

            created = client.post(
                "/api/market-sim/qualification-runs",
                json={
                    "strategyId": "s1",
                    "strategyVersion": 1,
                    "strategyHash": "s" * 64,
                    "sourceId": "src1",
                    "datasetHash": "d" * 64,
                    "gitSha": "a" * 40,
                    "codeVersion": "1.0.0",
                    "seed": 1,
                    "trialFamilyId": "fam1",
                    "featurePipelineHash": "f" * 64,
                    "executionModelHash": "e" * 64,
                    "costModelHash": "c" * 64,
                    "riskModelHash": "r" * 64,
                    "sizingModelHash": "z" * 64,
                    "splitManifestHash": "m" * 64,
                    "datasetId": "ds1",
                    "datasetVersionId": "dsv1",
                    "enqueue": False,
                    "allowInlineDev": False,
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            body = created.json()["qualification"]
            qid = body["qualification_id"]
            self.assertTrue(qid)
            # No job_runtime → warning / queued semantics, not silent PASS
            self.assertIn(body.get("status") or body.get("state"), {"CREATED", "QUEUED"})

            got = client.get(f"/api/market-sim/qualification-runs/{qid}")
            self.assertEqual(got.status_code, 200)
            gates = client.get(f"/api/market-sim/qualification-runs/{qid}/gates")
            self.assertEqual(gates.status_code, 200)
            cancel = client.post(f"/api/market-sim/qualification-runs/{qid}/cancel")
            self.assertEqual(cancel.status_code, 200)

            cert_reject = client.post(
                "/api/market-sim/datasets/ds1/certification/evaluate",
                json={
                    "datasetVersionId": "v1",
                    "datasetHash": "h" * 64,
                    "certified": True,
                },
            )
            self.assertEqual(cert_reject.status_code, 400)

            risk = client.get("/api/market-sim/portfolios/pf-missing/strategy-risk")
            self.assertEqual(risk.status_code, 200)
            self.assertEqual(risk.json()["state"], "UNMEASURED")


if __name__ == "__main__":
    unittest.main()
