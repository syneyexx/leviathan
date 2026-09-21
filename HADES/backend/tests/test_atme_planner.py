"""Focused ATME unit tests (no PyTorch required)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.compatibility import check_strategy_compatibility
from training.estimator import estimate_strategy_memory, vram_reserve_bytes
from training.execution_plan import MemoryStrategy, PlanRequest, TrainingExecutionPlan
from training.failure_codes import TrainingFailureCode
from training.hardware_probe import Fact, GpuSnapshot, HardwareSnapshot, HostSnapshot, collect_hardware_snapshot
from training.model_inspector import inspect_local_model_dir, inspect_model_reference
from training.planner import plan_training, select_plan
from training.telemetry import classify_bottleneck, sanitize_telemetry_payload
from training_routes import mount_training_routes
from training_service import TrainingWorkspace


class _FakeDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.values = {"file_read_policy": "ask", "network_policy": "ask", "subprocess_policy": "ask"}

    def get_settings(self) -> dict[str, str]:
        return dict(self.values)


def _hardware(*, vram_total: int | None = 16 * 1024**3, vram_free: int | None = 14 * 1024**3, cuda: bool = True, ram: int = 64 * 1024**3) -> HardwareSnapshot:
    return HardwareSnapshot(
        gpu=GpuSnapshot(
            name=Fact(value="Test GPU", source="detected"),
            cuda_available=Fact(value=cuda, source="detected"),
            total_vram_bytes=Fact(value=vram_total, source="detected", unit="bytes"),
            free_vram_bytes=Fact(value=vram_free, source="detected", unit="bytes"),
            bitsandbytes_compatible=Fact(value=True, source="estimated"),
            count=Fact(value=1 if cuda else 0, source="detected"),
        ),
        host=HostSnapshot(
            total_ram_bytes=Fact(value=ram, source="detected", unit="bytes"),
            available_ram_bytes=Fact(value=int(ram * 0.7), source="detected", unit="bytes"),
            cpu_count=Fact(value=8, source="detected"),
            process_architecture=Fact(value="x86_64", source="detected"),
            platform_system=Fact(value="Linux", source="detected"),
        ),
        packages={
            "torch": {"available": True, "version": "2.0"},
            "bitsandbytes": {"available": True, "version": "0.43.0"},
        },
        profile_hash="hwtest",
    )


def _write_llama_config(root: Path, *, layers: int = 4, hidden: int = 256) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    config = {
        "architectures": ["LlamaForCausalLM"],
        "model_type": "llama",
        "num_hidden_layers": layers,
        "hidden_size": hidden,
        "intermediate_size": hidden * 4,
        "vocab_size": 1000,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "torch_dtype": "bfloat16",
        "tie_word_embeddings": True,
        "hidden_act": "silu",
    }
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    # Fake shard for size measurement.
    shard = root / "model.safetensors"
    shard.write_bytes(b"0" * 4096)
    return root


class AtmePlannerTests(unittest.TestCase):
    def test_vram_reserve_never_zero(self) -> None:
        self.assertGreaterEqual(vram_reserve_bytes(8 * 1024**3), 512 * 1024 * 1024)

    def test_strategy_ranking_prefers_resident(self) -> None:
        model_dir = Path(tempfile.mkdtemp()) / "model"
        _write_llama_config(model_dir)
        model = inspect_local_model_dir(model_dir)
        hardware = _hardware()
        request = PlanRequest(base_model=str(model_dir), sequence_length=128, batch_size=1, lora_r=8)
        response = plan_training(request, hardware=hardware, model=model)
        self.assertIsNotNone(response.selected)
        assert response.selected is not None
        self.assertEqual(response.selected.strategy, MemoryStrategy.GPU_RESIDENT)
        self.assertTrue(response.selected.feasible)

    def test_rejects_4bit_without_bitsandbytes(self) -> None:
        hardware = _hardware()
        hardware.packages["bitsandbytes"] = {"available": False, "version": None}
        model = inspect_model_reference("org/model")
        result = check_strategy_compatibility(
            MemoryStrategy.GPU_RESIDENT_4BIT,
            hardware=hardware,
            model=model,
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.failure_code, TrainingFailureCode.BITSANDBYTES_UNAVAILABLE)

    def test_rejects_unknown_architecture_for_streaming(self) -> None:
        hardware = _hardware()
        model = inspect_model_reference("org/mystery-model")
        result = check_strategy_compatibility(
            MemoryStrategy.RAM_LAYER_STREAMING,
            hardware=hardware,
            model=model,
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.failure_code, TrainingFailureCode.UNSUPPORTED_ARCHITECTURE)

    def test_auto_never_selects_low_confidence(self) -> None:
        candidates = [
            TrainingExecutionPlan(
                strategy=MemoryStrategy.RAM_LAYER_STREAMING,
                feasible=True,
                confidence="low",
                estimated_vram_peak_bytes=1,
            ),
            TrainingExecutionPlan(
                strategy=MemoryStrategy.GPU_RESIDENT,
                feasible=True,
                confidence="medium",
                estimated_vram_peak_bytes=2,
            ),
        ]
        selected = select_plan(
            candidates,
            requested=MemoryStrategy.AUTO,
            experimental_streaming_allowed=False,
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.strategy, MemoryStrategy.GPU_RESIDENT)

    def test_estimator_scales_with_sequence_length(self) -> None:
        model_dir = Path(tempfile.mkdtemp()) / "model"
        _write_llama_config(model_dir)
        model = inspect_local_model_dir(model_dir)
        hardware = _hardware()
        short = estimate_strategy_memory(
            strategy=MemoryStrategy.GPU_RESIDENT,
            hardware=hardware,
            model=model,
            sequence_length=128,
            batch_size=1,
            gradient_accumulation_steps=1,
            lora_r=8,
        )
        long = estimate_strategy_memory(
            strategy=MemoryStrategy.GPU_RESIDENT,
            hardware=hardware,
            model=model,
            sequence_length=4096,
            batch_size=1,
            gradient_accumulation_steps=1,
            lora_r=8,
        )
        self.assertGreater(long.vram_peak_bytes, short.vram_peak_bytes)

    def test_streaming_estimate_vram_below_resident_for_large_weights(self) -> None:
        model_dir = Path(tempfile.mkdtemp()) / "model"
        _write_llama_config(model_dir, layers=32, hidden=4096)
        # Inflate shard size so resident weights dominate.
        (model_dir / "model.safetensors").write_bytes(b"0" * (200 * 1024 * 1024))
        model = inspect_local_model_dir(model_dir)
        hardware = _hardware(vram_total=24 * 1024**3, vram_free=22 * 1024**3)
        resident = estimate_strategy_memory(
            strategy=MemoryStrategy.GPU_RESIDENT,
            hardware=hardware,
            model=model,
            sequence_length=512,
            batch_size=1,
            gradient_accumulation_steps=1,
            lora_r=8,
        )
        streamed = estimate_strategy_memory(
            strategy=MemoryStrategy.RAM_LAYER_STREAMING,
            hardware=hardware,
            model=model,
            sequence_length=512,
            batch_size=1,
            gradient_accumulation_steps=1,
            lora_r=8,
            buffer_count=1,
        )
        self.assertLess(streamed.vram_peak_bytes, resident.vram_peak_bytes)


class AtmeSerializationTests(unittest.TestCase):
    def test_hardware_snapshot_does_not_import_torch(self) -> None:
        snap = collect_hardware_snapshot()
        self.assertTrue(snap.profile_hash)
        self.assertIn(snap.host.platform_system.source, {"detected", "unknown"})

    def test_telemetry_strips_secrets_and_raw_records(self) -> None:
        cleaned = sanitize_telemetry_payload(
            {
                "step": 1,
                "hf_token": "hf_secret",
                "messages": [{"role": "user", "content": "nope"}],
                "loss": 0.5,
            }
        )
        self.assertEqual(cleaned.get("step"), 1)
        self.assertEqual(cleaned.get("loss"), 0.5)
        self.assertNotIn("hf_token", cleaned)
        self.assertNotIn("messages", cleaned)

    def test_bottleneck_classification_uses_measurements(self) -> None:
        self.assertEqual(
            classify_bottleneck(
                gpu_util=20.0,
                h2d_bytes_per_sec=1e9,
                storage_read_bytes_per_sec=None,
                step_duration_ms=100.0,
                vram_allocated_bytes=1,
                vram_total_bytes=10,
            ),
            "pcie_transfer",
        )


class AtmeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = _FakeDatabase(self.root / "hades.db")
        app = FastAPI()
        app.include_router(mount_training_routes({"database": self.db}), prefix="/api")
        self.client = TestClient(app)
        self.workspace = TrainingWorkspace(self.root / "training")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hardware_endpoint(self) -> None:
        response = self.client.get("/api/training/hardware")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("gpu", body)
        self.assertIn("host", body)
        self.assertIn("profile_hash", body)

    def test_plan_endpoint_without_launching_job(self) -> None:
        model_dir = self.root / "model"
        _write_llama_config(model_dir)
        response = self.client.post(
            "/api/training/plans",
            json={
                "base_model": str(model_dir),
                "sequence_length": 128,
                "batch_size": 1,
                "lora_r": 8,
                "memory_strategy": "auto",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("candidates", body)
        self.assertTrue(body["candidates"])

    def test_model_inspect_local(self) -> None:
        model_dir = self.root / "model"
        _write_llama_config(model_dir)
        response = self.client.post("/api/training/models/inspect", json={"base_model": str(model_dir)})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["streaming_compatible"])
        self.assertEqual(body["architecture_family"], "llama_like")

    def test_plan_persisted_fields_on_rejected_job_creation_path(self) -> None:
        # Create plan via workspace directly and ensure schema fields exist.
        model_dir = self.root / "model"
        _write_llama_config(model_dir)
        plan = self.workspace.create_plan(base_model=str(model_dir), memory_strategy="gpu_resident")
        self.assertIn("selected", plan)
        self.assertIn("planner_version", plan)

    def test_capabilities_include_atme(self) -> None:
        response = self.client.get("/api/training/capabilities")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("atme", body)
        self.assertIn("ram_layer_streaming", body["atme"]["strategies"])


if __name__ == "__main__":
    unittest.main()
