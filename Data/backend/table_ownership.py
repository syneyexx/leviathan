"""Machine-verifiable ownership map: every product table → exactly one DB domain.

Shared infrastructure tables (schema_migrations, commit_receipts, commit_batches)
exist in *each* canonical DB but are not migrated as authoritative duplicates from
legacy — they are recreated per domain. Legacy commit receipts are copied into
CONTROL only.
"""

from __future__ import annotations

from typing import Mapping

from Data.modules.common.database_domains import DatabaseDomain

# Tables that are created empty in every canonical DB (lane-local infrastructure).
PER_DATABASE_INFRASTRUCTURE: frozenset[str] = frozenset(
    {
        "schema_migrations",
        "commit_receipts",
        "commit_batches",
    }
)

# Product tables owned exclusively by CONTROL (legacy cutover copies here).
CONTROL_TABLES: frozenset[str] = frozenset(
    {
        "agent_definitions",
        "agent_events",
        "agent_missions",
        "agent_signal_dead_letters",
        "agent_signal_dedupe",
        "agent_signal_deliveries",
        "agent_signal_subscriptions",
        "agent_signals",
        "approvals",
        "artifacts",
        "authority_profiles",
        "behavior_profiles",
        "browser_sessions",
        "capability_call_receipts",
        "coding_change_plans",
        "coding_patches",
        "coding_semantic_map_cache",
        "coding_sessions",
        "coding_steps",
        "coding_turns",
        "cognitive_beliefs",
        "cognitive_events",
        "cognitive_runs",
        "context_snapshots",
        "conversations",
        "effect_ledger",
        "eval_case_results",
        "eval_regression_corpus",
        "eval_reports",
        "evidence",
        "external_log_windows",
        "external_module_versions",
        "external_modules",
        "external_plugin_bindings",
        "external_process_records",
        "external_skill_catalogs",
        "external_skills",
        "flywheel_challenger_proposals",
        "flywheel_promotions",
        "inference_efficiency_aggregates",
        "inference_efficiency_capabilities",
        "intelligence_assimilation_receipts",
        "jobs",
        "mcp_servers",
        "mcp_tool_calls",
        "mcp_tools",
        "memory_entries",
        "memory_fts",
        "memory_snapshots",
        "messages",
        "model_audit_log",
        "model_capability_results",
        "model_control_state",
        "model_downloads",
        "model_lineage_edges",
        "model_profiles",
        "model_providers",
        "model_registry",
        "model_residency_policies",
        "model_route_decisions",
        "model_runtime_bindings",
        "model_serving_workers",
        "multimodal_messages",
        "multimodal_sessions",
        "neuro_memory_snapshots",
        "observability_events",
        "preference_records",
        "provider_stream_events",
        "quality_acceptances",
        "quality_contracts",
        "quality_verdicts",
        "research_claim_edges",
        "research_claims",
        "research_conflicts",
        "research_events",
        "research_evidence",
        "research_projects",
        "research_reports",
        "research_reproducibility_bundles",
        "research_runs",
        "research_sources",
        "research_workers",
        "residual_receipts",
        "resource_reservations",
        "run_events",
        "runs",
        "schedules",
        "secret_credential_leases",
        "settings_overrides",
        "supervisor_leases",
        "task_dependencies",
        "task_events",
        "task_notes",
        "task_subtasks",
        "tasks",
        "tool_observations",
        "training_artifacts",
        "training_checkpoints",
        "training_jobs",
        "training_metrics",
        "verification_reports",
        "verified_experiences",
        "voice_realtime_sessions",
        "worker_instances",
        "worker_pool_desired",
        "worker_pools",
        "workflows",
        # Cutover ledger lives only on control.
        "db_cutover_state",
        "db_cutover_table_receipts",
        # Legacy commit receipts migrate to control only.
        "commit_receipts",
        "commit_batches",
    }
)

KNOWLEDGE_TABLES: frozenset[str] = frozenset(
    {
        "atlas_records",
        "dataset_annotation_items",
        "dataset_commit_index_rows",
        "dataset_files",
        "dataset_indexes",
        "dataset_jobs",
        "dataset_mixtures",
        "dataset_versions",
        "datasets",
        "deep_recall_logs",
        "directional_relation_atoms",
        "knowledge_chunk_embeddings",
        "knowledge_chunk_fts",
        "knowledge_chunks",
        "knowledge_commit_receipts",
        "knowledge_documents",
        "knowledge_fts",
        "knowledge_ingest_files",
        "retrieval_traces",
        "source_ingestion_commit_records",
        "source_ingestion_containers",
        "source_ingestion_members",
        "why_records",
        "atlas_fts",
    }
)

