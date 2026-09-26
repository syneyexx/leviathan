"""Typed quality contracts — revision-bound acceptance for TEAM and verified runs.

Canonical owner: verification (completion_verification). Cognition and research
consume these types; they must not invent a parallel acceptance authority.

Mandatory criteria cannot be averaged away. Advisory scores inform prioritization
only. A successful verdict against artifact revision A never certifies revision B.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class CriterionSeverity(str, Enum):
    MANDATORY = "mandatory"
    ADVISORY = "advisory"


class CriterionApplicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class CriterionVerdictStatus(str, Enum):
    PENDING = "pending"
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNVERIFIABLE = "unverifiable"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"


class EvidenceClass(str, Enum):
    TEST_RECEIPT = "test_receipt"
    ARTIFACT_INSPECTION = "artifact_inspection"
    CLAIM_SUPPORT = "claim_support"
    CITATION_AUDIT = "citation_audit"
    CALCULATION_RECEIPT = "calculation_receipt"
    GATEWAY_RECEIPT = "gateway_receipt"
    SOURCE_INSPECTION = "source_inspection"
    INDEPENDENT_CHECK = "independent_check"
    USER_INPUT = "user_input"
    UNCERTAINTY_STATEMENT = "uncertainty_statement"


class CompletionPolicyKind(str, Enum):
    """Cumulative stopping policy — distinct from per-operation resource bounds."""

    FIXED_BUDGET = "fixed_budget"
    QUALITY_CONTRACT = "quality_contract"


class AcceptanceOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    PROVISIONAL = "provisional"


@dataclass(frozen=True)
class QualityCriterion:
    criterion_id: str
    description: str
    verification_method: str
    evidence_class: EvidenceClass
    severity: CriterionSeverity = CriterionSeverity.MANDATORY
    applicability: CriterionApplicability = CriterionApplicability.APPLICABLE
    applicability_justification: str | None = None
    depends_on: tuple[str, ...] = ()
    threshold: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.applicability == CriterionApplicability.NOT_APPLICABLE:
            if not (self.applicability_justification or "").strip():
                raise ValueError(
                    f"criterion {self.criterion_id}: not_applicable requires justification"
                )

    def public_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "verification_method": self.verification_method,
            "evidence_class": self.evidence_class.value,
            "severity": self.severity.value,
            "applicability": self.applicability.value,
            "applicability_justification": self.applicability_justification,
            "depends_on": list(self.depends_on),
            "threshold": dict(self.threshold),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QualityCriterion":
        raw = dict(data or {})
        try:
            evidence = EvidenceClass(str(raw.get("evidence_class") or EvidenceClass.INDEPENDENT_CHECK.value))
        except ValueError as exc:
            raise ValueError(f"invalid evidence_class: {raw.get('evidence_class')}") from exc
        try:
            severity = CriterionSeverity(str(raw.get("severity") or CriterionSeverity.MANDATORY.value))
        except ValueError as exc:
            raise ValueError(f"invalid severity: {raw.get('severity')}") from exc
        try:
            applicability = CriterionApplicability(
                str(raw.get("applicability") or CriterionApplicability.APPLICABLE.value)
            )
        except ValueError as exc:
            raise ValueError(f"invalid applicability: {raw.get('applicability')}") from exc
        cid = str(raw.get("criterion_id") or raw.get("id") or "").strip()
        if not cid:
            raise ValueError("criterion_id is required")
        return cls(
            criterion_id=cid,
            description=str(raw.get("description") or cid),
            verification_method=str(raw.get("verification_method") or "unspecified"),
            evidence_class=evidence,
            severity=severity,
            applicability=applicability,
            applicability_justification=raw.get("applicability_justification"),
            depends_on=tuple(str(x) for x in (raw.get("depends_on") or ())),
            threshold=dict(raw.get("threshold") or {}),
            provenance=dict(raw.get("provenance") or {}),
        )


@dataclass(frozen=True)
class CriterionVerdict:
    criterion_id: str
    contract_version: int
    artifact_revision: str
    status: CriterionVerdictStatus
    verifier_identity: str
    verifier_type: str
    evidence_ids: tuple[str, ...] = ()
    public_justification: str = ""
    created_at: str = ""
    validity_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    verdict_id: str = ""

    def __post_init__(self) -> None:
        if self.status == CriterionVerdictStatus.SATISFIED and not self.evidence_ids:
            raise ValueError(
                f"criterion {self.criterion_id}: SATISFIED requires at least one evidence_id"
            )
        if not (self.artifact_revision or "").strip():
            raise ValueError("artifact_revision is required for a verdict")
        object.__setattr__(
            self,
            "verdict_id",
            self.verdict_id or f"verdict:{uuid.uuid4().hex[:16]}",
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "criterion_id": self.criterion_id,
            "contract_version": self.contract_version,
            "artifact_revision": self.artifact_revision,
            "status": self.status.value,
            "verifier_identity": self.verifier_identity,
            "verifier_type": self.verifier_type,
            "evidence_ids": list(self.evidence_ids),
            "public_justification": self.public_justification,
            "created_at": self.created_at,
            "validity_conditions": list(self.validity_conditions),
            "limitations": list(self.limitations),
            "truth": {
                "verdict_bound_to_artifact_revision": True,
                "satisfied_requires_evidence": True,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CriterionVerdict":
        raw = dict(data or {})
        status = CriterionVerdictStatus(str(raw.get("status") or CriterionVerdictStatus.PENDING.value))
        return cls(
            criterion_id=str(raw["criterion_id"]),
            contract_version=int(raw.get("contract_version") or 1),
            artifact_revision=str(raw.get("artifact_revision") or ""),
            status=status,
            verifier_identity=str(raw.get("verifier_identity") or "unknown"),
            verifier_type=str(raw.get("verifier_type") or "unknown"),
            evidence_ids=tuple(str(x) for x in (raw.get("evidence_ids") or ())),
            public_justification=str(raw.get("public_justification") or ""),
            created_at=str(raw.get("created_at") or ""),
            validity_conditions=tuple(str(x) for x in (raw.get("validity_conditions") or ())),
            limitations=tuple(str(x) for x in (raw.get("limitations") or ())),
            verdict_id=str(raw.get("verdict_id") or ""),
        )


@dataclass
class QualityContract:
    contract_id: str
    version: int
    run_id: str
    request_ref: str
    scope: str
    expected_deliverables: list[str] = field(default_factory=list)
    task_category: str = "general"
    exclusions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    accepted_uncertainty: list[str] = field(default_factory=list)
    freshness_requirements: dict[str, Any] = field(default_factory=dict)
    criteria: list[QualityCriterion] = field(default_factory=list)
    conflict_rule: str = "evidence_or_test_over_majority"
    missing_input_rule: str = "block_with_resume"
    uncertainty_rule: str = "explicit_uncertainty_may_satisfy_matching_criterion"
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    revised_at: str = ""

    def content_hash(self) -> str:
        blob = json.dumps(self.public_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]

    def mandatory_applicable(self) -> list[QualityCriterion]:
        return [
            c
            for c in self.criteria
            if c.severity == CriterionSeverity.MANDATORY
            and c.applicability == CriterionApplicability.APPLICABLE
        ]

    def advisory(self) -> list[QualityCriterion]:
        return [c for c in self.criteria if c.severity == CriterionSeverity.ADVISORY]

    def revise(
        self,
        *,
        criteria: Sequence[QualityCriterion] | None = None,
        scope: str | None = None,
        expected_deliverables: Sequence[str] | None = None,
        assumptions: Sequence[str] | None = None,
        accepted_uncertainty: Sequence[str] | None = None,
        exclusions: Sequence[str] | None = None,
        revised_at: str = "",
        revision_note: str = "",
        user_accepted_relaxation: bool = False,
    ) -> "QualityContract":
        """Return a new contract version. Material relaxation requires user acceptance."""
        new_criteria = list(criteria) if criteria is not None else list(self.criteria)
        if criteria is not None and not user_accepted_relaxation:
            old_ids = {
                c.criterion_id
                for c in self.mandatory_applicable()
            }
            new_ids = {
                c.criterion_id
                for c in new_criteria
                if c.severity == CriterionSeverity.MANDATORY
                and c.applicability == CriterionApplicability.APPLICABLE
            }
            removed = old_ids - new_ids
            if removed:
                raise ValueError(
                    "material criterion relaxation requires user_accepted_relaxation=True; "
                    f"removed={sorted(removed)}"
                )
            # Severity demotion of existing mandatory criteria is also material.
            old_sev = {c.criterion_id: c.severity for c in self.criteria}
            for c in new_criteria:
                if (
                    old_sev.get(c.criterion_id) == CriterionSeverity.MANDATORY
                    and c.severity != CriterionSeverity.MANDATORY
                    and c.applicability == CriterionApplicability.APPLICABLE
                ):
                    raise ValueError(
                        f"demoting mandatory criterion {c.criterion_id} requires user acceptance"
                    )
        prov = dict(self.provenance)
        history = list(prov.get("revision_history") or [])
        history.append(
            {
                "from_version": self.version,
                "to_version": self.version + 1,
                "note": revision_note,
                "user_accepted_relaxation": user_accepted_relaxation,
                "at": revised_at,
            }
        )
        prov["revision_history"] = history
        return QualityContract(
            contract_id=self.contract_id,
            version=self.version + 1,
            run_id=self.run_id,
            request_ref=self.request_ref,
            scope=scope if scope is not None else self.scope,
            expected_deliverables=(
                list(expected_deliverables)
                if expected_deliverables is not None
                else list(self.expected_deliverables)
            ),
            task_category=self.task_category,
            exclusions=list(exclusions) if exclusions is not None else list(self.exclusions),
            assumptions=list(assumptions) if assumptions is not None else list(self.assumptions),
            accepted_uncertainty=(
                list(accepted_uncertainty)
                if accepted_uncertainty is not None
                else list(self.accepted_uncertainty)
            ),
            freshness_requirements=dict(self.freshness_requirements),
            criteria=new_criteria,
            conflict_rule=self.conflict_rule,
            missing_input_rule=self.missing_input_rule,
            uncertainty_rule=self.uncertainty_rule,
            provenance=prov,
            created_at=self.created_at,
            revised_at=revised_at or self.revised_at,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "version": self.version,
            "run_id": self.run_id,
            "request_ref": self.request_ref,
            "scope": self.scope,
            "expected_deliverables": list(self.expected_deliverables),
            "task_category": self.task_category,
            "exclusions": list(self.exclusions),
            "assumptions": list(self.assumptions),
            "accepted_uncertainty": list(self.accepted_uncertainty),
            "freshness_requirements": dict(self.freshness_requirements),
            "criteria": [c.public_dict() for c in self.criteria],
            "conflict_rule": self.conflict_rule,
            "missing_input_rule": self.missing_input_rule,
            "uncertainty_rule": self.uncertainty_rule,
            "provenance": dict(self.provenance),
            "created_at": self.created_at,
            "revised_at": self.revised_at,
            "truth": {
                "mandatory_cannot_be_averaged_away": True,
                "material_relaxation_requires_user_acceptance": True,
                "ambition_phrases_are_not_predicates": True,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QualityContract":
        raw = dict(data or {})
        criteria = [QualityCriterion.from_dict(c) for c in (raw.get("criteria") or [])]
        return cls(
            contract_id=str(raw.get("contract_id") or f"qc:{uuid.uuid4().hex[:12]}"),
            version=int(raw.get("version") or 1),
            run_id=str(raw.get("run_id") or ""),
            request_ref=str(raw.get("request_ref") or ""),
            scope=str(raw.get("scope") or ""),
            expected_deliverables=list(raw.get("expected_deliverables") or []),
            task_category=str(raw.get("task_category") or "general"),
            exclusions=list(raw.get("exclusions") or []),
            assumptions=list(raw.get("assumptions") or []),
            accepted_uncertainty=list(raw.get("accepted_uncertainty") or []),
            freshness_requirements=dict(raw.get("freshness_requirements") or {}),
            criteria=criteria,
            conflict_rule=str(raw.get("conflict_rule") or "evidence_or_test_over_majority"),
            missing_input_rule=str(raw.get("missing_input_rule") or "block_with_resume"),
            uncertainty_rule=str(
                raw.get("uncertainty_rule") or "explicit_uncertainty_may_satisfy_matching_criterion"
            ),
            provenance=dict(raw.get("provenance") or {}),
            created_at=str(raw.get("created_at") or ""),
            revised_at=str(raw.get("revised_at") or ""),
        )


@dataclass(frozen=True)
class AcceptanceRecord:
    acceptance_id: str
    contract_id: str
    contract_version: int
    contract_hash: str
    artifact_revision: str
    outcome: AcceptanceOutcome
    mandatory_verdict_ids: tuple[str, ...]
    advisory_notes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    created_at: str = ""
    limitations: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "acceptance_id": self.acceptance_id,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_hash": self.contract_hash,
            "artifact_revision": self.artifact_revision,
            "outcome": self.outcome.value,
            "mandatory_verdict_ids": list(self.mandatory_verdict_ids),
            "advisory_notes": list(self.advisory_notes),
            "blockers": list(self.blockers),
            "created_at": self.created_at,
            "limitations": list(self.limitations),
            "truth": {
                "accepted_only_when_all_mandatory_satisfied": True,
                "advisory_cannot_compensate_mandatory_failure": True,
            },
        }


def _verdict_for_criterion(
    criterion_id: str,
    verdicts: Sequence[CriterionVerdict],
    *,
    artifact_revision: str,
    contract_version: int,
) -> CriterionVerdict | None:
    """Latest non-stale verdict matching revision + contract version."""
    matches = [
        v
        for v in verdicts
        if v.criterion_id == criterion_id
        and v.artifact_revision == artifact_revision
        and v.contract_version == contract_version
        and v.status != CriterionVerdictStatus.STALE
    ]
    return matches[-1] if matches else None


def aggregate_acceptance(
    contract: QualityContract,
    verdicts: Sequence[CriterionVerdict],
    *,
    artifact_revision: str,
    unresolved_blocking_conflicts: Sequence[str] = (),
    created_at: str = "",
) -> AcceptanceRecord:
    """Deterministic acceptance: all applicable mandatory criteria SATISFIED for this revision."""
    if not (artifact_revision or "").strip():
        raise ValueError("artifact_revision required for acceptance aggregation")

    mandatory = contract.mandatory_applicable()
    satisfied_ids: list[str] = []
    blockers: list[str] = []
    advisory_notes: list[str] = []

    for crit in mandatory:
        verdict = _verdict_for_criterion(
            crit.criterion_id,
            verdicts,
            artifact_revision=artifact_revision,
            contract_version=contract.version,
        )
        if verdict is None:
            blockers.append(f"missing_verdict:{crit.criterion_id}")
            continue
        if verdict.status == CriterionVerdictStatus.SATISFIED:
            satisfied_ids.append(verdict.verdict_id)
        elif verdict.status == CriterionVerdictStatus.NOT_APPLICABLE:
            blockers.append(
                f"not_applicable_without_contract_mark:{crit.criterion_id}"
            )
        elif verdict.status == CriterionVerdictStatus.UNVERIFIABLE:
            blockers.append(f"unverifiable:{crit.criterion_id}:{verdict.public_justification}")
        else:
            blockers.append(f"{verdict.status.value}:{crit.criterion_id}")

    for crit in contract.advisory():
        verdict = _verdict_for_criterion(
            crit.criterion_id,
            verdicts,
            artifact_revision=artifact_revision,
            contract_version=contract.version,
        )
        if verdict is None:
            advisory_notes.append(f"advisory_pending:{crit.criterion_id}")
        elif verdict.status != CriterionVerdictStatus.SATISFIED:
            advisory_notes.append(f"advisory_{verdict.status.value}:{crit.criterion_id}")

    conflict_blockers = [f"blocking_conflict:{c}" for c in unresolved_blocking_conflicts]
    blockers.extend(conflict_blockers)

    if blockers:
        outcome = (
            AcceptanceOutcome.BLOCKED
            if any(b.startswith("blocking_conflict:") or b.startswith("unverifiable:") for b in blockers)
            or any(b.startswith("missing_verdict:") for b in blockers)
            else AcceptanceOutcome.REJECTED
        )
        if any(b.startswith("unsatisfied:") or b.startswith("pending:") for b in blockers):
            outcome = AcceptanceOutcome.INCOMPLETE
        if conflict_blockers:
            outcome = AcceptanceOutcome.BLOCKED
    else:
        outcome = AcceptanceOutcome.ACCEPTED

    return AcceptanceRecord(
        acceptance_id=f"acc:{uuid.uuid4().hex[:16]}",
        contract_id=contract.contract_id,
        contract_version=contract.version,
        contract_hash=contract.content_hash(),
        artifact_revision=artifact_revision,
        outcome=outcome,
        mandatory_verdict_ids=tuple(satisfied_ids),
        advisory_notes=tuple(advisory_notes),
        blockers=tuple(blockers),
        created_at=created_at,
        limitations=(),
    )


def invalidate_verdicts_for_revision(
    verdicts: Sequence[CriterionVerdict],
    *,
    artifact_revision: str | None = None,
    contract_version: int | None = None,
    criterion_ids: Sequence[str] | None = None,
) -> list[CriterionVerdict]:
    """Mark matching verdicts STALE when artifact/contract/criteria change."""
    out: list[CriterionVerdict] = []
    id_filter = set(criterion_ids) if criterion_ids is not None else None
    for v in verdicts:
        match_rev = artifact_revision is None or v.artifact_revision == artifact_revision
        match_ver = contract_version is None or v.contract_version == contract_version
        match_id = id_filter is None or v.criterion_id in id_filter
        if match_rev and match_ver and match_id and v.status != CriterionVerdictStatus.STALE:
            out.append(
                CriterionVerdict(
                    criterion_id=v.criterion_id,
                    contract_version=v.contract_version,
                    artifact_revision=v.artifact_revision,
                    status=CriterionVerdictStatus.STALE,
                    verifier_identity=v.verifier_identity,
                    verifier_type=v.verifier_type,
                    evidence_ids=v.evidence_ids,
                    public_justification=f"stale: {v.public_justification}",
                    created_at=v.created_at,
                    validity_conditions=v.validity_conditions,
                    limitations=tuple([*v.limitations, "invalidated_by_revision_change"]),
                    verdict_id=v.verdict_id,
                )
            )
        else:
            out.append(v)
    return out


def criterion_progress(
    contract: QualityContract,
    verdicts: Sequence[CriterionVerdict],
    *,
    artifact_revision: str,
) -> dict[str, Any]:
    """Open-ended criterion progress — never a fake percent of fixed total rounds."""
    mandatory = contract.mandatory_applicable()
    satisfied = 0
    pending = 0
    failed = 0
    unverifiable = 0
    for crit in mandatory:
        verdict = _verdict_for_criterion(
            crit.criterion_id,
            verdicts,
            artifact_revision=artifact_revision,
            contract_version=contract.version,
        )
        if verdict is None or verdict.status == CriterionVerdictStatus.PENDING:
            pending += 1
        elif verdict.status == CriterionVerdictStatus.SATISFIED:
            satisfied += 1
        elif verdict.status == CriterionVerdictStatus.UNVERIFIABLE:
            unverifiable += 1
        else:
            failed += 1
    total = len(mandatory)
    return {
        "mandatory_total": total,
        "mandatory_satisfied": satisfied,
        "mandatory_pending": pending,
        "mandatory_failed": failed,
        "mandatory_unverifiable": unverifiable,
        "advisory_total": len(contract.advisory()),
        "label": "criteria_satisfied",
        "truth": {
            "not_percent_truth": True,
            "not_predicted_time": True,
            "not_fixed_round_fraction": True,
            "open_ended_iteration": True,
        },
    }


def new_contract_id() -> str:
    return f"qc:{uuid.uuid4().hex[:12]}"
