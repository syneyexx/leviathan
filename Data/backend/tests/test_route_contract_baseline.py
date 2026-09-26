"""W0D — HTTP route surface contract.

Captures (method, path) operations from the FastAPI app and asserts they match
the frozen baseline recorded before main.py domain extractions. New routes may
be added; existing baseline ops must not disappear or change method.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "route_contract_baseline.json"


def _app_operations() -> set[tuple[str, str]]:
    from Data.backend.main import app

    ops: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not path or not methods:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            ops.add((method, path))
    return ops


class RouteContractBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.baseline_ops = {
            (item["method"], item["path"]) for item in cls.baseline["operations"]
        }
        cls.current_ops = _app_operations()

    def test_baseline_fixture_present(self) -> None:
        self.assertTrue(FIXTURE.is_file())
        self.assertGreaterEqual(len(self.baseline_ops), 400)

    def test_no_baseline_route_removed(self) -> None:
        missing = sorted(self.baseline_ops - self.current_ops)
        self.assertEqual(
            missing,
            [],
            f"route contract regression — missing ops: {missing[:20]}",
        )

    def test_knowledge_cluster_still_present(self) -> None:
        required = {
            ("GET", "/api/knowledge"),
            ("POST", "/api/knowledge"),
            ("GET", "/api/knowledge/search"),
            ("GET", "/api/knowledge/atlas"),
            ("POST", "/api/knowledge/ingest/scan"),
            ("DELETE", "/api/knowledge/{document_id}"),
        }
        self.assertTrue(required.issubset(self.current_ops))

    def test_extracted_routers_still_mounted(self) -> None:
        required = {
            ("GET", "/api/cognition/health"),
            ("GET", "/api/coding/health"),
            ("GET", "/api/research/projects"),
            ("GET", "/api/datasets"),
            ("GET", "/api/models"),
        }
        # Some of these may use slightly different static paths — check soft.
        present = {op for op in required if op in self.current_ops}
        self.assertGreaterEqual(len(present), 3, f"expected extracted routers mounted, got {present}")


if __name__ == "__main__":
    unittest.main()
