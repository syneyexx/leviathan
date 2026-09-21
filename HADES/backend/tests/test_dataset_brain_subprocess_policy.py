from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataset_brain_routes import mount_dataset_brain_routes


class _FakeDatabase:
    def __init__(self, path: Path, *, subprocess_policy: str) -> None:
        self.path = path
        self.subprocess_policy = subprocess_policy

    def get_settings(self) -> dict[str, object]:
        return {
            "network_policy": "allow",
            "file_read_policy": "allow",
            "subprocess_policy": self.subprocess_policy,
        }


class DatasetBrainSubprocessPolicyTests(unittest.TestCase):
    def _exercise(self, subprocess_policy: str, *, approved_subprocess: bool) -> tuple[object, MagicMock]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fake_brain = MagicMock()
        fake_brain.workspace = SimpleNamespace(
            get_dataset=MagicMock(return_value={"id": "ds_test", "source_type": "local"})
        )
        fake_brain.status.return_value = {"materialized_complete": True}
        fake_brain.create_job.return_value = {"id": "brain_fake", "status": "running"}

        app = FastAPI()
        database = _FakeDatabase(Path(temp.name) / "hades.db", subprocess_policy=subprocess_policy)
        app.include_router(mount_dataset_brain_routes({"database": database}), prefix="/api")
        client = TestClient(app)

        with patch(
            "dataset_brain_routes.DatasetBrainManager.from_database",
            return_value=fake_brain,
        ):
            response = client.post(
                "/api/training/brain/datasets/ds_test/index",
                json={"approved_subprocess": approved_subprocess},
            )
        return response, fake_brain

    def test_block_cannot_be_overridden_by_request_approval(self) -> None:
        response, fake_brain = self._exercise("block", approved_subprocess=True)
        self.assertEqual(response.status_code, 403)
        fake_brain.create_job.assert_not_called()

    def test_ask_requires_explicit_subprocess_approval(self) -> None:
        response, fake_brain = self._exercise("ask", approved_subprocess=False)
        self.assertEqual(response.status_code, 409)
        fake_brain.create_job.assert_not_called()

    def test_ask_allows_explicit_subprocess_approval(self) -> None:
        response, fake_brain = self._exercise("ask", approved_subprocess=True)
        self.assertEqual(response.status_code, 201, response.text)
        fake_brain.create_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
