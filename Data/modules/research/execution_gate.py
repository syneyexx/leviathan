"""Mechanical gate: heavy Research execution is worker-owned in production.

Mirrors Source Ingestion's execution gate. FastAPI may validate/authorize/enqueue
only. In-process heavy execution is allowed solely under an explicit
``inprocess_test`` mechanical allow (pytest session or env opt-in).

Fail-closed rules:
- worker-settings / configuration exceptions ⇒ treat as external required
- external mode + JobRuntime missing ⇒ typed unavailable (never ``_spawn_run``)
- UNKNOWN worker availability never becomes AVAILABLE
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


ALLOW_INPROCESS_ENV = "LEVIATHAN_RESEARCH_ALLOW_INPROCESS_TEST"
RUNNER_ENV = "LEVIATHAN_RESEARCH_RUNNER"
EXTERNALIZE_ENV = "LEVIATHAN_WORKERS_EXTERNALIZE_API"

ExecutionMode = Literal["external", "inprocess_test"]


class WorkerMeasuredState(str, Enum):
    """Physical research-pool measurement — independent of enqueue permission."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"
    NOT_MEASURED = "NOT_MEASURED"


@dataclass(frozen=True)
class ResearchWorkerAvailability:
    """Separate enqueue permission from measured worker presence."""

    can_enqueue: bool
    worker_state: WorkerMeasuredState
    worker_measured: bool
    wait_reason: str | None = None
    details: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "can_enqueue": self.can_enqueue,
            "worker_state": self.worker_state.value,
            "worker_measured": self.worker_measured,
            "wait_reason": self.wait_reason,
            "details": dict(self.details or {}),
        }


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


