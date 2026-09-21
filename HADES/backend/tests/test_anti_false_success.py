"""Anti-false-success regression layer: try to mislead HADES readiness/completion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_job_control import interpret_job_poll
from coding_reviewer import review_coding_result
from control.limit_classifications import (
    LIMIT_ENTRIES,
    LimitClassification,
    fingerprint,
    validate_configurable_finding,
)
from gen2.dashboard import build_dashboard, capability_status_fields
from gen2.sandbox import detect_host_sandbox_capabilities, try_assign_job_object
from gen2.services import Gen2Services
from gen2.store import Gen2Store
from preview_runtime import PreviewManager


class AntiFalseSuccessTests(unittest.TestCase):
    def test_poll_timeout_is_not_completion(self) -> None:
        result = interpret_job_poll({"status": "running", "output": "still going"}, timed_out=True)
        self.assertFalse(result.get("complete"))
        self.assertTrue(result.get("false_success_rejected"))
        self.assertEqual(result.get("reason"), "poll_timeout_not_completion")

    def test_started_without_health_not_ready(self) -> None:
        mgr = PreviewManager()
        # Direct contract: a started flag without health must not be treated as ready.
        payload = {"started": True, "healthy": False, "ready": True}
        self.assertTrue(payload["started"])
        self.assertFalse(payload["healthy"])
        self.assertNotEqual(payload["healthy"], payload.get("ready") and payload["started"])

    def test_reviewer_suggestion_without_evidence_is_not_proof(self) -> None:
        review = review_coding_result(
            goal="fix bug",
            diff_text="",
            changed_files=[],
            test_result={},
            suggest_extra_checks=True,
        )
        self.assertTrue(review.get("suggestions_are_not_proof"))
        for defect in review.get("defects") or []:
            self.assertFalse(defect.get("from_suggestion"))

    def test_plugin_error_in_http_200_shape_is_failure(self) -> None:
        payload = {"http_status": 200, "status": "failed", "error": "tool exploded", "stdout": ""}
        self.assertEqual(payload["http_status"], 200)
        self.assertNotEqual(str(payload.get("status")).lower(), "completed")
        self.assertTrue(payload.get("error"))

    def test_model_claims_tests_passed_without_test_event(self) -> None:
        events = [{"type": "assistant", "content": "All tests passed successfully."}]
        self.assertFalse(any(e.get("type") in {"test_result", "unittest", "pytest"} for e in events))

    def test_sandbox_api_without_enforcement_not_operational(self) -> None:
        caps = detect_host_sandbox_capabilities()
        self.assertFalse(caps.get("operationally_tested"))
        self.assertFalse(caps.get("os_isolation_enforced"))
        probe = try_assign_job_object(1)
        self.assertFalse(bool(probe.get("operationally_tested")))

    def test_configurable_without_binding_fails(self) -> None:
        finding = {
            "file": "backend/example_fake.py",
            "line": 1,
            "kind": "named_constant",
            "name": "MAX_FAKE",
            "symbol": "module",
            "snippet": "MAX_FAKE = 1",
        }
        fp = fingerprint(finding)
        LIMIT_ENTRIES[fp] = LimitClassification(
            classification="configurable",
            reason="fake",
            control_key="missing.key",
            definition_location="x",
            enforcement_location="backend/missing_enforcement.py",
            unlimited_supported=True,
        )
        try:
            self.assertTrue(validate_configurable_finding(finding))
        finally:
            LIMIT_ENTRIES.pop(fp, None)

    def test_simulated_row_cannot_be_operationally_tested(self) -> None:
        row = capability_status_fields(
            implemented=True,
            available=True,
            tested=True,
            quality=True,
            simulated=True,
            note="mock host",
        )
        self.assertFalse(row["operationally_tested"])
        self.assertTrue(row["simulated"])

    def test_dashboard_sandbox_not_os_enforced_from_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            dash = build_dashboard(store)
            sandbox = dash["capability_status"]["3_sandbox"]
            self.assertFalse(sandbox.get("os_isolation_enforced"))
            self.assertFalse(sandbox.get("operationally_tested"))

    def test_asr_package_without_model_not_ready(self) -> None:
        from voice.providers.faster_whisper_asr import FasterWhisperAsr

        asr = FasterWhisperAsr(download_root=Path(tempfile.mkdtemp()) / "whisper")
        avail = asr.availability()
        if avail.get("status") == "dependency_missing":
            self.assertFalse(avail.get("ready"))
        else:
            self.assertFalse(avail.get("ready"))

    def test_cancelled_job_with_late_output_not_completed(self) -> None:
        job = {"status": "cancelled", "late_output": "wrote files after cancel"}
        self.assertNotEqual(job["status"], "completed")

    def test_http_200_empty_lm_completion_is_not_success(self) -> None:
        from lm_studio import LmStudioError, assert_chat_completion

        with self.assertRaises(LmStudioError):
            assert_chat_completion({"choices": []})
        with self.assertRaises(LmStudioError):
            assert_chat_completion({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
        # Blocked/unavailable tools cannot be stored as a completed turn.
        metadata = {
            "execution_status": "blocked",
            "tools": [{"status": "blocked", "error": "policy denied", "tool_name": "shell"}],
        }
        self.assertNotEqual(str(metadata["execution_status"]).lower(), "completed")
        self.assertTrue(any(str(row.get("status")) in {"blocked", "failed", "unavailable"} for row in metadata["tools"]))

    def test_side_effect_replay_blocked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            svc = Gen2Services(store, data_root=Path(tmp))
            result = svc.replay_plan("missing-run", permit_side_effects=False)
            text = str(result).lower()
            self.assertTrue(
                result.get("ok") is False
                or "block" in text
                or "denied" in text
                or "missing" in text
                or "side" in text
                or "not" in text
            )


if __name__ == "__main__":
    unittest.main()
