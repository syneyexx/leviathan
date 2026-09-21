"""Honesty tests for host probes (LM Studio / browser / voice)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host_probes import (
    STATUS_VOCABULARY,
    judge_lm_studio_chat_response,
    probe_browser,
    probe_voice,
)


class LmStudioJudgeTests(unittest.TestCase):
    def test_http_200_empty_completion_is_not_pass(self) -> None:
        judged = judge_lm_studio_chat_response(
            transport_ok=True,
            http_status=200,
            body={"choices": [{"message": {"content": ""}}]},
        )
        self.assertTrue(judged["transport_reachable"])
        self.assertFalse(judged["inference_ok"])
        self.assertNotEqual(judged["status"], "PASS")
        self.assertEqual(judged["failure_reason"], "empty_completion_content")

    def test_missing_choices_not_pass(self) -> None:
        judged = judge_lm_studio_chat_response(
            transport_ok=True,
            http_status=200,
            body={"choices": []},
        )
        self.assertEqual(judged["failure_reason"], "empty_or_missing_choices")
        self.assertEqual(judged["status"], "DEGRADED")

    def test_usable_content_is_pass(self) -> None:
        judged = judge_lm_studio_chat_response(
            transport_ok=True,
            http_status=200,
            body={"choices": [{"message": {"content": "HADES_LIVE_OK"}}]},
        )
        self.assertTrue(judged["inference_ok"])
        self.assertEqual(judged["status"], "PASS")

    def test_transport_failure_unverified(self) -> None:
        judged = judge_lm_studio_chat_response(
            transport_ok=False,
            http_status=None,
            body=None,
            transport_error="connection refused",
        )
        self.assertEqual(judged["status"], "UNVERIFIED_ON_HOST")
        self.assertFalse(judged["transport_reachable"])


class BrowserProbeTests(unittest.TestCase):
    def test_manifest_alone_is_not_pass(self) -> None:
        row = probe_browser(repo_root=Path(__file__).resolve().parents[2])
        self.assertNotEqual(row["status"], "PASS")
        self.assertIn(row["status"], {"UNAVAILABLE", "UNVERIFIED_ON_HOST", "DEGRADED"})
        # Without Ready+deps, operationally_tested must stay false.
        if not row.get("operationally_tested"):
            self.assertNotEqual(row["status"], "PASS")
        evidence = row.get("evidence") or {}
        if evidence.get("manifest_present"):
            self.assertNotEqual(row.get("failure_reason"), None)


class VoiceProbeTests(unittest.TestCase):
    def test_axes_separated_and_doctor_alone_not_pass(self) -> None:
        with patch("voice.install.doctor", return_value={"ready": True, "checks": [{"id": "asr", "ok": True}]}):
            with patch("voice.runtime.VoiceRuntime", side_effect=RuntimeError("no models")):
                row = probe_voice(settings={"voice_asr_provider": "faster_whisper"})
        self.assertNotEqual(row["status"], "PASS")
        evidence = row["evidence"]
        for key in (
            "deps_modelcache",
            "asr_wav_fixture",
            "tts_playable_file",
            "physical_mic",
            "physical_playback",
            "config",
        ):
            self.assertIn(key, evidence)
        self.assertFalse(evidence["physical_mic"]["ok"])
        self.assertFalse(evidence["physical_playback"]["ok"])
        self.assertFalse(row["operationally_tested"])

    def test_status_vocabulary_documented(self) -> None:
        for status in ("PASS", "FAIL", "SKIPPED", "UNAVAILABLE", "UNVERIFIED_ON_HOST"):
            self.assertIn(status, STATUS_VOCABULARY)


if __name__ == "__main__":
    unittest.main()
