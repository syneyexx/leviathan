"""Isolated Neural Runtime worker process (Phase 9).

Heavy ML imports occur only inside this process. Host HADES (FastAPI/SQLite)
communicates via JSON lines on stdin/stdout. Cancellation uses cancel.requested
in the work directory (same pattern as training_worker).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Ensure backend package root is importable when launched as a script.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _cancel_requested(work_dir: Path) -> bool:
    return (work_dir / "cancel.requested").is_file()


def _reply(ok: bool, result: dict[str, Any] | None = None, **error: Any) -> None:
    if ok:
        sys.stdout.write(json.dumps({"ok": True, "result": result or {}}, ensure_ascii=False) + "\n")
    else:
        payload = {"ok": False, **error}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES Neural Runtime worker")
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    work_dir = Path(args.work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Lazy import after process start.
    from neural.checkpoint import SCHEMA_VERSION, NeuralMemoryCheckpointStore
    from neural.config import NeuralMemoryConfig
    from neural.contracts import (
        NEURAL_RUNTIME_PROTOCOL_VERSION,
        NeuralInferRequest,
        NeuralMode,
        NeuralModelSpec,
        NeuralRuntimeIdentity,
    )
    from neural.errors import (
        NeuralCheckpointIncompatible,
        NeuralModeUnsupported,
        NeuralRuntimeCancelled,
    )
    from neural.runtime import NeuralModelRuntime
    from neural.runtime_compat import validate_memory_checkpoint_manifest
    from neural.toy_transformer import ToyTransformerConfig

    engine: NeuralModelRuntime | None = None
    identity: NeuralRuntimeIdentity | None = None
    base_checksum: str | None = None
    mode = NeuralMode.OFF
    memory_loaded = False
    slow_checkpoint_id: str | None = None
    cancelled = False

    def build_identity(spec: NeuralModelSpec, checksum: str, eng: NeuralModelRuntime) -> NeuralRuntimeIdentity:
        return NeuralRuntimeIdentity(
            protocol_version=NEURAL_RUNTIME_PROTOCOL_VERSION,
            base_model_id=spec.model_id,
            base_model_fingerprint=checksum,
            tokenizer_id=spec.tokenizer_id,
            neural_architecture_version=eng.memory.config.architecture_version,
            adapter_checkpoint_id=None,
            slow_memory_checkpoint_id=slow_checkpoint_id,
            fast_memory_state_id=None,
            injection_layers=tuple(spec.injection_layers),
            fusion_scale=float(spec.fusion_scale),
            dtype=spec.dtype,
            quantization=spec.quantization,
            hidden_size=spec.hidden_size,
            num_layers=spec.num_layers,
            mode=eng.mode,
        )

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _reply(False, code="neural_runtime_failed", message="invalid json")
            continue
        op = str(message.get("op") or "")
        try:
            if op == "ping":
                _reply(True, {"status": "ok", "protocol_version": NEURAL_RUNTIME_PROTOCOL_VERSION})
                continue
            if op == "cancel":
                cancelled = True
                (work_dir / "cancel.requested").write_text("cancel\n", encoding="utf-8")
                _reply(True, {"cancelled": True})
                continue
            if op == "stop":
                engine = None
                identity = None
                _reply(True, {"stopped": True})
                return 0
            if op == "crash_test":
                # Intentional hard exit for containment tests.
                sys.stderr.write("intentional crash_test\n")
                sys.stderr.flush()
                os_exit = getattr(__import__("os"), "_exit")
                os_exit(99)
            if op == "load_model":
                spec = NeuralModelSpec.from_dict(dict(message.get("spec") or {}))
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
                    mode=mode,
                    injection_layers=list(spec.injection_layers),
                    fusion_scale=spec.fusion_scale,
                    device=spec.device,
                )
                base_checksum = engine.verify_base_frozen()
                identity = build_identity(spec, base_checksum, engine)
                memory_loaded = False
                cancelled = False
                cancel_path = work_dir / "cancel.requested"
                if cancel_path.exists():
                    cancel_path.unlink()
                _reply(True, {"identity": identity.to_dict()})
                continue
            if op == "unload_model":
                engine = None
                identity = None
                base_checksum = None
                memory_loaded = False
                _reply(True, {"unloaded": True})
                continue
            if op == "load_checkpoint":
                if engine is None or identity is None:
                    _reply(False, code="neural_runtime_not_ready", message="model not loaded")
                    continue
                store_root = Path(str(message["store_root"]))
                checkpoint_id = message.get("checkpoint_id")
                candidate = bool(message.get("candidate", False))
                store = NeuralMemoryCheckpointStore(store_root)
                if checkpoint_id is None:
                    pointer_name = "latest_candidate.json" if candidate else "latest.json"
                    pointer = json.loads((store.root / pointer_name).read_text(encoding="utf-8"))
                    checkpoint_id = str(pointer["checkpoint_id"])
                    candidate = bool(pointer.get("candidate", candidate))
                manifest_path = (
                    store.root / ("candidate" if candidate else "good") / str(checkpoint_id) / "manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                validate_memory_checkpoint_manifest(
                    manifest,
                    expected_hidden_size=identity.hidden_size,
                    expected_architecture_version=identity.neural_architecture_version,
                    expected_schema_version=SCHEMA_VERSION,
                )
                memory = store.load(
                    str(checkpoint_id),
                    candidate=candidate,
                    expected_config=engine.memory.config,
                )
                engine.memory = memory
                slow_checkpoint_id = str(checkpoint_id)
                memory_loaded = True
                identity = build_identity(
                    NeuralModelSpec(
                        model_id=identity.base_model_id,
                        hidden_size=identity.hidden_size,
                        num_layers=identity.num_layers,
                        injection_layers=identity.injection_layers,
                        fusion_scale=identity.fusion_scale,
                        dtype=identity.dtype,
                        quantization=identity.quantization,
                        tokenizer_id=identity.tokenizer_id,
                    ),
                    base_checksum or identity.base_model_fingerprint,
                    engine,
                )
                _reply(True, {"checkpoint_id": slow_checkpoint_id, "memory_loaded": memory_loaded})
                continue
            if op == "infer":
                if engine is None or identity is None:
                    _reply(False, code="neural_runtime_not_ready", message="model not loaded")
                    continue
                if cancelled or _cancel_requested(work_dir):
                    cancelled = False
                    _reply(False, code="neural_runtime_cancelled", message="inference cancelled")
                    continue
                req = NeuralInferRequest.from_dict(dict(message.get("request") or {}))
                if req.mode is NeuralMode.LEARN:
                    raise NeuralModeUnsupported("LEARN disabled in worker")
                engine.set_mode(req.mode)
                t0 = time.perf_counter()
                forward = engine.forward(req.input_ids)
                latency = (time.perf_counter() - t0) * 1000.0
                if _cancel_requested(work_dir):
                    _reply(False, code="neural_runtime_cancelled", message="inference cancelled")
                    continue
                logits = forward.logits.detach().cpu().tolist()
                _reply(
                    True,
                    {
                        "request_id": req.request_id,
                        "mode": forward.mode.value,
                        "logits": logits,
                        "bypassed": forward.bypassed,
                        "base_checksum": forward.base_checksum,
                        "fusion_events": list(forward.fusion_events),
                        "latency_ms": latency,
                        "cancelled": False,
                    },
                )
                continue
            if op == "prove_base_frozen":
                if engine is None:
                    _reply(False, code="neural_runtime_not_ready", message="model not loaded")
                    continue
                checksum = engine.verify_base_frozen()
                _reply(True, {"base_checksum": checksum})
                continue
            if op == "health":
                _reply(
                    True,
                    {
                        "process_alive": True,
                        "runtime_initialized": engine is not None,
                        "base_model_loaded": engine is not None,
                        "memory_loaded": memory_loaded,
                        "identity": identity.to_dict() if identity else None,
                    },
                )
                continue
            _reply(False, code="neural_runtime_failed", message=f"unknown op: {op}")
        except NeuralCheckpointIncompatible as exc:
            _reply(False, code=exc.code, message=str(exc), detail=exc.detail)
        except NeuralModeUnsupported as exc:
            _reply(False, code=exc.code, message=str(exc), detail=exc.detail)
        except NeuralRuntimeCancelled as exc:
            _reply(False, code=exc.code, message=str(exc), detail=exc.detail)
        except Exception as exc:  # noqa: BLE001
            _reply(
                False,
                code="neural_runtime_failed",
                message=str(exc),
                detail={"traceback": traceback.format_exc()[-2000:]},
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
