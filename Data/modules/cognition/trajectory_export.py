"""Public cognitive trajectory export → training bridge (F14 / R22).

Exports structured *public* cognition (no private CoT) for governed SFT/DPO
ingestion. Unverified output is never training truth; nothing auto-promotes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .types import CognitiveRunStatus


SCHEMA_VERSION = "1"

# Keep in sync with experience.ACTIVE_LEARNING_TRIGGERS (avoid circular import).
_KNOWN_AL_TRIGGERS = frozenset(
    {
        "verification_failed",
        "high_uncertainty",
        "run_failed",
        "contradiction_dense",
        "low_evidence_research",
        "budget_exhausted",
        "partial_completion",
        "repeated_critic_replan",
        "user_correction",
        "capability_blocked",
        "unresolved_hypotheses",
        "timeout",
        "unspecified",
    }
)

# Private CoT / provider thinking channels — never enter training export.
_PRIVATE_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "reasoning_text",
        "thinking",
        "thinking_content",
        "encrypted_content",
        "private_cot",
        "chain_of_thought",
        "hidden_reasoning",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def scrub_private_fields(value: Any) -> Any:
    """Recursively drop private CoT keys from nested public payloads."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key in _PRIVATE_KEYS or key.startswith("private_"):
                continue
            out[key] = scrub_private_fields(v)
        return out
    if isinstance(value, list):
        return [scrub_private_fields(v) for v in value]
    if isinstance(value, tuple):
        return [scrub_private_fields(v) for v in value]
    return value


