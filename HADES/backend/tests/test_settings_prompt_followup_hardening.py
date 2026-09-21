"""Focused regressions for network presets and system-prompt hardening.

ADDED_NOT_EXECUTED — GitHub Actions are intentionally not used for this change
because the repository owner reported a billing error.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from control.presets import preset_values
from models_routes import MAX_SYSTEM_PROMPT_CHARS, ModelProfileInput
from reasoning.context import assemble_budgeted_messages
from reasoning.provider_budget import enforce_provider_payload_budget


class NetworkPresetSafetyTests(unittest.TestCase):
    def test_normal_autonomy_presets_explicitly_allow_network(self) -> None:
        for preset_id in ("balanced", "power_user", "maximum_autonomy"):
            with self.subTest(preset_id=preset_id):
                self.assertEqual(preset_values(preset_id).get("network_policy"), "allow")

    def test_safe_preset_keeps_network_blocked(self) -> None:
        self.assertEqual(preset_values("safe").get("network_policy"), "block")


class SystemPromptContractTests(unittest.TestCase):
    def test_model_profile_accepts_prompt_above_legacy_20k_limit(self) -> None:
        prompt = "system policy\n" * 2_000
        self.assertGreater(len(prompt), 20_000)
        model = ModelProfileInput(system_prompt=prompt)
        self.assertEqual(model.system_prompt, prompt)

    def test_model_profile_rejects_storage_payload_above_explicit_ceiling(self) -> None:
        with self.assertRaises(ValidationError):
            ModelProfileInput(system_prompt="x" * (MAX_SYSTEM_PROMPT_CHARS + 1))

    def test_context_budget_never_rewrites_explicit_system_parts(self) -> None:
        system_prompt = "MANDATORY:" + ("x" * 10_000)
        messages, report = assemble_budgeted_messages(
            system_parts=[system_prompt],
            history=[],
            context_items=[],
            user_text="hello",
            max_chars=2_000,
            reserve_output_chars=500,
            protocol_overhead_chars=0,
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], system_prompt)
        self.assertIn("budget_exceeded_unresolved", report.notes)

    def test_provider_budget_never_truncates_protected_system_prompt(self) -> None:
        system_prompt = "MANDATORY:" + ("x" * 10_000)
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "hello"},
                ]
            },
            max_chars=2_000,
            reserve_output_chars=500,
            capacity_source="test",
            allow_truncate=True,
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.overflow)
        self.assertIn("protected_prompt_preserved", decision.notes)
        self.assertEqual(decision.messages[0]["content"], system_prompt)

    def test_provider_budget_may_drop_old_history_without_changing_system_prompt(self) -> None:
        system_prompt = "policy"
        decision = enforce_provider_payload_budget(
            {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "old" * 5_000},
                    {"role": "user", "content": "current"},
                ]
            },
            max_chars=2_500,
            reserve_output_chars=500,
            capacity_source="test",
            allow_truncate=True,
        )
        self.assertTrue(decision.ok)
        self.assertTrue(decision.truncated)
        self.assertEqual(decision.messages[0]["role"], "system")
        self.assertEqual(decision.messages[0]["content"], system_prompt)
        self.assertEqual(decision.messages[-1]["content"], "current")


if __name__ == "__main__":
    unittest.main()
