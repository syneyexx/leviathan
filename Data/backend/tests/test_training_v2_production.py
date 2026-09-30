"""Training V2 production honesty — capabilities, devices, planner, preflight, service."""

from __future__ import annotations

from pathlib import Path

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.common.corpus import build_corpus_layout
from Data.modules.training import TrainingConfig, TrainingService, TrainingStore, probe_training_capabilities
from Data.modules.training.collators import MaskedCausalLMCollator, char_mask_to_token_labels
from Data.modules.training.device_resolve import build_device_env, select_training_device
from Data.modules.training.hardware import stable_device_id_for
from Data.modules.training.model_source import is_gguf_ref
from Data.modules.training.planner import plan_training
from Data.modules.training.preflight import run_preflight
from Data.modules.training.types import (
    DurableTrainingStatus,
    GpuDeviceInfo,
    HardwareSnapshot,
    MethodSupport,
    MethodSupportStatus,
    PackageAvailability,
    TrainingCapabilities,
)


def _gpu(index: int, *, free_gib: float, total_gib: float, uuid: str, name: str = "GPU") -> GpuDeviceInfo:
    return GpuDeviceInfo(
        index=index,
        name=name,
        total_vram_bytes=int(total_gib * 1024**3),
        free_vram_bytes=int(free_gib * 1024**3),
        used_vram_bytes=int((total_gib - free_gib) * 1024**3),
        stable_device_id=f"gpu-uuid-{uuid}",
        uuid=uuid,
        compute_capability="8.0",
        probe_source="nvidia-smi",
    )


def _hw(gpus: tuple[GpuDeviceInfo, ...], *, cuda: bool = True) -> HardwareSnapshot:
    return HardwareSnapshot(
        cpu_model="test-cpu",
        logical_cores=8,
        physical_cores=4,
        ram_total_bytes=64 * 1024**3,
        ram_available_bytes=48 * 1024**3,
        disk_free_bytes=200 * 1024**3,
        gpus=gpus,
        cuda_available=cuda,
        cuda_runtime_version=None,
        torch_cuda_version="12.1",
        driver_version="550",
        supports_fp16=True,
        supports_bf16=True,
        supports_4bit=True,
    )


def _caps_all_supported() -> TrainingCapabilities:
    support = {
        m: MethodSupport(method=m, status=MethodSupportStatus.SUPPORTED, requires=())
        for m in ("sft", "lora", "qlora", "dpo")
    }
    return TrainingCapabilities(
        packages=(PackageAvailability(name="torch", available=True, version="2.0"),),
        can_run_fixture=True,
        can_run_lora=True,
        can_run_qlora=True,
        can_run_dpo=True,
        ready=True,
        missing_for_lora=(),
        can_run_sft=True,
        can_run_dpo_micro=True,
        can_use_flash_attention=False,
        can_use_8bit_optimizer=False,
        cuda_available=True,
        method_support=support,
        dpo_hf_status=MethodSupportStatus.SUPPORTED.value,
    )


