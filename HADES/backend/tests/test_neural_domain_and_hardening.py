"""Phase 13 domain memory + Phase 21 product controller hardening tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _torch_or_skip(test: unittest.TestCase):
    from neural.deps import neural_available

    if not neural_available():
        test.skipTest("torch unavailable")
    import torch

    return torch


class DomainMemoryTests(unittest.TestCase):
    def test_coding_update_preserves_research(self) -> None:
        from neural.domain_memory import DomainMemoryRegistry, NeuralDomain

        reg = DomainMemoryRegistry()
        before = {d.value: type(reg.bank(d))(domain=d, version=reg.bank(d).version) for d in NeuralDomain}
        reg.bump_version(NeuralDomain.CODING, checkpoint_id="coding_v1")
        preserved = reg.preserve_other_domains(NeuralDomain.CODING, before=before)
        self.assertTrue(preserved["research"])
        self.assertTrue(preserved["general"])
        self.assertEqual(reg.bank(NeuralDomain.CODING).version, 1)
        self.assertEqual(reg.bank(NeuralDomain.RESEARCH).version, 0)

    def test_research_update_preserves_coding(self) -> None:
        from neural.domain_memory import DomainMemoryRegistry, NeuralDomain

        reg = DomainMemoryRegistry()
        reg.bump_version(NeuralDomain.CODING, checkpoint_id="coding_v1")
        before = {d.value: type(reg.bank(d))(domain=d, version=reg.bank(d).version) for d in NeuralDomain}
        reg.bump_version(NeuralDomain.RESEARCH, checkpoint_id="research_v1")
        preserved = reg.preserve_other_domains(NeuralDomain.RESEARCH, before=before)
        self.assertTrue(preserved["coding"])
        self.assertEqual(reg.bank(NeuralDomain.CODING).checkpoint_id, "coding_v1")

    def test_general_independently_versioned(self) -> None:
        from neural.domain_memory import DomainMemoryRegistry, NeuralDomain

        reg = DomainMemoryRegistry()
        reg.bump_version(NeuralDomain.GENERAL, checkpoint_id="general_v12")
        self.assertEqual(reg.bank(NeuralDomain.GENERAL).version, 1)
        self.assertEqual(reg.bank(NeuralDomain.CODING).version, 0)

    def test_domain_routing_deterministic(self) -> None:
        from neural.domain_memory import route_domains, NeuralDomain

        a = route_domains("fix pytest failure in worker pool")
        b = route_domains("fix pytest failure in worker pool")
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(a.primary, NeuralDomain.CODING)
        self.assertIn(NeuralDomain.GENERAL, a.domains)

    def test_wrong_domain_checkpoint_fails(self) -> None:
        from neural.domain_memory import DomainMemoryRegistry, NeuralDomain
        from neural.errors import NeuralDomainMismatch

        reg = DomainMemoryRegistry()
        reg.bump_version(NeuralDomain.CODING, checkpoint_id="coding_v1")
        with self.assertRaises(NeuralDomainMismatch):
            reg.assert_domain_checkpoint(NeuralDomain.CODING, "research_v9")

    def test_fusion_bounded_and_domain_disable(self) -> None:
        from neural.domain_memory import DomainMemoryRegistry, NeuralDomain

        reg = DomainMemoryRegistry(max_fused_domains=2)
        reg.set_enabled(NeuralDomain.RESEARCH, False)
        decision = reg.select_for_task("research claim with citation evidence")
        self.assertNotIn(NeuralDomain.RESEARCH, decision.domains)
        self.assertLessEqual(len(decision.domains), 2)


class ProductControllerHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.product_controller import NeuralCapacityConfig, NeuralProductController, reset_neural_product_controller_for_tests

        reset_neural_product_controller_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.controller = NeuralProductController(
            work_dir=Path(self.tmp.name) / "neural",
            capacity=NeuralCapacityConfig(max_concurrent_infer=1, acquire_timeout_s=0.2),
        )

    def tearDown(self) -> None:
        try:
            self.controller.stop()
        except Exception:
            pass
        self.tmp.cleanup()

    def test_disabled_start_allocates_no_engine(self) -> None:
        status = self.controller.start(mode="off", allow=False)
        self.assertFalse(status["ready"])
        self.assertFalse(status["started"])
        self.assertIsNone(self.controller.boundary._engine)

    def test_start_stop_restart_persistence(self) -> None:
        from neural.contracts import NeuralMode

        self.controller.start(mode=NeuralMode.OFF, allow=True, auto_load_model=True)
        # OFF with allow still starts boundary in OFF mode (engine may load for research).
        self.controller.record_promotion("slow_v3")
        manifest = self.controller.save_manifest()
        self.assertEqual(manifest.known_good_checkpoint_id, "slow_v3")
        self.controller.stop()
        # New controller instance from same work_dir restores manifest.
        from neural.product_controller import NeuralProductController

        restored = NeuralProductController(work_dir=self.controller.work_dir)
        self.assertEqual(restored._manifest.known_good_checkpoint_id, "slow_v3")
        self.assertEqual(restored.domains.bank("general").checkpoint_id, "slow_v3")
        restored.stop()

    def test_soak_start_infer_stop_cycles(self) -> None:
        from neural.contracts import NeuralInferRequest, NeuralMode

        for i in range(8):
            self.controller.start(mode=NeuralMode.READ, allow=True, auto_load_model=True)
            status = self.controller.status()
            self.assertTrue(status["ready"], status)
            out = self.controller.infer(
                NeuralInferRequest(request_id=f"soak-{i}", input_ids=[[1, 2, 3]], mode=NeuralMode.READ)
            )
            self.assertIsNotNone(out)
            self.controller.stop()
            self.assertEqual(self.controller.boundary.health().state.value, "stopped")

    def test_capacity_blocks_oversubscribe(self) -> None:
        import threading

        from neural.contracts import NeuralInferRequest, NeuralMode
        from neural.errors import NeuralCapacityExceeded

        self.controller.start(mode=NeuralMode.READ, allow=True, auto_load_model=True)
        entered = threading.Event()
        release = threading.Event()

        def _hold() -> None:
            # Acquire slot then block until released.
            acquired = self.controller._infer_slots.acquire(timeout=1.0)
            self.assertTrue(acquired)
            entered.set()
            release.wait(timeout=2.0)
            self.controller._infer_slots.release()

        t = threading.Thread(target=_hold)
        t.start()
        self.assertTrue(entered.wait(timeout=1.0))
        with self.assertRaises(NeuralCapacityExceeded):
            self.controller.infer(
                NeuralInferRequest(request_id="cap", input_ids=[[1]], mode=NeuralMode.READ)
            )
        release.set()
        t.join(timeout=2.0)
        self.controller.stop()

    def test_cancellation_increments_metrics(self) -> None:
        from neural.contracts import NeuralInferRequest, NeuralMode
        from neural.errors import NeuralRuntimeCancelled

        self.controller.start(mode=NeuralMode.READ, allow=True, auto_load_model=True)
        self.controller.cancel()
        with self.assertRaises(NeuralRuntimeCancelled):
            self.controller.infer(
                NeuralInferRequest(request_id="c", input_ids=[[1, 2]], mode=NeuralMode.READ)
            )
        self.assertGreaterEqual(self.controller.boundary.metrics().cancel_count, 1)
        self.controller.stop()

    def test_oom_mapped_to_typed_error(self) -> None:
        from neural.contracts import NeuralInferRequest, NeuralMode
        from neural.errors import NeuralRuntimeOOM

        self.controller.start(mode=NeuralMode.READ, allow=True, auto_load_model=True)

        def _boom(_req):
            raise RuntimeError("CUDA out of memory")

        self.controller.boundary.infer = _boom  # type: ignore[method-assign]
        with self.assertRaises(NeuralRuntimeOOM):
            self.controller.infer(
                NeuralInferRequest(request_id="oom", input_ids=[[1]], mode=NeuralMode.READ)
            )
        self.controller.stop()


class NeuralRoutesSmokeTests(unittest.TestCase):
    def test_status_disabled_without_torch_start(self) -> None:
        import tempfile
        from pathlib import Path

        from database import Database
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neural_routes import mount_neural_routes
        from neural.product_controller import reset_neural_product_controller_for_tests

        reset_neural_product_controller_for_tests()
        tmp = tempfile.TemporaryDirectory()
        db = Database(Path(tmp.name) / "hades.db")
        db.initialize()
        app = FastAPI()
        app.include_router(mount_neural_routes({"database": db}), prefix="/api")
        client = TestClient(app)
        response = client.get("/api/neural/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["product_state"], "disabled")
        settings = client.get("/api/neural/settings").json()
        self.assertEqual(settings["neural_mode"], "off")
        self.assertEqual(settings["learn_default"], "disabled")
        patched = client.patch("/api/neural/settings", json={"neural_mode": "shadow", "neural_allow": True})
        self.assertEqual(patched.status_code, 200)
        self.assertTrue(patched.json()["values"]["neural_allow"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
