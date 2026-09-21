"""Conversation-scoped coding job route delegates to existing CodingJobStore."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "backend" / "coding_build_routes.py"


class ConversationCodingJobRouteTests(unittest.TestCase):
    def test_route_delegates_without_parallel_engine(self) -> None:
        source = ROUTES.read_text(encoding="utf-8")
        self.assertIn('/conversations/{conversation_id}/coding-jobs', source)
        self.assertIn("build_from_goal_async", source)
        self.assertIn("bind_conversation_run", source)
        self.assertIn('run_type="coding"', source)
        # Must not invent a second CodingAgentService orchestration path here.
        tree = ast.parse(source)
        defs = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.assertIn("register_coding_build_routes", defs)
        self.assertNotIn("class ParallelCodingEngine", source)
        self.assertIn("Thin Chat-scoped coding start", source)


if __name__ == "__main__":
    unittest.main()
