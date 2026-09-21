from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import training_service
from training_service import TrainingWorkspace


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 424242
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class TrainingSpawnPersistenceTests(unittest.TestCase):
    def test_spawned_worker_is_not_left_running_when_pid_state_cannot_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = TrainingWorkspace(Path(temp_dir) / "training")
            dataset_id = "ds_0123456789abcdef"
            dataset_dir = workspace.datasets_dir / dataset_id
            dataset_dir.mkdir(parents=True, exist_ok=False)
            (dataset_dir / "dataset.json").write_text(
                json.dumps(
                    {
                        "id": dataset_id,
                        "name": "fixture",
                        "source_type": "local",
                        "status": "ready",
                        "format": "jsonl",
                        "path": str(Path(temp_dir) / "fixture.jsonl"),
                        "columns": ["text"],
                        "mapping": {"text_field": "text"},
                        "created_at": "2026-09-13T00:00:00+00:00",
                        "updated_at": "2026-09-13T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            fake_process = _FakeProcess()
            real_atomic = training_service._atomic_write_json
            calls = {"count": 0}

            def fail_second_atomic(path: Path, payload: dict) -> None:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated job-state persistence failure")
                real_atomic(path, payload)

            capabilities = {
                "trainer_ready": True,
                "required_packages": ["torch", "transformers", "datasets", "peft", "accelerate"],
                "packages": {
                    "torch": {"available": True},
                    "transformers": {"available": True},
                    "datasets": {"available": True},
                    "peft": {"available": True},
                    "accelerate": {"available": True},
                    "bitsandbytes": {"available": True},
                },
            }

            with patch.object(workspace, "capabilities", return_value=capabilities), \
                 patch("training_service.subprocess.Popen", return_value=fake_process), \
                 patch("training_service._atomic_write_json", side_effect=fail_second_atomic):
                with self.assertRaises(OSError):
                    workspace.create_job(dataset_id=dataset_id, base_model="fixture/model")

            self.assertTrue(
                fake_process.terminated or fake_process.killed,
                "worker must be stopped if its PID/running state could not be persisted",
            )


if __name__ == "__main__":
    unittest.main()
