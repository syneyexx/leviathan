from __future__ import annotations

import os
import unittest
from unittest import mock

from pydantic import ValidationError

from config import Settings


class BootstrapConfigValidationTests(unittest.TestCase):
    def test_zero_request_timeout_is_rejected_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {"HADES_REQUEST_TIMEOUT_SECONDS": "0"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_zero_concurrency_is_rejected_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {"HADES_MAX_CONCURRENT_TASKS": "0"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_positive_fractional_timeout_and_positive_concurrency_remain_valid(self) -> None:
        env = {
            "HADES_REQUEST_TIMEOUT_SECONDS": "0.5",
            "HADES_MAX_CONCURRENT_TASKS": "3",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.request_timeout_seconds, 0.5)
        self.assertEqual(settings.max_concurrent_tasks, 3)


if __name__ == "__main__":
    unittest.main()
