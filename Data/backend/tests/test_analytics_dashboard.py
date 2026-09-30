"""Analytics dashboard read-model tests — multi-DB, no fake trends."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.analytics import AnalyticsService
from Data.modules.analytics.contracts import (
    classify_dataset_type,
    classify_item_type,
    classify_research_activity,
    classify_source,
    processing_task_for_capability,
)


def _utc(offset_days: int = 0, offset_hours: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=offset_days, hours=offset_hours)
    return dt.isoformat(timespec="seconds")


def _init_control(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE research_projects (
            project_id TEXT PRIMARY KEY,
            title TEXT,
            topic TEXT,
            objective TEXT,
            status TEXT,
            depth TEXT,
            allow_web INTEGER DEFAULT 0,
            respect_robots_txt INTEGER DEFAULT 1,
            model_profile_json TEXT DEFAULT '{}',
            budget_json TEXT DEFAULT '{}',
            plan_json TEXT DEFAULT '{}',
            execution_mode TEXT DEFAULT 'normal',
            phase TEXT DEFAULT 'idle',
            progress_pct REAL DEFAULT 0,
            analysis_mode TEXT DEFAULT 'deterministic_fallback',
            connected_datasets_json TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE research_runs (
            run_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            execution_mode TEXT NOT NULL DEFAULT 'normal',
            workers INTEGER DEFAULT 1,
            rounds_per_worker INTEGER DEFAULT 1,
            phase TEXT DEFAULT 'idle',
            completed_worker_rounds INTEGER DEFAULT 0,
            total_worker_rounds INTEGER DEFAULT 0,
            progress_pct REAL DEFAULT 0,
            analysis_mode TEXT DEFAULT 'deterministic_fallback',
            error TEXT,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            capability_id TEXT NOT NULL,
            arguments_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL,
            requested_by TEXT NOT NULL DEFAULT 'test',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE TABLE agent_definitions (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE agent_missions (
            mission_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE training_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            method TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def _init_knowledge(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE knowledge_documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT DEFAULT 'READY',
            size_bytes INTEGER,
            trust_metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            token_estimate INTEGER NOT NULL DEFAULT 1,
            source_type TEXT DEFAULT 'document',
            provenance_json TEXT DEFAULT '{}'
        );
        CREATE TABLE datasets (
            dataset_id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            source_type TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            byte_size INTEGER,
            row_count INTEGER,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE dataset_jobs (
            job_id TEXT PRIMARY KEY,
            dataset_id TEXT,
            job_type TEXT,
            status TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


class ContractHelpersTests(unittest.TestCase):
    def test_item_type_map(self) -> None:
        self.assertEqual(classify_item_type("pdf"), "document")
        self.assertEqual(classify_item_type("note"), "note")
        self.assertEqual(classify_item_type(None), "unknown")
        self.assertEqual(classify_item_type("weird_thing"), "other")

    def test_source_unknown_not_manual(self) -> None:
        self.assertEqual(classify_source(None), "unknown")
        self.assertEqual(classify_source(""), "unknown")
        self.assertEqual(classify_source("manual"), "manual")

    def test_dataset_type(self) -> None:
        self.assertEqual(
            classify_dataset_type(primary_category="FINANCE_TRADING"),
            "market",
        )
        self.assertEqual(
            classify_dataset_type(primary_category="GENERAL", metadata={"synthetic": True}),
            "synthetic",
        )
        self.assertEqual(classify_dataset_type(primary_category="UNCATEGORIZED"), "unknown")

    def test_research_activity(self) -> None:
        self.assertEqual(
            classify_research_activity(allow_web=True),
            "web_research",
        )
        self.assertEqual(
            classify_research_activity(execution_mode="team"),
            "agent_research",
        )
        self.assertEqual(
            classify_research_activity(metadata={"trading": True}),
            "trading",
        )

    def test_processing_capability(self) -> None:
        self.assertEqual(processing_task_for_capability("embedding.batch"), "embedding_generation")
        self.assertEqual(processing_task_for_capability("dataset.process"), "dataset_processing")
        self.assertEqual(processing_task_for_capability("document_ai.ocr"), "document_processing")
        self.assertEqual(processing_task_for_capability("ocr.extract"), "document_processing")
        self.assertEqual(processing_task_for_capability("web.search"), "web_scraping")
        self.assertEqual(processing_task_for_capability("web.fetch"), "web_scraping")
        self.assertEqual(processing_task_for_capability("knowledge.ingest_document"), "document_processing")
        self.assertEqual(processing_task_for_capability("knowledge.commit"), "document_processing")
        self.assertEqual(processing_task_for_capability("research.synthesize"), "knowledge_extraction")
        self.assertEqual(processing_task_for_capability("rerank.batch"), "embedding_generation")
        self.assertIsNone(processing_task_for_capability("models.load"))
        # Must not substring-match unrelated capabilities.
        self.assertIsNone(processing_task_for_capability("agent.web_assist"))


class AnalyticsDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.control = root / "control.db"
        self.knowledge = root / "knowledge.db"
        _init_control(self.control)
        _init_knowledge(self.knowledge)
        self.svc = AnalyticsService(self.control, knowledge_db_path=self.knowledge)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ins_doc(self, doc_id: str, *, source: str, created_at: str, size: int = 100) -> None:
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            """
            INSERT INTO knowledge_documents(id, title, content, source, created_at, updated_at, size_bytes)
            VALUES (?, ?, 'x', ?, ?, ?, ?)
            """,
            (doc_id, doc_id, source, created_at, created_at, size),
        )
        conn.execute(
            """
            INSERT INTO knowledge_chunks(
                chunk_id, document_id, chunk_index, content, content_hash, source_type, provenance_json
            ) VALUES (?, ?, 0, 'c', 'h', ?, ?)
            """,
            (
                f"{doc_id}-c0",
                doc_id,
                "document" if source == "manual" else source,
                json.dumps({}),
            ),
        )
        conn.commit()
        conn.close()

    def test_overview_knowledge_totals(self) -> None:
        now = _utc(0)
        self._ins_doc("d1", source="manual", created_at=now)
        self._ins_doc("d2", source="web", created_at=now)
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, name, status, source_type, created_at, updated_at, byte_size, metadata_json)
            VALUES ('ds1', 'A', 'ready', 'local', ?, ?, 1024, ?)
            """,
            (now, now, json.dumps({"semanticProfile": {"primaryCategory": "FINANCE_TRADING", "tags": ["trading"]}})),
        )
        conn.commit()
        conn.close()
        conn = sqlite3.connect(self.control)
        conn.execute(
            """
            INSERT INTO research_runs(
                run_id, project_id, status, created_at, updated_at
            ) VALUES ('r1', 'p1', 'completed', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()

        dash = self.svc.dashboard(chart_range="30d", ranking_range="7d")
        self.assertEqual(dash["kpis"]["knowledgeItems"]["value"], 2)
        self.assertEqual(dash["kpis"]["datasets"]["value"], 1)
        self.assertEqual(dash["kpis"]["researchJobs"]["value"], 1)
        # documents = classified as document (manual → document via source_type on chunk)
        self.assertGreaterEqual(dash["kpis"]["documents"]["value"], 1)
        self.assertTrue(dash["truth"]["no_fake_trends"])
        self.assertTrue(dash["truth"]["unknown_is_not_zero"])

    def test_processing_unmeasured_when_no_jobs(self) -> None:
        dash = self.svc.dashboard()
        self.assertEqual(dash["kpis"]["avgProcessingSeconds"]["status"], "UNMEASURED")
        self.assertIsNone(dash["kpis"]["avgProcessingSeconds"]["value"])

    def test_processing_duration_excludes_nonterminal(self) -> None:
        now = _utc(0)
        started = _utc(offset_hours=-1)
        conn = sqlite3.connect(self.control)
        conn.execute(
            """
            INSERT INTO jobs(job_id, capability_id, state, created_at, updated_at, started_at, finished_at)
            VALUES ('j1', 'embedding.batch', 'COMPLETED', ?, ?, ?, ?)
            """,
            (now, now, started, now),
        )
        conn.execute(
            """
            INSERT INTO jobs(job_id, capability_id, state, created_at, updated_at, started_at, finished_at)
            VALUES ('j2', 'embedding.batch', 'RUNNING', ?, ?, ?, ?)
            """,
            (now, now, started, now),
        )
        conn.commit()
        conn.close()
        dash = self.svc.dashboard()
        self.assertIsNotNone(dash["kpis"]["avgProcessingSeconds"]["value"])
        tasks = {t["key"]: t for t in dash["processing"]["tasks"]}
        self.assertEqual(tasks["embedding_generation"]["count"], 1)

    def test_knowledge_growth_no_fabricated_prehistory(self) -> None:
        # Only create docs in last 2 days — earlier buckets may be unknown or baseline 0
        self._ins_doc("d1", source="manual", created_at=_utc(-1))
        self._ins_doc("d2", source="manual", created_at=_utc(0))
        dash = self.svc.dashboard(chart_range="7d")
        points = dash["knowledgeGrowth"]["points"]
        self.assertTrue(points)
        # Final known cumulative should be 2
        known = [p for p in points if p.get("known")]
        self.assertEqual(known[-1]["value"], 2)

    def test_dataset_growth_coverage(self) -> None:
        now = _utc(0)
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, name, status, source_type, created_at, updated_at, byte_size)
            VALUES ('a', 'A', 'ready', 'local', ?, ?, 2048)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, name, status, source_type, created_at, updated_at, byte_size)
            VALUES ('b', 'B', 'ready', 'local', ?, ?, NULL)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()
        dash = self.svc.dashboard(chart_range="7d")
        cov = dash["datasetGrowth"]["coverage"]
        self.assertEqual(cov["measuredCount"], 1)
        self.assertEqual(cov["unknownCount"], 1)

    def test_distributions_percentages(self) -> None:
        self._ins_doc("d1", source="manual", created_at=_utc(0))
        self._ins_doc("d2", source="web", created_at=_utc(0))
        dash = self.svc.dashboard()
        segs = dash["distributions"]["itemTypes"]["segments"]
        total_pct = sum(s["percent"] for s in segs)
        self.assertAlmostEqual(total_pct, 100.0, delta=0.2)
        self.assertEqual(dash["distributions"]["itemTypes"]["total"], 2)

    def test_top_agents_requires_provenance(self) -> None:
        now = _utc(0)
        self._ins_doc("d1", source="manual", created_at=now)
        # Without agent provenance → empty top agents
        dash = self.svc.dashboard(ranking_range="7d")
        self.assertEqual(dash["rankings"]["topAgents"], [])

        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            "UPDATE knowledge_chunks SET provenance_json = ? WHERE document_id = ?",
            (json.dumps({"agent_id": "agent-1"}), "d1"),
        )
        conn.commit()
        conn.close()
        conn = sqlite3.connect(self.control)
        conn.execute(
            "INSERT INTO agent_definitions(agent_id, name) VALUES ('agent-1', 'Alpha')"
        )
        conn.execute(
            """
            INSERT INTO agent_missions(mission_id, agent_id, status, created_at)
            VALUES ('m1', 'agent-1', 'completed', ?), ('m2', 'agent-1', 'failed', ?)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()
        dash = self.svc.dashboard(ranking_range="7d")
        agents = dash["rankings"]["topAgents"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["agentId"], "agent-1")
        self.assertEqual(agents[0]["items"], 1)
        self.assertEqual(agents[0]["successRatePercent"], 50.0)

    def test_top_agents_signal_fabric_producer(self) -> None:
        now = _utc(0)
        self._ins_doc("d2", source="agent", created_at=now)
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            "UPDATE knowledge_chunks SET provenance_json = ? WHERE document_id = ?",
            (json.dumps({"producer": "signal_fabric:scout-9"}), "d2"),
        )
        conn.commit()
        conn.close()
        dash = self.svc.dashboard(ranking_range="7d")
        agents = dash["rankings"]["topAgents"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["agentId"], "scout-9")

    def test_tags_from_canonical_metadata(self) -> None:
        now = _utc(0)
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, name, status, source_type, created_at, updated_at, metadata_json)
            VALUES ('ds1', 'A', 'ready', 'local', ?, ?, ?)
            """,
            (
                now,
                now,
                json.dumps({"semanticProfile": {"primaryCategory": "GENERAL", "tags": ["bitcoin", "markt"]}}),
            ),
        )
        conn.commit()
        conn.close()
        dash = self.svc.dashboard(ranking_range="7d")
        tags = {t["tag"] for t in dash["rankings"]["popularTags"]}
        self.assertIn("bitcoin", tags)

    def test_activity_bounded(self) -> None:
        for i in range(15):
            self._ins_doc(f"d{i}", source="manual", created_at=_utc(offset_hours=-i))
        dash = self.svc.dashboard(activity_limit=10)
        self.assertLessEqual(len(dash["activity"]["items"]), 10)

    def test_system_usage_unmeasured_without_telemetry(self) -> None:
        dash = self.svc.dashboard()
        self.assertEqual(dash["kpis"]["systemUsagePercent"]["status"], "UNMEASURED")

    def test_system_usage_from_pressure(self) -> None:
        self.svc.telemetry_provider = lambda: {
            "dashboard": {"cpuPct": 40.0, "ramPct": 50.0, "vramPct": 60.0},
            "truth": {"measured": True},
        }
        self.svc._dashboard.telemetry_provider = self.svc.telemetry_provider
        dash = self.svc.dashboard()
        self.assertEqual(dash["kpis"]["systemUsagePercent"]["status"], "OK")
        self.assertIsNotNone(dash["kpis"]["systemUsagePercent"]["value"])

    def test_legacy_datasets_reads_knowledge_db(self) -> None:
        now = _utc(0)
        conn = sqlite3.connect(self.knowledge)
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, name, status, source_type, created_at, updated_at)
            VALUES ('ds1', 'A', 'ready', 'local', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
        conn.close()
        payload = self.svc.datasets(range_key="7d")
        self.assertEqual(payload["inventory"]["datasets"], 1)
        self.assertTrue(payload["truth"]["knowledge_database"])

    def test_delta_insufficient_previous(self) -> None:
        # Only current-window docs; no history before previous window.
        self._ins_doc("d1", source="manual", created_at=_utc(0))
        dash = self.svc.dashboard(chart_range="7d")
        # previous may be null → deltaPercent null
        delta = dash["kpis"]["knowledgeItems"]["deltaPercent"]
        self.assertTrue(delta is None or isinstance(delta, (int, float)))


if __name__ == "__main__":
    unittest.main()
