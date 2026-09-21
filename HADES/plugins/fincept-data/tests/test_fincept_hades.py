import io
import json
import os
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fincept_hades as fh


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None, url: str = "https://api.fincept.in/test"):
        self._body = io.BytesIO(body)
        self._status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return self._status

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.last_request = None

    def open(self, request, timeout=None):
        self.last_request = request
        return self.response


class FinceptAdapterTests(unittest.TestCase):
    def test_path_cannot_escape_fixed_host(self):
        for bad in ["https://evil.test/x", "//evil.test/x", "/../x", "/%2e%2e/x", "/x?url=https://evil.test", "/x\\evil"]:
            with self.subTest(bad=bad), self.assertRaises(fh.FinceptError):
                fh._clean_path(bad)

    def test_sensitive_paths_blocked_for_generic_tools(self):
        for bad in ["/user/profile", "/billing/history", "/admin/users"]:
            with self.subTest(bad=bad), self.assertRaises(fh.FinceptError):
                fh._clean_path(bad)
        self.assertEqual(fh._clean_path("/user/profile", allow_sensitive=True), "/user/profile")

    def test_api_key_is_header_only_and_not_echoed(self):
        response = FakeResponse(
            b'{"success":true,"data":{"value":42}}',
            headers={"Content-Type": "application/json", "X-RateLimit-Remaining": "499"},
        )
        opener = FakeOpener(response)
        with patch.dict(os.environ, {"FINCEPT_API_KEY": "fk_user_SUPER_SECRET"}, clear=False), patch.object(fh, "_opener", return_value=opener):
            result = fh._api_request(method="GET", path="/market/test", query={"symbol": "AAPL"}, max_bytes=10_000)
        self.assertTrue(result["ok"])
        self.assertEqual(result["rate_limit"]["remaining"], 499)
        self.assertIn("X-api-key", dict(opener.last_request.header_items()))
        serialized = json.dumps(result)
        self.assertNotIn("SUPER_SECRET", serialized)
        self.assertEqual(result["hades_knowledge"][0]["metadata"]["endpoint"], "/market/test")
        self.assertIn("symbol=AAPL", result["request"]["uri"])

    def test_response_size_is_bounded(self):
        response = FakeResponse(b"x" * 101, headers={"Content-Type": "text/plain"})
        with patch.dict(os.environ, {"FINCEPT_API_KEY": "fk_user_test"}, clear=False), patch.object(fh, "_opener", return_value=FakeOpener(response)):
            with self.assertRaises(fh.FinceptError):
                fh._api_request(method="GET", path="/market/test", query={}, max_bytes=100)

    def test_catalog_filters_docs_without_api_key(self):
        docs = "# Intro\n- [Pricing](https://docs.fincept.in/pricing)\n- [Portfolio Optimization](https://docs.fincept.in/portfolio)\n"
        opener = FakeOpener(FakeResponse(docs.encode(), headers={"Content-Type": "text/plain"}, url=fh.DOCS_INDEX))
        with patch.object(fh, "_opener", return_value=opener):
            args = type("Args", (), {"query": "portfolio", "limit": 10, "timeout": 10})()
            result = fh.command_catalog(args)
        self.assertEqual(len(result["matches"]), 1)
        self.assertIn("Portfolio", result["matches"][0])


if __name__ == "__main__":
    unittest.main()
