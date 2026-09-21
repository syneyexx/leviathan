#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mcp_bridge  # noqa: E402


class McpEmptyCallHonestyTests(unittest.TestCase):
    def test_empty_content_marks_is_error(self) -> None:
        session = mcp_bridge.McpSession.__new__(mcp_bridge.McpSession)
        session._lock = mock.MagicMock()
        session._lock.__enter__ = mock.MagicMock(return_value=None)
        session._lock.__exit__ = mock.MagicMock(return_value=False)
        session.notifications = []
        session.protocol_version = "2024-11-05"
        session._stderr_chunks = []
        session.request = mock.MagicMock(
            return_value={"isError": False, "content": [], "structuredContent": None}
        )
        out = session.call_tool("noop", {})
        self.assertTrue(out.get("isError"))
        self.assertIn("empty", str(out.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
