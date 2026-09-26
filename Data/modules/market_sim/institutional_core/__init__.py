"""Institutional Core (W37–W72) — domain logic extending market_sim owners.

Public API for capability gaps, IBOR hierarchy, reconciliation, risk, governance,
orders (paper/sim), audit integrity, control room snapshots, and assurance.
Live trading remains BLOCKED. No parallel BrainV2 / RiskEngineV2 / JobRuntime.
"""

from __future__ import annotations

from .status import (
    MeasurementState,
    STATUS_VOCABULARY,
    StatusedValue,
    TruthFlags,
    DEFAULT_TRUTH,
    coerce_measurement,
    is_green_claim,
    rollup_states,
    attach_truth,
)
from .store import MemoryStore, SqliteReadyStore
from .gap_ledger import (
    CapabilityGapRow,
    CapabilityGapMatrix,
    build_capability_gap_matrix,
    gaps_for_wave,
    open_gaps,
)
from .instrument_master import (
    TemporalWindow,
    InstrumentAlias,
    CanonicalInstrument,
    ResolutionResult,
    InstrumentMaster,
    instrument_from_mapping,
    resolve_many,
)
from .bitemporal import (
    BitemporalStamp,
    LineageRef,
    BitemporalRecord,
    BitemporalStore,
    build_record,
    compare_clocks,
    content_hash as bitemporal_content_hash,
)
from .data_governance import (
    QualityRule,
    QualityFinding,
    QuarantineRecord,
    GoldenSourceDeclaration,
    GovernanceReport,
    QuarantineRegistry,
    DEFAULT_QUALITY_RULES,
    DEFAULT_SOURCE_HIERARCHY,
    source_rank,
    prefer_source,
    evaluate_quality,
    governance_rollup,
)
from .ibor import (
    HIERARCHY_LEVELS,
    HierarchyNode,
    LotState,
    PositionState,
    IborSnapshot,
    IborEvent,
    reconstruct_ibor,
    children_of,
    validate_hierarchy,
)
from .subledger import (
    JOURNAL_ACCOUNTS,
    JournalLine,
    JournalEntry,
    SubledgerBalances,
    Subledger,
    trade_entry,
    valuation_entry,
    realize_pnl_entry,
    replay_balances,
)
from .reconciliation import (
    BREAK_STATUSES,
    Break,
    CompareContract,
    ReconciliationRun,
    transition_break,
    compare_maps,
    correlate_breaks,
    run_reconciliation,
    break_fingerprint,
)
from .performance import (
    Cashflow,
    PerformanceReport,
    simple_period_return,
    time_weighted_return,
    money_weighted_return,
    attribute_position_contributions,
    compute_performance,
)
from .enterprise_risk import (
    PositionRiskInput,
    ConcentrationBucket,
    EnterpriseRiskReport,
    aggregate_enterprise_risk,
)
from .stress_engine import (
    WhatIfShock,
    WhatIfResult,
    ReverseStressResult,
    run_what_if,
    reverse_stress_uniform,
)
from .liquidity import (
    LiquidityInput,
    LiquidityMetric,
    LiquidityReport,
    days_to_liquidate,
    evaluate_liquidity,
)
from .leverage_margin import (
    CollateralHaircut,
    MarginPosition,
    LeverageMarginReport,
    collateral_after_haircut,
    compute_leverage_margin,
)
from .multi_asset import (
    AssetClassCapability,
    MultiAssetTruthPack,
    build_multi_asset_truth_pack,
    family_status,
)
from .construction import (
    WeightBound,
    ConstructionConstraints,
    ConstructionResult,
    check_feasibility,
    optimize_scores,
)
from .mandates import (
    OrderIntent,
    PolicyViolation,
    PolicyDecision,
    mandate_fingerprint,
    pre_trade_check,
    post_trade_check,
    load_mandate,
)
from .decision_ledger import (
    HashRef,
    DecisionPacket,
    DecisionLedger,
    hash_payload,
    packet_from_decision_record,
)
from .model_risk import (
    MODEL_STATES,
    ModelCard,
    ModelRiskRegistry,
    model_card_from_mapping,
)
from .ai_governance import (
    LlmUseCase,
    AiGovernanceDecision,
    evaluate_llm_action,
    governance_inventory,
    redact_mapping,
)
from .strategy_lifecycle import (
    LIFECYCLE_STATES,
    StrategyLifecycleRecord,
    StrategyLifecycle,
    record_from_mapping,
)
from .entitlements import (
    ChangeRequest,
    ApprovalDecision,
    cannot_approve_own_change,
    required_authority_for_change,
    evaluate_approval,
    segregation_matrix,
)
from .order_lifecycle import (
    ORDER_STATES,
    Order,
    OrderLifecycle,
    order_from_mapping,
)
from .tca import (
    FillObservation,
    TcaMetrics,
    analyze_fill,
    analyze_fills,
)
from .corporate_actions import (
    CA_TYPES,
    CorporateAction,
    PositionAdjustment,
    apply_corporate_action,
    apply_ca_series,
)
from .durable_workflows import (
    WorkflowStep,
    WorkflowCheckpoint,
    DurableWorkflow,
    start_workflow,
    advance_workflow,
    resume_from_checkpoint,
    workflow_progress,
)
from .audit_integrity import (
    GENESIS_HASH,
    ChainedAuditEvent,
    HashChainedAuditLog,
    detect_corruption,
)
from .institutional_slo import (
    SloDefinition,
    SloObservation,
    HealthRollup,
    DEFAULT_SLOS,
    evaluate_slo,
    health_rollup,
    institutional_slo_snapshot,
)
from .exceptions_ops import (
    EXCEPTION_STATUSES,
    OpsException,
    ExceptionRegistry,
    exception_from_mapping,
)
from .resilience import (
    BackupArtifact,
    BackupManifest,
    build_backup_manifest,
    verify_restore,
    fault_inject,
)
from .security_hardening import (
    PrivilegeRequirement,
    PrivilegeCheckResult,
    DEFAULT_PRIVILEGES,
    check_least_privilege,
    redact_secrets,
    security_posture_snapshot,
)
from .api_surface import (
    ApiContract,
    INSTITUTIONAL_API_CATALOG,
    api_catalog_public,
    check_institutional_api,
)
from .events import (
    EventContract,
    INSTITUTIONAL_EVENT_CATALOG,
    event_catalog_public,
    validate_event,
)
from .control_room import ControlRoomSnapshot, build_control_room_snapshot
from .reporting import ReportSection, GovernanceReportPack, build_governance_report_pack
from .illiquid import (
    ILLIQUID_FAMILIES,
    IlliquidInstrument,
    IlliquidValuation,
    IlliquidRegistry,
)
from .scale_bench import (
    BenchCase,
    BenchResult,
    DEFAULT_BENCH_CASES,
    run_bench_case,
    run_scale_bench,
)
from .assurance import (
    FORBIDDEN_OWNER_CLASS_NAMES,
    AssuranceFinding,
    AssuranceReport,
    scan_forbidden_owner_classes,
    verify_live_trading_blocked,
    run_assurance,
)

