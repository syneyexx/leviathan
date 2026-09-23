"""Round 9 — Product Truth exit gates."""

from __future__ import annotations

import unittest

from Data.modules.product_truth import (
    ProductStatus,
    assess_product_truth,
    confidence_is_meaningless,
    normalize_status,
)


class ProductTruthVocabularyTests(unittest.TestCase):
    def test_vocabulary_covers_required_states(self) -> None:
        values = {s.value for s in ProductStatus}
        for required in (
            "operational",
            "degraded",
            "experimental",
            "fixture",
            "unavailable",
            "unconfigured",
            "unmeasured",
        ):
            self.assertIn(required, values)

    def test_import_success_alone_is_not_operational(self) -> None:
        # Feature disabled / no servers → unconfigured, never operational.
        report = assess_product_truth(
            backend_alive=True,
            observability_durable=True,
            jobs_queued=0,
            module_manager_enabled=True,
            module_count=1,
            mcp_feature_enabled=True,
            mcp_server_count=0,
            mcp_connected_count=0,
            telemetry_partial=False,
            browser_backend_kind="fixture",
            browser_production_capable=False,
            model_gateway_health="healthy",
            model_provider_count=0,
            embedding_available=False,
            agents_enabled=True,
            training_fixture_default=True,
            media_backend_kind="fixture",
            media_production_capable=False,
            voice_backend_kind="stub",
            voice_production_capable=False,
        )
        by_id = {c.id: c for c in report.components}
        self.assertEqual(by_id["mcp_bridge"].status, ProductStatus.UNCONFIGURED)
        self.assertEqual(by_id["browser"].status, ProductStatus.FIXTURE)
        self.assertEqual(by_id["models"].status, ProductStatus.UNCONFIGURED)
        self.assertEqual(by_id["training"].status, ProductStatus.FIXTURE)
        self.assertEqual(by_id["media"].status, ProductStatus.FIXTURE)
        self.assertEqual(by_id["voice"].status, ProductStatus.FIXTURE)
        # Flag-on alone is unmeasured, not operational.
        self.assertEqual(by_id["agents"].status, ProductStatus.UNMEASURED)
        self.assertEqual(by_id["module_manager"].status, ProductStatus.UNMEASURED)
        self.assertNotEqual(by_id["browser"].status, ProductStatus.OPERATIONAL)
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["import_success_is_not_operational"])
        self.assertTrue(payload["truth"]["fixture_is_not_production"])

    def test_empty_mcp_servers_not_healthy(self) -> None:
        report = assess_product_truth(
            backend_alive=True,
            observability_durable=True,
            jobs_queued=0,
            mcp_feature_enabled=True,
            mcp_server_count=0,
            mcp_connected_count=0,
            telemetry_partial=False,
        )
        mcp = next(c for c in report.components if c.id == "mcp_bridge")
        self.assertEqual(mcp.status, ProductStatus.UNCONFIGURED)
        self.assertNotEqual(mcp.status.value, "healthy")

    def test_legacy_healthy_normalizes_to_operational(self) -> None:
        self.assertEqual(normalize_status("healthy"), ProductStatus.OPERATIONAL)
        self.assertEqual(normalize_status("unknown"), ProductStatus.UNMEASURED)

    def test_confidence_without_evidence_is_meaningless(self) -> None:
        self.assertTrue(confidence_is_meaningless(95, evidence=None))
        self.assertTrue(confidence_is_meaningless(95, evidence=[]))
        self.assertFalse(confidence_is_meaningless(80, evidence=["span-1"]))


class ProductTruthLocalDomTests(unittest.TestCase):
    def test_local_dom_browser_can_be_operational(self) -> None:
        report = assess_product_truth(
            backend_alive=True,
            observability_durable=True,
            jobs_queued=0,
            telemetry_partial=False,
            browser_backend_kind="local_dom",
            browser_production_capable=True,
            model_gateway_health="healthy",
            model_provider_count=1,
            embedding_available=True,
            agents_enabled=False,
            mcp_feature_enabled=False,
            media_backend_kind="fixture",
            media_production_capable=False,
            voice_backend_kind="fixture",
            voice_production_capable=False,
        )
        browser = next(c for c in report.components if c.id == "browser")
        self.assertEqual(browser.status, ProductStatus.OPERATIONAL)
        self.assertTrue(browser.measured)

    def test_health_helpers_expose_posture_not_only_ok(self) -> None:
        import Data.backend.main as main

        snap = main._product_truth_snapshot()
        self.assertIn("overall", snap)
        self.assertIn("vocabulary", snap)
        self.assertNotIn("healthy", [c["status"] for c in snap["components"]])
        media = next(c for c in snap["components"] if c["id"] == "media")
        self.assertEqual(media["status"], "fixture")


if __name__ == "__main__":
    unittest.main()
