"""W37 — Capability gap matrix over existing market_sim owners.

Inventories CURRENT_OWNER, IMPLEMENTATION, TESTS, UI, STATUS, MISSING, TARGET_WAVE
from known market_sim reality — no fabricated PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass(frozen=True)
class CapabilityGapRow:
    capability: str
    current_owner: str
    implementation: str
    tests: str
    ui: str
    status: str
    missing: tuple[str, ...]
    target_wave: str
    notes: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "CURRENT_OWNER": self.current_owner,
            "IMPLEMENTATION": self.implementation,
            "TESTS": self.tests,
            "UI": self.ui,
            "STATUS": self.status,
            "MISSING": list(self.missing),
            "TARGET_WAVE": self.target_wave,
            "notes": self.notes,
        }


# Known reality snapshot — owners are existing market_sim / backend modules.
# STATUS uses honest vocabulary; COMPLETE means present for prior waves, not parity.
_KNOWN_GAPS: tuple[CapabilityGapRow, ...] = (
    CapabilityGapRow(
        capability="instrument_identity",
        current_owner="market_sim.instruments",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("canonical_alias_registry", "temporal_validity_window"),
        target_wave="W38",
        notes="InstrumentFamily + specs exist; master alias/temporal layer is W38.",
    ),
    CapabilityGapRow(
        capability="point_in_time_fabric",
        current_owner="market_sim.pit_fabric",
        implementation="PRESENT",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("bitemporal_lineage_export",),
        target_wave="W39",
    ),
    CapabilityGapRow(
        capability="dataset_quality",
        current_owner="market_sim.dataset_pipeline",
        implementation="PRESENT",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("quarantine_workflow", "golden_source_declaration"),
        target_wave="W40",
    ),
    CapabilityGapRow(
        capability="portfolio_book",
        current_owner="market_sim.portefeuille.ledger.PortfolioBook",
        implementation="PRESENT",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("enterprise_hierarchy", "event_reconstruction"),
        target_wave="W41",
    ),
    CapabilityGapRow(
        capability="accounting_wallet",
        current_owner="market_sim.accounting",
        implementation="PRESENT",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("subledger_journal", "lot_pnl_valuation_entries"),
        target_wave="W42",
    ),
    CapabilityGapRow(
        capability="reconciliation",
        current_owner="institutional_core.reconciliation",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("break_objects", "compare_contracts", "correlation"),
        target_wave="W43",
    ),
    CapabilityGapRow(
        capability="performance_attribution",
        current_owner="market_sim.portefeuille.attribution",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.ASSUMED.value,
        missing=("twr_mwr", "honest_methodology_labels"),
        target_wave="W44",
        notes="Position contribution exists; not Brinson/TWR/MWR.",
    ),
    CapabilityGapRow(
        capability="risk_analytics",
        current_owner="market_sim.risk_analytics + risk_guard",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("enterprise_aggregation", "concentration_rollups"),
        target_wave="W45",
    ),
    CapabilityGapRow(
        capability="scenario_stress",
        current_owner="market_sim.scenario_risk",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.ASSUMED.value,
        missing=("what_if_builder", "reverse_stress"),
        target_wave="W46",
    ),
    CapabilityGapRow(
        capability="liquidity_metrics",
        current_owner="institutional_core.liquidity",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("adv", "days_to_liquidate", "measurement_states"),
        target_wave="W47",
    ),
    CapabilityGapRow(
        capability="leverage_margin",
        current_owner="market_sim.short_margin + portefeuille.ledger",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.ASSUMED.value,
        missing=("collateral_model_labels", "enterprise_leverage_rollup"),
        target_wave="W48",
    ),
    CapabilityGapRow(
        capability="multi_asset_matrix",
        current_owner="market_sim.capabilities + instruments",
        implementation="PRESENT",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("institutional_capability_truth_pack"),
        target_wave="W49",
    ),
    CapabilityGapRow(
        capability="portfolio_construction",
        current_owner="institutional_core.construction",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("optimizer", "infeasible_honesty"),
        target_wave="W50",
    ),
    CapabilityGapRow(
        capability="mandates_policy",
        current_owner="market_sim.orchestra.types.Mandate",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("policy_as_code_pre_post_trade"),
        target_wave="W51",
    ),
    CapabilityGapRow(
        capability="decision_records",
        current_owner="market_sim.orchestra.types.DecisionRecord",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("immutable_hash_packets"),
        target_wave="W52",
    ),
    CapabilityGapRow(
        capability="model_risk",
        current_owner="institutional_core.model_risk",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("quant_lifecycle_states",),
        target_wave="W53",
    ),
    CapabilityGapRow(
        capability="ai_governance",
        current_owner="institutional_core.ai_governance",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("llm_governance_without_mcp_duplicate",),
        target_wave="W54",
    ),
    CapabilityGapRow(
        capability="strategy_lifecycle",
        current_owner="market_sim.strategy_lineage + promotion",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("closed_research_lifecycle_states"),
        target_wave="W55",
    ),
    CapabilityGapRow(
        capability="entitlements_sod",
        current_owner="institutional_core.entitlements",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("maker_checker", "cannot_approve_own_change"),
        target_wave="W56",
    ),
    CapabilityGapRow(
        capability="order_lifecycle",
        current_owner="market_sim.execution + paper_broker",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.OBSERVED.value,
        missing=("institutional_state_machine", "live_blocked_explicit"),
        target_wave="W57",
    ),
    CapabilityGapRow(
        capability="tca",
        current_owner="institutional_core.tca",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("implementation_shortfall", "measurement_states"),
        target_wave="W58",
    ),
    CapabilityGapRow(
        capability="corporate_actions",
        current_owner="market_sim.event_intel + pit_fabric",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.ASSUMED.value,
        missing=("economic_adjustments", "pit_ca_application"),
        target_wave="W59",
    ),
    CapabilityGapRow(
        capability="durable_workflows",
        current_owner="jobs.JobRuntime",
        implementation="PRESENT",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("durable_sm_helpers_for_job_runtime"),
        target_wave="W60",
        notes="Extend JobRuntime — never create a second queue.",
    ),
    CapabilityGapRow(
        capability="audit_log",
        current_owner="market_sim.institutional_ops.AuditLog",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("hash_chain", "corruption_detection"),
        target_wave="W61",
    ),
    CapabilityGapRow(
        capability="slo_health",
        current_owner="market_sim.institutional_ops.observability_snapshot",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="PARTIAL",
        status=MeasurementState.ASSUMED.value,
        missing=("slo_definitions", "honest_health_rollup"),
        target_wave="W62",
    ),
    CapabilityGapRow(
        capability="exception_ops",
        current_owner="institutional_core.exceptions_ops",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("unified_exception_lifecycle",),
        target_wave="W63",
    ),
    CapabilityGapRow(
        capability="resilience_dr",
        current_owner="institutional_core.resilience",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("backup_manifest", "restore_verification"),
        target_wave="W64",
        notes="In-process helpers only — no production DR claim.",
    ),
    CapabilityGapRow(
        capability="security_hardening",
        current_owner="institutional_core.security_hardening",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("least_privilege_checks", "redaction"),
        target_wave="W65",
    ),
    CapabilityGapRow(
        capability="api_contracts",
        current_owner="market_sim.institutional_ops.api_contract_check",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("institutional_api_catalog"),
        target_wave="W66",
    ),
    CapabilityGapRow(
        capability="event_contracts",
        current_owner="market_sim.market_event",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.OBSERVED.value,
        missing=("institutional_event_catalog"),
        target_wave="W67",
    ),
    CapabilityGapRow(
        capability="control_room",
        current_owner="institutional_core.control_room",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="PARTIAL",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("backend_snapshot_for_ui",),
        target_wave="W68",
    ),
    CapabilityGapRow(
        capability="governance_reporting",
        current_owner="institutional_core.reporting",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("report_packs_from_real_state",),
        target_wave="W69",
    ),
    CapabilityGapRow(
        capability="illiquid_private",
        current_owner="institutional_core.illiquid",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("private_asset_extensibility",),
        target_wave="W70",
    ),
    CapabilityGapRow(
        capability="scale_benchmarks",
        current_owner="market_sim.institutional_ops.scale_smoke",
        implementation="PARTIAL",
        tests="PRESENT",
        ui="ABSENT",
        status=MeasurementState.ASSUMED.value,
        missing=("institutional_bench_harness"),
        target_wave="W71",
        notes="scale_smoke is not a full multi-year benchmark.",
    ),
    CapabilityGapRow(
        capability="final_assurance",
        current_owner="institutional_core.assurance",
        implementation="NOT_IMPLEMENTED",
        tests="ABSENT",
        ui="ABSENT",
        status=MeasurementState.NOT_IMPLEMENTED.value,
        missing=("duplicate_owner_scan", "live_trading_blocked_verify"),
        target_wave="W72",
    ),
    CapabilityGapRow(
        capability="live_trading",
        current_owner="market_sim.trading_live_guard.LiveTradingGuard",
        implementation="PRESENT",
        tests="PRESENT",
        ui="PRESENT",
        status=MeasurementState.BLOCKED.value,
        missing=(),
        target_wave="N/A",
        notes="Live trading remains BLOCKED by design.",
    ),
)


@dataclass
class CapabilityGapMatrix:
    rows: list[CapabilityGapRow] = field(default_factory=list)
    generated_from: str = "market_sim_known_reality"

    def public_dict(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for row in self.rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
        return {
            "generatedFrom": self.generated_from,
            "rows": [r.public_dict() for r in self.rows],
            "byStatus": by_status,
            "count": len(self.rows),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "matrix_is_inventory_not_parity_claim": True,
                "not_implemented_rows_remain_honest": True,
            },
        }


def build_capability_gap_matrix(
    *,
    extra_rows: Sequence[CapabilityGapRow | Mapping[str, Any]] | None = None,
    include_known: bool = True,
) -> CapabilityGapMatrix:
    """Build the W37 gap matrix from known market_sim owners + optional extras."""
    rows: list[CapabilityGapRow] = list(_KNOWN_GAPS) if include_known else []
    for raw in extra_rows or ():
        if isinstance(raw, CapabilityGapRow):
            rows.append(raw)
            continue
        rows.append(
            CapabilityGapRow(
                capability=str(raw.get("capability") or raw.get("CAPABILITY") or "unknown"),
                current_owner=str(raw.get("current_owner") or raw.get("CURRENT_OWNER") or "UNASSIGNED"),
                implementation=str(raw.get("implementation") or raw.get("IMPLEMENTATION") or "UNKNOWN"),
                tests=str(raw.get("tests") or raw.get("TESTS") or "ABSENT"),
                ui=str(raw.get("ui") or raw.get("UI") or "ABSENT"),
                status=str(raw.get("status") or raw.get("STATUS") or MeasurementState.UNMEASURED.value),
                missing=tuple(raw.get("missing") or raw.get("MISSING") or ()),
                target_wave=str(raw.get("target_wave") or raw.get("TARGET_WAVE") or "UNASSIGNED"),
                notes=str(raw.get("notes") or ""),
            )
        )
    return CapabilityGapMatrix(rows=rows)


def gaps_for_wave(wave: str, matrix: CapabilityGapMatrix | None = None) -> list[dict[str, Any]]:
    m = matrix or build_capability_gap_matrix()
    target = str(wave).upper()
    return [r.public_dict() for r in m.rows if r.target_wave.upper() == target]


def open_gaps(matrix: CapabilityGapMatrix | None = None) -> list[dict[str, Any]]:
    """Rows that are not OBSERVED/BLOCKED-complete for live trading guard."""
    m = matrix or build_capability_gap_matrix()
    open_statuses = {
        MeasurementState.NOT_IMPLEMENTED.value,
        MeasurementState.UNMEASURED.value,
        MeasurementState.UNAVAILABLE.value,
        MeasurementState.ASSUMED.value,
        MeasurementState.EMPTY.value,
    }
    return [
        r.public_dict()
        for r in m.rows
        if r.status in open_statuses or r.missing
    ]
