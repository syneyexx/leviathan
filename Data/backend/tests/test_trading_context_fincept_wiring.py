"""Production wiring: TradingContextFabric + FinceptEvidenceBridge honesty."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from Data.modules.market_sim.fincept_bridge import (
    FinceptAvailabilityState,
    FinceptEvidenceBridge,
    FinceptInvocationRequest,
    FinceptResultState,
    discover_fincept_capabilities,
    map_module_status_to_fincept_availability,
)
from Data.modules.market_sim.orchestra.executors import ExecutionContext
from Data.modules.market_sim.orchestra.model_adapter import UnavailableTradingModel
from Data.modules.market_sim.orchestra.types import Mandate, MissionKind
from Data.modules.market_sim.trading_context import (
    TradingContextFabric,
    TradingContextRequest,
)


class _FakeStore:
    def append_decision(self, rec):  # noqa: ANN001
        return rec


class TradingContextFabricProductionPathTests(unittest.TestCase):
    def test_orchestra_bind_role_experience_invokes_fabric_assemble(self) -> None:
        """Production-like orchestra decision context must call TradingContextFabric.assemble."""
        assemble_calls: list[TradingContextRequest] = []

        class _Fabric:
            def assemble(self, request: TradingContextRequest):
                assemble_calls.append(request)
                real = TradingContextFabric(
                    strategy_memory_lister=lambda **_k: [
                        {
                            "memory_id": "rej-1",
                            "strategy_id": "s-rej",
                            "outcome_summary": "cost failure",
                            "rejected": True,
                            "available_at": "2024-01-01T00:00:00+00:00",
                            "metadata": {"epistemic_state": "REJECTED"},
                        }
                    ]
                )
                return real.assemble(request)

        ctx = ExecutionContext(
            orchestra_id="orch-1",
            mission_id="m-1",
            mandate=Mandate(),
            as_of="2024-06-01T00:00:00+00:00",
            mission_kind=MissionKind.DELIBERATION_ROUND,
            model=UnavailableTradingModel(),
            store=_FakeStore(),
            trading_context_fabric=_Fabric(),
        )
        payload = ctx.bind_role_experience(
            "critic",
            "challenge BTC proposal",
            symbols=["BTCUSD"],
            regime="up",
        )
        self.assertEqual(len(assemble_calls), 1)
        self.assertEqual(assemble_calls[0].role, "critic")
        self.assertEqual(assemble_calls[0].symbols, ["BTCUSD"])
        self.assertEqual(assemble_calls[0].decision_as_of, "2024-06-01T00:00:00+00:00")
        self.assertGreaterEqual(int(payload.get("negativeExperienceCount") or 0), 1)
        self.assertTrue((payload.get("truth") or {}).get("trading_context_fabric"))
        self.assertIn("rej-1", payload.get("evidenceRefs") or [])

    def test_orchestra_service_builds_fabric_for_execution_context(self) -> None:
        from Data.modules.market_sim.orchestra.service import TradingOrchestraService
        from Data.modules.market_sim.orchestra.store import OrchestraStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            store = OrchestraStore(Path(tmp) / "orch.db")
            store.initialize()
            service = TradingOrchestraService(store=store, enabled=True)
            self.assertIsNotNone(service.trading_context_fabric)
            self.assertTrue(hasattr(service.trading_context_fabric, "assemble"))


class FinceptAvailabilityHonestyTests(unittest.TestCase):
    def test_unknown_must_not_become_available(self) -> None:
        self.assertEqual(
            map_module_status_to_fincept_availability("UNKNOWN"),
            FinceptAvailabilityState.UNKNOWN,
        )
        self.assertEqual(
            map_module_status_to_fincept_availability(None),
            FinceptAvailabilityState.UNKNOWN,
        )
        self.assertEqual(
            map_module_status_to_fincept_availability("TOTALLY_MADE_UP"),
            FinceptAvailabilityState.UNKNOWN,
        )
        # Health READY cannot promote UNKNOWN lifecycle to AVAILABLE.
        self.assertEqual(
            map_module_status_to_fincept_availability("UNKNOWN", health_status="READY"),
            FinceptAvailabilityState.UNKNOWN,
        )
        info = discover_fincept_capabilities()
        self.assertEqual(info["state"], FinceptAvailabilityState.UNKNOWN.value)
        self.assertFalse(info["available"])
        self.assertNotEqual(info["state"], FinceptAvailabilityState.AVAILABLE.value)

    def test_unhealthy_module_manager_not_reported_available(self) -> None:
        managed = SimpleNamespace(
            status=SimpleNamespace(value="DEGRADED"),
            manifest=SimpleNamespace(capabilities=[]),
        )
        mm = mock.Mock()
        mm.enabled = True
        mm.get.return_value = managed
        mm.health.return_value = SimpleNamespace(status=SimpleNamespace(value="DEGRADED"))

        info = discover_fincept_capabilities(module_manager=mm)
        self.assertEqual(info["state"], FinceptAvailabilityState.UNHEALTHY.value)
        self.assertFalse(info["available"])
        self.assertNotEqual(info["state"], FinceptAvailabilityState.AVAILABLE.value)

        bridge = FinceptEvidenceBridge()
        discovery = bridge.bind_from_module_manager(mm)
        self.assertEqual(discovery["state"], FinceptAvailabilityState.UNHEALTHY.value)
        self.assertIsNone(bridge.executor)
        art = bridge.invoke(
            FinceptInvocationRequest(
                capability_id="external.fincept.analyze",
                role="strategy_researcher",
                objective="quant analytics on spreads",
                command="analyze",
                justified=True,
            )
        )
        self.assertEqual(art.result_state, FinceptResultState.UNHEALTHY)
        self.assertNotEqual(art.result_state, FinceptResultState.COMPLETED)

    def test_missing_module_not_available(self) -> None:
        mm = mock.Mock()
        mm.enabled = True
        mm.get.return_value = None
        mm.discover.return_value = []

        info = discover_fincept_capabilities(module_manager=mm)
        self.assertEqual(info["state"], FinceptAvailabilityState.UNAVAILABLE.value)
        self.assertFalse(info["available"])

        bridge = FinceptEvidenceBridge()
        bridge.bind_from_module_manager(mm)
        self.assertFalse(bridge.module_installed)
        self.assertIsNone(bridge.executor)

    def test_ready_binds_executor_via_module_manager(self) -> None:
        cap = SimpleNamespace(
            public_dict=lambda: {
                "capability_id": "external.fincept.analyze",
                "name": "Fincept Analyze",
            }
        )
        managed = SimpleNamespace(
            status=SimpleNamespace(value="READY"),
            manifest=SimpleNamespace(capabilities=(cap,)),
        )
        mm = mock.Mock()
        mm.enabled = True
        mm.get.return_value = managed
        mm.health.return_value = SimpleNamespace(status=SimpleNamespace(value="READY"))
        mm.execute.return_value = SimpleNamespace(
            status="COMPLETED",
            output={"metrics": {"pe": 12.0}},
            error=None,
            public_dict=lambda: {"status": "COMPLETED", "output": {"metrics": {"pe": 12.0}}},
        )

        bridge = FinceptEvidenceBridge()
        discovery = bridge.bind_from_module_manager(mm)
        self.assertEqual(discovery["state"], FinceptAvailabilityState.AVAILABLE.value)
        self.assertTrue(discovery["available"])
        self.assertIsNotNone(bridge.executor)

        art = bridge.invoke(
            FinceptInvocationRequest(
                capability_id="external.fincept.analyze",
                role="strategy_researcher",
                objective="compute financial ratios for AAPL",
                command="get_key_metrics",
                justified=True,
            )
        )
        self.assertEqual(art.result_state, FinceptResultState.COMPLETED)
        mm.execute.assert_called()


if __name__ == "__main__":
    unittest.main()
