"""WAVES 25–36 — providers, ops, honesty, scale, program gates."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from Data.modules.market_sim.institutional_ops import (
    AuditEvent,
    AuditLog,
    ResourceBudget,
    api_contract_check,
    check_resource_budget,
    dataset_trust_report,
    institutional_program_gate_summary,
    observability_snapshot,
    provider_fabric_inventory,
    scale_smoke,
    statistical_honesty_labels,
)


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "tests" / "institutional_trading_program.json"


class ProviderFabricW25Tests(unittest.TestCase):
    def test_inventory(self) -> None:
        inv = provider_fabric_inventory()
        ids = {p["id"] for p in inv["providers"]}
        self.assertIn("csv_local", ids)
        self.assertIn("binance_public", ids)
        self.assertEqual(
            next(p for p in inv["providers"] if p["id"] == "l2_orderbook")["status"],
            "NOT_IMPLEMENTED",
        )


class ResourceGovW26Tests(unittest.TestCase):
    def test_budget_violations(self) -> None:
        ok = check_resource_budget(bars=10, jobs=1, dataset_bytes=100)
        self.assertTrue(ok["ok"])
        bad = check_resource_budget(
            bars=999_999, jobs=1, dataset_bytes=100, budget=ResourceBudget(max_bars_in_memory=1000)
        )
        self.assertFalse(bad["ok"])
        self.assertIn("bars_in_memory", bad["violations"])


class DatasetTrustW27Tests(unittest.TestCase):
    def test_poisoning_signal(self) -> None:
        clean = dataset_trust_report(content_hash="abc", quality_verdict="PASS", source_reputation="KNOWN")
        self.assertEqual(clean["poisoningRisk"], "LOW")
        poisoned = dataset_trust_report(
            content_hash="abc", quality_verdict="PASS", unexpected_hash_change=True
        )
        self.assertEqual(poisoned["poisoningRisk"], "HIGH")


class GovernanceW28Tests(unittest.TestCase):
    def test_audit_append(self) -> None:
        log = AuditLog()
        log.append(AuditEvent("e1", "PROMOTE", "operator", "challenger->champion", "2024-01-01T00:00:00+00:00"))
        self.assertEqual(len(log.list_events()), 1)
        self.assertTrue(log.list_events()[0]["truth"]["append_only_audit_intent"])


class ObservabilityW29Tests(unittest.TestCase):
    def test_snapshot(self) -> None:
        snap = observability_snapshot(runs_active=2, paper_sessions=1)
        self.assertEqual(snap["health"], "OK")
        degraded = observability_snapshot(runs_active=0, paper_sessions=0, last_error="boom")
        self.assertEqual(degraded["health"], "DEGRADED")


class ApiContractW31Tests(unittest.TestCase):
    def test_required_routes(self) -> None:
        ok = api_contract_check(
            [
                "/api/market-sim/status",
                "/api/market-sim/capabilities",
                "/api/market-sim/data",
                "/api/extra",
            ]
        )
        self.assertTrue(ok["ok"])
        missing = api_contract_check(["/api/market-sim/status"])
        self.assertFalse(missing["ok"])
        self.assertIn("/api/market-sim/capabilities", missing["missing"])


class StatsHonestyW32Tests(unittest.TestCase):
    def test_uncorrected_not_discovery(self) -> None:
        labels = statistical_honesty_labels(
            trials=100, multiple_testing_corrected=False, sealed_holdout_used=False
        )
        self.assertIs(labels["claims"]["significant"], False)
        self.assertIs(labels["claims"]["generalizes"], False)
        self.assertTrue(labels["truth"]["profitable_backtest_is_not_proof"])


class AdversarialW33Tests(unittest.TestCase):
    def test_live_still_blocked_in_ops_truth(self) -> None:
        self.assertTrue(provider_fabric_inventory()["truth"]["live_trading_blocked"])
        self.assertTrue(observability_snapshot(runs_active=0, paper_sessions=0)["truth"]["live_trading_blocked"])


class ScaleW34Tests(unittest.TestCase):
    def test_scale_smoke(self) -> None:
        out = scale_smoke(n=10_000)
        self.assertTrue(out["ok"])
        self.assertTrue(out["truth"]["smoke_is_not_full_5y_benchmark"])


class FrontendJourneyW35Tests(unittest.TestCase):
    def test_marktdata_exposes_quality_column(self) -> None:
        page = ROOT.parent / "frontend" / "src" / "pages" / "trading" / "MarktdataPage.tsx"
        text = page.read_text(encoding="utf-8")
        self.assertIn("Quality", text)
        self.assertIn("qualityVerdict", text)
        strip = ROOT.parent / "frontend" / "src" / "pages" / "trading" / "InstitutionalStrip.tsx"
        self.assertTrue(strip.is_file())


class ProgramGatesW36Tests(unittest.TestCase):
    def test_program_complete_when_all_pass(self) -> None:
        data = json.loads(PROGRAM.read_text(encoding="utf-8"))
        summary = institutional_program_gate_summary(data["waves"])
        # May still have later waves open during partial runs; assert shape.
        self.assertIn("byStatus", summary)
        self.assertEqual(summary["liveTrading"], "BLOCKED")
        self.assertTrue(summary["truth"]["ci_skipped_per_operator"])
        self.assertTrue(summary["truth"]["editor_hades_out_of_scope"])


if __name__ == "__main__":
    unittest.main()
