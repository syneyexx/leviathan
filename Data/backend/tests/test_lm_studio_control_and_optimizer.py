"""Unit tests: LM Studio load config compiler + per-device headroom + optimizer scoring."""

from __future__ import annotations

from dataclasses import replace

import pytest

from Data.modules.models.contracts import ComputeDevice, DeviceRole, LoadOptions
from Data.modules.models.lm_studio_control import (
    CapabilitySupport,
    LMStudioControlCapabilities,
    classify_lm_studio_error,
    compile_lm_studio_load,
    config_fingerprint,
    parse_lms_estimate_output,
)
from Data.modules.models.optimizer import (
    CandidateResult,
    OptimizationObjective,
    OptimizationStatus,
    generate_candidates,
    score_candidate,
)
from Data.modules.models.placement import PlacementPlanner, usable_capacity_for_device


def _caps(**overrides) -> LMStudioControlCapabilities:
    base = LMStudioControlCapabilities(
        native_rest=CapabilitySupport.SUPPORTED,
        load=CapabilitySupport.SUPPORTED,
        unload=CapabilitySupport.SUPPORTED,
        loaded_instances=CapabilitySupport.SUPPORTED,
        resource_estimate=CapabilitySupport.SUPPORTED,
        gpu_ratio=CapabilitySupport.SUPPORTED,
        gpu_split=CapabilitySupport.UNSUPPORTED,
        custom_gpu_split=CapabilitySupport.UNSUPPORTED,
        disabled_gpus=CapabilitySupport.UNSUPPORTED,
        main_gpu=CapabilitySupport.UNSUPPORTED,
        strict_vram_cap=CapabilitySupport.UNSUPPORTED,
        flash_attention=CapabilitySupport.SUPPORTED,
        kv_gpu_offload=CapabilitySupport.SUPPORTED,
        kv_quantization=CapabilitySupport.UNSUPPORTED,
        eval_batch=CapabilitySupport.SUPPORTED,
        moe_num_experts=CapabilitySupport.SUPPORTED,
        context_length=CapabilitySupport.SUPPORTED,
        echo_load_config=CapabilitySupport.SUPPORTED,
        seed=CapabilitySupport.UNSUPPORTED,
        cpu_threads=CapabilitySupport.UNSUPPORTED,
        cli_available=True,
        sdk_available=False,
        sdk_reachable=False,
        provider_version="0.4.25",
    )
    return replace(base, **overrides) if overrides else base


def test_compile_rest_load_fields():
    caps = _caps()
    opts = LoadOptions(
        context_length=8192,
        batch_size=256,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        num_experts=4,
    )
    compiled = compile_lm_studio_load("qwen/qwen2.5-14b", opts, caps)
    assert compiled.rest_body["model"] == "qwen/qwen2.5-14b"
    assert compiled.rest_body["context_length"] == 8192
    assert compiled.rest_body["eval_batch_size"] == 256
    assert compiled.rest_body["flash_attention"] is True
    assert compiled.rest_body["offload_kv_cache_to_gpu"] is True
    assert compiled.rest_body["num_experts"] == 4
    assert compiled.rest_body["echo_load_config"] is True
    assert compiled.transport == "rest"


def test_compile_gpu_ratio_uses_cli_when_available():
    caps = _caps(cli_available=True, gpu_ratio=CapabilitySupport.SUPPORTED)
    opts = LoadOptions(context_length=4096, gpu_offload_ratio=0.8)
    compiled = compile_lm_studio_load("model-a", opts, caps)
    assert compiled.transport == "cli"
    assert "--gpu" in compiled.cli_args
    assert "0.8" in compiled.cli_args


def test_compile_custom_gpu_split_deferred_unsupported():
    caps = _caps()
    opts = LoadOptions(tensor_split=(0.9, 0.65), gpu_split_mode="manual", allow_multi_gpu=True)
    compiled = compile_lm_studio_load("model-a", opts, caps)
    assert "gpuSplit" in compiled.deferred_unsupported


def test_compile_unsupported_seed_cpu_threads_without_sdk():
    caps = _caps()  # no sdk
    opts = LoadOptions(seed=42, cpu_threads=8)
    compiled = compile_lm_studio_load("model-a", opts, caps)
    assert "seed" in compiled.deferred_unsupported
    assert "cpuThreads" in compiled.deferred_unsupported
    assert "INFERENCE_ONLY" in compiled.deferred_unsupported["cpuThreads"]


def test_compile_seed_uses_sdk_when_reachable():
    caps = _caps(
        seed=CapabilitySupport.SUPPORTED,
        sdk_available=True,
        sdk_reachable=True,
        sdk_version="1.5.0",
    )
    opts = LoadOptions(seed=7, context_length=4096)
    compiled = compile_lm_studio_load("model-a", opts, caps)
    assert compiled.transport == "sdk"
    assert compiled.rest_body.get("_sdkConfig", {}).get("seed") == 7
    assert "seed" not in compiled.deferred_unsupported or "INFERENCE" not in compiled.deferred_unsupported.get(
        "seed", ""
    )


def test_capability_field_matrix_scopes():
    caps = _caps(sdk_available=True, sdk_reachable=True, seed=CapabilitySupport.SUPPORTED, cpu_threads=CapabilitySupport.SUPPORTED)
    matrix = {f.key: f for f in caps.field_matrix()}
    assert matrix["seed"].scope.value == "LOAD"
    assert matrix["cpuThreads"].scope.value == "INFERENCE"
    assert matrix["keepDisplayHeadroom"].scope.value == "PLACEMENT_POLICY"
    assert matrix["tensorSplit"].reason_code == "SDK_SPLIT_STRATEGY_ONLY"
    pub = caps.public_dict()
    assert "fields" in pub
    assert any(f["key"] == "seed" for f in pub["fields"])


