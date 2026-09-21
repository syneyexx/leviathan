"""Long-task resume without double work (work package I).

Reliable identity linking (mission/task/run/step/artifact), side-effect
idempotency + reconcile, fencing/CAS for leases, and honest recovery when
evidence is missing. Does not claim universal exactly-once for external tools.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EffectStatus = Literal[
    "intended",
    "in_flight",
    "completed",
    "failed",
    "unresolved",
    "skipped_reconciled",
    "rejected_stale_fence",
]

ResumeAction = Literal[
    "reuse_completed",
    "resume_from_checkpoint",
    "reconcile_then_maybe_retry",
    "mark_unresolved",
    "skip_invalidated",
    "await_live_worker",
    "requeue_orphaned_running",
]


def _now() -> float:
    return time.time()


def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_idempotency_key(
    *,
    run_id: str,
    step_id: str,
    effect_kind: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """Stable key for durable intent. Same logical effect → same key."""
    blob = json.dumps(
        {"run_id": run_id, "step_id": step_id, "kind": effect_kind, "payload": payload or {}},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    return f"idem:{run_id}:{step_id}:{effect_kind}:{digest}"


@dataclass(slots=True)
class RunIdentity:
    """Canonical relation between mission / task / run / step / artifact ids."""

    mission_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)
    fence_token: str | None = None
    plan_version: int = 1
    generation: int = 1

    def bind(
        self,
        *,
        mission_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        step_id: str | None = None,
        artifact_id: str | None = None,
        fence_token: str | None = None,
        plan_version: int | None = None,
        generation: int | None = None,
    ) -> "RunIdentity":
        if mission_id is not None:
            self.mission_id = mission_id
        if task_id is not None:
            self.task_id = task_id
        if run_id is not None:
            self.run_id = run_id
        if step_id is not None:
            self.step_id = step_id
        if artifact_id:
            if artifact_id not in self.artifact_ids:
                self.artifact_ids.append(artifact_id)
        if fence_token is not None:
            self.fence_token = fence_token
        if plan_version is not None:
            self.plan_version = int(plan_version)
        if generation is not None:
            self.generation = int(generation)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RunIdentity":
        raw = dict(raw or {})
        return cls(
            mission_id=raw.get("mission_id"),
            task_id=raw.get("task_id"),
            run_id=raw.get("run_id"),
            step_id=raw.get("step_id"),
            artifact_ids=list(raw.get("artifact_ids") or []),
            fence_token=raw.get("fence_token"),
            plan_version=int(raw.get("plan_version") or 1),
            generation=int(raw.get("generation") or 1),
        )


@dataclass(slots=True)
class SideEffectIntent:
    """Durable intent recorded before an external/mutating effect."""

    intent_id: str
    idempotency_key: str
    effect_kind: str
    identity: dict[str, Any]
    payload_digest: str
    status: EffectStatus = "intended"
    fence_token: str = ""
    generation: int = 1
    result_ref: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SideEffectIntent":
        return cls(
            intent_id=str(raw.get("intent_id") or _short_id("intent")),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            effect_kind=str(raw.get("effect_kind") or ""),
            identity=dict(raw.get("identity") or {}),
            payload_digest=str(raw.get("payload_digest") or ""),
            status=str(raw.get("status") or "intended"),  # type: ignore[arg-type]
            fence_token=str(raw.get("fence_token") or ""),
            generation=int(raw.get("generation") or 1),
            result_ref=raw.get("result_ref"),
            evidence=dict(raw.get("evidence") or {}),
            created_at=float(raw.get("created_at") or _now()),
            updated_at=float(raw.get("updated_at") or _now()),
        )


@dataclass(slots=True)
class ResumeStepDecision:
    step_id: str
    action: ResumeAction
    reason: str
    checkpoint_phase: str | None = None
    prior_status: str | None = None
    intent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResumePlan:
    identity: dict[str, Any]
    decisions: list[ResumeStepDecision]
    reused_step_ids: list[str]
    requeue_step_ids: list[str]
    unresolved_step_ids: list[str]
    invalidated_step_ids: list[str]
    worker_live: bool
    status_label_stale: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": dict(self.identity),
            "decisions": [d.to_dict() for d in self.decisions],
            "reused_step_ids": list(self.reused_step_ids),
            "requeue_step_ids": list(self.requeue_step_ids),
            "unresolved_step_ids": list(self.unresolved_step_ids),
            "invalidated_step_ids": list(self.invalidated_step_ids),
            "worker_live": self.worker_live,
            "status_label_stale": self.status_label_stale,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class ConfirmedOutcome:
    """Same confirmed outcome surface for Mission Control and Tasks."""

    mission_id: str | None
    task_id: str | None
    run_id: str | None
    status: str
    verification_status: str | None
    evidence_refs: list[str]
    step_summary: dict[str, Any]
    confirmed: bool
    source: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SideEffectLedger:
    """CAS/idempotent ledger for side-effect intents.

    Crash between effect and checkpoint: if result evidence exists, mark completed
    without re-exec; if missing, mark unresolved (honest) — never blind replay.

    Optional ``persist_path`` enables crash/restart across separate processes
    (JSON snapshot). Does not claim universal exactly-once for external tools.
    """

    def __init__(self, persist_path: str | None = None) -> None:
        self._by_key: dict[str, SideEffectIntent] = {}
        self._by_id: dict[str, SideEffectIntent] = {}
        self._lock = threading.RLock()
        self._cancel_fences: dict[str, str] = {}  # run_id -> cancel fence
        self._late_artifacts: list[dict[str, Any]] = []
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def set_persist_path(self, path: str | None) -> None:
        with self._lock:
            self._persist_path = path
            if path:
                self._load()

    def _load(self) -> None:
        path = self._persist_path
        if not path:
            return
        try:
            from pathlib import Path

            p = Path(path)
            if not p.is_file():
                return
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        intents = list(raw.get("intents") or [])
        self._by_key.clear()
        self._by_id.clear()
        for row in intents:
            if not isinstance(row, dict):
                continue
            intent = SideEffectIntent.from_dict(row)
            if intent.idempotency_key:
                self._by_key[intent.idempotency_key] = intent
            self._by_id[intent.intent_id] = intent
        self._cancel_fences = {
            str(k): str(v) for k, v in dict(raw.get("cancel_fences") or {}).items()
        }
        self._late_artifacts = list(raw.get("late_artifacts") or [])

    def _restore_durable_state(self) -> None:
        """Rollback in-memory mutations to the last readable persisted snapshot."""
        self._by_key.clear()
        self._by_id.clear()
        self._cancel_fences = {}
        self._late_artifacts = []
        path = self._persist_path
        if not path:
            return
        try:
            from pathlib import Path

            p = Path(path)
            if not p.is_file():
                return
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        for row in list(raw.get("intents") or []):
            if not isinstance(row, dict):
                continue
            intent = SideEffectIntent.from_dict(row)
            if intent.idempotency_key:
                self._by_key[intent.idempotency_key] = intent
            self._by_id[intent.intent_id] = intent
        self._cancel_fences = {
            str(k): str(v) for k, v in dict(raw.get("cancel_fences") or {}).items()
        }
        self._late_artifacts = list(raw.get("late_artifacts") or [])

    def _save(self) -> bool:
        path = self._persist_path
        if not path:
            return True
        tmp = None
        try:
            from pathlib import Path

            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "intents": [i.to_dict() for i in self._by_id.values()],
                "cancel_fences": dict(self._cancel_fences),
                "late_artifacts": list(self._late_artifacts),
                "saved_at": _now(),
                "honesty": {
                    "exactly_once_not_claimed": True,
                    "persistence": "json_snapshot",
                },
            }
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
            return True
        except OSError:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            self._restore_durable_state()
            return False

    def record_intent(
        self,
        *,
        identity: RunIdentity,
        effect_kind: str,
        payload: dict[str, Any] | None = None,
        fence_token: str | None = None,
    ) -> dict[str, Any]:
        if not identity.run_id or not identity.step_id:
            raise ValueError("run_id and step_id required for side-effect intent")
        key = make_idempotency_key(
            run_id=identity.run_id,
            step_id=identity.step_id,
            effect_kind=effect_kind,
            payload=payload,
        )
        digest = hashlib.sha256(
            json.dumps(payload or {}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        fence = fence_token or identity.fence_token or ""
        with self._lock:
            existing = self._by_key.get(key)
            if existing:
                return {
                    "ok": True,
                    "idempotent": True,
                    "intent": existing.to_dict(),
                    "action": "reuse_existing_intent",
                }
            cancel_fence = self._cancel_fences.get(identity.run_id or "")
            if cancel_fence:
                intent = SideEffectIntent(
                    intent_id=_short_id("intent"),
                    idempotency_key=key,
                    effect_kind=effect_kind,
                    identity=identity.to_dict(),
                    payload_digest=digest,
                    status="rejected_stale_fence",
                    fence_token=fence,
                    generation=identity.generation,
                    evidence={"reason": "run_cancelled", "cancel_fence": cancel_fence},
                )
                self._by_key[key] = intent
                self._by_id[intent.intent_id] = intent
                if not self._save():
                    return {"ok": False, "reason": "persistence_failed", "action": "not_recorded"}
                return {
                    "ok": False,
                    "idempotent": False,
                    "intent": intent.to_dict(),
                    "action": "rejected_cancelled",
                }
            intent = SideEffectIntent(
                intent_id=_short_id("intent"),
                idempotency_key=key,
                effect_kind=effect_kind,
                identity=identity.to_dict(),
                payload_digest=digest,
                status="intended",
                fence_token=fence,
                generation=identity.generation,
            )
            self._by_key[key] = intent
            self._by_id[intent.intent_id] = intent
            if not self._save():
                return {"ok": False, "idempotent": False, "reason": "persistence_failed", "action": "not_recorded"}
            return {"ok": True, "idempotent": False, "intent": intent.to_dict(), "action": "recorded"}

    def mark_in_flight(self, intent_id: str, *, fence_token: str | None = None) -> dict[str, Any]:
        with self._lock:
            intent = self._by_id.get(intent_id)
            if not intent:
                return {"ok": False, "reason": "intent_not_found"}
            if fence_token and intent.fence_token and fence_token != intent.fence_token:
                intent.status = "rejected_stale_fence"
                intent.updated_at = _now()
                if not self._save():
                    return {"ok": False, "reason": "persistence_failed"}
                return {"ok": False, "reason": "stale_fence", "intent": intent.to_dict()}
            if intent.status in {"completed", "skipped_reconciled"}:
                return {"ok": True, "idempotent": True, "intent": intent.to_dict()}
            intent.status = "in_flight"
            intent.updated_at = _now()
            if not self._save():
                return {"ok": False, "reason": "persistence_failed"}
            return {"ok": True, "intent": intent.to_dict()}

    def complete(
        self,
        intent_id: str,
        *,
        result_ref: str | None = None,
        evidence: dict[str, Any] | None = None,
        fence_token: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            intent = self._by_id.get(intent_id)
            if not intent:
                return {"ok": False, "reason": "intent_not_found"}
            if fence_token and intent.fence_token and fence_token != intent.fence_token:
                intent.status = "rejected_stale_fence"
                intent.updated_at = _now()
                if not self._save():
                    return {"ok": False, "reason": "persistence_failed"}
                return {"ok": False, "reason": "stale_fence", "intent": intent.to_dict()}
            run_id = str((intent.identity or {}).get("run_id") or "")
            if run_id and run_id in self._cancel_fences:
                intent.status = "rejected_stale_fence"
                intent.evidence = {**intent.evidence, "late_after_cancel": True, **(evidence or {})}
                intent.updated_at = _now()
                self._late_artifacts.append(
                    {
                        "intent_id": intent.intent_id,
                        "result_ref": result_ref,
                        "run_id": run_id,
                        "rejected": True,
                        "at": _now(),
                    }
                )
                if not self._save():
                    return {"ok": False, "reason": "persistence_failed"}
                return {"ok": False, "reason": "cancelled_late_artifact", "intent": intent.to_dict()}
            intent.status = "completed"
            intent.result_ref = result_ref
            intent.evidence = {**intent.evidence, **(evidence or {})}
            intent.updated_at = _now()
            if not self._save():
                return {"ok": False, "reason": "persistence_failed"}
            return {"ok": True, "intent": intent.to_dict()}

    def fail(self, intent_id: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            intent = self._by_id.get(intent_id)
            if not intent:
                return {"ok": False, "reason": "intent_not_found"}
            intent.status = "failed"
            intent.evidence = {**intent.evidence, **(evidence or {})}
            intent.updated_at = _now()
            if not self._save():
                return {"ok": False, "reason": "persistence_failed"}
            return {"ok": True, "intent": intent.to_dict()}

    def reconcile_after_crash(
        self,
        *,
        idempotency_key: str,
        recovered_result_ref: str | None = None,
        recovered_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Recover when process died between effect and checkpoint.

        - If result/effect evidence is recoverable → complete without re-exec.
        - If evidence missing → unresolved (honest); do not blind re-exec.
        """
        with self._lock:
            intent = self._by_key.get(idempotency_key)
            if not intent:
                return {
                    "ok": False,
                    "action": "no_intent",
                    "may_reexec": False,
                    "reason": "no_durable_intent",
                    "note": "Cannot claim prior effect; do not invent success.",
                }
            if intent.status == "completed" and intent.result_ref:
                return {
                    "ok": True,
                    "action": "reuse_completed",
                    "may_reexec": False,
                    "intent": intent.to_dict(),
                    "double_effect_prevented": True,
                }
            if recovered_result_ref or (recovered_evidence and recovered_evidence.get("effect_observed")):
                intent.status = "completed"
                intent.result_ref = recovered_result_ref or intent.result_ref
                intent.evidence = {
                    **intent.evidence,
                    **(recovered_evidence or {}),
                    "reconciled_after_crash": True,
                }
                intent.updated_at = _now()
                if not self._save():
                    return {
                        "ok": False,
                        "action": "persistence_failed",
                        "may_reexec": False,
                        "reason": "snapshot_write_failed",
                    }
                return {
                    "ok": True,
                    "action": "reconciled_completed",
                    "may_reexec": False,
                    "intent": intent.to_dict(),
                    "double_effect_prevented": True,
                }
            if intent.status in {"intended", "in_flight", "failed"}:
                intent.status = "unresolved"
                intent.evidence = {
                    **intent.evidence,
                    "crash_window": True,
                    "evidence_missing": True,
                    **(recovered_evidence or {}),
                }
                intent.updated_at = _now()
                if not self._save():
                    return {
                        "ok": False,
                        "action": "persistence_failed",
                        "may_reexec": False,
                        "reason": "snapshot_write_failed",
                    }
                return {
                    "ok": True,
                    "action": "mark_unresolved",
                    "may_reexec": False,
                    "intent": intent.to_dict(),
                    "note": "Evidence missing after crash; unresolved — no blind re-exec.",
                    "double_effect_prevented": True,
                }
            return {
                "ok": True,
                "action": f"keep_{intent.status}",
                "may_reexec": False,
                "intent": intent.to_dict(),
            }

    def request_cancel(self, run_id: str) -> str:
        fence = f"cancel_{uuid.uuid4().hex[:10]}"
        with self._lock:
            self._cancel_fences[run_id] = fence
            if not self._save():
                raise RuntimeError("side_effect_ledger_persistence_failed:cancel_fence")
        return fence

    def accept_artifact(
        self,
        *,
        run_id: str,
        artifact_id: str,
        fence_token: str | None = None,
        cancel_fence: str | None = None,
    ) -> dict[str, Any]:
        """Reject late artifacts after cancel; accept only when run is not cancelled."""
        with self._lock:
            active_cancel = self._cancel_fences.get(run_id)
            if active_cancel:
                self._late_artifacts.append(
                    {
                        "run_id": run_id,
                        "artifact_id": artifact_id,
                        "rejected": True,
                        "reason": "cancel_fence",
                        "cancel_fence": active_cancel,
                        "provided_cancel_fence": cancel_fence,
                        "at": _now(),
                    }
                )
                persisted = self._save()
                return {
                    "ok": False,
                    "accepted": False,
                    "reason": "cancelled_late_artifact" if persisted else "cancelled_late_artifact_persistence_failed",
                    "cancel_fence": active_cancel,
                }
            return {
                "ok": True,
                "accepted": True,
                "artifact_id": artifact_id,
                "fence_token": fence_token,
            }

    def get_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock:
            intent = self._by_key.get(idempotency_key)
            return intent.to_dict() if intent else None

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [i.to_dict() for i in self._by_id.values() if (i.identity or {}).get("run_id") == run_id]

    def late_artifacts(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._late_artifacts)


