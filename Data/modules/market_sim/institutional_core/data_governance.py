"""W40 — Data governance: quality rules, source hierarchy, quarantine, golden source.

Extends dataset_pipeline / institutional_ops dataset trust — no parallel quality owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH, rollup_states


# Higher rank = preferred. Unknown sources rank below declared hierarchy.
DEFAULT_SOURCE_HIERARCHY: tuple[str, ...] = (
    "golden_internal",
    "vendor_primary",
    "vendor_secondary",
    "exchange_public",
    "csv_local",
    "derived",
    "UNMEASURED",
)


@dataclass(frozen=True)
class QualityRule:
    rule_id: str
    name: str
    severity: str  # BLOCK | WARN | INFO
    check: str  # symbolic check id
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "name": self.name,
            "severity": self.severity,
            "check": self.check,
            "description": self.description,
        }


DEFAULT_QUALITY_RULES: tuple[QualityRule, ...] = (
    QualityRule("qr_gaps", "bar_gap_ratio", "WARN", "max_gap_ratio"),
    QualityRule("qr_dupes", "duplicate_timestamps", "BLOCK", "no_duplicate_ts"),
    QualityRule("qr_neg", "non_negative_prices", "BLOCK", "prices_non_negative"),
    QualityRule("qr_hash", "content_hash_stable", "BLOCK", "hash_unchanged_without_version"),
    QualityRule("qr_source", "source_declared", "WARN", "source_in_hierarchy"),
)


@dataclass
class QualityFinding:
    rule_id: str
    passed: bool
    severity: str
    detail: str
    state: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "passed": self.passed,
            "severity": self.severity,
            "detail": self.detail,
            "state": self.state,
        }


@dataclass
class QuarantineRecord:
    dataset_id: str
    reason: str
    findings: list[QualityFinding]
    quarantined_at: str
    released_at: str | None = None
    status: str = "QUARANTINED"  # QUARANTINED | RELEASED | DESTROYED

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "reason": self.reason,
            "findings": [f.public_dict() for f in self.findings],
            "quarantinedAt": self.quarantined_at,
            "releasedAt": self.released_at,
            "status": self.status,
            "truth": {
                "quarantine_is_not_quality_pass": True,
                **DEFAULT_TRUTH.public_dict(),
            },
        }


@dataclass
class GoldenSourceDeclaration:
    domain: str  # e.g. equity_ohlcv | fx_spot
    source_id: str
    declared_at: str
    declared_by: str
    evidence: str = "ASSUMED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "sourceId": self.source_id,
            "declaredAt": self.declared_at,
            "declaredBy": self.declared_by,
            "evidence": self.evidence,
            "truth": {
                "declaration_is_not_automatic_proof": True,
                "evidence_assumed_until_measured": self.evidence
                in {MeasurementState.ASSUMED.value, MeasurementState.UNMEASURED.value},
            },
        }


@dataclass
class GovernanceReport:
    dataset_id: str
    source_id: str
    source_rank: int
    findings: list[QualityFinding]
    verdict: str
    quarantined: bool
    golden: GoldenSourceDeclaration | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "sourceId": self.source_id,
            "sourceRank": self.source_rank,
            "findings": [f.public_dict() for f in self.findings],
            "verdict": self.verdict,
            "quarantined": self.quarantined,
            "golden": None if self.golden is None else self.golden.public_dict(),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_dataset_pipeline": True,
            },
        }


def source_rank(
    source_id: str,
    hierarchy: Sequence[str] = DEFAULT_SOURCE_HIERARCHY,
) -> int:
    """Lower number = higher preference. Unknown sources get worst rank."""
    try:
        return list(hierarchy).index(source_id)
    except ValueError:
        return len(hierarchy) + 1


def prefer_source(
    candidates: Sequence[str],
    hierarchy: Sequence[str] = DEFAULT_SOURCE_HIERARCHY,
) -> str | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: source_rank(s, hierarchy))[0]


def evaluate_quality(
    *,
    dataset_id: str,
    source_id: str,
    metrics: Mapping[str, Any],
    rules: Sequence[QualityRule] = DEFAULT_QUALITY_RULES,
    hierarchy: Sequence[str] = DEFAULT_SOURCE_HIERARCHY,
    golden: GoldenSourceDeclaration | None = None,
) -> GovernanceReport:
    """Apply symbolic quality rules against caller-supplied metrics (no invented bars)."""
    findings: list[QualityFinding] = []
    for rule in rules:
        if rule.check == "max_gap_ratio":
            gap = metrics.get("gap_ratio")
            if gap is None:
                findings.append(
                    QualityFinding(
                        rule.rule_id, False, rule.severity, "gap_ratio UNMEASURED",
                        MeasurementState.UNMEASURED.value,
                    )
                )
            else:
                ok = float(gap) <= float(metrics.get("max_gap_ratio", 0.05))
                findings.append(
                    QualityFinding(rule.rule_id, ok, rule.severity, f"gap_ratio={gap}")
                )
        elif rule.check == "no_duplicate_ts":
            dupes = int(metrics.get("duplicate_timestamps") or 0)
            findings.append(
                QualityFinding(rule.rule_id, dupes == 0, rule.severity, f"duplicates={dupes}")
            )
        elif rule.check == "prices_non_negative":
            neg = int(metrics.get("negative_prices") or 0)
            findings.append(
                QualityFinding(rule.rule_id, neg == 0, rule.severity, f"negative_prices={neg}")
            )
        elif rule.check == "hash_unchanged_without_version":
            unexpected = bool(metrics.get("unexpected_hash_change"))
            findings.append(
                QualityFinding(
                    rule.rule_id,
                    not unexpected,
                    rule.severity,
                    "unexpected_hash_change" if unexpected else "hash_stable",
                )
            )
        elif rule.check == "source_in_hierarchy":
            known = source_id in set(hierarchy)
            findings.append(
                QualityFinding(
                    rule.rule_id,
                    known,
                    rule.severity,
                    "source_known" if known else "source_UNMEASURED",
                    MeasurementState.OBSERVED.value if known else MeasurementState.UNMEASURED.value,
                )
            )
        else:
            findings.append(
                QualityFinding(
                    rule.rule_id,
                    False,
                    rule.severity,
                    f"check_NOT_IMPLEMENTED:{rule.check}",
                    MeasurementState.NOT_IMPLEMENTED.value,
                )
            )

    block_fail = any(not f.passed and f.severity == "BLOCK" for f in findings)
    warn_fail = any(not f.passed and f.severity == "WARN" for f in findings)
    unmeasured = any(f.state == MeasurementState.UNMEASURED.value for f in findings)
    if block_fail:
        verdict = MeasurementState.FAIL.value
        quarantined = True
    elif unmeasured and not warn_fail:
        verdict = MeasurementState.UNMEASURED.value
        quarantined = False
    elif warn_fail:
        verdict = MeasurementState.DEGRADED.value
        quarantined = False
    else:
        verdict = MeasurementState.PASS.value
        quarantined = False

    return GovernanceReport(
        dataset_id=dataset_id,
        source_id=source_id,
        source_rank=source_rank(source_id, hierarchy),
        findings=findings,
        verdict=verdict,
        quarantined=quarantined,
        golden=golden,
    )


class QuarantineRegistry:
    def __init__(self) -> None:
        self._items: dict[str, QuarantineRecord] = {}

    def quarantine(self, record: QuarantineRecord) -> QuarantineRecord:
        self._items[record.dataset_id] = record
        return record

    def release(self, dataset_id: str, *, released_at: str) -> QuarantineRecord | None:
        rec = self._items.get(dataset_id)
        if rec is None:
            return None
        rec.status = "RELEASED"
        rec.released_at = released_at
        return rec

    def is_quarantined(self, dataset_id: str) -> bool:
        rec = self._items.get(dataset_id)
        return rec is not None and rec.status == "QUARANTINED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [r.public_dict() for r in self._items.values()],
            "activeCount": sum(1 for r in self._items.values() if r.status == "QUARANTINED"),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def governance_rollup(reports: Sequence[GovernanceReport]) -> dict[str, Any]:
    states = [r.verdict for r in reports]
    return {
        "count": len(reports),
        "rollup": rollup_states(states).value,
        "quarantined": [r.dataset_id for r in reports if r.quarantined],
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "empty_rollup_is_EMPTY": len(reports) == 0,
        },
    }


# ---------------------------------------------------------------------------
# Wave 8 — Data certification (derived from persisted evidence, not caller bools)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataCertificationPolicy:
    require_pit: bool = True
    require_historical_universe: bool = False
    require_revision_lineage: bool = False
    require_corporate_actions: bool = False
    require_license_known: bool = True
    max_gap_ratio: float | None = 0.05

    def public_dict(self) -> dict[str, Any]:
        return {
            "requirePit": self.require_pit,
            "requireHistoricalUniverse": self.require_historical_universe,
            "requireRevisionLineage": self.require_revision_lineage,
            "requireCorporateActions": self.require_corporate_actions,
            "requireLicenseKnown": self.require_license_known,
            "maxGapRatio": self.max_gap_ratio,
        }


@dataclass
class DataCertification:
    certification_id: str
    dataset_id: str
    dataset_version_id: str
    dataset_hash: str
    certification_state: str
    pit_state: str
    survivorship_state: str
    revision_state: str
    corporate_action_state: str
    license_state: str
    evidence: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    source_id: str = ""
    data_type: str = "ohlcv"
    certification_hash: str = ""
    certified_at: str = ""
    certified_by: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "certificationId": self.certification_id,
            "datasetId": self.dataset_id,
            "datasetVersionId": self.dataset_version_id,
            "datasetHash": self.dataset_hash,
            "certificationState": self.certification_state,
            "pitState": self.pit_state,
            "survivorshipState": self.survivorship_state,
            "revisionState": self.revision_state,
            "corporateActionState": self.corporate_action_state,
            "licenseState": self.license_state,
            "evidence": dict(self.evidence),
            "blockers": list(self.blockers),
            "sourceId": self.source_id,
            "dataType": self.data_type,
            "certificationHash": self.certification_hash,
            "certifiedAt": self.certified_at,
            "certifiedBy": self.certified_by,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "caller_boolean_not_certification": True,
                "legacy_datasets_unmeasured_until_evaluated": True,
            },
        }


def certify_dataset_from_evidence(
    *,
    dataset_id: str,
    dataset_version_id: str,
    dataset_hash: str,
    evidence: Mapping[str, Any],
    policy: DataCertificationPolicy | None = None,
    source_id: str = "",
    data_type: str = "ohlcv",
    certified_by: str = "data_governance",
    certification_id: str | None = None,
) -> DataCertification:
    """Derive certification from persisted metadata/manifests — never caller certified=true."""
    import hashlib
    import json
    from datetime import datetime, timezone

    policy = policy or DataCertificationPolicy()
    if evidence.get("certified") is True and len(evidence) <= 2:
        # Explicit caller boolean alone is insufficient.
        return DataCertification(
            certification_id=certification_id or f"cert_{dataset_hash[:12]}",
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            dataset_hash=dataset_hash,
            certification_state=MeasurementState.UNMEASURED.value,
            pit_state=MeasurementState.UNMEASURED.value,
            survivorship_state=MeasurementState.UNMEASURED.value,
            revision_state=MeasurementState.UNMEASURED.value,
            corporate_action_state=MeasurementState.UNMEASURED.value,
            license_state=str(evidence.get("license_state") or "UNKNOWN"),
            evidence=dict(evidence),
            blockers=["CALLER_BOOLEAN_NOT_CERTIFICATION"],
            source_id=source_id,
            data_type=data_type,
            certified_by=certified_by,
        )

    blockers: list[str] = []
    pit = MeasurementState.UNMEASURED.value
    surv = MeasurementState.UNMEASURED.value
    rev = MeasurementState.UNMEASURED.value
    corp = MeasurementState.UNMEASURED.value
    license_state = str(evidence.get("license_state") or evidence.get("license") or "UNKNOWN")

    # Bar/OHLCV evidence
    if data_type.lower() in {"ohlcv", "bar", "bars"}:
        required_bar_keys = (
            "content_hash",
            "source_id",
            "timestamp_normalized",
            "ordering_ok",
            "duplicate_handling",
            "gap_report",
            "ohlc_invariants_ok",
        )
        missing = [k for k in required_bar_keys if k not in evidence]
        if missing:
            blockers.append("BAR_EVIDENCE_INCOMPLETE")
            pit = MeasurementState.UNMEASURED.value
        else:
            gap = evidence.get("gap_report") or {}
            gap_ratio = gap.get("gap_ratio") if isinstance(gap, dict) else None
            if policy.max_gap_ratio is not None and gap_ratio is not None and float(gap_ratio) > float(policy.max_gap_ratio):
                blockers.append("GAP_RATIO_EXCEEDED")
                pit = MeasurementState.FAIL.value
            elif evidence.get("pit_certified") or evidence.get("available_at_semantics"):
                pit = MeasurementState.PASS.value
            else:
                pit = MeasurementState.OBSERVED.value

    if policy.require_historical_universe:
        univ = evidence.get("universe") or evidence.get("historical_universe") or {}
        if not univ or univ.get("today_symbol_list_only"):
            surv = MeasurementState.UNMEASURED.value
            blockers.append("SURVIVORSHIP_UNMEASURED")
        elif univ.get("listing_events") and univ.get("delisting_events") is not None:
            surv = MeasurementState.PASS.value
        else:
            surv = MeasurementState.UNMEASURED.value
            blockers.append("SURVIVORSHIP_UNMEASURED")
    else:
        surv = MeasurementState.NOT_IMPLEMENTED.value if "universe" not in evidence else MeasurementState.OBSERVED.value

    if policy.require_revision_lineage:
        rev_ev = evidence.get("revisions") or {}
        if not (rev_ev.get("available_at") and rev_ev.get("event_time") and rev_ev.get("revision_id")):
            rev = MeasurementState.UNMEASURED.value
            blockers.append("REVISION_LINEAGE_UNMEASURED")
        else:
            rev = MeasurementState.PASS.value
    else:
        rev = MeasurementState.UNMEASURED.value

    if policy.require_corporate_actions:
        ca = evidence.get("corporate_actions")
        if not ca:
            corp = MeasurementState.UNMEASURED.value
            blockers.append("CORPORATE_ACTIONS_UNMEASURED")
        else:
            corp = MeasurementState.PASS.value
    else:
        corp = MeasurementState.UNMEASURED.value

    if policy.require_license_known and license_state in {"", "UNKNOWN", "UNMEASURED"}:
        blockers.append("LICENSE_UNKNOWN")

    if policy.require_pit and pit not in {
        MeasurementState.PASS.value,
        MeasurementState.MEASURED.value,
        MeasurementState.OBSERVED.value,
    }:
        blockers.append("DATA_PIT_NOT_CERTIFIED")

    if blockers:
        cert_state = MeasurementState.FAIL.value if any(
            b in blockers for b in ("DATA_PIT_NOT_CERTIFIED", "GAP_RATIO_EXCEEDED", "BAR_EVIDENCE_INCOMPLETE")
        ) else MeasurementState.UNMEASURED.value
    else:
        cert_state = MeasurementState.PASS.value

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = {
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "dataset_hash": dataset_hash,
        "pit": pit,
        "surv": surv,
        "rev": rev,
        "corp": corp,
        "license": license_state,
        "evidence": dict(evidence),
    }
    chash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return DataCertification(
        certification_id=certification_id or f"cert_{chash[:16]}",
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        dataset_hash=dataset_hash,
        certification_state=cert_state,
        pit_state=pit,
        survivorship_state=surv,
        revision_state=rev,
        corporate_action_state=corp,
        license_state=license_state,
        evidence=dict(evidence),
        blockers=blockers,
        source_id=source_id or str(evidence.get("source_id") or ""),
        data_type=data_type,
        certification_hash=chash,
        certified_at=now,
        certified_by=certified_by,
    )
