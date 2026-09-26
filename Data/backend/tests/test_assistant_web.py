"""GI7 — web.search / web.fetch via WebResearchProvider; no fabrications."""

from __future__ import annotations

import unittest
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.function_runtime import build_default_registry
from Data.modules.research.web import HttpWebProvider, UnconfiguredWebProvider
from Data.modules.research.web_capabilities import (
    bind_web_provider,
    execute_web_fetch,
    execute_web_search,
)


class WebSearchHonestyTests(unittest.TestCase):
    def tearDown(self) -> None:
        bind_web_provider(None, allow_outbound=False)

    def test_search_unavailable_when_unconfigured(self) -> None:
        bind_web_provider(
            UnconfiguredWebProvider(),
            allow_outbound=False,
            allow_web=True,
        )
        out = execute_web_search("leviathan architecture", limit=3)
        self.assertEqual(out["status"], "UNAVAILABLE")
        self.assertEqual(out["error_code"], "WEB_SEARCH_UNAVAILABLE")
        self.assertEqual(out["results"], [])
        self.assertFalse(out["truth"]["fabricated"])
        self.assertTrue(out["truth"].get("not_configured"))

    def test_search_unavailable_when_outbound_without_endpoint(self) -> None:
        provider = HttpWebProvider(allow_outbound=True, search_endpoint=None)
        bind_web_provider(provider, allow_outbound=True, allow_web=True)
        out = execute_web_search("anything")
        self.assertEqual(out["status"], "UNAVAILABLE")
        self.assertEqual(out["error_code"], "WEB_SEARCH_UNAVAILABLE")
        self.assertEqual(out["results"], [])
        self.assertTrue(out["truth"]["direct_fetch_may_still_work"])

    def test_search_returns_real_json_results(self) -> None:
        provider = HttpWebProvider(
            allow_outbound=True,
            search_endpoint="https://search.example/api",
            search_provider="generic",
        )
        bind_web_provider(provider, allow_outbound=True)

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {
                    "results": [
                        {
                            "title": "Real Hit",
                            "url": "https://example.com/doc",
                            "snippet": "measured",
                        },
                        {"title": "No URL", "snippet": "skip"},
                    ]
                }

        with mock.patch("Data.modules.research.web.assert_safe_url"), mock.patch(
            "Data.modules.research.web.validate_url_for_fetch",
            return_value=mock.Mock(allowed=True),
        ), mock.patch("httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.get.return_value = _Resp()
            out = execute_web_search("real query", limit=5)

        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["title"], "Real Hit")
        self.assertEqual(out["results"][0]["url"], "https://example.com/doc")
        self.assertFalse(out["truth"]["fabricated"])

    def test_search_never_invents_empty_provider_hits(self) -> None:
        provider = HttpWebProvider(
            allow_outbound=True,
            search_endpoint="https://search.example/api",
        )
        bind_web_provider(provider, allow_outbound=True)

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {"results": []}

        with mock.patch("Data.modules.research.web.assert_safe_url"), mock.patch(
            "httpx.Client"
        ) as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.get.return_value = _Resp()
            out = execute_web_search("no hits")

        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["results"], [])
        self.assertEqual(out["count"], 0)


class WebFetchTests(unittest.TestCase):
    def tearDown(self) -> None:
        bind_web_provider(None, allow_outbound=False)

    def test_fetch_works_with_mock_httpx_when_search_unconfigured(self) -> None:
        provider = HttpWebProvider(allow_outbound=True, search_endpoint=None)
        bind_web_provider(provider, allow_outbound=True)
        search = execute_web_search("x")
        self.assertEqual(search["error_code"], "WEB_SEARCH_UNAVAILABLE")

        class _Resp:
            status_code = 200
            headers = {"content-type": "text/html; charset=utf-8"}
            content = b"<html><title>Hello</title><body><p>World</p></body></html>"
            url = "https://example.com/page"

        with mock.patch("Data.modules.research.web.assert_safe_url"), mock.patch(
            "httpx.Client"
        ) as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.get.return_value = _Resp()
            out = execute_web_fetch("https://example.com/page")

        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["page"]["title"], "Hello")
        self.assertIn("World", out["page"]["text"])
        self.assertTrue(out["truth"]["search_not_required"])
        self.assertFalse(out["truth"]["fabricated"])

    def test_fetch_blocked_when_outbound_disabled(self) -> None:
        provider = HttpWebProvider(allow_outbound=False)
        bind_web_provider(provider, allow_outbound=False)
        out = execute_web_fetch("https://example.com/")
        self.assertEqual(out["status"], "UNAVAILABLE")
        self.assertEqual(out["error_code"], "WEB_UNAVAILABLE")
        self.assertIn("Outbound", out["error"])

    def test_searxng_adapter_parses_content_field(self) -> None:
        provider = HttpWebProvider(
            allow_outbound=True,
            search_endpoint="https://searx.example/search",
            search_provider="searxng",
        )
        bind_web_provider(provider, allow_outbound=True)

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {
                    "results": [
                        {
                            "title": "Searx Hit",
                            "url": "https://example.com/a",
                            "content": "from searxng",
                        }
                    ]
                }

        with mock.patch("Data.modules.research.web.assert_safe_url"), mock.patch(
            "Data.modules.research.web.validate_url_for_fetch",
            return_value=mock.Mock(allowed=True),
        ), mock.patch("httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.get.return_value = _Resp()
            out = execute_web_search("q", limit=3)

        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["results"][0]["snippet"], "from searxng")
        self.assertIn("searxng", out["results"][0]["provider"])


class WebCatalogTests(unittest.TestCase):
    def test_capabilities_registered(self) -> None:
        catalog = build_default_catalog()
        search = catalog.get("web.search")
        fetch = catalog.get("web.fetch")
        self.assertIsNotNone(search)
        self.assertIsNotNone(fetch)
        assert search is not None and fetch is not None
        self.assertEqual(search.provider_ref, "web_search")
        self.assertEqual(fetch.provider_ref, "web_fetch")
        self.assertEqual(
            classify_capability(
                "web.search",
                metadata=search.metadata,
                provider_kind=search.provider_kind.value,
            ),
            ExecutionWorkloadClass.EXTERNAL_PREFERRED,
        )
        registry = build_default_registry()
        self.assertIn("web_search", registry)
        self.assertIn("web_fetch", registry)

    def test_function_entrypoints(self) -> None:
        bind_web_provider(UnconfiguredWebProvider(), allow_outbound=False)
        from Data.functions.web_search import run as search_run
        from Data.functions.web_fetch import run as fetch_run

        s = search_run(query="test")
        self.assertEqual(s["error_code"], "WEB_SEARCH_UNAVAILABLE")
        f = fetch_run(url="https://example.com")
        self.assertEqual(f["status"], "UNAVAILABLE")
        bind_web_provider(None, allow_outbound=False)


if __name__ == "__main__":
    unittest.main()
