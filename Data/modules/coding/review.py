"""Diff-based review artifacts + multi-agent review plan (U210–U211)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .patch import parse_unified_diff
from .transaction import ChangePlan


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class HunkReview:
    path: str
    old_start: int
    new_start: int
    finding: str
    severity: str  # info | warn | risk
    reasoning: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_start": self.old_start,
            "new_start": self.new_start,
            "finding": self.finding,
            "severity": self.severity,
            "reasoning": self.reasoning,
        }


@dataclass
class DiffReviewArtifact:
    review_id: str
    plan_id: str | None
    summary: str
    hunks: list[HunkReview] = field(default_factory=list)
    test_evidence: list[str] = field(default_factory=list)
    reviewer_findings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "plan_id": self.plan_id,
            "summary": self.summary,
            "hunks": [h.public_dict() for h in self.hunks],
            "test_evidence": list(self.test_evidence),
            "reviewer_findings": list(self.reviewer_findings),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "review_is_not_merge_authority": True,
                "uses_shared_agent_dag_roles": True,
            },
        }


_SECRETISH = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]", re.I)
_TODO = re.compile(r"\bTODO\b|\bFIXME\b")


def build_diff_review(
    *,
    plan: ChangePlan | None = None,
    diffs: dict[str, str] | None = None,
    test_evidence: list[str] | None = None,
) -> DiffReviewArtifact:
    hunks: list[HunkReview] = []
    findings: list[str] = []
    sources = dict(diffs or {})
    if plan:
        for change in plan.changes:
            if change.unified_diff:
                sources[change.path] = change.unified_diff
    for path, diff in sources.items():
        try:
            parsed = parse_unified_diff(diff)
        except Exception:  # noqa: BLE001
            findings.append(f"{path}: unreadable diff")
            continue
        for hunk in parsed:
            body = "\n".join(hunk.lines)
            severity = "info"
            finding = "hunk inspected"
            reasoning = f"{len(hunk.lines)} lines"
            if _SECRETISH.search(body):
                severity = "risk"
                finding = "possible secret material in diff"
                findings.append(f"{path}:{hunk.new_start} possible secret")
            elif _TODO.search(body):
                severity = "warn"
                finding = "TODO/FIXME introduced"
            elif any(line.startswith("+") and "except:" in line for line in hunk.lines):
                severity = "warn"
                finding = "bare except introduced"
            hunks.append(
                HunkReview(
                    path=path,
                    old_start=hunk.old_start,
                    new_start=hunk.new_start,
                    finding=finding,
                    severity=severity,
                    reasoning=reasoning,
                )
            )
    summary = (
        f"Reviewed {len(hunks)} hunks across {len(sources)} files; "
        f"{sum(1 for h in hunks if h.severity == 'risk')} risk findings"
    )
    return DiffReviewArtifact(
        review_id=f"rev_{uuid.uuid4().hex[:12]}",
        plan_id=plan.plan_id if plan else None,
        summary=summary,
        hunks=hunks,
        test_evidence=list(test_evidence or (plan.expected_tests if plan else [])),
        reviewer_findings=findings,
        metadata={"file_count": len(sources)},
    )


@dataclass(frozen=True)
class ReviewAgentNode:
    role: str  # planner | implementer | test_engineer | reviewer
    objective: str
    depends_on: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "depends_on": list(self.depends_on),
        }


def build_multi_agent_review_dag(plan: ChangePlan) -> dict[str, Any]:
    """Declare Planner/Implementer/Test/Reviewer nodes for the shared Agent DAG (U211)."""
    nodes = [
        ReviewAgentNode("planner", f"Refine change plan for: {plan.goal[:120]}"),
        ReviewAgentNode(
            "implementer",
            f"Apply {len(plan.changes)} file changes under snapshot rollback",
            depends_on=("planner",),
        ),
        ReviewAgentNode(
            "test_engineer",
            "Run adaptive verification for risk=" + plan.risk.value,
            depends_on=("implementer",),
        ),
        ReviewAgentNode(
            "reviewer",
            "Produce diff review artifact with per-hunk findings",
            depends_on=("implementer", "test_engineer"),
        ),
    ]
    return {
        "dag_id": f"coding_review_{plan.plan_id}",
        "plan_id": plan.plan_id,
        "nodes": [n.public_dict() for n in nodes],
        "truth": {
            "no_private_agent_runtime": True,
            "uses_shared_agent_dag_and_blackboard": True,
        },
    }
