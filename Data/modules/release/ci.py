"""CI / release measurement vocabulary (Round 10).

Unavailable or skipped suites must never be counted as PASS.
Use NOT_APPLICABLE when a suite is intentionally out of scope for this
environment, and UNMEASURED when a required probe was not executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateMeasurement(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNMEASURED = "UNMEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def measurement_counts_as_success(state: GateMeasurement) -> bool:
    """Only PASS is success. NOT_APPLICABLE is scoped-out, not a green check."""
    return state == GateMeasurement.PASS


def measurement_blocks_release(state: GateMeasurement, *, severity: str) -> bool:
    if severity != "BLOCK":
        return False
    return state == GateMeasurement.FAIL


def ci_release_mode() -> bool:
    """True when LEVIATHAN_CI_RELEASE is enabled (Round 10 CI ship profile)."""
    import os

    raw = (os.environ.get("LEVIATHAN_CI_RELEASE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CiSuiteResult:
    suite_id: str
    name: str
    measurement: GateMeasurement
    detail: str
    command: str = ""
    exclude: tuple[str, ...] = ()
    exit_code: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "measurement": self.measurement.value,
            "detail": self.detail,
            "command": self.command,
            "exclude": list(self.exclude),
            "exit_code": self.exit_code,
            "truth": {
                "skipped_unavailable_is_not_success": True,
                "not_applicable_is_not_pass": self.measurement != GateMeasurement.PASS,
                "unmeasured_is_not_pass": self.measurement != GateMeasurement.PASS,
            },
        }


@dataclass
class CiPlan:
    """Declarative LEVIATHAN CI plan — excludes HADES/ and editor/ by policy."""

    suites: list[CiSuiteResult] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        measurements = [s.measurement for s in self.suites]
        passed = sum(1 for m in measurements if m == GateMeasurement.PASS)
        failed = sum(1 for m in measurements if m == GateMeasurement.FAIL)
        unmeasured = sum(1 for m in measurements if m == GateMeasurement.UNMEASURED)
        na = sum(1 for m in measurements if m == GateMeasurement.NOT_APPLICABLE)
        release_ok = failed == 0 and unmeasured == 0
        return {
            "suites": [s.public_dict() for s in self.suites],
            "summary": {
                "pass": passed,
                "fail": failed,
                "unmeasured": unmeasured,
                "not_applicable": na,
                "total": len(self.suites),
                "release_ok": release_ok,
            },
            "policy": {
                "exclude_hades": True,
                "exclude_editor": True,
                "scope": "Data/",
            },
            "truth": {
                "skipped_unavailable_is_not_success": True,
                "not_applicable_is_not_pass": True,
                "unmeasured_is_not_pass": True,
                "release_ready_is_not_production_certified": True,
                "hades_and_editor_out_of_scope": True,
            },
        }


def interpret_command_result(
    *,
    suite_id: str,
    name: str,
    command: str,
    exit_code: int | None,
    available: bool = True,
    applicable: bool = True,
    detail: str = "",
    exclude: tuple[str, ...] = ("HADES/", "editor/"),
) -> CiSuiteResult:
    """Map a CI command outcome to honest measurement semantics."""
    if not applicable:
        return CiSuiteResult(
            suite_id=suite_id,
            name=name,
            measurement=GateMeasurement.NOT_APPLICABLE,
            detail=detail or "not applicable in this environment",
            command=command,
            exclude=exclude,
            exit_code=exit_code,
        )
    if not available:
        return CiSuiteResult(
            suite_id=suite_id,
            name=name,
            measurement=GateMeasurement.UNMEASURED,
            detail=detail or "suite unavailable — not executed (UNMEASURED ≠ PASS)",
            command=command,
            exclude=exclude,
            exit_code=exit_code,
        )
    if exit_code is None:
        return CiSuiteResult(
            suite_id=suite_id,
            name=name,
            measurement=GateMeasurement.UNMEASURED,
            detail=detail or "no exit code recorded — UNMEASURED ≠ PASS",
            command=command,
            exclude=exclude,
            exit_code=None,
        )
    if exit_code == 0:
        return CiSuiteResult(
            suite_id=suite_id,
            name=name,
            measurement=GateMeasurement.PASS,
            detail=detail or "exit 0",
            command=command,
            exclude=exclude,
            exit_code=0,
        )
    return CiSuiteResult(
        suite_id=suite_id,
        name=name,
        measurement=GateMeasurement.FAIL,
        detail=detail or f"exit {exit_code}",
        command=command,
        exclude=exclude,
        exit_code=exit_code,
    )


def default_leviathan_ci_plan(
    *,
    backend_exit: int | None = None,
    frontend_typecheck_exit: int | None = None,
    frontend_lint_exit: int | None = None,
    frontend_test_exit: int | None = None,
    frontend_build_exit: int | None = None,
    security_exit: int | None = None,
    migration_exit: int | None = None,
    integrity_exit: int | None = None,
    fixture_separation_exit: int | None = None,
    round_exit: int | None = None,
    node_available: bool = True,
    backend_available: bool = True,
) -> CiPlan:
    """Build the canonical CI plan. Suites not run stay UNMEASURED, never PASS."""
    suites = [
        interpret_command_result(
            suite_id="backend_unit",
            name="Backend unit + integration (Data/backend/tests)",
            command="python -m pytest Data/backend/tests -q --tb=line",
            exit_code=backend_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="frontend_typecheck",
            name="Frontend TypeScript build check",
            command="npm run typecheck",
            exit_code=frontend_typecheck_exit,
            available=node_available,
            detail="" if node_available else "Node/npm unavailable",
        ),
        interpret_command_result(
            suite_id="frontend_lint",
            name="Frontend lint (oxlint)",
            command="npm run lint",
            exit_code=frontend_lint_exit,
            available=node_available,
        ),
        interpret_command_result(
            suite_id="frontend_test",
            name="Frontend unit tests (vitest)",
            command="npm run test",
            exit_code=frontend_test_exit,
            available=node_available,
        ),
        interpret_command_result(
            suite_id="frontend_build",
            name="Frontend production build",
            command="npm run build",
            exit_code=frontend_build_exit,
            available=node_available,
        ),
        interpret_command_result(
            suite_id="security_sensitive",
            name="Security-sensitive Round 8 isolation tests",
            command="python -m pytest Data/backend/tests/test_round8_security_isolation.py -q",
            exit_code=security_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="migrations",
            name="Migration / durable schema regression",
            command=(
                "python -m pytest Data/backend/tests/test_round6_serving_reliability.py "
                "Data/backend/tests/test_wave3_model_serving.py -k migration -q"
            ),
            exit_code=migration_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="artifact_integrity",
            name="Artifact integrity reopen gates",
            command="python -m pytest Data/backend/tests/test_round7_browser_multimodal.py -k reopen -q",
            exit_code=integrity_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="fixture_production_separation",
            name="Fixture ≠ production honesty",
            command=(
                "python -m pytest Data/backend/tests/test_round7_browser_multimodal.py "
                "Data/backend/tests/test_round9_product_truth.py -k fixture -q"
            ),
            exit_code=fixture_separation_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="frontier_rounds",
            name="Frontier round exit gates (1–10)",
            command="python -m pytest Data/backend/tests/test_round*.py -q",
            exit_code=round_exit,
            available=backend_available,
        ),
        interpret_command_result(
            suite_id="hades",
            name="HADES (out of scope)",
            command="",
            exit_code=None,
            applicable=False,
            detail="HADES/ excluded from LEVIATHAN CI by policy",
        ),
        interpret_command_result(
            suite_id="editor",
            name="editor (out of scope)",
            command="",
            exit_code=None,
            applicable=False,
            detail="editor/ excluded from LEVIATHAN CI by policy",
        ),
    ]
    return CiPlan(suites=suites)
