from __future__ import annotations

import unittest

from reasoning.usage_telemetry import UsageTelemetry


class UsageTelemetrySessionIdentityTests(unittest.TestCase):
    def test_record_usage_without_conversation_counts_once(self) -> None:
        telemetry = UsageTelemetry()
        snap = telemetry.record_usage(
            {"total_tokens": 10, "prompt_tokens": 6, "completion_tokens": 4},
            conversation_id=None,
            model_id="m1",
        )
        self.assertEqual(snap.model_calls, 1)
        self.assertEqual(snap.session_total, 10)
        self.assertEqual(snap.conversation_total, 10)
        self.assertEqual(len(snap.history), 1)

    def test_status_without_conversation_appends_one_history_event(self) -> None:
        telemetry = UsageTelemetry()
        snap = telemetry.set_status("queued", conversation_id=None, model_id="m1")
        self.assertEqual(len(snap.history), 1)
        self.assertEqual(snap.status, "queued")

    def test_provisional_without_conversation_updates_once_without_completed_cost(self) -> None:
        telemetry = UsageTelemetry()
        snap = telemetry.record_provisional(output_tokens=20, conversation_id=None, model_id="m1")
        self.assertEqual(len(snap.history), 1)
        self.assertEqual(snap.model_calls, 0)
        self.assertEqual(snap.session_total, 0)
        self.assertEqual(snap.current_output, 20)

    def test_conversation_usage_updates_session_and_conversation_once_each(self) -> None:
        telemetry = UsageTelemetry()
        snap = telemetry.record_usage(
            {"total_tokens": 12, "prompt_tokens": 7, "completion_tokens": 5},
            conversation_id="c1",
            model_id="m1",
        )
        self.assertEqual(snap.model_calls, 1)
        self.assertEqual(snap.session_total, 12)
        self.assertEqual(snap.conversation_total, 12)
        self.assertEqual(len(snap.history), 1)
        session = telemetry.snapshot()
        self.assertEqual(session.model_calls, 1)
        self.assertEqual(session.session_total, 12)
        self.assertEqual(len(session.history), 1)


if __name__ == "__main__":
    unittest.main()
