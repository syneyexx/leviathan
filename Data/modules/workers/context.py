"""Typed worker execution context — canonical contract for all pool handlers.

Handlers must declare required dependencies. The runtime validates them before
invocation. Do not sprinkle ``ctx.get("settings")`` as a substitute for a contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


class WorkerContextError(RuntimeError):
    """Raised when a required worker dependency is missing or invalid."""

    def __init__(self, message: str, *, missing: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.missing = list(missing or [])


# Keys always present after ``build_minimal_job_context`` (production workers).
REQUIRED_BASE_KEYS: tuple[str, ...] = (
    "settings",
    "job_store",
    "job_runtime",
    "gateway",
    "function_runtime",
    "artifact_store",
    "registry",
    "admission",
    "worker_settings",
)

# Loop-critical keys for undeclared handlers / TEST-ONLY patched contexts.
# function_runtime + artifact_store remain required at production construction
# but are not forced on every custom handler that never uses them.
REQUIRED_RUNTIME_KEYS: tuple[str, ...] = (
    "settings",
    "job_store",
    "job_runtime",
    "gateway",
    "registry",
    "admission",
    "worker_settings",
)

# Keys added per-job by ``run_pool_loop`` before handler invocation.
PER_JOB_KEYS: tuple[str, ...] = (
    "worker_id",
    "lease_ttl_seconds",
    "lease_lost",
    "job_cancel_fence",
    "job_cancel_check",
)


@dataclass(frozen=True)
class WorkerContextRequirements:
    """Declare what a handler needs from the execution context."""

    required: tuple[str, ...] = REQUIRED_RUNTIME_KEYS
    optional: tuple[str, ...] = ()

    def validate(self, ctx: Mapping[str, Any]) -> list[str]:
        missing = [key for key in self.required if key not in ctx or ctx[key] is None]
        return missing


# Common requirement profiles for pool handlers.
REQUIRES_PRODUCTION = WorkerContextRequirements(required=REQUIRED_BASE_KEYS)
REQUIRES_BASE = WorkerContextRequirements(required=REQUIRED_RUNTIME_KEYS)
REQUIRES_SETTINGS = WorkerContextRequirements(required=("settings", "job_store"))
REQUIRES_MAINTENANCE = WorkerContextRequirements(
    required=("job_store", "admission", "registry"),
    optional=("settings", "worker_id", "lease_ttl_seconds"),
)
REQUIRES_SETTINGS_JOB = WorkerContextRequirements(
    required=("settings", "job_store", "job_runtime"),
)


@dataclass
class WorkerExecutionContext:
    """Validated view over the worker ctx mapping.

    Production handlers may keep using the underlying dict for backward
    compatibility; construction/validation goes through this type.
    """

    raw: dict[str, Any]
    requirements: WorkerContextRequirements = field(default_factory=lambda: REQUIRES_BASE)

    def __post_init__(self) -> None:
        missing = self.requirements.validate(self.raw)
        if missing:
            raise WorkerContextError(
                f"worker context missing required dependencies: {', '.join(missing)}",
                missing=missing,
            )

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.raw or self.raw[key] is None:
            raise WorkerContextError(
                f"worker context missing required dependency: {key}",
                missing=[key],
            )
        return self.raw[key]

    @property
    def settings(self) -> Any:
        return self.require("settings")

    @property
    def job_store(self) -> Any:
        return self.require("job_store")

    @property
    def job_runtime(self) -> Any:
        return self.require("job_runtime")

    @property
    def worker_id(self) -> str:
        return str(self.raw.get("worker_id") or "")

    def as_dict(self) -> dict[str, Any]:
        return self.raw


def validate_worker_context(
    ctx: Mapping[str, Any],
    *,
    requirements: WorkerContextRequirements | None = None,
) -> dict[str, Any]:
    """Validate ``ctx`` against requirements; return the same mapping on success."""
    req = requirements or REQUIRES_BASE
    missing = req.validate(ctx)
    if missing:
        raise WorkerContextError(
            f"worker context missing required dependencies: {', '.join(missing)}",
            missing=missing,
        )
    return dict(ctx)


def ensure_handler_context(
    ctx: Mapping[str, Any],
    *,
    requirements: WorkerContextRequirements,
) -> dict[str, Any]:
    """Validate at handler entry — typed error, never KeyError for declared deps."""
    return validate_worker_context(ctx, requirements=requirements)
