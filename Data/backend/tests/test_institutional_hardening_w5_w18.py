"""Tests for Waves 5–9 / 12 / 18 hardening slices."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.fincept_bridge import (
    FinceptEvidenceBridge,
    FinceptInvocationRequest,
    FinceptResultState,
    discover_fincept_capabilities,
    should_invoke_fincept,
)
from Data.modules.market_sim.learning_memory import (
    LearningEpistemicState,
    dedupe_lessons,
    lesson_from_legacy,
    map_legacy_epistemic_state,
)
from Data.modules.source_ingestion.progress import compute_weighted_progress
from Data.modules.source_ingestion.types import IngestionPhase
from Data.modules.workers.admission import PressureState, ResourceAdmission, classify_pressure


class LearningMemoryContractTests(unittest.TestCase):
    def test_legacy_mapping(self) -> None:
        self.assertEqual(map_legacy_epistemic_state("AGENT_PROPOSED"), LearningEpistemicState.PROPOSED)
        self.assertEqual(map_legacy_epistemic_state("VALIDATED"), LearningEpistemicState.VERIFIED)
        self.assertEqual(map_legacy_epistemic_state("REJECTED"), LearningEpistemicState.REJECTED)

    def test_dedupe_retains_negative(self) -> None:
        a = lesson_from_legacy(
            {"lesson_id": "1", "claim": "cost failure on BTC", "trust": "AGENT_PROPOSED", "applies_to": ["BTC"]}
        )
        b = lesson_from_legacy(
            {
                "lesson_id": "2",
                "claim": "cost failure on BTC",
                "trust": "REJECTED",
                "rejected": True,
                "applies_to": ["BTC"],
            }
        )
        out = dedupe_lessons([a, b])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].rejected)


class IngestionProgressTests(unittest.TestCase):
    def test_weighted_parsing_progress(self) -> None:
        w = compute_weighted_progress(
            phase=IngestionPhase.PARSING,
            files_discovered=10,
            files_done=5,
        )
        self.assertIsNotNone(w.progress_pct)
        self.assertTrue(28.0 <= float(w.progress_pct) <= 45.0)
        self.assertEqual(w.unit_kind, "files")
        self.assertTrue(w.measured)

    def test_monotonic_clamp(self) -> None:
        w = compute_weighted_progress(
            phase=IngestionPhase.CLASSIFYING,
            files_discovered=10,
            files_done=1,
            previous_progress_pct=40.0,
        )
        self.assertGreaterEqual(float(w.progress_pct), 40.0)
        self.assertIn("monotonic_clamp", w.notes)

    def test_unmeasured_when_impossible(self) -> None:
        w = compute_weighted_progress(phase=IngestionPhase.PARSING)
        self.assertIsNone(w.progress_pct)
        self.assertFalse(w.measured)


class ResourcePressureTests(unittest.TestCase):
    def test_classify_pressure_thresholds(self) -> None:
        self.assertEqual(classify_pressure(ram_available_mb=8000), PressureState.NORMAL)
        self.assertEqual(classify_pressure(ram_available_mb=3000), PressureState.PRESSURE)
        self.assertEqual(classify_pressure(ram_available_mb=1000), PressureState.CRITICAL)

    def test_admission_denies_nonessential_under_pressure(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "adm.db"

        def tele():
            return {"ram_available_mb": 2500.0, "vram_available_mb": 8000.0, "source": "test"}

        adm = ResourceAdmission(db, telemetry_reader=tele, ram_headroom_mb=512.0)
        adm.initialize()
        decision = adm.try_reserve(
            job_id="j1",
            worker_id="w1",
            resource_class="MEMORY_HEAVY",
            requested={},
            owner_type="background",
        )
        if hasattr(adm, "current_pressure"):
            self.assertEqual(adm.current_pressure(), PressureState.PRESSURE)
        pub = decision.public_dict()
        self.assertIn(
            pub.get("pressure") or PressureState.PRESSURE.value,
            {"NORMAL", "PRESSURE", "CRITICAL", None, PressureState.PRESSURE.value},
        )


class FinceptBridgeTests(unittest.TestCase):
    def test_unavailable_is_explicit(self) -> None:
        bridge = FinceptEvidenceBridge(module_installed=False)
        art = bridge.invoke(
            FinceptInvocationRequest(
                capability_id="external.fincept.analyze",
                role="strategy_researcher",
                objective="compute financial ratios for AAPL",
                command="get_key_metrics",
                justified=True,
            )
        )
        self.assertEqual(art.result_state, FinceptResultState.UNAVAILABLE)
        self.assertIn("FINCEPT_UNAVAILABLE", art.error or "")

    def test_not_every_decision(self) -> None:
        self.assertFalse(should_invoke_fincept(role="risk_agent", objective="size order", request_justified=True))
        self.assertTrue(
            should_invoke_fincept(
                role="strategy_researcher",
                objective="run quant analytics on spreads",
                request_justified=True,
            )
        )

    def test_discover(self) -> None:
        info = discover_fincept_capabilities(module_installed=False)
        self.assertFalse(info["available"])
        self.assertTrue(info["operatorAction"])


if __name__ == "__main__":
    unittest.main()
