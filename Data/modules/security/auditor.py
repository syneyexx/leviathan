from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class SecurityFinding:
    finding_id: str
    severity: str  # info | low | medium | high
    title: str
    detail: str
    passed: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class SecurityAuditReport:
    findings: tuple[SecurityFinding, ...]
    summary: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "findings": [item.public_dict() for item in self.findings],
            "summary": self.summary,
            "metadata": self.metadata,
            "truth": {
                "audit_report_is_not_penetration_test": True,
                "unmeasured_is_not_passed": True,
            },
        }


class SecurityAuditor:
    """Static configuration/security posture checks for LEVIATHAN."""

    def __init__(self, checks: list[Callable[[], SecurityFinding]] | None = None) -> None:
        self._checks = list(checks or [])

    def add(self, check: Callable[[], SecurityFinding]) -> None:
        self._checks.append(check)

    def run(self) -> SecurityAuditReport:
        findings = tuple(check() for check in self._checks)
        summary = {
            "total": len(findings),
            "passed": sum(1 for item in findings if item.passed),
            "failed": sum(1 for item in findings if not item.passed),
        }
        return SecurityAuditReport(findings=findings, summary=summary)