MARKET_TABLES: frozenset[str] = frozenset(
    {
        "institutional_audit_chain",
        "institutional_authority_approvals",
        "institutional_bitemporal_records",
        "institutional_breaks",
        "institutional_decision_packets",
        "institutional_exceptions",
        "institutional_ibor_events",
        "institutional_instrument_aliases",
        "institutional_instruments",
        "institutional_journal_entries",
        "institutional_mandates",
        "institutional_model_governance",
        "institutional_quarantine",
        "institutional_recon_runs",
        "institutional_valuation_snapshots",
        "institutional_workflow_checkpoints",
        "market_data_sources",
        "market_dataset_versions",
        "market_decisions",
        "market_experiments",
        "market_feed_checkpoints",
        "market_feed_latency_rollups",
        "market_feed_sessions",
        "market_knowledge_snapshots",
        "market_news_feeds",
        "market_news_items",
        "market_news_signals",
        "market_paper_deployments",
        "market_paper_sessions",
        "market_qualification_gate_results",
        "market_qualification_policies",
        "market_qualification_runs",
        "market_research_command_sessions",
        "market_dataset_certifications",
        "market_execution_calibrations",
        "market_strategy_behavior_fingerprints",
        "market_strategy_lifecycle",
        "market_strategy_risk_snapshots",
        "market_wfa_folds",
        "market_sim_agent_labs",
        "market_sim_closed_trades",
        "market_sim_commit_batches",
        "market_sim_equity",
        "market_sim_events",
        "market_sim_fills",
        "market_sim_learning_runs",
        "market_sim_messages",
        "market_sim_portfolio_allocations",
        "market_sim_portfolio_orders",
        "market_sim_portfolio_positions",
        "market_sim_portfolio_recommendations",
        "market_sim_portfolio_snapshots",
        "market_sim_portfolio_transactions",
        "market_sim_portfolios",
        "market_sim_research_campaigns",
        "market_sim_runs",
        "market_sim_sealed_attempts",
        "market_sim_split_manifests",
        "market_strategies",
        "market_strategy_memories",
        "market_strategy_versions",
    }
)

# Explicit non-product / ephemeral classifications (tests assert known set).
EPHEMERAL_OR_NON_PRODUCT: frozenset[str] = frozenset(
    {
        "sqlite_sequence",  # SQLite internal
        "sqlite_stat1",
        "sqlite_stat4",
    }
)

_FTS_SHADOW_SUFFIXES: tuple[str, ...] = (
    "_fts_data",
    "_fts_idx",
    "_fts_content",
    "_fts_docsize",
    "_fts_config",
)


def is_fts_shadow_table(name: str) -> bool:
    """True for SQLite FTS5 shadow tables auto-managed with a virtual table."""
    return any(name.endswith(suffix) for suffix in _FTS_SHADOW_SUFFIXES)

_DOMAIN_SETS: Mapping[DatabaseDomain, frozenset[str]] = {
    DatabaseDomain.CONTROL: CONTROL_TABLES,
    DatabaseDomain.KNOWLEDGE: KNOWLEDGE_TABLES,
    DatabaseDomain.MARKET: MARKET_TABLES,
}


class TableOwnershipError(ValueError):
    """Raised when a table has missing or ambiguous ownership."""


def ownership_for(table: str) -> DatabaseDomain | None:
    """Return owning domain, or None for infrastructure/ephemeral-only names."""
    name = table.strip()
    if not name:
        raise TableOwnershipError("empty table name")
    if name in EPHEMERAL_OR_NON_PRODUCT or is_fts_shadow_table(name):
        return None
    if name in PER_DATABASE_INFRASTRUCTURE and name not in CONTROL_TABLES:
        # schema_migrations is per-DB infrastructure and not a product cutover table.
        return None
    hits = [domain for domain, tables in _DOMAIN_SETS.items() if name in tables]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise TableOwnershipError(f"table {name!r} mapped to multiple domains: {hits}")
    return None


def require_ownership(table: str) -> DatabaseDomain:
    domain = ownership_for(table)
    if domain is None:
        raise TableOwnershipError(f"no database ownership classification for table {table!r}")
    return domain


def tables_for(domain: DatabaseDomain | str) -> frozenset[str]:
    key = DatabaseDomain(domain)
    return _DOMAIN_SETS[key]


def all_classified_product_tables() -> frozenset[str]:
    return frozenset().union(*_DOMAIN_SETS.values())


def cutover_copy_tables_for(domain: DatabaseDomain | str) -> frozenset[str]:
    """Tables whose *rows* are copied from legacy into the domain DB.

    Per-DB infrastructure is seeded empty except CONTROL which receives legacy
    commit_receipts / commit_batches.
    """
    key = DatabaseDomain(domain)
    owned = set(tables_for(key))
    if key is DatabaseDomain.CONTROL:
        owned |= {"commit_receipts", "commit_batches", "db_cutover_state", "db_cutover_table_receipts"}
        owned.discard("schema_migrations")
        return frozenset(owned)
    owned -= PER_DATABASE_INFRASTRUCTURE
    owned.discard("db_cutover_state")
    owned.discard("db_cutover_table_receipts")
    return frozenset(owned)


def validate_no_ambiguous_overlap() -> None:
    pairs = (
        (DatabaseDomain.CONTROL, DatabaseDomain.KNOWLEDGE),
        (DatabaseDomain.CONTROL, DatabaseDomain.MARKET),
        (DatabaseDomain.KNOWLEDGE, DatabaseDomain.MARKET),
    )
    for left, right in pairs:
        overlap = tables_for(left) & tables_for(right)
        # commit_* intentionally listed under CONTROL for cutover; not in K/M product sets.
        if overlap:
            raise TableOwnershipError(f"ownership overlap between {left} and {right}: {sorted(overlap)}")


def ownership_public_dict() -> dict[str, object]:
    return {
        "schema_version": 1,
        "domains": [d.value for d in DatabaseDomain],
        "control_tables": sorted(CONTROL_TABLES),
        "knowledge_tables": sorted(KNOWLEDGE_TABLES),
        "market_tables": sorted(MARKET_TABLES),
        "per_database_infrastructure": sorted(PER_DATABASE_INFRASTRUCTURE),
        "ephemeral_or_non_product": sorted(EPHEMERAL_OR_NON_PRODUCT),
        "counts": {
            "control": len(CONTROL_TABLES),
            "knowledge": len(KNOWLEDGE_TABLES),
            "market": len(MARKET_TABLES),
        },
    }


# Fail import if the static map is inconsistent.
validate_no_ambiguous_overlap()
