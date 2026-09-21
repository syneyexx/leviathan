"""Tests for local STT paste plugin and honest research coverage summaries."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "local-stt-paste"))

from fastapi.testclient import TestClient

import main
from database import Database
from platform_db import PlatformDatabase
from platform_services import PluginManager
from research_coverage import summarize_research_coverage

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "local-stt-paste"


class LocalSttPasteTests(unittest.TestCase):
    def test_transcribe_paste_validates_and_suggests(self) -> None:
        from hades_bridge import transcribe_paste

        empty = transcribe_paste("  ")
        self.assertFalse(empty["ok"])
        ok = transcribe_paste("Maak urgent een samenvatting van Orion-notities")
        self.assertTrue(ok["ok"])
        self.assertIn("Orion", ok["transcript"])
        suggestion = ok["suggestion"]
        assert suggestion is not None
        self.assertEqual(suggestion["priority"], "high")
        self.assertIn("Orion", suggestion["prompt"])

    def test_plugin_invoke_transcribe_paste(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDatabase(str(root / "platform.db"))
            db.initialize()
            source = root / "runtime"
            shutil.copytree(PLUGIN_ROOT, source, ignore=shutil.ignore_patterns("README.md"))
            manager = PluginManager(db, root / "data")
            plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
            db.set_plugin_state(plugin["id"], enabled=True)
            result = manager.invoke(
                plugin["id"],
                "transcribe_paste",
                {"transcript": "Plan een lokale research taak voor HADES"},
                approved_by_user=True,
            )
            self.assertEqual(result["status"], "completed", result.get("error"))
            blob = result.get("stdout") or result.get("output") or ""
            payload = json.loads(blob.strip())
            self.assertTrue(payload["ok"])
            self.assertIn("suggestion", payload)
            self.assertIn("geen ingebouwde asr", payload["suggestion"]["note"].lower())
            self.assertIn("auto_start", payload["suggestion"]["next_step"])


class ResearchCoverageTests(unittest.TestCase):
    def test_summarize_flags_gaps_honestly(self) -> None:
        summary = summarize_research_coverage(
            {
                "id": "rp_test",
                "depth": "expert",
                "status": "needs_more_evidence",
                "allow_web": True,
                "metrics": {
                    "coverage_score": 42,
                    "mastery_target": 90,
                    "source_count": 3,
                    "evidence_chunks": 2,
                    "domain_diversity": 1,
                    "metric_kind": "source_coverage_diversity",
                    "metric_note": "Geen aangetoonde expertise; alleen brondekking/diversiteit.",
                    "status": "needs-more-evidence",
                    "contradictions": ["Bron A ↔ Bron B"],
                },
            }
        )
        self.assertTrue(summary["incomplete"])
        self.assertTrue(summary["needs_more_evidence"])
        self.assertFalse(summary["complete"])
        self.assertGreaterEqual(len(summary["gaps"]), 2)
        self.assertIn("Bron A", summary["contradictions"][0])

    def test_coverage_api_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main.database = Database(str(root / "core.db"))
            main.database.initialize()
            main.platform_db = PlatformDatabase(str(root / "other.db"))
            main.ensure_platform_services()
            main.platform_db.initialize()
            project = main.platform_db.create_research_project(
                "Gap test",
                "Quantum computing",
                "expert",
                False,
                [],
                False,
            )
            main.platform_db.update_research_project(
                project["id"],
                status="needs_more_evidence",
                metrics={
                    "coverage_score": 35,
                    "mastery_target": 90,
                    "source_count": 2,
                    "evidence_chunks": 1,
                    "domain_diversity": 0,
                    "metric_kind": "source_coverage_diversity",
                    "status": "needs-more-evidence",
                },
            )
            with TestClient(main.app) as client:
                response = client.get(f"/api/research/{project['id']}/coverage")
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertTrue(body["incomplete"])
                self.assertTrue(body["needs_more_evidence"])
                self.assertTrue(body["gaps"])


if __name__ == "__main__":
    unittest.main()
