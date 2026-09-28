"""Mechanical gate: heavy agent mission execution is worker-owned in production.

``inprocess_test`` may run missions inline ONLY when explicitly allowed for tests.
An innocent env typo must never reactivate FastAPI-inline mission bodies.
"""

from __future__ import annotations

import os
import sys


ALLOW_INPROCESS_ENV = "LEVIATHAN_AGENTS_ALLOW_INPROCESS_TEST"
RUNNER_ENV = "LEVIATHAN_AGENTS_RUNNER"


def pytest_session_active() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and any(
        name.startswith("pytest") or name == "_pytest" for name in sys.modules
    )


def inprocess_execution_explicitly_allowed() -> bool:
    raw = (os.environ.get(ALLOW_INPROCESS_ENV) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return pytest_session_active()


def _explicit_externalize() -> bool | None:
    """Return True/False when env forces externalization; None if unset."""
    ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
    if ext in {"1", "true", "yes", "on"}:
        return True
    if ext in {"0", "false", "no", "off"}:
        return False
    raw = (os.environ.get(RUNNER_ENV) or "").strip().lower()
    if raw in {"external", "worker", "process", "fabric"}:
        return True
    if raw in {"inprocess_test", "inprocess", "thread", "api"}:
        return False
    return None


def runners_externalized() -> bool:
    """True when production should enqueue agent.advance (default).

    Under pytest (or explicit allow), unit tests may run mission bodies inline
    unless EXTERNALIZE/RUNNER explicitly forces external mode.
    """
    forced = _explicit_externalize()
    if forced is True:
        return True
    if forced is False:
        return False
    if inprocess_execution_explicitly_allowed():
        # Test harness without Worker Fabric: domain logic may execute inline.
        return False
    try:
        from Data.modules.workers.settings import load_worker_settings

        return bool(load_worker_settings().externalize_api_runners)
    except Exception:  # noqa: BLE001
        return True


def allow_inprocess_mission_execution() -> bool:
    """True only for explicit test/dev in-process mission bodies."""
    if not inprocess_execution_explicitly_allowed():
        return False
    forced = _explicit_externalize()
    if forced is True:
        return False
    return True
