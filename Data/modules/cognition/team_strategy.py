"""TEAM collaboration strategy — separate from reasoning depth.

ReasoningMode (FAST/STANDARD/DEEP/MAXIMUM/ADAPTIVE) describes effort within
model work. CollaborationStrategy describes how specialist tasks cooperate.
TEAM is not MAXIMUM-with-more-tokens.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from Data.modules.verification.quality_contract import (
    CompletionPolicyKind,
    CriterionApplicability,
    EvidenceClass,
    QualityContract,
    QualityCriterion,
    CriterionSeverity,
    new_contract_id,
)

from .team_task_profile import (
    LIGHTWEIGHT_CATEGORIES,
    TeamTaskProfile,
    build_team_task_profile,
)


class CollaborationStrategy(str, Enum):
    DIRECT = "direct"
    TEAM = "team"


class TeamRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    ANALYST = "analyst"
    RESEARCHER = "researcher"
    QUESTIONER = "questioner"
    CRITIC = "critic"
    VERIFIER = "verifier"
    SYNTHESIZER = "synthesizer"


class TeamRunStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    VERIFYING = "verifying"
    REVISING = "revising"
    WAITING_FOR_RESOURCE = "waiting_for_resource"
    WAITING_FOR_INPUT = "waiting_for_input"
    BLOCKED = "blocked"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


TERMINAL_TEAM_STATUSES = frozenset(
    {
        TeamRunStatus.COMPLETED,
        TeamRunStatus.CANCELLED,
        TeamRunStatus.FAILED,
    }
)

# Resumable non-success states — distinct from COMPLETED.
NON_SUCCESS_ACTIVE = frozenset(
    {
        TeamRunStatus.WAITING_FOR_RESOURCE,
        TeamRunStatus.WAITING_FOR_INPUT,
        TeamRunStatus.BLOCKED,
        TeamRunStatus.PAUSED,
    }
)

ALLOWED_TEAM_TRANSITIONS: dict[TeamRunStatus, frozenset[TeamRunStatus]] = {
    TeamRunStatus.QUEUED: frozenset(
        {TeamRunStatus.PLANNING, TeamRunStatus.CANCELLED, TeamRunStatus.FAILED}
    ),
    TeamRunStatus.PLANNING: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.CANCELLED,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.RUNNING: frozenset(
        {
            TeamRunStatus.VERIFYING,
            TeamRunStatus.REVISING,
            TeamRunStatus.WAITING_FOR_RESOURCE,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.PAUSED,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.VERIFYING: frozenset(
        {
            TeamRunStatus.COMPLETED,
            TeamRunStatus.REVISING,
            TeamRunStatus.RUNNING,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.REVISING: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.PLANNING,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.WAITING_FOR_RESOURCE: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.PAUSED,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.WAITING_FOR_INPUT: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.REVISING,
            TeamRunStatus.PLANNING,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.CANCELLED,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.BLOCKED: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.REVISING,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.CANCELLED,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.PAUSED: frozenset(
        {
            TeamRunStatus.RUNNING,
            TeamRunStatus.CANCELLING,
            TeamRunStatus.CANCELLED,
            TeamRunStatus.FAILED,
        }
    ),
    TeamRunStatus.CANCELLING: frozenset(
        {TeamRunStatus.CANCELLED, TeamRunStatus.FAILED}
    ),
    TeamRunStatus.CANCELLED: frozenset(),
    TeamRunStatus.FAILED: frozenset(),
    TeamRunStatus.COMPLETED: frozenset(),
}


USER_FACING_TEAM_DESCRIPTION = (
    "Continues until the quality criteria are met, or shows exactly what prevents completion."
)


@dataclass(frozen=True)
class ResourceBounds:
    """Per-operation / concurrency bounds — never a cumulative TEAM success gate."""

    model_call_timeout_seconds: float = 120.0
    max_model_output_tokens: int = 8192
    tool_timeout_seconds: float = 60.0
    max_tool_payload_bytes: int = 2_000_000
    max_parallel_workers: int = 4
    max_batch_queries: int = 16
    max_fan_out: int = 8
    operation_retry_limit: int = 3

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_call_timeout_seconds": self.model_call_timeout_seconds,
            "max_model_output_tokens": self.max_model_output_tokens,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "max_tool_payload_bytes": self.max_tool_payload_bytes,
            "max_parallel_workers": self.max_parallel_workers,
            "max_batch_queries": self.max_batch_queries,
            "max_fan_out": self.max_fan_out,
            "operation_retry_limit": self.operation_retry_limit,
            "truth": {
                "resource_bounds_are_not_cumulative_success_gates": True,
                "exhaustion_does_not_auto_complete": True,
            },
        }


@dataclass(frozen=True)
class OptionalUserCaps:
    """Explicit optional user caps. Null means unbounded (not 999999 or 0-as-unlimited)."""

    max_iterations: int | None = None
    max_total_tokens: int | None = None
    max_wall_time_seconds: float | None = None
    max_sources: int | None = None

    def __post_init__(self) -> None:
        for name, val in (
            ("max_iterations", self.max_iterations),
            ("max_total_tokens", self.max_total_tokens),
            ("max_sources", self.max_sources),
        ):
            if val is not None and int(val) < 0:
                raise ValueError(f"{name} must be null or non-negative")
        if self.max_wall_time_seconds is not None and float(self.max_wall_time_seconds) < 0:
            raise ValueError("max_wall_time_seconds must be null or non-negative")

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "max_total_tokens": self.max_total_tokens,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_sources": self.max_sources,
            "truth": {
                "null_means_unbounded": True,
                "cap_reached_is_incomplete_not_success": True,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "OptionalUserCaps":
        raw = dict(data or {})
        def _opt_int(key: str) -> int | None:
            if key not in raw or raw[key] is None:
                return None
            return int(raw[key])

        def _opt_float(key: str) -> float | None:
            if key not in raw or raw[key] is None:
                return None
            return float(raw[key])

        return cls(
            max_iterations=_opt_int("max_iterations"),
            max_total_tokens=_opt_int("max_total_tokens"),
            max_wall_time_seconds=_opt_float("max_wall_time_seconds"),
            max_sources=_opt_int("max_sources"),
        )


@dataclass(frozen=True)
class TeamExecutionPolicy:
    completion_policy: CompletionPolicyKind = CompletionPolicyKind.QUALITY_CONTRACT
    collaboration: CollaborationStrategy = CollaborationStrategy.TEAM
    resource_bounds: ResourceBounds = field(default_factory=ResourceBounds)
    user_caps: OptionalUserCaps = field(default_factory=OptionalUserCaps)
    no_progress_window: int = 3
    allow_parallel_workers: bool = True
    single_model_sequential: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "completion_policy": self.completion_policy.value,
            "collaboration": self.collaboration.value,
            "resource_bounds": self.resource_bounds.public_dict(),
            "user_caps": self.user_caps.public_dict(),
            "no_progress_window": self.no_progress_window,
            "allow_parallel_workers": self.allow_parallel_workers,
            "single_model_sequential": self.single_model_sequential,
            "description": USER_FACING_TEAM_DESCRIPTION,
            "truth": {
                "team_is_not_maximum_with_more_tokens": True,
                "no_fixed_cumulative_round_count": True,
                "no_fixed_cumulative_token_cap": True,
                "no_auto_success_on_pool_exhaustion": True,
            },
        }

    @classmethod
    def team_default(cls) -> "TeamExecutionPolicy":
        return cls()

    @classmethod
    def fixed_budget_default(cls) -> "TeamExecutionPolicy":
        return cls(
            completion_policy=CompletionPolicyKind.FIXED_BUDGET,
            collaboration=CollaborationStrategy.DIRECT,
        )


@dataclass
class TeamAssignment:
    task_id: str
    parent_run_id: str
    role: TeamRole
    objective: str
    criterion_ids: list[str] = field(default_factory=list)
    allowed_capabilities: list[str] = field(default_factory=list)
    forbidden_capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    expected_result_schema: str = "structured_json"
    revision_preconditions: list[str] = field(default_factory=list)
    context_refs: list[str] = field(default_factory=list)
    graph_revision: int = 1
    status: str = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_run_id": self.parent_run_id,
            "role": self.role.value,
            "objective": self.objective,
            "criterion_ids": list(self.criterion_ids),
            "allowed_capabilities": list(self.allowed_capabilities),
            "forbidden_capabilities": list(self.forbidden_capabilities),
            "dependencies": list(self.dependencies),
            "expected_result_schema": self.expected_result_schema,
            "revision_preconditions": list(self.revision_preconditions),
            "context_refs": list(self.context_refs),
            "graph_revision": self.graph_revision,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class TeamBlocker:
    blocker_id: str
    criterion_id: str | None
    kind: str
    summary: str
    attempted_remedies: list[str] = field(default_factory=list)
    needed_input: str | None = None
    needed_capability: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "criterion_id": self.criterion_id,
            "kind": self.kind,
            "summary": self.summary,
            "attempted_remedies": list(self.attempted_remedies),
            "needed_input": self.needed_input,
            "needed_capability": self.needed_capability,
        }


def normalize_collaboration_strategy(value: str | None) -> CollaborationStrategy:
    raw = (value or "direct").strip().lower()
    aliases = {
        "team": CollaborationStrategy.TEAM,
        "multi_agent": CollaborationStrategy.TEAM,
        "collaboration": CollaborationStrategy.TEAM,
        "direct": CollaborationStrategy.DIRECT,
        "none": CollaborationStrategy.DIRECT,
        "": CollaborationStrategy.DIRECT,
    }
    if raw in aliases:
        return aliases[raw]
    try:
        return CollaborationStrategy(raw)
    except ValueError as exc:
        raise ValueError(f"invalid collaboration_strategy: {value}") from exc


def transition_allowed(current: TeamRunStatus, target: TeamRunStatus) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TEAM_TRANSITIONS.get(current, frozenset())


def assert_transition(current: TeamRunStatus, target: TeamRunStatus) -> None:
    if not transition_allowed(current, target):
        raise ValueError(f"illegal TEAM transition {current.value} → {target.value}")


# --- Role templates (task templates, not a fixed permanent council) ---

ROLE_TEMPLATES: dict[TeamRole, dict[str, Any]] = {
    TeamRole.ORCHESTRATOR: {
        "responsibility": "Own contract, decomposition, scheduling and acceptance coordination",
        "required_output": "goal_graph_next_actions_status_blockers",
    },
    TeamRole.ANALYST: {
        "responsibility": "Form candidate solutions, assumptions and alternatives",
        "required_output": "candidate_artifact_and_propositions",
    },
    TeamRole.RESEARCHER: {
        "responsibility": "Retrieve relevant local/web evidence through allowed tools",
        "required_output": "evidence_records_provenance_coverage",
    },
    TeamRole.QUESTIONER: {
        "responsibility": "Identify missing information that could change the result",
        "required_output": "questions_impact_acquisition_method",
    },
    TeamRole.CRITIC: {
        "responsibility": "Search for counterexamples, violated constraints and alternatives",
        "required_output": "evidence_linked_objections",
    },
    TeamRole.VERIFIER: {
        "responsibility": "Check claims/artifacts using suitable methods",
        "required_output": "typed_verdicts_with_receipts",
    },
    TeamRole.SYNTHESIZER: {
        "responsibility": "Produce a coherent user-facing deliverable from accepted material",
        "required_output": "versioned_artifact_with_traceable_claims",
    },
}


def select_roles_for_task(
    *,
    task_category: str,
    requires_research: bool = False,
    requires_coding: bool = False,
    requires_tools: bool = False,
    profile: TeamTaskProfile | None = None,
) -> list[TeamRole]:
    """Choose useful roles — TEAM need not invoke every role.

    Lightweight conversational/self-description uses a smaller genuine TEAM
    graph (Analyst → Synthesizer → Verifier) — still TEAM, not DIRECT.
    """
    roles: list[TeamRole] = [TeamRole.ORCHESTRATOR]
    cat = (profile.category if profile else None) or (task_category or "general")
    cat = cat.lower()
    research = requires_research or (profile.requires_external_research if profile else False)
    coding = requires_coding or (profile.requires_code_execution if profile else False)
    tools = requires_tools or (profile.requires_tools if profile else False)
    lightweight = bool(profile and profile.lightweight) or cat in LIGHTWEIGHT_CATEGORIES

    if coding or cat in {"coding", "code", "repair"}:
        roles.extend([TeamRole.ANALYST, TeamRole.CRITIC, TeamRole.VERIFIER, TeamRole.SYNTHESIZER])
    elif research or cat in {"research", "factual", "investigation"}:
        roles.extend(
            [
                TeamRole.RESEARCHER,
                TeamRole.QUESTIONER,
                TeamRole.CRITIC,
                TeamRole.VERIFIER,
                TeamRole.SYNTHESIZER,
            ]
        )
    elif cat in {"quantitative", "calculation"}:
        roles.extend([TeamRole.ANALYST, TeamRole.VERIFIER, TeamRole.SYNTHESIZER])
    elif tools or cat in {"tool", "local_tool", "tool_task"}:
        roles.extend([TeamRole.ANALYST, TeamRole.VERIFIER, TeamRole.SYNTHESIZER])
    elif cat in {"design", "proposal"}:
        roles.extend([TeamRole.ANALYST, TeamRole.CRITIC, TeamRole.SYNTHESIZER])
    elif lightweight:
        # Genuine lightweight TEAM: analyst drafts, synthesizer delivers, verifier checks.
        roles.extend([TeamRole.ANALYST, TeamRole.SYNTHESIZER, TeamRole.VERIFIER])
    else:
        roles.extend([TeamRole.ANALYST, TeamRole.VERIFIER, TeamRole.SYNTHESIZER])
    # Deduplicate preserving order
    seen: set[TeamRole] = set()
    out: list[TeamRole] = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


@dataclass
class TeamSpecialistResult:
    """Typed specialist result contract shared by producers and TeamOrchestrator.

    LLM self-assertions (artifact_ok / tests_passed / claims_supported) are never
    authoritative alone — the orchestrator verifies against artifact state and
    real receipts before emitting SATISFIED verdicts.
    """

    role: str
    task_id: str = ""
    summary: str = ""
    artifact_candidate: dict[str, Any] | None = None
    provisional_artifact: dict[str, Any] | None = None
    evidence_refs: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_origins: list[str] = field(default_factory=list)
    criterion_observations: list[dict[str, Any]] = field(default_factory=list)
    material_claims: list[dict[str, Any]] = field(default_factory=list)
    tool_receipts: list[str] = field(default_factory=list)
    test_receipts: list[str] = field(default_factory=list)
    calculation_receipt_id: str | None = None
    test_receipt_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: str = ""
    # Explicit signals — still require matching receipts/artifact inspection.
    claims_supported: bool | None = None
    citation_audit_passed: bool | None = None
    tests_passed: bool | None = None
    supported_uncertainty: bool | None = None
    requirements_addressed: bool | None = None
    unsupported_new_claim: bool | None = None
    agents_agree_unsupported: bool | None = None
    # Deprecated producer hint — orchestrator must not treat this as proof.
    artifact_ok: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        art = self.artifact_candidate or self.provisional_artifact
        evidence = list(dict.fromkeys([*self.evidence_ids, *self.evidence_refs, *self.tool_receipts]))
        out: dict[str, Any] = {
            "role": self.role,
            "task_id": self.task_id,
            "summary": self.summary,
            "notes": self.notes or (self.summary[:500] if self.summary else ""),
            "evidence_ids": evidence,
            "evidence_refs": list(self.evidence_refs),
            "evidence_origins": list(self.evidence_origins),
            "criterion_observations": list(self.criterion_observations),
            "material_claims": list(self.material_claims),
            "tool_receipts": list(self.tool_receipts),
            "test_receipts": list(self.test_receipts),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "schema": "TeamSpecialistResult.v1",
        }
        if art is not None:
            out["provisional_artifact"] = dict(art)
            out["artifact_candidate"] = dict(art)
        if self.calculation_receipt_id:
            out["calculation_receipt_id"] = self.calculation_receipt_id
        if self.test_receipt_id:
            out["test_receipt_id"] = self.test_receipt_id
        for key in (
            "claims_supported",
            "citation_audit_passed",
            "tests_passed",
            "supported_uncertainty",
            "requirements_addressed",
            "unsupported_new_claim",
            "agents_agree_unsupported",
            "artifact_ok",
        ):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | "TeamSpecialistResult") -> "TeamSpecialistResult":
        if isinstance(data, TeamSpecialistResult):
            return data
        raw = dict(data or {})
        art = raw.get("artifact_candidate") or raw.get("provisional_artifact")
        evidence = [str(x) for x in (raw.get("evidence_ids") or raw.get("evidence_refs") or [])]
        return cls(
            role=str(raw.get("role") or ""),
            task_id=str(raw.get("task_id") or ""),
            summary=str(raw.get("summary") or raw.get("notes") or ""),
            artifact_candidate=dict(art) if isinstance(art, Mapping) else None,
            provisional_artifact=dict(art) if isinstance(art, Mapping) else None,
            evidence_refs=[str(x) for x in (raw.get("evidence_refs") or [])],
            evidence_ids=evidence,
            evidence_origins=[str(x) for x in (raw.get("evidence_origins") or [])],
            criterion_observations=list(raw.get("criterion_observations") or []),
            material_claims=list(raw.get("material_claims") or []),
            tool_receipts=[str(x) for x in (raw.get("tool_receipts") or [])],
            test_receipts=[str(x) for x in (raw.get("test_receipts") or [])],
            calculation_receipt_id=(
                str(raw["calculation_receipt_id"]) if raw.get("calculation_receipt_id") else None
            ),
            test_receipt_id=str(raw["test_receipt_id"]) if raw.get("test_receipt_id") else None,
            warnings=[str(x) for x in (raw.get("warnings") or [])],
            errors=[str(x) for x in (raw.get("errors") or ([raw["error"]] if raw.get("error") else []))],
            notes=str(raw.get("notes") or ""),
            claims_supported=raw.get("claims_supported"),
            citation_audit_passed=raw.get("citation_audit_passed"),
            tests_passed=raw.get("tests_passed"),
            supported_uncertainty=raw.get("supported_uncertainty"),
            requirements_addressed=raw.get("requirements_addressed"),
            unsupported_new_claim=raw.get("unsupported_new_claim"),
            agents_agree_unsupported=raw.get("agents_agree_unsupported"),
            artifact_ok=raw.get("artifact_ok"),
        )


def build_default_contract_for_request(
    *,
    run_id: str,
    request_ref: str,
    request_text: str,
    task_category: str = "general",
    requires_research: bool = False,
    requires_coding: bool = False,
    created_at: str = "",
    profile: TeamTaskProfile | None = None,
) -> QualityContract:
    """Translate a user request into concrete typed criteria (not ambition phrases).

    Task-aware: conversational/self-description gets response/coherence criteria
    without irrelevant web/test/calc receipts. Research/coding/calc stay strict.
    """
    resolved = profile or (
        build_team_task_profile(request_text)
        if (task_category or "general") == "general"
        and not requires_research
        and not requires_coding
        else None
    )
    criteria: list[QualityCriterion] = []
    cat = (resolved.category if resolved else None) or (task_category or "general")
    cat = cat.lower()
    research = requires_research or (resolved.requires_external_research if resolved else False)
    coding = requires_coding or (
        resolved.requires_code_execution if resolved else False
    ) or cat in {"coding", "code", "repair"}
    quantitative = (resolved.requires_calculation if resolved else False) or cat in {
        "quantitative",
        "calculation",
    }
    lightweight = bool(resolved and resolved.lightweight) or cat in LIGHTWEIGHT_CATEGORIES
    template = cat

    if coding:
        template = "coding"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:behavior_works",
                description="Requested behavior works for the delivered revision",
                verification_method="trusted_test_receipt_or_integration_check",
                evidence_class=EvidenceClass.TEST_RECEIPT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "coding"},
            )
        )
        criteria.append(
            QualityCriterion(
                criterion_id="crit:regression_preserved",
                description="Relevant prior behavior remains covered by checks",
                verification_method="regression_suite_receipt",
                evidence_class=EvidenceClass.TEST_RECEIPT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "coding"},
            )
        )
    elif research or cat in {"research", "factual", "investigation"}:
        template = "research" if cat != "factual" else "factual"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:claims_supported",
                description="Material factual claims have inspectable supporting evidence",
                verification_method="claim_to_source_span_audit",
                evidence_class=EvidenceClass.CLAIM_SUPPORT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": template},
            )
        )
        criteria.append(
            QualityCriterion(
                criterion_id="crit:citation_audit",
                description="Report citations resolve to recorded material and support the claim",
                verification_method="citation_audit",
                evidence_class=EvidenceClass.CITATION_AUDIT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": template},
            )
        )
        criteria.append(
            QualityCriterion(
                criterion_id="crit:conflicts_surfaced",
                description="Material conflicts and limitations are explicitly recorded",
                verification_method="conflict_and_gap_inspection",
                evidence_class=EvidenceClass.INDEPENDENT_CHECK,
                severity=CriterionSeverity.ADVISORY,
                provenance={"source": "team_template", "template": template},
            )
        )
    elif quantitative:
        template = "quantitative"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:reproducible_calc",
                description="Calculations are reproducible from recorded inputs and units",
                verification_method="calculation_receipt_comparison",
                evidence_class=EvidenceClass.CALCULATION_RECEIPT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "quantitative"},
            )
        )
    elif cat in {"design", "proposal"}:
        template = "design"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:requirements_addressed",
                description="Stated requirements and constraints are addressed with trade-offs",
                verification_method="requirement_to_artifact_mapping",
                evidence_class=EvidenceClass.ARTIFACT_INSPECTION,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "design"},
            )
        )
    elif cat in {"uncertainty", "uncertainty_assessment"}:
        template = "uncertainty"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:supported_uncertainty",
                description="Unresolved uncertainty is stated with supporting rationale — not invented facts",
                verification_method="uncertainty_statement_audit",
                evidence_class=EvidenceClass.UNCERTAINTY_STATEMENT,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "uncertainty"},
            )
        )
    elif lightweight:
        template = "conversational"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:deliverable_present",
                description="Non-empty candidate response exists for the current revision",
                verification_method="deterministic_response_artifact_inspection",
                evidence_class=EvidenceClass.ARTIFACT_INSPECTION,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "conversational"},
            )
        )
        criteria.append(
            QualityCriterion(
                criterion_id="crit:request_addressed",
                description="Response addresses the user's conversational/self-description request",
                verification_method="request_scope_response_inspection",
                evidence_class=EvidenceClass.ARTIFACT_INSPECTION,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "conversational"},
            )
        )
    else:
        template = "general"
        criteria.append(
            QualityCriterion(
                criterion_id="crit:deliverable_present",
                description="Requested deliverable exists with expected content for this revision",
                verification_method="artifact_or_response_inspection",
                evidence_class=EvidenceClass.ARTIFACT_INSPECTION,
                severity=CriterionSeverity.MANDATORY,
                provenance={"source": "team_template", "template": "general"},
            )
        )

    # Always: synthesis must not introduce unchecked new material claims.
    criteria.append(
        QualityCriterion(
            criterion_id="crit:synthesis_rechecked",
            description="Final synthesis introduces no unsupported new material claims",
            verification_method="post_synthesis_reverification",
            evidence_class=EvidenceClass.INDEPENDENT_CHECK,
            severity=CriterionSeverity.MANDATORY,
            provenance={"source": "team_template", "template": "synthesis_gate"},
        )
    )

    # Mark clearly irrelevant evidence classes as NOT_APPLICABLE for lightweight tasks
    # when a caller embeds a mixed contract — builder itself does not add them.
    final_category = (resolved.category if resolved else None) or cat or "general"

    return QualityContract(
        contract_id=new_contract_id(),
        version=1,
        run_id=run_id,
        request_ref=request_ref,
        scope=(request_text or "")[:2000],
        expected_deliverables=["accepted_answer_or_artifact"],
        task_category=final_category,
        exclusions=[],
        assumptions=[],
        accepted_uncertainty=[],
        criteria=criteria,
        provenance={
            "builder": "build_default_contract_for_request",
            "template": template,
            "profile": resolved.public_dict() if resolved else None,
            "lightweight": lightweight,
        },
        created_at=created_at,
    )


def mark_criterion_not_applicable(
    criterion: QualityCriterion,
    *,
    justification: str,
) -> QualityCriterion:
    """Return a copy of *criterion* marked NOT_APPLICABLE with justification."""
    return QualityCriterion(
        criterion_id=criterion.criterion_id,
        description=criterion.description,
        verification_method=criterion.verification_method,
        evidence_class=criterion.evidence_class,
        severity=criterion.severity,
        applicability=CriterionApplicability.NOT_APPLICABLE,
        applicability_justification=justification,
        depends_on=criterion.depends_on,
        threshold=dict(criterion.threshold),
        provenance={**dict(criterion.provenance), "applicability_set_by": "team_contract"},
    )


def new_assignment_id() -> str:
    return f"task:{uuid.uuid4().hex[:12]}"


def new_blocker_id() -> str:
    return f"blk:{uuid.uuid4().hex[:12]}"
