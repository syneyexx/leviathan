"""Memory FTS candidate retrieval preserves scope/forget/supersession contracts."""

from __future__ import annotations

import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database


def rank_memories(database: Database, query: str, limit: int = 6) -> list[dict]:
    query_tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", query.lower()))
    ranked: list[tuple[float, dict]] = []
    for item in database.search_memory_candidates(query, limit=max(48, limit * 8)):
        document = f"{item['title']} {item['summary']} {item['content']} {' '.join(item['tags'])}".lower()
        document_tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", document))
        overlap = len(query_tokens & document_tokens)
        title_bonus = 2 if any(token in item["title"].lower() for token in query_tokens) else 0
        score = (overlap + title_bonus) / max(1, len(query_tokens) + 1)
        if score > 0:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [{**item, "score": round(min(1.0, score), 3)} for score, item in ranked[:limit]]


def _memory_in_retrieval_scope(item: dict, *, conversation_id: str | None = None) -> bool:
    scope = str(item.get("scope") or "project")
    if scope in {"project", "global", ""}:
        return True
    if scope != "session":
        return True
    if not conversation_id:
        return False
    tags = item.get("tags") or []
    if isinstance(tags, str):
        return conversation_id in tags
    return conversation_id in {str(tag) for tag in tags}


class MemoryFtsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(str(Path(self.temp_dir.name) / "mem.db"))
        self.database.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fts_finds_needle_without_scanning_unrelated(self) -> None:
        for i in range(80):
            self.database.save_memory({
                "title": f"noise {i}",
                "content": f"irrelevant filler document {i} lorem ipsum",
                "summary": "noise",
                "collection": "Tests",
                "tags": ["noise"],
            })
        hit = self.database.save_memory({
            "title": "Endpoint",
            "content": "Endpoint is poort 2222",
            "summary": "config",
            "collection": "Tests",
            "tags": ["config"],
        })
        started = time.perf_counter()
        ranked = rank_memories(self.database, "Endpoint poort", limit=6)
        elapsed_ms = (time.perf_counter() - started) * 1000
        ids = {item["id"] for item in ranked}
        self.assertIn(hit["id"], ids)
        candidates = self.database.search_memory_candidates("Endpoint", limit=10)
        self.assertTrue(any(item["id"] == hit["id"] for item in candidates))
        print("MEMORY_FTS_RANK_MS", round(elapsed_ms, 3), "candidates", len(candidates))
        started_linear = time.perf_counter()
        linear = self.database.list_memories(limit=1000)
        linear_ms = (time.perf_counter() - started_linear) * 1000
        self.assertGreater(len(linear), len(candidates))
        print("MEMORY_LINEAR_LIST_MS", round(linear_ms, 3), "rows", len(linear))

    def test_fts_beats_python_scan_on_larger_collection(self) -> None:
        now = "2026-01-01T00:00:00+00:00"
        with self.database.connection() as db:
            rows = []
            for i in range(1500):
                rows.append(
                    (
                        f"mem_{i:04d}",
                        f"noise {i}",
                        f"irrelevant filler document {i} lorem ipsum dolor",
                        "noise",
                        "Tests",
                        "[]",
                        "Unittest",
                        "general",
                        "active",
                        0.8,
                        0.5,
                        now,
                        now,
                    )
                )
            db.executemany(
                """INSERT INTO memories(id,title,content,summary,collection,tags,source,memory_type,status,confidence,importance,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            self.database._ensure_memory_fts(db)
            self.database._rebuild_memory_fts(db)
        needle = self.database.save_memory({
            "title": "Endpoint",
            "content": "Endpoint is poort 9999 unique-needle-zzz",
            "summary": "config",
            "collection": "Tests",
            "tags": ["config"],
        })
        t0 = time.perf_counter()
        fts_hits = self.database.search_memory_candidates("unique-needle-zzz", limit=8)
        fts_ms = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        scanned = self.database.list_memories(limit=5000)
        python_hits = [item for item in scanned if "unique-needle-zzz" in item["content"]]
        scan_ms = (time.perf_counter() - t1) * 1000
        self.assertTrue(any(item["id"] == needle["id"] for item in fts_hits))
        self.assertTrue(any(item["id"] == needle["id"] for item in python_hits))
        print("MEMORY_FTS_1500_MS", round(fts_ms, 3), "LINEAR_SCAN_1500_MS", round(scan_ms, 3), "rows", len(scanned))
        self.assertLess(fts_ms, scan_ms)

    def test_forgotten_and_superseded_are_not_retrieved(self) -> None:
        old = self.database.save_memory({
            "title": "Endpoint",
            "content": "Endpoint is poort 1111",
            "summary": "old",
            "collection": "Tests",
            "tags": ["config"],
        })
        new = self.database.supersede_memory(old["id"], {
            "title": "Endpoint",
            "content": "Endpoint is poort 2222",
            "summary": "new",
            "collection": "Tests",
            "tags": ["config"],
        })
        ranked = rank_memories(self.database, "Endpoint", limit=6)
        self.assertEqual([item["id"] for item in ranked], [new["id"]])
        self.database.forget_memory(new["id"])
        ranked2 = rank_memories(self.database, "Endpoint", limit=6)
        self.assertEqual(ranked2, [])

    def test_session_scope_still_filters_in_rank(self) -> None:
        session = self.database.save_memory({
            "title": "session note",
            "content": "secret session alpha",
            "summary": "s",
            "collection": "Tests",
            "tags": ["conv_abc"],
            "scope": "session",
        })
        project = self.database.save_memory({
            "title": "project note",
            "content": "secret project alpha",
            "summary": "p",
            "collection": "Tests",
            "tags": ["project"],
            "scope": "project",
        })
        items = rank_memories(self.database, "alpha", limit=8)
        scoped = [item for item in items if _memory_in_retrieval_scope(item, conversation_id="conv_abc")]
        ids = {item["id"] for item in scoped}
        self.assertIn(session["id"], ids)
        self.assertIn(project["id"], ids)
        scoped_other = [item for item in items if _memory_in_retrieval_scope(item, conversation_id="other")]
        other_ids = {item["id"] for item in scoped_other}
        self.assertNotIn(session["id"], other_ids)
        self.assertIn(project["id"], other_ids)

    def test_main_rank_memories_uses_fts_candidates(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("search_memory_candidates", source)
        self.assertNotIn("for item in database.list_memories(limit=1000):", source)


if __name__ == "__main__":
    unittest.main()
