from __future__ import annotations

import unittest

from Data.modules.browser import (
    BrowserAction,
    BrowserAutomationStub,
    BrowserJobStatus,
    BrowserWorker,
)
from Data.modules.media import MediaAction, MediaAutomationStub, MediaJobStatus
from Data.modules.release import GateCheck, GateSeverity, ReleaseGateRunner, evaluation_relevance_gate
from Data.modules.voice import VoiceAction, VoiceJobStatus, VoiceRuntimeStub


class BrowserMediaVoiceStubTests(unittest.TestCase):
    def test_browser_stub_unsupported_when_feature_off(self) -> None:
        job = BrowserAutomationStub().request(action=BrowserAction.NAVIGATE, url="https://example.com")
        self.assertEqual(job.status, BrowserJobStatus.UNSUPPORTED)
        self.assertTrue(job.public_dict()["truth"]["no_fabricated_browser_results"])

    def test_fixture_browser_worker_completes(self) -> None:
        worker = BrowserWorker()
        job = worker.request(action=BrowserAction.NAVIGATE, url="https://example.com")
        self.assertEqual(job.status, BrowserJobStatus.COMPLETED)
        self.assertTrue(job.public_dict()["truth"]["fixture_is_not_chromium"])
        self.assertTrue(job.public_dict()["truth"]["requires_capability_gateway"])

    def test_media_requires_path(self) -> None:
        job = MediaAutomationStub().request(action=MediaAction.PROBE, path=None)
        self.assertEqual(job.status, MediaJobStatus.REJECTED)

    def test_voice_synthesize_requires_text(self) -> None:
        job = VoiceRuntimeStub().request(action=VoiceAction.SYNTHESIZE, text="")
        self.assertEqual(job.status, VoiceJobStatus.REJECTED)


class ReleaseGateTests(unittest.TestCase):
    def test_block_prevents_ready(self) -> None:
        runner = ReleaseGateRunner(
            checks=[
                lambda: GateCheck("a", "ok", GateSeverity.INFO, True, "ok"),
                lambda: GateCheck("b", "bad", GateSeverity.BLOCK, False, "fail"),
            ]
        )
        report = runner.run()
        self.assertFalse(report.ready)
        self.assertTrue(report.public_dict()["truth"]["release_ready_is_not_production_certified"])
        self.assertTrue(report.public_dict()["truth"]["evaluation_is_release_authority"])

    def test_warn_only_still_ready(self) -> None:
        runner = ReleaseGateRunner(
            checks=[
                lambda: GateCheck("a", "ok", GateSeverity.BLOCK, True, "ok"),
                lambda: GateCheck("b", "warn", GateSeverity.WARN, False, "missing dist"),
            ]
        )
        self.assertTrue(runner.run().ready)

    def test_evaluation_relevance_helper(self) -> None:
        gate = evaluation_relevance_gate(
            {"recorded": True, "measurement": "PASS", "detail": "ok", "promotable": True},
            require_pass=True,
        )
        self.assertTrue(gate.passed)


if __name__ == "__main__":
    unittest.main()