def _env_truthy(raw: str | None) -> bool | None:
    value = (raw or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def normalize_research_runner(raw: str | None) -> ExecutionMode | None:
    """Return explicit runner mode, or None when unset/ambiguous."""
    value = (raw or "").strip().lower()
    if not value:
        return None
    if value in {"fabric", "external", "worker", "process"}:
        return "external"
    if value == "inprocess_test":
        return "inprocess_test"
    if value in {"inprocess", "in-process", "internal", "thread"}:
        if inprocess_execution_explicitly_allowed():
            return "inprocess_test"
        return "external"
    return "external"


def resolve_execution_mode() -> ExecutionMode:
    """Canonical Research execution environment.

    Fail-closed: configuration/settings probe failures ⇒ ``external``.
    Explicit ``LEVIATHAN_WORKERS_EXTERNALIZE_API=0`` with allow gate ⇒ inprocess_test.
    """
    ext = _env_truthy(os.environ.get(EXTERNALIZE_ENV))
    if ext is True:
        return "external"
    if ext is False and inprocess_execution_explicitly_allowed():
        return "inprocess_test"
    if ext is False:
        # Explicitly disabled externalization outside test allow → still external
        # unless a domain runner asks for inprocess_test under the allow gate.
        runner = normalize_research_runner(os.environ.get(RUNNER_ENV))
        if runner == "inprocess_test" and inprocess_execution_explicitly_allowed():
            return "inprocess_test"
        # Historical tests set EXTERNALIZE=0 without the allow env; honor pytest.
        if pytest_session_active():
            return "inprocess_test"
        return "external"

    runner = normalize_research_runner(os.environ.get(RUNNER_ENV))
    if runner is not None:
        return runner

    for key in (
        "LEVIATHAN_SOURCE_INGESTION_RUNNER",
        "LEVIATHAN_DATASET_JOBS_RUNNER",
    ):
        sibling = normalize_research_runner(os.environ.get(key))
        if sibling == "external":
            return "external"

    try:
        from Data.modules.workers.settings import load_worker_settings

        if bool(load_worker_settings().externalize_api_runners):
            return "external"
    except Exception:  # noqa: BLE001 — fail closed
        return "external"

    # No explicit externalization signal. Under pytest allow inprocess; otherwise
    # production-safe default is external (JobRuntime path).
    if inprocess_execution_explicitly_allowed():
        return "inprocess_test"
    return "external"


def runners_externalized() -> bool:
    """True when Research heavy work must not run in the API process."""
    return resolve_execution_mode() == "external"


def allow_inprocess_research_execution() -> bool:
    """True only for mechanically gated test/inprocess mode."""
    return resolve_execution_mode() == "inprocess_test"


def refuse_inline_research(*, reason: str, capability: str | None = None) -> None:
    from Data.modules.research.types import ResearchError

    details: dict[str, Any] = {
        "reason": reason,
        "execution_owner": "research_worker",
        "execution_mode": resolve_execution_mode(),
    }
    if capability:
        details["capability"] = capability
    raise ResearchError(
        "RESEARCH_RUNTIME_UNAVAILABLE",
        "Research heavy execution requires JobRuntime + research worker; "
        f"inline API execution refused ({reason})",
        http_status=503,
        details=details,
    )


def require_job_runtime_for_external(
    job_runtime: Any | None,
    *,
    capability: str,
    reason: str = "job_runtime_unbound",
) -> None:
    """When external mode is active, JobRuntime must be bound before enqueue."""
    if allow_inprocess_research_execution():
        return
    if job_runtime is None:
        refuse_inline_research(reason=reason, capability=capability)


def probe_research_worker_availability(
    *,
    db_path: Any | None = None,
    runners_are_external: bool | None = None,
) -> ResearchWorkerAvailability:
    """Measure research pool health without conflating UNKNOWN and AVAILABLE.

    ``can_enqueue`` may still be true when the kernel can durably queue work while
    physical workers are UNAVAILABLE or UNKNOWN — callers decide wait_reason.
    """
    external = (
        runners_externalized() if runners_are_external is None else bool(runners_are_external)
    )
    try:
        from Data.modules.workers.protocol import WorkerInstanceState
        from Data.modules.workers.registry import WorkerRegistry
        from Data.modules.workers.settings import load_worker_settings

        wsettings = load_worker_settings()
        count = int((wsettings.pool_counts or {}).get("research", 0) or 0)
        if not wsettings.enabled:
            return ResearchWorkerAvailability(
                can_enqueue=True,
                worker_state=WorkerMeasuredState.DISABLED,
                worker_measured=True,
                wait_reason="QUEUED — waiting for research worker (workers disabled)",
                details={"workers_enabled": False, "pool_count": count},
            )
        if count <= 0:
            return ResearchWorkerAvailability(
                can_enqueue=True,
                worker_state=WorkerMeasuredState.UNAVAILABLE,
                worker_measured=True,
                wait_reason="QUEUED — waiting for research worker (pool count 0)",
                details={"workers_enabled": True, "pool_count": count},
            )
        if not external:
            return ResearchWorkerAvailability(
                can_enqueue=True,
                worker_state=WorkerMeasuredState.NOT_MEASURED,
                worker_measured=False,
                wait_reason=None,
                details={"execution_mode": "inprocess_test", "pool_count": count},
            )
        if db_path is None:
            return ResearchWorkerAvailability(
                can_enqueue=True,
                worker_state=WorkerMeasuredState.UNKNOWN,
                worker_measured=False,
                wait_reason="worker availability probe skipped (no db_path)",
                details={"pool_count": count},
            )
        registry = WorkerRegistry(db_path)
        registry.initialize()
        rows = registry.list(pool_id="research")
        live = [
            r
            for r in rows
            if getattr(r, "state", None)
            in {
                WorkerInstanceState.READY,
                WorkerInstanceState.BUSY,
            }
        ]
        if not live:
            return ResearchWorkerAvailability(
                can_enqueue=True,
                worker_state=WorkerMeasuredState.UNAVAILABLE,
                worker_measured=True,
                wait_reason="QUEUED — waiting for research worker",
                details={"pool_count": count, "registered_live": 0},
            )
        return ResearchWorkerAvailability(
            can_enqueue=True,
            worker_state=WorkerMeasuredState.AVAILABLE,
            worker_measured=True,
            wait_reason=None,
            details={"pool_count": count, "registered_live": len(live)},
        )
    except Exception as exc:  # noqa: BLE001 — never promote UNKNOWN→AVAILABLE
        return ResearchWorkerAvailability(
            can_enqueue=True,
            worker_state=WorkerMeasuredState.UNKNOWN,
            worker_measured=False,
            wait_reason="worker availability probe failed",
            details={
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            },
        )
