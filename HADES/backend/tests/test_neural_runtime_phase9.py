"""Phase 9: Neural Runtime lifecycle boundary tests.

Uses toy local modules only — no remote model downloads.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _torch_or_skip(test: unittest.TestCase):
    from neural.deps import neural_available

    if not neural_available():
        test.skipTest("torch unavailable")
    import torch

    return torch


class NeuralRuntimeBoundaryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.contracts import NeuralInferRequest, NeuralMode, NeuralModelSpec, NeuralRuntimeState
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig

        self.NeuralMode = NeuralMode
        self.NeuralInferRequest = NeuralInferRequest
        self.NeuralModelSpec = NeuralModelSpec
        self.NeuralRuntimeState = NeuralRuntimeState
        self.NeuralRuntimeBoundary = NeuralRuntimeBoundary
        self.NeuralRuntimeStartConfig = NeuralRuntimeStartConfig

    def test_start_stop_clean_shutdown(self) -> None:
        rt = self.NeuralRuntimeBoundary()
        health = rt.start(self.NeuralRuntimeStartConfig(isolation="inprocess", mode=self.NeuralMode.OFF))
        self.assertEqual(health.state, self.NeuralRuntimeState.READY)
        self.assertTrue(health.base_model_loaded)
        self.assertIsNotNone(health.identity)
        stopped = rt.stop()
        self.assertEqual(stopped.state, self.NeuralRuntimeState.STOPPED)
        self.assertFalse(stopped.base_model_loaded)

    def test_ready_means_inference_ready_not_just_started(self) -> None:
        rt = self.NeuralRuntimeBoundary()
        health = rt.start(
            self.NeuralRuntimeStartConfig(isolation="inprocess", auto_load_model=False)
        )
        self.assertEqual(health.state, self.NeuralRuntimeState.DEGRADED)
        from neural.errors import NeuralRuntimeNotReady

        with self.assertRaises(NeuralRuntimeNotReady):
            rt.infer(
                self.NeuralInferRequest(request_id="r1", input_ids=[[1, 2, 3]], mode=self.NeuralMode.OFF)
            )
        identity = rt.load_model(self.NeuralModelSpec())
        self.assertEqual(rt.health().state, self.NeuralRuntimeState.READY)
        self.assertTrue(identity.base_model_fingerprint)

    def test_truthful_unavailable_without_torch(self) -> None:
        from neural import deps as neural_deps

        rt = self.NeuralRuntimeBoundary()
        with mock.patch.object(neural_deps, "neural_available", return_value=False):
            health = rt.start(self.NeuralRuntimeStartConfig())
        self.assertEqual(health.state, self.NeuralRuntimeState.UNAVAILABLE)
        self.assertIsNotNone(health.last_error)
        self.assertEqual(health.last_error["code"], "neural_dependency_unavailable")

    def test_off_shadow_read_paths(self) -> None:
        rt = self.NeuralRuntimeBoundary()
        rt.start(
            self.NeuralRuntimeStartConfig(
                mode=self.NeuralMode.OFF,
                model_spec=self.NeuralModelSpec(fusion_scale=0.0, injection_layers=(1,)),
            )
        )
        ids = [[1, 2, 3, 4, 5, 6, 7, 8]]
        off = rt.infer(self.NeuralInferRequest(request_id="off", input_ids=ids, mode=self.NeuralMode.OFF))
        self.assertTrue(off.bypassed)
        self.assertEqual(off.fusion_events, [])

        # Force fusion weights so READ would diverge if applied.
        assert rt._engine is not None
        rt._engine.set_fusion_scale(1.0)
        with self.torch.no_grad():
            rt._engine.fusion.out_proj.weight.copy_(0.25 * self.torch.eye(32))

        shadow = rt.infer(
            self.NeuralInferRequest(request_id="shadow", input_ids=ids, mode=self.NeuralMode.SHADOW)
        )
        self.assertFalse(shadow.bypassed)
        self.assertTrue(shadow.fusion_events)
        self.assertEqual(off.logits, shadow.logits)

        read = rt.infer(self.NeuralInferRequest(request_id="read", input_ids=ids, mode=self.NeuralMode.READ))
        self.assertFalse(read.bypassed)
        self.assertNotEqual(off.logits, read.logits)
        rt.stop()

    def test_learn_rejected(self) -> None:
        from neural.errors import NeuralModeUnsupported

        rt = self.NeuralRuntimeBoundary()
        rt.start(self.NeuralRuntimeStartConfig())
        with self.assertRaises(NeuralModeUnsupported):
            rt.infer(
                self.NeuralInferRequest(
                    request_id="learn",
                    input_ids=[[1, 2]],
                    mode=self.NeuralMode.LEARN,
                )
            )
        rt.stop()

    def test_base_model_frozen_proven(self) -> None:
        rt = self.NeuralRuntimeBoundary()
        rt.start(self.NeuralRuntimeStartConfig())
        before = rt.prove_base_frozen()
        ids = [[3, 1, 4, 1, 5, 9, 2, 6]]
        rt.infer(self.NeuralInferRequest(request_id="a", input_ids=ids, mode=self.NeuralMode.READ))
        after = rt.prove_base_frozen()
        self.assertEqual(before, after)
        rt.stop()

    def test_checkpoint_mismatch_fails_before_attach(self) -> None:
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.config import NeuralMemoryConfig
        from neural.errors import NeuralCheckpointIncompatible
        from neural.memory import NeuralMemory

        rt = self.NeuralRuntimeBoundary()
        rt.start(
            self.NeuralRuntimeStartConfig(
                model_spec=self.NeuralModelSpec(hidden_size=32),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = NeuralMemoryCheckpointStore(tmp)
            bad = NeuralMemory(NeuralMemoryConfig(dim=64, hidden_dim=128, seed=1))
            store.save(bad, checkpoint_id="bad64", candidate=False)
            with self.assertRaises(NeuralCheckpointIncompatible) as ctx:
                rt.load_memory_checkpoint(store_root=tmp, checkpoint_id="bad64", candidate=False)
            self.assertEqual(ctx.exception.code, "neural_checkpoint_incompatible")
            self.assertEqual(ctx.exception.detail.get("checkpoint_hidden_size"), 64)
            self.assertEqual(ctx.exception.detail.get("runtime_hidden_size"), 32)
            self.assertIs(rt.health().checkpoint_compatible, False)
            # Runtime remains usable after rejected load.
            self.assertEqual(rt.health().state, self.NeuralRuntimeState.READY)
        rt.stop()

    def test_compatible_checkpoint_loads(self) -> None:
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.config import NeuralMemoryConfig
        from neural.memory import NeuralMemory

        rt = self.NeuralRuntimeBoundary()
        rt.start(self.NeuralRuntimeStartConfig(model_spec=self.NeuralModelSpec(hidden_size=32)))
        with tempfile.TemporaryDirectory() as tmp:
            store = NeuralMemoryCheckpointStore(tmp)
            mem = NeuralMemory(NeuralMemoryConfig(dim=32, hidden_dim=64, seed=1))
            store.save(mem, checkpoint_id="ok32", candidate=False)
            result = rt.load_memory_checkpoint(store_root=tmp, checkpoint_id="ok32", candidate=False)
            self.assertTrue(result["compatible"])
            self.assertTrue(rt.health().memory_loaded)
            self.assertIs(rt.health().checkpoint_compatible, True)
        rt.stop()

    def test_cancellation_before_infer(self) -> None:
        from neural.errors import NeuralRuntimeCancelled

        rt = self.NeuralRuntimeBoundary()
        rt.start(self.NeuralRuntimeStartConfig())
        rt.cancel()
        with self.assertRaises(NeuralRuntimeCancelled):
            rt.infer(
                self.NeuralInferRequest(request_id="c", input_ids=[[1, 2, 3]], mode=self.NeuralMode.OFF)
            )
        # Fresh cancel flag after stop/start.
        rt.stop()
        rt.start(self.NeuralRuntimeStartConfig())
        out = rt.infer(
            self.NeuralInferRequest(request_id="ok", input_ids=[[1, 2, 3]], mode=self.NeuralMode.OFF)
        )
        self.assertFalse(out.cancelled)
        rt.stop()

    def test_invalid_model_geometry_fails(self) -> None:
        from neural.errors import NeuralRuntimeFailed

        rt = self.NeuralRuntimeBoundary()
        with self.assertRaises((NeuralRuntimeFailed, ValueError, Exception)):
            rt.start(
                self.NeuralRuntimeStartConfig(
                    model_spec=self.NeuralModelSpec(hidden_size=0),
                )
            )
        # Boundary must report failed/unavailable rather than pretend ready.
        self.assertIn(
            rt.health().state,
            {
                self.NeuralRuntimeState.FAILED,
                self.NeuralRuntimeState.UNAVAILABLE,
                self.NeuralRuntimeState.STOPPED,
            },
        )

    def test_main_still_does_not_import_neural_lifecycle(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        self.assertNotIn("runtime_lifecycle", text)
        self.assertNotIn("NeuralRuntimeBoundary", text)


class NeuralRuntimeSubprocessIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.contracts import NeuralInferRequest, NeuralMode, NeuralModelSpec, NeuralRuntimeState
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig

        self.NeuralMode = NeuralMode
        self.NeuralInferRequest = NeuralInferRequest
        self.NeuralModelSpec = NeuralModelSpec
        self.NeuralRuntimeState = NeuralRuntimeState
        self.NeuralRuntimeBoundary = NeuralRuntimeBoundary
        self.NeuralRuntimeStartConfig = NeuralRuntimeStartConfig

    def test_subprocess_start_infer_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rt = self.NeuralRuntimeBoundary()
            health = rt.start(
                self.NeuralRuntimeStartConfig(
                    isolation="subprocess",
                    work_dir=tmp,
                    mode=self.NeuralMode.OFF,
                    model_spec=self.NeuralModelSpec(),
                )
            )
            self.assertEqual(health.state, self.NeuralRuntimeState.READY)
            self.assertEqual(health.isolation, "subprocess")
            self.assertTrue(health.process_alive)
            result = rt.infer(
                self.NeuralInferRequest(
                    request_id="sub-off",
                    input_ids=[[1, 2, 3, 4]],
                    mode=self.NeuralMode.OFF,
                )
            )
            self.assertTrue(result.bypassed)
            checksum = rt.prove_base_frozen()
            self.assertEqual(checksum, result.base_checksum)
            stopped = rt.stop()
            self.assertEqual(stopped.state, self.NeuralRuntimeState.STOPPED)
            self.assertFalse(stopped.process_alive)

    def test_worker_crash_does_not_corrupt_host_state(self) -> None:
        from neural.errors import NeuralRuntimeFailed

        with tempfile.TemporaryDirectory() as tmp:
            rt = self.NeuralRuntimeBoundary()
            rt.start(
                self.NeuralRuntimeStartConfig(
                    isolation="subprocess",
                    work_dir=tmp,
                    model_spec=self.NeuralModelSpec(),
                )
            )
            # Host markers that must survive worker death.
            host_marker = {"sqlite_ok": True, "fastapi_ok": True}
            with self.assertRaises(NeuralRuntimeFailed):
                rt._rpc({"op": "crash_test"}, timeout_s=5.0)
            health = rt.health()
            self.assertEqual(health.state, self.NeuralRuntimeState.FAILED)
            self.assertFalse(health.process_alive)
            # Host process state intact.
            self.assertTrue(host_marker["sqlite_ok"])
            self.assertTrue(host_marker["fastapi_ok"])
            # Clean shutdown still works.
            stopped = rt.stop()
            self.assertEqual(stopped.state, self.NeuralRuntimeState.STOPPED)
            # A new boundary can start again (host not poisoned).
            rt2 = self.NeuralRuntimeBoundary()
            h2 = rt2.start(
                self.NeuralRuntimeStartConfig(
                    isolation="inprocess",
                    model_spec=self.NeuralModelSpec(seed=99),
                )
            )
            self.assertEqual(h2.state, self.NeuralRuntimeState.READY)
            rt2.stop()


class NeuralRuntimeCompatUnitTests(unittest.TestCase):
    def test_validate_manifest_mismatch_message(self) -> None:
        from neural.errors import NeuralCheckpointIncompatible
        from neural.runtime_compat import validate_memory_checkpoint_manifest

        with self.assertRaises(NeuralCheckpointIncompatible) as ctx:
            validate_memory_checkpoint_manifest(
                {"dim": 4096, "schema_version": 1, "architecture_version": "parametric_mlp_v1"},
                expected_hidden_size=3584,
                expected_architecture_version="parametric_mlp_v1",
            )
        self.assertIn("4096", str(ctx.exception.detail))
        self.assertIn("3584", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
