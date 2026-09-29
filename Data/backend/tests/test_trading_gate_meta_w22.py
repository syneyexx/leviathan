"""Wave 22 — measurable meta gates for trading verifier / docs / frontend contracts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class TradingGateMetaTests(unittest.TestCase):
    def test_verifier_and_canonical_docs_present(self) -> None:
        verifier = ROOT / "scripts" / "verify_trading_100.py"
        backend_doc = ROOT / "Data" / "docs" / "Leviathan_system_backend.md"
        frontend_doc = ROOT / "Data" / "docs" / "Leviathan_system_frontend.md"
        gates = ROOT / "Data" / "backend" / "tests" / "trading_gates.json"
        self.assertTrue(verifier.is_file(), verifier)
        self.assertTrue(backend_doc.is_file(), backend_doc)
        self.assertTrue(frontend_doc.is_file(), frontend_doc)
        self.assertTrue(gates.is_file(), gates)
        payload = json.loads(gates.read_text(encoding="utf-8"))
        self.assertIn("gates", payload)
        self.assertGreaterEqual(len(payload["gates"]), 50)

    def test_completion_report_schema_when_present(self) -> None:
        report = ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json"
        self.assertTrue(report.is_file(), report)
        payload = json.loads(report.read_text(encoding="utf-8"))
        for key in (
            "source_commit",
            "source_tree",
            "generated_at",
            "dirty",
            "strict",
            "counts",
            "gates",
            "truth",
        ):
            self.assertIn(key, payload, key)
        self.assertTrue(payload["truth"].get("file_exists_alone_is_not_pass"))

    def test_orchestra_frontend_contracts_present(self) -> None:
        contract = (
            ROOT
            / "Data"
            / "frontend"
            / "src"
            / "pages"
            / "tradingOrchestraContracts.test.ts"
        )
        section = (
            ROOT
            / "Data"
            / "frontend"
            / "src"
            / "pages"
            / "agents"
            / "TradeOrchestraSection.tsx"
        )
        self.assertTrue(contract.is_file(), contract)
        self.assertTrue(section.is_file(), section)
        text = contract.read_text(encoding="utf-8")
        for needle in (
            "readiness",
            "live",
            "UNMEASURED",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
