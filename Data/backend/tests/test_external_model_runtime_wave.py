"""Architecture regression — model_runtime serving / diagnostics externalization wave."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.model_download.artifact_verify import (
    VerificationLevel,
    stream_hash_artifact,
    validate_gguf_header,
    validate_safetensors_header,
)
from Data.modules.model_runtime.env_policy import build_serving_child_env
from Data.modules.model_runtime.execution_gate import (
    allow_process_ownership,
    production_requires_external,
)
from Data.modules.model_runtime.facade import (
    CAP_BENCHMARK,
    CAP_INFERENCE_TEST,
    CAP_LOAD,
    CAP_PROBE,
    CAP_RECONCILE,
    CAP_UNLOAD,
)
from Data.modules.model_runtime.process_control import terminate_owned_process
from Data.modules.model_runtime.serving import (
    WorkerState,
    reset_serving_supervisor_for_tests,
)
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class ModelRuntimePoolRoutingTests(unittest.TestCase):
    def test_model_runtime_pool_is_singleton(self) -> None:
        self.assertIn("model_runtime", POOL_CATALOG)
        defn = POOL_CATALOG["model_runtime"]
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 1)
        self.assertIn("model_runtime.load", defn.job_kinds)

    def test_capabilities_route_to_model_runtime(self) -> None:
        for cap in (
            CAP_LOAD,
            CAP_UNLOAD,
            CAP_RECONCILE,
            CAP_BENCHMARK,
            CAP_PROBE,
            CAP_INFERENCE_TEST,
        ):
            self.assertEqual(pool_for_capability(cap), "model_runtime")
            self.assertNotEqual(pool_for_capability(cap), "general")
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)

    def test_model_download_not_absorbed(self) -> None:
        self.assertEqual(pool_for_capability("model_download.start"), "model_download")
        self.assertNotEqual(pool_for_capability("model_download.start"), "model_runtime")

    def test_capabilities_are_external_required(self) -> None:
        catalog = build_default_catalog()
        for cap in (CAP_LOAD, CAP_UNLOAD, CAP_RECONCILE, CAP_BENCHMARK, CAP_PROBE, CAP_INFERENCE_TEST):
            definition = catalog.get(cap)
            self.assertIsNotNone(definition, cap)
            assert definition is not None
            cls = classify_capability(cap, metadata=definition.metadata)
            self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED, cap)


class ProcessOwnershipGateTests(unittest.TestCase):
    def test_api_externalized_cannot_own_processes(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_MODEL_RUNTIME_ALLOW_INLINE_TEST": "0",
            },
            clear=False,
        ):
            with mock.patch(
                "Data.modules.model_runtime.execution_gate.pytest_session_active",
                return_value=False,
            ):
                with mock.patch(
                    "Data.modules.execution.workload.running_in_worker_process",
                    return_value=False,
                ):
                    self.assertTrue(production_requires_external())
                    self.assertFalse(allow_process_ownership())

    def test_model_runtime_worker_can_own_processes(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKER_ID": "model_runtime-1",
                "LEVIATHAN_WORKER_POOL": "model_runtime",
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
            },
            clear=False,
        ):
            self.assertTrue(allow_process_ownership())

    def test_embedding_worker_cannot_own_serving(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKER_ID": "embedding-1",
                "LEVIATHAN_WORKER_POOL": "embedding",
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
            },
            clear=False,
        ):
            self.assertFalse(allow_process_ownership())


class ServingSupervisorHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        registry = Path(self.tmp.name) / "serving_registry.json"
        self.supervisor = reset_serving_supervisor_for_tests(registry_path=registry)

    def test_api_spawn_refused_when_externalized(self) -> None:
        with mock.patch(
            "Data.modules.model_runtime.execution_gate.allow_process_ownership",
            return_value=False,
        ):
            with self.assertRaises(Exception) as ctx:
                self.supervisor.start_subprocess(
                    provider_id="p",
                    model_id="m",
                    backend_kind="llama_cpp",
                    command=["/bin/true"],
                    endpoint="http://127.0.0.1:9/v1",
                )
            self.assertIn("model_runtime", str(ctx.exception).lower())

    def test_missing_binary_unavailable(self) -> None:
        with mock.patch(
            "Data.modules.model_runtime.execution_gate.allow_process_ownership",
            return_value=True,
        ):
            worker = self.supervisor.start_subprocess(
                provider_id="p",
                model_id="m",
                backend_kind="llama_cpp",
                command=["/nonexistent/leviathan-llama-server-xyz"],
                endpoint="http://127.0.0.1:9/v1",
            )
        self.assertEqual(worker.state, WorkerState.UNAVAILABLE)
        self.assertNotEqual(worker.state, WorkerState.READY)

    def test_empty_command_unavailable_not_inproc_fallback(self) -> None:
        with mock.patch(
            "Data.modules.model_runtime.execution_gate.allow_process_ownership",
            return_value=True,
        ):
            worker = self.supervisor.start_subprocess(
                provider_id="p",
                model_id="m",
                backend_kind="llama_cpp",
                command=[],
                endpoint="http://127.0.0.1:9/v1",
            )
        self.assertEqual(worker.state, WorkerState.UNAVAILABLE)

    def test_stale_generation_unload_refused(self) -> None:
        with mock.patch(
            "Data.modules.model_runtime.execution_gate.allow_process_ownership",
            return_value=True,
        ):
            worker = self.supervisor.start_inproc(
                provider_id="p", model_id="m1", backend_kind="inproc"
            )
        gen = worker.serving_generation
        stopped = self.supervisor.stop(worker.worker_id, expected_generation=gen + 99)
        # Stale generation must not clear READY/inproc worker.
        self.assertIn("stale", (stopped.last_error or "").lower())
        still = self.supervisor.get_worker(worker.worker_id)
        assert still is not None
        self.assertEqual(still.state, WorkerState.READY)

    def test_operator_owned_not_killed(self) -> None:
        with mock.patch(
            "Data.modules.model_runtime.execution_gate.allow_process_ownership",
            return_value=True,
        ):
            worker = self.supervisor.start_inproc(
                provider_id="p", model_id="ext", backend_kind="inproc"
            )
        worker.managed_by_leviathan = False
        out = self.supervisor.stop(worker.worker_id)
        self.assertIn("refusing", (out.last_error or "").lower())
        self.assertEqual(out.state, WorkerState.READY)

    def test_env_policy_excludes_secrets(self) -> None:
        env = build_serving_child_env(
            {"CUDA_VISIBLE_DEVICES": "0"},
            base={
                "PATH": "/usr/bin",
                "OPENAI_API_KEY": "sk-secret",
                "CUDA_VISIBLE_DEVICES": "1",
                "HOME": "/home/u",
            },
        )
        self.assertIn("PATH", env)
        self.assertEqual(env.get("CUDA_VISIBLE_DEVICES"), "0")
        self.assertNotIn("OPENAI_API_KEY", env)


class ArtifactVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_streaming_hash_progress_and_digest(self) -> None:
        path = self.root / "model.bin"
        payload = b"abcdefgh" * 4096
        path.write_bytes(payload)
        events: list[dict] = []

        def progress(evt: dict) -> None:
            events.append(dict(evt))

        result = stream_hash_artifact(path, progress=progress)
        self.assertTrue(result["ok"])
        self.assertEqual(result["hash"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["level"], VerificationLevel.HASH_VERIFIED.value)
        self.assertTrue(any(e.get("phase") == "hashing" for e in events))
        self.assertTrue(result["truth"]["streaming_hash"])

    def test_hash_cancel(self) -> None:
        path = self.root / "big.bin"
        path.write_bytes(os.urandom(256 * 1024))
        calls = {"n": 0}

        def cancel() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        with self.assertRaises(Exception):
            stream_hash_artifact(path, cancel_check=cancel, chunk_size=1024)

    def test_hash_mutation_rejected(self) -> None:
        path = self.root / "mut.bin"
        path.write_bytes(b"x" * 64 * 1024)
        mutated = {"done": False}

        def progress(evt: dict) -> None:
            if not mutated["done"] and int(evt.get("bytes_hashed") or 0) >= 4096:
                # Change size so identity before/after diverges.
                path.write_bytes(b"y" * 8)
                mutated["done"] = True

        result = stream_hash_artifact(path, progress=progress, chunk_size=1024)
        self.assertTrue(mutated["done"])
        self.assertTrue(
            result.get("artifactChanged") or result.get("status") == "CHANGED_DURING_READ"
        )
        self.assertFalse(result["ok"])

    def test_gguf_valid_and_invalid_magic(self) -> None:
        good = self.root / "ok.gguf"
        # magic + version + tensor_count + metadata_kv_count
        good.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 1, 0) + b"\x00" * 32)
        bad = self.root / "bad.gguf"
        bad.write_bytes(b"XXXX" + b"\x00" * 40)
        self.assertTrue(validate_gguf_header(good)["ok"])
        self.assertFalse(validate_gguf_header(bad)["ok"])
        self.assertEqual(validate_gguf_header(bad).get("error"), "invalid_magic")

    def test_safetensors_header(self) -> None:
        path = self.root / "m.safetensors"
        header = json.dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}})
        raw = header.encode("utf-8")
        path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\x00\x00\x00\x00")
        self.assertTrue(validate_safetensors_header(path)["ok"])
        truncated = self.root / "trunc.safetensors"
        truncated.write_bytes(struct.pack("<Q", 1000) + b"{}")
        self.assertFalse(validate_safetensors_header(truncated)["ok"])


class ArchitectureSourceGuards(unittest.TestCase):
    def test_routes_do_not_call_process_next(self) -> None:
        from Data.backend.routes import models as models_routes

        source = inspect.getsource(models_routes)
        self.assertNotIn("process_next(", source)

    def test_control_plane_load_enqueues_when_external(self) -> None:
        from Data.modules.models.control_plane import ModelControlPlane

        source = inspect.getsource(ModelControlPlane.load_model)
        self.assertIn("submit_load", source)
        self.assertIn("_externalize_runtime", source)

    def test_no_model_runtime_db(self) -> None:
        root = Path("Data/modules")
        offenders = list(root.rglob("model_runtime.db")) + list(root.rglob("model_servers.db"))
        self.assertEqual(offenders, [])


class WindowsProcessControlUnitTests(unittest.TestCase):
    def test_terminate_already_exited(self) -> None:
        class _Proc:
            returncode = 0

            def poll(self):
                return 0

        result = terminate_owned_process(_Proc())  # type: ignore[arg-type]
        self.assertTrue(result["alreadyExited"])
        self.assertFalse(result["forced"])


if __name__ == "__main__":
    unittest.main()
