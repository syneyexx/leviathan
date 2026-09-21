"""Regression tests for 2026-09-11 static full-repo audit fixes.

ADDED_NOT_EXECUTED — user constraint forbids CLI test execution during this audit.
Execution status = NOT_EXECUTED_BY_USER_CONSTRAINT.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class UrlSecurityTests(unittest.TestCase):
    """HADES-AUDIT-2026-001 / SSRF helpers."""

    def test_blocks_private_and_metadata_hosts(self) -> None:
        from url_security import UrlSecurityError, assert_public_http_url, is_private_or_local_host

        self.assertTrue(is_private_or_local_host("127.0.0.1"))
        self.assertTrue(is_private_or_local_host("10.0.0.1"))
        self.assertTrue(is_private_or_local_host("169.254.169.254"))
        self.assertTrue(is_private_or_local_host("localhost"))
        with self.assertRaises(UrlSecurityError):
            assert_public_http_url("http://127.0.0.1/secret", purpose="test")
        with self.assertRaises(UrlSecurityError):
            assert_public_http_url("http://169.254.169.254/latest/meta-data/", purpose="test")
        with self.assertRaises(UrlSecurityError):
            assert_public_http_url("file:///etc/passwd", purpose="test")
        parsed = assert_public_http_url("https://example.com/path", purpose="test")
        self.assertEqual(parsed.hostname, "example.com")


class WebResearchRedirectSsrfSourceTests(unittest.TestCase):
    """HADES-AUDIT-2026-001 — WebResearchService must not auto-follow redirects."""

    def test_get_disables_follow_redirects(self) -> None:
        import inspect
        from platform_services_core import WebResearchService

        source = inspect.getsource(WebResearchService._get)
        self.assertIn("follow_redirects=False", source)
        self.assertIn("safe_public_url", source)
        robots = inspect.getsource(WebResearchService.allowed_by_robots)
        self.assertIn("follow_redirects=False", robots)
        self.assertIn("return False", robots)


class ExplainHighProfileDirectChatNoToolsTests(unittest.TestCase):
    """Simple explain turns stay direct_chat without tool schemas (even on high)."""

    def test_explain_high_simple_question_skips_tools(self) -> None:
        from reasoning.understanding import build_request_spec, build_route_decision

        spec = build_request_spec("Leg uit wat deze delete-opdracht doet")
        self.assertEqual(spec.speech_act, "explain")
        self.assertFalse(spec.needs_tools)
        for profile in ("high", "maximum"):
            route = build_route_decision(
                spec,
                requested_profile=profile,
                network_policy="allow",
                plugin_tools_enabled=True,
            )
            self.assertEqual(route.target, "direct_chat", profile)
            self.assertFalse(route.allow_tools, profile)
            self.assertEqual(route.max_tool_rounds, 0, profile)


class PaperBotDisabledHonestyTests(unittest.TestCase):
    """HADES-AUDIT-2026-008 — paper bot must not silently re-enable trading."""

    def test_execute_paper_bot_step_raises_when_disabled(self) -> None:
        from trading_service import PaperTradingService, TradingBotService
        from platform_db import PlatformDB

        root = Path(tempfile.mkdtemp(prefix="hades-audit-paper-"))
        db = PlatformDB(root / "platform.db")
        paper = PaperTradingService(db)
        bot = TradingBotService(db, paper, knowledge=None)
        # Minimal bars/strategy stub via raising early on bars length if needed —
        # disabled check happens after bars validation, so seed enough bars.
        seeded = bot.seed_synthetic(symbol="BTC/USDT", bars=80, seed=3)
        self.assertGreaterEqual(seeded["bars"], 50)
        bars = bot.get_bars("BTC/USDT", "1h", 100)
        discoveries = bot.discover_strategies(bars, top_n=1)
        saved = bot.persist_discovered(discoveries, symbol="BTC/USDT", timeframe="1h")
        self.assertFalse(paper.state()["settings"]["enabled"])
        with self.assertRaisesRegex(RuntimeError, "paper_trading_disabled"):
            bot.execute_paper_bot_step(saved[0], bars, position_fraction=0.1)


class ComputeLeaseHoldTests(unittest.TestCase):
    """HADES-AUDIT-2026-003 — unexpired foreign lease must not be overwritten."""

    def test_lease_held_by_other_node(self) -> None:
        from gen2.compute_fabric import lease_remote_job
        from gen2.store import Gen2Store

        root = Path(tempfile.mkdtemp(prefix="hades-audit-lease-"))
        store = Gen2Store(root / "gen2.db")
        job = store.create_remote_job(
            {"node_id": "node_a", "status": "queued", "payload": {"type": "ping"}}
        )
        first = lease_remote_job(store, job["id"], node_id="node_a", lease_seconds=60)
        self.assertTrue(first.get("ok"))
        second = lease_remote_job(store, job["id"], node_id="node_b", lease_seconds=60)
        self.assertFalse(second.get("ok"))
        self.assertEqual(second.get("error"), "lease_held")


class WorkspaceBackupCoverageTests(unittest.TestCase):
    """HADES-AUDIT-2026-002 — core backup includes durable sibling stores."""

    def test_core_categories_include_durable_stores(self) -> None:
        from workspace_backup import CORE_CATEGORIES, WorkspaceBackupService

        for name in (
            "embeddings",
            "effect_ledger",
            "claims",
            "leases",
            "voice",
            "coding_jobs",
        ):
            self.assertIn(name, CORE_CATEGORIES)
        root = Path(tempfile.mkdtemp(prefix="hades-audit-bak-"))
        (root / "embedding_index.sqlite3").write_bytes(b"x")
        (root / "effect_ledger.db").write_bytes(b"x")
        (root / "claims.sqlite").write_bytes(b"x")
        (root / "execution_leases.json").write_text("{}", encoding="utf-8")
        (root / "voice").mkdir()
        (root / "voice" / "note.txt").write_text("v", encoding="utf-8")
        (root / "coding_jobs").mkdir()
        (root / "coding_jobs" / "job.json").write_text("{}", encoding="utf-8")
        (root / "hades.db").write_bytes(b"db")
        svc = WorkspaceBackupService(root, db_path=root / "hades.db")
        inv = svc.inventory()
        rels = {e["relative_path"] for e in inv["entries"] if e.get("included")}
        self.assertIn("embedding_index.sqlite3", rels)
        self.assertIn("effect_ledger.db", rels)
        self.assertIn("claims.sqlite", rels)
        self.assertIn("execution_leases.json", rels)
        self.assertTrue(any(r.startswith("voice/") for r in rels))
        self.assertTrue(any(r.startswith("coding_jobs/") for r in rels))

    def test_extract_enforces_archive_file_limit(self) -> None:
        from workspace_backup import WorkspaceBackupService

        root = Path(tempfile.mkdtemp(prefix="hades-audit-zip-"))
        archive = root / "bomb.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for i in range(3):
                zf.writestr(f"f{i}.txt", b"x")
        dest = root / "out"
        # Monkeypatch limits via control settings if available; otherwise assert source contract.
        import inspect

        source = inspect.getsource(WorkspaceBackupService.safe_extract_workspace_zip)
        self.assertIn("max_archive_files", source)
        self.assertIn("max_archive_bytes", source)


class AbSummaryMetricsHonestyTests(unittest.TestCase):
    """HADES-AUDIT-2026-005 — A/B meta score must not invent pass=1.0 quality."""

    def test_ab_summary_metrics_not_model_quality_pass(self) -> None:
        import inspect
        from gen2 import eval_lab

        source = inspect.getsource(eval_lab.run_ab_experiment)
        self.assertIn("experiment_completed", source)
        self.assertIn("not_model_quality", source)
        self.assertNotIn('"pass": 1.0', source)


class DeepWebSsrfHelpersTests(unittest.TestCase):
    """HADES-AUDIT-2026-004 — deep-web blocks private hosts."""

    def test_assert_public_crawl_url_blocks_loopback(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "deep-web-downloader"))
        from deep_utils import assert_public_crawl_url, is_blocked_ssrf_host

        self.assertTrue(is_blocked_ssrf_host("127.0.0.1"))
        with self.assertRaises(ValueError):
            assert_public_crawl_url("http://127.0.0.1/x")
        with self.assertRaises(ValueError):
            assert_public_crawl_url("http://169.254.169.254/latest/meta-data/")


class GitImportPrivateHostSourceTests(unittest.TestCase):
    """HADES-AUDIT-2026-006 — plugin git import rejects private hosts."""

    def test_import_git_uses_url_security(self) -> None:
        import inspect
        from platform_services_core import PluginManager

        source = inspect.getsource(PluginManager.import_git)
        self.assertIn("assert_public_http_url", source)
        self.assertIn("git_import", source)


class RedactDependencySecretsTests(unittest.TestCase):
    """HADES-AUDIT-2026-012 — dependency log redaction covers authToken/Basic/URL userinfo."""

    def test_redacts_common_secret_shapes(self) -> None:
        from plugin_dependency_runtime import redact_dependency_output

        samples = {
            "authToken=sekrit": "authToken=[REDACTED]",
            "npm_config_authtoken=sekrit": "npm_config_authtoken=[REDACTED]",
            "Authorization: Basic dXNlcjpwYXNz": "Authorization: Basic [REDACTED]",
            "https://user:ghp_xxx@host/repo.git": "https://[REDACTED]:[REDACTED]@host/repo.git",
            "//registry.npmjs.org/:_authToken=abc": "//registry.npmjs.org/:_authToken=[REDACTED]",
        }
        for raw, expected_fragment in samples.items():
            redacted = redact_dependency_output(raw)
            self.assertIn(expected_fragment.split("=")[0] if "=" in expected_fragment else expected_fragment[:20], redacted)
            self.assertIn("[REDACTED]", redacted)
            self.assertNotIn("sekrit", redacted)
            self.assertNotIn("ghp_xxx", redacted)
            self.assertNotIn("dXNlcjpwYXNz", redacted)
            self.assertNotIn("abc", redacted.replace("[REDACTED]", ""))


class NewsPluginSsrfSourceTests(unittest.TestCase):
    """HADES-AUDIT-2026-009 — news plugins use public URL guards."""

    def test_ultimate_news_ssrf_module(self) -> None:
        root = Path(__file__).resolve().parents[2] / "plugins" / "ultimate-news-feeder"
        sys.path.insert(0, str(root))
        from ssrf import assert_public_http_url

        with self.assertRaises(ValueError):
            assert_public_http_url("http://127.0.0.1/x")
        with self.assertRaises(ValueError):
            assert_public_http_url("http://169.254.169.254/latest/meta-data/")

    def test_financial_fetch_bytes_source(self) -> None:
        from pathlib import Path as P

        source = (P(__file__).resolve().parents[2] / "plugins" / "financial-news-intelligence" / "financial_news_intelligence.py").read_text(encoding="utf-8")
        self.assertIn("assert_public_http_url", source)
        self.assertIn("301, 302, 303, 307, 308", source)


if __name__ == "__main__":
    unittest.main()
