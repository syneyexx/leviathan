from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RequestKind = Literal[
    "chat",
    "question",
    "analysis",
    "research",
    "code",
    "debug",
    "planning",
    "tool_use",
    "multi_step",
    "memory_write",
    "unknown",
]

ReasoningProfileName = Literal["fast", "standard", "high", "maximum", "adaptive", "normal", "medium"]
ProductModeName = Literal["normal", "medium", "high", "adaptive"]

RouteTarget = Literal[
    "direct_chat",
    "analysis",
    "research",
    "work_runtime",
    "tool_loop",
    "specialist_agent",
]


@dataclass(slots=True)
class RequestSpec:
    """Structured understanding of a user request. Not a permission grant.

    Interpretation never grants permissions. ``goal`` is a compact summary;
    ``raw_text`` remains the authoritative user text.
    """

    raw_text: str
    kind: RequestKind
    goal: str
    constraints: list[str] = field(default_factory=list)
    acceptance_hints: list[str] = field(default_factory=list)
    needs_tools: bool = False
    needs_research: bool = False
    needs_memory_write: bool = False
    needs_plan: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    ambiguity: Literal["low", "medium", "high"] = "low"
    signals: dict[str, Any] = field(default_factory=dict)
    # Compact interpretation separate from authorization.
    speech_act: str = "inform"  # explain | execute | question | compare | correct | refuse | inform
    asked_output: str = "answer"
    missing_info: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    assumptions: list[str] = field(default_factory=list)
    interpretation: dict[str, Any] = field(default_factory=dict)
    # Additive resolved-request fields (raw_text stays authoritative).
    resolved_goal: str = ""
    resolved_query: str = ""
    referent_summary: str = ""
    source_message_id: str | None = None

    def effective_goal(self) -> str:
        return (self.resolved_goal or self.goal or self.raw_text or "").strip()

    def effective_query(self) -> str:
        return (self.resolved_query or self.resolved_goal or self.goal or self.raw_text or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskFeatures:
    """Structured task traits used for policy choice. Not a permission grant.

    ``heuristic_score`` is an uncalibrated cheap hint, never a confidence.
    """

    speech_act: str = "inform"
    independent_outcomes: int = 1
    has_step_dependencies: bool = False
    result_affecting_ambiguity: bool = False
    freshness_required: bool = False
    context_available: bool = True
    context_missing: bool = False
    tools_required: bool = False
    side_effects: bool = False
    evidence_kind: str = "none"
    prior_run_failures: int = 0
    user_constraint_count: int = 0
    direct_answer: bool = False
    material_uncertainty: bool = False
    cheap_hints: dict[str, Any] = field(default_factory=dict)
    heuristic_score: float | None = None
    heuristic_score_kind: str = "uncalibrated_hint"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModeDecision:
    selected_mode: ProductModeName
    effective_policy: ReasoningProfileName
    decision_reason: str
    policy_version: str
    requested_raw: str = ""
    compatibility: str | None = None
    explicit: bool = False
    classification_used: bool = False
    classification_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RouteDecision:
    target: RouteTarget
    profile: ReasoningProfileName
    agent_id: str | None
    rationale: str
    allow_tools: bool
    allow_web: bool
    max_tool_rounds: int
    require_verification: bool
    stop_and_ask: bool = False
    ask_questions: list[str] = field(default_factory=list)
    selected_mode: str = ""
    effective_policy: str = ""
    decision_reason: str = ""
    policy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextItem:
    item_id: str
    kind: Literal[
        "system_policy",
        "user_constraint",
        "recent_message",
        "memory",
        "knowledge",
        "skill",
        "evidence",
        "tool_result",
        "plan",
        "workspace",
        "neural_association",
        "other",
    ]
    content: str
    provenance: str
    priority: int = 100
    trusted: bool = False
    redactable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BudgetReport:
    max_chars: int
    used_chars: int
    kept_items: int
    dropped_items: int
    protected_kept: int
    truncated: bool
    notes: list[str] = field(default_factory=list)
    drop_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanStep:
    step_id: str
    title: str
    instruction: str
    agent_id: str
    kind: str = "work"
    depends_on: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Plan:
    goal: str
    acceptance_criteria: list[str]
    steps: list[PlanStep]
    version: int = 1
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "acceptance_criteria": list(self.acceptance_criteria),
            "steps": [step.to_dict() for step in self.steps],
            "version": self.version,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class ToolCallRequest:
    plugin_id: str
    tool_name: str
    arguments: dict[str, Any]
    call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolObservation:
    call_id: str | None
    plugin_id: str
    tool_name: str
    status: str
    exit_code: int | None = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    output: str = ""
    structured_output: dict[str, Any] | list[Any] | None = None
    truncation: dict[str, Any] | None = None
    invocation_type: str = "autonomous"
    side_effects: Literal["none", "known", "uncertain"] = "uncertain"

    @property
    def succeeded(self) -> bool:
        return self.status in {"completed", "succeeded", "success", "ok"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AcceptanceCriterionMatch:
    """Per-criterion checklist row for honest completion matching."""

    criterion: str
    met: bool
    note: str = ""
    criterion_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VerificationParseStatus = Literal[
    "valid_json",
    "valid_schema",
    "incomplete_coverage",
    "insufficient_evidence",
    "verified",
    "unverified",
    "invalid_json",
    "invalid_schema",
    "repaired",
]


@dataclass(slots=True)
class VerificationResult:
    passed: bool
    issues: list[str]
    final_answer: str
    evidence_refs: list[str] = field(default_factory=list)
    method: str = "structured_critic"
    incomplete: bool = False
    criteria_checklist: list[AcceptanceCriterionMatch] = field(default_factory=list)
    # Separated verification axes — do not collapse into a single passed flag.
    parse_status: str = "unverified"
    schema_valid: bool = False
    criteria_coverage_complete: bool = False
    evidence_sufficient: bool = False
    repair_notes: list[str] = field(default_factory=list)
    # Critic may propose repairs; rewrites are not auto-trusted.
    repair_instructions: list[str] = field(default_factory=list)
    proposed_final_answer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "final_answer": self.final_answer,
            "evidence_refs": list(self.evidence_refs),
            "method": self.method,
            "incomplete": self.incomplete,
            "criteria_checklist": [item.to_dict() for item in self.criteria_checklist],
            "parse_status": self.parse_status,
            "schema_valid": self.schema_valid,
            "criteria_coverage_complete": self.criteria_coverage_complete,
            "evidence_sufficient": self.evidence_sufficient,
            "repair_notes": list(self.repair_notes),
            "repair_instructions": list(self.repair_instructions),
            "proposed_final_answer": self.proposed_final_answer,
        }
