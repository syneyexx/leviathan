"""Mechanical gate: heavy Knowledge execution is worker-owned in production.

Mirrors source_ingestion.execution_gate — production never silently falls back
to FastAPI-inline scan/chunk/embed. Test-only inline paths require an explicit
allow gate or an active pytest session.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

ALLOW_INLINE_ENV = "LEVIATHAN_KNOWLEDGE_ALLOW_INLINE_TEST"
# Canonical worker externalization (shared with ExecutionGateway / Workload).
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
    """Canonical externalization predicate — NOT evaluation-specific naming."""
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


def production_requires_external() -> bool:
    """True when API must enqueue — never run heavy Knowledge inline."""
    if not workers_externalize_enabled():
        return False
    # Even with externalize on, explicit test allow may use store helpers directly.
    return not inline_execution_explicitly_allowed()


def refuse_inline_knowledge(*, reason: str = "worker_required") -> None:
    """Raise typed unavailable when API must not run heavy Knowledge inline."""
    from fastapi import HTTPException

    raise HTTPException(
        status_code=503,
        detail={
            "error": "KNOWLEDGE_PREPARE_UNAVAILABLE",
            "message": (
                "Knowledge preparation must execute on knowledge_prepare / embedding / "
                f"db_commit workers; inline API execution refused ({reason})"
            ),
            "reason": reason,
            "execution_owner": "knowledge_prepare",
        },
    )


def resolve_externalize_fn(
    externalize_fn: Callable[[], bool] | None = None,
    *,
    settings: Any | None = None,
) -> Callable[[], bool]:
    """Prefer an injected predicate; fall back to canonical workers_externalize_enabled."""
    if externalize_fn is not None:
        return externalize_fn
    return lambda: workers_externalize_enabled(settings)
