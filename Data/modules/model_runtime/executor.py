"""model_runtime worker executor — owns ServingSupervisor and diagnostics."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

from Data.modules.jobs.leases import fenced_transition
from Data.modules.jobs.states import JobState
from Data.modules.model_runtime.facade import (
    CAP_BENCHMARK,
    CAP_INFERENCE_TEST,
    CAP_LOAD,
    CAP_PROBE,
    CAP_RECONCILE,
    CAP_UNLOAD,
)


class ModelRuntimeExecutor:
    """Singleton-pool executor for managed serving lifecycle + probes/benchmarks."""

    def __init__(self, *, settings: Any | None = None) -> None:
        self.settings = settings
        self._plane: Any | None = None
        self._supervision_stop = threading.Event()
        self._supervision_thread: threading.Thread | None = None
        self._bootstrapped = False

    def close(self) -> None:
        self._supervision_stop.set()
        thread = self._supervision_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._supervision_thread = None

    def bootstrap(self, ctx: dict[str, Any]) -> None:
        """Composition root: own ServingSupervisor, reconcile, start heartbeat."""
        if self._bootstrapped:
            return
        os.environ.setdefault("LEVIATHAN_WORKER_POOL", "model_runtime")
        plane = self._get_plane(ctx)
        # Force supervisor construction in this worker process.
        serving = getattr(plane, "serving", None)
        if serving is not None:
            try:
                serving.reconcile_persisted_orphans()
                serving.reconcile()
            except Exception:  # noqa: BLE001
                pass
            try:
                plane.reconcile_serving_workers()
            except Exception:  # noqa: BLE001
                pass
        self._start_supervision_loop(plane)
        self._bootstrapped = True

    def _start_supervision_loop(self, plane: Any) -> None:
        if self._supervision_thread is not None:
            return
        self._supervision_stop.clear()

        def _loop() -> None:
            while not self._supervision_stop.wait(10.0):
                try:
                    serving = getattr(plane, "serving", None)
                    if serving is not None:
                        serving.reconcile()
                except Exception:  # noqa: BLE001
                    pass

        self._supervision_thread = threading.Thread(
            target=_loop,
            name="model-runtime-supervise",
            daemon=True,
        )
        self._supervision_thread.start()

    def _get_plane(self, ctx: dict[str, Any]) -> Any:
        if self._plane is not None:
            return self._plane
        from Data.modules.models.control_plane import ModelControlPlane

        settings = ctx.get("settings") or self.settings
        if settings is None:
            from Data.backend.config import load_settings

            settings = load_settings()
            self.settings = settings
        plane = ModelControlPlane(settings)
        job_runtime = ctx.get("job_runtime")
        if job_runtime is not None:
            plane.bind_job_runtime(job_runtime)
        self._plane = plane
        return plane

    def execute_job(self, ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
        self.bootstrap(ctx)
        store = ctx["job_store"]
        worker_id = str(ctx.get("worker_id") or "")
        capability = str(getattr(job, "capability_id", "") or "")
        args = dict(getattr(job, "arguments", None) or {})

        def _cancelled() -> bool:
            try:
                current = store.get(job.job_id)
                if current is None:
                    return True
                return current.state in {JobState.CANCELLED, JobState.FAILED}
            except Exception:  # noqa: BLE001
                return False

        try:
            if capability == CAP_LOAD:
                result = self._run_async(self._load(ctx, args, cancel_check=_cancelled))
            elif capability == CAP_UNLOAD:
                result = self._run_async(self._unload(ctx, args, cancel_check=_cancelled))
            elif capability == CAP_RECONCILE:
                result = self._reconcile(ctx)
            elif capability == CAP_BENCHMARK:
                result = self._run_async(
                    self._benchmark(ctx, args, cancel_check=_cancelled)
                )
            elif capability == CAP_PROBE:
                result = self._run_async(self._probe(ctx, args, cancel_check=_cancelled))
            elif capability == CAP_INFERENCE_TEST:
                result = self._run_async(
                    self._inference_test(ctx, args, cancel_check=_cancelled)
                )
            else:
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.FAILED,
                    error=f"unknown model_runtime capability: {capability}",
                    worker_id=worker_id,
                    ctx=ctx,
                )
                return {"error": f"unknown capability {capability}"}

            if _cancelled():
                fenced_transition(
                    store,
                    job.job_id,
                    JobState.CANCELLED,
                    result=result if isinstance(result, dict) else {"partial": True},
                    error="cancelled",
                    worker_id=worker_id,
                    ctx=ctx,
                )
                return result if isinstance(result, dict) else {}

            fenced_transition(
                store,
                job.job_id,
                JobState.COMPLETED,
                result=result if isinstance(result, dict) else {"ok": True},
                worker_id=worker_id,
                ctx=ctx,
            )
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001
            fenced_transition(
                store,
                job.job_id,
                JobState.FAILED,
                error=str(exc)[:500],
                worker_id=worker_id,
                ctx=ctx,
            )
            return {"error": str(exc)}

    def _run_async(self, coro: Any) -> Any:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Nested: create a fresh loop in a thread.
                result_box: dict[str, Any] = {}
                error_box: dict[str, BaseException] = {}

                def _runner() -> None:
                    try:
                        result_box["value"] = asyncio.run(coro)
                    except BaseException as exc:  # noqa: BLE001
                        error_box["error"] = exc

                thread = threading.Thread(target=_runner, daemon=True)
                thread.start()
                thread.join()
                if "error" in error_box:
                    raise error_box["error"]
                return result_box.get("value")
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _load(
        self,
        ctx: dict[str, Any],
        args: dict[str, Any],
        *,
        cancel_check: Any,
    ) -> dict[str, Any]:
        from Data.modules.models import parse_load_options

        if cancel_check():
            return {"cancelled": True, "phase": "planning"}
        plane = self._get_plane(ctx)
        model_id = str(args.get("model_id") or "")
        options = parse_load_options(args.get("options") or {})
        confirm_oom = bool(args.get("confirm_oom"))
        # Allow inline serving ownership inside this worker.
        os.environ["LEVIATHAN_MODEL_RUNTIME_ALLOW_INLINE_TEST"] = "1"
        try:
            result = await plane.load_model(
                model_id, options, confirm_oom=confirm_oom
            )
        finally:
            # Keep allow flag for the worker process lifetime — this process is
            # the authorized owner. Explicit env already set by entrypoint.
            pass
        return {
            "queued": False,
            "modelId": model_id,
            "phase": "ready",
            "result": result,
        }

    async def _unload(
        self,
        ctx: dict[str, Any],
        args: dict[str, Any],
        *,
        cancel_check: Any,
    ) -> dict[str, Any]:
        if cancel_check():
            return {"cancelled": True, "phase": "drain"}
        plane = self._get_plane(ctx)
        model_id = str(args.get("model_id") or "")
        serving_generation = args.get("serving_generation")
        # Stale-generation fence: refuse to stop a newer serving generation.
        if serving_generation is not None:
            snap = plane.residency.snapshot(model_id)
            current_gen = int(getattr(snap, "runtime_generation", 0) or 0)
            if current_gen and int(serving_generation) != current_gen:
                from Data.modules.models.errors import (
                    MODEL_RUNTIME_STALE_GENERATION,
                    ModelControlError,
                )

                raise ModelControlError(
                    code=MODEL_RUNTIME_STALE_GENERATION,
                    message=(
                        f"Stale unload generation {serving_generation} "
                        f"(current={current_gen}); refusing to stop replacement server"
                    ),
                    model_id=model_id,
                    http_status=409,
                    details={
                        "requestedGeneration": int(serving_generation),
                        "currentGeneration": current_gen,
                    },
                )
        result = await plane.unload_model(model_id)
        return {"modelId": model_id, "phase": "stopped", "result": result}

    def _reconcile(self, ctx: dict[str, Any]) -> dict[str, Any]:
        plane = self._get_plane(ctx)
        result = plane.reconcile_serving_workers()
        try:
            plane.reconcile_persisted_serving_workers()
        except Exception:  # noqa: BLE001
            pass
        return {"reconcile": result, "phase": "done"}

    async def _benchmark(
        self,
        ctx: dict[str, Any],
        args: dict[str, Any],
        *,
        cancel_check: Any,
    ) -> dict[str, Any]:
        plane = self._get_plane(ctx)
        model_id = str(args.get("model_id") or "")
        warmup = max(0, int(args.get("warmup") or 1))
        iterations = max(1, min(int(args.get("iterations") or 3), 20))
        prompt = str(args.get("prompt") or "Count from 1 to 3.")
        max_tokens = max(1, min(int(args.get("max_tokens") or 16), 256))
        adapter = plane.get_adapter(plane.registry.get(model_id).provider_id)

        samples: list[dict[str, Any]] = []
        cancelled = False
        phase = "warmup"

        for i in range(warmup):
            if cancel_check():
                cancelled = True
                break
            phase = f"warmup {i + 1}/{warmup}"
            started = time.perf_counter()
            try:
                outcome = await adapter.test_inference(
                    model_id, prompt=prompt, max_tokens=max_tokens
                )
            except Exception as exc:  # noqa: BLE001
                return {
                    "modelId": model_id,
                    "status": "FAILED",
                    "phase": phase,
                    "error": str(exc)[:300],
                    "samples": samples,
                }
            _ = (time.perf_counter() - started) * 1000.0
            _ = outcome

        if not cancelled:
            for i in range(iterations):
                if cancel_check():
                    cancelled = True
                    break
                phase = f"iteration {i + 1}/{iterations}"
                started = time.perf_counter()
                try:
                    outcome = await adapter.test_inference(
                        model_id, prompt=prompt, max_tokens=max_tokens
                    )
                except Exception as exc:  # noqa: BLE001
                    return {
                        "modelId": model_id,
                        "status": "FAILED",
                        "phase": phase,
                        "error": str(exc)[:300],
                        "samples": samples,
                        "truth": {"no_fabricated_tps": True},
                    }
                total_ms = (time.perf_counter() - started) * 1000.0
                samples.append(
                    {
                        "requestLatencyMs": total_ms,
                        "timeToFirstTokenMs": outcome.get("latencyMs"),
                        "tokensGenerated": outcome.get("tokensGenerated"),
                        "tokensPerSecond": outcome.get("tokensPerSecond"),
                        "preview": outcome.get("preview"),
                    }
                )

        phase = "aggregating" if samples else phase
        latencies = [s["requestLatencyMs"] for s in samples if s.get("requestLatencyMs") is not None]
        mean_ms = (sum(latencies) / len(latencies)) if latencies else None
        # Never invent tokens/sec from character counts.
        measured_tps = [
            s["tokensPerSecond"]
            for s in samples
            if s.get("tokensPerSecond") is not None
        ]
        serving_workers = [
            w
            for w in plane.list_serving_workers()
            if w.get("model_id") == model_id or w.get("modelId") == model_id
        ]
        worker_id = serving_workers[0].get("worker_id") if serving_workers else None
        status = "CANCELLED" if cancelled else "COMPLETED"
        if cancelled and samples:
            status = "CANCELLED"
        return {
            "modelId": model_id,
            "status": status,
            "phase": "done" if not cancelled else "cancelled",
            "warmup": warmup,
            "iterationsRequested": iterations,
            "iterationsMeasured": len(samples),
            "requestLatencyMsMean": mean_ms,
            "requestLatencyMsMin": min(latencies) if latencies else None,
            "requestLatencyMsMax": max(latencies) if latencies else None,
            "tokensPerSecond": (
                (sum(measured_tps) / len(measured_tps)) if measured_tps else None
            ),
            "servingWorkerId": worker_id,
            "samples": samples,
            "note": "Measured raw metrics only — not a ranking score",
            "truth": {
                "no_fabricated_tps": True,
                "warmup_separated": True,
                "partial_on_cancel": cancelled,
            },
        }

    async def _probe(
        self,
        ctx: dict[str, Any],
        args: dict[str, Any],
        *,
        cancel_check: Any,
    ) -> dict[str, Any]:
        plane = self._get_plane(ctx)
        model_id = str(args.get("model_id") or "")
        capabilities = args.get("capabilities")
        timeout_seconds = float(args.get("timeout_seconds") or 15.0)
        if cancel_check():
            return {"modelId": model_id, "status": "CANCELLED", "results": []}
        results = await plane.probes.probe(
            model_id,
            capabilities=list(capabilities) if capabilities else None,
            timeout_seconds=timeout_seconds,
        )
        return {
            "modelId": model_id,
            "status": "COMPLETED",
            "results": [r.public_dict() for r in results],
            "truth": {
                "declared_is_not_verified": True,
                "old_evidence_preserved_until_complete": True,
            },
        }

    async def _inference_test(
        self,
        ctx: dict[str, Any],
        args: dict[str, Any],
        *,
        cancel_check: Any,
    ) -> dict[str, Any]:
        if cancel_check():
            return {"status": "CANCELLED"}
        plane = self._get_plane(ctx)
        model_id = str(args.get("model_id") or "")
        result = await plane.test_inference(
            model_id,
            prompt=str(args.get("prompt") or "ping"),
            max_tokens=int(args.get("max_tokens") or 64),
            stream=bool(args.get("stream")),
        )
        return {"status": "COMPLETED", "result": result}
