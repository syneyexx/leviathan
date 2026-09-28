"""Lesson trust evolution — AGENT_PROPOSED until measured repeated evidence validates.

Wave 16–17: lessons never overwrite prior claims; trust/conflict updates carry
provenance. SEALED-derived knowledge is rejected for adaptive use (firewall).
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .agent_lab import LessonTrust
from .epistemic import assert_adaptive_write_allowed, is_adaptive_evidence
from .learning_types import MeasurementStatus
from .types import MarketSimError


# Re-export for callers / tests
__all__ = [
    "EvidenceRecord",
    "LessonTrust",
    "LessonTrustPolicy",
    "accumulate_counterevidence",
    "accumulate_supporting_evidence",
    "assert_lesson_adaptive_allowed",
    "new_agent_proposed_lesson",
    "validate_lesson_trust_transition",
]


class LessonTrustTransitionError(MarketSimError):
    def __init__(self, detail: str, *, code: str = "LESSON_TRUST_TRANSITION_FORBIDDEN") -> None:
        super().__init__(code, detail, http_status=409)


@dataclass(frozen=True)
class LessonTrustPolicy:
    """Measured repeated-evidence policy for AGENT_PROPOSED → VALIDATED."""

    min_supporting_evidence: int = 2
    min_distinct_refs: int = 2
    require_measured: bool = True
    allow_sealed_adaptive: bool = False  # always False in practice
    counterevidence_rejects_at: int = 2

    def public_dict(self) -> dict[str, Any]:
        return {
            "min_supporting_evidence": self.min_supporting_evidence,
            "min_distinct_refs": self.min_distinct_refs,
            "require_measured": self.require_measured,
            "allow_sealed_adaptive": self.allow_sealed_adaptive,
            "counterevidence_rejects_at": self.counterevidence_rejects_at,
            "truth": {
                "agent_proposed_is_not_proof": True,
                "validated_requires_repeated_measured_evidence": True,
                "sealed_cannot_validate_adaptive_lessons": True,
                "never_overwrite_old_lesson_claim": True,
            },
        }


DEFAULT_LESSON_TRUST_POLICY = LessonTrustPolicy()


@dataclass
class EvidenceRecord:
    evidence_id: str
    kind: str  # supporting | counter
    measurement_status: str = MeasurementStatus.MEASURED.value
    evidence_refs: list[str] = field(default_factory=list)
    evidence_class: str | None = None
    validation_stage: str | None = None
    split_role: str | None = None
    note: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "measurement_status": self.measurement_status,
            "evidence_refs": list(self.evidence_refs),
            "evidence_class": self.evidence_class,
            "validation_stage": self.validation_stage,
            "split_role": self.split_role,
            "note": self.note,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "EvidenceRecord":
        raw = dict(raw or {})
        return cls(
            evidence_id=str(raw.get("evidence_id") or uuid.uuid4()),
            kind=str(raw.get("kind") or "supporting"),
            measurement_status=str(
                raw.get("measurement_status") or MeasurementStatus.MEASURED.value
            ),
            evidence_refs=[str(r) for r in (raw.get("evidence_refs") or [])],
            evidence_class=(str(raw["evidence_class"]) if raw.get("evidence_class") is not None else None),
            validation_stage=(
                str(raw["validation_stage"]) if raw.get("validation_stage") is not None else None
            ),
            split_role=(str(raw["split_role"]) if raw.get("split_role") is not None else None),
            note=str(raw.get("note") or ""),
            created_at=str(raw.get("created_at") or ""),
            metadata=dict(raw.get("metadata") or {}),
        )


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    LessonTrust.AGENT_PROPOSED.value: frozenset(
        {LessonTrust.VALIDATED.value, LessonTrust.REJECTED.value, LessonTrust.AGENT_PROPOSED.value}
    ),
    LessonTrust.VALIDATED.value: frozenset(
        {LessonTrust.REJECTED.value, LessonTrust.VALIDATED.value}
    ),
    LessonTrust.REJECTED.value: frozenset({LessonTrust.REJECTED.value}),
}


def assert_lesson_adaptive_allowed(
    *,
    evidence_class: str | None = None,
    validation_stage: str | None = None,
    split_role: str | None = None,
) -> None:
    """SEALED-derived knowledge must not enter adaptive lesson validation."""
    assert_adaptive_write_allowed(
        evidence_class=evidence_class,
        validation_stage=validation_stage,
        split_role=split_role,
    )


def _is_measured(status: str | None) -> bool:
    return str(status or "").upper() == MeasurementStatus.MEASURED.value


def _supporting_records(lesson: Mapping[str, Any]) -> list[dict[str, Any]]:
    meta = dict(lesson.get("metadata") or {})
    return [dict(e) for e in (meta.get("supporting_evidence") or [])]


def _counter_records(lesson: Mapping[str, Any]) -> list[dict[str, Any]]:
    meta = dict(lesson.get("metadata") or {})
    return [dict(e) for e in (meta.get("counterevidence") or [])]


def _distinct_refs(records: Sequence[Mapping[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for rec in records:
        for r in rec.get("evidence_refs") or []:
            refs.add(str(r))
        eid = rec.get("evidence_id")
        if eid:
            refs.add(str(eid))
    return refs


def _policy_satisfied(
    lesson: Mapping[str, Any],
    *,
    policy: LessonTrustPolicy,
    target: str,
) -> tuple[bool, str]:
    if target == LessonTrust.AGENT_PROPOSED.value:
        return True, "noop"
    if target == LessonTrust.REJECTED.value:
        counters = _counter_records(lesson)
        measured = [c for c in counters if _is_measured(c.get("measurement_status"))]
        if policy.require_measured and not measured and counters:
            return False, "counterevidence_unmeasured"
        if len(counters) >= policy.counterevidence_rejects_at or (
            lesson.get("trust") == LessonTrust.AGENT_PROPOSED.value and len(counters) >= 1
        ):
            # Explicit reject of AGENT_PROPOSED allowed with ≥1 counter; VALIDATED needs threshold
            if lesson.get("trust") == LessonTrust.VALIDATED.value:
                if len(measured if policy.require_measured else counters) < policy.counterevidence_rejects_at:
                    return False, "insufficient_counterevidence_to_demote_validated"
            return True, "counterevidence_ok"
        return False, "insufficient_counterevidence"

    # VALIDATED
    if target != LessonTrust.VALIDATED.value:
        return False, f"unknown_target:{target}"

    supporting = _supporting_records(lesson)
    if policy.require_measured:
        supporting = [s for s in supporting if _is_measured(s.get("measurement_status"))]
    # Reject SEALED / non-adaptive evidence for validation
    adaptive_ok: list[dict[str, Any]] = []
    for s in supporting:
        if not is_adaptive_evidence(
            evidence_class=s.get("evidence_class"),
            validation_stage=s.get("validation_stage"),
            split_role=s.get("split_role"),
        ):
            continue
        adaptive_ok.append(s)
    supporting = adaptive_ok
    if len(supporting) < policy.min_supporting_evidence:
        return False, "insufficient_supporting_evidence"
    refs = _distinct_refs(supporting)
    # Also count top-level evidence_refs on the lesson itself
    for r in lesson.get("evidence_refs") or []:
        refs.add(str(r))
    if len(refs) < policy.min_distinct_refs:
        return False, "insufficient_distinct_evidence_refs"
    return True, "policy_ok"


def validate_lesson_trust_transition(
    current_trust: str,
    target_trust: str,
    *,
    lesson: Mapping[str, Any] | None = None,
    policy: LessonTrustPolicy | None = None,
    evidence_class: str | None = None,
    validation_stage: str | None = None,
    split_role: str | None = None,
) -> dict[str, Any]:
    """Validate a trust transition. Raises on illegal / under-evidenced moves."""
    cur = str(current_trust or LessonTrust.AGENT_PROPOSED.value).upper()
    tgt = str(target_trust or "").upper()
    pol = policy or DEFAULT_LESSON_TRUST_POLICY

    if cur not in _ALLOWED_TRANSITIONS:
        raise LessonTrustTransitionError(f"unknown current trust: {cur}")
    if tgt not in _ALLOWED_TRANSITIONS.get(cur, frozenset()):
        raise LessonTrustTransitionError(
            f"illegal trust transition {cur} → {tgt}",
            code="LESSON_TRUST_ILLEGAL_TRANSITION",
        )

    # SEALED firewall — validating via sealed evidence is forbidden
    if tgt == LessonTrust.VALIDATED.value:
        assert_lesson_adaptive_allowed(
            evidence_class=evidence_class,
            validation_stage=validation_stage,
            split_role=split_role,
        )

    lesson_dict = dict(lesson or {})
    if not lesson_dict:
        lesson_dict = {"trust": cur, "metadata": {}, "evidence_refs": []}
    ok, reason = _policy_satisfied(lesson_dict, policy=pol, target=tgt)
    if not ok and cur != tgt:
        raise LessonTrustTransitionError(
            f"trust transition {cur} → {tgt} blocked: {reason}",
            code="LESSON_TRUST_EVIDENCE_INSUFFICIENT",
        )
    return {
        "ok": True,
        "from": cur,
        "to": tgt,
        "reason": reason,
        "policy": pol.public_dict(),
    }


def _append_evidence(
    lesson: Mapping[str, Any],
    *,
    bucket: str,
    evidence: EvidenceRecord | Mapping[str, Any],
    never_overwrite_claim: bool = True,
) -> dict[str, Any]:
    """Return a new lesson dict with evidence appended — claim preserved."""
    out = copy.deepcopy(dict(lesson))
    claim = out.get("claim")
    meta = dict(out.get("metadata") or {})
    rec = evidence if isinstance(evidence, EvidenceRecord) else EvidenceRecord.from_dict(evidence)
    # Firewall: SEALED evidence cannot be used as adaptive supporting evidence
    if bucket == "supporting_evidence":
        assert_lesson_adaptive_allowed(
            evidence_class=rec.evidence_class,
            validation_stage=rec.validation_stage,
            split_role=rec.split_role,
        )
    rows = [dict(e) for e in (meta.get(bucket) or [])]
    rows.append(rec.public_dict())
    meta[bucket] = rows
    # Provenance trail (append-only)
    trail = [dict(t) for t in (meta.get("trust_provenance") or [])]
    trail.append(
        {
            "event": f"accumulate_{bucket}",
            "evidence_id": rec.evidence_id,
            "measurement_status": rec.measurement_status,
            "created_at": rec.created_at,
        }
    )
    meta["trust_provenance"] = trail
    out["metadata"] = meta
    # Merge refs without dropping old ones
    existing_refs = [str(r) for r in (out.get("evidence_refs") or [])]
    for r in rec.evidence_refs:
        if r not in existing_refs:
            existing_refs.append(r)
    out["evidence_refs"] = existing_refs
    if never_overwrite_claim and claim is not None:
        out["claim"] = claim
    return out


def accumulate_supporting_evidence(
    lesson: Mapping[str, Any],
    evidence: EvidenceRecord | Mapping[str, Any],
    *,
    policy: LessonTrustPolicy | None = None,
    auto_promote: bool = False,
) -> dict[str, Any]:
    """Append supporting evidence; optionally promote to VALIDATED when policy met.

    Never overwrites the original claim text.
    """
    out = _append_evidence(lesson, bucket="supporting_evidence", evidence=evidence)
    if auto_promote:
        try:
            validate_lesson_trust_transition(
                str(out.get("trust") or LessonTrust.AGENT_PROPOSED.value),
                LessonTrust.VALIDATED.value,
                lesson=out,
                policy=policy,
            )
            prev = str(out.get("trust") or LessonTrust.AGENT_PROPOSED.value)
            out["trust"] = LessonTrust.VALIDATED.value
            meta = dict(out.get("metadata") or {})
            trail = [dict(t) for t in (meta.get("trust_provenance") or [])]
            trail.append(
                {
                    "event": "trust_transition",
                    "from": prev,
                    "to": LessonTrust.VALIDATED.value,
                    "policy": (policy or DEFAULT_LESSON_TRUST_POLICY).public_dict(),
                }
            )
            meta["trust_provenance"] = trail
            out["metadata"] = meta
        except LessonTrustTransitionError:
            pass
    return out


def accumulate_counterevidence(
    lesson: Mapping[str, Any],
    evidence: EvidenceRecord | Mapping[str, Any],
    *,
    policy: LessonTrustPolicy | None = None,
    auto_reject: bool = False,
) -> dict[str, Any]:
    """Append counterevidence; optionally demote to REJECTED when policy met.

    Never overwrites the original claim text.
    """
    out = _append_evidence(lesson, bucket="counterevidence", evidence=evidence)
    if auto_reject:
        try:
            validate_lesson_trust_transition(
                str(out.get("trust") or LessonTrust.AGENT_PROPOSED.value),
                LessonTrust.REJECTED.value,
                lesson=out,
                policy=policy,
            )
            prev = str(out.get("trust") or LessonTrust.AGENT_PROPOSED.value)
            out["trust"] = LessonTrust.REJECTED.value
            meta = dict(out.get("metadata") or {})
            trail = [dict(t) for t in (meta.get("trust_provenance") or [])]
            trail.append(
                {
                    "event": "trust_transition",
                    "from": prev,
                    "to": LessonTrust.REJECTED.value,
                    "policy": (policy or DEFAULT_LESSON_TRUST_POLICY).public_dict(),
                }
            )
            meta["trust_provenance"] = trail
            out["metadata"] = meta
        except LessonTrustTransitionError:
            pass
    return out


def new_agent_proposed_lesson(
    *,
    claim: str,
    evidence_refs: Sequence[str] | None = None,
    applies_to: Sequence[str] | None = None,
    confidence: float = 0.3,
    lesson_id: str | None = None,
    created_at: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical constructor — lessons always start AGENT_PROPOSED."""
    return {
        "lesson_id": lesson_id or str(uuid.uuid4()),
        "claim": claim,
        "evidence_refs": list(evidence_refs or []),
        "applies_to": list(applies_to or []),
        "trust": LessonTrust.AGENT_PROPOSED.value,
        "confidence": float(confidence),
        "created_at": created_at,
        "metadata": {
            "supporting_evidence": [],
            "counterevidence": [],
            "trust_provenance": [
                {"event": "created", "trust": LessonTrust.AGENT_PROPOSED.value},
            ],
            **dict(metadata or {}),
        },
        "truth": {
            "agent_proposed_is_not_proof": True,
            "validated_requires_repeated_measured_evidence": True,
        },
    }
