
"""GraphRAG query must fail closed on empty stdout."""
from __future__ import annotations
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_bridge():
    spec = importlib.util.spec_from_file_location("graphrag_hades_bridge", ROOT / "hades_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class GraphragQueryHonestyTests(unittest.TestCase):
    def test_empty_query_stdout_exits_nonzero(self) -> None:
        bridge = load_bridge()
        with mock.patch.object(
            bridge, "run", return_value={"command": ["graphrag"], "exit_code": 0, "stdout": "", "stderr": ""}
        ), mock.patch.object(sys, "argv", ["hades_bridge.py", "query", "--root", "/tmp", "--query", "q"]), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as out:
            code = bridge.main()
        payload = json.loads(out.getvalue())
        self.assertFalse(payload.get("ok"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