def _content_hash(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass
class PublicCognitiveTrajectory:
    """One run's public trajectory suitable for governed training ingestion."""

    trajectory_id: str
    run_id: str
    task_id: str | None
    domain: str
    goal: str
    status: str
    mode: str | None = None
    strategy: str | None = None
    neural_effort: str | None = None
    expected_gain: float | None = None
    verification_status: str = "UNMEASURED"
    messages: list[dict[str, str]] = field(default_factory=list)
    action_summaries: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    reasoning_state: dict[str, Any] = field(default_factory=dict)
    hypothesis_board: dict[str, Any] = field(default_factory=dict)
    critic_report: dict[str, Any] | None = None
    experience_id: str | None = None
    admitted: bool = False
    export_class: str = "unverified_excluded"
    # verified_sft | preference_candidate | active_learning | unverified_excluded
    created_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        body = scrub_private_fields(
            {
                "trajectory_id": self.trajectory_id,
                "run_id": self.run_id,
                "task_id": self.task_id,
                "domain": self.domain,
                "goal": self.goal,
                "status": self.status,
                "mode": self.mode,
                "strategy": self.strategy,
                "neural_effort": self.neural_effort,
                "expected_gain": self.expected_gain,
                "verification_status": self.verification_status,
                "messages": list(self.messages),
                "action_summaries": list(self.action_summaries),
                "evidence_refs": list(self.evidence_refs),
                "reasoning_state": dict(self.reasoning_state),
                "hypothesis_board": dict(self.hypothesis_board),
                "critic_report": self.critic_report,
                "experience_id": self.experience_id,
                "admitted": self.admitted,
                "export_class": self.export_class,
                "created_at": self.created_at,
                "metadata": dict(self.metadata),
                "schema_version": SCHEMA_VERSION,
            }
        )
        body["content_hash"] = _content_hash(body)
        body["truth"] = {
            "public_trajectory_only": True,
            "no_private_cot": True,
            "unverified_is_not_training_truth": True,
            "auto_promote_forbidden": True,
            "requires_human_or_policy_approval": True,
            "structured_trajectory_bridge": True,
        }
        return body

    def to_canonical_record(self) -> dict[str, Any]:
        """Dataset-shaped record (id/text/messages/metadata) — not yet ingested."""
        pub = self.public_dict()
        text_parts = [f"Goal: {self.goal}"]
        if self.action_summaries:
            text_parts.append("Actions: " + " → ".join(self.action_summaries[:24]))
        assistant = ""
        for msg in self.messages:
            if msg.get("role") == "assistant":
                assistant = str(msg.get("content") or "")
                break
        if assistant:
            text_parts.append(f"Response: {assistant[:2000]}")
        return scrub_private_fields(
            {
                "id": self.trajectory_id,
                "text": "\n".join(text_parts),
                "messages": list(self.messages),
                "labels": {
                    "export_class": self.export_class,
                    "verification_status": self.verification_status,
                    "admitted": self.admitted,
                    "domain": self.domain,
                    "mode": self.mode,
                    "strategy": self.strategy,
                },
                "metadata": {
                    "source": "cognition_trajectory_export",
                    "run_id": self.run_id,
                    "experience_id": self.experience_id,
                    "content_hash": pub["content_hash"],
                    "schema_version": SCHEMA_VERSION,
                    "auto_promote_forbidden": True,
                    "requires_human_or_policy_approval": True,
                },
                "split": None,
                "truth": {
                    "registered_is_not_trained": True,
                    "auto_promote_forbidden": True,
                    "no_private_cot": True,
                },
            }
        )


def _classify_export(
    *,
    admitted: bool,
    verification_status: str,
    status: str,
    has_assistant: bool,
) -> str:
    if admitted and verification_status in {"PASSED", "COMPLETED_VERIFIED", "verified"} and has_assistant:
        return "verified_sft"
    if status in {
        CognitiveRunStatus.FAILED.value,
        CognitiveRunStatus.PARTIAL.value,
        CognitiveRunStatus.TIMEOUT.value,
        CognitiveRunStatus.RESOURCE_EXHAUSTED.value,
    }:
        return "active_learning"
    if verification_status in {"FAILED"}:
        return "preference_candidate"
    return "unverified_excluded"


def build_trajectory_from_run_snapshot(
    snapshot: Mapping[str, Any],
    *,
    experience: Any | None = None,
) -> PublicCognitiveTrajectory:
    """Build a trajectory from a public run snapshot (status/checkpoint dict)."""
    snap = scrub_private_fields(dict(snapshot))
    run_id = str(snap.get("run_id") or "")
    goal = str(snap.get("goal") or (snap.get("task") or {}).get("goal") or "")[:500]
    domain = str(snap.get("domain") or (snap.get("task") or {}).get("domain") or "general")
    status = str(snap.get("status") or "")
    mode = snap.get("mode") or snap.get("effective_mode")
    strategy = snap.get("strategy")
    neural = None
    nb = snap.get("neural_budgets")
    if isinstance(nb, Mapping):
        neural = nb.get("native_effort")
    expected_gain = snap.get("expected_gain")

    exp_map: Mapping[str, Any] | None = None
    if experience is not None:
        if isinstance(experience, Mapping):
            exp_map = experience
        elif hasattr(experience, "public_dict"):
            try:
                exp_map = experience.public_dict()
            except Exception:  # noqa: BLE001
                exp_map = None

    exp_id = None
    admitted = False
    verification = str(snap.get("verification_passed"))
    if verification == "True":
        verification_status = "PASSED"
    elif verification == "False":
        verification_status = "FAILED"
    else:
        verification_status = "UNMEASURED"

    exp_mode = mode
    exp_neural = neural
    exp_gain = expected_gain
    exp_actions: list[str] = []
    exp_evidence: list[str] = []
    if exp_map is not None:
        exp_id = exp_map.get("experience_id")
        admitted = bool(exp_map.get("admitted"))
        verification_status = str(exp_map.get("verification_status") or verification_status)
        strategy = strategy or exp_map.get("strategy")
        domain = str(exp_map.get("domain") or domain)
        goal = str(exp_map.get("task_summary") or goal)
        exp_mode = exp_map.get("mode") or exp_mode
        exp_neural = exp_map.get("neural_effort") or exp_neural
        if exp_map.get("expected_gain") is not None:
            exp_gain = exp_map.get("expected_gain")
        exp_actions = [str(x) for x in (exp_map.get("action_sequence_summary") or [])]
        exp_evidence = [str(x) for x in (exp_map.get("evidence_refs") or [])]

    response = snap.get("response") or snap.get("response_text")
    if not response and isinstance(snap.get("response_preview"), str):
        # Prefer full response; preview alone is insufficient for strong SFT.
        response = None
    messages: list[dict[str, str]] = []
    if goal:
        messages.append({"role": "user", "content": goal})
    if response:
        messages.append({"role": "assistant", "content": str(response)[:8000]})

    actions = snap.get("actions") or []
    action_summaries: list[str] = []
    for a in actions:
        if isinstance(a, Mapping):
            action_summaries.append(str(a.get("kind") or a.get("action") or ""))
        else:
            action_summaries.append(str(getattr(a, "kind", a)))
    if not action_summaries:
        action_summaries = exp_actions

    evidence: list[str] = []
    for o in snap.get("observations") or []:
        if isinstance(o, Mapping):
            evidence.extend(str(r) for r in (o.get("evidence_refs") or []))
    if not evidence:
        evidence = exp_evidence

    rs = snap.get("reasoning_state")
    if not isinstance(rs, Mapping):
        rs = {}
    hb = snap.get("hypothesis_board")
    if not isinstance(hb, Mapping):
        hb = {}

    export_class = _classify_export(
        admitted=admitted,
        verification_status=verification_status,
        status=status,
        has_assistant=bool(response),
    )

    return PublicCognitiveTrajectory(
        trajectory_id=str(uuid.uuid4()),
        run_id=run_id,
        task_id=str(snap.get("task_id") or "") or None,
        domain=domain,
        goal=goal,
        status=status,
        mode=str(exp_mode) if exp_mode is not None else None,
        strategy=str(strategy) if strategy is not None else None,
        neural_effort=str(exp_neural) if exp_neural is not None else None,
        expected_gain=float(exp_gain) if exp_gain is not None else None,
        verification_status=verification_status,
        messages=messages,
        action_summaries=[s for s in action_summaries if s],
        evidence_refs=evidence,
        reasoning_state=dict(rs),
        hypothesis_board=dict(hb),
        critic_report=snap.get("critic_report") if isinstance(snap.get("critic_report"), dict) else None,
        experience_id=str(exp_id) if exp_id else None,
        admitted=admitted,
        export_class=export_class,
        metadata={
            "shadow": bool(snap.get("shadow")),
            "completion": snap.get("completion"),
        },
    )


def build_trajectory_from_experience(
    experience: Any,
    *,
    response_text: str | None = None,
    run_id: str | None = None,
) -> PublicCognitiveTrajectory:
    """Thin trajectory from an admitted/rejected experience (optional response)."""
    if isinstance(experience, Mapping):
        data = dict(experience)
    elif hasattr(experience, "public_dict"):
        data = dict(experience.public_dict())
    else:
        raise TypeError("experience must provide public_dict() or be a mapping")

    task_summary = str(data.get("task_summary") or "")
    messages: list[dict[str, str]] = [{"role": "user", "content": task_summary}]
    if response_text:
        messages.append({"role": "assistant", "content": response_text[:8000]})
    admitted = bool(data.get("admitted"))
    verification_status = str(data.get("verification_status") or "UNMEASURED")
    outcome = str(data.get("outcome") or "")
    export_class = _classify_export(
        admitted=admitted,
        verification_status=verification_status,
        status=outcome,
        has_assistant=bool(response_text),
    )
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return PublicCognitiveTrajectory(
        trajectory_id=str(uuid.uuid4()),
        run_id=run_id or str(meta.get("run_id") or ""),
        task_id=None,
        domain=str(data.get("domain") or "general"),
        goal=task_summary,
        status=outcome,
        mode=data.get("mode"),
        strategy=data.get("strategy"),
        neural_effort=data.get("neural_effort"),
        expected_gain=data.get("expected_gain"),
        verification_status=verification_status,
        messages=messages,
        action_summaries=[str(x) for x in (data.get("action_sequence_summary") or [])],
        evidence_refs=[str(x) for x in (data.get("evidence_refs") or [])],
        experience_id=str(data.get("experience_id") or "") or None,
        admitted=admitted,
        export_class=export_class,
        metadata={"source": "verified_experience"},
    )


class TrajectoryExportBridge:
    """Bridge: public trajectories → training-ready export bundle (never auto-trains)."""

    def __init__(self) -> None:
        self._trajectories: dict[str, PublicCognitiveTrajectory] = {}

    def record(self, trajectory: PublicCognitiveTrajectory) -> PublicCognitiveTrajectory:
        self._trajectories[trajectory.trajectory_id] = trajectory
        return trajectory

    def list_trajectories(
        self,
        *,
        export_class: str | None = None,
        admitted_only: bool = False,
    ) -> list[PublicCognitiveTrajectory]:
        items = list(self._trajectories.values())
        if admitted_only:
            items = [t for t in items if t.admitted]
        if export_class is not None:
            items = [t for t in items if t.export_class == export_class]
        return items

    def export_bundle(
        self,
        trajectories: Sequence[PublicCognitiveTrajectory] | None = None,
        *,
        active_learning: Sequence[Mapping[str, Any]] | None = None,
        include_excluded: bool = False,
    ) -> dict[str, Any]:
        """Produce a governed training export package.

        Does not write datasets or start training jobs.
        """
        items = list(trajectories) if trajectories is not None else list(self._trajectories.values())
        if not include_excluded:
            items = [t for t in items if t.export_class != "unverified_excluded"]

        sft_records = [
            t.to_canonical_record()
            for t in items
            if t.export_class == "verified_sft"
        ]
        preference_seeds = [
            scrub_private_fields(
                {
                    "trajectory_id": t.trajectory_id,
                    "run_id": t.run_id,
                    "prompt": t.goal,
                    "rejected_preview": next(
                        (m.get("content") for m in t.messages if m.get("role") == "assistant"),
                        None,
                    ),
                    "verification_status": t.verification_status,
                    "source": "cognition_trajectory",
                    "requires_human_or_policy_approval": True,
                    "auto_promote_forbidden": True,
                    "preferred_id": None,  # operator must supply preferred
                    "truth": {
                        "preference_labels_not_fabricated": True,
                        "registered_is_not_trained": True,
                    },
                }
            )
            for t in items
            if t.export_class in {"preference_candidate", "active_learning"}
        ]

        al_payload = []
        for c in active_learning or []:
            reason = str(c.get("reason") or "unspecified")
            al_payload.append(
                scrub_private_fields(
                    {
                        **dict(c),
                        "trigger_known": reason in _KNOWN_AL_TRIGGERS,
                        "auto_promote_forbidden": True,
                        "requires_human_or_policy_approval": True,
                        "source": c.get("source") or "active_learning",
                    }
                )
            )

        bundle = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": _now(),
            "trajectory_count": len(items),
            "sft_record_count": len(sft_records),
            "preference_seed_count": len(preference_seeds),
            "active_learning_count": len(al_payload),
            "trajectories": [t.public_dict() for t in items],
            "sft_records": sft_records,
            "preference_seeds": preference_seeds,
            "active_learning": al_payload,
            "ingestion": {
                "status": "exported_not_ingested",
                "auto_promote_forbidden": True,
                "requires_human_or_policy_approval": True,
                "dataset_write_requires_explicit_step": True,
                "training_job_requires_explicit_step": True,
            },
            "truth": {
                "structured_trajectory_bridge": True,
                "public_trajectory_only": True,
                "no_private_cot": True,
                "unverified_is_not_training_truth": True,
                "auto_promote_forbidden": True,
                "export_is_not_training": True,
                "registered_is_not_trained": True,
            },
        }
        return scrub_private_fields(bundle)
