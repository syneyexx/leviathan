"""Install execution gate — production never runs pip/npm/venv on the API thread."""

from __future__ import annotations

import os
import sys


ALLOW_SYNC_TEST_ENV = "LEVIATHAN_MODULE_ALLOW_SYNC_INSTALL_TEST"


def pytest_session_active() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and any(
        name.startswith("pytest") or name == "_pytest" for name in sys.modules
    )


def allow_sync_install_for_tests() -> bool:
    """True only inside a test harness.

    Production never allows sync install even when the feature flag is on.
    Under pytest, routes may enable sync via ``allow_sync_install_fallback``
    for deterministic fixtures; the explicit env is an additional opt-in.
    """
    if not pytest_session_active():
        return False
    raw = (os.environ.get(ALLOW_SYNC_TEST_ENV) or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    # pytest session + route flag is sufficient for TEST-ONLY sync paths.
    return True
