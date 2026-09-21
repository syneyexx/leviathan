"""Structured agent-to-agent collaboration: messages, mission state, budgets, loops."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .store import append_message, load_messages, load_mission, save_mission
from .taxonomy import DEFAULT_BUDGETS, MESSAGE_TYPES


INJECTION_MARKERS = (
    "ignore previous",
    "ignore all instructions",
    "you are now",
    "system prompt",
    "override policy",
    "grant approval",
    "disable trust",
    "jailbreak",
)


@dataclass(slots=True)
class CollaborationMessage:
    message_id: str
    mission_id: str
    sender: str
    recipient: str
    task_id: str
    message_type: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "ok"
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MissionState:
    mission_id: str
    goal: str
    requirements: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    assignments: dict[str, str] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    tool_observations: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_BUDGETS))
    usage: dict[str, int] = field(default_factory=lambda: {"agents": 0, "messages": 0, "consultations": 0, "critique_cycles": 0, "model_calls": 0, "retries": 0})
    mutation_owner: str | None = None
    locked_paths: list[str] = field(default_factory=list)
    visit_graph: dict[str, int] = field(default_factory=dict)
    dead_providers: list[str] = field(default_factory=list)
    completed_work: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "MissionState":
        return cls(
            mission_id=str(raw.get("mission_id") or ""),
            goal=str(raw.get("goal") or ""),
            requirements=list(raw.get("requirements") or []),
            plan=list(raw.get("plan") or []),
            facts=list(raw.get("facts") or []),
            decisions=list(raw.get("decisions") or []),
            open_questions=list(raw.get("open_questions") or []),
            assignments=dict(raw.get("assignments") or {}),
            artifacts=list(raw.get("artifacts") or []),
            evidence=list(raw.get("evidence") or []),
            tool_observations=list(raw.get("tool_observations") or []),
            verification=dict(raw.get("verification") or {}),
            status=str(raw.get("status") or "active"),
            budgets=dict(raw.get("budgets") or DEFAULT_BUDGETS),
            usage=dict(raw.get("usage") or {}),
            mutation_owner=raw.get("mutation_owner"),
            locked_paths=list(raw.get("locked_paths") or []),
            visit_graph=dict(raw.get("visit_graph") or {}),
            dead_providers=list(raw.get("dead_providers") or []),
            completed_work=list(raw.get("completed_work") or []),
        )


def _contains_injection(text: str) -> bool:
    sample = (text or "").lower()
    return any(marker in sample for marker in INJECTION_MARKERS)


def validate_message(
    raw: dict[str, Any],
    *,
    mission: MissionState,
    runtime_sender: str,
) -> tuple[CollaborationMessage | None, str]:
    message_type = str(raw.get("message_type") or raw.get("type") or "").strip()
    if message_type not in MESSAGE_TYPES:
        return None, "invalid_message_type"
    claimed_sender = str(raw.get("sender") or "").strip()
    if claimed_sender and claimed_sender != runtime_sender:
        return None, "sender_spoof_rejected"
    recipient = str(raw.get("recipient") or "").strip()
    if not recipient:
        return None, "missing_recipient"
    if str(raw.get("mission_id") or mission.mission_id) != mission.mission_id:
        return None, "mission_scope_mismatch"
    blob = f"{raw.get('summary') or ''} {raw.get('payload') or ''}"
    status = "ok"
    if _contains_injection(blob):
        status = "untrusted_injection_ignored"
    message = CollaborationMessage(
        message_id=str(raw.get("message_id") or uuid.uuid4()),
        mission_id=mission.mission_id,
        sender=runtime_sender,
        recipient=recipient,
        task_id=str(raw.get("task_id") or ""),
        message_type=message_type,
        summary=str(raw.get("summary") or "")[:500],
        payload=dict(raw.get("payload") or {}) if isinstance(raw.get("payload"), dict) else {},
        artifact_refs=list(raw.get("artifact_refs") or []),
        evidence_refs=list(raw.get("evidence_refs") or []),
        status=status,
    )
    return message, "ok"


def compact_handoff(mission: MissionState, *, task: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    return {
        "goal": mission.goal,
        "task": task,
        "relevant_findings": list(mission.facts[-8:]),
        "acceptance": list(mission.verification.get("acceptance") or []),
        "artifact_refs": list(mission.artifacts[-8:]),
        "evidence_refs": list(mission.evidence[-8:]),
        "known_risks": list(mission.verification.get("risks") or []),
        "completed_work": list(mission.completed_work),
        **extra,
    }


def targeted_consultation_context(question: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "question": question,
        "evidence": list(evidence or [])[:12],
        "full_mission": False,
        "instruction": "Return a structured finding. Do not request the entire mission.",
    }


class CollaborationSession:
    def __init__(self, mission: MissionState, *, db: Any | None = None) -> None:
        self.mission = mission
        self.db = db
        self.messages: list[CollaborationMessage] = []
        if db is not None:
            saved = load_mission(db, mission.mission_id)
            if saved:
                self.mission = MissionState.from_mapping(saved)
            for raw in load_messages(db, mission.mission_id):
                self.messages.append(
                    CollaborationMessage(
                        message_id=str(raw.get("message_id") or ""),
                        mission_id=str(raw.get("mission_id") or mission.mission_id),
                        sender=str(raw.get("sender") or ""),
                        recipient=str(raw.get("recipient") or ""),
                        task_id=str(raw.get("task_id") or ""),
                        message_type=str(raw.get("message_type") or ""),
                        summary=str(raw.get("summary") or ""),
                        payload=dict(raw.get("payload") or {}),
                        artifact_refs=list(raw.get("artifact_refs") or []),
                        evidence_refs=list(raw.get("evidence_refs") or []),
                        status=str(raw.get("status") or "ok"),
                        timestamp=str(raw.get("timestamp") or ""),
                    )
                )

    def persist(self) -> None:
        if self.db is None:
            return
        save_mission(self.db, self.mission.mission_id, self.mission.to_dict(), self.mission.status)

    def _budget_ok(self, key: str) -> bool:
        used = int(self.mission.usage.get(key) or 0)
        limit = int(self.mission.budgets.get(f"max_{key}", self.mission.budgets.get(key, 0)) or 0)
        if key == "messages":
            limit = int(self.mission.budgets.get("max_messages") or 0)
        if key == "agents":
            limit = int(self.mission.budgets.get("max_agents") or 0)
        if key == "consultations":
            limit = int(self.mission.budgets.get("max_consultations") or 0)
        if key == "critique_cycles":
            limit = int(self.mission.budgets.get("max_critique_cycles") or 0)
        if key == "model_calls":
            limit = int(self.mission.budgets.get("max_model_calls") or 0)
        return used < limit if limit else True

    def _visit_key(self, sender: str, recipient: str, summary: str) -> str:
        digest = hashlib.sha256(f"{sender}|{recipient}|{summary}".encode("utf-8")).hexdigest()[:16]
        return f"{sender}->{recipient}:{digest}"

    def post(self, raw: dict[str, Any], *, runtime_sender: str) -> CollaborationMessage:
        if self.mission.status in {"cancelled", "deadlock", "budget_exhausted"}:
            raise RuntimeError(self.mission.status)
        if not self._budget_ok("messages"):
            self.mission.status = "budget_exhausted"
            self.persist()
            raise RuntimeError("budget_exhausted")
        message, reason = validate_message(raw, mission=self.mission, runtime_sender=runtime_sender)
        if message is None:
            raise ValueError(reason)
        visit = self._visit_key(message.sender, message.recipient, message.summary)
        self.mission.visit_graph[visit] = int(self.mission.visit_graph.get(visit) or 0) + 1
        reverse = self._visit_key(message.recipient, message.sender, message.summary)
        if int(self.mission.visit_graph.get(visit) or 0) >= 3 and int(self.mission.visit_graph.get(reverse) or 0) >= 2:
            self.mission.status = "deadlock"
            self.persist()
            raise RuntimeError("deadlock")
        if message.message_type == "critique":
            self.mission.usage["critique_cycles"] = int(self.mission.usage.get("critique_cycles") or 0) + 1
            if not self._budget_ok("critique_cycles"):
                self.mission.status = "budget_exhausted"
                self.persist()
                raise RuntimeError("budget_exhausted")
        if message.message_type == "question":
            self.mission.usage["consultations"] = int(self.mission.usage.get("consultations") or 0) + 1
        self.mission.usage["messages"] = int(self.mission.usage.get("messages") or 0) + 1
        if message.message_type == "finding" and message.summary:
            self.mission.facts.append(message.summary)
        if message.message_type == "completed":
            self.mission.completed_work.append(message.summary or message.task_id)
        self.messages.append(message)
        if self.db is not None:
            append_message(self.db, self.mission.mission_id, message.message_id, message.to_dict())
        self.persist()
        return message

    def cancel(self) -> None:
        self.mission.status = "cancelled"
        self.persist()

    def restart(self) -> MissionState:
        """Honest restart: keep completed work, drop in-flight chatter."""
        self.mission.status = "active"
        self.mission.usage["messages"] = 0
        self.mission.usage["consultations"] = 0
        self.mission.usage["critique_cycles"] = 0
        self.mission.visit_graph = {}
        self.mission.open_questions = []
        self.persist()
        return self.mission
