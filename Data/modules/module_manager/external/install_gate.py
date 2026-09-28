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
    """True only for explicit TEST-ONLY sync install (never production)."""
    raw = (os.environ.get(ALLOW_SYNC_TEST_ENV) or "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return False
    return pytest_session_active()
