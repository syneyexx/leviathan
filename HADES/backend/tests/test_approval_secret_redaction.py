from __future__ import annotations

import unittest

from approvals import redact_secrets


class ApprovalSecretRedactionTests(unittest.TestCase):
    def test_compound_secret_keys_are_redacted_without_masking_metrics(self) -> None:
        # Field names are credential-shaped by design; every value below is a
        # synthetic non-credential fixture used only to test masking behavior.
        fixture = "fixture-value"
        payload = {
            "api_key": fixture,
            "openai_api_key": fixture,
            "refresh_token": fixture,
            "client_secret": fixture,
            "signing_private_key": fixture,
            "aws_secret_access_key": fixture,
            "authorization_header": fixture,
            "nested": {
                "hf_token": fixture,
                "max_tokens": 4096,
                "monkey": "ordinary-field",
            },
        }

        redacted = redact_secrets(payload)
        self.assertEqual(redacted["api_key"], "***")
        self.assertEqual(redacted["openai_api_key"], "***")
        self.assertEqual(redacted["refresh_token"], "***")
        self.assertEqual(redacted["client_secret"], "***")
        self.assertEqual(redacted["signing_private_key"], "***")
        self.assertEqual(redacted["aws_secret_access_key"], "***")
        self.assertEqual(redacted["authorization_header"], "***")
        self.assertEqual(redacted["nested"]["hf_token"], "***")
        self.assertEqual(redacted["nested"]["max_tokens"], 4096)
        self.assertEqual(redacted["nested"]["monkey"], "ordinary-field")


if __name__ == "__main__":
    unittest.main()
