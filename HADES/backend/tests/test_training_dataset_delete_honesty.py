from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from training_service import TrainingWorkspace


class TrainingDatasetDeleteHonestyTests(unittest.TestCase):
    def test_managed_upload_delete_does_not_claim_success_when_payload_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = TrainingWorkspace(Path(temp_dir) / "training")
            upload = workspace.prepare_upload_path("fixture.jsonl")
            upload.write_text('{"text":"fixture"}\n', encoding="utf-8")
            dataset = workspace.register_local(upload, name="fixture", managed_upload=True)
            metadata_path = workspace._dataset_meta_path(dataset["id"])

            real_unlink = Path.unlink

            def fail_payload_unlink(path: Path, *args, **kwargs):
                if path == upload:
                    raise OSError("simulated payload deletion failure")
                return real_unlink(path, *args, **kwargs)

            failure: ValueError | None = None
            with patch.object(Path, "unlink", new=fail_payload_unlink):
                try:
                    workspace.delete_dataset(dataset["id"])
                except ValueError as exc:
                    failure = exc

            self.assertIsNotNone(failure, "delete must not report success while managed bytes remain")
            self.assertTrue(upload.exists(), "fault injection should leave the managed payload in place")
            self.assertTrue(metadata_path.exists(), "metadata must remain so deletion can be retried safely")


if __name__ == "__main__":
    unittest.main()
