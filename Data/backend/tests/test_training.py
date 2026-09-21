from __future__ import annotations

import unittest

from Data.modules.training import TrainingJobStatus, TrainingRegistry


class TrainingRegistryTests(unittest.TestCase):
    def test_register_is_not_trained(self) -> None:
        registry = TrainingRegistry()
        job = registry.register(name="demo", objective="fit toy model")
        self.assertEqual(job.status, TrainingJobStatus.REGISTERED)
        self.assertEqual(job.metrics, {})
        self.assertTrue(job.public_dict()["truth"]["registered_is_not_trained"])

    def test_start_unsupported_fails_honestly(self) -> None:
        registry = TrainingRegistry()
        job = registry.register(name="demo", objective="x")
        failed = registry.start_unsupported(job.job_id)
        self.assertEqual(failed.status, TrainingJobStatus.FAILED)
        self.assertIn("not implemented", failed.error or "")


if __name__ == "__main__":
    unittest.main()
