from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_brain_worker import _iter_hf_rows, _iter_hf_viewer_rows


class _BrokenAfterSkipStream:
    def __init__(self) -> None:
        self.skipped = None

    def skip(self, count: int):
        self.skipped = count
        return self

    def __iter__(self):
        raise RuntimeError("stream failed before first resumed row")
        yield  # pragma: no cover


class _Response:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return _Response(self.payload)


class DatasetBrainHuggingFaceResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = {
            "source": {
                "dataset_id": "example/corpus",
                "config": "default",
                "split": "train",
            }
        }

    def test_viewer_fallback_keeps_absolute_resume_offset_after_skip_failure(self) -> None:
        stream = _BrokenAfterSkipStream()
        fake_datasets = types.ModuleType("datasets")
        fake_datasets.load_dataset = lambda *args, **kwargs: stream  # type: ignore[attr-defined]

        with (
            patch.dict(sys.modules, {"datasets": fake_datasets}),
            patch("dataset_brain_worker.importlib.util.find_spec", return_value=object()),
            patch(
                "dataset_brain_worker._iter_hf_viewer_rows",
                return_value=iter([{"text": "row-from-checkpoint"}]),
            ) as viewer,
        ):
            rows = list(_iter_hf_rows(self.dataset, 5, None))

        self.assertEqual(stream.skipped, 5)
        self.assertEqual(rows, [{"text": "row-from-checkpoint"}])
        viewer.assert_called_once_with(self.dataset, 5, None)

    def test_partial_viewer_response_is_rejected(self) -> None:
        payload = {
            "partial": True,
            "rows": [{"row": {"text": "incomplete"}, "truncated_cells": []}],
            "num_rows_total": 1000,
        }
        with patch("dataset_brain_worker.httpx.Client", side_effect=lambda *a, **k: _Client(payload)):
            with self.assertRaisesRegex(RuntimeError, "partial=true"):
                list(_iter_hf_viewer_rows(self.dataset, 0, None))

    def test_truncated_viewer_cells_are_rejected(self) -> None:
        payload = {
            "partial": False,
            "rows": [
                {
                    "row": {"text": "incomplete"},
                    "truncated_cells": [{"column": "text"}],
                }
            ],
            "num_rows_total": 1,
        }
        with patch("dataset_brain_worker.httpx.Client", side_effect=lambda *a, **k: _Client(payload)):
            with self.assertRaisesRegex(RuntimeError, "cellen afgekapt"):
                list(_iter_hf_viewer_rows(self.dataset, 0, None))


if __name__ == "__main__":
    unittest.main()
