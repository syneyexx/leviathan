"""Regression tests for the verified HADES experience feedback loop."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.flight_recorder import record
from gen2.store import Gen2Store
from gen2.verified_experience import retrieve_verified_experiences, training_record_from_experience
from reasoning.chat_context import (
    assemble_chat_context_messages,
    verified_experience_retrieval_enabled,
)


class VerifiedExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "experience.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _verified_success(self, run_id: str = "run-success") -> None:
        record(
            self.store,
            run_id,
            "PLAN",
            {
                "goal": "Fix CMake native install path for HADES",
                "reasoning": "private scratchpad that must never be recalled",
            },
        )
        record(
            self.store,
            run_id,
            "TOOL",
            {"tool_name": "ctest", "ok": True, "path": "native/build/windows-release"},
        )
        record(
            self.store,
            run_id,
            "VERIFY",
            {"passed": True, "summary": "runtime_tests and executor_tests passed"},
        )
        record(
            self.store,
            run_id,
            "TERMINAL",
            {"ok": True, "status": "completed", "summary": "CMake install path corrected"},
        )

    def test_positive_history_requires_explicit_verification(self) -> None:
        record(self.store, "unverified", "PLAN", {"goal": "Fix CMake native install path"})
        record(self.store, "unverified", "TERMINAL", {"ok": True, "status": "completed"})
        self._verified_success()
        hits = retrieve_verified_experiences(self.store, "CMake native install", limit=5)
        ids = {hit["metadata"]["run_id"] for hit in hits}
        self.assertIn("run-success", ids)
        self.assertNotIn("unverified", ids)

    def test_runtime_event_bus_vocabulary_is_learned(self) -> None:
        run_id = "runtime-run"
        self.store.append_run_event(
            run_id=run_id,
            event_type="STEP_STARTED",
            payload={"instruction": "Repair Python C++ bridge serialization", "step_title": "bridge repair"},
        )
        self.store.append_run_event(
            run_id=run_id,
            event_type="TOOL_STATUS",
            payload={"tool_name": "pytest", "status": "completed", "path": "backend/tests"},
        )
        self.store.append_run_event(
            run_id=run_id,
            event_type="VERIFICATION",
            payload={"status": "completed", "summary": "bridge regression tests passed"},
        )
        self.store.append_run_event(
            run_id=run_id,
            event_type="FINAL_OUTCOME",
            payload={"status": "completed", "summary": "Python C++ bridge repaired"},
        )
        hits = retrieve_verified_experiences(self.store, "Python C++ bridge", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["outcome"], "verified_success")
        self.assertIn("Repair Python C++ bridge serialization", hits[0]["content"])

    def test_latest_verification_wins_after_replan(self) -> None:
        run_id = "replanned-run"
        record(self.store, run_id, "PLAN", {"goal": "Repair crawler parser"})
        record(self.store, run_id, "VERIFY", {"passed": False, "summary": "first attempt failed"})
        record(self.store, run_id, "TOOL", {"tool_name": "repair", "ok": True})
        record(self.store, run_id, "VERIFY", {"passed": True, "summary": "second attempt passed"})
        record(self.store, run_id, "TERMINAL", {"ok": True, "status": "completed"})
        hits = retrieve_verified_experiences(self.store, "crawler parser", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["outcome"], "verified_success")
        self.assertIn("second attempt passed", hits[0]["content"])

    def test_failed_latest_verification_overrides_terminal_success(self) -> None:
        run_id = "verification-contradiction"
        record(self.store, run_id, "PLAN", {"goal": "Repair native runtime installer"})
        record(self.store, run_id, "VERIFY", {"passed": False, "summary": "installer regression still failing"})
        record(self.store, run_id, "TERMINAL", {"ok": True, "status": "completed"})
        hits = retrieve_verified_experiences(self.store, "native runtime installer", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["outcome"], "verified_failure")
        self.assertIn("installer regression still failing", hits[0]["content"])

    def test_tool_failure_without_terminal_is_not_promoted(self) -> None:
        record(self.store, "still-running", "PLAN", {"goal": "Repair PDF crawler"})
        record(
            self.store,
            "still-running",
            "TOOL",
            {"tool_name": "pdf_crawl", "ok": False, "error": "temporary parser failure"},
        )
        self.assertEqual(retrieve_verified_experiences(self.store, "PDF crawler", limit=3), [])

    def test_failure_experience_is_recalled_as_warning_evidence(self) -> None:
        run_id = "crawler-failure"
        record(self.store, run_id, "PLAN", {"goal": "Repair PDF crawler no results"})
        record(
            self.store,
            run_id,
            "TOOL",
            {"tool_name": "pdf_crawl", "ok": False, "error": "parser returned zero documents"},
        )
        record(self.store, run_id, "VERIFY", {"passed": False, "summary": "expected documents were missing"})
        record(self.store, run_id, "TERMINAL", {"ok": False, "status": "failed", "error": "verification failed"})
        hits = retrieve_verified_experiences(self.store, "PDF crawler documents", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["outcome"], "verified_failure")
        self.assertIn("parser returned zero documents", hits[0]["content"])
        self.assertIn("Failure class:", hits[0]["content"])

    def test_runtime_error_is_terminal_failure(self) -> None:
        run_id = "runtime-error"
        self.store.append_run_event(
            run_id=run_id,
            event_type="STEP_STARTED",
            payload={"instruction": "Compile native executor"},
        )
        self.store.append_run_event(
            run_id=run_id,
            event_type="ERROR",
            payload={"error": "native executor compile failed"},
        )
        hits = retrieve_verified_experiences(self.store, "native executor compile", limit=3)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["metadata"]["outcome"], "verified_failure")

    def test_secrets_and_hidden_reasoning_are_not_recalled(self) -> None:
        run_id = "secret-run"
        record(
            self.store,
            run_id,
            "PLAN",
            {"goal": "Repair GitHub upload workflow", "chain_of_thought": "never expose this internal trace"},
        )
        record(self.store, run_id, "VERIFY", {"passed": True, "summary": "upload check passed"})
        record(
            self.store,
            run_id,
            "TERMINAL",
            {"ok": True, "status": "completed", "summary": "GitHub upload fixed; api_key=super-secret-value"},
        )
        hits = retrieve_verified_experiences(self.store, "GitHub upload", limit=3)
        self.assertEqual(len(hits), 1)
        rendered = hits[0]["content"]
        self.assertNotIn("never expose this internal trace", rendered)
        self.assertNotIn("super-secret-value", rendered)
        self.assertIn("***REDACTED***", rendered)
        self.assertFalse(hits[0]["metadata"]["hidden_reasoning_stored"])
        self.assertIsNone(hits[0]["reliability"])
        self.assertIsNone(hits[0]["freshness"])

    def test_irrelevant_experiences_are_not_injected(self) -> None:
        self._verified_success()
        self.assertEqual(retrieve_verified_experiences(self.store, "weather tomorrow Amsterdam", limit=3), [])

    def test_generic_stopword_query_does_not_recall_history(self) -> None:
        self._verified_success()
        self.assertEqual(retrieve_verified_experiences(self.store, "Can you please help with this?", limit=3), [])

    def test_chat_path_receives_bounded_experience_context_by_default(self) -> None:
        self._verified_success()
        messages, report, meta = assemble_chat_context_messages(
            system_parts=["System"],
            history=[],
            context_items=[],
            user_text="Can you inspect the CMake native install problem?",
            max_chars=8_000,
            reserve_output_chars=1_000,
            settings={"enable_context_compiler_chat": False},
            gen2_store=self.store,
            goal="CMake native install problem",
            env={},
        )
        self.assertEqual(meta["verified_experience"]["retrieved"], 1)
        self.assertTrue(meta["verified_experience"]["fail_open"])
        system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
        self.assertIn("PRIOR VERIFIED EXPERIENCE", system_text)
        self.assertIn("flight-recorder:run-success", system_text)
        self.assertLessEqual(report.used_chars, report.max_chars)

    def test_chat_path_can_disable_experience_retrieval(self) -> None:
        self._verified_success()
        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["System"],
            history=[],
            context_items=[],
            user_text="CMake native install",
            max_chars=8_000,
            settings={"enable_context_compiler_chat": False, "enable_verified_experience_retrieval": False},
            gen2_store=self.store,
            env={},
        )
        self.assertFalse(meta["verified_experience"]["enabled"])
        self.assertEqual(meta["verified_experience"]["retrieved"], 0)
        self.assertNotIn("PRIOR VERIFIED EXPERIENCE", "\n".join(m["content"] for m in messages))

    def test_process_environment_kill_switch_is_honored(self) -> None:
        with patch.dict("os.environ", {"HADES_VERIFIED_EXPERIENCE_RETRIEVAL": "0"}):
            self.assertFalse(verified_experience_retrieval_enabled({}, env=None))
        with patch.dict("os.environ", {"HADES_VERIFIED_EXPERIENCE_RETRIEVAL": "true"}):
            self.assertTrue(verified_experience_retrieval_enabled({}, env=None))

    def test_chat_path_fails_open_when_experience_store_is_unavailable(self) -> None:
        class BrokenStore:
            def connection(self):
                raise RuntimeError("store unavailable")

        messages, _report, meta = assemble_chat_context_messages(
            system_parts=["System"],
            history=[],
            context_items=[],
            user_text="normal question",
            max_chars=4_000,
            settings={"enable_context_compiler_chat": False},
            gen2_store=BrokenStore(),
            env={},
        )
        self.assertEqual(meta["verified_experience"]["error"], "RuntimeError")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "normal question")

    def test_future_training_record_contains_no_reasoning_trace(self) -> None:
        self._verified_success()
        item = retrieve_verified_experiences(self.store, "CMake install", limit=1)[0]
        record_out = training_record_from_experience(item)
        self.assertTrue(record_out["verified"])
        self.assertFalse(record_out["contains_chain_of_thought"])
        self.assertEqual(record_out["run_id"], "run-success")


if __name__ == "__main__":
    unittest.main()