__all__ = [
    # status
    "MeasurementState",
    "STATUS_VOCABULARY",
    "StatusedValue",
    "TruthFlags",
    "DEFAULT_TRUTH",
    "coerce_measurement",
    "is_green_claim",
    "rollup_states",
    "attach_truth",
    # store
    "MemoryStore",
    "SqliteReadyStore",
    # W37
    "CapabilityGapRow",
    "CapabilityGapMatrix",
    "build_capability_gap_matrix",
    "gaps_for_wave",
    "open_gaps",
    # W38
    "TemporalWindow",
    "InstrumentAlias",
    "CanonicalInstrument",
    "ResolutionResult",
    "InstrumentMaster",
    "instrument_from_mapping",
    "resolve_many",
    # W39
    "BitemporalStamp",
    "LineageRef",
    "BitemporalRecord",
    "BitemporalStore",
    "build_record",
    "compare_clocks",
    "bitemporal_content_hash",
    # W40
    "QualityRule",
    "QualityFinding",
    "QuarantineRecord",
    "GoldenSourceDeclaration",
    "GovernanceReport",
    "QuarantineRegistry",
    "DEFAULT_QUALITY_RULES",
    "DEFAULT_SOURCE_HIERARCHY",
    "source_rank",
    "prefer_source",
    "evaluate_quality",
    "governance_rollup",
    # W41
    "HIERARCHY_LEVELS",
    "HierarchyNode",
    "LotState",
    "PositionState",
    "IborSnapshot",
    "IborEvent",
    "reconstruct_ibor",
    "children_of",
    "validate_hierarchy",
    # W42
    "JOURNAL_ACCOUNTS",
    "JournalLine",
    "JournalEntry",
    "SubledgerBalances",
    "Subledger",
    "trade_entry",
    "valuation_entry",
    "realize_pnl_entry",
    "replay_balances",
    # W43
    "BREAK_STATUSES",
    "Break",
    "CompareContract",
    "ReconciliationRun",
    "transition_break",
    "compare_maps",
    "correlate_breaks",
    "run_reconciliation",
    "break_fingerprint",
    # W44
    "Cashflow",
    "PerformanceReport",
    "simple_period_return",
    "time_weighted_return",
    "money_weighted_return",
    "attribute_position_contributions",
    "compute_performance",
    # W45
    "PositionRiskInput",
    "ConcentrationBucket",
    "EnterpriseRiskReport",
    "aggregate_enterprise_risk",
    # W46
    "WhatIfShock",
    "WhatIfResult",
    "ReverseStressResult",
    "run_what_if",
    "reverse_stress_uniform",
    # W47
    "LiquidityInput",
    "LiquidityMetric",
    "LiquidityReport",
    "days_to_liquidate",
    "evaluate_liquidity",
    # W48
    "CollateralHaircut",
    "MarginPosition",
    "LeverageMarginReport",
    "collateral_after_haircut",
    "compute_leverage_margin",
    # W49
    "AssetClassCapability",
    "MultiAssetTruthPack",
    "build_multi_asset_truth_pack",
    "family_status",
    # W50
    "WeightBound",
    "ConstructionConstraints",
    "ConstructionResult",
    "check_feasibility",
    "optimize_scores",
    # W51
    "OrderIntent",
    "PolicyViolation",
    "PolicyDecision",
    "mandate_fingerprint",
    "pre_trade_check",
    "post_trade_check",
    "load_mandate",
    # W52
    "HashRef",
    "DecisionPacket",
    "DecisionLedger",
    "hash_payload",
    "packet_from_decision_record",
    # W53
    "MODEL_STATES",
    "ModelCard",
    "ModelRiskRegistry",
    "model_card_from_mapping",
    # W54
    "LlmUseCase",
    "AiGovernanceDecision",
    "evaluate_llm_action",
    "governance_inventory",
    "redact_mapping",
    # W55
    "LIFECYCLE_STATES",
    "StrategyLifecycleRecord",
    "StrategyLifecycle",
    "record_from_mapping",
    # W56
    "ChangeRequest",
    "ApprovalDecision",
    "cannot_approve_own_change",
    "required_authority_for_change",
    "evaluate_approval",
    "segregation_matrix",
    # W57
    "ORDER_STATES",
    "Order",
    "OrderLifecycle",
    "order_from_mapping",
    # W58
    "FillObservation",
    "TcaMetrics",
    "analyze_fill",
    "analyze_fills",
    # W59
    "CA_TYPES",
    "CorporateAction",
    "PositionAdjustment",
    "apply_corporate_action",
    "apply_ca_series",
    # W60
    "WorkflowStep",
    "WorkflowCheckpoint",
    "DurableWorkflow",
    "start_workflow",
    "advance_workflow",
    "resume_from_checkpoint",
    "workflow_progress",
    # W61
    "GENESIS_HASH",
    "ChainedAuditEvent",
    "HashChainedAuditLog",
    "detect_corruption",
    # W62
    "SloDefinition",
    "SloObservation",
    "HealthRollup",
    "DEFAULT_SLOS",
    "evaluate_slo",
    "health_rollup",
    "institutional_slo_snapshot",
    # W63
    "EXCEPTION_STATUSES",
    "OpsException",
    "ExceptionRegistry",
    "exception_from_mapping",
    # W64
    "BackupArtifact",
    "BackupManifest",
    "build_backup_manifest",
    "verify_restore",
    "fault_inject",
    # W65
    "PrivilegeRequirement",
    "PrivilegeCheckResult",
    "DEFAULT_PRIVILEGES",
    "check_least_privilege",
    "redact_secrets",
    "security_posture_snapshot",
    # W66
    "ApiContract",
    "INSTITUTIONAL_API_CATALOG",
    "api_catalog_public",
    "check_institutional_api",
    # W67
    "EventContract",
    "INSTITUTIONAL_EVENT_CATALOG",
    "event_catalog_public",
    "validate_event",
    # W68
    "ControlRoomSnapshot",
    "build_control_room_snapshot",
    # W69
    "ReportSection",
    "GovernanceReportPack",
    "build_governance_report_pack",
    # W70
    "ILLIQUID_FAMILIES",
    "IlliquidInstrument",
    "IlliquidValuation",
    "IlliquidRegistry",
    # W71
    "BenchCase",
    "BenchResult",
    "DEFAULT_BENCH_CASES",
    "run_bench_case",
    "run_scale_bench",
    # W72
    "FORBIDDEN_OWNER_CLASS_NAMES",
    "AssuranceFinding",
    "AssuranceReport",
    "scan_forbidden_owner_classes",
    "verify_live_trading_blocked",
    "run_assurance",
]
