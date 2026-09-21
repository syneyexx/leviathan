from __future__ import annotations

import unittest

from reasoning.provider_budget import enforce_provider_payload_budget, estimate_payload_chars


def _assistant_tool_call(argument_size: int = 0) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "plugin__tool",
                    "arguments": '{"payload":"' + ("x" * argument_size) + '"}',
                },
            }
        ],
    }


def _tool_result(size: int = 0) -> dict:
    return {"role": "tool", "tool_call_id": "call_1", "content": "y" * size}


class ProviderBudgetToolHistoryIntegrityTests(unittest.TestCase):
    def test_tool_call_arguments_count_toward_payload_estimate(self) -> None:
        payload = {
            "messages": [
                {"role": "system", "content": "policy"},
                _assistant_tool_call(argument_size=5_000),
                _tool_result(size=10),
            ]
        }
        self.assertGreater(estimate_payload_chars(payload), 5_000)

    def test_old_tool_exchange_is_trimmed_atomically(self) -> None:
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": "policy"},
                    _assistant_tool_call(argument_size=2_000),
                    _tool_result(size=2_000),
                    {"role": "user", "content": "current request"},
                ]
            },
            max_chars=2_000,
            reserve_output_chars=500,
            capacity_source="test",
        )
        self.assertTrue(decision.ok)
        self.assertTrue(decision.truncated)
        self.assertEqual([row.get("role") for row in decision.messages], ["system", "user"])
        self.assertIn("dropped_tool_exchange_atomically", decision.notes)

    def test_mandatory_final_tool_result_never_becomes_orphaned(self) -> None:
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": "policy"},
                    {"role": "user", "content": "older request"},
                    _assistant_tool_call(argument_size=3_000),
                    _tool_result(size=3_000),
                ]
            },
            max_chars=2_000,
            reserve_output_chars=500,
            capacity_source="test",
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.overflow)
        roles = [row.get("role") for row in decision.messages]
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)
        assistant = next(row for row in decision.messages if row.get("role") == "assistant")
        tool = next(row for row in decision.messages if row.get("role") == "tool")
        self.assertEqual(assistant["tool_calls"][0]["id"], tool["tool_call_id"])

    def test_output_reserve_is_not_overridden_by_prompt_floor(self) -> None:
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": "policy"},
                    {"role": "user", "content": "small but mandatory request"},
                ]
            },
            max_chars=700,
            reserve_output_chars=500,
            capacity_source="model_reported",
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.overflow)

    def test_reserve_larger_than_capacity_fails_closed(self) -> None:
        decision = enforce_provider_payload_budget(
            {"messages": [{"role": "system", "content": "policy"}]},
            max_chars=1_000,
            reserve_output_chars=2_000,
            capacity_source="model_reported",
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.overflow)
        self.assertIn("output_reserve_exhausts_capacity", decision.notes)


if __name__ == "__main__":
    unittest.main()
