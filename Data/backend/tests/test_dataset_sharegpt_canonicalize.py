"""ShareGPT / conversations.from+value must canonicalize to valid chat records."""

from __future__ import annotations

import unittest

from Data.modules.datasets.canonicalize import dict_to_canonical, normalize_chat_message
from Data.modules.datasets.validation import validate_record, validate_records


class ShareGptCanonicalizeTests(unittest.TestCase):
    def test_normalize_sharegpt_from_value(self) -> None:
        msg = normalize_chat_message({"from": "human", "value": "Hello"})
        self.assertEqual(msg["role"], "user")
        self.assertEqual(msg["content"], "Hello")

    def test_normalize_gpt_alias(self) -> None:
        msg = normalize_chat_message({"from": "gpt", "value": "Hi there"})
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["content"], "Hi there")

    def test_openai_messages_unchanged(self) -> None:
        msg = normalize_chat_message({"role": "user", "content": "ping"})
        self.assertEqual(msg["role"], "user")
        self.assertEqual(msg["content"], "ping")

    def test_blackhat_finetune_conversations_shape_validates(self) -> None:
        """Regression: sumitkumar1st/blackhat_ai_finetune uses conversations+from/value."""
        row = {
            "conversations": [
                {"from": "user", "value": "What's the process for a simple TCP port scan using Nmap?"},
                {
                    "from": "assistant",
                    "value": "You can use the command `nmap -sT -p 1-65535 target.com`.",
                },
            ]
        }
        rec = dict_to_canonical(row, index=0, source="hf-test")
        self.assertTrue(rec.text.strip())
        self.assertEqual(len(rec.messages or []), 2)
        self.assertEqual(rec.messages[0]["role"], "user")
        self.assertEqual(rec.messages[0]["content"][:20], "What's the process f")
        self.assertEqual(rec.messages[1]["role"], "assistant")
        issues = validate_record(rec)
        self.assertEqual(issues, [])

    def test_sharegpt_batch_validation_report_valid(self) -> None:
        rows = [
            {
                "conversations": [
                    {"from": "human", "value": f"Q{i}"},
                    {"from": "gpt", "value": f"A{i}"},
                ]
            }
            for i in range(5)
        ]
        records = [dict_to_canonical(r, index=i, source="sharegpt") for i, r in enumerate(rows)]
        report = validate_records(records)
        self.assertTrue(report["valid"])
        self.assertEqual(report["errorCount"], 0)
        self.assertEqual(report["rowCount"], 5)


if __name__ == "__main__":
    unittest.main()
