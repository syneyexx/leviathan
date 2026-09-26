"""Failure-path cases for institutional_core (deterministic, no network)."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.institutional_core.assurance import verify_live_trading_blocked
from Data.modules.market_sim.institutional_core.entitlements import (
    ChangeRequest,
    evaluate_approval,
)
from Data.modules.market_sim.institutional_core.exceptions_ops import (
    ExceptionRegistry,
    OpsException,
)
from Data.modules.market_sim.institutional_core.model_risk import (
    ModelCard,
    ModelRiskRegistry,
)
from Data.modules.market_sim.institutional_core.order_lifecycle import Order, OrderLifecycle
from Data.modules.market_sim.institutional_core.reconciliation import (
    Break,
    transition_break,
)
from Data.modules.market_sim.institutional_core.resilience import (
    build_backup_manifest,
    fault_inject,
    verify_restore,
)
from Data.modules.market_sim.institutional_core.status import MeasurementState
from Data.modules.market_sim.institutional_core.strategy_lifecycle import (
    StrategyLifecycle,
    StrategyLifecycleRecord,
)


class ReconciliationFailurePaths(unittest.TestCase):
    def test_open_to_resolved_refused(self) -> None:
        brk = Break(
            break_id="b1",
            domain="cash",
            field="qty",
            left_system="a",
            right_system="b",
            left_key="k",
            right_key="k",
            left_value=1,
            right_value=2,
        )
        with self.assertRaises(ValueError):
            transition_break(brk, new_status="RESOLVED", actor="bot", ts="t", note="nope")
        with self.assertRaises(ValueError):
            transition_break(
                brk, new_status="WAIVED", actor="bot", ts="t", note="auto", auto=True
            )


class OrderFailurePaths(unittest.TestCase):
    def test_live_create_and_transition_blocked(self) -> None:
        life = OrderLifecycle()
        order = life.create(Order(order_id="L1", symbol="AAPL", side="BUY", qty=1, mode="LIVE"))
        self.assertEqual(order.state, "REJECTED")
        with self.assertRaises(PermissionError):
            life.transition("L1", new_state="ACCEPTED", ts="t")


class ModelRiskFailurePaths(unittest.TestCase):
    def test_illegal_and_unvalidated_approval(self) -> None:
        reg = ModelRiskRegistry()
        reg.register(ModelCard("m", "n", "1", "o", state="CANDIDATE"))
        with self.assertRaises(ValueError):
            reg.transition("m", new_state="PRODUCTION", actor="a", ts="t")
        reg.transition("m", new_state="IN_VALIDATION", actor="a", ts="t")
        with self.assertRaises(ValueError):
            reg.transition(
                "m",
                new_state="APPROVED",
                actor="a",
                ts="t",
                validation_evidence=MeasurementState.UNMEASURED.value,
            )


class StrategyFailurePaths(unittest.TestCase):
    def test_champion_without_sealed_evidence(self) -> None:
        life = StrategyLifecycle()
        life.upsert(StrategyLifecycleRecord("s", "1", state="CHALLENGER"))
        with self.assertRaises(ValueError):
            life.transition("s", "1", new_state="CHAMPION", actor="pm", ts="t")


class EntitlementFailurePaths(unittest.TestCase):
    def test_same_actor_and_insufficient_authority(self) -> None:
        change = ChangeRequest(
            change_id="c",
            kind="LIMIT_LOOSEN",
            maker_id="maker",
            payload={},
            required_authority="risk_officer",
        )
        own = evaluate_approval(change, checker_id="maker", checker_roles=["admin"])
        self.assertFalse(own.allowed)
        weak = evaluate_approval(change, checker_id="other", checker_roles=["viewer"])
        self.assertFalse(weak.allowed)
        self.assertTrue(any("insufficient_authority" in r for r in weak.reasons))


class ExceptionFailurePaths(unittest.TestCase):
    def test_silent_resolve_from_open_forbidden(self) -> None:
        reg = ExceptionRegistry()
        reg.open(OpsException("e", "DATA", "LOW", "x"))
        with self.assertRaises(ValueError):
            reg.transition("e", new_status="RESOLVED", actor="bot", ts="t", note="done")


class ResilienceFailurePaths(unittest.TestCase):
    def test_missing_and_corrupt_restore(self) -> None:
        docs = {"a": {"v": 1}, "b": {"v": 2}}
        manifest = build_backup_manifest(
            manifest_id="m", created_at="t0", documents=docs
        )
        dropped = fault_inject(docs, drop_keys=["b"])
        missing = verify_restore(manifest, dropped)
        self.assertFalse(missing["ok"])
        self.assertIn("missing:b", missing["errors"])


class LiveTradingFailurePaths(unittest.TestCase):
    def test_live_remains_blocked(self) -> None:
        status = verify_live_trading_blocked()
        self.assertTrue(status["ok"])
        self.assertEqual(status["LIVE_TRADING_AVAILABLE"], MeasurementState.BLOCKED.value)


if __name__ == "__main__":
    unittest.main()
