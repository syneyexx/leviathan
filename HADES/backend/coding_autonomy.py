"""Coding autonomy profiles — skill ≠ permission.

Profiles control what the Coding Agent may do locally. External publish/push/merge
remain under existing authorization and are never granted by a benchmark score.
"""

from __future__ import annotations

from typing import Any


CODING_AUTONOMY_PROFILES = (
    "analyze_only",
    "managed_workspace_modify",
    "reviewable_result",
)

# Conceptual frontier levels mapped onto existing profiles — no implicit privilege escalation.
FRONTIER_AUTONOMY_LEVELS = {
    "READ_ONLY": "analyze_only",
    "PLAN_ONLY": "analyze_only",
    "PATCH_IN_SANDBOX": "managed_workspace_modify",
    "VERIFY_IN_SANDBOX": "managed_workspace_modify",
    "APPLY_WITH_APPROVAL": "reviewable_result",
    "AUTHORIZED_AUTONOMOUS_APPLY": "reviewable_result",  # still requires apply endpoint approval
}

CODING_AUTONOMY_VERSION = "coding_autonomy_v1"

# Task-type suitability is advisory — success on bugfix does not prove migration skill.
TASK_TYPE_SUITABILITY = {
    "simple_local_bugfix": {
        "default_profile": "managed_workspace_modify",
        "may_recommend_reviewable": True,
    },
    "multi_module_change": {
        "default_profile": "reviewable_result",
        "may_recommend_reviewable": True,
    },
    "dependency_change": {
        "default_profile": "analyze_only",
        "may_recommend_reviewable": False,
        "note": "Dependency changes require explicit human approval beyond profile.",
    },
    "database_migration": {
        "default_profile": "analyze_only",
        "may_recommend_reviewable": False,
    },
    "security_or_permissions": {
        "default_profile": "analyze_only",
        "may_recommend_reviewable": False,
        "note": "Security/permission changes never auto-escalate.",
    },
}


def normalize_coding_autonomy(value: str | None) -> str:
    raw = (value or "reviewable_result").strip()
    mapped = FRONTIER_AUTONOMY_LEVELS.get(raw.upper())
    if mapped:
        return mapped
    raw = raw.lower()
    if raw in {"analyze", "analyze-only", "analyse_only", "read_only", "readonly", "plan_only"}:
        return "analyze_only"
    if raw in {"managed", "workspace", "managed_workspace", "local_modify", "patch_in_sandbox", "verify_in_sandbox"}:
        return "managed_workspace_modify"
    if raw in {"reviewable", "review", "prepare_review", "reviewable_result", "apply_with_approval"}:
        return "reviewable_result"
    if raw in CODING_AUTONOMY_PROFILES:
        return raw
    return "reviewable_result"


def profile_policy(profile: str | None) -> dict[str, Any]:
    p = normalize_coding_autonomy(profile)
    if p == "analyze_only":
        return {
            "profile": p,
            "version": CODING_AUTONOMY_VERSION,
            "allow_explore": True,
            "allow_investigate": True,
            "allow_workspace_edits": False,
            "allow_run_tests": True,
            "allow_apply_to_source": False,
            "allow_external_publish": False,
            "produce_report": True,
            "frontier_level": "READ_ONLY",
            "description": "Analyze and propose only — no edits in managed workspace.",
        }
    if p == "managed_workspace_modify":
        return {
            "profile": p,
            "version": CODING_AUTONOMY_VERSION,
            "allow_explore": True,
            "allow_investigate": True,
            "allow_workspace_edits": True,
            "allow_run_tests": True,
            "allow_apply_to_source": False,
            "allow_external_publish": False,
            "produce_report": True,
            "frontier_level": "VERIFY_IN_SANDBOX",
            "description": "Modify and test only inside a managed worktree/copy.",
        }
    return {
        "profile": "reviewable_result",
        "version": CODING_AUTONOMY_VERSION,
        "allow_explore": True,
        "allow_investigate": True,
        "allow_workspace_edits": True,
        "allow_run_tests": True,
        "allow_apply_to_source": False,  # still requires explicit approve on apply endpoint
        "allow_external_publish": False,
        "produce_report": True,
        "frontier_level": "APPLY_WITH_APPROVAL",
        "description": "Prepare a reviewable result (diff + tests + delivery); apply remains gated.",
    }


def recommend_profile(
    *,
    task_kind: str,
    measured_pass_rate: float | None = None,
    human_usable_rate: float | None = None,
    regressions: int = 0,
) -> dict[str, Any]:
    """Advisory recommendation only — never auto-activates higher autonomy."""
    base = TASK_TYPE_SUITABILITY.get(task_kind) or {
        "default_profile": "analyze_only",
        "may_recommend_reviewable": False,
    }
    recommended = base["default_profile"]
    reasons: list[str] = []
    if regressions > 0:
        recommended = "analyze_only"
        reasons.append("quality_regression_fallback")
    elif (
        base.get("may_recommend_reviewable")
        and measured_pass_rate is not None
        and measured_pass_rate >= 0.8
        and human_usable_rate is not None
        and human_usable_rate >= 0.7
    ):
        recommended = "reviewable_result"
        reasons.append("measured_quality_supports_reviewable")
    else:
        reasons.append("default_for_task_kind")
    return {
        "task_kind": task_kind,
        "recommended_profile": recommended,
        "activation": "explicit_user_opt_in",
        "revocable": True,
        "visible": True,
        "reasons": reasons,
        "note": "Benchmark score does not grant permissions. External publish stays blocked.",
        "version": CODING_AUTONOMY_VERSION,
    }
