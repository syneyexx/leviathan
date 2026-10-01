"""Production regressions: ModelLoadOptimizer identity, cancel, gates, candidates."""

from __future__ import annotations

import asyncio
import threading
import uuid

import pytest

from Data.modules.models.contracts import LoadOptions
from Data.modules.models.optimizer import (
    CandidateResult,
    ModelLoadOptimizer,
    OptimizationObjective,
    OptimizationRun,
    OptimizationStatus,
    generate_candidates,
    passes_mandatory_gates,
    score_candidate,
)


def test_exactly_one_run_id_register_and_run() -> None:
    opt = ModelLoadOptimizer()
    run_id = str(uuid.uuid4())
    pending = OptimizationRun(
        run_id=run_id,
        model_id="m1",
        status=OptimizationStatus.PENDING,
        hardware_fingerprint="hw-abc",
    )
    registered = opt.register_run(pending)

    async def _load(mid: str, opts: LoadOptions) -> dict:
        return {"loadTimeSeconds": 0.1}

    async def _unload(mid: str) -> dict:
        return {}

    async def _bench(mid: str) -> dict:
        return {"metrics": {"generationTps": 20.0, "promptTps": 100.0, "ttftSeconds": 0.2}}

    async def _go() -> OptimizationRun:
        return await opt.run(
            model_id="m1",
            base_options=LoadOptions(context_length=4096, flash_attention=True),
            run_id=run_id,
            hardware_fingerprint="hw-abc",
            max_candidates=4,
            deadline_seconds=30.0,
            load_fn=_load,
            unload_fn=_unload,
            benchmark_fn=_bench,
        )

    finished = asyncio.run(_go())
    assert finished is registered
    assert finished.run_id == run_id
    assert opt.get(run_id) is finished
    assert finished.hardware_fingerprint == "hw-abc"
    assert "hardwareFingerprint" in finished.public_dict()


def test_cancel_real_run_stays_cancelled_no_late_best() -> None:
    opt = ModelLoadOptimizer()
    run_id = str(uuid.uuid4())
    opt.register_run(
        OptimizationRun(run_id=run_id, model_id="m1", status=OptimizationStatus.PENDING)
    )

    gate = threading.Event()
    entered = threading.Event()

    async def _load(mid: str, opts: LoadOptions) -> dict:
        entered.set()
        # Block until cancel path releases us.
        while not gate.is_set():
            await asyncio.sleep(0.01)
        return {"loadTimeSeconds": 0.01}

    async def _unload(mid: str) -> dict:
        return {}

    async def _bench(mid: str) -> dict:
        return {"metrics": {"generationTps": 99.0}}

    async def _scenario() -> OptimizationRun:
        task = asyncio.create_task(
            opt.run(
                model_id="m1",
                base_options=LoadOptions(context_length=2048),
                run_id=run_id,
                hardware_fingerprint="hw-cancel",
                max_candidates=4,
                deadline_seconds=60.0,
                op_timeout_seconds=30.0,
                load_fn=_load,
                unload_fn=_unload,
                benchmark_fn=_bench,
            )
        )
        # Wait until load is blocked.
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set(), "load never entered"
        cancelled = opt.cancel(run_id)
        assert cancelled is not None
        assert cancelled.cancel_requested is True
        gate.set()
        return await task

    finished = asyncio.run(_scenario())
    assert finished.run_id == run_id
    assert finished.status == OptimizationStatus.CANCELLED
    assert finished.best_index is None
    assert all(c.status != OptimizationStatus.BEST for c in finished.candidates)


def test_generate_candidates_varies_flash_kv_batch_preserves_base() -> None:
    base = LoadOptions(
        context_length=8192,
        gpu_offload_ratio=0.8,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        batch_size=256,
        num_experts=4,
        keep_display_headroom=True,
        seed=42,
    )
    cands = generate_candidates(base, max_candidates=8)
    assert 4 <= len(cands) <= 8
    flashes = {c.flash_attention for c in cands}
    kvs = {c.offload_kv_cache_to_gpu for c in cands}
    batches = {c.batch_size for c in cands}
    assert False in flashes and True in flashes
    assert False in kvs and True in kvs
    assert len(batches) >= 2
    # Base options preserved via replace — unrelated fields stay.
    for c in cands:
        assert c.num_experts == 4
        assert c.seed == 42


