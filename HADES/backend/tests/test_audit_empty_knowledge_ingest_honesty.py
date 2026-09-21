"""Empty knowledge ingest must not count as verified success."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class EmptyKnowledgeIngestHonestyTests(unittest.TestCase):
    def test_helper_rejects_zero_chunks(self) -> None:
        from platform_services_core import knowledge_ingest_verified

        self.assertFalse(
            knowledge_ingest_verified({"id": "s1", "status": "ready", "chunks": 0})
        )
        self.assertTrue(
            knowledge_ingest_verified({"id": "s1", "status": "ready", "chunks": 2})
        )

    def test_ingest_text_blank_is_verification_failed(self) -> None:
        from platform_services_core import KnowledgeService

        db = MagicMock()
        svc = KnowledgeService(db=db, data_root=Path("/tmp/hades-empty-ingest"))
        result = svc.ingest_text(
            title="blank",
            text="   \n",
            source_type="note",
            uri="note://blank",
        )
        self.assertEqual(result.get("status"), "verification_failed")
        self.assertEqual(result.get("chunks"), 0)
        self.assertEqual(result.get("error"), "empty_knowledge_text")
        self.assertFalse((result.get("persistence") or {}).get("verification_passed", True))
        db.upsert_knowledge_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
