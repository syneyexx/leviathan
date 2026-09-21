"""Conversation export redaction tests."""

from __future__ import annotations

import unittest

from conversation_export import export_conversation_markdown, redact_secrets


class ConversationExportTests(unittest.TestCase):
    def test_redacts_bearer_and_api_key(self) -> None:
        text = redact_secrets("Authorization: Bearer SECRETTOKEN123 and api_key=abc")
        self.assertNotIn("SECRETTOKEN123", text)
        self.assertIn("[REDACTED]", text)

    def test_export_includes_turns_and_runs(self) -> None:
        md = export_conversation_markdown(
            {"id": "c1", "title": "Demo"},
            [{"id": "m1", "role": "user", "content": "hallo"}, {"id": "m2", "role": "assistant", "content": "hoi"}],
            runs=[{"run_type": "coding", "run_id": "j1", "status": "completed", "title": "fix"}],
            artifacts=[{"id": "a1", "name": "diff.patch", "mime_type": "text/plain"}],
        )
        self.assertIn("# Demo", md)
        self.assertIn("hallo", md)
        self.assertIn("coding", md)
        self.assertIn("diff.patch", md)


if __name__ == "__main__":
    unittest.main()
