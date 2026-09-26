"""GI11 — crawler finding → CodingCognitiveStrategy repair bridge (no fake fixed)."""

from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from Data.modules.browser import (
    BrowserJourneyCrawler,
    CrawlBudget,
    CrawlIssue,
    JourneyPersona,
    QaRepairBridge,
)
from Data.modules.browser.worker import BrowserWorker


class _OkHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        body = b"<html><body><h1>OK after repair</h1><a href='/'>Home</a></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class QaRepairBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), _OkHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}/"
        worker = BrowserWorker(backend_kind="local_dom", allow_network=True)
        self.crawler = BrowserJourneyCrawler(
            browser_worker=worker,
            budget=CrawlBudget(max_pages=4, max_actions=10, max_wall_time_seconds=8.0),
            sleep_fn=lambda _s: None,
        )
        self.bridge = QaRepairBridge(crawler=self.crawler)

    def tearDown(self) -> None:
        self.httpd.shutdown()

    def test_propose_does_not_auto_fix(self) -> None:
        finding = CrawlIssue(
            issue_id="iss_test",
            severity="high",
            kind="broken_link",
            message="HTTP 404 for /broken",
            url=self.base,
            reproduction=["Navigate /", "Click broken"],
        )
        proposal = self.bridge.propose_from_finding(finding)
        self.assertEqual(proposal.status, "PROPOSED")
        self.assertTrue(proposal.public_dict()["truth"]["operator_triggered_only"])
        self.assertTrue(proposal.public_dict()["truth"]["no_fake_fixed_state"])
        self.assertTrue(proposal.acceptance)
        self.assertIn("FIX", str(proposal.coding_plan.get("task_type") or "FIX").upper())

    def test_verify_requires_replay_evidence(self) -> None:
        finding = {
            "kind": "broken_link",
            "message": "HTTP 404",
            "url": self.base,
        }
        proposal = self.bridge.propose_from_finding(finding)
        self.bridge.mark_applied_unverified(proposal.proposal_id, evidence={"patch": "noop"})
        verified = self.bridge.verify_with_replay(
            proposal.proposal_id,
            start_url=self.base,
            seed=3,
            original_kind="broken_link",
        )
        # OK fixture has no broken_link — verification may pass without inventing success earlier.
        self.assertIn(verified.status, {"VERIFIED", "FAILED"})
        self.assertIn("replay", verified.evidence)
        if verified.status == "VERIFIED":
            self.assertEqual(verified.evidence["replay"]["matching_kind_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
