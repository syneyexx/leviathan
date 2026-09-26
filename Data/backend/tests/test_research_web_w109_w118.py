"""W110–W118 research web provider chain, readiness, and quality gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.research.quality_scorecard import build_quality_scorecard
from Data.modules.research.sources import SourceIngestor
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import ResearchProject, ResearchDepth, ResearchStatus
from Data.modules.research.web import (
    BEST_EFFORT_PUBLIC_PROVIDER,
    ChainedWebProvider,
    DuckDuckGoHtmlSearchProvider,
    HttpWebProvider,
    WebPageContent,
    WebSearchResult,
    build_web_provider,
    web_unavailable_reason,
    _parse_ddg_html_results,
)
from Data.modules.research.web_readiness import build_web_readiness, probe_web_research


DDG_SAMPLE = """
<html><body>
<a class="result__a" href="https://sqlite.org/wal.html">SQLite WAL</a>
<a class="result__snippet" href="https://sqlite.org/wal.html">Write-Ahead Logging</a>
<a class="result__a" href="https://example.com/docs">Example Docs</a>
</body></html>
"""


class ParseDdgHtmlTests(unittest.TestCase):
    def test_parses_real_https_urls(self) -> None:
        items = _parse_ddg_html_results(DDG_SAMPLE, limit=5)
        self.assertGreaterEqual(len(items), 2)
        self.assertTrue(all(i["url"].startswith("https://") for i in items))
        self.assertEqual(items[0]["url"], "https://sqlite.org/wal.html")


class ChainedProviderTests(unittest.TestCase):
    def test_auto_mode_search_configured_without_endpoint(self) -> None:
        provider = build_web_provider(allow_outbound=True, search_mode="auto")
        self.assertTrue(provider.configured())
        self.assertTrue(provider.search_configured())
        self.assertIsNone(
            web_unavailable_reason(allow_web=True, allow_outbound=True, provider=provider)
        )

    def test_configured_only_without_endpoint_is_unavailable(self) -> None:
        provider = build_web_provider(allow_outbound=True, search_mode="configured_only")
        self.assertFalse(provider.search_configured())
        reason = web_unavailable_reason(
            allow_web=True, allow_outbound=True, provider=provider
        )
        self.assertEqual(reason, "web_search_endpoint_unconfigured")

    def test_failover_to_fallback_on_configured_error(self) -> None:
        chain = ChainedWebProvider(
            allow_outbound=True,
            search_endpoint="https://search.example.invalid/search",
            search_provider="generic",
            search_mode="auto",
        )

        def boom(query: str, *, limit: int = 5):
            raise RuntimeError("search_http_401")

        chain._configured.search = boom  # type: ignore[method-assign]
        chain._fallback.search = lambda query, limit=5: [  # type: ignore[method-assign]
            WebSearchResult(
                title="T",
                url="https://sqlite.org/wal.html",
                snippet="s",
                provider=BEST_EFFORT_PUBLIC_PROVIDER,
                retrieved_at="2026-01-01T00:00:00Z",
            )
        ]
        results = chain.search("sqlite wal", limit=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(chain._last_search_provider, BEST_EFFORT_PUBLIC_PROVIDER)

    def test_configured_only_does_not_failover(self) -> None:
        chain = ChainedWebProvider(
            allow_outbound=True,
            search_endpoint="https://search.example.invalid/search",
            search_mode="configured_only",
        )

        def boom(query: str, *, limit: int = 5):
            raise RuntimeError("search_http_401")

        chain._configured.search = boom  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            chain.search("q")


class ReadinessTests(unittest.TestCase):
    def test_readiness_ready_with_fallback(self) -> None:
        provider = build_web_provider(allow_outbound=True, search_mode="auto")
        ready = build_web_readiness(
            allow_outbound=True,
            provider=provider,
            search_endpoint=None,
            api_key_configured=False,
            search_mode="auto",
        )
        self.assertTrue(ready.search_available)
        self.assertTrue(ready.direct_fetch_available)
        self.assertFalse(ready.api_key_configured)
        self.assertIn("READY", ready.operator_summary)
        self.assertNotIn("api_key", ready.public_dict())  # no secret fields

    def test_probe_does_not_persist(self) -> None:
        provider = build_web_provider(allow_outbound=True, search_mode="auto")

        def fake_search(query: str, *, limit: int = 5):
            return [
                WebSearchResult(
                    title="SQLite WAL",
                    url="https://sqlite.org/wal.html",
                    snippet="wal",
                    provider=BEST_EFFORT_PUBLIC_PROVIDER,
                    retrieved_at="2026-01-01T00:00:00Z",
                )
            ]

        def fake_fetch(url: str, **kwargs):
            return WebPageContent(
                url=url,
                canonical_url=url,
                title="WAL",
                text="Write-Ahead Logging enables concurrent readers. " * 5,
                content_type="text/html",
                status_code=200,
                content_hash="abc",
                fetched_at="2026-01-01T00:00:00Z",
                metadata={},
            )

        provider.search = fake_search  # type: ignore[method-assign]
        provider.fetch_page = fake_fetch  # type: ignore[method-assign]
        out = probe_web_research(provider, allow_outbound=True, query="sqlite")
        self.assertEqual(out["status"], "OK")
        self.assertFalse(out["truth"]["persists_artifacts"])


class SourceProvenanceTests(unittest.TestCase):
    def test_search_hit_is_not_verified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "r.db")
            store.initialize()
            project = store.create_project(title="t", topic="sqlite", allow_web=True)
            ingestor = SourceIngestor(store, Path(tmp) / "snap")
            hit = WebSearchResult(
                title="T",
                url="https://sqlite.org/wal.html",
                snippet="not evidence",
                provider="test",
                retrieved_at="2026-01-01T00:00:00Z",
            )
            discovered = ingestor.from_web_search(project.project_id, hit, query="q", rank=1)
            self.assertEqual(
                discovered.provenance.get("retrieval_status"),
                "DISCOVERED_BUT_UNVERIFIED",
            )
            self.assertEqual(discovered.provenance.get("epistemic"), "discovery_metadata_not_evidence")


class QualityGateZeroEvidenceTests(unittest.TestCase):
    def test_allow_web_zero_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "r.db")
            store.initialize()
            project = store.create_project(title="t", topic="sqlite", allow_web=True)
            project.status = ResearchStatus.COMPLETED
            store.save_project(project)
            card = build_quality_scorecard(store, project)
            gate = card.metadata.get("evidence_quality_gate") or {}
            self.assertEqual(gate.get("status"), "INSUFFICIENT_EVIDENCE")
            self.assertFalse(card.metadata.get("quality_pass"))
            self.assertLessEqual(card.overall, 0.35)


class LocalhostBlockedTests(unittest.TestCase):
    def test_http_provider_rejects_localhost_search_results(self) -> None:
        provider = HttpWebProvider(
            allow_outbound=True,
            search_endpoint="https://search.example/search",
            search_provider="generic",
        )

        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "results": [
                        {"title": "local", "url": "http://127.0.0.1/secret", "snippet": "x"},
                        {"title": "ok", "url": "https://sqlite.org/wal.html", "snippet": "y"},
                    ]
                }

        class Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, *a, **k):
                return Resp()

        with mock.patch("Data.modules.research.web.httpx.Client", Client), mock.patch(
            "Data.modules.research.web.assert_safe_url"
        ):
            results = provider.search("q", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://sqlite.org/wal.html")


if __name__ == "__main__":
    unittest.main()