def test_headroom_violation_never_best_or_pass_winner() -> None:
    obj = OptimizationObjective(keep_display_responsive=True)
    result = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.HEADROOM_VIOLATION,
        generation_tps=50.0,
    )
    assert passes_mandatory_gates(result, obj) is False
    assert score_candidate(result, obj) is None

    # Even when display headroom objective is off, HEADROOM is never BEST-green.
    obj2 = OptimizationObjective(keep_display_responsive=False)
    assert passes_mandatory_gates(result, obj2) is False


def test_oom_never_best() -> None:
    obj = OptimizationObjective()
    result = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.OOM,
        generation_tps=40.0,
    )
    assert passes_mandatory_gates(result, obj) is False
    assert score_candidate(result, obj) is None


def test_unstable_never_best() -> None:
    obj = OptimizationObjective()
    result = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.UNSTABLE,
        generation_tps=40.0,
    )
    assert passes_mandatory_gates(result, obj) is False
    assert score_candidate(result, obj) is None


def test_missing_generation_tps_with_max_tokens_not_best() -> None:
    obj = OptimizationObjective(max_tokens_per_sec=True)
    result = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.PASS,
        generation_tps=None,
        prompt_tps=200.0,
        ttft_seconds=0.5,
    )
    assert passes_mandatory_gates(result, obj) is False


def test_passes_mandatory_gates_unit() -> None:
    obj = OptimizationObjective()
    good = CandidateResult(
        index=1,
        options=LoadOptions(),
        status=OptimizationStatus.PASS,
        generation_tps=22.0,
    )
    assert passes_mandatory_gates(good, obj) is True

    for status in (
        OptimizationStatus.OOM,
        OptimizationStatus.UNSTABLE,
        OptimizationStatus.LOAD_FAILED,
        OptimizationStatus.CANCELLED,
        OptimizationStatus.SKIPPED,
        OptimizationStatus.UNMEASURED,
        OptimizationStatus.TIMEOUT,
        OptimizationStatus.PENDING,
        OptimizationStatus.RUNNING,
        OptimizationStatus.HEADROOM_VIOLATION,
    ):
        bad = CandidateResult(index=2, options=LoadOptions(), status=status, generation_tps=99.0)
        assert passes_mandatory_gates(bad, obj) is False, status


def test_hardware_fingerprint_on_run_public_dict() -> None:
    run = OptimizationRun(
        run_id="r1",
        model_id="m1",
        hardware_fingerprint="deadbeef",
    )
    pub = run.public_dict()
    assert pub["hardwareFingerprint"] == "deadbeef"
    assert hasattr(run, "hardware_fingerprint")


@pytest.mark.asyncio
async def test_headroom_and_oom_not_crowned_in_live_run() -> None:
    opt = ModelLoadOptimizer()
    calls = {"n": 0}

    async def _load(mid: str, opts: LoadOptions) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            from Data.modules.models.errors import ModelControlError

            raise ModelControlError(code="LOAD_OOM_CUDA", message="oom")
        return {"loadTimeSeconds": 0.05}

    async def _unload(mid: str) -> dict:
        return {}

    async def _bench(mid: str) -> dict:
        return {"metrics": {"generationTps": 30.0}}

    async def _headroom() -> bool:
        return False  # always violate after successful loads

    run = await opt.run(
        model_id="m1",
        base_options=LoadOptions(context_length=4096, flash_attention=True, batch_size=256),
        hardware_fingerprint="hw-live",
        max_candidates=4,
        deadline_seconds=30.0,
        load_fn=_load,
        unload_fn=_unload,
        benchmark_fn=_bench,
        headroom_check_fn=_headroom,
    )
    assert run.hardware_fingerprint == "hw-live"
    assert run.status != OptimizationStatus.BEST or all(
        c.status != OptimizationStatus.OOM and c.status != OptimizationStatus.HEADROOM_VIOLATION
        for c in run.candidates
        if c.index == run.best_index
    )
    # No OOM/HEADROOM candidate may be crowned BEST.
    for c in run.candidates:
        if c.status in {OptimizationStatus.OOM, OptimizationStatus.HEADROOM_VIOLATION}:
            assert c.status != OptimizationStatus.BEST
            assert c.score is None
    assert run.status in {
        OptimizationStatus.UNMEASURED,
        OptimizationStatus.BEST,
        OptimizationStatus.PASS,
    }
    if run.status == OptimizationStatus.BEST:
        winner = next(c for c in run.candidates if c.index == run.best_index)
        assert winner.status == OptimizationStatus.BEST
        assert winner.generation_tps is not None
