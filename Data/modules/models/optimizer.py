"""Bounded deterministic model load-profile optimizer.

Searches a small candidate set, measures real load/benchmark outcomes, and
selects the best profile by explicit weighted objectives. No LLM scoring.

Lifecycle invariants:
  - Exactly one OptimizationRun identity from start → terminal
  - cancel_requested on that object stops the real loop
  - Terminal CANCELLED is never overwritten by late PASS/BEST
  - Per-model lock serializes concurrent optimizer lifecycle ops
  - Each estimate/preflight/load/warmup/benchmark/unload is bounded
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Awaitable, Callable

from Data.modules.models.contracts import LoadOptions
from Data.modules.models.errors import ModelControlError
from Data.modules.models.lm_studio_control import config_fingerprint


class OptimizationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    BEST = "BEST"
    OOM = "OOM"
    LOAD_FAILED = "LOAD_FAILED"
    HEADROOM_VIOLATION = "HEADROOM_VIOLATION"
    UNSTABLE = "UNSTABLE"
    CANCELLED = "CANCELLED"
    UNMEASURED = "UNMEASURED"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"


# Statuses that may never become BEST / run PASS when objectives require safety.
_NEVER_WINNER = frozenset(
    {
        OptimizationStatus.OOM,
        OptimizationStatus.UNSTABLE,
        OptimizationStatus.LOAD_FAILED,
        OptimizationStatus.CANCELLED,
        OptimizationStatus.SKIPPED,
        OptimizationStatus.UNMEASURED,
        OptimizationStatus.TIMEOUT,
        OptimizationStatus.PENDING,
        OptimizationStatus.RUNNING,
    }
)


@dataclass
class OptimizationObjective:
    max_tokens_per_sec: bool = True
    keep_display_responsive: bool = True
    maximize_model_size: bool = False
    stable_no_oom: bool = True

    weight_gen_tps: float = 1.0
    weight_prompt_tps: float = 0.35
    weight_ttft: float = 0.25
    weight_headroom_violation: float = 5.0
    weight_oom: float = 10.0
    weight_unstable: float = 4.0
    weight_completeness: float = 0.5

    def public_dict(self) -> dict[str, Any]:
        return {
            "maxTokensPerSec": self.max_tokens_per_sec,
            "keepDisplayResponsive": self.keep_display_responsive,
            "maximizeModelSize": self.maximize_model_size,
            "stableNoOom": self.stable_no_oom,
            "weights": {
                "generationTps": self.weight_gen_tps,
                "promptTps": self.weight_prompt_tps,
                "ttft": self.weight_ttft,
                "headroomViolation": self.weight_headroom_violation,
                "oom": self.weight_oom,
                "unstable": self.weight_unstable,
                "completeness": self.weight_completeness,
            },
        }


@dataclass
class CandidateResult:
    index: int
    options: LoadOptions
    status: OptimizationStatus
    score: float | None = None
    context_length: int | None = None
    gpu_offload_ratio: float | None = None
    gpu0_ratio: float | None = None
    gpu1_ratio: float | None = None
    generation_tps: float | None = None
    prompt_tps: float | None = None
    ttft_seconds: float | None = None
    load_time_seconds: float | None = None
    peak_vram_bytes: int | None = None
    error: str | None = None
    fingerprint: str | None = None
    applied_config: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    estimate_disagreement: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "status": self.status.value,
            "score": self.score,
            "context": self.context_length,
            "gpuOffload": self.gpu_offload_ratio,
            "gpu0": self.gpu0_ratio,
            "gpu1": self.gpu1_ratio,
            "generationTps": self.generation_tps,
            "promptTps": self.prompt_tps,
            "ttftSeconds": self.ttft_seconds,
            "loadTimeSeconds": self.load_time_seconds,
            "peakVramBytes": self.peak_vram_bytes,
            "error": self.error,
            "fingerprint": self.fingerprint,
            "appliedConfig": self.applied_config,
            "warnings": list(self.warnings),
            "estimateDisagreement": self.estimate_disagreement,
            "options": self.options.as_provider_payload(
                [
                    "contextLength",
                    "batchSize",
                    "flashAttention",
                    "offloadKvCacheToGpu",
                    "gpuOffloadRatio",
                    "gpuSplitMode",
                    "tensorSplit",
                    "numExperts",
                    "keepDisplayHeadroom",
                    "kvCacheDtype",
                ]
            ),
        }


@dataclass
class OptimizationRun:
    run_id: str
    model_id: str
    status: OptimizationStatus = OptimizationStatus.PENDING
    objectives: OptimizationObjective = field(default_factory=OptimizationObjective)
    candidates: list[CandidateResult] = field(default_factory=list)
    best_index: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    error: str | None = None
    max_candidates: int = 8
    deadline_seconds: float = 900.0
    hardware_fingerprint: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "modelId": self.model_id,
            "status": self.status.value,
            "objectives": self.objectives.public_dict(),
            "candidates": [c.public_dict() for c in self.candidates],
            "bestIndex": self.best_index,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "cancelRequested": self.cancel_requested,
            "error": self.error,
            "maxCandidates": self.max_candidates,
            "deadlineSeconds": self.deadline_seconds,
            "hardwareFingerprint": self.hardware_fingerprint,
        }

    def is_terminal(self) -> bool:
        return self.status in {
            OptimizationStatus.BEST,
            OptimizationStatus.PASS,
            OptimizationStatus.CANCELLED,
            OptimizationStatus.UNMEASURED,
            OptimizationStatus.TIMEOUT,
        }


def generate_candidates(
    base: LoadOptions,
    *,
    max_candidates: int = 8,
    device_count: int = 1,
    supported_controls: set[str] | None = None,
) -> list[LoadOptions]:
    """Bounded deterministic search that actually varies supported axes.

    Uses dataclasses.replace so unrelated base settings are preserved.
    Only varies controls listed in ``supported_controls`` when provided.
    """
    max_candidates = max(4, min(12, int(max_candidates)))
    supported = supported_controls or {
        "contextLength",
        "batchSize",
        "flashAttention",
        "offloadKvCacheToGpu",
        "gpuOffloadRatio",
        "gpuSplitMode",
        "kvCacheDtype",
    }

    contexts: list[int] = []
    base_ctx = base.context_length or 8192
    if "contextLength" in supported:
        for c in (base_ctx, max(2048, base_ctx // 2), min(base_ctx * 2, 32768), 4096):
            if int(c) not in contexts:
                contexts.append(int(c))
    else:
        contexts = [int(base_ctx)]

    ratios: list[float] = []
    base_ratio = base.gpu_offload_ratio if base.gpu_offload_ratio is not None else 0.8
    if "gpuOffloadRatio" in supported:
        for r in (base_ratio, min(1.0, base_ratio + 0.1), max(0.4, base_ratio - 0.15), 1.0, 0.6):
            rr = round(float(r), 3)
            if rr not in ratios:
                ratios.append(rr)
    else:
        ratios = [round(float(base_ratio), 3)]

    if "flashAttention" in supported:
        flash_opts = [
            base.flash_attention if base.flash_attention is not None else True,
            False,
        ]
    else:
        flash_opts = [base.flash_attention]

    if "offloadKvCacheToGpu" in supported:
        kv_opts = [
            base.offload_kv_cache_to_gpu if base.offload_kv_cache_to_gpu is not None else True,
            False,
        ]
    else:
        kv_opts = [base.offload_kv_cache_to_gpu]

    if "batchSize" in supported:
        raw_batches = [base.batch_size or 256, 128, 512]
        batches: list[int | None] = []
        for b in raw_batches:
            if b not in batches:
                batches.append(b)
    else:
        batches = [base.batch_size]

    kv_dtypes: list[str | None] = [base.kv_cache_dtype]
    if "kvCacheDtype" in supported and base.kv_cache_dtype:
        # Keep base dtype only — do not invent unsupported dtypes.
        kv_dtypes = [base.kv_cache_dtype]

    seen: set[tuple] = set()
    out: list[LoadOptions] = []

    # Coarse grid: vary all supported axes without combinatorial explosion by
    # walking a deterministic diagonal + a few axis sweeps.
    def _append(opts: LoadOptions) -> bool:
        key = (
            opts.context_length,
            opts.gpu_offload_ratio,
            opts.flash_attention,
            opts.offload_kv_cache_to_gpu,
            opts.batch_size,
            opts.kv_cache_dtype,
            opts.gpu_split_mode,
        )
        if key in seen:
            return False
        seen.add(key)
        out.append(opts)
        return len(out) >= max_candidates

    # Reserve slots so flash/kv/batch and the safer profile actually appear.
    # Pass 1 alone (context × ratio) must not exhaust the entire budget.
    axis_reserve = 0
    if len(flash_opts) > 1 or len(kv_opts) > 1 or len(batches) > 1:
        axis_reserve += min(4, max_candidates // 2)
    if "flashAttention" in supported:
        axis_reserve = min(max_candidates - 1, max(axis_reserve, 1) + 1)
    pass1_limit = max(1, max_candidates - axis_reserve)

    # Pass 1: context × ratio with base flash/kv/batch
    for ctx in contexts:
        for ratio in ratios:
            if len(out) >= pass1_limit:
                break
            opts = replace(
                base,
                context_length=ctx,
                gpu_offload_ratio=ratio,
                batch_size=batches[0],
                flash_attention=flash_opts[0],
                offload_kv_cache_to_gpu=kv_opts[0],
                keep_display_headroom=(
                    base.keep_display_headroom
                    if base.keep_display_headroom is not None
                    else True
                ),
            )
            if device_count >= 2 and base.allow_multi_gpu and "gpuSplitMode" in supported:
                opts = replace(opts, gpu_split_mode=base.gpu_split_mode or "auto")
            if _append(opts):
                break
        if len(out) >= pass1_limit:
            break

    # Pass 2: ensure flash / kv / batch actually vary (single-axis first),
    # then fill remaining combinations. Nested flash×kv×batch alone can
    # exhaust the budget before False-flash is reached.
    base_ctx0 = contexts[0]
    base_ratio0 = ratios[0]

    def _axis_opts(*, flash=None, kv=None, batch=None) -> LoadOptions:
        return replace(
            base,
            context_length=base_ctx0,
            gpu_offload_ratio=base_ratio0,
            flash_attention=flash_opts[0] if flash is None else flash,
            offload_kv_cache_to_gpu=kv_opts[0] if kv is None else kv,
            batch_size=batches[0] if batch is None else batch,
            keep_display_headroom=(
                base.keep_display_headroom
                if base.keep_display_headroom is not None
                else True
            ),
        )

    # Single-axis flips from the base profile
    if len(flash_opts) > 1:
        if _append(_axis_opts(flash=flash_opts[1])):
            return out
    if len(kv_opts) > 1:
        if _append(_axis_opts(kv=kv_opts[1])):
            return out
    for batch in batches[1:]:
        if _append(_axis_opts(batch=batch)):
            return out

    # Remaining combinations
    for flash in flash_opts:
        for kv in kv_opts:
            for batch in batches:
                if _append(_axis_opts(flash=flash, kv=kv, batch=batch)):
                    return out

    # Pass 3: explicit no-flash safer profile (comment must match config)
    if len(out) < max_candidates and "flashAttention" in supported:
        safer = replace(
            base,
            context_length=max(2048, (base.context_length or 8192) // 2),
            batch_size=128 if "batchSize" in supported else base.batch_size,
            flash_attention=False,
            offload_kv_cache_to_gpu=(
                True if "offloadKvCacheToGpu" in supported else base.offload_kv_cache_to_gpu
            ),
            gpu_offload_ratio=max(0.5, (base.gpu_offload_ratio or 0.8) - 0.2),
            keep_display_headroom=True,
        )
        _append(safer)

    return out[:max_candidates]


def passes_mandatory_gates(
    result: CandidateResult, objectives: OptimizationObjective
) -> bool:
    """Safety/correctness gates before scoring. Scoring never overrules these."""
    if result.status in _NEVER_WINNER:
        return False
    if objectives.stable_no_oom and result.status == OptimizationStatus.OOM:
        return False
    if objectives.keep_display_responsive and result.status == OptimizationStatus.HEADROOM_VIOLATION:
        return False
    if objectives.max_tokens_per_sec and result.generation_tps is None:
        # Latency-only is NOT a full PASS for maxTokensPerSec objective.
        return False
    if result.status == OptimizationStatus.HEADROOM_VIOLATION:
        # Even if keep_display_responsive is False, HEADROOM is never BEST-green.
        # It may still be scored only when display headroom is not required —
        # but never as production BEST. Gate keeps it out of BEST selection.
        return False
    if result.status not in {OptimizationStatus.PASS, OptimizationStatus.BEST}:
        return False
    return True


def score_candidate(result: CandidateResult, objectives: OptimizationObjective) -> float | None:
    """Deterministic score. Higher is better. Only called for gate-passing candidates."""
    if result.status in {OptimizationStatus.CANCELLED, OptimizationStatus.SKIPPED}:
        return None
    if result.status == OptimizationStatus.UNMEASURED:
        return None
    if result.status == OptimizationStatus.OOM:
        return None  # never score OOM into winners
    if result.status == OptimizationStatus.UNSTABLE:
        return None
    if result.status == OptimizationStatus.LOAD_FAILED:
        return None
    if result.status == OptimizationStatus.HEADROOM_VIOLATION:
        return None  # never green

    score = 0.0
    if objectives.max_tokens_per_sec and result.generation_tps is not None:
        score += objectives.weight_gen_tps * float(result.generation_tps)
    if result.prompt_tps is not None:
        score += objectives.weight_prompt_tps * float(result.prompt_tps)
    if result.ttft_seconds is not None and result.ttft_seconds > 0:
        score += objectives.weight_ttft * (1.0 / float(result.ttft_seconds))
    if objectives.stable_no_oom and result.status == OptimizationStatus.PASS:
        score += 5.0
    if objectives.maximize_model_size and result.gpu_offload_ratio is not None:
        score += objectives.weight_completeness * float(result.gpu_offload_ratio) * 10.0
    return score


class ModelLoadOptimizer:
    """In-process optimizer orchestrator. Long work driven from control plane / model_runtime."""

    def __init__(self) -> None:
        self._runs: dict[str, OptimizationRun] = {}
        self._lock = asyncio.Lock()
        self._model_locks: dict[str, asyncio.Lock] = {}

    def _model_lock(self, model_id: str) -> asyncio.Lock:
        lock = self._model_locks.get(model_id)
        if lock is None:
            lock = asyncio.Lock()
            self._model_locks[model_id] = lock
        return lock

    def get(self, run_id: str) -> OptimizationRun | None:
        return self._runs.get(run_id)

    def list_for_model(self, model_id: str) -> list[OptimizationRun]:
        return [r for r in self._runs.values() if r.model_id == model_id]

    def register_run(self, run: OptimizationRun) -> OptimizationRun:
        """Register a pre-created run so start→terminal shares one identity."""
        self._runs[run.run_id] = run
        return run

    def cancel(self, run_id: str) -> OptimizationRun | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.cancel_requested = True
        if run.status in {OptimizationStatus.RUNNING, OptimizationStatus.PENDING}:
            run.status = OptimizationStatus.CANCELLED
            if run.finished_at is None:
                run.finished_at = time.time()
        return run

    def _still_active(self, run: OptimizationRun) -> bool:
        if run.cancel_requested:
            return False
        if run.status == OptimizationStatus.CANCELLED:
            return False
        return True

    async def _bounded(
        self,
        run: OptimizationRun,
        coro: Awaitable[Any],
        *,
        timeout: float,
        label: str,
    ) -> Any:
        if not self._still_active(run):
            raise asyncio.CancelledError(f"optimization cancelled before {label}")
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{label} timed out after {timeout}s") from exc

    async def run(
        self,
        *,
        model_id: str,
        base_options: LoadOptions,
        objectives: OptimizationObjective | None = None,
        max_candidates: int = 8,
        deadline_seconds: float = 900.0,
        device_count: int = 1,
        provider_version: str | None = None,
        hardware_fingerprint: str | None = None,
        quantization: str | None = None,
        run_id: str | None = None,
        supported_controls: set[str] | None = None,
        op_timeout_seconds: float = 180.0,
        load_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]],
        unload_fn: Callable[[str], Awaitable[dict[str, Any]]],
        benchmark_fn: Callable[[str], Awaitable[dict[str, Any]]],
        preflight_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None = None,
        estimate_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None = None,
        headroom_check_fn: Callable[[], Awaitable[bool]] | None = None,
    ) -> OptimizationRun:
        async with self._model_lock(model_id):
            return await self._run_locked(
                model_id=model_id,
                base_options=base_options,
                objectives=objectives,
                max_candidates=max_candidates,
                deadline_seconds=deadline_seconds,
                device_count=device_count,
                provider_version=provider_version,
                hardware_fingerprint=hardware_fingerprint,
                quantization=quantization,
                run_id=run_id,
                supported_controls=supported_controls,
                op_timeout_seconds=op_timeout_seconds,
                load_fn=load_fn,
                unload_fn=unload_fn,
                benchmark_fn=benchmark_fn,
                preflight_fn=preflight_fn,
                estimate_fn=estimate_fn,
                headroom_check_fn=headroom_check_fn,
            )

    async def _run_locked(
        self,
        *,
        model_id: str,
        base_options: LoadOptions,
        objectives: OptimizationObjective | None,
        max_candidates: int,
        deadline_seconds: float,
        device_count: int,
        provider_version: str | None,
        hardware_fingerprint: str | None,
        quantization: str | None,
        run_id: str | None,
        supported_controls: set[str] | None,
        op_timeout_seconds: float,
        load_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]],
        unload_fn: Callable[[str], Awaitable[dict[str, Any]]],
        benchmark_fn: Callable[[str], Awaitable[dict[str, Any]]],
        preflight_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None,
        estimate_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None,
        headroom_check_fn: Callable[[], Awaitable[bool]] | None,
    ) -> OptimizationRun:
        # Reuse pre-registered run when run_id provided — never allocate a second identity.
        if run_id and run_id in self._runs:
            run = self._runs[run_id]
            if run.cancel_requested or run.status == OptimizationStatus.CANCELLED:
                run.status = OptimizationStatus.CANCELLED
                run.finished_at = run.finished_at or time.time()
                return run
            run.status = OptimizationStatus.RUNNING
            run.started_at = run.started_at or time.time()
            run.objectives = objectives or run.objectives or OptimizationObjective()
            run.max_candidates = max_candidates
            run.deadline_seconds = deadline_seconds
            run.hardware_fingerprint = hardware_fingerprint
        else:
            run = OptimizationRun(
                run_id=run_id or str(uuid.uuid4()),
                model_id=model_id,
                objectives=objectives or OptimizationObjective(),
                max_candidates=max_candidates,
                deadline_seconds=deadline_seconds,
                status=OptimizationStatus.RUNNING,
                started_at=time.time(),
                hardware_fingerprint=hardware_fingerprint,
            )
            self._runs[run.run_id] = run

        candidates = generate_candidates(
            base_options,
            max_candidates=max_candidates,
            device_count=device_count,
            supported_controls=supported_controls,
        )
        deadline = (run.started_at or time.time()) + deadline_seconds
        loaded = False

        try:
            for idx, opts in enumerate(candidates):
                if not self._still_active(run) or time.time() > deadline:
                    run.candidates.append(
                        CandidateResult(
                            index=idx + 1,
                            options=opts,
                            status=OptimizationStatus.CANCELLED
                            if run.cancel_requested
                            else OptimizationStatus.TIMEOUT,
                            context_length=opts.context_length,
                            gpu_offload_ratio=opts.gpu_offload_ratio,
                        )
                    )
                    if run.cancel_requested:
                        run.status = OptimizationStatus.CANCELLED
                    else:
                        run.status = OptimizationStatus.TIMEOUT
                        run.error = "optimization deadline exceeded"
                    break

                remaining = max(1.0, deadline - time.time())
                op_budget = min(op_timeout_seconds, remaining)

                fp = config_fingerprint(
                    model_id=model_id,
                    quantization=quantization,
                    provider_version=provider_version,
                    hardware_fingerprint=hardware_fingerprint,
                    options=opts,
                )
                result = CandidateResult(
                    index=idx + 1,
                    options=opts,
                    status=OptimizationStatus.PENDING,
                    context_length=opts.context_length,
                    gpu_offload_ratio=opts.gpu_offload_ratio,
                    gpu0_ratio=(opts.tensor_split[0] if opts.tensor_split else None),
                    gpu1_ratio=(
                        opts.tensor_split[1]
                        if opts.tensor_split and len(opts.tensor_split) > 1
                        else None
                    ),
                    fingerprint=fp,
                )

                # Preflight
                if preflight_fn is not None and self._still_active(run):
                    try:
                        pre = await self._bounded(
                            run, preflight_fn(model_id, opts), timeout=op_budget, label="preflight"
                        )
                        verdict = _extract_preflight_verdict(pre)
                        if verdict == "LIKELY_OOM":
                            result.status = OptimizationStatus.OOM
                            result.error = "preflight LIKELY_OOM"
                            run.candidates.append(result)
                            continue
                        if not bool(pre.get("feasible", True)) and verdict in {
                            "LIKELY_OOM",
                            "INSUFFICIENT_MEMORY",
                            "INSUFFICIENT_VRAM",
                        }:
                            result.status = OptimizationStatus.OOM
                            result.error = f"preflight not feasible: {verdict}"
                            run.candidates.append(result)
                            continue
                    except TimeoutError:
                        result.status = OptimizationStatus.TIMEOUT
                        result.error = "preflight timeout"
                        run.candidates.append(result)
                        continue
                    except ModelControlError as exc:
                        if "OOM" in (exc.code or "") or "MEMORY" in (exc.code or "") or "VRAM" in (
                            exc.code or ""
                        ):
                            result.status = OptimizationStatus.OOM
                            result.error = exc.message
                            run.candidates.append(result)
                            continue
                    except asyncio.CancelledError:
                        run.status = OptimizationStatus.CANCELLED
                        break

                # Provider / Leviathan estimate (advisory but disagreement is preserved)
                if estimate_fn is not None and self._still_active(run):
                    try:
                        est = await self._bounded(
                            run, estimate_fn(model_id, opts), timeout=op_budget, label="estimate"
                        )
                        if isinstance(est, dict):
                            if est.get("disagreeMaterially"):
                                result.estimate_disagreement = True
                                result.warnings.append(
                                    "estimate disagreement >25% — conservative OOM policy"
                                )
                            status = str(est.get("status") or "").upper()
                            if status in {"UNMEASURED", "UNAVAILABLE"}:
                                result.warnings.append(f"estimate status={status}")
                            # Conservative: material disagreement + likely high VRAM → skip as OOM-risk
                            if (
                                result.estimate_disagreement
                                and run.objectives.stable_no_oom
                                and str(est.get("conservativeVerdict") or "").upper() == "LIKELY_OOM"
                            ):
                                result.status = OptimizationStatus.OOM
                                result.error = "conservative estimate LIKELY_OOM under disagreement"
                                run.candidates.append(result)
                                continue
                    except TimeoutError:
                        result.warnings.append("estimate timeout")
                    except Exception as exc:  # noqa: BLE001
                        result.warnings.append(f"provider estimate unavailable: {exc}")

                if not self._still_active(run):
                    result.status = OptimizationStatus.CANCELLED
                    run.candidates.append(result)
                    run.status = OptimizationStatus.CANCELLED
                    break

                # Load
                try:
                    load_result = await self._bounded(
                        run, load_fn(model_id, opts), timeout=op_budget, label="load"
                    )
                    loaded = True
                    if not self._still_active(run):
                        try:
                            await unload_fn(model_id)
                        except Exception:  # noqa: BLE001
                            pass
                        loaded = False
                        result.status = OptimizationStatus.CANCELLED
                        run.candidates.append(result)
                        run.status = OptimizationStatus.CANCELLED
                        break
                    result.load_time_seconds = load_result.get("loadTimeSeconds") or (
                        load_result.get("receipt") or {}
                    ).get("loadTimeSeconds")
                    result.applied_config = load_result.get("appliedConfig") or (
                        load_result.get("receipt") or {}
                    ).get("appliedConfig")
                except TimeoutError:
                    result.status = OptimizationStatus.TIMEOUT
                    result.error = "load timeout"
                    run.candidates.append(result)
                    loaded = False
                    continue
                except ModelControlError as exc:
                    code = exc.code or ""
                    if "OOM" in code or "MEMORY" in code or "VRAM" in code:
                        result.status = OptimizationStatus.OOM
                    else:
                        result.status = OptimizationStatus.LOAD_FAILED
                    result.error = exc.message
                    run.candidates.append(result)
                    loaded = False
                    continue
                except asyncio.CancelledError:
                    if loaded:
                        try:
                            await unload_fn(model_id)
                        except Exception:  # noqa: BLE001
                            pass
                        loaded = False
                    run.status = OptimizationStatus.CANCELLED
                    break
                except Exception as exc:  # noqa: BLE001
                    result.status = OptimizationStatus.LOAD_FAILED
                    result.error = str(exc)
                    run.candidates.append(result)
                    loaded = False
                    continue

                if headroom_check_fn is not None:
                    try:
                        ok = await self._bounded(
                            run, headroom_check_fn(), timeout=min(30.0, op_budget), label="headroom"
                        )
                        if not ok:
                            result.status = OptimizationStatus.HEADROOM_VIOLATION
                            result.warnings.append("post-load display/aux headroom violated")
                            try:
                                await self._bounded(
                                    run, unload_fn(model_id), timeout=min(60.0, op_budget), label="unload"
                                )
                            except Exception:  # noqa: BLE001
                                result.warnings.append("unload after headroom violation failed")
                                result.status = OptimizationStatus.UNSTABLE
                            loaded = False
                            run.candidates.append(result)
                            continue
                    except Exception as exc:  # noqa: BLE001
                        result.warnings.append(f"headroom check failed: {exc}")

                if not self._still_active(run):
                    try:
                        await unload_fn(model_id)
                    except Exception:  # noqa: BLE001
                        pass
                    loaded = False
                    result.status = OptimizationStatus.CANCELLED
                    run.candidates.append(result)
                    run.status = OptimizationStatus.CANCELLED
                    break

                # Exactly one benchmark call (warmup+measure owned by benchmark service)
                try:
                    bench = await self._bounded(
                        run, benchmark_fn(model_id), timeout=op_budget, label="benchmark"
                    )
                    metrics = (
                        bench.get("metrics") if isinstance(bench.get("metrics"), dict) else bench
                    )
                    result.generation_tps = _as_float(
                        metrics.get("generationTps")
                        or metrics.get("tokensPerSecond")
                        or metrics.get("generation_tokens_per_sec")
                    )
                    result.prompt_tps = _as_float(
                        metrics.get("promptTps") or metrics.get("prompt_tokens_per_sec")
                    )
                    result.ttft_seconds = _as_float(
                        metrics.get("ttftSeconds")
                        or metrics.get("ttft")
                        or metrics.get("timeToFirstToken")
                    )
                    if result.ttft_seconds is None:
                        # Map ms keys honestly
                        ttft_ms = _as_float(
                            metrics.get("timeToFirstTokenMs") or metrics.get("ttftMs")
                        )
                        if ttft_ms is not None:
                            result.ttft_seconds = ttft_ms / 1000.0
                    if (
                        result.generation_tps is None
                        and result.prompt_tps is None
                        and result.ttft_seconds is None
                    ):
                        latency = _as_float(
                            metrics.get("latencyMs")
                            or metrics.get("latency_ms")
                            or metrics.get("requestLatencyMs")
                        )
                        if latency is not None:
                            result.ttft_seconds = latency / 1000.0
                            result.warnings.append(
                                "Benchmark returned latency only; generation tok/s UNMEASURED"
                            )
                            # Mandatory maxTokensPerSec → cannot PASS
                            if run.objectives.max_tokens_per_sec:
                                result.status = OptimizationStatus.UNMEASURED
                            else:
                                result.status = OptimizationStatus.PASS
                        else:
                            result.status = OptimizationStatus.UNMEASURED
                    elif run.objectives.max_tokens_per_sec and result.generation_tps is None:
                        result.status = OptimizationStatus.UNMEASURED
                        result.warnings.append(
                            "maxTokensPerSec required but generation TPS not measured"
                        )
                    else:
                        result.status = OptimizationStatus.PASS
                except TimeoutError:
                    result.status = OptimizationStatus.TIMEOUT
                    result.error = "benchmark timeout"
                    result.warnings.append("benchmark timed out")
                except Exception as exc:  # noqa: BLE001
                    result.status = OptimizationStatus.UNMEASURED
                    result.error = str(exc)
                    result.warnings.append("benchmark failed")

                try:
                    await self._bounded(
                        run, unload_fn(model_id), timeout=min(60.0, op_budget), label="unload"
                    )
                    loaded = False
                except Exception as exc:  # noqa: BLE001
                    result.warnings.append(f"unload after candidate failed: {exc}")
                    result.status = OptimizationStatus.UNSTABLE
                    loaded = False

                if not self._still_active(run):
                    result.status = OptimizationStatus.CANCELLED
                    run.candidates.append(result)
                    run.status = OptimizationStatus.CANCELLED
                    break

                # Score only after gates — store raw score for gate-passers
                if passes_mandatory_gates(result, run.objectives):
                    result.score = score_candidate(result, run.objectives)
                else:
                    result.score = None
                run.candidates.append(result)

            # Final selection — never crown HEADROOM/OOM/UNSTABLE
            if run.status != OptimizationStatus.CANCELLED and not run.cancel_requested:
                eligible = [
                    c
                    for c in run.candidates
                    if passes_mandatory_gates(c, run.objectives) and c.score is not None
                ]
                if eligible:
                    best = max(eligible, key=lambda c: float(c.score or -1e18))
                    best.status = OptimizationStatus.BEST
                    run.best_index = best.index
                    run.status = OptimizationStatus.BEST
                else:
                    # Any PASS without full mandatory metrics still not BEST
                    if any(c.status == OptimizationStatus.PASS for c in run.candidates):
                        # PASS without being eligible means objectives blocked BEST
                        run.status = OptimizationStatus.UNMEASURED
                        run.error = "no candidate satisfied mandatory objective gates"
                    elif run.status not in {
                        OptimizationStatus.TIMEOUT,
                        OptimizationStatus.CANCELLED,
                    }:
                        run.status = OptimizationStatus.UNMEASURED
            elif run.cancel_requested:
                run.status = OptimizationStatus.CANCELLED

        except Exception as exc:  # noqa: BLE001
            if run.status != OptimizationStatus.CANCELLED:
                run.status = OptimizationStatus.UNMEASURED
                run.error = f"optimizer_failure:{type(exc).__name__}:{exc}"
        finally:
            if loaded:
                try:
                    await unload_fn(model_id)
                except Exception:  # noqa: BLE001
                    if run.error:
                        run.error = f"{run.error}; cleanup unload failed"
                    else:
                        run.error = "cleanup unload failed"
            # Terminal immutability: if cancel won the race, keep CANCELLED
            if run.cancel_requested:
                run.status = OptimizationStatus.CANCELLED
            run.finished_at = time.time()

        return run


def _extract_preflight_verdict(pre: dict[str, Any]) -> str:
    if not isinstance(pre, dict):
        return ""
    for key in ("verdict", "preflightVerdict"):
        if pre.get(key):
            return str(pre[key]).upper()
    estimate = pre.get("estimate")
    if isinstance(estimate, dict) and estimate.get("verdict"):
        return str(estimate["verdict"]).upper()
    plan = pre.get("plan")
    if isinstance(plan, dict) and plan.get("verdict"):
        return str(plan["verdict"]).upper()
    # placement_preflight shape: feasible bool
    if pre.get("feasible") is False:
        reason = str(pre.get("reason") or pre.get("error") or "")
        if any(tok in reason.upper() for tok in ("OOM", "VRAM", "MEMORY")):
            return "LIKELY_OOM"
    return ""


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
