"""Phase 9 Neural Runtime lifecycle boundary.

Owns start/stop/health/load/infer/metrics for the research NeuralModelRuntime.
Default isolation is in-process; optional subprocess isolation follows the
training_worker pattern so CUDA/native crashes do not take down FastAPI.

Not wired into ModelGateway / FastAPI. Default mode remains OFF. LEARN rejected.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from neural.checkpoint import SCHEMA_VERSION, NeuralMemoryCheckpointStore
from neural.config import NeuralMemoryConfig
from neural.contracts import (
    NEURAL_RUNTIME_PROTOCOL_VERSION,
    NeuralInferRequest,
    NeuralInferResult,
    NeuralMode,
    NeuralModelSpec,
    NeuralRuntimeHealth,
    NeuralRuntimeIdentity,
    NeuralRuntimeMetrics,
    NeuralRuntimeState,
)
from neural import deps as neural_deps
from neural.errors import (
    NeuralCheckpointIncompatible,
    NeuralModeUnsupported,
    NeuralRuntimeCancelled,
    NeuralRuntimeFailed,
    NeuralRuntimeNotReady,
    NeuralRuntimeUnavailable,
)
from neural.runtime_compat import validate_memory_checkpoint_manifest


@dataclass
class NeuralRuntimeStartConfig:
    isolation: str = "inprocess"  # inprocess | subprocess
    mode: NeuralMode = NeuralMode.OFF
    work_dir: str | Path | None = None
    model_spec: NeuralModelSpec | None = None
    auto_load_model: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "isolation": self.isolation,
            "mode": self.mode.value,
            "work_dir": str(self.work_dir) if self.work_dir else None,
            "model_spec": self.model_spec.to_dict() if self.model_spec else None,
            "auto_load_model": self.auto_load_model,
        }


class NeuralRuntimeBoundary:
    """Typed lifecycle façade over NeuralModelRuntime (+ optional subprocess)."""

    def __init__(self) -> None:
        self._state = NeuralRuntimeState.STOPPED
        self._isolation = "inprocess"
        self._mode = NeuralMode.OFF
        self._engine: Any | None = None
        self._identity: NeuralRuntimeIdentity | None = None
        self._metrics = NeuralRuntimeMetrics()
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._last_error: dict[str, Any] | None = None
        self._last_inference_success: bool | None = None
        self._checkpoint_compatible: bool | None = None
        self._memory_loaded = False
        self._adapter_loaded = False
        self._slow_checkpoint_id: str | None = None
        self._fast_state_id: str | None = None
        self._gpu_oom = False
        self._process: subprocess.Popen[str] | None = None
        self._work_dir: Path | None = None
        self._model_spec: NeuralModelSpec | None = None
        self._base_checksum_at_load: str | None = None

    # --- public contract -------------------------------------------------

    def start(self, config: NeuralRuntimeStartConfig | Mapping[str, Any] | None = None) -> NeuralRuntimeHealth:
        with self._lock:
            cfg = self._coerce_start_config(config)
            if cfg.isolation not in {"inprocess", "subprocess"}:
                raise NeuralRuntimeUnavailable(
                    "unsupported isolation mode",
                    detail={"isolation": cfg.isolation},
                )
            if self._state not in {
                NeuralRuntimeState.STOPPED,
                NeuralRuntimeState.FAILED,
                NeuralRuntimeState.UNAVAILABLE,
            }:
                raise NeuralRuntimeNotReady(
                    "runtime already active",
                    detail={"state": self._state.value},
                )
            self._reset_session_flags()
            self._isolation = cfg.isolation
            self._mode = cfg.mode
            self._model_spec = cfg.model_spec or NeuralModelSpec()
            self._state = NeuralRuntimeState.STARTING
            if not neural_deps.neural_available():
                self._state = NeuralRuntimeState.UNAVAILABLE
                self._last_error = {
                    "code": "neural_dependency_unavailable",
                    "message": "PyTorch is not installed; neural runtime unavailable",
                }
                return self.health()
            try:
                if cfg.isolation == "subprocess":
                    self._start_subprocess(cfg)
                elif cfg.auto_load_model:
                    self._state = NeuralRuntimeState.LOADING
                    self._load_model_inprocess(self._model_spec)
                else:
                    # Process/session started but not inference-ready until load_model.
                    self._state = NeuralRuntimeState.DEGRADED
                self._last_error = None
            except NeuralRuntimeUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 — boundary must stay truthful
                self._state = NeuralRuntimeState.FAILED
                self._last_error = {"code": "neural_runtime_failed", "message": str(exc)}
                raise NeuralRuntimeFailed(str(exc), detail=dict(self._last_error)) from exc
            return self.health()

    def stop(self) -> NeuralRuntimeHealth:
        with self._lock:
            self._state = NeuralRuntimeState.STOPPING
            self._cancel.set()
            try:
                if self._isolation == "subprocess" and self._process is not None:
                    self._rpc({"op": "stop"}, timeout_s=5.0, ignore_dead=True)
                    self._terminate_process()
                self._engine = None
                self._identity = None
                self._memory_loaded = False
                self._adapter_loaded = False
                self._base_checksum_at_load = None
                self._state = NeuralRuntimeState.STOPPED
                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._state = NeuralRuntimeState.FAILED
                self._last_error = {"code": "neural_runtime_failed", "message": str(exc)}
            finally:
                self._cancel.clear()
            return self.health()

    def health(self) -> NeuralRuntimeHealth:
        process_alive = True
        if self._isolation == "subprocess":
            process_alive = self._process is not None and self._process.poll() is None
            if self._process is not None and not process_alive and self._state not in {
                NeuralRuntimeState.STOPPED,
                NeuralRuntimeState.STOPPING,
                NeuralRuntimeState.FAILED,
            }:
                self._state = NeuralRuntimeState.FAILED
                self._last_error = {
                    "code": "neural_runtime_failed",
                    "message": "neural runtime worker process exited",
                    "returncode": self._process.returncode,
                }
        info = neural_deps.torch_info()
        base_loaded = self._identity is not None and self._state is NeuralRuntimeState.READY
        return NeuralRuntimeHealth(
            state=self._state,
            process_alive=process_alive,
            runtime_initialized=self._engine is not None or (
                self._isolation == "subprocess" and process_alive and self._identity is not None
            ),
            base_model_loaded=base_loaded,
            memory_loaded=self._memory_loaded,
            adapter_loaded=self._adapter_loaded,
            cuda_available=bool(info.get("cuda")),
            gpu_oom_state=self._gpu_oom,
            last_inference_success=self._last_inference_success,
            last_error=dict(self._last_error) if self._last_error else None,
            checkpoint_compatible=self._checkpoint_compatible,
            isolation=self._isolation,
            identity=self._identity,
        )

    def load_model(self, spec: NeuralModelSpec | Mapping[str, Any] | None = None) -> NeuralRuntimeIdentity:
        with self._lock:
            model_spec = NeuralModelSpec.from_dict(spec) if isinstance(spec, Mapping) else (spec or self._model_spec or NeuralModelSpec())
            self._model_spec = model_spec
            if not neural_deps.neural_available():
                self._state = NeuralRuntimeState.UNAVAILABLE
                raise NeuralRuntimeUnavailable("PyTorch unavailable")
            self._state = NeuralRuntimeState.LOADING
            try:
                if self._isolation == "subprocess":
                    payload = self._rpc({"op": "load_model", "spec": model_spec.to_dict()}, timeout_s=60.0)
                    self._identity = NeuralRuntimeIdentity(**self._identity_kwargs_from_dict(payload["identity"]))
                    self._base_checksum_at_load = self._identity.base_model_fingerprint
                    self._state = NeuralRuntimeState.READY
                else:
                    self._load_model_inprocess(model_spec)
                assert self._identity is not None
                return self._identity
            except Exception as exc:  # noqa: BLE001
                self._state = NeuralRuntimeState.FAILED
                self._last_error = {"code": "neural_runtime_failed", "message": str(exc)}
                raise

    def unload_model(self) -> NeuralRuntimeHealth:
        with self._lock:
            if self._isolation == "subprocess" and self._process is not None:
                self._rpc({"op": "unload_model"}, timeout_s=30.0)
            self._engine = None
            self._identity = None
            self._memory_loaded = False
            self._base_checksum_at_load = None
            if self._state not in {NeuralRuntimeState.STOPPED, NeuralRuntimeState.FAILED}:
                self._state = NeuralRuntimeState.DEGRADED
            return self.health()

    def load_memory_checkpoint(
        self,
        *,
        store_root: str | Path,
        checkpoint_id: str | None = None,
        candidate: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state is not NeuralRuntimeState.READY or self._identity is None:
                raise NeuralRuntimeNotReady(
                    "runtime not ready for checkpoint load",
                    detail={"state": self._state.value},
                )
            store = NeuralMemoryCheckpointStore(store_root)
            # Peek manifest before attach.
            if checkpoint_id is None:
                pointer_name = "latest_candidate.json" if candidate else "latest.json"
                pointer = json.loads((store.root / pointer_name).read_text(encoding="utf-8"))
                checkpoint_id = str(pointer["checkpoint_id"])
                candidate = bool(pointer.get("candidate", candidate))
            manifest_path = store.root / ("candidate" if candidate else "good") / str(checkpoint_id) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            try:
                validate_memory_checkpoint_manifest(
                    manifest,
                    expected_hidden_size=self._identity.hidden_size,
                    expected_architecture_version=self._identity.neural_architecture_version,
                    expected_schema_version=SCHEMA_VERSION,
                )
                self._checkpoint_compatible = True
            except NeuralCheckpointIncompatible as exc:
                self._checkpoint_compatible = False
                self._last_error = exc.as_dict()
                raise

            t0 = time.perf_counter()
            if self._isolation == "subprocess":
                payload = self._rpc(
                    {
                        "op": "load_checkpoint",
                        "store_root": str(Path(store_root)),
                        "checkpoint_id": checkpoint_id,
                        "candidate": candidate,
                    },
                    timeout_s=60.0,
                )
                self._slow_checkpoint_id = str(payload.get("checkpoint_id") or checkpoint_id)
            else:
                assert self._engine is not None
                memory = store.load(
                    checkpoint_id,
                    candidate=candidate,
                    expected_config=self._engine.memory.config,
                )
                self._engine.memory = memory
                self._slow_checkpoint_id = str(checkpoint_id)
            self._metrics.checkpoint_load_ms = (time.perf_counter() - t0) * 1000.0
            self._memory_loaded = True
            self._refresh_identity_checkpoint_ids()
            return {"checkpoint_id": self._slow_checkpoint_id, "compatible": True}

    def infer(self, request: NeuralInferRequest | Mapping[str, Any]) -> NeuralInferResult:
        req = NeuralInferRequest.from_dict(request) if isinstance(request, Mapping) else request
        with self._lock:
            if self._cancel.is_set():
                self._metrics.cancel_count += 1
                raise NeuralRuntimeCancelled("inference cancelled before start")
            if self._state is not NeuralRuntimeState.READY:
                raise NeuralRuntimeNotReady(
                    "runtime not ready for inference",
                    detail={"state": self._state.value},
                )
            if req.mode is NeuralMode.LEARN:
                raise NeuralModeUnsupported(
                    "LEARN mode is not enabled on NeuralRuntimeBoundary",
                    detail={"mode": req.mode.value},
                )
            t0 = time.perf_counter()
            try:
                if self._isolation == "subprocess":
                    payload = self._rpc(
                        {"op": "infer", "request": req.to_dict()},
                        timeout_s=120.0,
                    )
                    if payload.get("cancelled"):
                        self._metrics.cancel_count += 1
                        raise NeuralRuntimeCancelled("inference cancelled")
                    result = NeuralInferResult(
                        request_id=req.request_id,
                        mode=NeuralMode(payload["mode"]),
                        logits=payload.get("logits"),
                        bypassed=bool(payload.get("bypassed")),
                        base_checksum=str(payload.get("base_checksum") or ""),
                        fusion_events=list(payload.get("fusion_events") or []),
                        latency_ms=float(payload.get("latency_ms") or 0.0),
                    )
                else:
                    result = self._infer_inprocess(req)
                # Prove freeze after every inference.
                if self._base_checksum_at_load and result.base_checksum != self._base_checksum_at_load:
                    self._state = NeuralRuntimeState.FAILED
                    raise NeuralRuntimeFailed(
                        "base model weights changed during inference",
                        detail={
                            "expected": self._base_checksum_at_load,
                            "got": result.base_checksum,
                        },
                    )
                self._last_inference_success = True
                self._metrics.inference_count += 1
                self._metrics.total_inference_latency_ms = result.latency_ms
                if self._metrics.first_token_latency_ms is None:
                    self._metrics.first_token_latency_ms = result.latency_ms
                return result
            except NeuralRuntimeCancelled:
                self._last_inference_success = False
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_inference_success = False
                self._last_error = {"code": getattr(exc, "code", "neural_runtime_failed"), "message": str(exc)}
                if "out of memory" in str(exc).lower():
                    self._gpu_oom = True
                    self._state = NeuralRuntimeState.DEGRADED
                raise
            finally:
                elapsed = (time.perf_counter() - t0) * 1000.0
                if self._metrics.total_inference_latency_ms is None:
                    self._metrics.total_inference_latency_ms = elapsed

    def metrics(self) -> NeuralRuntimeMetrics:
        return self._metrics

    def cancel(self) -> None:
        self._cancel.set()
        self._metrics.cancel_count += 1
        if self._isolation == "subprocess" and self._process is not None and self._work_dir is not None:
            (self._work_dir / "cancel.requested").write_text("cancel\n", encoding="utf-8")
            try:
                self._rpc({"op": "cancel"}, timeout_s=2.0, ignore_dead=True)
            except Exception:  # noqa: BLE001
                pass

    def prove_base_frozen(self) -> str:
        """Efficient freeze proof: compare checksum identity before/after ops."""
        with self._lock:
            if self._isolation == "subprocess":
                payload = self._rpc({"op": "prove_base_frozen"}, timeout_s=30.0)
                checksum = str(payload["base_checksum"])
            else:
                if self._engine is None:
                    raise NeuralRuntimeNotReady("no engine loaded")
                checksum = self._engine.verify_base_frozen()
            if self._base_checksum_at_load and checksum != self._base_checksum_at_load:
                raise NeuralRuntimeFailed(
                    "base model immutability proof failed",
                    detail={"expected": self._base_checksum_at_load, "got": checksum},
                )
            return checksum

    # --- internals -------------------------------------------------------

    def _coerce_start_config(
        self, config: NeuralRuntimeStartConfig | Mapping[str, Any] | None
    ) -> NeuralRuntimeStartConfig:
        if config is None:
            return NeuralRuntimeStartConfig()
        if isinstance(config, NeuralRuntimeStartConfig):
            return config
        mode = config.get("mode", NeuralMode.OFF)
        if isinstance(mode, str):
            mode = NeuralMode(mode)
        spec_raw = config.get("model_spec")
        spec = NeuralModelSpec.from_dict(spec_raw) if isinstance(spec_raw, Mapping) else spec_raw
        return NeuralRuntimeStartConfig(
            isolation=str(config.get("isolation") or "inprocess"),
            mode=mode,
            work_dir=config.get("work_dir"),
            model_spec=spec,
            auto_load_model=bool(config.get("auto_load_model", True)),
        )

    def _reset_session_flags(self) -> None:
        self._cancel.clear()
        self._last_error = None
        self._last_inference_success = None
        self._checkpoint_compatible = None
        self._memory_loaded = False
        self._adapter_loaded = False
        self._slow_checkpoint_id = None
        self._fast_state_id = None
        self._gpu_oom = False
        self._metrics = NeuralRuntimeMetrics()

    def _load_model_inprocess(self, spec: NeuralModelSpec) -> None:
        from neural.runtime import NeuralModelRuntime
        from neural.toy_transformer import ToyTransformerConfig

        t0 = time.perf_counter()
        toy = ToyTransformerConfig(
            vocab_size=spec.vocab_size,
            hidden_size=spec.hidden_size,
            num_layers=spec.num_layers,
            num_heads=spec.num_heads,
            intermediate_size=spec.intermediate_size,
            max_seq_len=spec.max_seq_len,
            seed=spec.seed,
        )
        mem_cfg = NeuralMemoryConfig(
            dim=spec.hidden_size,
            hidden_dim=max(32, spec.hidden_size * 2),
            mode=NeuralMode.OFF,
            seed=spec.seed,
            device=spec.device,
        )
        engine = NeuralModelRuntime(
            toy_config=toy,
            memory_config=mem_cfg,
            mode=self._mode if self._mode is not NeuralMode.LEARN else NeuralMode.OFF,
            injection_layers=list(spec.injection_layers),
            fusion_scale=spec.fusion_scale,
            device=spec.device,
        )
        checksum = engine.verify_base_frozen()
        self._engine = engine
        self._base_checksum_at_load = checksum
        self._identity = NeuralRuntimeIdentity(
            protocol_version=NEURAL_RUNTIME_PROTOCOL_VERSION,
            base_model_id=spec.model_id,
            base_model_fingerprint=checksum,
            tokenizer_id=spec.tokenizer_id,
            neural_architecture_version=mem_cfg.architecture_version,
            adapter_checkpoint_id=None,
            slow_memory_checkpoint_id=self._slow_checkpoint_id,
            fast_memory_state_id=self._fast_state_id,
            injection_layers=tuple(spec.injection_layers),
            fusion_scale=float(spec.fusion_scale),
            dtype=spec.dtype,
            quantization=spec.quantization,
            hidden_size=spec.hidden_size,
            num_layers=spec.num_layers,
            mode=engine.mode,
        )
        self._metrics.model_load_ms = (time.perf_counter() - t0) * 1000.0
        self._state = NeuralRuntimeState.READY

    def _infer_inprocess(self, req: NeuralInferRequest) -> NeuralInferResult:
        assert self._engine is not None
        if self._cancel.is_set():
            self._metrics.cancel_count += 1
            raise NeuralRuntimeCancelled("inference cancelled")
        self._engine.set_mode(req.mode)
        t0 = time.perf_counter()
        forward = self._engine.forward(req.input_ids)
        latency = (time.perf_counter() - t0) * 1000.0
        if self._cancel.is_set():
            self._metrics.cancel_count += 1
            raise NeuralRuntimeCancelled("inference cancelled")
        # Convert logits to nested lists for transport stability when needed.
        logits = forward.logits
        try:
            logits = logits.detach().cpu().tolist()
        except Exception:  # noqa: BLE001
            pass
        fusion_ms = None
        if forward.fusion_events:
            # Diagnostics only — do not invent timings when hooks omit them.
            fusion_ms = None
        self._metrics.fusion_overhead_ms = fusion_ms
        return NeuralInferResult(
            request_id=req.request_id,
            mode=forward.mode,
            logits=logits,
            bypassed=forward.bypassed,
            base_checksum=forward.base_checksum,
            fusion_events=list(forward.fusion_events),
            latency_ms=latency,
        )

    def _refresh_identity_checkpoint_ids(self) -> None:
        if self._identity is None:
            return
        self._identity = NeuralRuntimeIdentity(
            protocol_version=self._identity.protocol_version,
            base_model_id=self._identity.base_model_id,
            base_model_fingerprint=self._identity.base_model_fingerprint,
            tokenizer_id=self._identity.tokenizer_id,
            neural_architecture_version=self._identity.neural_architecture_version,
            adapter_checkpoint_id=self._identity.adapter_checkpoint_id,
            slow_memory_checkpoint_id=self._slow_checkpoint_id,
            fast_memory_state_id=self._fast_state_id,
            injection_layers=self._identity.injection_layers,
            fusion_scale=self._identity.fusion_scale,
            dtype=self._identity.dtype,
            quantization=self._identity.quantization,
            hidden_size=self._identity.hidden_size,
            num_layers=self._identity.num_layers,
            mode=self._identity.mode,
        )

    def _identity_kwargs_from_dict(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        mode = raw.get("mode", NeuralMode.OFF)
        if isinstance(mode, str):
            mode = NeuralMode(mode)
        return {
            "protocol_version": int(raw["protocol_version"]),
            "base_model_id": str(raw["base_model_id"]),
            "base_model_fingerprint": str(raw["base_model_fingerprint"]),
            "tokenizer_id": raw.get("tokenizer_id"),
            "neural_architecture_version": str(raw["neural_architecture_version"]),
            "adapter_checkpoint_id": raw.get("adapter_checkpoint_id"),
            "slow_memory_checkpoint_id": raw.get("slow_memory_checkpoint_id"),
            "fast_memory_state_id": raw.get("fast_memory_state_id"),
            "injection_layers": tuple(int(x) for x in raw.get("injection_layers") or ()),
            "fusion_scale": float(raw.get("fusion_scale") or 0.0),
            "dtype": str(raw.get("dtype") or "float32"),
            "quantization": raw.get("quantization"),
            "hidden_size": int(raw["hidden_size"]),
            "num_layers": int(raw["num_layers"]),
            "mode": mode,
        }

    # --- subprocess isolation (training_worker-style) --------------------

    def _start_subprocess(self, cfg: NeuralRuntimeStartConfig) -> None:
        work = Path(cfg.work_dir) if cfg.work_dir else Path(os.environ.get("TMP", "/tmp")) / f"hades-neural-runtime-{os.getpid()}"
        work.mkdir(parents=True, exist_ok=True)
        self._work_dir = work
        worker = Path(__file__).resolve().parent / "runtime_worker.py"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [sys.executable, str(worker), "--work-dir", str(work)],
            cwd=str(worker.parent.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            close_fds=True,
            creationflags=creationflags,
        )
        # Handshake
        hello = self._rpc({"op": "ping"}, timeout_s=10.0)
        if hello.get("status") != "ok":
            raise NeuralRuntimeFailed("worker handshake failed", detail=hello)
        if cfg.auto_load_model:
            self.load_model(self._model_spec)

    def _rpc(self, message: dict[str, Any], *, timeout_s: float, ignore_dead: bool = False) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            if ignore_dead:
                return {"status": "dead"}
            raise NeuralRuntimeFailed("worker process missing")
        if self._process.poll() is not None:
            if ignore_dead:
                return {"status": "dead", "returncode": self._process.returncode}
            self._state = NeuralRuntimeState.FAILED
            raise NeuralRuntimeFailed(
                "worker process not alive",
                detail={"returncode": self._process.returncode},
            )
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        # Blocking readline with crude timeout via worker responsiveness.
        self._process.stdout.flush()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._process.poll() is not None:
                err = ""
                if self._process.stderr is not None:
                    try:
                        err = self._process.stderr.read() or ""
                    except Exception:  # noqa: BLE001
                        err = ""
                raise NeuralRuntimeFailed(
                    "worker exited during rpc",
                    detail={"returncode": self._process.returncode, "stderr": err[-2000:]},
                )
            # Non-blocking-ish: rely on line-buffered text mode.
            ready_line = self._process.stdout.readline()
            if ready_line:
                try:
                    payload = json.loads(ready_line)
                except json.JSONDecodeError as exc:
                    raise NeuralRuntimeFailed("invalid worker response", detail={"line": ready_line}) from exc
                if payload.get("ok") is False:
                    code = str(payload.get("code") or "neural_runtime_failed")
                    if code == "neural_checkpoint_incompatible":
                        raise NeuralCheckpointIncompatible(
                            str(payload.get("message") or "incompatible"),
                            detail=dict(payload.get("detail") or {}),
                        )
                    if code == "neural_runtime_cancelled":
                        raise NeuralRuntimeCancelled(str(payload.get("message") or "cancelled"))
                    if code == "neural_mode_unsupported":
                        raise NeuralModeUnsupported(
                            str(payload.get("message") or "unsupported"),
                            detail=dict(payload.get("detail") or {}),
                        )
                    raise NeuralRuntimeFailed(
                        str(payload.get("message") or "worker error"),
                        detail={"code": code, **dict(payload.get("detail") or {})},
                    )
                return dict(payload.get("result") or payload)
            time.sleep(0.01)
        raise NeuralRuntimeFailed("worker rpc timeout", detail={"op": message.get("op")})

    def _terminate_process(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
