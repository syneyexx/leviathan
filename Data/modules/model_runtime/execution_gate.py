"""Mechanical gate: managed serving lifecycle is worker-owned in production.

FastAPI may enqueue model_runtime jobs and relay HTTP to a managed local
endpoint. It must never own Popen handles or run inference compute / probes /
benchmarks / large artifact hashing inline when externalization is enabled.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

ALLOW_INLINE_ENV = "LEVIATHAN_MODEL_RUNTIME_ALLOW_INLINE_TEST"
EXTERNALIZE_API_ENV = "LEVIATHAN_WORKERS_EXTERNALIZE_API"


def pytest_session_active() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and any(
        name.startswith("pytest") or name == "_pytest" for name in sys.modules
    )


def inline_execution_explicitly_allowed() -> bool:
    raw = (os.environ.get(ALLOW_INLINE_ENV) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return pytest_session_active()


def workers_externalize_enabled(settings: Any | None = None) -> bool:
    if settings is not None:
        workers = getattr(settings, "workers", None)
        if workers is not None:
            enabled = bool(getattr(workers, "enabled", True))
            externalize = bool(getattr(workers, "externalize_api_runners", True))
            return enabled and externalize
    try:
        from Data.modules.execution.workload import externalize_api_enabled

        return bool(externalize_api_enabled())
    except Exception:  # noqa: BLE001
        raw = (os.environ.get(EXTERNALIZE_API_ENV) or "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}


def production_requires_external(settings: Any | None = None) -> bool:
    """True when API must enqueue — never run managed serving lifecycle inline."""
    if not workers_externalize_enabled(settings):
        return False
    return not inline_execution_explicitly_allowed()


def allow_process_ownership() -> bool:
    """True when this process may own ServingSupervisor Popen handles."""
    from Data.modules.execution.workload import running_in_worker_process

    if running_in_worker_process():
        pool = (os.environ.get("LEVIATHAN_WORKER_POOL") or "").strip()
        # Only the singleton model_runtime pool owns managed serving children.
        # Empty pool: legacy/test workers that set LEVIATHAN_WORKER_ID only.
        return pool in {"", "model_runtime"}
    # API / non-worker: only when externalization is off or test allow is set.
    return not production_requires_external()


def refuse_inline_serving(*, reason: str = "worker_required") -> None:
    from Data.modules.models.errors import MODEL_RUNTIME_UNAVAILABLE, ModelControlError

    raise ModelControlError(
        code=MODEL_RUNTIME_UNAVAILABLE,
        message=(
            "Managed model serving lifecycle must execute on the model_runtime "
            f"singleton worker; inline API ownership refused ({reason})"
        ),
        retryable=True,
        http_status=503,
        details={
            "reason": reason,
            "execution_owner": "model_runtime",
        },
    )


def resolve_externalize_fn(
    externalize_fn: Callable[[], bool] | None = None,
    *,
    settings: Any | None = None,
) -> Callable[[], bool]:
    if externalize_fn is not None:
        return externalize_fn
    return lambda: workers_externalize_enabled(settings)


# --- Wave compatibility aliases (927bacda naming) ---


def runners_externalized(settings: Any | None = None) -> bool:
    """Alias for ``workers_externalize_enabled`` (wave / managed_adapter)."""
    return workers_externalize_enabled(settings)


def allow_inline_serving_for_tests() -> bool:
    """True under pytest / explicit inline allow — never production FastAPI."""
    return inline_execution_explicitly_allowed()
