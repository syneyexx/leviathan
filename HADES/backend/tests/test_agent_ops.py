"""Agent console aggregation and usage extraction unit tests."""

from __future__ import annotations

import unittest

from agent_ops import build_agent_console, extract_usage, is_planned_agent


class AgentOpsTests(unittest.TestCase):
    def test_extract_usage_keeps_missing_as_null(self) -> None:
        self.assertIsNone(extract_usage(None))
        self.assertIsNone(extract_usage({}))
        self.assertIsNone(extract_usage({"usage": {}}))
        usage = extract_usage(
            {
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 2},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                }
            }
        )
        assert usage is not None
        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 8)
        self.assertEqual(usage["total_tokens"], 20)
        self.assertEqual(usage["cached_tokens"], 2)
        self.assertEqual(usage["reasoning_tokens"], 3)
        self.assertIsNone(usage["cost"])

    def test_planned_detection(self) -> None:
        self.assertFalse(is_planned_agent("web_scout", "Web Scout"))
        self.assertFalse(is_planned_agent("voice_specialist", "Voice Specialist"))
        self.assertFalse(is_planned_agent("chat", "Chat Agent"))
        # Legacy (*) marker must not override an implemented contract.
        self.assertFalse(is_planned_agent("web_scout", "Web Scout (*)"))
        # Unknown agent without contract still treated as planned when marked.
        self.assertTrue(is_planned_agent("future_agent_xyz", "Future (*)"))

    def test_console_marks_planned_unavailable_and_missing_usage(self) -> None:
        snapshot = build_agent_console(
            agents=[
                {
                    "id": "chat",
                    "name": "Chat Agent",
                    "role": "chat",
                    "description": "Chat",
                    "reasoning_profile": "adaptive",
                    "enabled": True,
                    "allowed_tools": [],
                    "max_subtasks": 2,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "web_scout",
                    "name": "Web Scout",
                    "role": "web",
                    "description": "Web scout",
                    "reasoning_profile": "high",
                    "enabled": True,
                    "allowed_tools": [],
                    "max_subtasks": 4,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ],
            tasks=[
                {
                    "id": "task_1",
                    "title": "Run chat",
                    "prompt": "Hallo",
                    "agent": "chat",
                    "status": "running",
                    "progress": 40,
                    "error": None,
                    "started_at": "2026-01-01T00:01:00+00:00",
                    "finished_at": None,
                    "updated_at": "2026-01-01T00:02:00+00:00",
                    "created_at": "2026-01-01T00:01:00+00:00",
                    "model_id": "local-model",
                }
            ],
            work_steps=[],
            usage_by_agent={},
            recent_events=[],
            provider_connected=True,
            active_profile={"model_id": "local-model", "temperature": 0.7, "top_p": 0.9, "max_tokens": 2048},
        )
        by_id = {item["id"]: item for item in snapshot["items"]}
        self.assertEqual(by_id["chat"]["status"], "running")
        self.assertEqual(by_id["chat"]["health"], "healthy")
        self.assertFalse(by_id["chat"]["usage"]["known"])
        self.assertIsNone(by_id["chat"]["usage"]["total_tokens"])
        self.assertEqual(by_id["web_scout"]["status"], "idle")
        self.assertFalse(by_id["web_scout"]["planned"])
        self.assertNotIn("(*)", by_id["web_scout"]["name"])
        self.assertTrue(by_id["web_scout"]["controls"]["can_enable"] or by_id["web_scout"]["enabled"])

    def test_failed_agent_and_known_usage(self) -> None:
        snapshot = build_agent_console(
            agents=[
                {
                    "id": "build",
                    "name": "Code / Build Agent",
                    "role": "code",
                    "description": "Build",
                    "reasoning_profile": "maximum",
                    "enabled": True,
                    "allowed_tools": [],
                    "max_subtasks": 6,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            tasks=[
                {
                    "id": "task_fail",
                    "title": "Broken",
                    "prompt": "fail",
                    "agent": "build",
                    "status": "failed",
                    "progress": 0,
                    "error": "timeout",
                    "started_at": "2026-01-01T00:01:00+00:00",
                    "finished_at": "2026-01-01T00:02:00+00:00",
                    "updated_at": "2026-01-01T00:02:00+00:00",
                    "created_at": "2026-01-01T00:01:00+00:00",
                    "model_id": "local-model",
                }
            ],
            work_steps=[],
            usage_by_agent={
                "build": {
                    "requests": 2,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "cached_tokens": None,
                    "reasoning_tokens": None,
                    "cost": None,
                    "known": True,
                }
            },
            recent_events=[],
            provider_connected=False,
            active_profile={"model_id": "local-model"},
        )
        item = snapshot["items"][0]
        self.assertEqual(item["status"], "error")
        self.assertEqual(item["last_error"], "timeout")
        self.assertTrue(item["usage"]["known"])
        self.assertEqual(item["usage"]["total_tokens"], 150)
        self.assertEqual(item["health"], "error")


if __name__ == "__main__":
    unittest.main()
