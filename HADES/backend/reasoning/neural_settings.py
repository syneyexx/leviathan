"""Neural settings + helpers for real HADES integration (Phase 10/11).

Defaults keep conventional HADES behavior (Neural Mode OFF, dual memory off).
Lazy-imports neural packages so missing torch never breaks startup.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from reasoning.runtime_selection import NeuralRequirement, RuntimeSelectionRequest


def _env_map(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def resolve_neural_mode(settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None) -> str:
    settings = settings or {}
    raw = settings.get("neural_mode")
    if raw is None:
        raw = _env_map(env).get("HADES_NEURAL_MODE", "off")
    mode = str(raw or "off").strip().lower()
    if mode not in {"off", "shadow", "read", "learn"}:
        return "off"
    return mode


def resolve_neural_requirement(
    settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None
) -> NeuralRequirement:
    settings = settings or {}
    raw = settings.get("neural_requirement")
    if raw is None:
        raw = _env_map(env).get("HADES_NEURAL_REQUIREMENT", "off")
    value = str(raw or "off").strip().lower()
    try:
        return NeuralRequirement(value)
    except ValueError:
        return NeuralRequirement.OFF


def resolve_shadow_sample_rate(
    settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None
) -> float:
    settings = settings or {}
    raw = settings.get("neural_shadow_sample_rate")
    if raw is None:
        raw = _env_map(env).get("HADES_NEURAL_SHADOW_SAMPLE_RATE", "0")
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, rate))


def neural_allow(settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None) -> bool:
    """Master allow gate. Default False — neural never activates by accident."""
    settings = settings or {}
    if "neural_allow" in settings:
        return bool(settings.get("neural_allow"))
    raw = _env_map(env).get("HADES_NEURAL_ALLOW")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "on", "yes", "enabled"}


def dual_memory_enabled(settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None) -> bool:
    settings = settings or {}
    if "neural_dual_memory_enabled" in settings:
        return bool(settings.get("neural_dual_memory_enabled"))
    raw = _env_map(env).get("HADES_NEURAL_DUAL_MEMORY")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "on", "yes", "enabled"}


def neural_runtime_probe() -> dict[str, Any]:
    """Truthful capability probe without importing heavy modules when absent."""
    try:
        from neural.deps import neural_available, torch_info
    except Exception as exc:  # noqa: BLE001
        return {
            "allow_neural": False,
            "neural_available": False,
            "neural_ready": False,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_chat": False,
            "error": type(exc).__name__,
        }
    available = bool(neural_available())
    info = torch_info() if available else {"available": False, "cuda": False}
    return {
        "neural_available": available,
        # V2: inference-ready still needs torch for parametric memory; encoder is separate.
        "neural_ready": available,
        "supports_streaming": False,  # honest: Neural Runtime does not stream yet
        "supports_tools": False,  # honest: no tool-call protocol
        "supports_chat": available,  # research chat-shaped responses only
        "supports_neural_memory": available,
        "supports_shadow": available,
        "supports_read": available,
        "supports_learn": False,
        "supports_hidden_state_access": available,
        "production_encoder": "lm_studio_embedding",
        "toy_encoder": "test_only",
        "torch": info,
    }


def build_runtime_selection(
    settings: Mapping[str, Any] | None = None, *, env: Mapping[str, str] | None = None
) -> RuntimeSelectionRequest:
    probe = neural_runtime_probe()
    allow = neural_allow(settings, env=env)
    return RuntimeSelectionRequest(
        neural_mode=resolve_neural_mode(settings, env=env),
        neural_requirement=resolve_neural_requirement(settings, env=env),
        shadow_sample_rate=resolve_shadow_sample_rate(settings, env=env),
        neural_available=bool(probe.get("neural_available")),
        neural_ready=bool(probe.get("neural_ready")),
        allow_neural=allow,
    )


def make_toy_neural_chat_hook() -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Optional research Neural Runtime hook returning a chat-shaped dict.

    Returns None when torch/runtime cannot start. Never used when neural_mode=off.
    """
    probe = neural_runtime_probe()
    if not probe.get("neural_available"):
        return None
    try:
        from neural.contracts import NeuralInferRequest, NeuralMode, NeuralModelSpec
        from neural.runtime_lifecycle import NeuralRuntimeBoundary, NeuralRuntimeStartConfig
    except Exception:
        return None

    runtime = NeuralRuntimeBoundary()
    try:
        health = runtime.start(NeuralRuntimeStartConfig(model_spec=NeuralModelSpec(), mode=NeuralMode.OFF))
        if health.state.value != "ready":
            runtime.stop()
            return None
    except Exception:
        try:
            runtime.stop()
        except Exception:  # noqa: BLE001
            pass
        return None

    def _infer(payload: dict[str, Any]) -> dict[str, Any]:
        mode_raw = str((payload.get("_hades_neural_mode") or "read")).lower()
        mode = NeuralMode.READ if mode_raw == "read" else NeuralMode.SHADOW if mode_raw == "shadow" else NeuralMode.OFF
        # Derive a tiny token window from message text length — deterministic, local.
        text = ""
        for msg in payload.get("messages") or []:
            if isinstance(msg, dict):
                text += str(msg.get("content") or "")
        seed = sum(ord(ch) for ch in text[:64]) % 40 + 1
        ids = [[(seed + i) % 48 for i in range(8)]]
        result = runtime.infer(NeuralInferRequest(request_id="gateway", input_ids=ids, mode=mode))
        summary = (
            f"[neural_runtime research] mode={result.mode.value} bypassed={result.bypassed} "
            f"latency_ms={result.latency_ms:.2f}"
        )
        return {
            "choices": [{"message": {"role": "assistant", "content": summary}}],
            "model": "neural_toy_runtime",
            "mode": result.mode.value,
            "bypassed": result.bypassed,
            "base_checksum": result.base_checksum,
            "latency_ms": result.latency_ms,
            "fusion_events": list(result.fusion_events),
            "_hades_neural_research": True,
        }

    # Attach cleanup handle for tests/callers that want to stop the session.
    _infer._neural_runtime = runtime  # type: ignore[attr-defined]
    return _infer


def maybe_ingest_after_work_completion(
    store: Any,
    settings: Mapping[str, Any] | None = None,
    *,
    query: str = "",
    limit: int = 8,
) -> dict[str, Any] | None:
    """Fail-open post-task hook: verified experiences → ContinualLearningPipeline.

    No-ops when Neural is OFF. Never raises into Work completion.
    """
    try:
        from neural.experience_ingest import maybe_ingest_verified_experiences

        report = maybe_ingest_verified_experiences(
            store,
            settings,
            query=query,
            limit=limit,
        )
        return report.to_dict()
    except Exception:
        return None
