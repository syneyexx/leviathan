"""F5 — Structured public reasoning state (persist / hydrate / candidates)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.store import CognitionStore
from Data.modules.cognition.structured_state import (
    CandidateSummary,
    StructuredReasoningState,
    structured_state_from_mapping,
)
from Data.modules.cognition.types import CognitiveRunStatus


class StructuredStateContractTests(unittest.TestCase):
    def test_round_trip_public_dict(self) -> None:
        state = StructuredReasoningState()
        state.seed_from_goal("What is the capital of France?")
        state.add_claim("Paris is the capital", confidence_band="moderate")
        state.add_evidence_ref("ev-1", kind="knowledge", preview="wiki excerpt")
        state.candidate_summaries = [
            CandidateSummary(0, "Paris", text_chars=5, temperature=0.2, selected=True),
            CandidateSummary(1, "Lyon", text_chars=4, temperature=0.5, selected=False),
        ]
        state.inference_path = "ttc"
        state.last_selection_method = "majority_normalized"
        state.agreement_ratio = 0.67
        public = state.public_dict()
        self.assertEqual(public["schema_version"], "1")
        self.assertTrue(public["truth"]["persistable_public_contract"])
        self.assertTrue(public["truth"]["no_private_cot"])
        restored = structured_state_from_mapping(public)
        self.assertEqual(len(restored.open_questions), 1)
        self.assertEqual(restored.open_questions[0].text, "What is the capital of France?")
        self.assertEqual(len(restored.claims), 1)
        self.assertEqual(len(restored.candidate_summaries), 2)
        self.assertEqual(restored.inference_path, "ttc")
        self.assertEqual(restored.last_selection_method, "majority_normalized")

    def test_ingest_ttc_candidates(self) -> None:
        state = StructuredReasoningState()
        state.ingest_inference_compute(
            {
                "path": "ttc",
                "native_effort_effective": "UNSUPPORTED",
                "reasoning_tokens_status": "UNMEASURED",
                "model_calls_consumed": 3,
                "ttc": {
                    "selection": {
                        "method": "majority_normalized",
                        "chosen_index": 1,
                        "agreement_ratio": 0.6667,
                    },
                    "candidates": [
                        {
                            "index": 0,
                            "text_preview": "A",
                            "text_chars": 1,
                            "temperature": 0.2,
                            "ok": True,
                        },
                        {
                            "index": 1,
                            "text_preview": "B",
                            "text_chars": 1,
                            "temperature": 0.4,
                            "ok": True,
                        },
                        {
                            "index": 2,
                            "text_preview": "C",
                            "text_chars": 1,
                            "temperature": 0.6,
                            "ok": False,
                            "error": "empty_response",
                        },
                    ],
                },
            }
        )
        self.assertEqual(state.inference_path, "ttc")
        self.assertEqual(state.model_calls_consumed, 3)
        self.assertEqual(state.last_selection_method, "majority_normalized")
        self.assertEqual(len(state.candidate_summaries), 3)
        selected = [c for c in state.candidate_summaries if c.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].index, 1)
        blob = str(state.public_dict()).lower()
        self.assertNotIn("chain of thought", blob)

    def test_never_fabricates_answer_on_empty(self) -> None:
        state = StructuredReasoningState()
        state.answer_open_questions("")
        self.assertEqual(state.open_questions, [])
        state.seed_from_goal("Q?")
        state.answer_open_questions(None)
        self.assertEqual(state.open_questions[0].status, "open")


class RuntimeStructuredStateTests(unittest.TestCase):
    def test_submit_seeds_and_status_exposes_contract(self) -> None:
        runtime = CognitiveRuntime(enabled=True, shadow=True, iterative=False)
        status = runtime.submit("Explain gravity briefly", run=False)
        self.assertIn("reasoning_state", status)
        rs = status["reasoning_state"]
        self.assertEqual(rs["schema_version"], "1")
        self.assertGreaterEqual(rs["counts"]["open_questions"], 1)
        self.assertTrue(status["truth"]["reasoning_state_is_public_contract"])

    def test_persist_and_hydrate_reasoning_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cognition.db"
            MigrationRunner(db).apply_all()
            store = CognitionStore(db_path=db)

            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                store=store,
            )
            status = runtime.submit("What causes tides?", run=False)
            run_id = status["run_id"]
            live = runtime._require(run_id)
            live.reasoning_state.ingest_inference_compute(
                {
                    "path": "ttc",
                    "reasoning_tokens_status": "UNMEASURED",
                    "model_calls_consumed": 2,
                    "ttc": {
                        "selection": {
                            "method": "longest_valid",
                            "chosen_index": 0,
                            "agreement_ratio": 1.0,
                        },
                        "candidates": [
                            {
                                "index": 0,
                                "text_preview": "Moon gravity",
                                "text_chars": 12,
                                "ok": True,
                                "temperature": 0.2,
                            }
                        ],
                    },
                }
            )
            live.status = CognitiveRunStatus.SHADOW
            runtime._persist_update(live, final=True)

            runtime._runs.clear()
            hydrated = runtime._hydrate_from_store(run_id)
            self.assertEqual(hydrated.reasoning_state.inference_path, "ttc")
            self.assertEqual(len(hydrated.reasoning_state.candidate_summaries), 1)
            self.assertEqual(
                hydrated.reasoning_state.candidate_summaries[0].text_preview,
                "Moon gravity",
            )
            self.assertGreaterEqual(len(hydrated.reasoning_state.open_questions), 1)
            public = hydrated.public_status()
            self.assertEqual(public["reasoning_state"]["last_selection_method"], "longest_valid")
            store.close()


if __name__ == "__main__":
    unittest.main()
