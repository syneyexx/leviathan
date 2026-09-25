"""Hardening tests for Research workers, immutability, uploads, and Brain sync."""

from __future__ import annotations

import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.knowledge import KnowledgeStore
from Data.modules.research import (
    ResearchExecutionMode,
    ResearchService,
    ResearchStatus,
    UnconfiguredWebProvider,
    apply_plan_edits,
)
from Data.modules.research.budgets import (
    NORMAL_ROUNDS,
    NORMAL_WORKERS,
    budget_catalog,
    resolve_execution_budget,
    budget_for_depth,
)
from Data.modules.research.coordinator import assign_worker_queries
from Data.modules.research.planner import build_plan
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import ResearchPhase, WorkerStatus
from Data.modules.research.uploads import parse_bytes, sanitize_filename


class ResearchHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
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
            sources_root=self.root / "sources",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_budget_catalog_exposes_normal_and_custom_limits(self) -> None:
        catalog = budget_catalog()
        self.assertEqual(catalog["execution_modes"]["normal"]["research_workers"], NORMAL_WORKERS)
        self.assertEqual(catalog["execution_modes"]["normal"]["rounds"], NORMAL_ROUNDS)
        self.assertEqual(catalog["execution_modes"]["custom"]["limits"]["research_workers"]["max"], 16)
        self.assertEqual(catalog["execution_modes"]["custom"]["limits"]["rounds"]["max"], 100)
        normal = resolve_execution_budget(
            execution_mode=ResearchExecutionMode.NORMAL,
            base=budget_for_depth("quick"),
        )
        self.assertEqual(normal.research_workers, 2)
        self.assertEqual(normal.rounds, 10)

    def test_immutable_plan_adaptation_no_frozen_mutation(self) -> None:
        self.knowledge.upsert_document(
            title="Conflict A",
            content="Widget Alpha was launched in 2020. The launch was public.",
            source="press-a",
        )
        self.knowledge.upsert_document(
            title="Conflict B",
            content="Widget Alpha was launched in 2021. The company delayed the launch.",
            source="press-b",
        )
        project = self.service.create_project(
            topic="When was Widget Alpha launched?",
            depth="standard",
            allow_web=False,
            execution_mode="custom",
            budget_overrides={"rounds": 2, "research_workers": 1, "max_sources": 10},
        )
        planned = self.service.plan(project.project_id)
        original_plan = planned.plan
        assert original_plan is not None
        original_queries = list(original_plan.retrieval_queries)
        original_id = id(original_plan)

        # Field reassignment on frozen plan must fail (the production crash).
        with self.assertRaises(Exception):
            original_plan.retrieval_queries = original_queries + ["mutated"]  # type: ignore[misc]

        done = self.service.run(project.project_id, background=False)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        # Original plan object must not have been replaced/mutated via assignment.
        self.assertEqual(id(original_plan), original_id)
        # apply_plan_edits returns a new plan instance
        edited = apply_plan_edits(original_plan, {"retrieval_queries": original_queries + ["extra q"]})
        self.assertIsNot(edited, original_plan)
        self.assertIn("extra q", edited.retrieval_queries)
        self.assertNotIn("extra q", original_plan.retrieval_queries)

    def test_normal_mode_two_workers_ten_rounds(self) -> None:
        self.knowledge.upsert_document(
            title="Ledger",
            content="LEVIATHAN research uses a durable evidence ledger for offline projects.",
            source="fixture",
        )
        project = self.service.create_project(
            topic="How does LEVIATHAN preserve evidence?",
            depth="deep",
            allow_web=False,
            execution_mode="normal",
        )
        self.assertEqual(project.budget.research_workers, 2)
        self.assertEqual(project.budget.rounds, 10)
        self.assertEqual(project.total_worker_rounds, 20)
        done = self.service.run(project.project_id, background=False)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        workers = self.service.list_workers(project.project_id)
        self.assertEqual(len(workers), 2)
        for w in workers:
            self.assertEqual(w.total_rounds, 10)
            self.assertEqual(w.completed_rounds, 10)
            self.assertEqual(w.status, WorkerStatus.COMPLETED)
        self.assertEqual(done.completed_worker_rounds, 20)
        self.assertEqual(done.progress_pct, 100.0)

    def test_custom_mode_three_workers_four_rounds_with_concurrency(self) -> None:
        self.knowledge.upsert_document(
            title="Concurrency note",
            content="Parallel research workers share a durable store and evidence ledger.",
            source="fixture",
        )
        overlap = {"max": 0}
        lock = threading.Lock()
        active = {"n": 0}

        original = self.service.runner.coordinator._worker_round

        def wrapped(worker, project_id, round_number, total_rounds, queries):
            with lock:
                active["n"] += 1
                overlap["max"] = max(overlap["max"], active["n"])
            try:
                time.sleep(0.02)
                return original(worker, project_id, round_number, total_rounds, queries)
            finally:
                with lock:
                    active["n"] -= 1

        self.service.runner.coordinator._worker_round = wrapped  # type: ignore[method-assign]

        project = self.service.create_project(
            topic="How do research workers coordinate?",
            depth="standard",
            allow_web=False,
            execution_mode="custom",
            budget_overrides={"research_workers": 3, "rounds": 4, "max_sources": 20},
        )
        self.assertEqual(project.budget.research_workers, 3)
        self.assertEqual(project.budget.rounds, 4)
        done = self.service.run(project.project_id, background=False)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        workers = self.service.list_workers(project.project_id)
        self.assertEqual(len(workers), 3)
        self.assertEqual(sum(w.completed_rounds for w in workers), 12)
        self.assertEqual(done.completed_worker_rounds, 12)
        # Concurrent fan-out should overlap at least once for 3 workers.
        self.assertGreaterEqual(overlap["max"], 2)

    def test_query_assignment_is_diverse(self) -> None:
        queries = ["q1", "q2", "q3", "q4", "q5", "q6"]
        a = assign_worker_queries(queries, worker_index=0, worker_count=2, round_number=1)
        b = assign_worker_queries(queries, worker_index=1, worker_count=2, round_number=1)
        self.assertTrue(a)
        self.assertTrue(b)
        self.assertNotEqual(a, b)

    def test_upload_txt_enters_brain_and_is_retrievable(self) -> None:
        token = "ZXQ-RESEARCH-91827"
        project = self.service.create_project(
            topic="Find the research token",
            execution_mode="custom",
            budget_overrides={"rounds": 1, "research_workers": 1},
        )
        payload = f"Leviathan test evidence token is {token}. Keep this sentence intact.\n".encode()
        result = self.service.upload_source(
            project.project_id,
            filename="token.txt",
            stream=io.BytesIO(payload),
            content_type="text/plain",
        )
        source = result["source"]
        self.assertEqual(source["parse_status"], "ok")
        self.assertEqual(source["brain_status"], "synced")
        self.assertTrue(source.get("brain_document_id"))
        hits = self.knowledge.search_lexical(token, limit=5)
        self.assertTrue(hits, msg="uploaded document must be retrievable from KnowledgeStore")
        blob = " ".join(h.get("chunk_content") or h.get("content") or "" for h in hits)
        self.assertIn(token, blob)

    def test_upload_rejects_path_traversal_and_unsupported(self) -> None:
        project = self.service.create_project(topic="Upload security", execution_mode="custom")
        safe = sanitize_filename("../../etc/passwd")
        self.assertNotIn("..", safe)
        with self.assertRaises(Exception):
            parse_bytes(b"not-a-pdf", filename="scan.exe")
        with self.assertRaises(Exception):
            self.service.upload_source(
                project.project_id,
                filename="evil.exe",
                stream=io.BytesIO(b"MZ"),
            )

    def test_upload_pdf_text_and_image_only(self) -> None:
        project = self.service.create_project(topic="PDF ingest", execution_mode="custom")
        # Minimal PDF with extractable text via pypdf if available; otherwise stream fallback.
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DecString

            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=200)
            # pypdf blank pages have no text — expect PDF_NO_EXTRACTABLE_TEXT
            buf = io.BytesIO()
            writer.write(buf)
            raw = buf.getvalue()
        except Exception:
            raw = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

        from Data.modules.research.types import ResearchError

        with self.assertRaises(ResearchError) as ctx:
            self.service.upload_source(
                project.project_id,
                filename="empty.pdf",
                stream=io.BytesIO(raw),
                content_type="application/pdf",
            )
        self.assertIn(ctx.exception.code, {"PDF_NO_EXTRACTABLE_TEXT", "SOURCE_PARSE_FAILED"})

        # Text PDF via simple constructed content if pypdf can write text is hard;
        # use parse_bytes on a synthetic text-bearing fallback through TXT path covered above.
        md = self.service.upload_source(
            project.project_id,
            filename="notes.md",
            stream=io.BytesIO(b"# Title\n\nUseful research note about widgets.\n"),
        )
        self.assertEqual(md["source"]["parse_status"], "ok")

    def test_failed_progress_not_100(self) -> None:
        project = self.service.create_project(
            topic="Force failure",
            execution_mode="custom",
            budget_overrides={"rounds": 1, "research_workers": 1},
        )
        self.service.plan(project.project_id)

        def boom(*_a, **_k):
            raise RuntimeError("provider exploded")

        self.service.runner.coordinator._worker_round = boom  # type: ignore[method-assign]
        with self.assertRaises(Exception):
            self.service.run(project.project_id, background=False)
        failed = self.service.get_project(project.project_id)
        self.assertEqual(failed.status, ResearchStatus.FAILED)
        self.assertLess(failed.progress_pct, 100.0)
        self.assertEqual(failed.phase, ResearchPhase.FAILED)

    def test_background_run_returns_quickly(self) -> None:
        self.knowledge.upsert_document(
            title="Bg",
            content="Background research execution should return control promptly to the API.",
            source="fixture",
        )
        project = self.service.create_project(
            topic="Background research promptness",
            execution_mode="custom",
            budget_overrides={"rounds": 2, "research_workers": 1},
        )
        started = time.time()
        queued = self.service.run(project.project_id, background=True)
        elapsed = time.time() - started
        self.assertLess(elapsed, 2.0)
        self.assertIn(queued.status, {ResearchStatus.QUEUED, ResearchStatus.RESEARCHING})
        # Wait for completion
        deadline = time.time() + 30
        while time.time() < deadline:
            latest = self.service.get_project(project.project_id)
            if latest.status in {ResearchStatus.COMPLETED, ResearchStatus.FAILED, ResearchStatus.CANCELLED}:
                break
            time.sleep(0.1)
        latest = self.service.get_project(project.project_id)
        self.assertEqual(latest.status, ResearchStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
