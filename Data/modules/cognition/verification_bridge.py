"""Independent verification bridge — map run observations to typed requirements.

Does not invent facts. Model text never becomes evidence. Research/file/receipt
refs are materialized into Evidence records when possible, then checked by
VerificationEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from Data.modules.evidence.refs import parse_evidence_ref
from Data.modules.evidence.types import EvidenceKind
from Data.modules.verification.types import VerificationRequirement


# Logical TaskModel.required_evidence → acceptable EvidenceKind values (OR).
_LOGICAL_EVIDENCE_MAP: dict[str, tuple[str, ...]] = {
    "source_or_evidence_ref": (
        EvidenceKind.RESEARCH_SOURCE.value,
        EvidenceKind.ARTIFACT_HASH.value,
        EvidenceKind.OBSERVATION_REF.value,
    ),
    "effect_or_patch_receipt": (
        EvidenceKind.CAPABILITY_RECEIPT.value,
        EvidenceKind.FILE_EXISTS.value,
        EvidenceKind.ARTIFACT_HASH.value,
    ),
    "observation_ref": (EvidenceKind.OBSERVATION_REF.value,),
    "verification_report": (
        EvidenceKind.ARTIFACT_HASH.value,
        EvidenceKind.CAPABILITY_RECEIPT.value,
        EvidenceKind.RESEARCH_SOURCE.value,
        EvidenceKind.FILE_EXISTS.value,
        EvidenceKind.OBSERVATION_REF.value,
    ),
}


@dataclass
class CollectedRunRefs:
    research_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    research_projects: list[str] = field(default_factory=list)
    # receipt_id → attested status / side_effects from observation telemetry
    receipt_attestations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # research evidence id → optional source_id / project_id from observation payload
    research_attestations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "research_ids": list(self.research_ids),
            "artifact_ids": list(self.artifact_ids),
            "observation_ids": list(self.observation_ids),
            "receipt_ids": list(self.receipt_ids),
            "file_paths": list(self.file_paths),
            "research_projects": list(self.research_projects),
            "truth": {
                "collected_from_observations_not_model_text": True,
                "model_output_is_not_evidence": True,
            },
        }


def collect_run_refs(
    *,
    observations: Sequence[Any],
    artifact_refs_extra: Sequence[str] | None = None,
) -> CollectedRunRefs:
    out = CollectedRunRefs()

    def _ingest(raw: str, *, obs: Any | None = None, attested_research: bool = False) -> None:
        parsed = parse_evidence_ref(raw)
        if parsed is None:
            return
        if parsed.kind == "research":
            if parsed.ref_id not in out.research_ids:
                out.research_ids.append(parsed.ref_id)
            att = out.research_attestations.setdefault(parsed.ref_id, {})
            if attested_research:
                att["attested"] = True
            if obs is not None:
                payload = getattr(obs, "payload", None) or {}
                meta = payload.get("metadata") if isinstance(payload, dict) else {}
                if isinstance(meta, dict) and meta.get("project_id"):
                    att["project_id"] = meta.get("project_id")
                if isinstance(payload, dict) and payload.get("artifact_refs"):
                    for ar in payload.get("artifact_refs") or []:
                        p = parse_evidence_ref(str(ar))
                        if p and p.kind == "research_project":
                            att["project_id"] = p.ref_id
        elif parsed.kind == "artifact":
            if parsed.ref_id not in out.artifact_ids:
                out.artifact_ids.append(parsed.ref_id)
        elif parsed.kind == "observation":
            if parsed.ref_id not in out.observation_ids:
                out.observation_ids.append(parsed.ref_id)
        elif parsed.kind == "receipt":
            if parsed.ref_id not in out.receipt_ids:
                out.receipt_ids.append(parsed.ref_id)
        elif parsed.kind == "file":
            if parsed.ref_id not in out.file_paths:
                out.file_paths.append(parsed.ref_id)
        elif parsed.kind == "research_project":
            if parsed.ref_id not in out.research_projects:
                out.research_projects.append(parsed.ref_id)

    for obs in observations or []:
        kind = getattr(getattr(obs, "kind", None), "value", getattr(obs, "kind", None))
        success = getattr(obs, "success", None)
        research_attested = kind == "AGENT_RESULT" and success is not False
        for ref in getattr(obs, "evidence_refs", None) or []:
            _ingest(str(ref), obs=obs, attested_research=research_attested)
        for ref in getattr(obs, "artifact_refs", None) or []:
            _ingest(str(ref), obs=obs)
        payload = getattr(obs, "payload", None) or {}
        if not isinstance(payload, Mapping):
            continue
        # Capability invoke: receipt in telemetry
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
        telemetry = result.get("telemetry") if isinstance(result, Mapping) else {}
        if not isinstance(telemetry, Mapping):
            telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), Mapping) else {}
        receipt_id = None
        if isinstance(telemetry, Mapping):
            receipt_id = telemetry.get("receipt_id")
        if not receipt_id:
            receipt_id = payload.get("receipt_id")
        if receipt_id:
            rid = str(receipt_id)
            if rid not in out.receipt_ids:
                out.receipt_ids.append(rid)
            status = str(result.get("status") or payload.get("status") or "")
            side_effects = list(result.get("side_effects") or []) if isinstance(result, Mapping) else []
            out.receipt_attestations[rid] = {
                "status": status,
                "side_effects": side_effects,
                "capability_id": result.get("capability_id") or payload.get("capability_id"),
            }
            _ingest(f"receipt:{rid}", obs=obs)
        for nested in payload.get("observations") or []:
            if not isinstance(nested, Mapping):
                continue
            eid = nested.get("evidence_id")
            if eid:
                _ingest(f"e:{eid}", obs=obs, attested_research=research_attested)
                if research_attested:
                    out.research_attestations.setdefault(str(eid), {})["attested"] = True

    for raw in artifact_refs_extra or []:
        _ingest(str(raw))

    return out


def requirements_from_logical(
    logical: Sequence[str] | None,
) -> list[VerificationRequirement]:
    """Expand TaskModel.required_evidence strings into typed OR-group requirements."""
    reqs: list[VerificationRequirement] = []
    for item in logical or []:
        key = str(item or "").strip()
        if not key:
            continue
        # Already a concrete EvidenceKind?
        try:
            kind = EvidenceKind(key.upper() if key.isupper() else key)
            reqs.append(
                VerificationRequirement(
                    requirement_id=f"required:{kind.value}",
                    description=f"Required evidence kind {kind.value}",
                    evidence_kind=kind.value,
                    min_verified=1,
                )
            )
            continue
        except ValueError:
            pass
        kinds = _LOGICAL_EVIDENCE_MAP.get(key)
        if not kinds:
            # Unknown logical token — keep as opaque kind (will stay UNMEASURED unless matched).
            reqs.append(
                VerificationRequirement(
                    requirement_id=f"required:{key}",
                    description=f"Required evidence: {key}",
                    evidence_kind=key if ("_" in key or key.isupper()) else None,
                    min_verified=1,
                )
            )
            continue
        # One requirement per acceptable kind; bridge uses any_pass grouping.
        for kind in kinds:
            reqs.append(
                VerificationRequirement(
                    requirement_id=f"required:{key}:{kind}",
                    description=f"Required {key} via {kind}",
                    evidence_kind=kind,
                    min_verified=1,
                )
            )
    return reqs


def requirements_from_refs(collected: CollectedRunRefs) -> list[VerificationRequirement]:
    reqs: list[VerificationRequirement] = []
    for rid in collected.research_ids:
        reqs.append(
            VerificationRequirement(
                requirement_id=f"research:{rid}",
                description=f"Research evidence {rid} resolves to a source",
                evidence_kind=EvidenceKind.RESEARCH_SOURCE.value,
                min_verified=1,
            )
        )
    for aid in collected.artifact_ids:
        reqs.append(
            VerificationRequirement(
                requirement_id=f"art:{aid}",
                description=f"Artifact evidence {aid}",
                evidence_kind=EvidenceKind.ARTIFACT_HASH.value,
                artifact_id=aid,
                min_verified=1,
            )
        )
    for oid in collected.observation_ids:
        reqs.append(
            VerificationRequirement(
                requirement_id=f"obs:{oid}",
                description=f"Observation evidence {oid}",
                evidence_kind=EvidenceKind.OBSERVATION_REF.value,
                observation_id=oid,
                min_verified=1,
            )
        )
    for receipt_id in collected.receipt_ids:
        reqs.append(
            VerificationRequirement(
                requirement_id=f"receipt:{receipt_id}",
                description=f"Capability receipt {receipt_id}",
                evidence_kind=EvidenceKind.CAPABILITY_RECEIPT.value,
                min_verified=1,
            )
        )
    for path in collected.file_paths:
        reqs.append(
            VerificationRequirement(
                requirement_id=f"file:{path}",
                description=f"File exists: {path}",
                evidence_kind=EvidenceKind.FILE_EXISTS.value,
                path=path,
                min_verified=1,
            )
        )
    return reqs


def materialize_evidence_claims(
    collected: CollectedRunRefs,
    *,
    evidence_service: Any | None,
    run_id: str | None = None,
    receipt_lookup: Any | None = None,
    research_lookup: Any | None = None,
) -> list[Any]:
    """Create Evidence records for collected refs. Returns created records (may be empty)."""
    if evidence_service is None:
        return []
    created: list[Any] = []
    for path in collected.file_paths:
        try:
            created.append(
                evidence_service.claim_file_exists(path=path, run_id=run_id)
            )
        except Exception:  # noqa: BLE001
            continue
    for receipt_id in collected.receipt_ids:
        att = collected.receipt_attestations.get(receipt_id) or {}
        try:
            created.append(
                evidence_service.claim_capability_receipt(
                    receipt_id=receipt_id,
                    run_id=run_id,
                    receipt_lookup=receipt_lookup,
                    receipt_status=att.get("status"),
                    side_effects=list(att.get("side_effects") or []),
                )
            )
        except Exception:  # noqa: BLE001
            continue
    for rid in collected.research_ids:
        att = collected.research_attestations.get(rid) or {}
        try:
            created.append(
                evidence_service.claim_research_source(
                    research_evidence_id=rid,
                    run_id=run_id,
                    project_id=att.get("project_id") or (
                        collected.research_projects[0] if collected.research_projects else None
                    ),
                    source_id=att.get("source_id"),
                    research_lookup=research_lookup,
                    attested=bool(att.get("attested")),
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return created


def build_verification_plan(
    *,
    required_evidence: Sequence[str] | None,
    observations: Sequence[Any],
) -> dict[str, Any]:
    collected = collect_run_refs(observations=observations)
    ref_reqs = requirements_from_refs(collected)
    logical_reqs = requirements_from_logical(required_evidence)
    # Group logical OR keys for evaluate_any_pass
    or_groups: dict[str, list[str]] = {}
    for req in logical_reqs:
        rid = req.requirement_id
        if rid.startswith("required:") and rid.count(":") >= 2:
            # required:{logical}:{kind}
            parts = rid.split(":", 2)
            logical = parts[1]
            or_groups.setdefault(logical, []).append(rid)
    return {
        "collected": collected,
        "requirements": ref_reqs + logical_reqs,
        "or_groups": or_groups,
        "truth": {
            "independent_of_model_text": True,
            "unmeasured_is_not_passed": True,
            "research_and_file_receipts_covered": True,
        },
    }


def collapse_or_groups(
    report: Any,
    or_groups: Mapping[str, Sequence[str]],
) -> Any:
    """If any member of an OR group PASSED, treat sibling UNMEASURED as satisfied.

    FAILED members still fail the group. Mutates a shallow copy of the report outcome
    via a new VerificationReport when needed.
    """
    from Data.modules.verification.types import (
        RequirementResult,
        VerificationOutcome,
        VerificationReport,
    )

    if not or_groups or report is None:
        return report
    by_id = {r.requirement_id: r for r in (report.requirements or ())}
    rewritten: list[RequirementResult] = []
    consumed: set[str] = set()
    for logical, member_ids in or_groups.items():
        members = [by_id[mid] for mid in member_ids if mid in by_id]
        if not members:
            continue
        for mid in member_ids:
            consumed.add(mid)
        if any(m.outcome == VerificationOutcome.FAILED for m in members):
            # Prefer failed detail
            failed = next(m for m in members if m.outcome == VerificationOutcome.FAILED)
            rewritten.append(
                RequirementResult(
                    requirement_id=f"required:{logical}",
                    outcome=VerificationOutcome.FAILED,
                    matched_evidence_ids=failed.matched_evidence_ids,
                    detail=failed.detail,
                )
            )
        elif any(m.outcome == VerificationOutcome.PASSED for m in members):
            passed = next(m for m in members if m.outcome == VerificationOutcome.PASSED)
            rewritten.append(
                RequirementResult(
                    requirement_id=f"required:{logical}",
                    outcome=VerificationOutcome.PASSED,
                    matched_evidence_ids=passed.matched_evidence_ids,
                    detail=f"satisfied via {passed.requirement_id}",
                )
            )
        else:
            rewritten.append(
                RequirementResult(
                    requirement_id=f"required:{logical}",
                    outcome=VerificationOutcome.UNMEASURED,
                    matched_evidence_ids=(),
                    detail="no matching verified evidence for logical requirement",
                )
            )
    for r in report.requirements or ():
        if r.requirement_id not in consumed:
            rewritten.append(r)

    if any(item.outcome == VerificationOutcome.FAILED for item in rewritten):
        outcome = VerificationOutcome.FAILED
    elif any(item.outcome == VerificationOutcome.UNMEASURED for item in rewritten):
        outcome = VerificationOutcome.UNMEASURED
    elif rewritten and all(item.outcome == VerificationOutcome.PASSED for item in rewritten):
        outcome = VerificationOutcome.PASSED
    else:
        outcome = VerificationOutcome.UNMEASURED

    meta = dict(getattr(report, "metadata", None) or {})
    meta["or_groups_collapsed"] = True
    return VerificationReport(
        report_id=report.report_id,
        outcome=outcome,
        created_at=report.created_at,
        run_id=report.run_id,
        job_id=report.job_id,
        requirements=tuple(rewritten),
        metadata=meta,
    )
