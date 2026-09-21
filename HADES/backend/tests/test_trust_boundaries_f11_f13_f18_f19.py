"""T11 trust-boundary fixes: F-11 peer trust, F-13 redirect SSRF, F-18 tool wrap, F-19 embed delete."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest import mock
from unittest.mock import MagicMock, patch

from database import Database
from embeddings import PersistentEmbeddingIndex
from local_api_trust import (
    LocalApiTrustMiddleware,
    assert_loopback_bind_or_warn,
    is_trusted_peer,
)
from reasoning.tool_protocol import tool_result_message, wrap_untrusted_tool_content
from url_security import safe_public_url
from web_research_service import WebResearchService


class PeerTrustF11Tests(unittest.TestCase):
    def test_non_loopback_peer_rejected(self) -> None:
        self.assertFalse(is_trusted_peer("192.168.1.50"))
        self.assertFalse(is_trusted_peer("10.0.0.8"))
        self.assertTrue(is_trusted_peer("127.0.0.1"))
        self.assertTrue(is_trusted_peer("::1"))
        self.assertTrue(is_trusted_peer("testclient"))

    def test_non_loopback_clients_opt_in(self) -> None:
        with patch.dict(os.environ, {"HADES_ALLOW_NON_LOOPBACK_CLIENTS": "1"}):
            self.assertTrue(is_trusted_peer("192.168.1.50"))

    def test_bind_assert_refuses_without_opt_in(self) -> None:
        with self.assertRaises(RuntimeError):
            assert_loopback_bind_or_warn(bind_host="0.0.0.0")

    def test_bind_assert_warns_with_opt_in(self) -> None:
        with patch.dict(os.environ, {"HADES_ALLOW_NON_LOOPBACK_BIND": "1"}):
            status = assert_loopback_bind_or_warn(bind_host="0.0.0.0")
            self.assertTrue(status["allowed"])
            self.assertTrue(status["warned"])
            self.assertFalse(status["loopback"])

    def test_middleware_rejects_get_from_untrusted_peer(self) -> None:
        """Minimal app: GET is gated by peer IP (F-11), not only mutating methods."""
        app = FastAPI()

        @app.get("/api/settings")
        async def settings() -> dict:
            return {"ok": True}

        app.add_middleware(LocalApiTrustMiddleware, allowed_origins=[])

        with TestClient(app) as client:
            # Trusted TestClient peer succeeds.
            self.assertEqual(client.get("/api/settings").status_code, 200)
            with patch("local_api_trust.is_trusted_peer", return_value=False):
                response = client.get("/api/settings")
            self.assertEqual(response.status_code, 403)
            self.assertIn("peer", response.json().get("detail", "").lower())


class RedirectLoopbackF13Tests(unittest.TestCase):
    def test_safe_public_url_blocks_loopback_redirect_target(self) -> None:
        self.assertIsNone(safe_public_url("http://127.0.0.1:8000/secret", allow_loopback=False))
        self.assertEqual(
            safe_public_url("http://127.0.0.1:8000/docs", allow_loopback=True),
            "http://127.0.0.1:8000/docs",
        )

    def test_web_research_rejects_redirect_to_loopback(self) -> None:
        class FakeResponse:
            def __init__(self, status_code: int, headers: dict[str, str] | None = None, text: str = ""):
                self.status_code = status_code
                self.headers = headers or {}
                self.text = text
                self.url = "https://evil.example/start"

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    raise RuntimeError(f"status {self.status_code}")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url: str):
                if "evil.example" in url:
                    return FakeResponse(302, {"location": "http://127.0.0.1:8000/api/settings"})
                return FakeResponse(200, {"content-type": "text/html"}, "<html>ok</html>")

        service = WebResearchService(MagicMock())
        with (
            mock.patch(
                "url_security.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
            mock.patch("web_research_service.httpx.AsyncClient", FakeClient),
            mock.patch.object(service, "allowed_by_robots", return_value=True),
            mock.patch("url_security.load_network_domain_policy", return_value=([], [], 10)),
        ):
            with self.assertRaises(PermissionError) as ctx:
                asyncio.run(service._get("https://evil.example/start", respect_robots=False))
            self.assertIn("geblokkeerde", str(ctx.exception).lower())


class ToolResultMarkingF18Tests(unittest.TestCase):
    def test_native_and_text_modes_both_wrap_untrusted(self) -> None:
        marker = "HADES TOOLRESULTAAT (onbetrouwbare tooldata)"
        native = tool_result_message(call_id="c1", content='{"ok":true}', mode="native")
        text = tool_result_message(call_id="c1", content='{"ok":true}', mode="text")
        self.assertEqual(native["role"], "tool")
        self.assertIn(marker, native["content"])
        self.assertIn(marker, text["content"])
        self.assertIn(marker, wrap_untrusted_tool_content("raw"))


class EmbeddingDeleteF19Tests(unittest.TestCase):
    def test_delete_memory_marks_embedding_index(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            root = Path(temp_dir.name)
            database = Database(str(root / "mem-del.db"))
            database.initialize()
            index = PersistentEmbeddingIndex(root / "embedding_index.sqlite3")
            index.configure_model("test-embed", dimension=4)

            memory = database.save_memory(
                {
                    "title": "secret",
                    "content": "sensitive payload",
                    "collection": "Algemeen",
                },
                memory_id="mem_test1",
            )
            memory_id = memory["id"]
            source_id = f"memory-{memory_id}"
            index.put_vector(
                source_id=source_id,
                content_hash="h1",
                vector=[0.1, 0.2, 0.3, 0.4],
                role="memory",
            )
            self.assertIsNotNone(index.get_vector(source_id))

            import main as main_mod

            prev_db = main_mod.database
            prev_index = main_mod.embedding_index
            try:
                main_mod.database = database
                main_mod.embedding_index = index
                asyncio.run(main_mod.delete_memory(memory_id))
            finally:
                main_mod.database = prev_db
                main_mod.embedding_index = prev_index

            self.assertTrue(index.is_deleted(source_id))
            self.assertIsNone(index.get_vector(source_id))
            self.assertIsNone(database.get_memory(memory_id))
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
