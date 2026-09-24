"""LEVIATHAN Coding Agent control plane."""

from .cognition import (
    CodingCognitiveStrategy,
    CodingPhase,
    CodingPlan,
    CodingTaskType,
    classify_coding_task,
)
from .llm_adapter import CodingLLMAdapter
from .loop import CodingLoop, FakeLLM
from .parser import extract_capabilities, extract_structured_capabilities, strip_capabilities
from .patch import PatchApplyError, PatchApplyError as PatchError, apply_unified_diff, parse_unified_diff
from .planner import build_initial_plan, mission_from_text
from .prompts import (
    CODING_COGNITIVE_OVERLAY,
    CODING_SYSTEM_PROMPT,
    coding_cognitive_overlay,
    coding_system_prompt,
)
from .review import DiffReviewArtifact, build_diff_review, build_multi_agent_review_dag
from .semantic_map import RepoSemanticMap, SemanticMapBuilder
from .service import CodingControlPlane
from .store import CodingStore
from .tools import GATED_CAPS, enforce_capability
from .transaction import ChangePlan, ChangeRisk, FileChange, WorkspaceTransaction, build_change_plan
from .types import (
    ACTIVE_STATUSES,
    CodingError,
    CodingPatch,
    CodingSession,
    CodingStep,
    CodingTurn,
    LoopResult,
    Mission,
    ParsedCapability,
    SessionStatus,
    StepKind,
    StepStatus,
    TERMINAL_STATUSES,
)
from .verify import AdaptiveVerificationPlan, discover_project_tooling, select_adaptive_verification
from .worker import CodingWorker
from .workspace import confine, is_denied, list_entries, resolve_root, search_files

__all__ = [
    "ACTIVE_STATUSES",
    "AdaptiveVerificationPlan",
    "CODING_COGNITIVE_OVERLAY",
    "CODING_SYSTEM_PROMPT",
    "ChangePlan",
    "ChangeRisk",
    "CodingCognitiveStrategy",
    "CodingControlPlane",
    "CodingError",
    "CodingLLMAdapter",
    "CodingLoop",
    "CodingPatch",
    "CodingPhase",
    "CodingPlan",
    "CodingSession",
    "CodingStep",
    "CodingStore",
    "CodingTaskType",
    "CodingTurn",
    "CodingWorker",
    "DiffReviewArtifact",
    "FakeLLM",
    "FileChange",
    "GATED_CAPS",
    "LoopResult",
    "Mission",
    "ParsedCapability",
    "PatchError",
    "RepoSemanticMap",
    "SemanticMapBuilder",
    "SessionStatus",
    "StepKind",
    "StepStatus",
    "TERMINAL_STATUSES",
    "WorkspaceTransaction",
    "apply_unified_diff",
    "build_change_plan",
    "build_diff_review",
    "build_initial_plan",
    "build_multi_agent_review_dag",
    "classify_coding_task",
    "coding_cognitive_overlay",
    "coding_system_prompt",
    "confine",
    "discover_project_tooling",
    "enforce_capability",
    "extract_capabilities",
    "extract_structured_capabilities",
    "is_denied",
    "list_entries",
    "mission_from_text",
    "parse_unified_diff",
    "resolve_root",
    "search_files",
    "select_adaptive_verification",
    "strip_capabilities",
]
