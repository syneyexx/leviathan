"""Acceptance tests for the Research subsystem."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.knowledge import KnowledgeStore
from Data.modules.research import (
    ResearchService,
    ResearchStatus,
    UnconfiguredWebProvider,
    validate_url_for_fetch,
)
from Data.modules.research.ssrf import assert_safe_url
from Data.modules.research.store import ResearchStore
from Data.modules.research.web import HttpWebProvider


class ResearchSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        # Unit tests exercise the in-process ResearchCoordinator (TEST/LEGACY).
        # Production defaults externalize research to workers.
        self._ext_patch = mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "0",
                "LEVIATHAN_RESEARCH_RUNNER": "inprocess",
            },
            clear=False,
        )
        self._ext_patch.start()
        self.addCleanup(self._ext_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "leviathan.db"
        self.data_root = self.root / "corpus"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeStore(
            self.db_path,
            data_root=self.data_root,
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        self.store = ResearchStore(self.db_path)
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ingest(self, title: str, content: str, source: str = "fixture") -> None:
        self.knowledge.upsert_document(title=title, content=content, source=source)

    def test_local_research_creates_sources_evidence_claims_report_and_citations(self) -> None:
        self._ingest(
            "Alpha overview",
            "LEVIATHAN research uses a durable evidence ledger. "
            "Local retrieval pulls chunk spans from the KnowledgeStore for offline projects.",
        )
        self._ingest(
            "Alpha methods",
            "Citations must resolve to evidence and then to a stored source snapshot. "
            "The research runner never invents source URLs.",
        )
        self._ingest(
            "Alpha gaps",
            "Coverage summaries list unresolved questions without fabricating a truth percentage.",
        )

        project = self.service.create_project(
            topic="How does LEVIATHAN local research preserve evidence?",
            objective="Document offline evidence and citation behavior",
            depth="standard",
            allow_web=False,
            local_scopes=["fixture"],
        )
        self.service.plan(project.project_id)
        done = self.service.run(project.project_id)

        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        sources = self.service.list_sources(project.project_id)
        evidence = self.service.list_evidence(project.project_id)
        claims = self.service.list_claims(project.project_id)
        report = self.service.get_report(project.project_id)

        self.assertGreaterEqual(len(sources), 1)
        self.assertGreaterEqual(len(evidence), 1)
        self.assertGreaterEqual(len(claims), 1)
        self.assertTrue(report.body_markdown)
        self.assertIn("Evidence", report.body_markdown)

        # Every citation in the report must resolve.
        resolutions = self.service.ledger.resolve_all_in_text(
            project.project_id, report.body_markdown
        )
        self.assertTrue(resolutions)
        for item in resolutions:
            self.assertTrue(item.resolved, msg=item.public_dict())
            self.assertIsNotNone(item.evidence_id)
            self.assertIsNotNone(item.source_id)
            src = self.store.get_source(item.source_id or "")
            self.assertIsNotNone(src)
            assert src is not None
            self.assertTrue(src.snapshot_path)
            self.assertTrue(Path(src.snapshot_path).is_file())

        # Survives "restart" via fresh service on same DB.
        restarted = ResearchService(
            ResearchStore(self.db_path),
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
        )
        restarted.store.initialize()
        again = restarted.get_project(project.project_id)
        self.assertEqual(again.status, ResearchStatus.COMPLETED)
        self.assertGreaterEqual(again.evidence_count, 1)
        self.assertIsNotNone(restarted.store.get_latest_report(project.project_id))

    def test_contradiction_preserved_in_conflicts_and_report(self) -> None:
        self._ingest(
            "Source A launch note",
            "Product X was launched in 2024. The launch event was covered by the trade press.",
            source="press-a",
        )
        self._ingest(
            "Source B launch note",
            "Product X was launched in 2025. The company delayed the public launch by one year.",
            source="press-b",
        )

        project = self.service.create_project(
            topic="When was Product X launched?",
            depth="standard",
            allow_web=False,
        )
        self.service.plan(project.project_id)
        done = self.service.run(project.project_id)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)

        conflicts = self.service.list_conflicts(project.project_id)
        self.assertGreaterEqual(len(conflicts), 1, msg="expected contradiction conflict record")
        conflict = conflicts[0]
        self.assertTrue(conflict.supporting_evidence_ids)
        self.assertTrue(conflict.contradicting_evidence_ids)
        self.assertEqual(conflict.analysis.get("resolution"), "unresolved")

        claims = self.service.list_claims(project.project_id)
        disputed = [c for c in claims if c.contradicting_evidence_ids]
        self.assertTrue(disputed)

        report = self.service.get_report(project.project_id)
        lowered = report.body_markdown.lower()
        self.assertTrue(
            "contradict" in lowered or "conflict" in lowered or "uncertainty" in lowered
        )
        # Must not collapse to a single confident year without acknowledging conflict.
        self.assertIn("2024", report.body_markdown)
        self.assertIn("2025", report.body_markdown)

    def test_web_requested_but_unavailable_is_explicit(self) -> None:
        self._ingest(
            "Local only",
            "Local document about LEVIATHAN offline research remains usable without web providers.",
        )
        project = self.service.create_project(
            topic="LEVIATHAN offline research",
            allow_web=True,
            depth="quick",
        )
        self.assertEqual(project.web_unavailable_reason, "outbound_network_disabled")
        self.service.plan(project.project_id)
        done = self.service.run(project.project_id)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        self.assertEqual(done.web_unavailable_reason, "outbound_network_disabled")

        events = self.service.list_events(project.project_id)
        web_events = [
            e
            for e in events
            if e.payload.get("channel") == "web" and e.payload.get("status") == "unavailable"
        ]
        self.assertTrue(web_events)
        # Local path still produced evidence.
        self.assertGreaterEqual(len(self.service.list_evidence(project.project_id)), 1)
        # No fabricated web pages.
        web_pages = [
            s for s in self.service.list_sources(project.project_id) if s.source_type.value == "web_page"
        ]
        self.assertEqual(web_pages, [])

    def test_ssrf_blocks_localhost_and_private_ips(self) -> None:
        blocked = [
            "http://127.0.0.1/secret",
            "https://localhost/admin",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.5/internal",
            "http://192.168.1.10/x",
            "file:///etc/passwd",
        ]
        for url in blocked:
            decision = validate_url_for_fetch(url, resolve_dns=False)
            self.assertFalse(decision.allowed, msg=f"should block {url}: {decision}")

        with self.assertRaises(ValueError):
            assert_safe_url("http://127.0.0.1/", resolve_dns=False)

        provider = HttpWebProvider(allow_outbound=True)
        with self.assertRaises(ValueError):
            provider.fetch_page("http://127.0.0.1/evil")

    def test_cancel_and_interrupt_recovery(self) -> None:
        self._ingest(
            "Cancel doc",
            "Document used while testing research cancel and interrupt recovery paths.",
        )
        project = self.service.create_project(
            topic="cancel research",
            depth="quick",
            allow_web=False,
        )
        self.service.plan(project.project_id)

        # Idle cancel before run.
        cancelled = self.service.cancel(project.project_id)
        self.assertEqual(cancelled.status, ResearchStatus.CANCELLED)

        # Fresh project: cooperative cancel during run via store flag mid-flight.
        project2 = self.service.create_project(
            topic="interrupt research",
            depth="deep",
            allow_web=False,
        )
        self.service.plan(project2.project_id)

        original_local_search = self.service.runner.local.search

        def search_and_cancel(query: str, **kwargs):
            self.store.request_cancel(project2.project_id)
            return original_local_search(query, **kwargs)

        self.service.runner.local.search = search_and_cancel  # type: ignore[method-assign]
        stopped = self.service.run(project2.project_id)
        self.assertEqual(stopped.status, ResearchStatus.CANCELLED)

        # Interrupt detection: dead worker pid.
        project3 = self.service.create_project(topic="dead worker", allow_web=False)
        project3.status = ResearchStatus.RESEARCHING
        project3.worker_pid = 999999  # unlikely to be alive
        self.store.save_project(project3)
        recovered = self.service.recover()
        self.assertIn(project3.project_id, recovered)
        again = self.service.get_project(project3.project_id)
        self.assertEqual(again.status, ResearchStatus.INTERRUPTED)

    def test_deepen_adds_round_without_deleting_prior_evidence(self) -> None:
        self._ingest(
            "Deepen base",
            "Initial evidence about LEVIATHAN deepen operations keeps prior evidence intact.",
        )
        self._ingest(
            "Deepen extra",
            "Additional material about unresolved questions helps a deepen round retrieve new spans.",
        )
        project = self.service.create_project(
            topic="LEVIATHAN deepen operations",
            depth="quick",
            allow_web=False,
        )
        self.service.plan(project.project_id)
        first = self.service.run(project.project_id)
        self.assertEqual(first.status, ResearchStatus.COMPLETED)
        evidence_before = len(self.service.list_evidence(project.project_id))
        rounds_before = first.current_round
        report_before = first.report_version

        deepened = self.service.deepen(project.project_id, extra_rounds=1)
        self.assertEqual(deepened.status, ResearchStatus.COMPLETED)
        self.assertGreater(deepened.current_round, rounds_before)
        self.assertGreaterEqual(len(self.service.list_evidence(project.project_id)), evidence_before)
        self.assertGreaterEqual(deepened.report_version, report_before)
        # Prior sources remain.
        self.assertGreaterEqual(len(self.service.list_sources(project.project_id)), 1)


if __name__ == "__main__":
    unittest.main()