def is_worker_live(
    *,
    status: str | None,
    worker_live: bool,
    lease_holder: str | None = None,
    own_worker_id: str | None = None,
    lease_expired: bool = False,
) -> dict[str, Any]:
    """Do not confuse durable 'running' label with a live owned process."""
    label = str(status or "")
    owned = bool(own_worker_id and lease_holder and own_worker_id == lease_holder and not lease_expired)
    live = bool(worker_live) and not lease_expired
    stale_label = label in {"running", "pause_requested", "cancel_requested"} and not live
    return {
        "status_label": label,
        "worker_live": live,
        "lease_owned": owned,
        "status_label_stale": stale_label,
        "may_start_new_worker": stale_label or label in {"paused", "interrupted", "queued"},
        "note": (
            "stale_running_label_not_live_process"
            if stale_label
            else ("live_worker" if live else "no_live_worker")
        ),
    }


def build_resume_plan(
    *,
    identity: RunIdentity,
    steps: list[dict[str, Any]],
    completed_ids: set[str] | None = None,
    invalidated_ids: set[str] | None = None,
    intents: list[dict[str, Any]] | None = None,
    worker_live: bool = False,
    status_label: str | None = None,
    checkpoint_by_step: dict[str, dict[str, Any]] | None = None,
) -> ResumePlan:
    """Decide what to reuse vs re-run vs leave unresolved after crash/redirect/refresh."""
    completed_ids = set(completed_ids or set())
    invalidated_ids = set(invalidated_ids or set())
    checkpoint_by_step = checkpoint_by_step or {}
    intents_by_step: dict[str, list[dict[str, Any]]] = {}
    for intent in intents or []:
        sid = str((intent.get("identity") or {}).get("step_id") or "")
        if sid:
            intents_by_step.setdefault(sid, []).append(intent)

    live_info = is_worker_live(status=status_label, worker_live=worker_live)
    decisions: list[ResumeStepDecision] = []
    reused: list[str] = []
    requeue: list[str] = []
    unresolved: list[str] = []
    notes: list[str] = []

    if live_info["worker_live"]:
        notes.append("live_worker_present_do_not_start_second")

    for index, step in enumerate(steps):
        sid = str(step.get("step_id") or step.get("id") or f"step-{index + 1}")
        status = str(step.get("status") or "pending")
        cp = checkpoint_by_step.get(sid) or {}
        step_intents = intents_by_step.get(sid) or []

        if sid in invalidated_ids:
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="skip_invalidated",
                    reason="redirect_invalidated_dependent",
                    prior_status=status,
                )
            )
            continue

        if status == "completed" or sid in completed_ids:
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="reuse_completed",
                    reason="independent_completed_step_kept",
                    prior_status=status,
                    checkpoint_phase=str(cp.get("phase") or "") or None,
                )
            )
            reused.append(sid)
            completed_ids.add(sid)
            continue

        if live_info["worker_live"] and status == "running":
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="await_live_worker",
                    reason="browser_refresh_must_not_start_second_worker",
                    prior_status=status,
                )
            )
            continue

        # Crash: was running / in-flight side effect without confirmed completion.
        unresolved_intents = [i for i in step_intents if i.get("status") in {"intended", "in_flight", "unresolved"}]
        completed_intents = [i for i in step_intents if i.get("status") in {"completed", "skipped_reconciled"}]
        if unresolved_intents and not completed_intents:
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="mark_unresolved",
                    reason="effect_without_checkpoint_evidence",
                    prior_status=status,
                    intent_id=str(unresolved_intents[0].get("intent_id") or "") or None,
                    checkpoint_phase=str(cp.get("phase") or "") or None,
                )
            )
            unresolved.append(sid)
            continue

        if completed_intents and status != "completed":
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="reconcile_then_maybe_retry",
                    reason="recover_effect_skip_blind_reexec",
                    prior_status=status,
                    intent_id=str(completed_intents[0].get("intent_id") or "") or None,
                    checkpoint_phase=str(cp.get("phase") or "") or None,
                )
            )
            # Treat as reusable completed effect; dependents may proceed.
            reused.append(sid)
            continue

        if status == "running" and live_info["status_label_stale"]:
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="requeue_orphaned_running",
                    reason="stale_running_label_no_live_process",
                    prior_status=status,
                    checkpoint_phase=str(cp.get("phase") or "") or None,
                )
            )
            requeue.append(sid)
            continue

        if status in {"failed", "error"}:
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="resume_from_checkpoint",
                    reason="failed_step_keeps_inspectable_partials",
                    prior_status=status,
                    checkpoint_phase=str(cp.get("phase") or "") or None,
                )
            )
            requeue.append(sid)
            continue

        if cp.get("phase"):
            decisions.append(
                ResumeStepDecision(
                    step_id=sid,
                    action="resume_from_checkpoint",
                    reason="resumable_checkpoint",
                    prior_status=status,
                    checkpoint_phase=str(cp.get("phase")),
                )
            )
            requeue.append(sid)
            continue

        decisions.append(
            ResumeStepDecision(
                step_id=sid,
                action="resume_from_checkpoint",
                reason="pending_or_incomplete",
                prior_status=status,
            )
        )
        requeue.append(sid)

    return ResumePlan(
        identity=identity.to_dict(),
        decisions=decisions,
        reused_step_ids=sorted(set(reused)),
        requeue_step_ids=requeue,
        unresolved_step_ids=unresolved,
        invalidated_step_ids=sorted(invalidated_ids),
        worker_live=bool(live_info["worker_live"]),
        status_label_stale=bool(live_info["status_label_stale"]),
        notes=notes,
    )


