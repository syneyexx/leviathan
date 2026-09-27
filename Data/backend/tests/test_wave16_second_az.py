"""Wave 16 second A–Z residual regressions (SECURITY/API/FRONTEND)."""

from __future__ import annotations

import unittest
from unittest import mock

from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.facade import ProviderExecutionClient
from Data.modules.provider_io.policy import ProviderIoSettings


class ApiQueueDepthFailClosedTests(unittest.TestCase):
    def test_queue_depth_read_failure_refuses_submit(self) -> None:
        import tempfile
        from pathlib import Path

        from Data.modules.provider_io.stream_store import ProviderStreamStore

        runtime = mock.Mock()
        runtime.store.list.side_effect = RuntimeError("db busy")
        with tempfile.TemporaryDirectory() as tmp:
            store = ProviderStreamStore(Path(tmp) / "streams.db")
            store.initialize()
            client = ProviderExecutionClient(
                runtime,
                stream_store=store,
                settings=ProviderIoSettings(queue_capacity=8),
            )
            with self.assertRaises(ProviderError) as ctx:
                client.submit(
                    provider="fake",
                    capability="http",
                    payload={"url": "https://example.com"},
                )
            self.assertEqual(ctx.exception.code, ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED)


class KnowledgeSearchHonestyTests(unittest.TestCase):
    def test_knowledge_search_does_not_mask_store_failure_as_empty(self) -> None:
        import Data.backend.main as main

        class _Boom:
            def search(self, *a, **k):
                raise RuntimeError("knowledge schema missing")

        prev_k = main.knowledge
        prev_r = getattr(main, "staged_retriever", None)
        try:
            main.knowledge = _Boom()
            main.staged_retriever = None
            with self.assertRaises(RuntimeError):
                main._knowledge_search("token", limit=3)
        finally:
            main.knowledge = prev_k
            main.staged_retriever = prev_r


class CapabilitySchemaPrivateHostTests(unittest.TestCase):
    def test_chat_capabilities_do_not_expose_allow_private_hosts(self) -> None:
        from Data.modules.execution import build_default_catalog

        catalog = build_default_catalog()
        for cap_id in ("provider.chat.complete", "provider.chat.stream"):
            cap = catalog.get(cap_id)
            self.assertIsNotNone(cap)
            props = (cap.input_schema or {}).get("properties") or {}
            self.assertNotIn("allow_private_hosts", props)


if __name__ == "__main__":
    unittest.main()
