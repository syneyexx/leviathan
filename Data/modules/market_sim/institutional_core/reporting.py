"""W69 — Governance report packs built from real institutional_core state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH, rollup_states
from .gap_ledger import build_capability_gap_matrix, open_gaps


@dataclass
class ReportSection:
    section_id: str
    title: str
    status: str
    body: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "title": self.title,
            "status": self.status,
            "body": dict(self.body),
        }


@dataclass
class GovernanceReportPack:
    pack_id: str
    generated_at: str
    sections: list[ReportSection]
    overall_status: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "packId": self.pack_id,
            "generatedAt": self.generated_at,
            "sections": [s.public_dict() for s in self.sections],
            "overallStatus": self.overall_status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "built_from_real_state": True,
                "no_fabricated_metrics": True,
            },
        }


def build_governance_report_pack(
    *,
    pack_id: str,
    generated_at: str,
    live_trading_status: Mapping[str, Any] | None = None,
    health: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    audit_verify: Mapping[str, Any] | None = None,
    exceptions: Mapping[str, Any] | None = None,
    assurance: Mapping[str, Any] | None = None,
) -> GovernanceReportPack:
    sections: list[ReportSection] = []

    matrix = build_capability_gap_matrix()
    open_rows = open_gaps(matrix)
    sections.append(
        ReportSection(
            section_id="gap_matrix",
            title="Capability gap matrix",
            status=MeasurementState.OBSERVED.value,
            body={
                "openGapCount": len(open_rows),
                "byStatus": matrix.public_dict()["byStatus"],
            },
        )
    )

    live = dict(live_trading_status or {})
    live_state = str(
        live.get("LIVE_TRADING_AVAILABLE")
        or live.get("status")
        or MeasurementState.UNMEASURED.value
    )
    sections.append(
        ReportSection(
            section_id="live_trading",
            title="Live trading guard",
            status=live_state if live else MeasurementState.UNMEASURED.value,
            body=live or {"status": MeasurementState.UNMEASURED.value},
        )
    )

    if health is not None:
        sections.append(
            ReportSection(
                section_id="slo_health",
                title="SLO health",
                status=str(health.get("overall") or health.get("status") or MeasurementState.UNMEASURED.value),
                body=dict(health),
            )
        )
    else:
        sections.append(
            ReportSection(
                section_id="slo_health",
                title="SLO health",
                status=MeasurementState.UNMEASURED.value,
                body={"status": MeasurementState.UNMEASURED.value},
            )
        )

    if reconciliation is not None:
        sections.append(
            ReportSection(
                section_id="reconciliation",
                title="Reconciliation",
                status=str(reconciliation.get("status") or MeasurementState.OBSERVED.value),
                body=dict(reconciliation),
            )
        )
    else:
        sections.append(
            ReportSection(
                section_id="reconciliation",
                title="Reconciliation",
                status=MeasurementState.EMPTY.value,
                body={"status": MeasurementState.EMPTY.value},
            )
        )

    if audit_verify is not None:
        sections.append(
            ReportSection(
                section_id="audit_integrity",
                title="Audit hash chain",
                status=str(audit_verify.get("status") or MeasurementState.UNMEASURED.value),
                body=dict(audit_verify),
            )
        )
    else:
        sections.append(
            ReportSection(
                section_id="audit_integrity",
                title="Audit hash chain",
                status=MeasurementState.UNMEASURED.value,
                body={"status": MeasurementState.UNMEASURED.value},
            )
        )

    if exceptions is not None:
        sections.append(
            ReportSection(
                section_id="exceptions",
                title="Open exceptions",
                status=str(exceptions.get("status") or MeasurementState.EMPTY.value),
                body=dict(exceptions),
            )
        )

    if assurance is not None:
        sections.append(
            ReportSection(
                section_id="assurance",
                title="Final assurance",
                status=str(assurance.get("status") or MeasurementState.UNMEASURED.value),
                body=dict(assurance),
            )
        )

    overall = rollup_states([s.status for s in sections]).value
    return GovernanceReportPack(
        pack_id=pack_id,
        generated_at=generated_at,
        sections=sections,
        overall_status=overall,
    )
