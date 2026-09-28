"""Mechanical gate: heavy source-ingestion execution is worker-owned in production.

``inprocess_test`` may run inline ONLY when explicitly allowed for tests.
An innocent env typo (e.g. ``RUNNER=inprocess``) must never reactivate API-inline
parse/extract/OCR without the allow flag or an active pytest session.
"""

from __future__ import annotations

import os
import sys
from typing import Any

ALLOW_INPROCESS_ENV = "LEVIATHAN_SOURCE_INGESTION_ALLOW_INPROCESS_TEST"
RUNNER_ENV = "LEVIATHAN_SOURCE_INGESTION_RUNNER"

# Exact runner values that may request in-process drain (still require allow/pytest).
_INPROCESS_RUNNERS = frozenset({"inprocess_test", "inprocess"})


def pytest_session_active() -> bool:
    """True when running under pytest (fixture/session), not merely because pytest is installed."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and any(
        name.startswith("pytest") or name == "_pytest"
        for name in sys.modules
    )


def inprocess_execution_explicitly_allowed() -> bool:
    """Explicit operator/test opt-in for API-thread ingestion (never production default)."""
    raw = (os.environ.get(ALLOW_INPROCESS_ENV) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return pytest_session_active()


def normalize_runner_value(raw: str | None) -> str:
    """Canonicalize runner string.

    Production default is ``fabric``. Only the exact token ``inprocess_test``
    (or legacy ``inprocess`` when the allow gate is open) yields inprocess_test.
    Ambiguous aliases like ``thread`` / ``internal`` fail closed to fabric unless
    the allow gate is open.
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
        # Legacy aliases: only honor when tests/operators explicitly allow inline.
        if inprocess_execution_explicitly_allowed():
            return "inprocess_test"
        return "fabric"
    return "fabric"


def runner_requests_inprocess(runner: str | None) -> bool:
    return (runner or "").strip().lower() in _INPROCESS_RUNNERS


def allow_inprocess_execution(settings: Any | None = None) -> bool:
    """True only when both runner asks for inprocess AND the mechanical allow gate is open."""
    runner = None
    if settings is not None:
        runner = getattr(settings, "runner", None)
    if runner is None:
        runner = normalize_runner_value(os.environ.get(RUNNER_ENV))
    if not runner_requests_inprocess(str(runner)):
        return False
    return inprocess_execution_explicitly_allowed()


def refuse_inline_ingestion(*, reason: str = "worker_required") -> None:
    """Raise the typed unavailable error used when API must not parse inline."""
    from Data.modules.research.types import ResearchError

    raise ResearchError(
        "SOURCE_INGESTION_UNAVAILABLE",
        "Source ingestion must execute on the source_ingestion worker; "
        f"inline API execution refused ({reason})",
        http_status=503,
        details={"reason": reason, "execution_owner": "source_ingestion"},
    )
