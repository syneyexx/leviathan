"""Durable training system tests — capabilities, preflight, fixture lifecycle."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.modules.common.corpus import build_corpus_layout
from Data.modules.common.secrets import redact_secrets
from Data.modules.training import (
    DurableTrainingStatus,
    PreferenceBridge,
    TrainingConfig,
    TrainingRecipeRegistry,
    TrainingRegistry,
    TrainingService,
    TrainingStore,
    probe_training_capabilities,
)
from Data.modules.training.types import PreflightVerdict


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
    service.reconcile()
    return service, tmp_path


def test_capabilities_do_not_crash_without_torch() -> None:
    caps = probe_training_capabilities()
    assert caps.can_run_fixture is True
    names = {p.name for p in caps.packages}
    assert "torch" in names
    assert "transformers" in names
    assert "peft" in names
    # Without ML deps, LoRA is unavailable — honest.
    if not any(p.name == "torch" and p.available for p in caps.packages):
        assert caps.can_run_lora is False
        assert "torch" in caps.missing_for_lora


def test_hardware_no_fake_gpu(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    hw = service.hardware()
    assert hw["truth"]["no_fabricated_gpu_telemetry"] is True
    # Must not invent utilization / temperature figures.
    for gpu in hw["gpus"]:
        assert "utilization" not in gpu
        assert "temperature" not in gpu
    if not hw["cudaAvailable"] and len(hw["gpus"]) == 0:
        assert hw["truth"]["gpu_absent_when_unmeasured"] is True


def test_preflight_blocks_missing_packages_for_lora(training_env: tuple[TrainingService, Path]) -> None:
    service, tmp_path = training_env
    caps = probe_training_capabilities()
    payload = {
        "name": "blocked-lora",
        "method": "lora",
        "base_model_ref": "sshleifer/tiny-gpt2",
        "dataset_path": str(tmp_path / "missing.jsonl"),
        "epochs": 1,
    }
    result = service.preflight(payload)
    if not caps.can_run_lora:
        assert result["verdict"] == PreflightVerdict.BLOCKED.value
        codes = {i["code"] for i in result["issues"]}
        assert "missing_packages" in codes or "dataset_path_missing" in codes
    else:
        # Environment has packages — dataset path still missing → blocked.
        assert result["verdict"] == PreflightVerdict.BLOCKED.value


def test_preflight_fixture_passes(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    result = service.preflight(
        {
            "name": "fix",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 3,
            "fixture_sleep_ms": 10,
        }
    )
    assert result["verdict"] in {PreflightVerdict.PASS.value, PreflightVerdict.WARNING.value}
    assert result["verdict"] != PreflightVerdict.BLOCKED.value


def test_fixture_worker_lifecycle(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    job = service.create_job(
        {
            "name": "fixture-run",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 4,
            "fixture_sleep_ms": 20,
            "seed": 7,
        }
    )
    assert job.status == DurableTrainingStatus.QUEUED
    started = service.start_job(job.job_id)
    assert started.worker_pid is not None
    finished = service.wait_until_terminal(job.job_id, timeout=30.0)
    assert finished.status == DurableTrainingStatus.COMPLETED
    assert finished.artifact_id is not None
    metrics = service.metrics(job.job_id)
    assert any(m["metricName"] == "train_loss" for m in metrics)
    assert all(m.get("metadata", {}).get("fixture") or m["metricName"] for m in metrics)
    checkpoints = service.checkpoints(job.job_id)
    assert len(checkpoints) >= 1
    evaluation = service.evaluate(job.job_id)
    assert evaluation["truth"]["fixture"] is True
    exported = service.export(job.job_id)
    assert Path(exported["exportPath"]).exists()


def test_cancel_fixture_job(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    job = service.create_job(
        {
            "name": "cancel-me",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 200,
            "fixture_sleep_ms": 100,
        },
        auto_start=True,
    )
    # Wait until running
    deadline = time.time() + 10
    while time.time() < deadline:
        current = service.get_job(job.job_id)
        assert current is not None
        if current.status == DurableTrainingStatus.RUNNING and current.worker_pid:
            break
        time.sleep(0.05)
    cancelled = service.cancel_job(job.job_id, wait_seconds=15.0)
    assert cancelled.status in {
        DurableTrainingStatus.CANCELLED,
        DurableTrainingStatus.CANCELLING,
    }
    # Allow cooperative finalize
    terminal = service.wait_until_terminal(job.job_id, timeout=20.0)
    assert terminal.status == DurableTrainingStatus.CANCELLED


def test_interrupt_reconcile(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    job = service.create_job(
        {
            "name": "kill-me",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 500,
            "fixture_sleep_ms": 200,
        },
        auto_start=True,
    )
    deadline = time.time() + 10
    pid = None
    while time.time() < deadline:
        current = service.get_job(job.job_id)
        assert current is not None
        if current.worker_pid and current.status == DurableTrainingStatus.RUNNING:
            pid = current.worker_pid
            break
        time.sleep(0.05)
    assert pid is not None
    os.kill(pid, signal.SIGKILL)
    # Reap zombie so liveness probes settle; then reconcile.
    deadline = time.time() + 5
    while time.time() < deadline:
        proc = service._processes.get(job.job_id)
        if proc is not None:
            proc.poll()
        from Data.modules.common.process import pid_is_alive

        if not pid_is_alive(pid):
            break
        time.sleep(0.05)
    results = service.reconcile()
    assert any(r["jobId"] == job.job_id for r in results)
    updated = service.get_job(job.job_id)
    assert updated is not None
    assert updated.status == DurableTrainingStatus.INTERRUPTED
    assert updated.status != DurableTrainingStatus.RUNNING


def test_secret_redaction_in_config_and_logs(training_env: tuple[TrainingService, Path]) -> None:
    service, _ = training_env
    secret = "hf_abcdefghijklmnopqrstuvwxyz012345"
    job = service.create_job(
        {
            "name": "secret-job",
            "method": "fixture",
            "base_model_ref": "fixture-base",
            "fixture_steps": 2,
            "fixture_sleep_ms": 10,
            "extra": {"authorization": f"Bearer {secret}", "api_key": secret},
        }
    )
    cfg_blob = str(job.config)
    assert secret not in cfg_blob
    assert "[REDACTED]" in cfg_blob or "api_key" in cfg_blob
    # Redaction helper itself
    assert secret not in redact_secrets(f"token={secret}")
    finished = service.start_job(job.job_id)
    finished = service.wait_until_terminal(finished.job_id, timeout=20.0)
    logs = service.logs(finished.job_id)
    assert secret not in logs["text"]


def test_preference_bridge_and_recipes_still_work() -> None:
    registry = TrainingRegistry()
    recipes = TrainingRecipeRegistry()
    assert recipes.get("pref_dpo_v1") is not None
    bridge = PreferenceBridge(registry)
    jobs = bridge.register_from_verification_reports(
        [{"report_id": "r1", "outcome": "PASSED"}],
        recipe_id="pref_dpo_v1",
    )
    assert len(jobs) == 1
    assert jobs[0].status.value == "REGISTERED"


def test_imports_survive_missing_ml_stack() -> None:
    # Importing the package must succeed even when torch/peft absent.
    import Data.modules.training as training_pkg
    import Data.modules.training.worker.trainer_loop as loop
    import Data.modules.training.worker.entry as entry

    assert training_pkg.TrainingService is not None
    assert loop.run_fixture_loop is not None
    assert entry.build_parser() is not None


def test_config_hash_stable() -> None:
    a = TrainingConfig(name="x", method="fixture", base_model_ref="b", seed=1)
    b = TrainingConfig(name="x", method="fixture", base_model_ref="b", seed=1)
    assert a.config_hash() == b.config_hash()


def test_sync_registers_trained_artifact(tmp_path: Path) -> None:
    import hashlib

    from Data.modules.models.store import ModelStore
    from Data.modules.training.model_registration import sync_completed_artifacts_to_models

    db = tmp_path / "reg.db"
    MigrationRunner(db).apply_all()
    ts = TrainingStore(db)
    ms = ModelStore(db)
    job = ts.create_job(name="j", method="fixture", base_model_ref="tiny", seed=1, config={})
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    cfg = adapter / "adapter_config.json"
    cfg.write_text('{"method":"fixture"}', encoding="utf-8")
    digest = hashlib.sha256(cfg.read_bytes()).hexdigest()
    art = ts.add_artifact(
        job_id=job.job_id,
        artifact_type="fixture_adapter",
        path=str(adapter),
        method="fixture",
        base_model_ref="tiny",
        content_hash=digest,
        config_hash=job.config_hash,
        compatibility={"inference_ready": False},
    )
    ts.update_job(job.job_id, status=DurableTrainingStatus.COMPLETED, artifact_id=art.artifact_id)
    synced = sync_completed_artifacts_to_models(model_store=ms, training_store=ts)
    assert len(synced) == 1
    assert synced[0]["integrity"] == "passed"
    assert synced[0]["modelId"].startswith("trained:")
    row = ms.get_model(synced[0]["modelId"])
    assert row is not None
    assert row["source"] == "trained"
    assert sync_completed_artifacts_to_models(model_store=ms, training_store=ts) == []
