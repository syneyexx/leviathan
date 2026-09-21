"""Trading Lab metadata storage.

Shares the existing HADES SQLite file through ``PlatformDatabase.connection()`` and follows
the same additive-migration discipline as ``backend/gen2/store.py``: every statement is
``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``, nothing existing is dropped
or rewritten, and the migration is recorded in the shared ``schema_migrations`` table plus a
subsystem-local ``lab_schema_migrations`` table.

Bulk market history does **not** live here; see ``trading_lab/bar_store.py``. SQLite holds
metadata: manifests, strategy versions, experiments, trials, runs, orders, fills, ledger
entries, snapshots, decisions, evaluations, model artefacts, agent tasks and the job queue.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any, Iterable, Sequence

from platform_db import PlatformDatabase, new_id, utc_now

LAB_SCHEMA_VERSION = 3
SHARED_MIGRATION_VERSION = 19

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_instruments (
    instrument_id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_instruments_family ON lab_instruments(family, venue, symbol);

CREATE TABLE IF NOT EXISTS lab_datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    data_level TEXT NOT NULL DEFAULT 'ohlcv',
    provider TEXT NOT NULL,
    provider_kind TEXT NOT NULL DEFAULT 'import',
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    row_count INTEGER NOT NULL DEFAULT 0,
    first_event_time TEXT,
    last_event_time TEXT,
    content_checksum TEXT NOT NULL DEFAULT '',
    frozen INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_datasets_instrument
    ON lab_datasets(instrument_id, timeframe, revision DESC);

CREATE TABLE IF NOT EXISTS lab_dataset_events (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(dataset_id, kind, event_time)
);
CREATE INDEX IF NOT EXISTS idx_lab_dataset_events_available
    ON lab_dataset_events(dataset_id, available_at);

CREATE TABLE IF NOT EXISTS lab_strategies (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    family TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'concept',
    current_version INTEGER NOT NULL DEFAULT 1,
    hypothesis_json TEXT NOT NULL DEFAULT '{}',
    owner TEXT NOT NULL DEFAULT 'operator',
    created_by TEXT NOT NULL DEFAULT 'operator',
    scope_note TEXT NOT NULL DEFAULT '',
    rejection_reason TEXT NOT NULL DEFAULT '',
    knowledge_source_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_strategies_status ON lab_strategies(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS lab_strategy_versions (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    code_reference TEXT NOT NULL DEFAULT '',
    code_hash TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'operator',
    created_at TEXT NOT NULL,
    UNIQUE(strategy_id, version)
);

CREATE TABLE IF NOT EXISTS lab_strategy_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_role TEXT NOT NULL DEFAULT 'operator',
    report_id TEXT,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_status_history_strategy
    ON lab_strategy_status_history(strategy_id, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_experiments (
    experiment_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    strategy_family TEXT NOT NULL,
    strategy_id TEXT,
    split TEXT NOT NULL DEFAULT 'development',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    search_method TEXT NOT NULL DEFAULT 'single',
    search_budget INTEGER NOT NULL DEFAULT 1,
    trials_completed INTEGER NOT NULL DEFAULT 0,
    trials_failed INTEGER NOT NULL DEFAULT 0,
    seed INTEGER NOT NULL DEFAULT 7,
    spec_json TEXT NOT NULL,
    dataset_hash TEXT NOT NULL DEFAULT '',
    code_hash TEXT NOT NULL DEFAULT '',
    base_commit TEXT NOT NULL DEFAULT '',
    best_trial_id TEXT,
    requested_by TEXT NOT NULL DEFAULT 'operator',
    job_id TEXT,
    preregistration_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_experiments_status ON lab_experiments(status, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_trials (
    trial_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    trial_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    params_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    run_id TEXT,
    split TEXT NOT NULL DEFAULT 'development',
    dataset_hash TEXT NOT NULL DEFAULT '',
    code_hash TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(experiment_id, trial_index)
);
CREATE INDEX IF NOT EXISTS idx_lab_trials_experiment ON lab_trials(experiment_id, trial_index);

CREATE TABLE IF NOT EXISTS lab_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'historical_simulation',
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'created',
    progress INTEGER NOT NULL DEFAULT 0,
    experiment_id TEXT,
    trial_id TEXT,
    strategy_id TEXT,
    strategy_version INTEGER,
    strategy_hash TEXT NOT NULL DEFAULT '',
    split TEXT NOT NULL DEFAULT 'development',
    dataset_ids_json TEXT NOT NULL DEFAULT '[]',
    dataset_hash TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    cost_model_json TEXT NOT NULL DEFAULT '{}',
    risk_limits_json TEXT NOT NULL DEFAULT '{}',
    seeds_json TEXT NOT NULL DEFAULT '{}',
    model_versions_json TEXT NOT NULL DEFAULT '{}',
    base_commit TEXT NOT NULL DEFAULT '',
    engine_version TEXT NOT NULL DEFAULT '',
    simulation_time TEXT,
    first_event_time TEXT,
    last_event_time TEXT,
    events_processed INTEGER NOT NULL DEFAULT 0,
    branch_of_run_id TEXT,
    branch_from_event_time TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_runs_status ON lab_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_runs_strategy ON lab_runs(strategy_id, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_key TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL DEFAULT 'engine',
    simulation_time TEXT,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lab_run_events_key
    ON lab_run_events(run_id, event_key) WHERE event_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lab_run_events_run ON lab_run_events(run_id, id DESC);

CREATE TABLE IF NOT EXISTS lab_orders (
    order_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    strategy_id TEXT,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    time_in_force TEXT NOT NULL DEFAULT 'GTC',
    status TEXT NOT NULL DEFAULT 'accepted',
    quantity TEXT NOT NULL,
    filled_quantity TEXT NOT NULL DEFAULT '0',
    average_fill_price TEXT,
    limit_price TEXT,
    stop_price TEXT,
    reduce_only INTEGER NOT NULL DEFAULT 0,
    post_only INTEGER NOT NULL DEFAULT 0,
    parent_order_id TEXT,
    oco_group TEXT,
    intent_json TEXT NOT NULL DEFAULT '{}',
    risk_decision_json TEXT NOT NULL DEFAULT '{}',
    price_source TEXT NOT NULL DEFAULT 'strategy_signal',
    created_event_time TEXT,
    eligible_from_event_time TEXT,
    expires_at_event_time TEXT,
    closed_event_time TEXT,
    reject_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_orders_run ON lab_orders(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_orders_status ON lab_orders(run_id, status);

CREATE TABLE IF NOT EXISTS lab_order_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    event_time TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    remaining_quantity TEXT NOT NULL DEFAULT '0',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_order_events_order ON lab_order_events(order_id, event_time);

CREATE TABLE IF NOT EXISTS lab_fills (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT NOT NULL DEFAULT '0',
    fee_currency TEXT NOT NULL DEFAULT 'USD',
    liquidity TEXT NOT NULL DEFAULT 'taker',
    intrabar_ambiguous INTEGER NOT NULL DEFAULT 0,
    modelled_slippage_bps TEXT NOT NULL DEFAULT '0',
    observed_execution INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_fills_run ON lab_fills(run_id, event_time);

CREATE TABLE IF NOT EXISTS lab_ledger_entries (
    entry_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_time TEXT NOT NULL,
    account TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount TEXT NOT NULL,
    kind TEXT NOT NULL,
    instrument_id TEXT,
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, source_event_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_lab_ledger_run ON lab_ledger_entries(run_id, event_time);

CREATE TABLE IF NOT EXISTS lab_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    equity TEXT NOT NULL DEFAULT '0',
    cash_json TEXT NOT NULL DEFAULT '{}',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, event_time)
);
CREATE INDEX IF NOT EXISTS idx_lab_snapshots_run ON lab_snapshots(run_id, event_time);

CREATE TABLE IF NOT EXISTS lab_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    strategy_id TEXT,
    action TEXT NOT NULL DEFAULT 'wait',
    signal TEXT NOT NULL DEFAULT 'flat',
    decision_json TEXT NOT NULL DEFAULT '{}',
    deferred_evaluation_at TEXT,
    later_outcome_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_decisions_run ON lab_decisions(run_id, event_time);

CREATE TABLE IF NOT EXISTS lab_evaluations (
    report_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL DEFAULT 1,
    evaluated_by TEXT NOT NULL,
    evaluator_role TEXT NOT NULL DEFAULT 'independent_validator',
    protocol TEXT NOT NULL DEFAULT 'walk_forward_expanding',
    verdict TEXT NOT NULL DEFAULT 'insufficient_evidence',
    evidence_class TEXT NOT NULL DEFAULT 'historical_evaluation',
    splits_json TEXT NOT NULL DEFAULT '[]',
    report_json TEXT NOT NULL DEFAULT '{}',
    consumed_for_promotion INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_evaluations_strategy
    ON lab_evaluations(strategy_id, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_holdout_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL DEFAULT 1,
    split TEXT NOT NULL,
    dataset_hash TEXT NOT NULL DEFAULT '',
    report_id TEXT,
    actor TEXT NOT NULL DEFAULT 'operator',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_holdout_usage_strategy
    ON lab_holdout_usage(strategy_id, split, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    strategy_id TEXT,
    dataset_ids_json TEXT NOT NULL DEFAULT '[]',
    split TEXT NOT NULL DEFAULT 'development',
    feature_spec_json TEXT NOT NULL DEFAULT '{}',
    label_spec_json TEXT NOT NULL DEFAULT '{}',
    preprocessing_json TEXT NOT NULL DEFAULT '{}',
    hyperparams_json TEXT NOT NULL DEFAULT '{}',
    weights_json TEXT NOT NULL DEFAULT '{}',
    training_window_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    baseline_comparison_json TEXT NOT NULL DEFAULT '{}',
    artefact_hash TEXT NOT NULL DEFAULT '',
    trained_by TEXT NOT NULL DEFAULT 'operator',
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);
CREATE INDEX IF NOT EXISTS idx_lab_models_kind ON lab_models(kind, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_agent_tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    assignment TEXT NOT NULL DEFAULT '',
    model_id TEXT,
    model_source TEXT NOT NULL DEFAULT 'shared',
    permissions_json TEXT NOT NULL DEFAULT '{}',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_agent_tasks_session
    ON lab_agent_tasks(session_id, created_at);

CREATE TABLE IF NOT EXISTS lab_agent_sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    strategy_id TEXT,
    experiment_id TEXT,
    max_concurrency INTEGER NOT NULL DEFAULT 2,
    budget_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_agent_sessions_status
    ON lab_agent_sessions(status, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_jobs (
    job_id TEXT PRIMARY KEY,
    job_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 5,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    progress INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    ref_type TEXT NOT NULL DEFAULT '',
    ref_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(job_key)
);
CREATE INDEX IF NOT EXISTS idx_lab_jobs_status ON lab_jobs(status, priority, created_at);

CREATE TABLE IF NOT EXISTS lab_paper_accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'paper',
    base_currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    run_id TEXT,
    strategy_id TEXT,
    cash_json TEXT NOT NULL DEFAULT '{}',
    risk_limits_json TEXT NOT NULL DEFAULT '{}',
    cost_model_json TEXT NOT NULL DEFAULT '{}',
    kill_switch INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    cost_model_json TEXT NOT NULL DEFAULT '{}',
    risk_limits_json TEXT NOT NULL DEFAULT '{}',
    resources_json TEXT NOT NULL DEFAULT '{}',
    providers_json TEXT NOT NULL DEFAULT '{}',
    split_policy_json TEXT NOT NULL DEFAULT '{}',
    agent_models_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""

_LEARNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_experiences (
    experience_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    experiment_id TEXT,
    trial_id TEXT,
    strategy_id TEXT,
    strategy_version INTEGER,
    instrument_id TEXT NOT NULL,
    timeframe TEXT,
    event_time TEXT NOT NULL,
    evaluation_time TEXT,
    mode TEXT,
    split TEXT NOT NULL DEFAULT 'development',
    strategy_family TEXT,
    strategy_params_json TEXT NOT NULL DEFAULT '{}',
    signal TEXT,
    action TEXT,
    confidence TEXT,
    regime_json TEXT NOT NULL DEFAULT '{}',
    regime_key TEXT,
    position_state_json TEXT NOT NULL DEFAULT '{}',
    portfolio_json TEXT NOT NULL DEFAULT '{}',
    entry_price REAL,
    later_price REAL,
    price_change REAL,
    gross_pnl REAL,
    net_pnl REAL,
    fees REAL,
    spread REAL,
    slippage REAL,
    mae REAL,
    mfe REAL,
    drawdown_contribution REAL,
    benchmark_return REAL,
    excess_return REAL,
    holding_horizon INTEGER,
    outcome_class TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    dataset_ids_json TEXT NOT NULL DEFAULT '[]',
    dataset_checksum TEXT NOT NULL DEFAULT '',
    strategy_hash TEXT NOT NULL DEFAULT '',
    engine_version TEXT NOT NULL DEFAULT '',
    unavailable_json TEXT NOT NULL DEFAULT '{}',
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_experiences_strategy
    ON lab_experiences(strategy_id, strategy_version, split, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_experiences_regime
    ON lab_experiences(strategy_family, regime_key, instrument_id, timeframe);
CREATE INDEX IF NOT EXISTS idx_lab_experiences_run
    ON lab_experiences(run_id, event_time);
CREATE INDEX IF NOT EXISTS idx_lab_experiences_split
    ON lab_experiences(split, strategy_family, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_learning_findings (
    finding_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    group_key TEXT NOT NULL,
    group_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    claim TEXT NOT NULL DEFAULT '',
    evidence_status TEXT NOT NULL DEFAULT 'insufficient_evidence',
    sample_count INTEGER NOT NULL DEFAULT 0,
    split TEXT NOT NULL DEFAULT 'development',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_findings_cycle
    ON lab_learning_findings(cycle_id, evidence_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_findings_group
    ON lab_learning_findings(group_key, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_trading_beliefs (
    belief_id TEXT PRIMARY KEY,
    claim TEXT NOT NULL,
    claim_hash TEXT NOT NULL DEFAULT '',
    scope_json TEXT NOT NULL DEFAULT '{}',
    strategy_family TEXT,
    instrument_id TEXT,
    asset_family TEXT,
    timeframe TEXT,
    regime_key TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    supporting_count INTEGER NOT NULL DEFAULT 0,
    contradicting_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    confidence_cap REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed',
    supersedes TEXT,
    superseded_by TEXT,
    source_finding_id TEXT,
    source_cycle_id TEXT,
    evidence_quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_beliefs_scope
    ON lab_trading_beliefs(strategy_family, instrument_id, timeframe, regime_key, status);
CREATE INDEX IF NOT EXISTS idx_lab_beliefs_status
    ON lab_trading_beliefs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_beliefs_hash
    ON lab_trading_beliefs(claim_hash);

CREATE TABLE IF NOT EXISTS lab_belief_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    confidence REAL,
    actor TEXT NOT NULL DEFAULT 'learning_engine',
    reason TEXT NOT NULL DEFAULT '',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_belief_history
    ON lab_belief_history(belief_id, created_at DESC);

CREATE TABLE IF NOT EXISTS lab_strategy_lineage (
    lineage_id TEXT PRIMARY KEY,
    parent_strategy_id TEXT NOT NULL,
    parent_version INTEGER NOT NULL,
    child_strategy_id TEXT NOT NULL,
    child_version INTEGER NOT NULL,
    mutation_kind TEXT NOT NULL,
    mutation_reason TEXT NOT NULL DEFAULT '',
    changed_fields_json TEXT NOT NULL DEFAULT '[]',
    belief_refs_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL DEFAULT 'evolution_engine',
    generation INTEGER NOT NULL DEFAULT 1,
    fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_lineage_parent
    ON lab_strategy_lineage(parent_strategy_id, parent_version);
CREATE INDEX IF NOT EXISTS idx_lab_lineage_child
    ON lab_strategy_lineage(child_strategy_id, child_version);
CREATE INDEX IF NOT EXISTS idx_lab_lineage_fingerprint
    ON lab_strategy_lineage(fingerprint);

CREATE TABLE IF NOT EXISTS lab_strategy_candidates (
    candidate_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL,
    parent_strategy_id TEXT,
    parent_version INTEGER,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    mutation_kind TEXT NOT NULL DEFAULT 'parameter_adjustment',
    mutation_reason TEXT NOT NULL DEFAULT '',
    changed_fields_json TEXT NOT NULL DEFAULT '[]',
    belief_refs_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    experiment_id TEXT,
    evaluation_id TEXT,
    rejection_reason TEXT NOT NULL DEFAULT '',
    reuse_of TEXT,
    created_by TEXT NOT NULL DEFAULT 'evolution_engine',
    generation INTEGER NOT NULL DEFAULT 1,
    spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_candidates_fingerprint
    ON lab_strategy_candidates(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_lab_candidates_cycle
    ON lab_strategy_candidates(cycle_id, status);

CREATE TABLE IF NOT EXISTS lab_champion_records (
    champion_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    admission_json TEXT NOT NULL DEFAULT '{}',
    comparison_json TEXT NOT NULL DEFAULT '{}',
    replaced_champion_id TEXT,
    replaced_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_champions_scope
    ON lab_champion_records(scope_key, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS lab_learning_cycles (
    cycle_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    objective TEXT NOT NULL DEFAULT '',
    autonomy_level TEXT NOT NULL DEFAULT 'off',
    parent_strategy_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
    generated_candidates_json TEXT NOT NULL DEFAULT '[]',
    experiment_ids_json TEXT NOT NULL DEFAULT '[]',
    evaluation_ids_json TEXT NOT NULL DEFAULT '[]',
    accepted_findings_json TEXT NOT NULL DEFAULT '[]',
    rejected_findings_json TEXT NOT NULL DEFAULT '[]',
    champion_changes_json TEXT NOT NULL DEFAULT '[]',
    report_json TEXT NOT NULL DEFAULT '{}',
    budget_json TEXT NOT NULL DEFAULT '{}',
    budget_used_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    token_usage_json TEXT NOT NULL DEFAULT '{}',
    failure_reason TEXT,
    job_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lab_cycles_status
    ON lab_learning_cycles(status, created_at DESC);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_encode)


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "as_json"):
        return value.as_json()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"not_json_serialisable:{type(value)!r}")


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


class TradingLabStore:
    """Repository for every durable Trading Lab record except bulk bars."""

    def __init__(self, db: PlatformDatabase) -> None:
        self.db = db

    # --- migration ---------------------------------------------------------------

    def initialize(self) -> None:
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
            conn.executescript(_SCHEMA)
            conn.executescript(_LEARNING_SCHEMA)
            self._ensure_column(conn, "lab_snapshots", "checkpoint_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "lab_settings", "learning_json", "TEXT NOT NULL DEFAULT '{}'")
            conn.execute(
                "INSERT OR IGNORE INTO lab_schema_migrations(version, applied_at) VALUES(?, ?)",
                (LAB_SCHEMA_VERSION, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (SHARED_MIGRATION_VERSION, now),
            )
            conn.execute(
                """INSERT OR IGNORE INTO lab_settings(
                       id, cost_model_json, risk_limits_json, resources_json,
                       providers_json, split_policy_json, agent_models_json, updated_at)
                   VALUES(1, '{}', '{}', '{}', '{}', '{}', '{}', ?)""",
                (now,),
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    # --- instruments -------------------------------------------------------------

    def list_instruments(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT spec_json FROM lab_instruments ORDER BY instrument_id").fetchall()
        return [_loads(row["spec_json"], {}) for row in rows]

    def upsert_instrument(self, spec: Any) -> None:
        payload = spec.as_json() if hasattr(spec, "as_json") else dict(spec)
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_instruments(instrument_id, family, venue, symbol, spec_json, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                       family=excluded.family, venue=excluded.venue, symbol=excluded.symbol,
                       spec_json=excluded.spec_json, updated_at=excluded.updated_at""",
                (
                    payload["instrument_id"],
                    payload["family"],
                    payload["venue"],
                    payload["symbol"],
                    _dumps(payload),
                    now,
                    now,
                ),
            )

    def delete_instrument(self, instrument_id: str) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM lab_instruments WHERE instrument_id=?", (instrument_id,))
        return cursor.rowcount > 0

    # --- datasets ----------------------------------------------------------------

    def upsert_dataset(self, manifest: Any) -> dict[str, Any]:
        payload = manifest.as_json() if hasattr(manifest, "as_json") else dict(manifest)
        now = utc_now()
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT frozen FROM lab_datasets WHERE dataset_id=?", (payload["dataset_id"],)
            ).fetchone()
            if existing and int(existing["frozen"]):
                raise RuntimeError(f"dataset_frozen:{payload['dataset_id']}")
            conn.execute(
                """INSERT INTO lab_datasets(
                       dataset_id, name, instrument_id, timeframe, data_level, provider, provider_kind,
                       is_synthetic, revision, row_count, first_event_time, last_event_time,
                       content_checksum, frozen, manifest_json, quality_json, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(dataset_id) DO UPDATE SET
                       name=excluded.name, data_level=excluded.data_level, provider=excluded.provider,
                       provider_kind=excluded.provider_kind, is_synthetic=excluded.is_synthetic,
                       revision=excluded.revision, row_count=excluded.row_count,
                       first_event_time=excluded.first_event_time, last_event_time=excluded.last_event_time,
                       content_checksum=excluded.content_checksum, manifest_json=excluded.manifest_json,
                       quality_json=excluded.quality_json, updated_at=excluded.updated_at""",
                (
                    payload["dataset_id"],
                    payload.get("name", payload["dataset_id"]),
                    payload["instrument_id"],
                    payload["timeframe"],
                    payload.get("data_level", "ohlcv"),
                    payload.get("provider", "import"),
                    payload.get("provider_kind", "import"),
                    int(bool(payload.get("is_synthetic"))),
                    int(payload.get("revision", 1)),
                    int(payload.get("row_count", 0)),
                    payload.get("first_event_time"),
                    payload.get("last_event_time"),
                    payload.get("content_checksum", ""),
                    int(bool(payload.get("frozen"))),
                    _dumps(payload),
                    _dumps(payload.get("quality") or {}),
                    payload.get("created_at") or now,
                    now,
                ),
            )
        return self.get_dataset(payload["dataset_id"]) or payload

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        return self._dataset_row(row) if row else None

    def list_datasets(
        self,
        *,
        instrument_id: str | None = None,
        timeframe: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if instrument_id:
            clauses.append("instrument_id=?")
            params.append(instrument_id)
        if timeframe:
            clauses.append("timeframe=?")
            params.append(timeframe)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_datasets {where} ORDER BY updated_at DESC LIMIT ?", params
            ).fetchall()
        return [self._dataset_row(row) for row in rows]

    def freeze_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            manifest_row = conn.execute(
                "SELECT manifest_json FROM lab_datasets WHERE dataset_id=?", (dataset_id,)
            ).fetchone()
            if not manifest_row:
                return None
            manifest = _loads(manifest_row["manifest_json"], {})
            manifest["frozen"] = True
            conn.execute(
                "UPDATE lab_datasets SET frozen=1, manifest_json=?, updated_at=? WHERE dataset_id=?",
                (_dumps(manifest), utc_now(), dataset_id),
            )
        return self.get_dataset(dataset_id)

    @staticmethod
    def _dataset_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        manifest = _loads(item.pop("manifest_json", None), {})
        item["quality"] = _loads(item.pop("quality_json", None), {})
        item["is_synthetic"] = bool(item.get("is_synthetic"))
        item["frozen"] = bool(item.get("frozen"))
        item["manifest"] = manifest
        item["partitions"] = manifest.get("partitions", [])
        item["licence"] = manifest.get("licence", "unspecified")
        item["availability_delay_seconds"] = manifest.get("availability_delay_seconds", 0)
        item["calendar"] = manifest.get("calendar", "24x7")
        item["source_reference"] = manifest.get("source_reference", "")
        return item

    def add_dataset_events(self, dataset_id: str, instrument_id: str, events: Iterable[dict[str, Any]]) -> int:
        now = utc_now()
        written = 0
        with self.db.connection() as conn:
            for event in events:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO lab_dataset_events(
                           id, dataset_id, instrument_id, kind, event_time, available_at, payload_json, created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        new_id("labev"),
                        dataset_id,
                        instrument_id,
                        event.get("kind", "corporate_action"),
                        event["event_time"],
                        event.get("available_at") or event["event_time"],
                        _dumps(event.get("payload") or {}),
                        now,
                    ),
                )
                written += cursor.rowcount if cursor.rowcount > 0 else 0
        return written

    def dataset_events(
        self,
        dataset_id: str,
        *,
        kind: str | None = None,
        available_until: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["dataset_id=?"]
        params: list[Any] = [dataset_id]
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if available_until:
            clauses.append("available_at<=?")
            params.append(available_until)
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_dataset_events WHERE {' AND '.join(clauses)} ORDER BY available_at",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json", None), {})
            result.append(item)
        return result

    # --- strategies --------------------------------------------------------------

    def create_strategy(
        self,
        *,
        name: str,
        family: str,
        hypothesis: Any,
        created_by: str,
        scope_note: str = "",
        status: str = "concept",
    ) -> str:
        strategy_id = new_id("lstr")
        now = utc_now()
        payload = hypothesis.as_json() if hasattr(hypothesis, "as_json") else dict(hypothesis or {})
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_strategies(
                       strategy_id, name, family, status, current_version, hypothesis_json,
                       owner, created_by, scope_note, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (strategy_id, name, family, status, 0, _dumps(payload), created_by, created_by, scope_note, now, now),
            )
            conn.execute(
                """INSERT INTO lab_strategy_status_history(
                       strategy_id, from_status, to_status, actor, actor_role, reason, created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (strategy_id, "", status, created_by, "operator", "created", now),
            )
        return strategy_id

    def add_strategy_version(self, strategy_id: str, spec: Any, *, created_by: str) -> int:
        payload = spec.as_json() if hasattr(spec, "as_json") else dict(spec)
        spec_hash = spec.content_hash() if hasattr(spec, "content_hash") else ""
        now = utc_now()
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS latest FROM lab_strategy_versions WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            version = int(row["latest"]) + 1
            payload["version"] = version
            payload["strategy_id"] = strategy_id
            conn.execute(
                """INSERT INTO lab_strategy_versions(
                       id, strategy_id, version, spec_json, spec_hash, code_reference, code_hash, created_by, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    new_id("lsv"),
                    strategy_id,
                    version,
                    _dumps(payload),
                    spec_hash,
                    payload.get("code_reference", ""),
                    payload.get("code_hash", ""),
                    created_by,
                    now,
                ),
            )
            conn.execute(
                "UPDATE lab_strategies SET current_version=?, updated_at=? WHERE strategy_id=?",
                (version, now, strategy_id),
            )
        return version

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            if not row:
                return None
            versions = conn.execute(
                "SELECT version, spec_json, spec_hash, created_by, created_at FROM lab_strategy_versions "
                "WHERE strategy_id=? ORDER BY version DESC",
                (strategy_id,),
            ).fetchall()
            history = conn.execute(
                "SELECT * FROM lab_strategy_status_history WHERE strategy_id=? ORDER BY created_at DESC LIMIT 50",
                (strategy_id,),
            ).fetchall()
        item = dict(row)
        item["hypothesis"] = _loads(item.pop("hypothesis_json", None), {})
        item["versions"] = [
            {
                "version": entry["version"],
                "spec": _loads(entry["spec_json"], {}),
                "spec_hash": entry["spec_hash"],
                "created_by": entry["created_by"],
                "created_at": entry["created_at"],
            }
            for entry in versions
        ]
        item["status_history"] = [dict(entry) for entry in history]
        return item

    def get_strategy_version(self, strategy_id: str, version: int | None = None) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            if version is None:
                row = conn.execute(
                    "SELECT * FROM lab_strategy_versions WHERE strategy_id=? ORDER BY version DESC LIMIT 1",
                    (strategy_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM lab_strategy_versions WHERE strategy_id=? AND version=?",
                    (strategy_id, int(version)),
                ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["spec"] = _loads(item.pop("spec_json", None), {})
        return item

    def list_strategies(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_strategies {where} ORDER BY updated_at DESC LIMIT ?", params
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["hypothesis"] = _loads(item.pop("hypothesis_json", None), {})
            result.append(item)
        return result

    def set_strategy_status(
        self,
        strategy_id: str,
        status: str,
        *,
        actor: str,
        actor_role: str = "operator",
        report_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.db.connection() as conn:
            row = conn.execute("SELECT status FROM lab_strategies WHERE strategy_id=?", (strategy_id,)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE lab_strategies SET status=?, rejection_reason=?, updated_at=? WHERE strategy_id=?",
                (status, reason if status == "rejected" else "", now, strategy_id),
            )
            conn.execute(
                """INSERT INTO lab_strategy_status_history(
                       strategy_id, from_status, to_status, actor, actor_role, report_id, reason, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (strategy_id, row["status"], status, actor, actor_role, report_id, reason, now),
            )
        return self.get_strategy(strategy_id)

    def update_strategy_fields(self, strategy_id: str, **fields: Any) -> None:
        allowed = {"name", "scope_note", "knowledge_source_id", "owner"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE lab_strategies SET {assignments} WHERE strategy_id=?",
                (*updates.values(), strategy_id),
            )

    # --- experiments and trials --------------------------------------------------

    def create_experiment(
        self,
        spec: Any,
        *,
        dataset_hash: str = "",
        code_hash: str = "",
        base_commit: str = "",
        strategy_id: str | None = None,
        preregistration: dict[str, Any] | None = None,
    ) -> str:
        payload = spec.as_json() if hasattr(spec, "as_json") else dict(spec)
        experiment_id = payload.get("experiment_id") or new_id("lexp")
        payload["experiment_id"] = experiment_id
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_experiments(
                       experiment_id, title, strategy_family, strategy_id, split, status, progress,
                       search_method, search_budget, seed, spec_json, dataset_hash, code_hash,
                       base_commit, requested_by, preregistration_json, created_at, updated_at)
                   VALUES(?,?,?,?,?,'queued',0,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    experiment_id,
                    payload.get("title", experiment_id),
                    payload["strategy_family"],
                    strategy_id,
                    payload.get("split", "development"),
                    payload.get("search_method", "single"),
                    int(payload.get("search_budget", 1)),
                    int(payload.get("seed", 7)),
                    _dumps(payload),
                    dataset_hash,
                    code_hash,
                    base_commit,
                    payload.get("requested_by", "operator"),
                    _dumps(preregistration or {}),
                    now,
                    now,
                ),
            )
        return experiment_id

    def update_experiment(self, experiment_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "progress",
            "trials_completed",
            "trials_failed",
            "best_trial_id",
            "error",
            "started_at",
            "finished_at",
            "strategy_id",
            "job_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "result" in fields:
            updates["result_json"] = _dumps(fields["result"] or {})
        if updates:
            updates["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in updates)
            with self.db.connection() as conn:
                conn.execute(
                    f"UPDATE lab_experiments SET {assignments} WHERE experiment_id=?",
                    (*updates.values(), experiment_id),
                )
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["spec"] = _loads(item.pop("spec_json", None), {})
        item["preregistration"] = _loads(item.pop("preregistration_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), {})
        return item

    def list_experiments(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_experiments {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["spec"] = _loads(item.pop("spec_json", None), {})
            item["preregistration"] = _loads(item.pop("preregistration_json", None), {})
            item["result"] = _loads(item.pop("result_json", None), {})
            result.append(item)
        return result

    def record_trial(
        self,
        experiment_id: str,
        *,
        trial_index: int,
        params: dict[str, Any],
        status: str,
        metrics: dict[str, Any] | None = None,
        run_id: str | None = None,
        split: str = "development",
        dataset_hash: str = "",
        code_hash: str = "",
        error: str | None = None,
    ) -> str:
        trial_id = new_id("ltri")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_trials(
                       trial_id, experiment_id, trial_index, status, params_json, metrics_json,
                       run_id, split, dataset_hash, code_hash, error, created_at, finished_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(experiment_id, trial_index) DO UPDATE SET
                       status=excluded.status, params_json=excluded.params_json,
                       metrics_json=excluded.metrics_json, run_id=excluded.run_id,
                       error=excluded.error, finished_at=excluded.finished_at""",
                (
                    trial_id,
                    experiment_id,
                    int(trial_index),
                    status,
                    _dumps(params),
                    _dumps(metrics or {}),
                    run_id,
                    split,
                    dataset_hash,
                    code_hash,
                    error,
                    now,
                    now if status in {"completed", "failed"} else None,
                ),
            )
            row = conn.execute(
                "SELECT trial_id FROM lab_trials WHERE experiment_id=? AND trial_index=?",
                (experiment_id, int(trial_index)),
            ).fetchone()
        return row["trial_id"] if row else trial_id

    def list_trials(self, experiment_id: str, *, limit: int = 2000) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_trials WHERE experiment_id=? ORDER BY trial_index LIMIT ?",
                (experiment_id, max(1, min(int(limit), 5000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["params"] = _loads(item.pop("params_json", None), {})
            item["metrics"] = _loads(item.pop("metrics_json", None), {})
            result.append(item)
        return result

    def count_trials(self, *, strategy_family: str | None = None, strategy_id: str | None = None) -> int:
        """Total recorded search attempts. Feeds the multiple-testing correction."""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_family:
            clauses.append("e.strategy_family=?")
            params.append(strategy_family)
        if strategy_id:
            clauses.append("e.strategy_id=?")
            params.append(strategy_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connection() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) AS total FROM lab_trials t
                    JOIN lab_experiments e ON e.experiment_id = t.experiment_id {where}""",
                params,
            ).fetchone()
        return int(row["total"] if row else 0)

    # --- runs --------------------------------------------------------------------

    def create_run(self, payload: dict[str, Any]) -> str:
        run_id = payload.get("run_id") or new_id("lrun")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_runs(
                       run_id, mode, label, status, progress, experiment_id, trial_id, strategy_id,
                       strategy_version, strategy_hash, split, dataset_ids_json, dataset_hash,
                       config_json, cost_model_json, risk_limits_json, seeds_json, model_versions_json,
                       base_commit, engine_version, branch_of_run_id, branch_from_event_time,
                       created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    payload.get("mode", "historical_simulation"),
                    payload.get("label", ""),
                    payload.get("status", "created"),
                    int(payload.get("progress", 0)),
                    payload.get("experiment_id"),
                    payload.get("trial_id"),
                    payload.get("strategy_id"),
                    payload.get("strategy_version"),
                    payload.get("strategy_hash", ""),
                    payload.get("split", "development"),
                    _dumps(payload.get("dataset_ids") or []),
                    payload.get("dataset_hash", ""),
                    _dumps(payload.get("config") or {}),
                    _dumps(payload.get("cost_model") or {}),
                    _dumps(payload.get("risk_limits") or {}),
                    _dumps(payload.get("seeds") or {}),
                    _dumps(payload.get("model_versions") or {}),
                    payload.get("base_commit", ""),
                    payload.get("engine_version", ""),
                    payload.get("branch_of_run_id"),
                    payload.get("branch_from_event_time"),
                    now,
                    now,
                ),
            )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        json_fields = {"result": "result_json", "checkpoint": "checkpoint_json", "model_versions": "model_versions_json"}
        allowed = {
            "status",
            "progress",
            "simulation_time",
            "first_event_time",
            "last_event_time",
            "events_processed",
            "error",
            "started_at",
            "finished_at",
            "strategy_id",
            "strategy_version",
            "label",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key in allowed:
                updates[key] = value
            elif key in json_fields:
                updates[json_fields[key]] = _dumps(value or {})
        if updates:
            updates["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in updates)
            with self.db.connection() as conn:
                conn.execute(
                    f"UPDATE lab_runs SET {assignments} WHERE run_id=?", (*updates.values(), run_id)
                )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def list_runs(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        strategy_id: str | None = None,
        experiment_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("mode", mode),
            ("strategy_id", strategy_id),
            ("experiment_id", experiment_id),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_runs {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._run_row(row) for row in rows]

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["dataset_ids"] = _loads(item.pop("dataset_ids_json", None), [])
        item["config"] = _loads(item.pop("config_json", None), {})
        item["cost_model"] = _loads(item.pop("cost_model_json", None), {})
        item["risk_limits"] = _loads(item.pop("risk_limits_json", None), {})
        item["seeds"] = _loads(item.pop("seeds_json", None), {})
        item["model_versions"] = _loads(item.pop("model_versions_json", None), {})
        item["checkpoint"] = _loads(item.pop("checkpoint_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), {})
        return item

    def append_run_event(
        self,
        run_id: str,
        message: str,
        *,
        level: str = "info",
        category: str = "engine",
        simulation_time: str | None = None,
        payload: dict[str, Any] | None = None,
        event_key: str | None = None,
    ) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO lab_run_events(
                       run_id, event_key, level, category, simulation_time, message, payload_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (run_id, event_key, level, category, simulation_time, message, _dumps(payload or {}), utc_now()),
            )

    def list_run_events(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_run_events WHERE run_id=? ORDER BY id DESC LIMIT ?",
                (run_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json", None), {})
            result.append(item)
        return result

    # --- orders, fills, ledger ---------------------------------------------------

    def persist_order(self, run_id: str, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_orders(
                       order_id, run_id, instrument_id, strategy_id, side, order_type, time_in_force,
                       status, quantity, filled_quantity, average_fill_price, limit_price, stop_price,
                       reduce_only, post_only, parent_order_id, oco_group, intent_json,
                       risk_decision_json, price_source, created_event_time, eligible_from_event_time,
                       expires_at_event_time, closed_event_time, reject_reason, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(order_id) DO UPDATE SET
                       status=excluded.status, filled_quantity=excluded.filled_quantity,
                       average_fill_price=excluded.average_fill_price, limit_price=excluded.limit_price,
                       stop_price=excluded.stop_price, closed_event_time=excluded.closed_event_time,
                       reject_reason=excluded.reject_reason, updated_at=excluded.updated_at""",
                (
                    record["order_id"],
                    run_id,
                    record["instrument_id"],
                    record.get("strategy_id"),
                    record["side"],
                    record["order_type"],
                    record.get("time_in_force", "GTC"),
                    record.get("status", "accepted"),
                    str(record.get("quantity", "0")),
                    str(record.get("filled_quantity", "0")),
                    None if record.get("average_fill_price") is None else str(record["average_fill_price"]),
                    None if record.get("limit_price") is None else str(record["limit_price"]),
                    None if record.get("stop_price") is None else str(record["stop_price"]),
                    int(bool(record.get("reduce_only"))),
                    int(bool(record.get("post_only"))),
                    record.get("parent_order_id"),
                    record.get("oco_group"),
                    _dumps(record.get("intent") or {}),
                    _dumps(record.get("risk_decision") or {}),
                    record.get("price_source", "strategy_signal"),
                    record.get("created_event_time"),
                    record.get("eligible_from_event_time"),
                    record.get("expires_at_event_time"),
                    record.get("closed_event_time"),
                    record.get("reject_reason", ""),
                    now,
                    now,
                ),
            )

    def list_orders(self, run_id: str, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses = ["run_id=?"]
        params: list[Any] = [run_id]
        if status:
            clauses.append("status=?")
            params.append(status)
        params.append(max(1, min(int(limit), 2000)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_orders WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["intent"] = _loads(item.pop("intent_json", None), {})
            item["risk_decision"] = _loads(item.pop("risk_decision_json", None), {})
            item["reduce_only"] = bool(item.get("reduce_only"))
            item["post_only"] = bool(item.get("post_only"))
            result.append(item)
        return result

    def append_order_event(self, run_id: str, event: Any) -> bool:
        """Append-only. Returns False when the event_id was already stored (idempotent replay)."""
        payload = event.as_json() if hasattr(event, "as_json") else dict(event)
        with self.db.connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO lab_order_events(
                       event_id, run_id, order_id, instrument_id, kind, event_time,
                       reason, remaining_quantity, payload_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["event_id"],
                    run_id,
                    payload["order_id"],
                    payload["instrument_id"],
                    payload["kind"],
                    payload["event_time"],
                    payload.get("reason", ""),
                    str(payload.get("remaining_quantity", "0")),
                    _dumps(payload),
                    utc_now(),
                ),
            )
        return cursor.rowcount > 0

    def append_fill(self, run_id: str, fill: Any) -> bool:
        payload = fill.as_json() if hasattr(fill, "as_json") else dict(fill)
        with self.db.connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO lab_fills(
                       event_id, run_id, order_id, instrument_id, event_time, side, quantity, price,
                       fee, fee_currency, liquidity, intrabar_ambiguous, modelled_slippage_bps,
                       observed_execution, payload_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["event_id"],
                    run_id,
                    payload["order_id"],
                    payload["instrument_id"],
                    payload["event_time"],
                    payload["side"],
                    str(payload["quantity"]),
                    str(payload["price"]),
                    str(payload.get("fee", "0")),
                    payload.get("fee_currency", "USD"),
                    payload.get("liquidity", "taker"),
                    int(bool(payload.get("intrabar_ambiguous"))),
                    str(payload.get("modelled_slippage_bps", "0")),
                    int(bool(payload.get("observed_execution"))),
                    _dumps(payload),
                    utc_now(),
                ),
            )
        return cursor.rowcount > 0

    def list_fills(self, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_fills WHERE run_id=? ORDER BY event_time DESC, rowid DESC LIMIT ?",
                (run_id, max(1, min(int(limit), 5000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json", None), {})
            item["intrabar_ambiguous"] = bool(item.get("intrabar_ambiguous"))
            item["observed_execution"] = bool(item.get("observed_execution"))
            result.append(item)
        return result

    def append_ledger_entries(self, run_id: str, entries: Sequence[dict[str, Any]]) -> int:
        """Append-only ledger writes. The (source_event_id, sequence) uniqueness is the
        idempotency guarantee: a replayed or retried fill cannot be booked twice."""
        written = 0
        now = utc_now()
        with self.db.connection() as conn:
            for entry in entries:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO lab_ledger_entries(
                           entry_id, run_id, source_event_id, sequence, event_time, account,
                           currency, amount, kind, instrument_id, memo, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id("lled"),
                        run_id,
                        entry["source_event_id"],
                        int(entry["sequence"]),
                        entry["event_time"],
                        entry["account"],
                        entry["currency"],
                        str(entry["amount"]),
                        entry["kind"],
                        entry.get("instrument_id"),
                        entry.get("memo", ""),
                        now,
                    ),
                )
                written += 1 if cursor.rowcount > 0 else 0
        return written

    def list_ledger_entries(self, run_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_ledger_entries WHERE run_id=? ORDER BY event_time, sequence LIMIT ?",
                (run_id, max(1, min(int(limit), 20000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def ledger_totals(self, run_id: str) -> dict[str, dict[str, str]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT account, currency, amount FROM lab_ledger_entries WHERE run_id=?""",
                (run_id,),
            ).fetchall()
        totals: dict[str, dict[str, Decimal]] = {}
        for row in rows:
            bucket = totals.setdefault(row["account"], {})
            bucket[row["currency"]] = bucket.get(row["currency"], Decimal("0")) + Decimal(row["amount"])
        return {
            account: {currency: str(amount) for currency, amount in sorted(balances.items())}
            for account, balances in sorted(totals.items())
        }

    def save_snapshot(self, run_id: str, snapshot: Any, *, engine_checkpoint: dict[str, Any] | None = None) -> None:
        payload = snapshot.as_json() if hasattr(snapshot, "as_json") else dict(snapshot)
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO lab_snapshots(
                       snapshot_id, run_id, event_time, equity, cash_json, snapshot_json, checkpoint_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    new_id("lsnap"),
                    run_id,
                    payload["as_of"],
                    str(payload.get("equity", "0")),
                    _dumps(payload.get("cash") or {}),
                    _dumps(payload),
                    _dumps(engine_checkpoint or {}),
                    utc_now(),
                ),
            )

    def save_engine_checkpoint(self, run_id: str, event_time: str, checkpoint: dict[str, Any]) -> None:
        """Attach an engine checkpoint to the snapshot at this time, creating a stub if needed."""
        blob = _dumps(checkpoint)
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT snapshot_id FROM lab_snapshots WHERE run_id=? AND event_time=?",
                (run_id, event_time),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE lab_snapshots SET checkpoint_json=? WHERE run_id=? AND event_time=?",
                    (blob, run_id, event_time),
                )
            else:
                conn.execute(
                    """INSERT INTO lab_snapshots(
                           snapshot_id, run_id, event_time, equity, cash_json, snapshot_json, checkpoint_json, created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (new_id("lsnap"), run_id, event_time, "0", "{}", "{}", blob, utc_now()),
                )
        self.update_run(run_id, checkpoint=checkpoint)

    def list_snapshots(self, run_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT event_time, equity, snapshot_json, checkpoint_json FROM lab_snapshots WHERE run_id=? "
                "ORDER BY event_time LIMIT ?",
                (run_id, max(1, min(int(limit), 20000))),
            ).fetchall()
        result = []
        for row in rows:
            checkpoint = _loads(row["checkpoint_json"] if "checkpoint_json" in row.keys() else None, {})
            result.append(
                {
                    "event_time": row["event_time"],
                    "equity": row["equity"],
                    "snapshot": _loads(row["snapshot_json"], {}),
                    "has_engine_checkpoint": bool(checkpoint),
                }
            )
        return result

    def engine_checkpoints(self, run_id: str) -> list[tuple[str, dict[str, Any]]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT event_time, checkpoint_json FROM lab_snapshots WHERE run_id=? ORDER BY event_time",
                (run_id,),
            ).fetchall()
        out: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            payload = _loads(row["checkpoint_json"] if "checkpoint_json" in row.keys() else None, {})
            if payload:
                out.append((row["event_time"], payload))
        return out

    def latest_snapshot(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT event_time, equity, snapshot_json FROM lab_snapshots WHERE run_id=? "
                "ORDER BY event_time DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {"event_time": row["event_time"], "equity": row["equity"], "snapshot": _loads(row["snapshot_json"], {})}

    def delete_after(self, run_id: str, event_time: str) -> dict[str, int]:
        """Used by rewind: a new branch never inherits post-rewind state."""
        with self.db.connection() as conn:
            snapshots = conn.execute(
                "DELETE FROM lab_snapshots WHERE run_id=? AND event_time>?", (run_id, event_time)
            ).rowcount
            fills = conn.execute(
                "DELETE FROM lab_fills WHERE run_id=? AND event_time>?", (run_id, event_time)
            ).rowcount
            order_events = conn.execute(
                "DELETE FROM lab_order_events WHERE run_id=? AND event_time>?", (run_id, event_time)
            ).rowcount
            ledger = conn.execute(
                "DELETE FROM lab_ledger_entries WHERE run_id=? AND event_time>?", (run_id, event_time)
            ).rowcount
            decisions = conn.execute(
                "DELETE FROM lab_decisions WHERE run_id=? AND event_time>?", (run_id, event_time)
            ).rowcount
        return {
            "snapshots": max(0, snapshots),
            "fills": max(0, fills),
            "order_events": max(0, order_events),
            "ledger_entries": max(0, ledger),
            "decisions": max(0, decisions),
        }

    # --- decisions ---------------------------------------------------------------

    def save_decision(self, record: Any) -> None:
        payload = record.as_json() if hasattr(record, "as_json") else dict(record)
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO lab_decisions(
                       decision_id, run_id, event_time, instrument_id, strategy_id, action, signal,
                       decision_json, deferred_evaluation_at, later_outcome_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["decision_id"],
                    payload["run_id"],
                    payload["event_time"],
                    payload["instrument_id"],
                    payload.get("strategy_id"),
                    payload.get("action", "wait"),
                    payload.get("signal", "flat"),
                    _dumps(payload),
                    payload.get("deferred_evaluation_at"),
                    _dumps(payload.get("later_outcome")) if payload.get("later_outcome") else None,
                    utc_now(),
                ),
            )

    def list_decisions(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_decisions WHERE run_id=? ORDER BY event_time DESC LIMIT ?",
                (run_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["decision"] = _loads(item.pop("decision_json", None), {})
            item["later_outcome"] = _loads(item.pop("later_outcome_json", None), None)
            result.append(item)
        return result

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["decision"] = _loads(item.pop("decision_json", None), {})
        item["later_outcome"] = _loads(item.pop("later_outcome_json", None), None)
        return item

    def list_resolved_decisions_without_experience(
        self,
        *,
        run_id: str | None = None,
        experiment_id: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        clauses = ["d.later_outcome_json IS NOT NULL", "e.experience_id IS NULL"]
        params: list[Any] = []
        if run_id:
            clauses.append("d.run_id=?")
            params.append(run_id)
        if experiment_id:
            clauses.append("(d.run_id LIKE ? OR d.run_id=?)")
            params.extend([f"{experiment_id}%", experiment_id])
        params.append(max(1, min(int(limit), 50_000)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"""SELECT d.* FROM lab_decisions d
                    LEFT JOIN lab_experiences e ON e.decision_id = d.decision_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY d.event_time
                    LIMIT ?""",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["decision"] = _loads(item.pop("decision_json", None), {})
            item["later_outcome"] = _loads(item.pop("later_outcome_json", None), None)
            result.append(item)
        return result

    def attach_decision_outcome(self, decision_id: str, outcome: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE lab_decisions SET later_outcome_json=? WHERE decision_id=?",
                (_dumps(outcome), decision_id),
            )

    # --- evaluations and holdout audit -------------------------------------------

    def save_evaluation(self, report: Any) -> str:
        payload = report.as_json() if hasattr(report, "as_json") else dict(report)
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO lab_evaluations(
                       report_id, strategy_id, strategy_version, evaluated_by, evaluator_role,
                       protocol, verdict, evidence_class, splits_json, report_json,
                       consumed_for_promotion, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,
                          COALESCE((SELECT consumed_for_promotion FROM lab_evaluations WHERE report_id=?), 0), ?)""",
                (
                    payload["report_id"],
                    payload["strategy_id"],
                    int(payload.get("strategy_version", 1)),
                    payload.get("evaluated_by", "unknown"),
                    payload.get("evaluator_role", "independent_validator"),
                    payload.get("protocol", "walk_forward_expanding"),
                    payload.get("verdict", "insufficient_evidence"),
                    payload.get("evidence_class", "historical_evaluation"),
                    _dumps(payload.get("splits_used") or []),
                    _dumps(payload),
                    payload["report_id"],
                    payload.get("created_at") or utc_now(),
                ),
            )
        return payload["report_id"]

    def get_evaluation(self, report_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_evaluations WHERE report_id=?", (report_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["report"] = _loads(item.pop("report_json", None), {})
        item["splits_used"] = _loads(item.pop("splits_json", None), [])
        item["consumed_for_promotion"] = bool(item.get("consumed_for_promotion"))
        return item

    def list_evaluations(self, *, strategy_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id:
            clauses.append("strategy_id=?")
            params.append(strategy_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_evaluations {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["report"] = _loads(item.pop("report_json", None), {})
            item["splits_used"] = _loads(item.pop("splits_json", None), [])
            item["consumed_for_promotion"] = bool(item.get("consumed_for_promotion"))
            result.append(item)
        return result

    def mark_evaluation_consumed(self, report_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE lab_evaluations SET consumed_for_promotion=1 WHERE report_id=?", (report_id,)
            )

    def record_holdout_usage(
        self,
        *,
        strategy_id: str,
        split: str,
        strategy_version: int = 1,
        dataset_hash: str = "",
        report_id: str | None = None,
        actor: str = "operator",
        reason: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_holdout_usage(
                       strategy_id, strategy_version, split, dataset_hash, report_id, actor, reason, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (strategy_id, int(strategy_version), split, dataset_hash, report_id, actor, reason, now),
            )
        return {
            "strategy_id": strategy_id,
            "strategy_version": int(strategy_version),
            "split": split,
            "report_id": report_id,
            "actor": actor,
            "used_at": now,
        }

    def holdout_usage(self, strategy_id: str, split: str | None = None) -> list[dict[str, Any]]:
        clauses = ["strategy_id=?"]
        params: list[Any] = [strategy_id]
        if split:
            clauses.append("split=?")
            params.append(split)
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_holdout_usage WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    # --- models ------------------------------------------------------------------

    def save_model(self, payload: dict[str, Any]) -> str:
        model_id = payload.get("model_id") or new_id("lmdl")
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS latest FROM lab_models WHERE name=?",
                (payload["name"],),
            ).fetchone()
            version = int(payload.get("version") or 0) or int(row["latest"]) + 1
            conn.execute(
                """INSERT INTO lab_models(
                       model_id, name, kind, version, strategy_id, dataset_ids_json, split,
                       feature_spec_json, label_spec_json, preprocessing_json, hyperparams_json,
                       weights_json, training_window_json, metrics_json, baseline_comparison_json,
                       artefact_hash, trained_by, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    model_id,
                    payload["name"],
                    payload["kind"],
                    version,
                    payload.get("strategy_id"),
                    _dumps(payload.get("dataset_ids") or []),
                    payload.get("split", "development"),
                    _dumps(payload.get("feature_spec") or {}),
                    _dumps(payload.get("label_spec") or {}),
                    _dumps(payload.get("preprocessing") or {}),
                    _dumps(payload.get("hyperparams") or {}),
                    _dumps(payload.get("weights") or {}),
                    _dumps(payload.get("training_window") or {}),
                    _dumps(payload.get("metrics") or {}),
                    _dumps(payload.get("baseline_comparison") or {}),
                    payload.get("artefact_hash", ""),
                    payload.get("trained_by", "operator"),
                    utc_now(),
                ),
            )
        return model_id

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_models WHERE model_id=?", (model_id,)).fetchone()
        return self._model_row(row) if row else None

    def list_models(self, *, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_models {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._model_row(row) for row in rows]

    @staticmethod
    def _model_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["dataset_ids"] = _loads(item.pop("dataset_ids_json", None), [])
        item["feature_spec"] = _loads(item.pop("feature_spec_json", None), {})
        item["label_spec"] = _loads(item.pop("label_spec_json", None), {})
        item["preprocessing"] = _loads(item.pop("preprocessing_json", None), {})
        item["hyperparams"] = _loads(item.pop("hyperparams_json", None), {})
        item["weights"] = _loads(item.pop("weights_json", None), {})
        item["training_window"] = _loads(item.pop("training_window_json", None), {})
        item["metrics"] = _loads(item.pop("metrics_json", None), {})
        item["baseline_comparison"] = _loads(item.pop("baseline_comparison_json", None), {})
        return item

    # --- agent sessions and tasks -------------------------------------------------

    def create_agent_session(self, payload: dict[str, Any]) -> str:
        session_id = payload.get("session_id") or new_id("lsess")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_agent_sessions(
                       session_id, title, objective, status, progress, strategy_id, experiment_id,
                       max_concurrency, budget_json, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    payload.get("title", ""),
                    payload.get("objective", ""),
                    payload.get("status", "queued"),
                    0,
                    payload.get("strategy_id"),
                    payload.get("experiment_id"),
                    int(payload.get("max_concurrency", 2)),
                    _dumps(payload.get("budget") or {}),
                    now,
                    now,
                ),
            )
        return session_id

    def update_agent_session(self, session_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "progress", "error", "finished_at", "strategy_id", "experiment_id"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "result" in fields:
            updates["result_json"] = _dumps(fields["result"] or {})
        if updates:
            updates["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in updates)
            with self.db.connection() as conn:
                conn.execute(
                    f"UPDATE lab_agent_sessions SET {assignments} WHERE session_id=?",
                    (*updates.values(), session_id),
                )
        return self.get_agent_session(session_id)

    def get_agent_session(self, session_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_agent_sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                return None
            tasks = conn.execute(
                "SELECT * FROM lab_agent_tasks WHERE session_id=? ORDER BY created_at", (session_id,)
            ).fetchall()
        item = dict(row)
        item["budget"] = _loads(item.pop("budget_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), {})
        item["tasks"] = [self._agent_task_row(entry) for entry in tasks]
        return item

    def list_agent_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_agent_sessions ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["budget"] = _loads(item.pop("budget_json", None), {})
            item["result"] = _loads(item.pop("result_json", None), {})
            result.append(item)
        return result

    def create_agent_task(self, payload: dict[str, Any]) -> str:
        task_id = payload.get("task_id") or new_id("ltask")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_agent_tasks(
                       task_id, session_id, role, status, progress, assignment, model_id, model_source,
                       permissions_json, input_json, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    payload["session_id"],
                    payload["role"],
                    payload.get("status", "queued"),
                    0,
                    payload.get("assignment", ""),
                    payload.get("model_id"),
                    payload.get("model_source", "shared"),
                    _dumps(payload.get("permissions") or {}),
                    _dumps(payload.get("input") or {}),
                    now,
                    now,
                ),
            )
        return task_id

    def update_agent_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "progress", "error", "started_at", "finished_at", "model_id", "model_source"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        for key, column in (("output", "output_json"), ("checkpoint", "checkpoint_json")):
            if key in fields:
                updates[column] = _dumps(fields[key] or {})
        if updates:
            updates["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in updates)
            with self.db.connection() as conn:
                conn.execute(
                    f"UPDATE lab_agent_tasks SET {assignments} WHERE task_id=?",
                    (*updates.values(), task_id),
                )
        return self.get_agent_task(task_id)

    def get_agent_task(self, task_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._agent_task_row(row) if row else None

    @staticmethod
    def _agent_task_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["permissions"] = _loads(item.pop("permissions_json", None), {})
        item["input"] = _loads(item.pop("input_json", None), {})
        item["output"] = _loads(item.pop("output_json", None), {})
        item["checkpoint"] = _loads(item.pop("checkpoint_json", None), {})
        return item

    # --- jobs --------------------------------------------------------------------

    def enqueue_job(
        self,
        *,
        job_key: str,
        kind: str,
        payload: dict[str, Any],
        priority: int = 5,
        max_attempts: int = 3,
        ref_type: str = "",
        ref_id: str = "",
    ) -> dict[str, Any]:
        """Idempotent enqueue: the same ``job_key`` never produces a second job."""
        now = utc_now()
        job_id = new_id("ljob")
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO lab_jobs(
                       job_id, job_key, kind, status, priority, max_attempts, payload_json,
                       ref_type, ref_id, created_at, updated_at)
                   VALUES(?,?,?,'queued',?,?,?,?,?,?,?)""",
                (job_id, job_key, kind, int(priority), int(max_attempts), _dumps(payload), ref_type, ref_id, now, now),
            )
            row = conn.execute("SELECT * FROM lab_jobs WHERE job_key=?", (job_key,)).fetchone()
        return self._job_row(row)

    def claim_job(self, job_id: str) -> dict[str, Any] | None:
        """Atomically move a queued job to running. Returns None when already claimed."""
        now = utc_now()
        with self.db.connection() as conn:
            cursor = conn.execute(
                """UPDATE lab_jobs SET status='running', attempts=attempts+1, started_at=COALESCE(started_at, ?),
                       updated_at=? WHERE job_id=? AND status IN ('queued','paused','retry')""",
                (now, now, job_id),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM lab_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "progress", "error", "finished_at", "priority"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        for key, column in (("checkpoint", "checkpoint_json"), ("result", "result_json")):
            if key in fields:
                updates[column] = _dumps(fields[key] or {})
        if updates:
            updates["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in updates)
            with self.db.connection() as conn:
                conn.execute(f"UPDATE lab_jobs SET {assignments} WHERE job_id=?", (*updates.values(), job_id))
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_jobs {where} ORDER BY priority, created_at LIMIT ?", params
            ).fetchall()
        return [self._job_row(row) for row in rows]

    def requeue_interrupted_jobs(self) -> int:
        """Called at startup: a job left ``running`` by a crash goes back to the queue.

        Bookings are idempotent, so resuming cannot double-book; the alternative — leaving
        them stuck in ``running`` — would silently lose work.
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                """UPDATE lab_jobs SET status='retry', updated_at=?
                   WHERE status='running' AND attempts < max_attempts""",
                (utc_now(),),
            )
            exhausted = conn.execute(
                """UPDATE lab_jobs SET status='failed', error=COALESCE(error, 'interrupted_and_attempts_exhausted'),
                       updated_at=? WHERE status='running' AND attempts >= max_attempts""",
                (utc_now(),),
            )
        return max(0, cursor.rowcount) + max(0, exhausted.rowcount)

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json", None), {})
        item["checkpoint"] = _loads(item.pop("checkpoint_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), {})
        return item

    # --- settings ----------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_settings WHERE id=1").fetchone()
        if not row:
            return {}
        item = dict(row)
        return {
            "cost_model": _loads(item.get("cost_model_json"), {}),
            "risk_limits": _loads(item.get("risk_limits_json"), {}),
            "resources": _loads(item.get("resources_json"), {}),
            "providers": _loads(item.get("providers_json"), {}),
            "split_policy": _loads(item.get("split_policy_json"), {}),
            "agent_models": _loads(item.get("agent_models_json"), {}),
            "learning": _loads(item.get("learning_json"), {}),
            "updated_at": item.get("updated_at", ""),
        }

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        columns = {
            "cost_model": "cost_model_json",
            "risk_limits": "risk_limits_json",
            "resources": "resources_json",
            "providers": "providers_json",
            "split_policy": "split_policy_json",
            "agent_models": "agent_models_json",
            "learning": "learning_json",
        }
        updates = {column: _dumps(values[key]) for key, column in columns.items() if key in values}
        if not updates:
            return self.settings()
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as conn:
            conn.execute(f"UPDATE lab_settings SET {assignments} WHERE id=1", tuple(updates.values()))
        return self.settings()

    # --- paper accounts ----------------------------------------------------------

    def upsert_paper_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = payload.get("account_id") or new_id("lacct")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_paper_accounts(
                       account_id, name, mode, base_currency, status, version, run_id, strategy_id,
                       cash_json, risk_limits_json, cost_model_json, kill_switch, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET
                       name=excluded.name, status=excluded.status, version=excluded.version,
                       run_id=excluded.run_id, strategy_id=excluded.strategy_id,
                       cash_json=excluded.cash_json, risk_limits_json=excluded.risk_limits_json,
                       cost_model_json=excluded.cost_model_json, kill_switch=excluded.kill_switch,
                       updated_at=excluded.updated_at""",
                (
                    account_id,
                    payload.get("name", "Paper account"),
                    payload.get("mode", "paper"),
                    payload.get("base_currency", "USD"),
                    payload.get("status", "active"),
                    int(payload.get("version", 1)),
                    payload.get("run_id"),
                    payload.get("strategy_id"),
                    _dumps(payload.get("cash") or {}),
                    _dumps(payload.get("risk_limits") or {}),
                    _dumps(payload.get("cost_model") or {}),
                    int(bool(payload.get("kill_switch"))),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM lab_paper_accounts WHERE account_id=?", (account_id,)).fetchone()
        item = dict(row)
        item["cash"] = _loads(item.pop("cash_json", None), {})
        item["risk_limits"] = _loads(item.pop("risk_limits_json", None), {})
        item["cost_model"] = _loads(item.pop("cost_model_json", None), {})
        item["kill_switch"] = bool(item.get("kill_switch"))
        return item

    def list_paper_accounts(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM lab_paper_accounts ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["cash"] = _loads(item.pop("cash_json", None), {})
            item["risk_limits"] = _loads(item.pop("risk_limits_json", None), {})
            item["cost_model"] = _loads(item.pop("cost_model_json", None), {})
            item["kill_switch"] = bool(item.get("kill_switch"))
            result.append(item)
        return result

    # --- experiences / learning --------------------------------------------------

    def save_experience(self, payload: dict[str, Any]) -> bool:
        now = utc_now()
        with self.db.connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO lab_experiences(
                       experience_id, decision_id, run_id, experiment_id, trial_id, strategy_id,
                       strategy_version, instrument_id, timeframe, event_time, evaluation_time,
                       mode, split, strategy_family, strategy_params_json, signal, action, confidence,
                       regime_json, regime_key, position_state_json, portfolio_json, entry_price,
                       later_price, price_change, gross_pnl, net_pnl, fees, spread, slippage, mae, mfe,
                       drawdown_contribution, benchmark_return, excess_return, holding_horizon,
                       outcome_class, evidence_refs_json, dataset_ids_json, dataset_checksum,
                       strategy_hash, engine_version, unavailable_json, is_synthetic, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["experience_id"],
                    payload["decision_id"],
                    payload.get("run_id") or "",
                    payload.get("experiment_id"),
                    payload.get("trial_id"),
                    payload.get("strategy_id"),
                    payload.get("strategy_version"),
                    payload.get("instrument_id") or "",
                    payload.get("timeframe"),
                    payload.get("event_time") or now,
                    payload.get("evaluation_time"),
                    payload.get("mode"),
                    payload.get("split") or "development",
                    payload.get("strategy_family"),
                    _dumps(payload.get("strategy_params") or {}),
                    payload.get("signal"),
                    payload.get("action"),
                    payload.get("confidence"),
                    _dumps(payload.get("regime") or {}),
                    payload.get("regime_key"),
                    _dumps(payload.get("position_state") or {}),
                    _dumps(payload.get("portfolio") or {}),
                    payload.get("entry_price"),
                    payload.get("later_price"),
                    payload.get("price_change"),
                    payload.get("gross_pnl"),
                    payload.get("net_pnl"),
                    payload.get("fees"),
                    payload.get("spread"),
                    payload.get("slippage"),
                    payload.get("mae"),
                    payload.get("mfe"),
                    payload.get("drawdown_contribution"),
                    payload.get("benchmark_return"),
                    payload.get("excess_return"),
                    payload.get("holding_horizon"),
                    payload.get("outcome_class"),
                    _dumps(payload.get("evidence_refs") or []),
                    _dumps(payload.get("dataset_ids") or []),
                    payload.get("dataset_checksum") or "",
                    payload.get("strategy_hash") or "",
                    payload.get("engine_version") or "",
                    _dumps(payload.get("unavailable") or {}),
                    int(bool(payload.get("is_synthetic"))),
                    now,
                ),
            )
        return cursor.rowcount > 0

    def get_experience(self, experience_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_experiences WHERE experience_id=?", (experience_id,)).fetchone()
        return self._experience_row(row) if row else None

    def list_experiences(
        self,
        *,
        strategy_id: str | None = None,
        strategy_family: str | None = None,
        instrument_id: str | None = None,
        timeframe: str | None = None,
        regime_key: str | None = None,
        split: str | None = None,
        strategy_version: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id:
            clauses.append("strategy_id=?")
            params.append(strategy_id)
        if strategy_family:
            clauses.append("strategy_family=?")
            params.append(strategy_family)
        if instrument_id:
            clauses.append("instrument_id=?")
            params.append(instrument_id)
        if timeframe:
            clauses.append("timeframe=?")
            params.append(timeframe)
        if regime_key:
            clauses.append("regime_key=?")
            params.append(regime_key)
        if split:
            clauses.append("split=?")
            params.append(split)
        if strategy_version is not None:
            clauses.append("strategy_version=?")
            params.append(int(strategy_version))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query_params = list(params) + [max(1, min(int(limit), 20_000)), max(0, int(offset))]
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_experiences {where} ORDER BY event_time DESC LIMIT ? OFFSET ?",
                query_params,
            ).fetchall()
        return [self._experience_row(row) for row in rows]

    def count_experiences(self, **filters: Any) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("strategy_id", "strategy_family", "instrument_id", "timeframe", "regime_key", "split"):
            if filters.get(key):
                clauses.append(f"{key}=?")
                params.append(filters[key])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM lab_experiences {where}", params).fetchone()
        return int(row["total"] if row else 0)

    def learning_overview_counts(self) -> dict[str, int]:
        with self.db.connection() as conn:
            experiences = conn.execute("SELECT COUNT(*) AS total FROM lab_experiences").fetchone()["total"]
            findings = conn.execute("SELECT COUNT(*) AS total FROM lab_learning_findings").fetchone()["total"]
            beliefs = conn.execute(
                "SELECT status, COUNT(*) AS total FROM lab_trading_beliefs GROUP BY status"
            ).fetchall()
            cycles = conn.execute(
                "SELECT COUNT(*) AS total FROM lab_learning_cycles WHERE status NOT IN ('completed','cancelled','failed')"
            ).fetchone()["total"]
        counts = {row["status"]: int(row["total"]) for row in beliefs}
        return {
            "experiences": int(experiences or 0),
            "findings": int(findings or 0),
            "beliefs": sum(counts.values()),
            "beliefs_supported": counts.get("supported", 0) + counts.get("confirmed", 0),
            "beliefs_confirmed": counts.get("confirmed", 0),
            "beliefs_weakened": counts.get("weakened", 0),
            "beliefs_contradicted": counts.get("contradicted", 0),
            "beliefs_retired": counts.get("retired", 0),
            "active_cycles": int(cycles or 0),
        }

    @staticmethod
    def _experience_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["strategy_params"] = _loads(item.pop("strategy_params_json", None), {})
        item["regime"] = _loads(item.pop("regime_json", None), {})
        item["position_state"] = _loads(item.pop("position_state_json", None), {})
        item["portfolio"] = _loads(item.pop("portfolio_json", None), {})
        item["evidence_refs"] = _loads(item.pop("evidence_refs_json", None), [])
        item["dataset_ids"] = _loads(item.pop("dataset_ids_json", None), [])
        item["unavailable"] = _loads(item.pop("unavailable_json", None), {})
        item["is_synthetic"] = bool(item.get("is_synthetic"))
        return item

    def save_learning_finding(self, payload: dict[str, Any]) -> str:
        finding_id = payload.get("finding_id") or new_id("lfind")
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO lab_learning_findings(
                       finding_id, cycle_id, group_key, group_json, metrics_json, claim,
                       evidence_status, sample_count, split, evidence_refs_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    finding_id,
                    payload.get("cycle_id"),
                    payload.get("group_key") or finding_id,
                    _dumps(payload.get("group") or {}),
                    _dumps(payload.get("metrics") or {}),
                    payload.get("claim") or "",
                    payload.get("evidence_status") or "insufficient_evidence",
                    int(payload.get("sample_count") or 0),
                    payload.get("split") or "development",
                    _dumps(payload.get("evidence_refs") or []),
                    utc_now(),
                ),
            )
        return finding_id

    def list_learning_findings(self, *, cycle_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if cycle_id:
            clauses.append("cycle_id=?")
            params.append(cycle_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_learning_findings {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["group"] = _loads(item.pop("group_json", None), {})
            item["metrics"] = _loads(item.pop("metrics_json", None), {})
            item["evidence_refs"] = _loads(item.pop("evidence_refs_json", None), [])
            result.append(item)
        return result

    def upsert_trading_belief(self, payload: dict[str, Any]) -> dict[str, Any]:
        from trading_lab.contracts import stable_hash

        now = utc_now()
        claim = str(payload.get("claim") or "")
        claim_hash = payload.get("claim_hash") or stable_hash(
            {
                "family": payload.get("strategy_family"),
                "instrument": payload.get("instrument_id"),
                "timeframe": payload.get("timeframe"),
                "regime": payload.get("regime_key"),
                "claim": claim,
            }
        )
        refs = list(payload.get("evidence_refs") or [])
        if not refs and not payload.get("open_question"):
            raise ValueError("belief_requires_evidence_refs")
        with self.db.connection() as conn:
            existing = conn.execute(
                """SELECT * FROM lab_trading_beliefs
                   WHERE claim_hash=? OR (
                       IFNULL(strategy_family,'')=? AND IFNULL(instrument_id,'')=?
                       AND IFNULL(timeframe,'')=? AND IFNULL(regime_key,'')=?
                   )
                   ORDER BY updated_at DESC LIMIT 1""",
                (
                    claim_hash,
                    payload.get("strategy_family") or "",
                    payload.get("instrument_id") or "",
                    payload.get("timeframe") or "",
                    payload.get("regime_key") or "",
                ),
            ).fetchone()
            if existing:
                belief_id = existing["belief_id"]
                previous_refs = _loads(existing["evidence_refs_json"], [])
                merged = list(dict.fromkeys([*previous_refs, *refs]))
                from_status = existing["status"]
                to_status = payload.get("status") or existing["status"]
                conn.execute(
                    """UPDATE lab_trading_beliefs SET
                           claim=?, claim_hash=?, scope_json=?, strategy_family=?, instrument_id=?,
                           asset_family=?, timeframe=?, regime_key=?, evidence_refs_json=?,
                           supporting_count=?, contradicting_count=?, confidence=?, confidence_cap=?,
                           status=?, source_finding_id=COALESCE(?, source_finding_id),
                           source_cycle_id=COALESCE(?, source_cycle_id),
                           evidence_quality_json=?, updated_at=?
                       WHERE belief_id=?""",
                    (
                        claim or existing["claim"],
                        claim_hash,
                        _dumps(payload.get("scope") or _loads(existing["scope_json"], {})),
                        payload.get("strategy_family") or existing["strategy_family"],
                        payload.get("instrument_id") or existing["instrument_id"],
                        payload.get("asset_family") or existing["asset_family"],
                        payload.get("timeframe") or existing["timeframe"],
                        payload.get("regime_key") or existing["regime_key"],
                        _dumps(merged),
                        int(payload.get("supporting_count", existing["supporting_count"]) or 0),
                        int(payload.get("contradicting_count", existing["contradicting_count"]) or 0),
                        float(payload.get("confidence", existing["confidence"]) or 0),
                        float(payload.get("confidence_cap", existing["confidence_cap"]) or 0),
                        to_status,
                        payload.get("source_finding_id"),
                        payload.get("source_cycle_id"),
                        _dumps(payload.get("evidence_quality") or _loads(existing["evidence_quality_json"], {})),
                        now,
                        belief_id,
                    ),
                )
                conn.execute(
                    """INSERT INTO lab_belief_history(
                           belief_id, from_status, to_status, confidence, actor, reason, evidence_refs_json, created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        belief_id,
                        from_status,
                        to_status,
                        float(payload.get("confidence", existing["confidence"]) or 0),
                        payload.get("actor") or "learning_engine",
                        payload.get("reason") or "evidence update",
                        _dumps(refs),
                        now,
                    ),
                )
            else:
                belief_id = payload.get("belief_id") or new_id("lblf")
                conn.execute(
                    """INSERT INTO lab_trading_beliefs(
                           belief_id, claim, claim_hash, scope_json, strategy_family, instrument_id,
                           asset_family, timeframe, regime_key, evidence_refs_json, supporting_count,
                           contradicting_count, confidence, confidence_cap, status, supersedes,
                           source_finding_id, source_cycle_id, evidence_quality_json, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        belief_id,
                        claim,
                        claim_hash,
                        _dumps(payload.get("scope") or {}),
                        payload.get("strategy_family"),
                        payload.get("instrument_id"),
                        payload.get("asset_family"),
                        payload.get("timeframe"),
                        payload.get("regime_key"),
                        _dumps(refs),
                        int(payload.get("supporting_count") or 0),
                        int(payload.get("contradicting_count") or 0),
                        float(payload.get("confidence") or 0),
                        float(payload.get("confidence_cap") or 0),
                        payload.get("status") or "proposed",
                        payload.get("supersedes"),
                        payload.get("source_finding_id"),
                        payload.get("source_cycle_id"),
                        _dumps(payload.get("evidence_quality") or {}),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """INSERT INTO lab_belief_history(
                           belief_id, from_status, to_status, confidence, actor, reason, evidence_refs_json, created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        belief_id,
                        "",
                        payload.get("status") or "proposed",
                        float(payload.get("confidence") or 0),
                        payload.get("actor") or "learning_engine",
                        "created",
                        _dumps(refs),
                        now,
                    ),
                )
        return self.get_trading_belief(belief_id) or {"belief_id": belief_id}

    def get_trading_belief(self, belief_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_trading_beliefs WHERE belief_id=?", (belief_id,)).fetchone()
            history = conn.execute(
                "SELECT * FROM lab_belief_history WHERE belief_id=? ORDER BY created_at DESC LIMIT 40",
                (belief_id,),
            ).fetchall()
        if not row:
            return None
        item = self._belief_row(row)
        item["history"] = [dict(entry) for entry in history]
        for entry in item["history"]:
            entry["evidence_refs"] = _loads(entry.pop("evidence_refs_json", None), [])
        return item

    def list_trading_beliefs(
        self,
        *,
        status: str | None = None,
        strategy_family: str | None = None,
        instrument_id: str | None = None,
        timeframe: str | None = None,
        regime_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if strategy_family:
            clauses.append("strategy_family=?")
            params.append(strategy_family)
        if instrument_id:
            clauses.append("instrument_id=?")
            params.append(instrument_id)
        if timeframe:
            clauses.append("timeframe=?")
            params.append(timeframe)
        if regime_key:
            clauses.append("regime_key=?")
            params.append(regime_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_trading_beliefs {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._belief_row(row) for row in rows]

    def update_trading_belief_status(
        self,
        belief_id: str,
        *,
        status: str,
        actor: str = "learning_engine",
        reason: str = "",
        evidence_refs: list[str] | None = None,
        superseded_by: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_trading_belief(belief_id)
        if current is None:
            return None
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """UPDATE lab_trading_beliefs SET status=?, superseded_by=COALESCE(?, superseded_by), updated_at=?
                   WHERE belief_id=?""",
                (status, superseded_by, now, belief_id),
            )
            conn.execute(
                """INSERT INTO lab_belief_history(
                       belief_id, from_status, to_status, confidence, actor, reason, evidence_refs_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    belief_id,
                    current.get("status"),
                    status,
                    current.get("confidence") or 0,
                    actor,
                    reason,
                    _dumps(evidence_refs or []),
                    now,
                ),
            )
        if superseded_by:
            with self.db.connection() as conn:
                conn.execute(
                    "UPDATE lab_trading_beliefs SET supersedes=?, updated_at=? WHERE belief_id=?",
                    (belief_id, now, superseded_by),
                )
        if current.get("supersedes"):
            with self.db.connection() as conn:
                conn.execute(
                    "UPDATE lab_trading_beliefs SET superseded_by=?, status='superseded', updated_at=? WHERE belief_id=?",
                    (belief_id, now, current["supersedes"]),
                )
        return self.get_trading_belief(belief_id)

    @staticmethod
    def _belief_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["scope"] = _loads(item.pop("scope_json", None), {})
        item["evidence_refs"] = _loads(item.pop("evidence_refs_json", None), [])
        item["evidence_quality"] = _loads(item.pop("evidence_quality_json", None), {})
        return item

    def save_strategy_lineage(self, payload: dict[str, Any]) -> str:
        lineage_id = payload.get("lineage_id") or new_id("llin")
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_strategy_lineage(
                       lineage_id, parent_strategy_id, parent_version, child_strategy_id, child_version,
                       mutation_kind, mutation_reason, changed_fields_json, belief_refs_json,
                       evidence_refs_json, created_by, generation, fingerprint, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lineage_id,
                    payload["parent_strategy_id"],
                    int(payload.get("parent_version") or 1),
                    payload["child_strategy_id"],
                    int(payload.get("child_version") or 1),
                    payload.get("mutation_kind") or "parameter_adjustment",
                    payload.get("mutation_reason") or "",
                    _dumps(payload.get("changed_fields") or []),
                    _dumps(payload.get("belief_refs") or []),
                    _dumps(payload.get("evidence_refs") or []),
                    payload.get("created_by") or "evolution_engine",
                    int(payload.get("generation") or 1),
                    payload.get("fingerprint") or "",
                    utc_now(),
                ),
            )
        return lineage_id

    def list_strategy_lineage(
        self,
        *,
        strategy_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id:
            clauses.append("(parent_strategy_id=? OR child_strategy_id=?)")
            params.extend([strategy_id, strategy_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 2000)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_strategy_lineage {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["changed_fields"] = _loads(item.pop("changed_fields_json", None), [])
            item["belief_refs"] = _loads(item.pop("belief_refs_json", None), [])
            item["evidence_refs"] = _loads(item.pop("evidence_refs_json", None), [])
            result.append(item)
        return result

    def save_strategy_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_id = payload.get("candidate_id") or new_id("lcand")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_strategy_candidates(
                       candidate_id, cycle_id, strategy_id, strategy_version, parent_strategy_id,
                       parent_version, fingerprint, status, mutation_kind, mutation_reason,
                       changed_fields_json, belief_refs_json, evidence_refs_json, experiment_id,
                       evaluation_id, rejection_reason, reuse_of, created_by, generation, spec_json,
                       created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_id,
                    payload.get("cycle_id"),
                    payload["strategy_id"],
                    int(payload.get("strategy_version") or 1),
                    payload.get("parent_strategy_id"),
                    payload.get("parent_version"),
                    payload.get("fingerprint") or "",
                    payload.get("status") or "proposed",
                    payload.get("mutation_kind") or "parameter_adjustment",
                    payload.get("mutation_reason") or "",
                    _dumps(payload.get("changed_fields") or []),
                    _dumps(payload.get("belief_refs") or []),
                    _dumps(payload.get("evidence_refs") or []),
                    payload.get("experiment_id"),
                    payload.get("evaluation_id"),
                    payload.get("rejection_reason") or "",
                    payload.get("reuse_of"),
                    payload.get("created_by") or "evolution_engine",
                    int(payload.get("generation") or 1),
                    _dumps(payload.get("spec") or {}),
                    now,
                    now,
                ),
            )
        return self.get_strategy_candidate(candidate_id) or {"candidate_id": candidate_id}

    def get_strategy_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_strategy_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        return self._candidate_row(row) if row else None

    def update_strategy_candidate(self, candidate_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "experiment_id",
            "evaluation_id",
            "rejection_reason",
            "reuse_of",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_strategy_candidate(candidate_id)
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE lab_strategy_candidates SET {assignments} WHERE candidate_id=?",
                (*updates.values(), candidate_id),
            )
        return self.get_strategy_candidate(candidate_id)

    def list_strategy_candidates(
        self,
        *,
        cycle_id: str | None = None,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if cycle_id:
            clauses.append("cycle_id=?")
            params.append(cycle_id)
        if strategy_id:
            clauses.append("strategy_id=?")
            params.append(strategy_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_strategy_candidates {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._candidate_row(row) for row in rows]

    def list_candidate_fingerprints(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            with self.db.connection() as conn:
                rows = conn.execute(
                    "SELECT fingerprint, status, candidate_id, experiment_id FROM lab_strategy_candidates WHERE status=?",
                    (status,),
                ).fetchall()
        else:
            with self.db.connection() as conn:
                rows = conn.execute(
                    "SELECT fingerprint, status, candidate_id, experiment_id FROM lab_strategy_candidates"
                ).fetchall()
        return [dict(row) for row in rows]

    def find_candidate_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT * FROM lab_strategy_candidates WHERE fingerprint=?
                   ORDER BY CASE status WHEN 'tested' THEN 0 WHEN 'validated' THEN 0 ELSE 1 END, created_at
                   LIMIT 1""",
                (fingerprint,),
            ).fetchone()
        return self._candidate_row(row) if row else None

    @staticmethod
    def _candidate_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["changed_fields"] = _loads(item.pop("changed_fields_json", None), [])
        item["belief_refs"] = _loads(item.pop("belief_refs_json", None), [])
        item["evidence_refs"] = _loads(item.pop("evidence_refs_json", None), [])
        item["spec"] = _loads(item.pop("spec_json", None), {})
        return item

    def install_champion(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        champion_id = payload.get("champion_id") or new_id("lchamp")
        scope_key = payload["scope_key"]
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE lab_champion_records SET status='replaced', updated_at=? WHERE scope_key=? AND status='active'",
                (now, scope_key),
            )
            conn.execute(
                """INSERT INTO lab_champion_records(
                       champion_id, scope_key, scope_json, strategy_id, strategy_version, status,
                       admission_json, comparison_json, replaced_champion_id, replaced_reason,
                       created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    champion_id,
                    scope_key,
                    _dumps(payload.get("scope") or {}),
                    payload["strategy_id"],
                    int(payload.get("strategy_version") or 1),
                    "active",
                    _dumps(payload.get("admission") or {}),
                    _dumps(payload.get("comparison") or payload.get("admission") or {}),
                    payload.get("replaced_champion_id"),
                    payload.get("replaced_reason") or "",
                    now,
                    now,
                ),
            )
        return self.get_champion(champion_id) or {"champion_id": champion_id}

    def get_champion(self, champion_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_champion_records WHERE champion_id=?", (champion_id,)).fetchone()
        return self._champion_row(row) if row else None

    def get_active_champion(self, scope_key: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM lab_champion_records WHERE scope_key=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
                (scope_key,),
            ).fetchone()
        return self._champion_row(row) if row else None

    def list_champions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lab_champion_records ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._champion_row(row) for row in rows]

    @staticmethod
    def _champion_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["scope"] = _loads(item.pop("scope_json", None), {})
        item["admission"] = _loads(item.pop("admission_json", None), {})
        item["comparison"] = _loads(item.pop("comparison_json", None), {})
        return item

    def create_learning_cycle(self, payload: dict[str, Any]) -> dict[str, Any]:
        cycle_id = payload.get("cycle_id") or new_id("lcyc")
        now = utc_now()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO lab_learning_cycles(
                       cycle_id, status, stage, objective, autonomy_level, parent_strategy_ids_json,
                       evidence_snapshot_json, generated_candidates_json, experiment_ids_json,
                       evaluation_ids_json, accepted_findings_json, rejected_findings_json,
                       champion_changes_json, report_json, budget_json, budget_used_json,
                       checkpoint_json, token_usage_json, failure_reason, job_id, started_at,
                       created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cycle_id,
                    payload.get("status") or "queued",
                    payload.get("stage") or "queued",
                    payload.get("objective") or "",
                    payload.get("autonomy_level") or "off",
                    _dumps(payload.get("parent_strategy_ids") or []),
                    _dumps(payload.get("evidence_snapshot") or {}),
                    _dumps(payload.get("generated_candidates") or []),
                    _dumps(payload.get("experiment_ids") or []),
                    _dumps(payload.get("evaluation_ids") or []),
                    _dumps(payload.get("accepted_findings") or []),
                    _dumps(payload.get("rejected_findings") or []),
                    _dumps(payload.get("champion_changes") or []),
                    _dumps(payload.get("report") or {}),
                    _dumps(payload.get("budget") or {}),
                    _dumps(payload.get("budget_used") or {}),
                    _dumps(payload.get("checkpoint") or {}),
                    _dumps(payload.get("token_usage") or {}),
                    payload.get("failure_reason"),
                    payload.get("job_id"),
                    payload.get("started_at"),
                    now,
                    now,
                ),
            )
        return self.get_learning_cycle(cycle_id) or {"cycle_id": cycle_id}

    def get_learning_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lab_learning_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
        return self._cycle_row(row) if row else None

    def list_learning_cycles(self, *, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 200)))
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM lab_learning_cycles {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._cycle_row(row) for row in rows]

    def update_learning_cycle(self, cycle_id: str, **fields: Any) -> dict[str, Any] | None:
        json_fields = {
            "parent_strategy_ids": "parent_strategy_ids_json",
            "evidence_snapshot": "evidence_snapshot_json",
            "generated_candidates": "generated_candidates_json",
            "experiment_ids": "experiment_ids_json",
            "evaluation_ids": "evaluation_ids_json",
            "accepted_findings": "accepted_findings_json",
            "rejected_findings": "rejected_findings_json",
            "champion_changes": "champion_changes_json",
            "report": "report_json",
            "budget": "budget_json",
            "budget_used": "budget_used_json",
            "checkpoint": "checkpoint_json",
            "token_usage": "token_usage_json",
        }
        scalar = {
            "status",
            "stage",
            "objective",
            "autonomy_level",
            "failure_reason",
            "job_id",
            "started_at",
            "finished_at",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key in json_fields:
                updates[json_fields[key]] = _dumps(value if value is not None else {})
            elif key in scalar:
                updates[key] = value
        if not updates:
            return self.get_learning_cycle(cycle_id)
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE lab_learning_cycles SET {assignments} WHERE cycle_id=?",
                (*updates.values(), cycle_id),
            )
        return self.get_learning_cycle(cycle_id)

    def add_open_question(self, cycle_id: str, claim: str, evidence_refs: list[str]) -> None:
        cycle = self.get_learning_cycle(cycle_id)
        if cycle is None:
            return
        report = dict(cycle.get("report") or {})
        questions = list(report.get("open_questions") or [])
        questions.append({"claim": claim, "evidence_refs": evidence_refs})
        report["open_questions"] = questions
        self.update_learning_cycle(cycle_id, report=report)

    def save_cycle_suggestion(self, cycle_id: str, item: dict[str, Any]) -> None:
        cycle = self.get_learning_cycle(cycle_id)
        if cycle is None:
            return
        report = dict(cycle.get("report") or {})
        suggestions = list(report.get("candidate_suggestions") or [])
        suggestions.append(item)
        report["candidate_suggestions"] = suggestions
        self.update_learning_cycle(cycle_id, report=report)

    @staticmethod
    def _cycle_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["parent_strategy_ids"] = _loads(item.pop("parent_strategy_ids_json", None), [])
        item["evidence_snapshot"] = _loads(item.pop("evidence_snapshot_json", None), {})
        item["generated_candidates"] = _loads(item.pop("generated_candidates_json", None), [])
        item["experiment_ids"] = _loads(item.pop("experiment_ids_json", None), [])
        item["evaluation_ids"] = _loads(item.pop("evaluation_ids_json", None), [])
        item["accepted_findings"] = _loads(item.pop("accepted_findings_json", None), [])
        item["rejected_findings"] = _loads(item.pop("rejected_findings_json", None), [])
        item["champion_changes"] = _loads(item.pop("champion_changes_json", None), [])
        item["report"] = _loads(item.pop("report_json", None), {})
        item["budget"] = _loads(item.pop("budget_json", None), {})
        item["budget_used"] = _loads(item.pop("budget_used_json", None), {})
        item["checkpoint"] = _loads(item.pop("checkpoint_json", None), {})
        item["token_usage"] = _loads(item.pop("token_usage_json", None), {})
        return item


__all__ = ["LAB_SCHEMA_VERSION", "SHARED_MIGRATION_VERSION", "TradingLabStore"]
