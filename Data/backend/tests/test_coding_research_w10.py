"""W10 — Coding native tools + Research web policy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.coding.loop import CodingLoop, FakeLLM
from Data.modules.coding.parser import (
    CODING_TOOL_SCHEMAS,
    capabilities_from_native_tool_calls,
    extract_capabilities,
)
from Data.modules.coding.store import CodingStore
from Data.modules.coding.types import Mission, SessionStatus, StepKind, StepStatus
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.research.web import (
    HostRateLimiter,
    check_robots_allowed,
    _html_to_readable_text,
    _extract_published_at,
)


class NativeToolCallParseTests(unittest.TestCase):
    def test_native_tool_calls_preferred_over_text(self) -> None:
        calls = [
            {
                "id": "1",
                "function": {
                    "name": "file.read",
                    "arguments": '{"path": "a.py"}',
                },
            }
        ]
        caps = capabilities_from_native_tool_calls(calls)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].capability_id, "file.read")
        self.assertEqual(caps[0].arguments["path"], "a.py")
        self.assertEqual(caps[0].source, "native_tools")

    def test_schemas_cover_core_coding_caps(self) -> None:
        names = {s["function"]["name"] for s in CODING_TOOL_SCHEMAS}
        self.assertIn("file.write", names)
        self.assertIn("coding.run_tests", names)


class CodingLoopNativeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "c.db"
        MigrationRunner(self.db).apply_all()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / "a.py").write_text("x = 1\n", encoding="utf-8")
        self.store = CodingStore(self.db)
        self.store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.llm = FakeLLM()
        self.loop = CodingLoop(
            self.store,
            gateway=self.gateway,
            llm=self.llm,
            agents_enabled=True,
            coding_enabled=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loop_prefers_native_tool_calls_and_passes_schemas(self) -> None:
        session = self.store.create_session(
            user_goal="read a.py",
            workspace_root=str(self.ws),
            mission=Mission.GENERIC,
            status=SessionStatus.RUNNING,
        )
        # Native call only — no XML in text.
        self.llm.queue.append("I will read the file.")
        self.llm.tool_calls_queue.append(
            [{"function": {"name": "workspace.list", "arguments": "{}"}}]
        )
        with mock.patch.object(
            self.loop,
            "_execute",
            return_value={"status": "COMPLETED", "output": {"entries": []}},
        ):
            result = self.loop.run_round(session.session_id)
        self.assertIsNotNone(self.llm.last_tools_requested)
        self.assertGreater(len(self.llm.last_tools_requested or []), 0)
        self.assertEqual(self.llm.last_completion_source, "native_tools")
        self.assertNotEqual(result.error, "LLMUnavailable")

    def test_writes_without_tests_are_unverified(self) -> None:
        session = self.store.create_session(
            user_goal="write hello",
            workspace_root=str(self.ws),
            mission=Mission.GENERIC,
            status=SessionStatus.RUNNING,
        )
        self.store.add_step(
            session.session_id,
            kind=StepKind.CAPABILITY,
            status=StepStatus.COMPLETED,
            capability_id="file.write",
            arguments={"path": "hello.py", "content": "print(1)"},
        )
        session = self.store.get_session(session.session_id)
        assert session is not None
        result = self.loop._finish_verify(session, reason="no_tools")
        self.assertEqual(result.status, SessionStatus.UNVERIFIED)
        self.assertIn("coding.run_tests", result.error or "")


class ResearchWebPolicyTests(unittest.TestCase):
    def test_readability_prefers_article(self) -> None:
        html = (
            "<html><body><nav>nav junk</nav>"
            "<article>" + ("<p>Important research claim about markets. </p>" * 10) + "</article>"
            "</body></html>"
        )
        text, extractor = _html_to_readable_text(html)
        self.assertIn("readability", extractor)
        self.assertIn("Important research claim", text)
        self.assertNotIn("nav junk", text)

    def test_published_at_from_meta(self) -> None:
        html = '<meta property="article:published_time" content="2024-01-15T12:00:00Z">'
        self.assertEqual(_extract_published_at(html), "2024-01-15T12:00:00Z")

    def test_robots_disallow(self) -> None:
        robots_body = "User-agent: *\nDisallow: /secret\n"
        with mock.patch("Data.modules.research.web.validate_url_for_fetch") as v:
            v.return_value = mock.Mock(allowed=True, reason="ok")
            with mock.patch("Data.modules.research.web.httpx.Client") as client_cls:
                client = client_cls.return_value.__enter__.return_value
                resp = mock.Mock(status_code=200, text=robots_body)
                client.get.return_value = resp
                # Clear cache
                from Data.modules.research import web as webmod

                webmod._ROBOTS_CACHE.clear()
                decision = check_robots_allowed(
                    "https://example.com/secret/page",
                    user_agent="LEVIATHAN-Research/1.0",
                )
        self.assertFalse(decision["allowed"])
        self.assertTrue(decision["robots_checked"])

    def test_rate_limiter_delays_burst(self) -> None:
        limiter = HostRateLimiter(min_interval_seconds=0.05)
        t0 = limiter.wait("example.test")
        t1 = limiter.wait("example.test")
        self.assertEqual(t0, 0.0)
        self.assertGreaterEqual(t1, 0.04)


class FallbackParserStillWorks(unittest.TestCase):
    def test_xml_fallback_when_no_native(self) -> None:
        text = '<capability id="file.read"><arg name="path">a.py</arg></capability>'
        caps = extract_capabilities(text)
        self.assertEqual(caps[0].capability_id, "file.read")


if __name__ == "__main__":
    unittest.main()
