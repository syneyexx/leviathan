"""Wave 13 — strategy lifecycle persistence hooks + evidence bindings."""

from __future__ import annotations

import unittest
from typing import Any

from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.institutional_core.strategy_lifecycle import (
    StrategyLifecycle,
    StrategyLifecycleRecord,
    StrategyLifecycleService,
)


class _MemoryLifecycleStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []

    def save_strategy_lifecycle(self, row: dict[str, Any]) -> dict[str, Any]:
        key = f"{row['strategy_id']}@{row['strategy_version']}"
        self.rows[key] = dict(row)
        return self.rows[key]

    def get_strategy_lifecycle(self, strategy_id: str, version: str) -> dict[str, Any] | None:
        return self.rows.get(f"{strategy_id}@{version}")

    def append_audit_event(self, event: dict[str, Any]) -> None:
        self.audits.append(dict(event))


class StrategyLifecyclePersistW13Tests(unittest.TestCase):
    def test_service_alias_and_no_degraded(self) -> None:
        self.assertIs(StrategyLifecycleService, StrategyLifecycle)
        life = StrategyLifecycle()
        life.upsert(StrategyLifecycleRecord(strategy_id="s", version="1", state="PAPER"))
        with self.assertRaises(ValueError):
            life.transition("s", "1", new_state="DEGRADED", actor="x", ts="t0")

    def test_in_memory_when_store_missing_methods(self) -> None:
        class _Bare:
            pass

        life = StrategyLifecycle(store=_Bare())
        rec = life.upsert(StrategyLifecycleRecord(strategy_id="s1", version="1", state="IDEA"))
        self.assertEqual(rec.state, "IDEA")
        moved = life.transition("s1", "1", new_state="RESEARCH", actor="a", ts="t1")
        self.assertEqual(moved.state, "RESEARCH")
        self.assertEqual(len(life.audit_events()), 1)

    def test_persists_via_store_hooks(self) -> None:
        store = _MemoryLifecycleStore()
        life = StrategyLifecycle(store=store)
        life.upsert(StrategyLifecycleRecord(strategy_id="s1", version="3", state="BACKTEST"))
        self.assertIn("s1@3", store.rows)

        life.transition(
            "s1",
            "3",
            new_state="VALIDATION",
            actor="quant",
            ts="t1",
            extra_evidence={"backtest_completed": MeasurementState.PASS.value},
        )
        self.assertEqual(store.rows["s1@3"]["state"], "VALIDATION")
        self.assertTrue(store.audits)
        self.assertEqual(store.audits[-1]["kind"], "STRATEGY_LIFECYCLE_TRANSITION")

        # Fresh service loads from store.
        life2 = StrategyLifecycle(store=store)
        loaded = life2.get("s1", "3")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.state, "VALIDATION")

    def test_sealed_eval_to_paper_requires_qualified_and_sealed(self) -> None:
        life = StrategyLifecycle()
        life.upsert(StrategyLifecycleRecord(strategy_id="s1", version="1", state="SEALED_EVAL"))
        with self.assertRaises(ValueError):
            life.transition(
                "s1",
                "1",
                new_state="PAPER",
                actor="pm",
                ts="t0",
                evidence_key="sealed_holdout",
                evidence_state=MeasurementState.PASS.value,
            )
        with self.assertRaises(ValueError):
            life.transition(
                "s1",
                "1",
                new_state="PAPER",
                actor="pm",
                ts="t1",
                extra_evidence={"qualification_decision": "QUALIFIED"},
                qualification_id="q1",
            )
        ok = life.transition(
            "s1",
            "1",
            new_state="PAPER",
            actor="pm",
            ts="t2",
            qualification_id="q1",
            extra_evidence={
                "qualification_decision": "QUALIFIED",
                "sealed_holdout": MeasurementState.PASS.value,
            },
        )
        self.assertEqual(ok.state, "PAPER")
        self.assertEqual(ok.qualification_id, "q1")
        self.assertEqual(len(life.audit_events()), 1)

    def test_validation_to_sealed_requires_qualification_gates(self) -> None:
        life = StrategyLifecycle()
        life.upsert(StrategyLifecycleRecord(strategy_id="s1", version="1", state="VALIDATION"))
        with self.assertRaises(ValueError):
            life.transition("s1", "1", new_state="SEALED_EVAL", actor="a", ts="t0")
        ok = life.transition(
            "s1",
            "1",
            new_state="SEALED_EVAL",
            actor="a",
            ts="t1",
            extra_evidence={
                "qualification_wfa": MeasurementState.PASS.value,
                "qualification_statistics": MeasurementState.PASS.value,
                "qualification_robustness": MeasurementState.PASS.value,
            },
        )
        self.assertEqual(ok.state, "SEALED_EVAL")

    def test_champion_path_evidence_and_retire(self) -> None:
        life = StrategyLifecycle()
        life.upsert(
            StrategyLifecycleRecord(
                strategy_id="s1",
                version="1",
                state="PAPER",
                evidence={"sealed_holdout": MeasurementState.PASS.value},
            )
        )
        life.transition(
            "s1",
            "1",
            new_state="CHALLENGER",
            actor="gov",
            ts="t1",
            extra_evidence={"paper_evidence": MeasurementState.OBSERVED.value},
        )
        life.transition(
            "s1",
            "1",
            new_state="CHAMPION",
            actor="gov",
            ts="t2",
            extra_evidence={"forward_evidence": MeasurementState.PASS.value},
        )
        retired = life.transition(
            "s1",
            "1",
            new_state="RETIRED",
            actor="gov",
            ts="t3",
            extra_evidence={"retirement_policy": "PRESENT"},
        )
        self.assertEqual(retired.state, "RETIRED")
        self.assertEqual(len(life.audit_events()), 3)


if __name__ == "__main__":
    unittest.main()
