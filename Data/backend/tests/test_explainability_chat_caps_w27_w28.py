"""Wave 27/28 — candidate explainability + READ-only market_sim chat capabilities."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.function_runtime.types import SideEffect
from Data.modules.market_sim.candidate_explainability import explain_candidate
from Data.modules.market_sim.chat_capabilities import (
    CHAT_READ_CAPABILITY_IDS,
    bind_market_sim_plane,
    handle_lab_best_candidate,
    handle_lab_hypotheses,
    handle_lab_status,
    handle_lessons_summary,
    handle_paper_drift,
    register_market_sim_chat_capabilities,
)


class ExplainCandidateTests(unittest.TestCase):
    def test_explain_from_candidate_dict_evidence_only(self) -> None:
        candidate = {
            "candidate_id": "cand_1",
            "strategy_id": "s1",
            "strategy_version": 2,
            "generation": 3,
            "proposal_method": "MUTATE",
            "hypothesis": "momentum persists in BTC 1h",
            "parent_refs": [{"candidate_id": "cand_0"}],
            "status": "REJECTED",
            "metadata": {
                "hypothesis_id": "hyp_1",
                "critic_notes": [{"text": "overfit risk on VAL", "verdict": "WEAK"}],
                "stage_results": {
                    "TRAIN": {"status": "completed", "accepted": True, "fitness_score": 0.4},
                    "VAL": {
                        "status": "completed",
                        "accepted": False,
                        "fitness_score": 0.1,
                        "acceptance": {"failures": ["min_trades"]},
                    },
                    "ROBUSTNESS": {
                        "status": "completed",
                        "accepted": False,
                        "verdict": {
                            "results": [
                                {
                                    "perturbation_id": "fee_cost_up",
                                    "accepted": False,
                                    "reason": "fee stress fail",
                                }
                            ]
                        },
                    },
                },
            },
        }
        learning = {
            "learning_run_id": "lr_1",
            "candidates": [candidate],
            "metadata": {
                "qualification_required": True,
                "institutional_qualified": False,
                "ready_for_shadow": False,
                "note": "learner_cannot_set_authoritative_qualified",
            },
        }
        out = explain_candidate(
            store=None,
            candidate_id="cand_1",
            candidate=candidate,
            learning_run=learning,
        )
        self.assertTrue(out["present"])
        self.assertEqual(out["hypothesisId"], "hyp_1")
        self.assertEqual(out["method"], "MUTATE")
        self.assertEqual(out["parents"][0]["candidate_id"], "cand_0")
        self.assertEqual(out["splitThatKilled"]["split"], "VAL")
        self.assertTrue(out["criticNotes"])
        self.assertEqual(out["costSensitivity"]["measurement"], "MEASURED")
        kinds = {b["kind"] for b in out["sealedQualificationBlockers"]}
        self.assertIn("QUALIFICATION_REQUIRED", kinds)
        self.assertEqual(out["liveTrading"], "BLOCKED")
        self.assertTrue(out["truth"]["no_llm_storytelling"])

    def test_explain_missing_candidate(self) -> None:
        out = explain_candidate(store=None, candidate_id="missing", learning_run={"candidates": []})
        self.assertFalse(out["present"])
        self.assertEqual(out["error"], "CANDIDATE_NOT_FOUND")


class ChatCapabilityRegistrationTests(unittest.TestCase):
    def test_capabilities_registered_read_only(self) -> None:
        catalog = build_default_catalog()
        registered = register_market_sim_chat_capabilities(catalog)
        for cap_id in CHAT_READ_CAPABILITY_IDS:
            self.assertIn(cap_id, registered)
            cap = catalog.get(cap_id)
            self.assertIsNotNone(cap)
            self.assertEqual(cap.side_effects, (SideEffect.READ,))
            self.assertEqual((cap.metadata or {}).get("live_trading"), "BLOCKED")
            self.assertFalse((cap.metadata or {}).get("mutations"))
            self.assertEqual((cap.metadata or {}).get("execution_class"), "INLINE_SAFE")

    def test_handlers_return_structured_data_without_writing(self) -> None:
        plane = SimpleNamespace(
            get_agent_lab=MagicMock(
                return_value={
                    "lab_id": "lab_1",
                    "name": "Discovery",
                    "status": "RUNNING",
                    "run_mode": "AUTONOMOUS_DISCOVERY",
                    "learning_run_id": "lr_1",
                    "learning": {"stage": "TRAIN", "status": "RUNNING", "current_generation": 2},
                    "metadata": {"hypothesis_id": "hyp_1", "run_mode": "AUTONOMOUS_DISCOVERY"},
                    "lessons": [
                        {"lesson_id": "les_1", "claim": "fees matter", "trust": "AGENT_PROPOSED"}
                    ],
                }
            ),
            get_lab_candidates=MagicMock(
                return_value={
                    "lab_id": "lab_1",
                    "learning_run_id": "lr_1",
                    "qualified_candidate": None,
                    "best_validation_candidate": "cand_1",
                    "best_train_candidate": "cand_1",
                    "candidates": [
                        {
                            "candidate_id": "cand_1",
                            "strategy_id": "s1",
                            "strategy_version": 1,
                            "generation": 1,
                            "proposal_method": "SEED",
                            "hypothesis": "h",
                            "status": "PROPOSED",
                            "metadata": {"stage_results": {"VAL": {"fitness_score": 0.2, "accepted": True}}},
                        }
                    ],
                }
            ),
            list_lab_hypotheses=MagicMock(
                return_value={
                    "lab_id": "lab_1",
                    "hypotheses": [
                        {
                            "hypothesis_id": "hyp_1",
                            "status": "TESTING",
                            "trust": "UNDER_TEST",
                            "statement": "edge exists",
                        }
                    ],
                    "count": 1,
                }
            ),
            get_lab_lessons=MagicMock(
                return_value={
                    "lab_id": "lab_1",
                    "lessons": [
                        {"lesson_id": "les_1", "claim": "fees matter", "trust": "AGENT_PROPOSED"}
                    ],
                }
            ),
            list_paper_deployments=MagicMock(
                return_value=[
                    {
                        "deployment_id": "dep_1",
                        "status": "RUNNING",
                        "mode": "autonomous_paper",
                        "strategy_asset_id": "s1",
                        "metadata": {"portfolio_id": "pf_1"},
                        "loop": {
                            "drift_review": {
                                "status": "DRIFT_DETECTED",
                                "continualResearch": {
                                    "ticketId": "drift-1",
                                    "reason": "paper_forward_metric_drift",
                                    "researchQuestion": "why drifted?",
                                },
                            }
                        },
                    }
                ]
            ),
            get_paper_deployment=MagicMock(),
        )
        bind_market_sim_plane(plane)
        try:
            status = handle_lab_status(lab_id="lab_1")
            self.assertEqual(status["status"], "OK")
            self.assertEqual(status["runMode"], "AUTONOMOUS_DISCOVERY")
            self.assertFalse(status["wrote"])
            self.assertEqual(status["liveTrading"], "BLOCKED")

            best = handle_lab_best_candidate(lab_id="lab_1")
            self.assertEqual(best["best"]["candidateId"], "cand_1")
            self.assertFalse(best["wrote"])

            hyps = handle_lab_hypotheses(lab_id="lab_1")
            self.assertEqual(hyps["activeCount"], 1)
            self.assertFalse(hyps["wrote"])

            lessons = handle_lessons_summary(lab_id="lab_1")
            self.assertEqual(lessons["count"], 1)
            self.assertFalse(lessons["wrote"])

            drift = handle_paper_drift(portfolio_id="pf_1")
            self.assertEqual(drift["deploymentCount"], 1)
            self.assertEqual(drift["driftTickets"][0]["ticketId"], "drift-1")
            self.assertFalse(drift["wrote"])
            self.assertEqual(drift["liveTrading"], "BLOCKED")

            # Handlers must not mutate plane owners.
            plane.get_agent_lab.assert_called()
            self.assertFalse(hasattr(plane, "upsert_agent_lab") and plane.upsert_agent_lab.called)  # type: ignore[attr-defined]
        finally:
            bind_market_sim_plane(None)


if __name__ == "__main__":
    unittest.main()
