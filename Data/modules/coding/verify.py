"""Project tooling discovery + adaptive verification selection (U207–U208)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .semantic_map import RepoSemanticMap, SemanticMapBuilder
from .transaction import ChangePlan, ChangeRisk


class VerificationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolingProbe:
    name: str
    kind: str  # test | lint | typecheck | format | build
    command: list[str]
    status: VerificationOutcome
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "command": list(self.command),
            "status": self.status.value,
            "detail": self.detail,
            "truth": {
                "unavailable_is_not_failed": True,
                "not_run_is_not_passed": True,
            },
        }


@dataclass
class AdaptiveVerificationPlan:
    scope: str  # minimal | expanded
    risk: str
    selected: list[ToolingProbe] = field(default_factory=list)
    deferred: list[ToolingProbe] = field(default_factory=list)
    rationale: str = ""
    related_tests: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "risk": self.risk,
            "selected": [t.public_dict() for t in self.selected],
            "deferred": [t.public_dict() for t in self.deferred],
            "rationale": self.rationale,
            "related_tests": list(self.related_tests),
            "truth": {
                "minimal_for_low_risk": True,
                "expanded_on_dependency_or_high_risk": True,
                "unavailable_is_not_failed": True,
            },
        }


def discover_project_tooling(workspace_root: Path) -> list[ToolingProbe]:
    root = Path(workspace_root)
    probes: list[ToolingProbe] = []
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists() or any(root.glob("test_*.py")):
        probes.append(
            ToolingProbe(
                name="pytest",
                kind="test",
                command=["python3", "-m", "pytest", "-q"],
                status=VerificationOutcome.NOT_RUN,
                detail="pytest detected",
            )
        )
    else:
        probes.append(
            ToolingProbe(
                name="pytest",
                kind="test",
                command=["python3", "-m", "pytest", "-q"],
                status=VerificationOutcome.UNAVAILABLE,
                detail="no pytest config or test_*.py found",
            )
        )
    if (root / "package.json").exists():
        probes.append(
            ToolingProbe(
                name="npm-test",
                kind="test",
                command=["npm", "test"],
                status=VerificationOutcome.NOT_RUN,
                detail="package.json present",
            )
        )
    # Optional scanners — reported distinctly from functional tests (U214).
    probes.append(
        ToolingProbe(
            name="ruff",
            kind="lint",
            command=["ruff", "check", "."],
            status=VerificationOutcome.UNAVAILABLE,
            detail="optional static analysis — not required",
        )
    )
    return probes


def select_adaptive_verification(
    workspace_root: Path,
    *,
    plan: ChangePlan | None = None,
    semantic_map: RepoSemanticMap | None = None,
) -> AdaptiveVerificationPlan:
    tooling = discover_project_tooling(workspace_root)
    risk = plan.risk if plan else ChangeRisk.LOW
    smap = semantic_map or SemanticMapBuilder(workspace_root).build()
    related: list[str] = []
    if plan:
        for path in plan.affected_files:
            stem = Path(path).stem
            for test_path in smap.tests:
                if stem and stem in test_path:
                    related.append(test_path)
        related = sorted(set(related))

    available_tests = [t for t in tooling if t.kind == "test" and t.status != VerificationOutcome.UNAVAILABLE]
    unavailable = [t for t in tooling if t.status == VerificationOutcome.UNAVAILABLE]
    others = [t for t in tooling if t.kind != "test" and t.status != VerificationOutcome.UNAVAILABLE]

    expand = risk in {ChangeRisk.MEDIUM, ChangeRisk.HIGH} or len((plan.affected_files if plan else [])) > 2
    if expand:
        selected = available_tests + others
        deferred = unavailable
        scope = "expanded"
        rationale = "Expanded suite due to risk/dependency breadth"
    else:
        # Minimal: prefer related tests via pytest path selectors when possible.
        selected = []
        for probe in available_tests:
            if related and probe.name == "pytest":
                selected.append(
                    ToolingProbe(
                        name=probe.name,
                        kind=probe.kind,
                        command=list(probe.command) + list(related[:5]),
                        status=VerificationOutcome.NOT_RUN,
                        detail=f"minimal related tests: {', '.join(related[:5])}",
                    )
                )
            else:
                selected.append(probe)
        deferred = others + unavailable
        scope = "minimal"
        rationale = "Minimal meaningful verification for low-risk change"
    return AdaptiveVerificationPlan(
        scope=scope,
        risk=risk.value if isinstance(risk, ChangeRisk) else str(risk),
        selected=selected,
        deferred=deferred,
        rationale=rationale,
        related_tests=related,
    )
