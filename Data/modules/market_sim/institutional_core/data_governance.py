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