def test_cpu_threads_never_enter_rest_body():
    caps = _caps(cpu_threads=CapabilitySupport.SUPPORTED, sdk_available=True, sdk_reachable=True)
    opts = LoadOptions(cpu_threads=8, context_length=2048)
    compiled = compile_lm_studio_load("model-a", opts, caps)
    assert "cpu_threads" not in compiled.rest_body
    assert "cpuThreads" not in compiled.rest_body
    assert "cpuThreads" in compiled.deferred_unsupported


def test_classify_oom_variants():
    assert classify_lm_studio_error("cudaMalloc failed: out of memory") == "LOAD_OOM_CUDA"
    assert classify_lm_studio_error("failed to allocate buffer for kv cache") == "LOAD_OOM_KV_CACHE"
    assert classify_lm_studio_error("connection refused") == "LM_STUDIO_OFFLINE"


def test_parse_lms_estimate_output():
    text = """Model: openai/gpt-oss-120b
Estimated GPU Memory:   65.68 GB
Estimated Total Memory: 65.68 GB
Estimate: This model may be loaded based on your resource guardrails settings.
"""
    parsed = parse_lms_estimate_output(text)
    assert parsed["model"] == "openai/gpt-oss-120b"
    assert parsed["estimatedGpuMemoryBytes"] == int(65.68 * 1024**3)
    assert parsed["provenance"] == "PROVIDER_ESTIMATE"


def test_per_device_headroom_priority():
    planner = PlacementPlanner(
        default_vram_headroom_bytes=512 * 1024**2,
        per_device_headroom_bytes={"gpu-a": 3 * 1024**3},
        role_headroom_bytes={"DISPLAY": 3 * 1024**3, "AUXILIARY": 512 * 1024**2},
    )
    display = ComputeDevice(
        stable_device_id="gpu-b",
        free_vram_bytes=int(13.8 * 1024**3),
        total_vram_bytes=16 * 1024**3,
        role=DeviceRole.DISPLAY,
    )
    aux = ComputeDevice(
        stable_device_id="gpu-a",
        free_vram_bytes=int(5.5 * 1024**3),
        total_vram_bytes=6 * 1024**3,
        role=DeviceRole.AUXILIARY,
    )
    # per-device wins for gpu-a
    assert planner.headroom_for_device(aux) == 3 * 1024**3
    # role default for display
    assert planner.headroom_for_device(display) == 3 * 1024**3

    usable_aux = usable_capacity_for_device(
        aux, headroom_bytes=planner.headroom_for_device(aux)
    )
    # free 5.5GB - 3GB headroom = 2.5GB (per-device override), NOT 5.0
    assert usable_aux.usable_bytes == int(5.5 * 1024**3) - 3 * 1024**3

    usable_disp = usable_capacity_for_device(
        display, headroom_bytes=planner.headroom_for_device(display)
    )
    assert usable_disp.usable_bytes == int(13.8 * 1024**3) - 3 * 1024**3
    assert usable_disp.usable_bytes <= int(10.8 * 1024**3) + 1024  # ~10.8GB


def test_aux_role_headroom_when_no_per_device():
    planner = PlacementPlanner(
        default_vram_headroom_bytes=512 * 1024**2,
        role_headroom_bytes={"AUXILIARY": 512 * 1024**2, "DISPLAY": 3 * 1024**3},
    )
    aux = ComputeDevice(
        stable_device_id="gpu-x",
        free_vram_bytes=int(5.5 * 1024**3),
        role=DeviceRole.AUXILIARY,
    )
    usable = usable_capacity_for_device(aux, headroom_bytes=planner.headroom_for_device(aux))
    assert usable.usable_bytes == int(5.5 * 1024**3) - 512 * 1024**2
    assert usable.usable_bytes <= 5 * 1024**3


def test_optimizer_candidates_bounded():
    base = LoadOptions(context_length=8192, gpu_offload_ratio=0.8, flash_attention=True)
    cands = generate_candidates(base, max_candidates=8, device_count=2)
    assert 4 <= len(cands) <= 8


def test_optimizer_score_excludes_unmeasured_as_winner_value():
    obj = OptimizationObjective()
    unmeas = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.UNMEASURED,
        generation_tps=None,
    )
    assert score_candidate(unmeas, obj) is None
    oom = CandidateResult(
        index=2,
        options=LoadOptions(),
        status=OptimizationStatus.OOM,
    )
    assert score_candidate(oom, obj) is not None and score_candidate(oom, obj) < 0
    good = CandidateResult(
        index=3,
        options=LoadOptions(),
        status=OptimizationStatus.PASS,
        generation_tps=28.0,
        prompt_tps=400.0,
        ttft_seconds=0.8,
    )
    assert score_candidate(good, obj) > 0


def test_config_fingerprint_changes_with_context():
    a = config_fingerprint(
        model_id="m1",
        quantization="Q4_K_M",
        provider_version="0.4.25",
        hardware_fingerprint="hw1",
        options=LoadOptions(context_length=8192),
    )
    b = config_fingerprint(
        model_id="m1",
        quantization="Q4_K_M",
        provider_version="0.4.25",
        hardware_fingerprint="hw1",
        options=LoadOptions(context_length=16384),
    )
    assert a != b
