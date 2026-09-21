import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain_node_detail import build_brain_node_detail
from database import Database
from platform_db import PlatformDatabase


class BrainNodeDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = str(Path(self.temp_dir.name) / "brain-detail.db")
        self.database = Database(path)
        self.database.initialize()
        self.platform_db = PlatformDatabase(path)
        self.platform_db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_knowledge_detail_returns_stored_chunk_content_and_source(self) -> None:
        source = self.platform_db.upsert_knowledge_source(
            title="HADES research bron",
            source_type="web",
            uri="https://example.test/research",
            content_hash="abc123",
            metadata={"topic": "brain-detail"},
            status="ready",
        )
        self.platform_db.replace_knowledge_chunks(
            source["id"],
            source["title"],
            [
                {"heading": "Intro", "content": "Volledige opgeslagen onderzoeksinformatie.", "content_hash": "c1", "token_estimate": 8},
                {"heading": "Conclusie", "content": "Tweede inhoudelijke passage.", "content_hash": "c2", "token_estimate": 6},
            ],
        )

        detail = build_brain_node_detail(
            database=self.database,
            platform_db=self.platform_db,
            node_id=f"knowledge_{source['id']}",
        )

        self.assertEqual(detail["kind"], "knowledge")
        self.assertEqual(detail["source_uri"], "https://example.test/research")
        self.assertFalse(detail["truncated"])
        self.assertEqual([section["title"] for section in detail["sections"]], ["Intro", "Conclusie"])
        self.assertIn("Volledige opgeslagen onderzoeksinformatie.", detail["sections"][0]["content"])
        self.assertEqual(detail["metadata"]["topic"], "brain-detail")

    def test_missing_derived_node_is_not_fabricated(self) -> None:
        with self.assertRaises(KeyError):
            build_brain_node_detail(
                database=self.database,
                platform_db=self.platform_db,
                node_id="knowledge_src_missing",
            )


if __name__ == "__main__":
    unittest.main()
