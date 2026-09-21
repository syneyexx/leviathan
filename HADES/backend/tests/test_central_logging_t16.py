"""T16/F-33: every 5xx carries a trace_id that appears in the application log."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from errors.http_errors import TraceCorrelationMiddleware, install_api_error_handlers
from errors.logging_setup import configure_hades_logging, find_trace_in_log, hades_log_path
from errors.taxonomy import ErrorCode, HadesError


class CentralLoggingT16Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        self.log_path = configure_hades_logging(self.root, level="INFO", force=True)
        self.app = FastAPI()
        self.app.add_middleware(TraceCorrelationMiddleware)
        install_api_error_handlers(self.app)

        @self.app.get("/boom")
        def boom() -> None:
            raise RuntimeError("intentional unhandled failure")

        @self.app.get("/http500")
        def http500() -> None:
            raise HTTPException(status_code=500, detail="synthetic_server_error")

        @self.app.get("/hades500")
        def hades500() -> None:
            raise HadesError(code=ErrorCode.INTERNAL_ERROR, message="taxonomy_internal")

        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _assert_trace_in_body_and_log(self, response) -> str:
        self.assertEqual(response.status_code, 500)
        body = response.json()
        trace_id = body.get("trace_id") or (body.get("detail") or {}).get("trace_id")
        self.assertTrue(trace_id, body)
        self.assertEqual(response.headers.get("X-Trace-Id"), trace_id)
        # Handlers flush via logging; RotatingFileHandler writes immediately.
        logging_root = __import__("logging").getLogger()
        for handler in logging_root.handlers:
            if getattr(handler, "_hades_owned", False):
                handler.flush()
        self.assertTrue(
            find_trace_in_log(self.log_path, str(trace_id)),
            f"trace_id {trace_id!r} missing from {self.log_path}",
        )
        self.assertEqual(hades_log_path(self.root), self.log_path)
        return str(trace_id)

    def test_unhandled_exception_5xx_trace_id_in_log(self) -> None:
        response = self.client.get("/boom")
        self._assert_trace_in_body_and_log(response)
        self.assertIn("INTERNAL_ERROR", response.json().get("error_code", ""))

    def test_http_exception_5xx_trace_id_in_log(self) -> None:
        response = self.client.get("/http500")
        self._assert_trace_in_body_and_log(response)
        body = response.json()
        self.assertIn("synthetic_server_error", str(body.get("detail") or body.get("message") or body))

    def test_hades_error_5xx_trace_id_in_log(self) -> None:
        response = self.client.get("/hades500")
        self._assert_trace_in_body_and_log(response)
        self.assertEqual(response.json().get("code"), "INTERNAL_ERROR")

    def test_incoming_trace_id_header_is_honored(self) -> None:
        fixed = "t16-fixed-trace-id-001"
        response = self.client.get("/boom", headers={"X-Trace-Id": fixed})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json().get("trace_id"), fixed)
        self.assertEqual(response.headers.get("X-Trace-Id"), fixed)
        logging_root = __import__("logging").getLogger()
        for handler in logging_root.handlers:
            if getattr(handler, "_hades_owned", False):
                handler.flush()
        self.assertTrue(find_trace_in_log(self.log_path, fixed))


if __name__ == "__main__":
    unittest.main()
