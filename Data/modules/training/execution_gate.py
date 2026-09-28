"""Mechanical gate: trainer subprocess ownership is training_control-owned.

FastAPI may validate/plan/create durable jobs and enqueue ``training.control``.
It must never Popen a production trainer or run heavy integrity/dataset hashing
inline when externalization is enabled.
"""

from __future__ import annotations

import os
import sys
from typing import Any


ALLOW_INLINE_ENV = "LEVIATHAN_TRAINING_ALLOW_INLINE_TEST"
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
    if not workers_externalize_enabled(settings):
        return False
    return not inline_execution_explicitly_allowed()


def allow_trainer_ownership(*, settings: Any | None = None) -> bool:
    """True when this process may own a trainer Popen handle."""
    from Data.modules.execution.workload import running_in_worker_process

    if running_in_worker_process():
        pool = (os.environ.get("LEVIATHAN_WORKER_POOL") or "").strip()
        return pool in {"", "training_control"}
    return not production_requires_external(settings)


class TrainingExecutionGateError(RuntimeError):
    """Raised when production API attempts trainer ownership or heavy inline scans."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = 503
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        return {"error": self.message, "details": self.details}


def refuse_inline_trainer(*, reason: str = "worker_required") -> None:
    raise TrainingExecutionGateError(
        "Trainer subprocess ownership must execute on the training_control "
        f"singleton worker; inline API spawn refused ({reason})",
        details={
            "reason": reason,
            "execution_owner": "training_control",
            "code": "TRAINING_WORKER_UNAVAILABLE",
        },
    )


def refuse_inline_heavy_scan(*, reason: str = "worker_required") -> None:
    raise TrainingExecutionGateError(
        "Heavy training integrity/dataset hashing must execute on "
        f"training_control; inline API scan refused ({reason})",
        details={
            "reason": reason,
            "execution_owner": "training_control",
            "code": "TRAINING_WORKER_UNAVAILABLE",
        },
    )
