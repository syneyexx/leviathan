"""Conversation pin policy: secret skip + force cannot bypass."""

from __future__ import annotations

import unittest

from conversation_pins import (
    apply_pins_to_working_state,
    filter_pin_paths,
    is_blocked_pin_path,
    pins_from_working_state,
    summarize_pins,
)


class ConversationPinPolicyTests(unittest.TestCase):
    def test_env_and_keys_blocked_even_with_force(self) -> None:
        blocked, reason = is_blocked_pin_path(".env", force=True)
        self.assertTrue(blocked)
        self.assertEqual(reason, "blocked_secret_name")
        blocked2, _ = is_blocked_pin_path("C:/secrets/id_rsa", force=True)
        self.assertTrue(blocked2)
        blocked3, _ = is_blocked_pin_path("private.key", force=True)
        self.assertTrue(blocked3)

    def test_filter_reports_skipped_and_summary(self) -> None:
        result = filter_pin_paths(
            [".env", "README.md", "missing-file-xyz.dat"],
            force=True,
        )
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "blocked_secret_name")
        self.assertTrue(result["skipped"][0]["force_ignored"])
        summary = result["summary"]
        self.assertGreaterEqual(summary["skipped"], 1)
        self.assertIn("skipped", summary["label"])

    def test_summarize_pins_counts(self) -> None:
        summary = summarize_pins(
            [
                {"status": "indexed"},
                {"status": "indexed"},
                {"status": "stale"},
                {"status": "skipped"},
            ]
        )
        self.assertEqual(summary["indexed"], 2)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual(summary["skipped"], 1)

    def test_working_state_pin_roundtrip(self) -> None:
        state, result = apply_pins_to_working_state({}, paths=["README.md", ".env"], force=True)
        self.assertEqual(len(result["skipped"]), 1)
        loaded = pins_from_working_state(state)
        self.assertEqual(loaded["summary"]["skipped"], 1)
        self.assertIn("pins", state)


if __name__ == "__main__":
    unittest.main()
