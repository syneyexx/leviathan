"""Bounded deterministic model load-profile optimizer.

Searches a small candidate set, measures real load/benchmark outcomes, and
selects the best profile by explicit weighted objectives. No LLM scoring.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

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


@dataclass
class OptimizationObjective:
    max_tokens_per_sec: bool = True
    keep_display_responsive: bool = True
    maximize_model_size: bool = False
    stable_no_oom: bool = True

    # Explicit deterministic weights
    weight_gen_tps: float = 1.0
    weight_prompt_tps: float = 0.35
    weight_ttft: float = 0.25  # lower better
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
        }


def generate_candidates(
    base: LoadOptions,
    *,
    max_candidates: int = 8,
    device_count: int = 1,
) -> list[LoadOptions]:
    """Coarse-to-fine deterministic candidate set (4–12)."""
    max_candidates = max(4, min(12, int(max_candidates)))
    contexts = []
    base_ctx = base.context_length or 8192
    for c in (base_ctx, max(2048, base_ctx // 2), min(base_ctx * 2, 32768), 4096):
        if c not in contexts:
            contexts.append(int(c))
    ratios = []
    base_ratio = base.gpu_offload_ratio if base.gpu_offload_ratio is not None else 0.8
    for r in (base_ratio, min(1.0, base_ratio + 0.1), max(0.4, base_ratio - 0.15), 1.0, 0.6):
        rr = round(float(r), 3)
        if rr not in ratios:
            ratios.append(rr)

    flash_opts = [base.flash_attention if base.flash_attention is not None else True, False]
    kv_opts = [
        base.offload_kv_cache_to_gpu if base.offload_kv_cache_to_gpu is not None else True,
        False,
    ]
    batches = [base.batch_size or 256, 128, 512]
    seen: set[tuple] = set()
    out: list[LoadOptions] = []
    for ctx in contexts:
        for ratio in ratios:
            for flash in flash_opts[:1]:  # prefer flash on first pass
                for kv in kv_opts[:1]:
                    for batch in batches[:1]:
                        key = (ctx, ratio, flash, kv, batch)
                        if key in seen:
                            continue
                        seen.add(key)
                        tensor = base.tensor_split
                        split_mode = base.gpu_split_mode
                        if device_count >= 2 and base.allow_multi_gpu:
                            # Prefer auto; custom ratios unsupported via REST — keep requested split only as preference
                            split_mode = base.gpu_split_mode or "auto"
                        out.append(
                            LoadOptions(
                                context_length=ctx,
                                batch_size=batch,
                                flash_attention=flash,
                                offload_kv_cache_to_gpu=kv,
                                gpu_offload_ratio=ratio,
                                gpu_split_mode=split_mode,
                                tensor_split=tensor,
                                num_experts=base.num_experts,
                                keep_display_headroom=base.keep_display_headroom
                                if base.keep_display_headroom is not None
                                else True,
                                allow_multi_gpu=base.allow_multi_gpu,
                                preferred_device_ids=base.preferred_device_ids,
                                excluded_device_ids=base.excluded_device_ids,
                                main_gpu_ordinal=base.main_gpu_ordinal,
                            )
                        )
                        if len(out) >= max_candidates:
                            return out
    # Second pass: add safer / no-flash variants if room
    if len(out) < max_candidates:
        out.append(
            LoadOptions(
                context_length=max(2048, (base.context_length or 8192) // 2),
                batch_size=128,
                flash_attention=True,
                offload_kv_cache_to_gpu=True,
                gpu_offload_ratio=max(0.5, (base.gpu_offload_ratio or 0.8) - 0.2),
                keep_display_headroom=True,
            )
        )
    return out[:max_candidates]


def score_candidate(result: CandidateResult, objectives: OptimizationObjective) -> float | None:
    """Deterministic score. Higher is better. UNMEASURED / OOM → None or heavily penalized."""
    if result.status in {OptimizationStatus.CANCELLED, OptimizationStatus.SKIPPED}:
        return None
    if result.status == OptimizationStatus.UNMEASURED:
        return None
    if result.status == OptimizationStatus.OOM:
        return -objectives.weight_oom * 100.0
    if result.status == OptimizationStatus.LOAD_FAILED:
        return -50.0
    if result.status == OptimizationStatus.HEADROOM_VIOLATION:
        base = -objectives.weight_headroom_violation * 20.0
    else:
        base = 0.0

    score = base
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
    if objectives.keep_display_responsive and result.status == OptimizationStatus.HEADROOM_VIOLATION:
        score -= objectives.weight_headroom_violation * 10.0
    return score


class ModelLoadOptimizer:
    """In-process optimizer orchestrator. Long work should be driven from model_runtime/eval pool."""

    def __init__(self) -> None:
        self._runs: dict[str, OptimizationRun] = {}
        self._lock = asyncio.Lock()

    def get(self, run_id: str) -> OptimizationRun | None:
        return self._runs.get(run_id)

    def list_for_model(self, model_id: str) -> list[OptimizationRun]:
        return [r for r in self._runs.values() if r.model_id == model_id]

    def cancel(self, run_id: str) -> OptimizationRun | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.cancel_requested = True
        if run.status == OptimizationStatus.RUNNING:
            run.status = OptimizationStatus.CANCELLED
        return run

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
        load_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]],
        unload_fn: Callable[[str], Awaitable[dict[str, Any]]],
        benchmark_fn: Callable[[str], Awaitable[dict[str, Any]]],
        preflight_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None = None,
        estimate_fn: Callable[[str, LoadOptions], Awaitable[dict[str, Any]]] | None = None,
        headroom_check_fn: Callable[[], Awaitable[bool]] | None = None,
    ) -> OptimizationRun:
        run = OptimizationRun(
            run_id=str(uuid.uuid4()),
            model_id=model_id,
            objectives=objectives or OptimizationObjective(),
            max_candidates=max_candidates,
            deadline_seconds=deadline_seconds,
            status=OptimizationStatus.RUNNING,
            started_at=time.time(),
        )
        self._runs[run.run_id] = run

        candidates = generate_candidates(
            base_options, max_candidates=max_candidates, device_count=device_count
        )
        deadline = run.started_at + deadline_seconds

        for idx, opts in enumerate(candidates):
            if run.cancel_requested or time.time() > deadline:
                run.candidates.append(
                    CandidateResult(
                        index=idx + 1,
                        options=opts,
                        status=OptimizationStatus.CANCELLED,
                        context_length=opts.context_length,
                        gpu_offload_ratio=opts.gpu_offload_ratio,
                    )
                )
                run.status = OptimizationStatus.CANCELLED
                break

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
                gpu1_ratio=(opts.tensor_split[1] if opts.tensor_split and len(opts.tensor_split) > 1 else None),
                fingerprint=fp,
            )

            # Preflight reject unsafe candidates (optimizer never confirmOom)
            if preflight_fn is not None:
                try:
                    pre = await preflight_fn(model_id, opts)
                    verdict = str(
                        (pre.get("estimate") or pre.get("preflight") or pre).get("verdict")
                        if isinstance(pre.get("estimate") or pre.get("preflight") or pre, dict)
                        else pre.get("verdict")
                        or ""
                    ).upper()
                    if verdict == "LIKELY_OOM":
                        result.status = OptimizationStatus.OOM
                        result.error = "preflight LIKELY_OOM"
                        result.score = score_candidate(result, run.objectives)
                        run.candidates.append(result)
                        continue
                except ModelControlError as exc:
                    if "OOM" in exc.code or "MEMORY" in exc.code:
                        result.status = OptimizationStatus.OOM
                        result.error = exc.message
                        result.score = score_candidate(result, run.objectives)
                        run.candidates.append(result)
                        continue

            if estimate_fn is not None:
                try:
                    await estimate_fn(model_id, opts)
                except Exception:  # noqa: BLE001 — estimate advisory
                    result.warnings.append("provider estimate unavailable")

            # Load
            try:
                load_result = await load_fn(model_id, opts)
                result.load_time_seconds = (
                    load_result.get("loadTimeSeconds")
                    or (load_result.get("receipt") or {}).get("loadTimeSeconds")
                )
                result.applied_config = load_result.get("appliedConfig") or (
                    load_result.get("receipt") or {}
                ).get("appliedConfig")
            except ModelControlError as exc:
                code = exc.code or ""
                if "OOM" in code:
                    result.status = OptimizationStatus.OOM
                else:
                    result.status = OptimizationStatus.LOAD_FAILED
                result.error = exc.message
                result.score = score_candidate(result, run.objectives)
                run.candidates.append(result)
                continue
            except Exception as exc:  # noqa: BLE001
                result.status = OptimizationStatus.LOAD_FAILED
                result.error = str(exc)
                result.score = score_candidate(result, run.objectives)
                run.candidates.append(result)
                continue

            if headroom_check_fn is not None:
                try:
                    ok = await headroom_check_fn()
                    if not ok:
                        result.status = OptimizationStatus.HEADROOM_VIOLATION
                        result.warnings.append("post-load display/aux headroom violated")
                        try:
                            await unload_fn(model_id)
                        except Exception:  # noqa: BLE001
                            pass
                        result.score = score_candidate(result, run.objectives)
                        run.candidates.append(result)
                        continue
                except Exception as exc:  # noqa: BLE001
                    result.warnings.append(f"headroom check failed: {exc}")

            # Benchmark (warmup separate from measured — caller responsibility)
            try:
                bench = await benchmark_fn(model_id)
                metrics = bench.get("metrics") if isinstance(bench.get("metrics"), dict) else bench
                result.generation_tps = _as_float(
                    metrics.get("generationTps")
                    or metrics.get("tokensPerSecond")
                    or metrics.get("generation_tokens_per_sec")
                )
                result.prompt_tps = _as_float(
                    metrics.get("promptTps") or metrics.get("prompt_tokens_per_sec")
                )
                result.ttft_seconds = _as_float(
                    metrics.get("ttftSeconds") or metrics.get("ttft") or metrics.get("timeToFirstToken")
                )
                if result.generation_tps is None and result.prompt_tps is None and result.ttft_seconds is None:
                    # Latency-only benchmark — mark UNMEASURED for tok/s, still record latency if present
                    latency = _as_float(metrics.get("latencyMs") or metrics.get("latency_ms"))
                    if latency is not None:
                        result.ttft_seconds = latency / 1000.0
                        result.status = OptimizationStatus.PASS
                        result.warnings.append(
                            "Benchmark returned latency only; generation tok/s UNMEASURED"
                        )
                    else:
                        result.status = OptimizationStatus.UNMEASURED
                else:
                    result.status = OptimizationStatus.PASS
            except Exception as exc:  # noqa: BLE001
                result.status = OptimizationStatus.UNMEASURED
                result.error = str(exc)
                result.warnings.append("benchmark failed")

            try:
                await unload_fn(model_id)
            except Exception as exc:  # noqa: BLE001
                result.warnings.append(f"unload after candidate failed: {exc}")
                result.status = OptimizationStatus.UNSTABLE

            result.score = score_candidate(result, run.objectives)
            run.candidates.append(result)

        # Select best among measured PASS / HEADROOM (scored)
        scored = [
            c
            for c in run.candidates
            if c.score is not None and c.status not in {OptimizationStatus.UNMEASURED, OptimizationStatus.CANCELLED}
        ]
        if scored:
            best = max(scored, key=lambda c: float(c.score or -1e18))
            # Do not crown UNMEASURED or OOM as BEST
            if best.status in {OptimizationStatus.PASS, OptimizationStatus.HEADROOM_VIOLATION} or (
                best.status == OptimizationStatus.PASS
            ):
                if best.status == OptimizationStatus.PASS:
                    best.status = OptimizationStatus.BEST
                    run.best_index = best.index
                    run.status = OptimizationStatus.BEST
                else:
                    run.status = OptimizationStatus.PASS
                    run.best_index = best.index
            else:
                run.status = OptimizationStatus.PASS if any(
                    c.status == OptimizationStatus.PASS for c in run.candidates
                ) else OptimizationStatus.UNMEASURED
        else:
            if run.status != OptimizationStatus.CANCELLED:
                run.status = OptimizationStatus.UNMEASURED

        run.finished_at = time.time()
        return run


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