def pause_during_tool_execution(*, phase: str, tool_in_flight: bool) -> dict[str, Any]:
    """Pause request during tool execution: stop new work; finish or fence current effect."""
    if tool_in_flight:
        return {
            "pause_state": "pause_requested",
            "safe_to_mark_paused": False,
            "phase": phase,
            "note": "tool_in_flight_wait_for_boundary_or_reconcile",
            "inflight_side_effects": True,
        }
    return {
        "pause_state": "paused",
        "safe_to_mark_paused": True,
        "phase": phase,
        "note": "safe_boundary",
        "inflight_side_effects": False,
    }


def model_timeout_recovery(*, step_id: str, had_side_effect_intent: bool, result_observed: bool) -> dict[str, Any]:
    if result_observed:
        return {
            "step_id": step_id,
            "action": "checkpoint_completed_from_observation",
            "may_retry_model": False,
            "note": "timeout_after_effect_observed",
        }
    if had_side_effect_intent:
        return {
            "step_id": step_id,
            "action": "mark_unresolved",
            "may_retry_model": False,
            "note": "timeout_with_intent_no_evidence",
        }
    return {
        "step_id": step_id,
        "action": "retry_model_bounded",
        "may_retry_model": True,
        "note": "timeout_before_side_effect",
    }


def collect_inspectable_partials(
    *,
    step_id: str,
    checkpoint: dict[str, Any] | None,
    artifacts: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Failed step leaves inspectable partials (checkpoint + artifacts + error)."""
    cp = dict(checkpoint or {})
    arts = list(artifacts or [])
    return {
        "step_id": step_id,
        "failed": True,
        "checkpoint_phase": cp.get("phase"),
        "checkpoint": cp,
        "partial_artifacts": arts,
        "error": error,
        "inspectable": bool(cp or arts or error),
        "note": "partials_retained_for_inspection",
    }


def confirmed_outcome_from_task_and_mission(
    *,
    task: dict[str, Any] | None,
    mission: dict[str, Any] | None,
) -> ConfirmedOutcome:
    """Mission Control and Tasks must show the same confirmed outcome."""
    task = dict(task or {})
    mission = dict(mission or {})
    task_status = str(task.get("status") or "")
    mission_status = str(mission.get("status") or "")
    verification = dict(mission.get("verification") or task.get("verification") or {})
    ver_status = str(verification.get("status") or "") or None
    evidence_refs = list(verification.get("evidence_refs") or [])
    step_summary = dict(
        (verification.get("step_summary") or {})
        or (mission.get("step_summary") or {})
        or (task.get("step_summary") or {})
    )

    # Prefer evidence-based mission status when linked; otherwise task.
    if mission.get("id") and mission_status:
        status = mission_status
        source = "mission_control"
    else:
        status = task_status
        source = "tasks"

    confirmed = status in {"completed", "failed", "cancelled"} and (
        status != "completed" or ver_status == "passed" or not mission.get("id")
    )
    notes: list[str] = []
    if mission.get("id") and task.get("id"):
        if mission.get("task_id") and str(mission.get("task_id")) != str(task.get("id")):
            notes.append("mission_task_id_mismatch")
            confirmed = False
        if task_status == "completed" and mission_status == "failed":
            notes.append("mission_rejected_task_completed_without_evidence")
            status = "failed"
            confirmed = True
            source = "mission_control"
        elif task_status and mission_status and task_status != mission_status:
            # Align display to mission when verification failed the completion claim.
            if mission_status in {"failed", "blocked", "cancelled"}:
                status = mission_status
                source = "mission_control"
                notes.append("aligned_to_mission_evidence")
            else:
                notes.append(f"status_divergence:task={task_status}:mission={mission_status}")

    return ConfirmedOutcome(
        mission_id=str(mission.get("id")) if mission.get("id") else None,
        task_id=str(task.get("id")) if task.get("id") else None,
        run_id=str(task.get("run_id") or mission.get("execution_id") or mission.get("run_id") or "") or None,
        status=status,
        verification_status=ver_status,
        evidence_refs=[str(r) for r in evidence_refs],
        step_summary=step_summary,
        confirmed=confirmed,
        source=source,
        notes=notes,
    )


def apply_new_user_instructions(
    *,
    current_plan_version: int,
    steps: list[dict[str, Any]],
    completed_ids: set[str],
    instruction: str,
    invalidate_from_step_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Redirect/new instructions: keep independent completed steps; re-run dependents."""
    from reasoning.run_control import apply_redirect

    effect = apply_redirect(
        current_plan_version=current_plan_version,
        command_plan_version=current_plan_version,
        steps=steps,
        completed_ids=completed_ids,
        new_instruction=instruction,
        target_step_ids=invalidate_from_step_ids,
    )
    # Also invalidate dependents of targeted steps.
    invalidated = set(effect.invalidated_step_ids)
    if invalidate_from_step_ids:
        known = {
            str(s.get("step_id") or s.get("id") or f"step-{i+1}"): s
            for i, s in enumerate(steps)
        }
        changed = True
        while changed:
            changed = False
            for sid, step in known.items():
                deps = {str(d) for d in (step.get("depends_on") or [])}
                if sid not in invalidated and deps & invalidated:
                    invalidated.add(sid)
                    changed = True
    reused = sorted(completed_ids - invalidated)
    return {
        "accepted": effect.accepted,
        "plan_version": effect.plan_version,
        "reused_step_ids": reused,
        "invalidated_step_ids": sorted(invalidated),
        "new_instruction": effect.new_instruction,
        "reason": effect.reason,
        "ui_note": "Voltooide onafhankelijke stappen blijven behouden; alleen afhankelijk werk wordt opnieuw uitgevoerd.",
    }


# Process-wide ledger (tests may construct their own).
default_side_effect_ledger = SideEffectLedger()
