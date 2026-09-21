"""Live chat usage telemetry / provisional stream ticks.

Behavioral unit checks only — no live LM Studio required.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ProvisionalUsageTelemetryTests(unittest.TestCase):
    def test_record_provisional_updates_current_without_inflating_calls(self) -> None:
        from reasoning.usage_telemetry import UsageTelemetry

        tel = UsageTelemetry()
        before = tel.snapshot("c-live")
        self.assertEqual(before.model_calls, 0)
        self.assertEqual(before.session_total, 0)

        snap = tel.record_provisional(
            output_tokens=40,
            input_tokens=10,
            conversation_id="c-live",
            model_id="local-m",
            status="generating",
        )
        self.assertEqual(snap.current_output, 40)
        self.assertEqual(snap.current_input, 10)
        self.assertEqual(snap.current_total, 50)
        self.assertEqual(snap.current_kind, "estimate")
        self.assertEqual(snap.status, "generating")
        self.assertEqual(snap.model_calls, 0)
        self.assertEqual(snap.session_total, 0)
        self.assertEqual(snap.peak_total, 50)

        snap2 = tel.record_provisional(
            output_tokens=80,
            input_tokens=10,
            conversation_id="c-live",
            model_id="local-m",
        )
        self.assertEqual(snap2.current_output, 80)
        self.assertEqual(snap2.current_total, 90)
        self.assertEqual(snap2.model_calls, 0)
        self.assertEqual(snap2.session_total, 0)
        self.assertEqual(snap2.peak_total, 90)

    def test_completed_usage_still_increments_totals(self) -> None:
        from reasoning.usage_telemetry import UsageTelemetry

        tel = UsageTelemetry()
        tel.record_provisional(output_tokens=20, conversation_id="c2")
        snap = tel.record_usage(
            {"total_tokens": 120, "prompt_tokens": 40, "completion_tokens": 80},
            conversation_id="c2",
            model_id="m",
            kind="exact",
            status="idle",
        )
        self.assertEqual(snap.model_calls, 1)
        self.assertEqual(snap.session_total, 120)
        self.assertEqual(snap.current_kind, "exact")


class StreamProvisionalWiringTests(unittest.TestCase):
    def test_stream_helper_ticks_provisional_usage(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        # Locate the stream helper body without importing FastAPI-heavy main.
        start = source.find("async def _chat_with_optional_stream(")
        self.assertGreater(start, 0)
        chunk = source[start : start + 8_000]
        self.assertIn("record_provisional", chunk)
        self.assertIn("_tick_provisional_usage", chunk)
        self.assertIn("conversation_id", chunk)


if __name__ == "__main__":
    unittest.main()
