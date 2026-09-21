#!/usr/bin/env python3
"""Automated tests for Web PDF Harvester."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.site import PDF_BYTES, FixtureServer  # noqa: E402
from pdf_harvester.actions import run_action  # noqa: E402
from pdf_harvester.html_extract import extract_scored_links  # noqa: E402
from pdf_harvester.models import CrawlConfig  # noqa: E402
from pdf_harvester.pdf_detect import detect_from_headers, detect_from_magic  # noqa: E402
from pdf_harvester.scoring import is_safe_automatic_click, score_link  # noqa: E402
from pdf_harvester.storage import sanitize_filename  # noqa: E402
from pdf_harvester.urls import normalize_url, safe_normalize  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_relative_absolute_protocol_fragment(self) -> None:
        base = "https://Example.COM/books/list"
        self.assertEqual(
            normalize_url("/a/b", base=base),
            "https://example.com/a/b",
        )
        self.assertEqual(
            normalize_url("https://cdn.example.com/x.pdf#section", base=base),
            "https://cdn.example.com/x.pdf",
        )
        self.assertEqual(
            normalize_url("//cdn.example.com/y.pdf", base=base),
            "https://cdn.example.com/y.pdf",
        )

    def test_tracking_stripped_but_id_kept(self) -> None:
        url = normalize_url("https://ex.com/download.php?id=1337&utm_source=x&gclid=1")
        self.assertIn("id=1337", url)
        self.assertNotIn("utm_source", url)
        self.assertNotIn("gclid", url)

    def test_duplicate_slash_and_encoding(self) -> None:
        url = normalize_url("https://ex.com//a//b%20c")
        self.assertEqual(url, "https://ex.com/a/b%20c")

    def test_ssrf_blocked(self) -> None:
        self.assertIsNone(safe_normalize("http://127.0.0.1/secret"))
        self.assertIsNone(safe_normalize("file:///etc/passwd"))
        self.assertIsNone(safe_normalize("javascript:alert(1)"))
        ok = normalize_url("http://127.0.0.1/x", allow_private=True)
        self.assertTrue(ok.startswith("http://127.0.0.1/"))


class PdfDetectTests(unittest.TestCase):
    def test_url_pdf(self) -> None:
        d = detect_from_headers("https://ex.com/a.pdf")
        self.assertTrue(d.is_pdf)

    def test_content_type(self) -> None:
        d = detect_from_headers("https://ex.com/download?id=1", content_type="application/pdf")
        self.assertTrue(d.is_pdf)
        self.assertEqual(d.method, "content_type")

    def test_content_disposition(self) -> None:
        d = detect_from_headers(
            "https://ex.com/dl",
            content_disposition='attachment; filename="book.pdf"',
        )
        self.assertTrue(d.is_pdf)

    def test_magic(self) -> None:
        d = detect_from_magic(b"%PDF-1.7....")
        self.assertTrue(d.is_pdf)
        self.assertEqual(d.method, "magic_bytes")

    def test_fake_html_named_pdf(self) -> None:
        d = detect_from_headers("https://ex.com/fake.pdf", content_type="text/html")
        self.assertFalse(d.is_pdf)
        d2 = detect_from_magic(b"<!doctype html><html>", url="https://ex.com/fake.pdf")
        self.assertFalse(d2.is_pdf)


class ScoringTests(unittest.TestCase):
    def test_high_vs_low(self) -> None:
        high = score_link(url="https://ex.com/x", anchor_text="Download PDF")
        low = score_link(url="https://ex.com/about", anchor_text="About us")
        self.assertGreater(high.score, low.score)

    def test_safe_click(self) -> None:
        self.assertTrue(is_safe_automatic_click("Download / View book"))
        self.assertFalse(is_safe_automatic_click("Sign in to continue"))
        self.assertFalse(is_safe_automatic_click("Buy now"))


class SanitizeTests(unittest.TestCase):
    def test_traversal_and_reserved(self) -> None:
        self.assertNotIn("..", sanitize_filename("../etc/passwd.pdf"))
        self.assertTrue(sanitize_filename("CON.pdf").startswith("_") or "CON" not in sanitize_filename("CON.pdf").split(".")[0].upper() or sanitize_filename("CON.pdf").startswith("_"))


class ExtractTests(unittest.TestCase):
    def test_iframe_and_relative(self) -> None:
        html = '<a href="/a">A</a><iframe src="/downloads/test.pdf"></iframe><embed src="https://cdn.example/x.pdf">'
        links, title, _ = extract_scored_links(html, "https://example.org/start", allow_private=False)
        urls = {item.url for item in links}
        self.assertIn("https://example.org/a", urls)
        self.assertIn("https://example.org/downloads/test.pdf", urls)
        self.assertIn("https://cdn.example/x.pdf", urls)


class IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wph-"))
        self.data_dir = str(self.tmp / "data")
        self.server = FixtureServer().start()

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _discover(self, **extra):
        params = {
            "start_urls": [self.server.base_url + "/"],
            "max_depth": 6,
            "max_pages": 50,
            "rate_limit_ms": 0,
            "respect_robots_txt": True,
            "resume": False,
            "use_browser": False,
            "allow_private_hosts": True,
            "data_dir": self.data_dir,
            "max_concurrent_requests": 4,
        }
        params.update(extra)
        return run_action("discover", params)

    def test_five_hop_discover_no_download(self) -> None:
        result = self._discover()
        self.assertTrue(result.get("success"), result)
        self.assertGreaterEqual(result["stats"]["pdfs_confirmed"], 1)
        self.assertTrue(Path(result["index_path"]).exists())
        self.assertTrue(Path(result["links_export_path"]).exists())
        # Discovery must not create downloaded PDFs
        downloads = list(Path(self.data_dir).joinpath("downloads").rglob("*.pdf"))
        self.assertEqual(downloads, [])
        listing = run_action("list", {"data_dir": self.data_dir, "filter": "confirmed"})
        self.assertGreaterEqual(listing["total"], 1)
        item = listing["items"][0]
        self.assertIn("/downloads/test.pdf", item["normalized_url"])
        self.assertGreaterEqual(len(item.get("click_path") or []), 5)
        # path should include the hop chain
        joined = " ".join(item["click_path"])
        self.assertIn("/category", joined)
        self.assertIn("/book/123", joined)

    def test_download_all_and_idempotent(self) -> None:
        disc = self._discover()
        self.assertTrue(disc.get("success"), disc)
        first = run_action(
            "download_all",
            {"data_dir": self.data_dir, "allow_private_hosts": True, "download_concurrency": 2},
        )
        self.assertTrue(first.get("success"), first)
        self.assertGreaterEqual(first["downloaded"], 1)
        path = Path(first["results"][0]["local_path"])
        self.assertTrue(path.exists())
        self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
        self.assertTrue(first["results"][0]["sha256"])
        second = run_action(
            "download_all",
            {"data_dir": self.data_dir, "allow_private_hosts": True},
        )
        self.assertTrue(second.get("success"), second)
        self.assertEqual(second["downloaded"], 0)
        self.assertGreaterEqual(second["skipped"], 1)

    def test_loop_protection(self) -> None:
        result = self._discover(start_urls=[self.server.base_url + "/loop-a"], max_pages=20, max_depth=6)
        self.assertTrue(result.get("success"), result)
        # Should terminate without hanging; visited bounded
        self.assertLessEqual(result["stats"]["pages_visited"], 20)

    def test_fake_pdf_not_confirmed(self) -> None:
        result = self._discover(start_urls=[self.server.base_url + "/fake.pdf"], max_pages=5)
        # Should not confirm HTML as PDF
        self.assertEqual(result.get("stats", {}).get("pdfs_confirmed", 0), 0)

    def test_direct_pdf_content_disposition(self) -> None:
        result = self._discover(start_urls=[self.server.base_url + "/direct.pdf"], max_pages=3)
        self.assertGreaterEqual(result["stats"]["pdfs_confirmed"], 1)

    def test_cancel_flag(self) -> None:
        cancel = run_action("cancel", {"data_dir": self.data_dir, "reason": "test"})
        self.assertTrue(cancel["success"])
        flag = Path(self.data_dir) / "state" / "cancel.flag"
        self.assertTrue(flag.exists())

    def test_status_and_health(self) -> None:
        self._discover()
        status = run_action("status", {"data_dir": self.data_dir})
        self.assertTrue(status["success"])
        self.assertGreaterEqual(status["index_counts"]["confirmed"], 1)
        health = run_action("health", {"data_dir": self.data_dir})
        self.assertTrue(health["success"])

    def test_resume_state_file(self) -> None:
        first = self._discover(max_pages=3, resume=False)
        self.assertTrue((Path(self.data_dir) / "state" / "crawl_state.json").exists())
        # Exhausted crawl (no remaining queue) must not report success=True as a silent no-op.
        second = self._discover(max_pages=30, resume=True)
        self.assertFalse(second.get("success"), second)
        self.assertIn("resume", (second.get("error") or "").lower())
        # Explicit fresh crawl still works against the same data_dir.
        fresh = self._discover(max_pages=30, resume=False)
        self.assertTrue(fresh.get("success"), fresh)
        self.assertGreaterEqual(fresh.get("pages_visited_this_run", fresh["stats"]["pages_visited"]), 1)

    def test_download_all_empty_index_is_not_success(self) -> None:
        empty = run_action("download_all", {"data_dir": self.data_dir})
        self.assertFalse(empty.get("success"), empty)
        self.assertTrue(empty.get("no_work"))
        self.assertIn("No confirmed", empty.get("error") or "")


class DownloadRedirectSsrfTests(unittest.TestCase):
    def test_redirect_to_private_host_is_blocked(self) -> None:
        import httpx

        from pdf_harvester.downloader import Downloader
        from pdf_harvester.index import ResourceIndex
        from pdf_harvester.models import ResourceRecord, ResourceStatus, new_resource_id
        from pdf_harvester.storage import StoragePaths

        seed = "https://cdn.example.com/open.pdf"
        data_dir = tempfile.mkdtemp(prefix="hades-dl-ssrf-")
        try:
            paths = StoragePaths(Path(data_dir)).ensure()
            index = ResourceIndex(paths)
            record = ResourceRecord(
                id=new_resource_id(seed),
                discovered_url=seed,
                normalized_url=seed,
                hostname="cdn.example.com",
                status=ResourceStatus.CONFIRMED.value,
                filename="open.pdf",
            )
            index.upsert(record)

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    302,
                    headers={"Location": "http://127.0.0.1:9/secret.pdf"},
                    request=request,
                )

            transport = httpx.MockTransport(handler)
            real_client = httpx.AsyncClient

            def client_factory(*args, **kwargs):
                kwargs["transport"] = transport
                kwargs["follow_redirects"] = False
                return real_client(*args, **kwargs)

            downloader = Downloader(index=index, paths=paths, allow_private=False, max_retries=0)
            with unittest.mock.patch("httpx.AsyncClient", side_effect=client_factory):
                result = asyncio.run(downloader.download_ids([record.id]))
            self.assertEqual(result["failed"], 1, result)
            failed = result["results"][0]
            self.assertEqual(failed["status"], "failed")
            self.assertIn("SSRF_BLOCKED", failed.get("error") or "")
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
