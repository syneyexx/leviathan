"""Mechanical gate: heavy Coding execution is worker-owned in production.

``inprocess_test`` may run inline ONLY when explicitly allowed for tests.
An innocent env typo (e.g. ``RUNNER=inprocess``) must never reactivate
API-owned CodingWorker daemon threads or session-store claim fallbacks.
"""

from __future__ import annotations

import os
import sys
from typing import Any

ALLOW_INPROCESS_ENV = "LEVIATHAN_CODING_ALLOW_INPROCESS_TEST"
RUNNER_ENV = "LEVIATHAN_CODING_RUNNER"

_INPROCESS_RUNNERS = frozenset({"inprocess_test", "inprocess"})


def pytest_session_active() -> bool:
    """True when running under pytest (fixture/session), not merely because pytest is installed."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and any(
        name.startswith("pytest") or name == "_pytest" for name in sys.modules
    )


def inprocess_execution_explicitly_allowed() -> bool:
    """Explicit operator/test opt-in for API-thread coding (never production default)."""
    raw = (os.environ.get(ALLOW_INPROCESS_ENV) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return pytest_session_active()


def normalize_runner_value(raw: str | None) -> str:
    """Canonicalize runner string.

    Production default is ``fabric``. Only the exact token ``inprocess_test``
    (or legacy ``inprocess`` when the allow gate is open) yields inprocess_test.
    """
    value = (raw or "").strip().lower()
    if not value:
        return "fabric"
    if value in {"fabric", "external", "worker", "process"}:
        return "fabric"
    if value in {"standalone", "standalone_legacy", "legacy_external", "legacy"}:
        return "standalone_legacy"
    if value in {"none", "off", "disabled"}:
        return "disabled"
    if value == "inprocess_test":
        return "inprocess_test"
    if value in {"inprocess", "in-process", "internal", "thread"}:
        if inprocess_execution_explicitly_allowed():
            return "inprocess_test"
        return "fabric"
    return "fabric"


def runner_requests_inprocess(runner: str | None) -> bool:
    return (runner or "").strip().lower() in _INPROCESS_RUNNERS


def allow_inprocess_execution(settings: Any | None = None) -> bool:
    """True only when the mechanical allow gate is open AND inprocess is intended.

    Under pytest, an *unset* runner defaults to allowing the test harness
    (drain / process_next / explicit run_round). An explicit ``fabric`` runner
    under pytest still refuses in-process claim paths so architecture tests
    can prove fail-closed behavior.
    """
    if not inprocess_execution_explicitly_allowed():
        return False
    runner = None
    raw_env = os.environ.get(RUNNER_ENV)
    if settings is not None:
        coding = getattr(settings, "coding", None)
        runner = getattr(coding, "runner", None) if coding is not None else None
        if runner is None:
            runner = getattr(settings, "runner", None)
    if runner is None:
        if raw_env is None or str(raw_env).strip() == "":
            # Unset: under pytest allow test harness; otherwise fabric.
            return pytest_session_active()
        runner = normalize_runner_value(raw_env)
    if runner_requests_inprocess(str(runner)):
        return True
    return False


def runners_externalized() -> bool:
    """True when Coding must not own API daemon threads."""
    ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
    if ext in {"1", "true", "yes", "on"}:
        return True
    if ext in {"0", "false", "no", "off"}:
        return False
    coding_runner = normalize_runner_value(os.environ.get(RUNNER_ENV))
    if coding_runner in {"fabric", "standalone_legacy"}:
        return True
    try:
        from Data.modules.workers.settings import load_worker_settings

        return bool(load_worker_settings().externalize_api_runners)
    except Exception:  # noqa: BLE001
        # Default fail-closed to external when uncertain in production-like installs.
        return True


def refuse_inline_coding(*, reason: str = "worker_required") -> None:
    """Raise the typed unavailable error used when API must not run CodingLoop inline."""
    from Data.modules.coding.types import CodingError

    raise CodingError(
        "CODING_EXECUTION_UNAVAILABLE",
        "Coding execution must run on the coding worker; "
        f"inline API execution refused ({reason})",
        http_status=503,
        details={"reason": reason, "execution_owner": "coding"},
    )
