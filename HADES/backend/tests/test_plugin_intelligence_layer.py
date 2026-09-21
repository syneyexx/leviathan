from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from platform_db import PlatformDatabase

from plugin_knowledge_index import (
    knowledge_fast_path_result,
    reindex_plugin,
    remove_plugin_index,
    search_plugin_knowledge,
)
from plugin_registry_cache import (
    begin_request_cache,
    cached_list_plugins,
    end_request_cache,
    invalidate_plugin_registry_cache,
    registry_generation,
)
from reasoning.tool_engine import normalize_tool_result_status, observation_payload
from reasoning.tool_observation_budget import build_bounded_tool_observation
from reasoning.tools import observation_from_invoke_result
from tool_result_cache import (
    cache_key,
    clear_tool_result_cache,
    get_cached_result,
    store_cached_result,
    tool_invocation_cacheable,
)


class PluginKnowledgeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "platform.db"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_plugin(self, plugin_id: str = "demo") -> dict:
        root = Path(self.tmp.name) / plugin_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_text("Alpha search plugin documents weather queries.", encoding="utf-8")
        (root / "hades-plugin.json").write_text(
            json.dumps({"name": "Demo", "version": "1.0.0", "knowledge_paths": ["README.md"]}),
            encoding="utf-8",
        )
        plugin = {
            "id": plugin_id,
            "local_path": str(root),
            "manifest": {"name": "Demo", "version": "1.0.0", "knowledge_paths": ["README.md"]},
        }
        return plugin

    def test_index_incremental_and_fts(self) -> None:
        plugin = self._write_plugin()
        first = reindex_plugin(self.db, plugin)
        self.assertGreaterEqual(first["indexed"], 1)
        second = reindex_plugin(self.db, plugin)
        self.assertEqual(second["indexed"], 0)
        Path(plugin["local_path"], "README.md").write_text("Beta updated plugin docs.", encoding="utf-8")
        third = reindex_plugin(self.db, plugin)
        self.assertGreaterEqual(third["indexed"], 1)
        hits = search_plugin_knowledge(self.db, "Beta updated", plugin_id="demo")
        self.assertTrue(hits)
        self.assertIn("Beta", hits[0]["excerpt"])

    def test_invalidation_on_remove(self) -> None:
        plugin = self._write_plugin("rm")
        reindex_plugin(self.db, plugin)
        self.assertTrue(search_plugin_knowledge(self.db, "Alpha", plugin_id="rm"))
        remove_plugin_index(self.db, "rm")
        self.assertFalse(search_plugin_knowledge(self.db, "Alpha", plugin_id="rm"))

    def test_knowledge_fast_path_without_subprocess(self) -> None:
        plugin = self._write_plugin("fast")
        reindex_plugin(self.db, plugin)
        tool = {
            "name": "search_docs",
            "metadata": {"static_knowledge": True, "action": "search"},
            "input_schema": {"type": "object"},
        }
        result = knowledge_fast_path_result(self.db, plugin, tool, {"query": "weather"})
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "completed")
        structured = result.get("structured_output") or {}
        self.assertEqual(structured.get("source"), "plugin_knowledge_index")


class ToolObservationBudgetTests(unittest.TestCase):
    def test_total_budget_preserves_failure_truth(self) -> None:
        row = {
            "status": "failed",
            "error": "boom",
            "exit_code": 2,
            "stderr": "E" * 5000,
            "stdout": "O" * 5000,
            "structured_output": {"detail": "x" * 5000, "knowledge_updated": True},
        }
        normalized = normalize_tool_result_status(row)
        payload = build_bounded_tool_observation(normalized, max_chars=400)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "boom")
        self.assertNotIn("knowledge_updated", (payload.get("structured_output") or {}))
        self.assertTrue(payload.get("_truncation", {}).get("truncated"))

    def test_structured_output_in_model_observation(self) -> None:
        result = {
            "status": "completed",
            "exit_code": 0,
            "stdout": "ok",
            "structured_output": {"rows": [1, 2], "success": True},
        }
        normalized = normalize_tool_result_status(result)
        text = observation_payload(normalized, limit=10_000)
        parsed = json.loads(text)
        self.assertIn("structured_output", parsed)
        self.assertEqual(parsed["structured_output"]["rows"], [1, 2])
        self.assertNotIn("success", parsed["structured_output"])

    def test_observation_from_invoke_result_v2(self) -> None:
        obs = observation_from_invoke_result(
            plugin_id="p",
            tool_name="t",
            result={"status": "completed", "structured_output": {"value": 1}},
            tool_result_max_chars=5000,
        )
        self.assertEqual(obs.structured_output, {"value": 1})


class RegistryAndToolCacheTests(unittest.TestCase):
    def test_request_scoped_registry_cache(self) -> None:
        calls = {"n": 0}

        def list_plugins() -> list[dict[str, Any]]:
            calls["n"] += 1
            return [{"id": "a"}]

        begin_request_cache()
        try:
            self.assertEqual(cached_list_plugins(list_plugins)[0]["id"], "a")
            cached_list_plugins(list_plugins)
            self.assertEqual(calls["n"], 1)
        finally:
            end_request_cache()

        gen_before = registry_generation()
        invalidate_plugin_registry_cache()
        self.assertGreater(registry_generation(), gen_before)

    def test_read_cache_hit_miss_and_write_not_cached(self) -> None:
        clear_tool_result_cache()
        plugin = {"id": "p", "permissions": ["subprocess"], "capabilities": {"effects": []}}
        read_tool = {"name": "get", "metadata": {"action": "get"}}
        write_tool = {"name": "save", "metadata": {"action": "write"}}
        self.assertTrue(tool_invocation_cacheable(plugin, read_tool))
        self.assertFalse(tool_invocation_cacheable(plugin, write_tool))
        key = cache_key("p", "get", {"id": 1})
        self.assertIsNone(get_cached_result(key))
        store_cached_result(key, {"status": "completed", "stdout": "cached"})
        hit = get_cached_result(key)
        self.assertIsNotNone(hit)
        self.assertTrue((hit or {}).get("_tool_result_cache", {}).get("hit") is False)
        fail_key = cache_key("p", "get", {"id": 2})
        store_cached_result(fail_key, {"status": "failed", "error": "nope"})
        self.assertIsNone(get_cached_result(fail_key))


if __name__ == "__main__":
    unittest.main()
