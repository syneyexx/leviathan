from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_brain_preflight import DatasetBrainStorageError, estimate_hf_split_size, preflight_hf_disk


class _Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Client:
    payload = None
    status_code = 200

    def __init__(self, *args, **kwargs) -> None:
        self.headers = kwargs.get("headers") or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None):
        return _Response(self.payload, self.status_code)


class DatasetBrainPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = {
            "source": {
                "dataset_id": "example/corpus",
                "config": "default",
                "split": "train",
            }
        }

    def _full_payload(self, *, memory_bytes: int = 1024, parquet_bytes: int = 512):
        return {
            "size": {
                "splits": [
                    {
                        "dataset": "example/corpus",
                        "config": "default",
                        "split": "train",
                        "num_bytes_memory": memory_bytes,
                        "num_bytes_parquet_files": parquet_bytes,
                        "num_rows": 42,
                    }
                ]
            },
            "partial": False,
            "pending": [],
            "failed": [],
        }

    def test_complete_size_selects_requested_split(self) -> None:
        _Client.payload = self._full_payload(memory_bytes=4096, parquet_bytes=2048)
        _Client.status_code = 200
        with patch("dataset_brain_preflight.httpx.Client", _Client):
            result = estimate_hf_split_size(self.dataset, token="hf_secret")
        self.assertTrue(result["known"])
        self.assertEqual(result["estimated_bytes"], 4096)
        self.assertEqual(result["num_rows"], 42)

    def test_partial_size_is_never_treated_as_complete(self) -> None:
        payload = self._full_payload(memory_bytes=10_000)
        payload["partial"] = True
        _Client.payload = payload
        _Client.status_code = 200
        with patch("dataset_brain_preflight.httpx.Client", _Client):
            result = estimate_hf_split_size(self.dataset)
        self.assertFalse(result["known"])
        self.assertEqual(result["reason"], "partial_size")

    def test_unavailable_size_endpoint_degrades_to_unknown(self) -> None:
        class _BrokenClient(_Client):
            def get(self, url, params=None):
                raise httpx.ConnectError("offline")

        with patch("dataset_brain_preflight.httpx.Client", _BrokenClient):
            result = estimate_hf_split_size(self.dataset)
        self.assertFalse(result["known"])
        self.assertEqual(result["reason"], "size_endpoint_unavailable")

    def test_complete_estimate_blocks_provably_insufficient_disk(self) -> None:
        gib = 1024**3
        _Client.payload = self._full_payload(memory_bytes=20 * gib, parquet_bytes=10 * gib)
        _Client.status_code = 200
        usage = type("Usage", (), {"free": 12 * gib})()
        with tempfile.TemporaryDirectory() as tmp, (
            patch("dataset_brain_preflight.httpx.Client", _Client),
            patch("dataset_brain_preflight.shutil.disk_usage", return_value=usage),
        ):
            with self.assertRaisesRegex(DatasetBrainStorageError, "Onvoldoende vrije schijfruimte"):
                preflight_hf_disk(Path(tmp), self.dataset)

    def test_partial_estimate_does_not_fabricate_hard_requirement(self) -> None:
        payload = self._full_payload(memory_bytes=100 * 1024**3)
        payload["partial"] = True
        _Client.payload = payload
        _Client.status_code = 200
        usage = type("Usage", (), {"free": 6 * 1024**3})()
        with tempfile.TemporaryDirectory() as tmp, (
            patch("dataset_brain_preflight.httpx.Client", _Client),
            patch("dataset_brain_preflight.shutil.disk_usage", return_value=usage),
        ):
            result = preflight_hf_disk(Path(tmp), self.dataset)
        self.assertFalse(result["known"])
        self.assertIsNone(result["required_bytes"])


if __name__ == "__main__":
    unittest.main()
