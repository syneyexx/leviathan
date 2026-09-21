from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from training_routes import mount_training_routes
from training_service import TrainingWorkspace


class _FakeDatabase:
    def __init__(self, path: Path, *, subprocess_policy: str = "block") -> None:
        self.path = path
        self.subprocess_policy = subprocess_policy

    def get_settings(self) -> dict[str, object]:
        return {
            "network_policy": "allow",
            "subprocess_policy": self.subprocess_policy,
        }


def _client(temp_dir: str, *, subprocess_policy: str) -> TestClient:
    app = FastAPI()
    app.include_router(
        mount_training_routes(
            {
                "database": _FakeDatabase(
                    Path(temp_dir) / "hades.db",
                    subprocess_policy=subprocess_policy,
                )
            }
        ),
        prefix="/api",
    )
    return TestClient(app)


class TrainingSubprocessPolicyTests(unittest.TestCase):
    def test_training_job_respects_subprocess_block_before_worker_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir, subprocess_policy="block")
            with patch.object(
                TrainingWorkspace,
                "get_dataset",
                return_value={"id": "ds_test", "source_type": "local", "mapping": {}},
            ), patch.object(
                TrainingWorkspace,
                "create_job",
                return_value={"id": "train_fake", "status": "running"},
            ) as create_job:
                response = client.post(
                    "/api/training/jobs",
                    json={
                        "dataset_id": "ds_test",
                        "base_model": "example/model",
                        "approved_network": True,
                    },
                )

            self.assertEqual(response.status_code, 403)
            create_job.assert_not_called()

    def test_training_job_requires_distinct_subprocess_approval_when_policy_is_ask(self) -> None:
        """Open remainder: `ask` needs a dedicated approved_subprocess request/UI field."""
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir, subprocess_policy="ask")
            with patch.object(
                TrainingWorkspace,
                "get_dataset",
                return_value={"id": "ds_test", "source_type": "local", "mapping": {}},
            ), patch.object(
                TrainingWorkspace,
                "create_job",
                return_value={"id": "train_fake", "status": "running"},
            ) as create_job:
                response = client.post(
                    "/api/training/jobs",
                    json={
                        "dataset_id": "ds_test",
                        "base_model": "example/model",
                        "approved_network": True,
                    },
                )

            self.assertEqual(response.status_code, 409)
            create_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
