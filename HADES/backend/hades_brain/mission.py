"""Mission views, single owner, cross-domain refs. No full-transcript dumps."""

from __future__ import annotations

from typing import Any

from capability_intel.collaboration import MissionState, compact_handoff

from .contracts import ContentRef


ROLE_VIEWS: dict[str, tuple[str, ...]] = {
    "coding.test_engineer": ("diff_refs", "impacted_tests", "acceptance"),
    "coding.investigator": ("goal", "file_refs", "open_questions"),
    "trading.validator": ("evaluation_report", "experiment_refs", "acceptance"),
    "media.editor": ("storyboard_ref", "asset_refs", "render_constraints"),
    "research.worker": ("question", "source_refs", "citation_budget"),
    "chat.assistant": ("goal", "summary_ref", "acceptance"),
}


def ensure_owner(mission: MissionState, owner: str | None = None) -> MissionState:
    if not getattr(mission, "mutation_owner", None):
        mission.mutation_owner = owner or "hades.brain"
    return mission


def compile_role_view(mission: MissionState, *, role: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Role-specific bounded view. Never the entire mission transcript."""
    extra = extra or {}
    keys = ROLE_VIEWS.get(role) or ("goal", "acceptance", "artifact_refs", "evidence_refs")
    handoff = compact_handoff(mission, task=str(extra.get("task") or role), extra=extra)
    view: dict[str, Any] = {
        "role": role,
        "full_mission": False,
        "full_transcript": False,
        "owner": mission.mutation_owner,
        "goal": mission.goal,
    }
    mapping = {
        "goal": mission.goal,
        "acceptance": handoff.get("acceptance") or [],
        "artifact_refs": handoff.get("artifact_refs") or [],
        "evidence_refs": handoff.get("evidence_refs") or [],
        "diff_refs": extra.get("diff_refs") or [item for item in mission.artifacts if "diff" in str(item).lower()],
        "impacted_tests": extra.get("impacted_tests") or [],
        "file_refs": extra.get("file_refs") or [],
        "open_questions": list(mission.open_questions[-8:]),
        "evaluation_report": extra.get("evaluation_report") or extra.get("run_ref"),
        "experiment_refs": extra.get("experiment_refs") or [],
        "storyboard_ref": extra.get("storyboard_ref"),
        "asset_refs": extra.get("asset_refs") or [],
        "render_constraints": extra.get("render_constraints") or [],
        "question": extra.get("question") or mission.goal,
        "source_refs": extra.get("source_refs") or list(mission.evidence[-8:]),
        "citation_budget": extra.get("citation_budget") or 8,
        "summary_ref": extra.get("summary_ref"),
    }
    for key in keys:
        view[key] = mapping.get(key)
    view["handoff"] = {k: handoff[k] for k in ("goal", "task", "relevant_findings", "acceptance", "artifact_refs", "evidence_refs", "known_risks") if k in handoff}
    return view


def cross_domain_handoff(
    *,
    from_domain: str,
    to_domain: str,
    goal: str,
    artifact_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    summary: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = extra or {}
    if extra.get("transcript") or extra.get("full_mission"):
        extra = {k: v for k, v in extra.items() if k not in {"transcript", "full_mission", "messages"}}
    return {
        "message_type": "task_handoff",
        "from_domain": from_domain,
        "to_domain": to_domain,
        "goal": goal,
        "summary": summary[:500],
        "artifact_refs": list(artifact_refs or []),
        "evidence_refs": list(evidence_refs or []),
        "full_transcript": False,
        "content_refs": [
            ContentRef(kind="artifact_ref", value=item).to_dict() for item in (artifact_refs or [])
        ]
        + [ContentRef(kind="evidence_ref", value=item).to_dict() for item in (evidence_refs or [])],
        "extras": extra,
    }


def compose_domain_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Focused composition fixture: refs/deltas only between domains."""
    out: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for step in steps:
        payload = dict(step)
        if previous:
            payload.setdefault("artifact_refs", previous.get("produces") or previous.get("artifact_refs") or [])
            payload["upstream_transcript"] = False
        out.append(payload)
        previous = payload
    return out