@pytest.fixture()
def training_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TrainingService, Path]:
    db_path = tmp_path / "leviathan.db"
    corpus_root = tmp_path / "corpus"
    monkeypatch.setenv("LEVIATHAN_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LEVIATHAN_CORPUS_ROOT", str(corpus_root))
    monkeypatch.setenv("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
    settings = Settings.from_env()
    MigrationRunner(settings.database_path).apply_all()
    corpus = build_corpus_layout(settings)
    service = TrainingService(settings, store=TrainingStore(settings.database_path), corpus=corpus)
    return service, tmp_path


def test_ready_false_when_only_fixture_available() -> None:
    caps = probe_training_capabilities(
        package_probe=lambda name: PackageAvailability(name=name, available=False, import_error="missing"),
        cuda_available=False,
    )
    assert caps.can_run_fixture is True
    assert caps.can_run_dpo_micro is True
    assert caps.can_run_dpo is False
    assert caps.ready is False
    assert caps.method_support["dpo"].status == MethodSupportStatus.DEPENDENCY_MISSING
    names = {p.name for p in caps.packages}
    assert "trl" in names
    assert "flash_attn" in names
    pub = caps.public_dict()
    assert pub["ready"] is False
    assert pub["canRunDpoMicro"] is True
    assert pub["canRunDpo"] is False
    assert pub["truth"]["fixture_is_not_production_ready"] is True


def test_config_backward_compatible_from_dict() -> None:
    cfg = TrainingConfig.from_dict(
        {
            "name": "legacy",
            "method": "lora",
            "base_model_ref": "org/m",
            "dataset_path": "/tmp/d.jsonl",
            "unknown_future_knob": 123,
        }
    )
    assert cfg.apply_planner_suggestions is False
    assert cfg.device_strategy == "auto"
    assert cfg.selected_stable_device_ids == []
    assert cfg.optimizer == "adamw_torch"
    assert cfg.dpo_beta == 0.1
    assert cfg.extra.get("unknown_future_knob") == 123
    assert cfg.validate() == []


def test_stable_device_id_and_public_dict() -> None:
    sid = stable_device_id_for(uuid="GPU-XYZ", pci_bus_id=None, ordinal=0, name="A100")
    assert sid == "gpu-uuid-GPU-XYZ"
    gpu = _gpu(0, free_gib=10, total_gib=24, uuid="GPU-XYZ", name="A100")
    assert gpu.public_dict()["stableDeviceId"] == "gpu-uuid-GPU-XYZ"


def test_device_resolve_uses_selected_not_first() -> None:
    hw = _hw((_gpu(0, free_gib=1, total_gib=8, uuid="A"), _gpu(1, free_gib=20, total_gib=24, uuid="B")))
    cfg = TrainingConfig(
        name="t",
        method="lora",
        base_model_ref="/m",
        dataset_path="/d",
        selected_stable_device_ids=["gpu-uuid-B"],
    )
    sel = select_training_device(cfg, hw)
    assert sel.ok and sel.device is not None
    assert sel.device.index == 1
    env = build_device_env(sel)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


def test_device_resolve_auto_picks_highest_free_vram() -> None:
    hw = _hw((_gpu(0, free_gib=2, total_gib=8, uuid="A"), _gpu(1, free_gib=18, total_gib=24, uuid="B")))
    cfg = TrainingConfig(name="t", method="lora", base_model_ref="/m", dataset_path="/d")
    sel = select_training_device(cfg, hw)
    assert sel.device is not None and sel.device.index == 1
    assert sel.auto_selected is True


def test_device_resolve_rejects_multi_gpu() -> None:
    hw = _hw((_gpu(0, free_gib=8, total_gib=8, uuid="A"), _gpu(1, free_gib=8, total_gib=8, uuid="B")))
    cfg = TrainingConfig(
        name="t",
        method="lora",
        base_model_ref="/m",
        dataset_path="/d",
        selected_stable_device_ids=["gpu-uuid-A", "gpu-uuid-B"],
    )
    sel = select_training_device(cfg, hw)
    assert not sel.ok
    assert any("multi-GPU" in e for e in sel.errors)


def test_planner_reports_requested_suggested_effective_without_silent_apply() -> None:
    hw = _hw((_gpu(0, free_gib=1, total_gib=8, uuid="A"), _gpu(1, free_gib=22, total_gib=24, uuid="B")))
    cfg = TrainingConfig(
        name="t",
        method="lora",
        base_model_ref="/m",
        dataset_path="/d",
        selected_stable_device_ids=["gpu-uuid-B"],
        train_batch_size=8,
        apply_planner_suggestions=False,
    )
    plan = plan_training(cfg, hw, _caps_all_supported())
    assert plan.selected_device is not None
    assert plan.selected_device["ordinal"] == 1
    assert plan.requested_config["train_batch_size"] == 8
    assert plan.suggestions_applied is False
    # Effective mirrors requested when suggestions are not accepted.
    assert plan.effective_config["train_batch_size"] == 8
    pub = plan.public_dict()
    assert pub["truth"]["planner_never_silently_mutates_config"] is True
    assert pub["truth"]["multi_gpu_not_implemented"] is True


def test_preflight_blocks_gguf_and_validates_flash_attn() -> None:
    hw = _hw((_gpu(0, free_gib=20, total_gib=24, uuid="A"),))
    caps = _caps_all_supported()
    gguf = run_preflight(
        TrainingConfig(name="t", method="lora", base_model_ref="weights.gguf", dataset_path="/missing.jsonl"),
        hardware=hw,
        capabilities=caps,
    )
    assert gguf.verdict.value == "BLOCKED"
    assert any(i.code == "gguf_not_trainable" for i in gguf.issues)
    assert is_gguf_ref("weights.gguf")

    flash = run_preflight(
        TrainingConfig(
            name="t",
            method="lora",
            base_model_ref="/local/model",
            dataset_path="/missing.jsonl",
            flash_attention=True,
        ),
        hardware=hw,
        capabilities=caps,
    )
    assert any(i.code == "flash_attention_unavailable" for i in flash.issues)


def test_preflight_allows_durable_dpo_when_deps_ok(tmp_path: Path) -> None:
    hw = _hw((_gpu(0, free_gib=20, total_gib=24, uuid="A"),))
    caps = _caps_all_supported()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{"model_type":"llama","hidden_size":64,"num_hidden_layers":2,"vocab_size":100,"num_attention_heads":4}', encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"fake")
    ds = tmp_path / "prefs.jsonl"
    ds.write_text(
        '{"prompt":"p","chosen":"good","rejected":"bad"}\n'
        '{"prompt":"p2","chosen":"good2","rejected":"bad2"}\n',
        encoding="utf-8",
    )
    result = run_preflight(
        TrainingConfig(name="dpo", method="dpo", base_model_ref=str(model_dir), dataset_path=str(ds)),
        hardware=hw,
        capabilities=caps,
    )
    assert not any(i.code == "dpo_not_durable_lora" for i in result.issues)
    assert not any(i.code == "dpo_dependencies_missing" for i in result.issues)


def test_create_job_does_not_silently_apply_planner(training_env: tuple[TrainingService, Path]) -> None:
    service, tmp_path = training_env
    job = service.create_job(
        {
            "name": "no-silent",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 2,
            "train_batch_size": 7,
            "apply_planner_suggestions": False,
        }
    )
    assert job.config.get("train_batch_size") == 7
    assert job.planner.get("suggestionsApplied") is False
    assert job.planner.get("requestedConfig", {}).get("train_batch_size") == 7


def test_fixture_lifecycle_still_green(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    job = service.create_job(
        {
            "name": "fixture-v2",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 3,
            "fixture_sleep_ms": 5,
        },
        auto_start=True,
    )
    final = service.wait_until_terminal(job.job_id, timeout=30)
    assert final.status == DurableTrainingStatus.COMPLETED
    assert final.artifact_id


def test_launcher_accepts_cuda_visible_devices(tmp_path: Path) -> None:
    from Data.modules.training.launcher import TrainingLauncher

    launcher = TrainingLauncher()
    env = launcher.build_child_env(cuda_visible_devices="1", extra_env={"LEVIATHAN_TRAINING_FIXTURE": "1"})
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    assert env["LEVIATHAN_TRAINING_FIXTURE"] == "1"


def test_collator_masks_and_counts_tokens() -> None:
    labels = char_mask_to_token_labels(
        [1, 2, 3, 4],
        [(0, 1), (1, 2), (2, 3), (3, 4)],
        [0, 0, 1, 1],
        [1, 1, 1, 1],
    )
    assert labels == [-100, -100, 3, 4]
    collator = MaskedCausalLMCollator(pad_token_id=0)
    padded = collator.pad(
        [
            {"input_ids": [1, 2], "attention_mask": [1, 1], "labels": [1, 2]},
            {"input_ids": [3], "attention_mask": [1], "labels": [3]},
        ]
    )
    assert padded["input_ids"][1] == [3, 0]
    assert padded["labels"][1] == [3, -100]
    assert collator.tokens_seen == 3


def test_spawn_refuses_cancelling_job(training_env: tuple[TrainingService, Path]) -> None:
    from Data.modules.training.service import TrainingError

    service, _ = training_env
    job = service.create_job(
        {
            "name": "cancel-spawn",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 2,
        }
    )
    service.store.update_job(job.job_id, cancel_requested=True, status=DurableTrainingStatus.CANCELLING)
    with pytest.raises(TrainingError) as exc:
        service._spawn_owned(
            job.job_id,
            config=TrainingConfig.from_dict(job.config),
            output_dir=Path(job.output_dir or "."),
            log_path=Path(job.log_path or (Path(".") / "w.log")),
            events_path=Path(".") / "e.jsonl",
            preflight={},
        )
    assert exc.value.http_status == 409
    assert exc.value.details.get("code") == "TRAINING_SPAWN_REFUSED_CANCEL"


def test_resume_verifies_checkpoint(training_env: tuple[TrainingService, Path], tmp_path: Path) -> None:
    from Data.modules.training.service import TrainingError

    service, _ = training_env
    job = service.create_job(
        {
            "name": "resume-bad",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 2,
        }
    )
    bad = tmp_path / "checkpoint-empty"
    bad.mkdir()
    service.store.update_job(
        job.job_id,
        status=DurableTrainingStatus.INTERRUPTED,
        checkpoint={"path": str(bad), "step": 1},
    )
    with pytest.raises(TrainingError) as exc:
        service.resume_job(job.job_id)
    assert exc.value.details.get("code") in {
        "TRAINING_CHECKPOINT_INCOMPLETE",
        "RESUME_CHECKPOINT_INVALID",
        "TRAINING_CHECKPOINT_INVALID",
    }
