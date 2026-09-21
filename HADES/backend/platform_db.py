from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from sqlite_runtime import sqlite_connection, wal_owner


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class PlatformDatabase:
    """Extended HADES platform storage sharing the same SQLite file as the core database."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with sqlite_connection(self.path, timeout=15, busy_timeout=8000) as db:
            yield db

    def checkpoint_wal(self, *, truncate: bool = False) -> None:
        if truncate:
            wal_owner.truncate_file(self.path)
        else:
            with sqlite_connection(self.path, timeout=15, busy_timeout=8000) as db:
                wal_owner.checkpoint(db, kind="passive", path=self.path)

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    local_path TEXT,
                    content_hash TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_type, uri)
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    heading TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source ON knowledge_chunks(source_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_type ON knowledge_sources(source_type, updated_at DESC);

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    chunk_id UNINDEXED,
                    source_id UNINDEXED,
                    title,
                    heading,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TABLE IF NOT EXISTS research_projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    depth TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    allow_web INTEGER NOT NULL DEFAULT 0,
                    authorized_downloads INTEGER NOT NULL DEFAULT 0,
                    source_inputs TEXT NOT NULL DEFAULT '[]',
                    findings TEXT NOT NULL DEFAULT '',
                    report TEXT NOT NULL DEFAULT '',
                    metrics TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    max_rounds INTEGER,
                    agent_count INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS research_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_project_sources (
                    project_id TEXT NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
                    relevance REAL NOT NULL DEFAULT 1.0,
                    PRIMARY KEY(project_id, source_id)
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS indexed_files (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    content_hash TEXT,
                    source_id TEXT REFERENCES knowledge_sources(id) ON DELETE SET NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    indexed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plugins (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    local_path TEXT NOT NULL,
                    plugin_type TEXT NOT NULL,
                    runtime_type TEXT NOT NULL,
                    entrypoint TEXT NOT NULL DEFAULT '',
                    manifest TEXT NOT NULL,
                    permissions TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    health TEXT NOT NULL DEFAULT 'unknown',
                    trust TEXT NOT NULL DEFAULT 'local',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plugin_tools (
                    id TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    input_schema TEXT NOT NULL DEFAULT '{}',
                    output_schema TEXT NOT NULL DEFAULT '{}',
                    command TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(plugin_id, name)
                );

                CREATE TABLE IF NOT EXISTS plugin_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_text TEXT,
                    stdout_text TEXT NOT NULL DEFAULT '',
                    stderr_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT,
                    exit_code INTEGER,
                    duration_ms INTEGER,
                    invocation_type TEXT NOT NULL DEFAULT 'manual',
                    approved_by_user INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tool_calls_plugin_started ON tool_calls(plugin_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS brain_external_links (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'gerelateerd aan',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_id, target_id)
                );

                CREATE TABLE IF NOT EXISTS work_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    output TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, step_index)
                );
                CREATE INDEX IF NOT EXISTS idx_work_steps_task ON work_steps(task_id, step_index);

                CREATE TABLE IF NOT EXISTS work_checkpoints (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_work_checkpoints_task ON work_checkpoints(task_id, created_at);

                CREATE TABLE IF NOT EXISTS agent_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reasoning_profile TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    allowed_tools TEXT NOT NULL DEFAULT '[]',
                    max_subtasks INTEGER NOT NULL DEFAULT 4,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_trading_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    kill_switch INTEGER NOT NULL DEFAULT 0,
                    quote_asset TEXT NOT NULL DEFAULT 'USDT',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_wallets (
                    asset TEXT PRIMARY KEY,
                    balance REAL NOT NULL,
                    reserved REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('long')),
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    cost_basis REAL NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open','closed')),
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS paper_orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy','sell')),
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    notional REAL NOT NULL,
                    status TEXT NOT NULL,
                    position_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            now = utc_now()
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)", (now,))
            columns = {row["name"] for row in db.execute("PRAGMA table_info(research_projects)").fetchall()}
            if "authorized_downloads" not in columns:
                db.execute("ALTER TABLE research_projects ADD COLUMN authorized_downloads INTEGER NOT NULL DEFAULT 0")
            tool_columns = {row["name"] for row in db.execute("PRAGMA table_info(plugin_tools)").fetchall()}
            if "metadata" not in tool_columns:
                db.execute("ALTER TABLE plugin_tools ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            call_columns = {row["name"] for row in db.execute("PRAGMA table_info(tool_calls)").fetchall()}
            call_additions = {
                "stdout_text": "TEXT NOT NULL DEFAULT ''",
                "stderr_text": "TEXT NOT NULL DEFAULT ''",
                "exit_code": "INTEGER",
                "duration_ms": "INTEGER",
                "invocation_type": "TEXT NOT NULL DEFAULT 'manual'",
                "approved_by_user": "INTEGER NOT NULL DEFAULT 0",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, declaration in call_additions.items():
                if column not in call_columns:
                    db.execute(f"ALTER TABLE tool_calls ADD COLUMN {column} {declaration}")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(2, ?)", (now,))
            step_columns = {row["name"] for row in db.execute("PRAGMA table_info(work_steps)").fetchall()}
            step_additions = {
                "step_key": "TEXT",
                "depends_on_json": "TEXT NOT NULL DEFAULT '[]'",
                "input_refs_json": "TEXT NOT NULL DEFAULT '[]'",
                "output_schema_json": "TEXT NOT NULL DEFAULT '{}'",
                "plan_version": "INTEGER NOT NULL DEFAULT 1",
            }
            for column, declaration in step_additions.items():
                if column not in step_columns:
                    db.execute(f"ALTER TABLE work_steps ADD COLUMN {column} {declaration}")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(3, ?)", (now,))

            # Agent console: durable model-usage events keyed by specialist/agent.
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_usage_events (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'lm_studio',
                    model_id TEXT,
                    task_id TEXT,
                    conversation_id TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    cached_tokens INTEGER,
                    reasoning_tokens INTEGER,
                    cost REAL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_usage_agent ON agent_usage_events(agent_id, created_at DESC);
                """
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(5, ?)", (now,))

            # Capability suite: artifacts, approvals, inbox, schedules
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    checksum_sha256 TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    parent_artifact_id TEXT,
                    status TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    creator_run_id TEXT,
                    creator_toolcall_id TEXT,
                    conversation_id TEXT,
                    project_id TEXT,
                    task_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_conversation ON artifacts(conversation_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_artifacts_kind_status ON artifacts(kind, status);

                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    policy_outcome TEXT NOT NULL DEFAULT 'approval_required',
                    plugin_id TEXT,
                    tool_name TEXT,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    arguments_hash TEXT NOT NULL DEFAULT '',
                    schema_version TEXT NOT NULL DEFAULT '1',
                    scope_json TEXT NOT NULL DEFAULT '{}',
                    expected_effect TEXT NOT NULL DEFAULT '',
                    destination_paths_json TEXT NOT NULL DEFAULT '[]',
                    run_id TEXT,
                    task_id TEXT,
                    conversation_id TEXT,
                    step_id TEXT,
                    plan_version INTEGER,
                    project_id TEXT,
                    resume_token TEXT,
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    response_payload_json TEXT NOT NULL DEFAULT '{}',
                    expires_at TEXT,
                    decision_at TEXT,
                    decision_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS inbox_items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    ref_type TEXT,
                    ref_id TEXT,
                    project_id TEXT,
                    task_id TEXT,
                    conversation_id TEXT,
                    status TEXT NOT NULL DEFAULT 'unread',
                    dedupe_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_dedupe ON inbox_items(dedupe_key) WHERE dedupe_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox_items(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_schedules (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    run_at TEXT,
                    time_of_day TEXT,
                    weekday INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    paused INTEGER NOT NULL DEFAULT 0,
                    catch_up INTEGER NOT NULL DEFAULT 1,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_due ON task_schedules(enabled, paused, next_run_at);

                CREATE TABLE IF NOT EXISTS task_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    planned_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'claimed',
                    result_summary TEXT NOT NULL DEFAULT '',
                    claimed_at TEXT NOT NULL,
                    finished_at TEXT
                );
                """
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(4, ?)", (now,))
            self._seed_agents(db, now)
            db.execute("INSERT OR IGNORE INTO paper_trading_settings(id,enabled,kill_switch,quote_asset,updated_at) VALUES(1,0,0,'USDT',?)", (now,))
            db.execute("INSERT OR IGNORE INTO paper_wallets(asset,balance,reserved,updated_at) VALUES('USDT',10000.0,0,?)", (now,))

            # Trading bot: local OHLCV, strategy library, discovery/backtest runs, bot settings
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_bars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL DEFAULT '1h',
                    ts TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'synthetic',
                    UNIQUE(symbol, timeframe, ts)
                );
                CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_ts ON market_bars(symbol, timeframe, ts);

                CREATE TABLE IF NOT EXISTS trading_strategies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    params_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    score REAL NOT NULL DEFAULT 0,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '',
                    knowledge_source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trading_strategies_status ON trading_strategies(status, score DESC);

                CREATE TABLE IF NOT EXISTS trading_strategy_runs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL DEFAULT '1h',
                    strategy_id TEXT,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    knowledge_source_id TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trading_runs_status ON trading_strategy_runs(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS trading_bot_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    strategy_id TEXT,
                    symbol TEXT NOT NULL DEFAULT 'BTC/USDT',
                    timeframe TEXT NOT NULL DEFAULT '1h',
                    position_fraction REAL NOT NULL DEFAULT 0.1,
                    last_bar_ts TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO trading_bot_settings(id,enabled,strategy_id,symbol,timeframe,position_fraction,last_bar_ts,updated_at) VALUES(1,0,NULL,'BTC/USDT','1h',0.1,NULL,?)",
                (now,),
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(6, ?)", (now,))

            # Plugin Runtime v2: failure_state + isolation columns (trust reused/normalized in app layer).
            # Version 8: Gen2 store owns migration 7 on the shared schema_migrations table.
            plugin_columns = {row["name"] for row in db.execute("PRAGMA table_info(plugins)").fetchall()}
            plugin_additions = {
                "failure_state": "TEXT",
                "isolation": "TEXT NOT NULL DEFAULT 'plugin_cwd'",
            }
            for column, declaration in plugin_additions.items():
                if column not in plugin_columns:
                    db.execute(f"ALTER TABLE plugins ADD COLUMN {column} {declaration}")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(8, ?)", (now,))

            self._seed_agents(db, now)
            self._promote_implemented_agents(db, now)

            # Per-project research depth controls (rounds + parallel research agents).
            research_columns = {row["name"] for row in db.execute("PRAGMA table_info(research_projects)").fetchall()}
            if "max_rounds" not in research_columns:
                db.execute("ALTER TABLE research_projects ADD COLUMN max_rounds INTEGER")
            if "agent_count" not in research_columns:
                db.execute("ALTER TABLE research_projects ADD COLUMN agent_count INTEGER NOT NULL DEFAULT 1")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(11, ?)", (now,))

            # F-15: index research_events by project_id (queried on every project detail).
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_events_project ON research_events(project_id, id)"
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(18, ?)", (now,))

            # HADES-10 Phase 3A: conversation ↔ run binding for Chat reconnect.
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_runs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    title TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(conversation_id, run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_runs_conv
                    ON conversation_runs(conversation_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversation_runs_run
                    ON conversation_runs(run_id);
                """
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(17, ?)", (now,))

    def _seed_agents(self, db: sqlite3.Connection, now: str) -> None:
        agents = [
            ("chat", "Chat Agent", "chat", "Normale gesprekken en gebruikersgerichte synthese.", "adaptive", 2),
            ("research_planner", "Research Planner", "research", "Splitst onderzoek op in vragen, bronnen en controlepunten.", "high", 6),
            ("research_worker", "Research Worker", "research", "Onderzoekt een begrensd subonderwerp met bronverwijzingen.", "high", 4),
            ("document_intel", "Document Intelligence", "documents", "Structureert, extraheert en indexeert documenten.", "standard", 2),
            ("knowledge_builder", "Knowledge Builder", "knowledge", "Zet gevalideerde informatie om naar duurzame kennis.", "standard", 3),
            ("memory_curator", "Memory Curator", "memory", "Beheert compacte duurzame project- en gespreksmemories.", "standard", 2),
            ("retrieval", "Retrieval Service", "retrieval", "Zoekt relevante Memory, Knowledge en Evidence zonder contextbloat.", "fast", 1),
            ("critic", "Verification / Critic", "verification", "Controleert claims, voltooiing en bewijs onafhankelijk.", "maximum", 3),
            ("build", "Code / Build Agent", "code", "Analyseert codebases, patcht, test en levert proof-of-work.", "maximum", 6),
            ("plugin_converter", "Plugin Conversion Agent", "plugins", "Analyseert externe source en bouwt gecontroleerde adapters.", "high", 4),
            ("workspace", "File / Workspace Agent", "files", "Beheert workspaces binnen bestandstoestemmingen.", "standard", 2),
            ("executor", "Task Planner / Executor", "work", "Voert langlopende meerstaps taken uit met checkpoints.", "maximum", 8),
            ("compressor", "Context Compressor", "context", "Comprimeert oude context met behoud van bronverwijzingen.", "fast", 1),
            ("web_scout", "Web Scout", "web", "Internetverkenner voor actuele bronnen via WebResearchService (network policy).", "high", 4),
            ("evidence_auditor", "Evidence Auditor", "verification", "Bron-auditor voor provenance, conflicten en claimdekking.", "maximum", 4),
            ("tool_orchestrator", "Tool Orchestrator", "plugins", "Specialist voor multi-plugin workflows via PluginManager.", "high", 6),
            ("trading_specialist", "Trading Specialist", "trading", "PAPER-strategieanalyse en marktkennis via PaperTradingService.", "high", 4),
            ("voice_specialist", "Voice Specialist", "voice", "Spraak-, transcriptie- en voice-workflows (lokaal).", "standard", 3),
        ]
        for values in agents:
            db.execute(
                """INSERT OR IGNORE INTO agent_profiles
                   (id,name,role,description,reasoning_profile,enabled,allowed_tools,max_subtasks,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,'[]',?,?,?)""",
                (*values, now, now),
            )

    def _promote_implemented_agents(self, db: sqlite3.Connection, now: str) -> None:
        """Migration 10: former planned agents now have real runtimes + contracts."""
        promotions = {
            "web_scout": (
                "Web Scout",
                "Internetverkenner voor actuele bronnen via WebResearchService (network policy).",
            ),
            "evidence_auditor": (
                "Evidence Auditor",
                "Bron-auditor voor provenance, conflicten en claimdekking.",
            ),
            "tool_orchestrator": (
                "Tool Orchestrator",
                "Specialist voor multi-plugin workflows via PluginManager.",
            ),
            "trading_specialist": (
                "Trading Specialist",
                "PAPER-strategieanalyse en marktkennis via PaperTradingService.",
            ),
            "voice_specialist": (
                "Voice Specialist",
                "Spraak-, transcriptie- en voice-workflows (lokaal).",
            ),
        }
        for agent_id, (name, description) in promotions.items():
            db.execute(
                """UPDATE agent_profiles
                   SET name=?, description=?, enabled=1, updated_at=?
                   WHERE id=?""",
                (name, description, now, agent_id),
            )
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(10, ?)", (now,))

    @staticmethod
    def _json(value: str | None, fallback: Any) -> Any:
        try:
            return json.loads(value or "")
        except Exception:
            return fallback

    def upsert_knowledge_source(
        self,
        *,
        title: str,
        source_type: str,
        uri: str,
        local_path: str | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "ready",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                "SELECT id, created_at FROM knowledge_sources WHERE source_type=? AND uri=?",
                (source_type, uri),
            ).fetchone()
            source_id = row["id"] if row else new_id("src")
            created_at = row["created_at"] if row else now
            db.execute(
                """INSERT INTO knowledge_sources
                   (id,title,source_type,uri,local_path,content_hash,metadata,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_type,uri) DO UPDATE SET
                   title=excluded.title,local_path=excluded.local_path,content_hash=excluded.content_hash,
                   metadata=excluded.metadata,status=excluded.status,updated_at=excluded.updated_at""",
                (
                    source_id,
                    title,
                    source_type,
                    uri,
                    local_path,
                    content_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    status,
                    created_at,
                    now,
                ),
            )
        return self.get_knowledge_source(source_id) or {}

    def get_knowledge_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = self._json(item.get("metadata"), {})
        return item

    def get_knowledge_source_by_uri(self, source_type: str, uri: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM knowledge_sources WHERE source_type=? AND uri=?",
                (source_type, uri),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = self._json(item.get("metadata"), {})
        return item

    def list_knowledge_sources(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM knowledge_sources ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._json(item.get("metadata"), {})
            items.append(item)
        return items

    def replace_knowledge_chunks(self, source_id: str, title: str, chunks: list[dict[str, Any]]) -> int:
        now = utc_now()
        with self.connection() as db:
            return self._replace_knowledge_chunks_conn(db, source_id, title, chunks, now=now)

    def _replace_knowledge_chunks_conn(
        self,
        db: sqlite3.Connection,
        source_id: str,
        title: str,
        chunks: list[dict[str, Any]],
        *,
        now: str | None = None,
    ) -> int:
        stamp = now or utc_now()
        written = 0
        old = db.execute("SELECT id FROM knowledge_chunks WHERE source_id=?", (source_id,)).fetchall()
        if old:
            db.executemany("DELETE FROM knowledge_fts WHERE chunk_id=?", [(row["id"],) for row in old])
        db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
        for seq, chunk in enumerate(chunks):
            content = str(chunk.get("content", "")).strip()
            if not content:
                continue
            chunk_id = str(chunk.get("id") or new_id("chunk"))
            heading = str(chunk.get("heading", ""))
            digest = str(chunk.get("content_hash", ""))
            tokens = int(chunk.get("token_estimate", max(1, len(content) // 4)))
            db.execute(
                """INSERT INTO knowledge_chunks
                   (id,source_id,sequence,heading,content,content_hash,token_estimate,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (chunk_id, source_id, seq, heading, content, digest, tokens, stamp),
            )
            db.execute(
                "INSERT INTO knowledge_fts(chunk_id,source_id,title,heading,content) VALUES(?,?,?,?,?)",
                (chunk_id, source_id, title, heading, content),
            )
            written += 1
        return written

    def upsert_knowledge_with_chunks(
        self,
        *,
        title: str,
        source_type: str,
        uri: str,
        chunks: list[dict[str, Any]],
        local_path: str | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "ready",
    ) -> dict[str, Any]:
        """Atomically upsert a knowledge source and replace its chunks (F-14).

        One SQLite transaction: source is ``pending`` until chunks commit, then
        promoted to ``ready`` only when at least one chunk was written. A crash
        mid-write cannot leave a published ready source with 0 chunks.
        """
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                "SELECT id, created_at FROM knowledge_sources WHERE source_type=? AND uri=?",
                (source_type, uri),
            ).fetchone()
            source_id = row["id"] if row else new_id("src")
            created_at = row["created_at"] if row else now
            db.execute(
                """INSERT INTO knowledge_sources
                   (id,title,source_type,uri,local_path,content_hash,metadata,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_type,uri) DO UPDATE SET
                   title=excluded.title,local_path=excluded.local_path,content_hash=excluded.content_hash,
                   metadata=excluded.metadata,status=excluded.status,updated_at=excluded.updated_at""",
                (
                    source_id,
                    title,
                    source_type,
                    uri,
                    local_path,
                    content_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    "pending",
                    created_at,
                    now,
                ),
            )
            written = self._replace_knowledge_chunks_conn(db, source_id, title, chunks, now=now)
            if status == "ready":
                final_status = "ready" if written > 0 else "verification_failed"
            else:
                final_status = status
            db.execute(
                "UPDATE knowledge_sources SET status=?, updated_at=? WHERE id=?",
                (final_status, now, source_id),
            )
        source = self.get_knowledge_source(source_id) or {}
        source["chunks_written"] = written
        return source

    def search_knowledge(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in query)
        tokens = [token for token in cleaned.split() if len(token) > 1][:20]
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        with self.connection() as db:
            try:
                if not fts_query:
                    raise sqlite3.OperationalError("empty fts query")
                rows = db.execute(
                    """SELECT f.chunk_id,f.source_id,f.title,f.heading,f.content,
                              bm25(knowledge_fts) AS rank,s.source_type,s.uri,s.local_path,s.updated_at
                       FROM knowledge_fts f
                       JOIN knowledge_sources s ON s.id=f.source_id
                       WHERE knowledge_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                needle = f"%{query}%"
                rows = db.execute(
                    """SELECT c.id AS chunk_id,c.source_id,s.title,c.heading,c.content,0 AS rank,
                              s.source_type,s.uri,s.local_path,s.updated_at
                       FROM knowledge_chunks c JOIN knowledge_sources s ON s.id=c.source_id
                       WHERE c.content LIKE ? OR s.title LIKE ? LIMIT ?""",
                    (needle, needle, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def knowledge_stats(self) -> dict[str, Any]:
        with self.connection() as db:
            sources = db.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            tokens = db.execute("SELECT COALESCE(SUM(token_estimate),0) FROM knowledge_chunks").fetchone()[0]
            types = {
                row["source_type"]: row["n"]
                for row in db.execute(
                    "SELECT source_type,COUNT(*) AS n FROM knowledge_sources GROUP BY source_type"
                ).fetchall()
            }
        return {"sources": sources, "chunks": chunks, "token_estimate": tokens, "types": types}

    def create_research_project(
        self,
        title: str,
        topic: str,
        depth: str,
        allow_web: bool,
        source_inputs: list[str],
        authorized_downloads: bool = False,
        max_rounds: int | None = None,
        agent_count: int = 1,
    ) -> dict[str, Any]:
        now = utc_now()
        project_id = new_id("research")
        rounds_value = None if max_rounds is None else max(1, min(int(max_rounds), 60))
        agents_value = max(1, min(int(agent_count or 1), 8))
        item = {
            "id": project_id,
            "title": title.strip() or topic.strip()[:120],
            "topic": topic.strip(),
            "depth": depth,
            "status": "queued",
            "progress": 0,
            "allow_web": int(allow_web),
            "authorized_downloads": int(authorized_downloads),
            "source_inputs": json.dumps(source_inputs, ensure_ascii=False),
            "findings": "",
            "report": "",
            "metrics": json.dumps({}, ensure_ascii=False),
            "error": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "max_rounds": rounds_value,
            "agent_count": agents_value,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO research_projects
                   (id,title,topic,depth,status,progress,allow_web,authorized_downloads,source_inputs,findings,report,metrics,error,
                    created_at,updated_at,started_at,finished_at,max_rounds,agent_count)
                   VALUES(:id,:title,:topic,:depth,:status,:progress,:allow_web,:authorized_downloads,:source_inputs,:findings,:report,
                          :metrics,:error,:created_at,:updated_at,:started_at,:finished_at,:max_rounds,:agent_count)""",
                item,
            )
        self.add_research_event(project_id, "info", "Onderzoeksproject aangemaakt.")
        return self.get_research_project(project_id) or {}

    def _research_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["allow_web"] = bool(item["allow_web"])
        item["authorized_downloads"] = bool(item.get("authorized_downloads", 0))
        item["source_inputs"] = self._json(item.get("source_inputs"), [])
        item["metrics"] = self._json(item.get("metrics"), {})
        raw_rounds = item.get("max_rounds")
        item["max_rounds"] = None if raw_rounds is None else int(raw_rounds)
        item["agent_count"] = max(1, int(item.get("agent_count") or 1))
        return item

    def list_research_projects(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM research_projects ORDER BY updated_at DESC").fetchall()
        return [item for row in rows if (item := self._research_row(row))]

    def get_research_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM research_projects WHERE id=?", (project_id,)).fetchone()
        return self._research_row(row)

    def update_research_project(self, project_id: str, **values: Any) -> dict[str, Any] | None:
        allowed = {"status", "progress", "findings", "report", "metrics", "error", "started_at", "finished_at"}
        values = {key: value for key, value in values.items() if key in allowed}
        if "metrics" in values and not isinstance(values["metrics"], str):
            values["metrics"] = json.dumps(values["metrics"], ensure_ascii=False)
        values["updated_at"] = utc_now()
        with self.connection() as db:
            db.execute(
                "UPDATE research_projects SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                [*values.values(), project_id],
            )
        return self.get_research_project(project_id)

    def add_research_event(self, project_id: str, level: str, message: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO research_events(project_id,level,message,created_at) VALUES(?,?,?,?)",
                (project_id, level, message, utc_now()),
            )

    def research_events(self, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM research_events WHERE project_id=? ORDER BY id", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def link_research_source(self, project_id: str, source_id: str, relevance: float = 1.0) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO research_project_sources(project_id,source_id,relevance) VALUES(?,?,?)",
                (project_id, source_id, relevance),
            )

    def research_sources(self, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT s.*,r.relevance FROM research_project_sources r
                   JOIN knowledge_sources s ON s.id=r.source_id
                   WHERE r.project_id=? ORDER BY r.relevance DESC,s.updated_at DESC""",
                (project_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._json(item.get("metadata"), {})
            items.append(item)
        return items

    def upsert_workspace(self, name: str, root_path: str) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute("SELECT id,created_at FROM workspaces WHERE root_path=?", (root_path,)).fetchone()
            workspace_id = row["id"] if row else new_id("ws")
            created_at = row["created_at"] if row else now
            db.execute(
                """INSERT INTO workspaces(id,name,root_path,created_at,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(root_path) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at""",
                (workspace_id, name, root_path, created_at, now),
            )
        return self.get_workspace(workspace_id) or {}

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        return dict(row) if row else None

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM workspaces ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def upsert_indexed_file(
        self,
        *,
        workspace_id: str | None,
        path: str,
        name: str,
        extension: str,
        size_bytes: int,
        mtime: float,
        content_hash: str | None,
        source_id: str | None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute("SELECT id,created_at FROM indexed_files WHERE path=?", (path,)).fetchone()
            file_id = row["id"] if row else new_id("file")
            created_at = row["created_at"] if row else now
            db.execute(
                """INSERT INTO indexed_files
                   (id,workspace_id,path,name,extension,size_bytes,mtime,content_hash,source_id,status,error,indexed_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET
                   workspace_id=excluded.workspace_id,name=excluded.name,extension=excluded.extension,
                   size_bytes=excluded.size_bytes,mtime=excluded.mtime,content_hash=excluded.content_hash,
                   source_id=excluded.source_id,status=excluded.status,error=excluded.error,
                   indexed_at=excluded.indexed_at,updated_at=excluded.updated_at""",
                (
                    file_id,
                    workspace_id,
                    path,
                    name,
                    extension,
                    size_bytes,
                    mtime,
                    content_hash,
                    source_id,
                    status,
                    error,
                    now if status == "ready" else None,
                    created_at,
                    now,
                ),
            )
            result = db.execute("SELECT * FROM indexed_files WHERE id=?", (file_id,)).fetchone()
        return dict(result)

    def get_indexed_file(self, file_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM indexed_files WHERE id=?", (file_id,)).fetchone()
        return dict(row) if row else None

    def list_indexed_files(self, workspace_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connection() as db:
            if workspace_id == "uploads":
                rows = db.execute(
                    "SELECT * FROM indexed_files WHERE workspace_id IS NULL ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif workspace_id:
                rows = db.execute(
                    "SELECT * FROM indexed_files WHERE workspace_id=? ORDER BY updated_at DESC LIMIT ?",
                    (workspace_id, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM indexed_files ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def list_knowledge_chunks(self, source_id: str, limit: int = 40) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT id,source_id,sequence,heading,content,content_hash,token_estimate,created_at
                   FROM knowledge_chunks WHERE source_id=? ORDER BY sequence ASC LIMIT ?""",
                (source_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_knowledge_source(self, source_id: str) -> int:
        """Hard-delete a knowledge source and its chunks/FTS rows."""
        if not source_id:
            return 0
        with self.connection() as db:
            row = db.execute("SELECT id FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
            if not row:
                return 0
            old = db.execute("SELECT id FROM knowledge_chunks WHERE source_id=?", (source_id,)).fetchall()
            if old:
                db.executemany("DELETE FROM knowledge_fts WHERE chunk_id=?", [(item["id"],) for item in old])
            db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM knowledge_sources WHERE id=?", (source_id,))
        return 1

    def delete_indexed_file(self, file_id: str, *, remove_knowledge: bool = True) -> dict[str, Any] | None:
        record = self.get_indexed_file(file_id)
        if not record:
            return None
        source_id = record.get("source_id")
        with self.connection() as db:
            db.execute("DELETE FROM indexed_files WHERE id=?", (file_id,))
        if remove_knowledge and source_id:
            self.delete_knowledge_source(str(source_id))
        return record

    def delete_workspace(self, workspace_id: str, *, remove_files: bool = True) -> dict[str, Any] | None:
        workspace = self.get_workspace(workspace_id)
        if not workspace:
            return None
        removed_files = 0
        if remove_files:
            for item in self.list_indexed_files(workspace_id, limit=100_000):
                self.delete_indexed_file(item["id"], remove_knowledge=True)
                removed_files += 1
        with self.connection() as db:
            db.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))
        return {**workspace, "removed_files": removed_files}

    def save_plugin(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        plugin_id = str(values.get("id") or new_id("plugin"))
        with self.connection() as db:
            row = db.execute("SELECT created_at FROM plugins WHERE id=?", (plugin_id,)).fetchone()
            created_at = row["created_at"] if row else now
            db.execute(
                """INSERT INTO plugins
                   (id,name,version,description,source,source_ref,local_path,plugin_type,runtime_type,entrypoint,
                    manifest,permissions,status,enabled,health,trust,last_error,failure_state,isolation,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name,version=excluded.version,description=excluded.description,source=excluded.source,
                   source_ref=excluded.source_ref,local_path=excluded.local_path,plugin_type=excluded.plugin_type,
                   runtime_type=excluded.runtime_type,entrypoint=excluded.entrypoint,manifest=excluded.manifest,
                   permissions=excluded.permissions,status=excluded.status,enabled=excluded.enabled,
                   health=excluded.health,trust=excluded.trust,last_error=excluded.last_error,
                   failure_state=excluded.failure_state,isolation=excluded.isolation,updated_at=excluded.updated_at""",
                (
                    plugin_id,
                    values["name"],
                    values.get("version", "0.1.0"),
                    values.get("description", ""),
                    values.get("source", "local"),
                    values.get("source_ref", ""),
                    values["local_path"],
                    values.get("plugin_type", "tool"),
                    values.get("runtime_type", "unknown"),
                    values.get("entrypoint", ""),
                    json.dumps(values.get("manifest", {}), ensure_ascii=False),
                    json.dumps(values.get("permissions", []), ensure_ascii=False),
                    values.get("status", "detected"),
                    int(bool(values.get("enabled", False))),
                    values.get("health", "unknown"),
                    values.get("trust", "untrusted"),
                    values.get("last_error"),
                    values.get("failure_state"),
                    values.get("isolation", "plugin_cwd"),
                    created_at,
                    now,
                ),
            )
        return self.get_plugin(plugin_id) or {}

    def _plugin_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["manifest"] = self._json(item.get("manifest"), {})
        item["permissions"] = self._json(item.get("permissions"), [])
        item["enabled"] = bool(item["enabled"])
        # Normalize legacy trust labels for callers.
        from plugin_runtime_v2 import normalize_isolation, normalize_trust

        item["trust"] = normalize_trust(item.get("trust"))
        item["isolation"] = normalize_isolation(item.get("isolation") or item["manifest"].get("isolation"))
        item["failure_state"] = item.get("failure_state") or None
        item["capabilities"] = item["manifest"].get("capabilities") if isinstance(item["manifest"].get("capabilities"), dict) else {}
        return item

    def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM plugins WHERE id=?", (plugin_id,)).fetchone()
        return self._plugin_row(row)

    def list_plugins(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM plugins ORDER BY updated_at DESC").fetchall()
        return [item for row in rows if (item := self._plugin_row(row))]

    def set_plugin_state(
        self,
        plugin_id: str,
        *,
        enabled: bool | None = None,
        status: str | None = None,
        health: str | None = None,
        last_error: str | None = None,
        trust: str | None = None,
        failure_state: str | None = None,
        isolation: str | None = None,
        clear_failure: bool = False,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": utc_now()}
        if enabled is not None:
            values["enabled"] = int(enabled)
        if status is not None:
            values["status"] = status
        if health is not None:
            values["health"] = health
        if last_error is not None:
            values["last_error"] = last_error
        if trust is not None:
            from plugin_runtime_v2 import normalize_trust

            values["trust"] = normalize_trust(trust)
        if isolation is not None:
            from plugin_runtime_v2 import normalize_isolation

            values["isolation"] = normalize_isolation(isolation)
        if clear_failure:
            values["failure_state"] = None
        elif failure_state is not None:
            values["failure_state"] = failure_state
            # Structural failures must not leave a plugin falsely Ready/enabled.
            structural = {
                "dependency_failed",
                "integrity_failed",
                "unsupported_runtime",
                "not_ready",
            }
            if failure_state in structural:
                values["status"] = "needs_review"
                values["enabled"] = 0
                if health is None:
                    values["health"] = "needs_attention"
        with self.connection() as db:
            db.execute(
                "UPDATE plugins SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                [*values.values(), plugin_id],
            )
        try:
            from plugin_registry_cache import invalidate_plugin_registry_cache
            from tool_result_cache import clear_tool_result_cache

            invalidate_plugin_registry_cache()
            if any(key in values for key in ("enabled", "trust", "status", "failure_state")):
                clear_tool_result_cache()
        except Exception:
            pass
        return self.get_plugin(plugin_id)

    def plugin_timeline(self, plugin_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        from plugin_runtime_v2 import build_timeline

        events = self.plugin_events(plugin_id)
        calls = self.tool_calls(plugin_id, limit=max(1, min(limit, 500)))
        return build_timeline(events=events, tool_calls=calls)[-limit:]

    def delete_plugin(self, plugin_id: str) -> bool:
        with self.connection() as db:
            row = db.execute("SELECT id FROM plugins WHERE id=?", (plugin_id,)).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM plugin_events WHERE plugin_id=?", (plugin_id,))
            db.execute("DELETE FROM plugin_tools WHERE plugin_id=?", (plugin_id,))
            db.execute("DELETE FROM tool_calls WHERE plugin_id=?", (plugin_id,))
            db.execute("DELETE FROM plugins WHERE id=?", (plugin_id,))
        try:
            from plugin_knowledge_index import remove_plugin_index
            from plugin_registry_cache import invalidate_plugin_registry_cache
            from tool_result_cache import clear_tool_result_cache

            remove_plugin_index(self, plugin_id)
            invalidate_plugin_registry_cache()
            clear_tool_result_cache()
        except Exception:
            pass
        return True

    def replace_plugin_tools(self, plugin_id: str, tools: list[dict[str, Any]]) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM plugin_tools WHERE plugin_id=?", (plugin_id,))
            for tool in tools:
                command = tool.get("command", "")
                command_value = json.dumps(command, ensure_ascii=False) if isinstance(command, list) else str(command)
                metadata = {
                    key: value for key, value in tool.items()
                    if key not in {"id", "plugin_id", "name", "description", "input_schema", "output_schema", "command", "enabled"}
                }
                db.execute(
                    """INSERT INTO plugin_tools
                       (id,plugin_id,name,description,input_schema,output_schema,command,metadata,enabled)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id("tool"),
                        plugin_id,
                        tool["name"],
                        tool.get("description", ""),
                        json.dumps(tool.get("input_schema", {}), ensure_ascii=False),
                        json.dumps(tool.get("output_schema", {}), ensure_ascii=False),
                        command_value,
                        json.dumps(metadata, ensure_ascii=False),
                        int(bool(tool.get("enabled", True))),
                    ),
                )

    def plugin_tools(self, plugin_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as db:
            if plugin_id:
                rows = db.execute(
                    "SELECT * FROM plugin_tools WHERE plugin_id=? ORDER BY name", (plugin_id,)
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM plugin_tools ORDER BY plugin_id,name").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["input_schema"] = self._json(item.get("input_schema"), {})
            item["output_schema"] = self._json(item.get("output_schema"), {})
            raw_command = str(item.get("command", ""))
            parsed_command = self._json(raw_command, None) if raw_command.lstrip().startswith("[") else None
            item["command"] = parsed_command if isinstance(parsed_command, list) else raw_command
            item["metadata"] = self._json(item.get("metadata"), {})
            item["enabled"] = bool(item["enabled"])
            items.append(item)
        return items

    def add_plugin_event(self, plugin_id: str, level: str, message: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO plugin_events(plugin_id,level,message,created_at) VALUES(?,?,?,?)",
                (plugin_id, level, message, utc_now()),
            )

    def plugin_events(self, plugin_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM plugin_events WHERE plugin_id=? ORDER BY id", (plugin_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_tool_call(
        self,
        plugin_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        *,
        invocation_type: str = "manual",
        approved_by_user: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        call_id = new_id("call")
        safe_input = self._redact_tool_data(input_data)
        safe_metadata = self._redact_tool_data(metadata or {})
        with self.connection() as db:
            db.execute(
                """INSERT INTO tool_calls
                   (id,plugin_id,tool_name,input_json,status,invocation_type,approved_by_user,metadata_json,started_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    call_id,
                    plugin_id,
                    tool_name,
                    json.dumps(safe_input, ensure_ascii=False),
                    "running",
                    invocation_type,
                    int(approved_by_user),
                    json.dumps(safe_metadata, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return call_id

    @staticmethod
    def _redact_tool_data(value: Any, key: str = "") -> Any:
        """Keep execution traces useful without persisting common secret fields."""
        sensitive = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.I)
        if sensitive.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(item_key): PlatformDatabase._redact_tool_data(item_value, str(item_key)) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [PlatformDatabase._redact_tool_data(item, key) for item in value]
        return value

    def finish_tool_call(
        self,
        call_id: str,
        status: str,
        *,
        output: str | None = None,
        stdout: str = "",
        stderr: str = "",
        error: str | None = None,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_tool_call(call_id)
        prior_meta = existing.get("metadata") if isinstance(existing, dict) else None
        merged_meta: dict[str, Any] = {}
        if isinstance(prior_meta, dict):
            merged_meta.update(prior_meta)
        if isinstance(metadata, dict):
            merged_meta.update(metadata)
        with self.connection() as db:
            db.execute(
                """UPDATE tool_calls SET status=?,output_text=?,stdout_text=?,stderr_text=?,error=?,exit_code=?,
                   duration_ms=?,metadata_json=?,finished_at=? WHERE id=?""",
                (
                    status,
                    output,
                    stdout[-100_000:],
                    stderr[-100_000:],
                    error,
                    exit_code,
                    duration_ms,
                    json.dumps(self._redact_tool_data(merged_meta), ensure_ascii=False),
                    utc_now(),
                    call_id,
                ),
            )
        return self.get_tool_call(call_id)

    def get_tool_call(self, call_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM tool_calls WHERE id=?", (call_id,)).fetchone()
        return self._tool_call_row(row)

    def tool_calls(self, plugin_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM tool_calls WHERE plugin_id=? ORDER BY started_at DESC LIMIT ?",
                (plugin_id, max(1, min(limit, 500))),
            ).fetchall()
        return [item for row in rows if (item := self._tool_call_row(row))]

    def latest_dependency_call(self, plugin_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM tool_calls WHERE plugin_id=? AND tool_name='__dependencies__' ORDER BY started_at DESC LIMIT 1",
                (plugin_id,),
            ).fetchone()
        return self._tool_call_row(row)

    def recover_running_tool_calls(self) -> int:
        """Mark in-flight calls interrupted when their supervising HADES process died."""
        now = utc_now()
        with self.connection() as db:
            result = db.execute(
                """UPDATE tool_calls
                   SET status='interrupted', error='HADES herstartte tijdens deze toolcall.',
                       finished_at=?, duration_ms=COALESCE(duration_ms, 0)
                   WHERE status='running'""",
                (now,),
            )
        return result.rowcount

    def _tool_call_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["input"] = self._json(item.pop("input_json", "{}"), {})
        item["metadata"] = self._json(item.pop("metadata_json", "{}"), {})
        item["output"] = item.pop("output_text", None)
        item["stdout"] = item.pop("stdout_text", "")
        item["stderr"] = item.pop("stderr_text", "")
        item["approved_by_user"] = bool(item.get("approved_by_user"))
        item["timestamp"] = item.get("finished_at") or item.get("started_at")
        return item

    def replace_work_plan(self, task_id: str, steps: list[dict[str, Any]], *, plan_version: int = 1) -> list[dict[str, Any]]:
        now = utc_now()
        with self.connection() as db:
            db.execute("DELETE FROM work_steps WHERE task_id=?", (task_id,))
            for index, step in enumerate(steps):
                step_key = str(step.get("step_id") or step.get("step_key") or f"step-{index + 1}")
                depends_on = step.get("depends_on") or []
                if not isinstance(depends_on, list):
                    depends_on = []
                input_refs = step.get("input_refs") or []
                if not isinstance(input_refs, list):
                    input_refs = []
                output_schema = step.get("output_schema") if isinstance(step.get("output_schema"), dict) else {}
                if step.get("required_capability"):
                    output_schema = dict(output_schema)
                    output_schema["required_capability"] = step.get("required_capability")
                db.execute(
                    """INSERT INTO work_steps(
                           id,task_id,step_index,agent_id,kind,title,instruction,status,output,error,
                           step_key,depends_on_json,input_refs_json,output_schema_json,plan_version,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,'queued','',NULL,?,?,?,?,?,?,?)""",
                    (
                        new_id("step"),
                        task_id,
                        index,
                        step.get("agent_id", "executor"),
                        step.get("kind", "work"),
                        step.get("title", f"Stap {index + 1}"),
                        step.get("instruction", ""),
                        step_key,
                        json.dumps(depends_on, ensure_ascii=False),
                        json.dumps(input_refs, ensure_ascii=False),
                        json.dumps(output_schema, ensure_ascii=False),
                        int(plan_version),
                        now,
                        now,
                    ),
                )
        return self.work_steps(task_id)

    def work_steps(self, task_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM work_steps WHERE task_id=? ORDER BY step_index", (task_id,)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["step_key"] = item.get("step_key") or item.get("id")
            item["depends_on"] = self._json(item.pop("depends_on_json", "[]"), [])
            item["input_refs"] = self._json(item.pop("input_refs_json", "[]"), [])
            item["output_schema"] = self._json(item.pop("output_schema_json", "{}"), {})
            if isinstance(item.get("output_schema"), dict) and item["output_schema"].get("required_capability"):
                item["required_capability"] = item["output_schema"].get("required_capability")
            items.append(item)
        return items

    def update_work_step(self, step_id: str, *, status: str | None = None, output: str | None = None, error: str | None = None) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            values["status"] = status
        if output is not None:
            values["output"] = output
        if error is not None:
            values["error"] = error
        with self.connection() as db:
            db.execute("UPDATE work_steps SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?", [*values.values(), step_id])
            row = db.execute("SELECT * FROM work_steps WHERE id=?", (step_id,)).fetchone()
        return dict(row) if row else None

    def add_work_checkpoint(self, task_id: str, state: dict[str, Any]) -> str:
        checkpoint_id = new_id("checkpoint")
        with self.connection() as db:
            db.execute(
                "INSERT INTO work_checkpoints(id,task_id,state_json,created_at) VALUES(?,?,?,?)",
                (checkpoint_id, task_id, json.dumps(state, ensure_ascii=False), utc_now()),
            )
        return checkpoint_id

    def latest_work_checkpoint(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM work_checkpoints WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["state"] = self._json(item.pop("state_json"), {})
        return item

    def reset_interrupted_work_steps(self, task_id: str) -> int:
        """Return interrupted running steps to queued so a recovered task can resume safely."""
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE work_steps SET status='queued', error='Backend herstart; stap veilig hervat.', updated_at=? "
                "WHERE task_id=? AND status='running'",
                (utc_now(), task_id),
            )
        return int(cursor.rowcount or 0)

    def reset_failed_work_steps_for_resume(self, task_id: str) -> int:
        """Re-queue failed/cancelled steps while keeping completed steps for checkpoint resume."""
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE work_steps SET status='queued', error='', output=COALESCE(output, ''), updated_at=? "
                "WHERE task_id=? AND status IN ('failed', 'cancelled')",
                (utc_now(), task_id),
            )
        return int(cursor.rowcount or 0)

    def clear_work_state(self, task_id: str) -> None:
        """Drop a previous execution plan/checkpoints for an explicit retry from scratch."""
        with self.connection() as db:
            db.execute("DELETE FROM work_steps WHERE task_id=?", (task_id,))
            db.execute("DELETE FROM work_checkpoints WHERE task_id=?", (task_id,))

    def work_summary(self, task_id: str) -> dict[str, Any]:
        steps = self.work_steps(task_id)
        checkpoint = self.latest_work_checkpoint(task_id)
        counts = {status: 0 for status in ("queued", "running", "completed", "failed", "cancelled")}
        for step in steps:
            counts[step.get("status", "queued")] = counts.get(step.get("status", "queued"), 0) + 1
        return {"steps": steps, "checkpoint": checkpoint, "counts": counts}

    def add_brain_external_link(self, source_id: str, target_id: str, relation: str = "gerelateerd aan") -> dict[str, Any] | None:
        if source_id == target_id:
            return None
        with self.connection() as db:
            existing = db.execute(
                "SELECT 1 FROM brain_external_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            ).fetchone()
            if existing:
                return None
            db.execute(
                "INSERT INTO brain_external_links(source_id,target_id,relation,created_at) VALUES(?,?,?,?)",
                (source_id, target_id, relation.strip() or "gerelateerd aan", utc_now()),
            )
        return {
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation.strip() or "gerelateerd aan",
            "external": True,
        }

    def update_brain_external_link(self, source_id: str, target_id: str, relation: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT source_id, target_id, relation FROM brain_external_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            ).fetchone()
            if not row:
                return None
            cleaned = relation.strip() or "gerelateerd aan"
            db.execute(
                "UPDATE brain_external_links SET relation = ? WHERE source_id = ? AND target_id = ?",
                (cleaned, source_id, target_id),
            )
        return {"source_id": source_id, "target_id": target_id, "relation": cleaned, "external": True}

    def delete_brain_external_link(self, source_id: str, target_id: str) -> bool:
        with self.connection() as db:
            cur = db.execute(
                "DELETE FROM brain_external_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            )
            return cur.rowcount > 0

    def list_brain_external_links(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT source_id,target_id,relation FROM brain_external_links ORDER BY created_at").fetchall()
        return [{**dict(row), "external": True} for row in rows]

    def count_knowledge_sources(self) -> int:
        with self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0])

    def list_agents(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM agent_profiles ORDER BY role,name").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["allowed_tools"] = self._json(item.get("allowed_tools"), [])
            item["enabled"] = bool(item["enabled"])
            items.append(item)
        return items

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM agent_profiles WHERE id=?", (agent_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["allowed_tools"] = self._json(item.get("allowed_tools"), [])
        item["enabled"] = bool(item["enabled"])
        return item

    def set_agent_state(self, agent_id: str, *, enabled: bool) -> dict[str, Any] | None:
        current = self.get_agent(agent_id)
        if not current:
            return None
        with self.connection() as db:
            db.execute(
                "UPDATE agent_profiles SET enabled=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, utc_now(), agent_id),
            )
        return self.get_agent(agent_id)

    def list_work_steps(self, *, limit: int = 2_000) -> list[dict[str, Any]]:
        """Recent work steps across tasks for agent console aggregation."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM work_steps ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 10_000)),),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["step_key"] = item.get("step_key") or item.get("id")
            item["depends_on"] = self._json(item.pop("depends_on_json", "[]"), [])
            item["input_refs"] = self._json(item.pop("input_refs_json", "[]"), [])
            item["output_schema"] = self._json(item.pop("output_schema_json", "{}"), {})
            if isinstance(item.get("output_schema"), dict) and item["output_schema"].get("required_capability"):
                item["required_capability"] = item["output_schema"].get("required_capability")
            items.append(item)
        return items

    def record_agent_usage(
        self,
        *,
        agent_id: str,
        provider: str,
        model_id: str | None,
        usage: dict[str, Any],
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        event_id = new_id("ausage")
        now = utc_now()
        record = {
            "id": event_id,
            "agent_id": agent_id,
            "provider": provider or "lm_studio",
            "model_id": model_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_tokens": usage.get("cached_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "cost": usage.get("cost"),
            "created_at": now,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO agent_usage_events(
                    id,agent_id,provider,model_id,task_id,conversation_id,
                    input_tokens,output_tokens,total_tokens,cached_tokens,reasoning_tokens,cost,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["id"],
                    record["agent_id"],
                    record["provider"],
                    record["model_id"],
                    record["task_id"],
                    record["conversation_id"],
                    record["input_tokens"],
                    record["output_tokens"],
                    record["total_tokens"],
                    record["cached_tokens"],
                    record["reasoning_tokens"],
                    record["cost"],
                    record["created_at"],
                ),
            )
        return record

    def agent_usage_totals(self) -> dict[str, dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT agent_id,
                          COUNT(*) AS requests,
                          SUM(input_tokens) AS input_tokens,
                          SUM(output_tokens) AS output_tokens,
                          SUM(total_tokens) AS total_tokens,
                          SUM(cached_tokens) AS cached_tokens,
                          SUM(reasoning_tokens) AS reasoning_tokens,
                          SUM(cost) AS cost
                   FROM agent_usage_events
                   GROUP BY agent_id"""
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            # SUM of all-NULL columns is NULL — keep null so UI shows "—" not fake 0.
            result[str(item["agent_id"])] = {
                "requests": int(item["requests"] or 0),
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "total_tokens": item["total_tokens"],
                "cached_tokens": item["cached_tokens"],
                "reasoning_tokens": item["reasoning_tokens"],
                "cost": item["cost"],
                "known": True,
            }
        return result

    def agent_usage_events(self, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM agent_usage_events WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
                (agent_id, max(1, min(int(limit), 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- Artifacts ---
    def _artifact_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["metadata"] = self._json(item.pop("metadata_json", "{}"), {})
        return item

    def insert_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as db:
            db.execute(
                """INSERT INTO artifacts(
                    id,name,kind,mime_type,size_bytes,checksum_sha256,version,parent_artifact_id,status,storage_path,
                    creator_run_id,creator_toolcall_id,conversation_id,project_id,task_id,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["id"], record["name"], record["kind"], record["mime_type"], record["size_bytes"],
                    record["checksum_sha256"], record["version"], record.get("parent_artifact_id"), record["status"],
                    record["storage_path"], record.get("creator_run_id"), record.get("creator_toolcall_id"),
                    record.get("conversation_id"), record.get("project_id"), record.get("task_id"),
                    json.dumps(record.get("metadata") or {}, ensure_ascii=False),
                    record["created_at"], record["updated_at"],
                ),
            )
        return self.get_artifact(record["id"]) or record

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return self._artifact_row(row)

    def list_artifacts(
        self,
        *,
        conversation_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM artifacts WHERE status != 'deleted'"
        params: list[Any] = []
        if conversation_id:
            sql += " AND conversation_id=?"
            params.append(conversation_id)
        if task_id:
            sql += " AND task_id=?"
            params.append(task_id)
        if project_id:
            sql += " AND project_id=?"
            params.append(project_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._artifact_row(row) for row in rows if row]

    def search_artifacts(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        needle = f"%{query}%"
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE status != 'deleted' AND (name LIKE ? OR mime_type LIKE ? OR kind LIKE ?) ORDER BY updated_at DESC LIMIT ?",
                (needle, needle, needle, limit),
            ).fetchall()
        return [self._artifact_row(row) for row in rows if row]

    def update_artifact(self, artifact_id: str, **values: Any) -> bool:
        if not values:
            return False
        payload = dict(values)
        if "metadata" in payload:
            payload["metadata_json"] = json.dumps(payload.pop("metadata") or {}, ensure_ascii=False)
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE artifacts SET " + ",".join(f"{key}=?" for key in payload) + " WHERE id=?",
                [*payload.values(), artifact_id],
            )
        return cursor.rowcount > 0

    # --- Approvals ---
    def _approval_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["arguments_json"] = self._json(item.get("arguments_json"), {})
        item["scope_json"] = self._json(item.get("scope_json"), {})
        item["destination_paths"] = self._json(item.pop("destination_paths_json", "[]"), [])
        item["checkpoint_json"] = self._json(item.get("checkpoint_json"), {})
        item["response_payload"] = self._json(item.pop("response_payload_json", "{}"), {})
        return item

    def insert_approval_request(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as db:
            db.execute(
                """INSERT INTO approval_requests(
                    id,kind,status,policy_outcome,plugin_id,tool_name,arguments_json,arguments_hash,schema_version,scope_json,
                    expected_effect,destination_paths_json,run_id,task_id,conversation_id,step_id,plan_version,project_id,
                    resume_token,checkpoint_json,response_payload_json,expires_at,decision_at,decision_note,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["id"], record["kind"], record["status"], record.get("policy_outcome", "approval_required"),
                    record.get("plugin_id"), record.get("tool_name"),
                    json.dumps(record.get("arguments_json") or {}, ensure_ascii=False),
                    record.get("arguments_hash", ""), record.get("schema_version", "1"),
                    json.dumps(record.get("scope_json") or {}, ensure_ascii=False),
                    record.get("expected_effect", ""),
                    json.dumps(record.get("destination_paths") or [], ensure_ascii=False),
                    record.get("run_id"), record.get("task_id"), record.get("conversation_id"), record.get("step_id"),
                    record.get("plan_version"), record.get("project_id"), record.get("resume_token"),
                    json.dumps(record.get("checkpoint_json") or {}, ensure_ascii=False),
                    json.dumps(record.get("response_payload") or {}, ensure_ascii=False),
                    record.get("expires_at"), record.get("decision_at"), record.get("decision_note"),
                    record["created_at"], record["updated_at"],
                ),
            )
        return self.get_approval_request(record["id"]) or record

    def get_approval_request(self, request_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone()
        return self._approval_row(row)

    def list_approval_requests(
        self,
        *,
        status: str | None = None,
        task_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM approval_requests WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if task_id:
            sql += " AND task_id=?"
            params.append(task_id)
        if conversation_id:
            sql += " AND conversation_id=?"
            params.append(conversation_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._approval_row(row) for row in rows if row]

    def expire_approval_requests(self, now_iso: str) -> int:
        """Timeout must not auto-allow or auto-reject: pending stays pending.

        Historical rows already marked ``expired`` remain expired. New timeouts
        are surfaced via ``timed_out`` on the public approval view instead of
        silently changing status.
        """
        _ = now_iso
        return 0

    def decide_approval_request(
        self,
        request_id: str,
        *,
        status: str,
        decision_note: str = "",
        response_payload: dict[str, Any] | None = None,
        decision_at: str,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            cursor = db.execute(
                """UPDATE approval_requests
                   SET status=?, decision_note=?, response_payload_json=?, decision_at=?, updated_at=?
                   WHERE id=? AND status='pending'""",
                (
                    status,
                    decision_note,
                    json.dumps(response_payload or {}, ensure_ascii=False),
                    decision_at,
                    decision_at,
                    request_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = db.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone()
        return self._approval_row(row)

    # --- Inbox ---
    def insert_inbox_item(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as db:
            try:
                db.execute(
                    """INSERT INTO inbox_items(
                        id,kind,title,body,ref_type,ref_id,project_id,task_id,conversation_id,status,dedupe_key,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record["id"], record["kind"], record["title"], record.get("body", ""),
                        record.get("ref_type"), record.get("ref_id"), record.get("project_id"),
                        record.get("task_id"), record.get("conversation_id"), record.get("status", "unread"),
                        record.get("dedupe_key"), record["created_at"], record["updated_at"],
                    ),
                )
            except sqlite3.IntegrityError:
                if record.get("dedupe_key"):
                    row = db.execute("SELECT * FROM inbox_items WHERE dedupe_key=?", (record["dedupe_key"],)).fetchone()
                    return dict(row) if row else record
                raise
        return self.get_inbox_item(record["id"]) or record

    def get_inbox_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def get_inbox_by_dedupe(self, dedupe_key: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM inbox_items WHERE dedupe_key=?", (dedupe_key,)).fetchone()
        return dict(row) if row else None

    def list_inbox_items(self, *, status: str | None = None, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM inbox_items WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_inbox_item(self, item_id: str, **values: Any) -> dict[str, Any] | None:
        if not values:
            return self.get_inbox_item(item_id)
        with self.connection() as db:
            db.execute(
                "UPDATE inbox_items SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                [*values.values(), item_id],
            )
        return self.get_inbox_item(item_id)

    def mark_inbox_refs(self, ref_type: str, ref_id: str, *, status: str) -> int:
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE inbox_items SET status=?, updated_at=? WHERE ref_type=? AND ref_id=? AND status!='archived'",
                (status, utc_now(), ref_type, ref_id),
            )
        return int(cursor.rowcount or 0)

    # --- Schedules ---
    def _schedule_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["paused"] = bool(item.get("paused"))
        item["catch_up"] = bool(item.get("catch_up"))
        return item

    def upsert_task_schedule(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as db:
            existing = db.execute("SELECT id FROM task_schedules WHERE task_id=?", (record["task_id"],)).fetchone()
            if existing:
                schedule_id = existing["id"]
                db.execute(
                    """UPDATE task_schedules SET frequency=?, timezone=?, run_at=?, time_of_day=?, weekday=?,
                       enabled=?, paused=?, catch_up=?, next_run_at=?, updated_at=? WHERE id=?""",
                    (
                        record["frequency"], record["timezone"], record.get("run_at"), record.get("time_of_day"),
                        record.get("weekday"), int(bool(record.get("enabled", True))), int(bool(record.get("paused", False))),
                        int(bool(record.get("catch_up", True))), record.get("next_run_at"), record["updated_at"], schedule_id,
                    ),
                )
            else:
                schedule_id = record["id"]
                db.execute(
                    """INSERT INTO task_schedules(
                        id,task_id,frequency,timezone,run_at,time_of_day,weekday,enabled,paused,catch_up,next_run_at,last_run_at,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        schedule_id, record["task_id"], record["frequency"], record["timezone"], record.get("run_at"),
                        record.get("time_of_day"), record.get("weekday"), int(bool(record.get("enabled", True))),
                        int(bool(record.get("paused", False))), int(bool(record.get("catch_up", True))),
                        record.get("next_run_at"), record.get("last_run_at"), record["created_at"], record["updated_at"],
                    ),
                )
        return self.get_task_schedule(schedule_id) or record

    def get_task_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM task_schedules WHERE id=?", (schedule_id,)).fetchone()
        return self._schedule_row(row)

    def get_task_schedule_for_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM task_schedules WHERE task_id=?", (task_id,)).fetchone()
        return self._schedule_row(row)

    def update_task_schedule(self, schedule_id: str, **values: Any) -> dict[str, Any]:
        payload = dict(values)
        for key in ("enabled", "paused", "catch_up"):
            if key in payload:
                payload[key] = int(bool(payload[key]))
        with self.connection() as db:
            db.execute(
                "UPDATE task_schedules SET " + ",".join(f"{key}=?" for key in payload) + " WHERE id=?",
                [*payload.values(), schedule_id],
            )
        item = self.get_task_schedule(schedule_id)
        if not item:
            raise KeyError(schedule_id)
        return item

    def list_due_schedules(self, now_iso: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM task_schedules WHERE enabled=1 AND paused=0 AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at",
                (now_iso,),
            ).fetchall()
        return [self._schedule_row(row) for row in rows if row]

    def claim_task_occurrence(
        self,
        *,
        occurrence_id: str,
        schedule_id: str,
        task_id: str,
        planned_at: str,
        claimed_at: str,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            try:
                db.execute(
                    """INSERT INTO task_occurrences(occurrence_id,schedule_id,task_id,planned_at,status,result_summary,claimed_at,finished_at)
                       VALUES(?,?,?,?,'claimed','',?,NULL)""",
                    (occurrence_id, schedule_id, task_id, planned_at, claimed_at),
                )
            except sqlite3.IntegrityError:
                return None
            row = db.execute("SELECT * FROM task_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        return dict(row) if row else None

    def finish_task_occurrence(self, occurrence_id: str, *, status: str, result_summary: str, finished_at: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE task_occurrences SET status=?, result_summary=?, finished_at=? WHERE occurrence_id=?",
                (status, result_summary[:4000], finished_at, occurrence_id),
            )

    def get_task_occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM task_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        return dict(row) if row else None

    def delete_knowledge_by_uri(self, uri: str) -> int:
        """Hard-delete a knowledge source and its chunks/FTS rows by URI."""
        with self.connection() as db:
            row = db.execute("SELECT id FROM knowledge_sources WHERE uri=?", (uri,)).fetchone()
        if not row:
            return 0
        return self.delete_knowledge_source(row["id"])

    def mark_knowledge_forgotten(self, uri: str) -> int:
        with self.connection() as db:
            row = db.execute("SELECT id, metadata FROM knowledge_sources WHERE uri=?", (uri,)).fetchone()
            if not row:
                return 0
            meta = self._json(row["metadata"], {})
            meta["forgotten"] = True
            meta["forgotten_at"] = utc_now()
            db.execute(
                "UPDATE knowledge_sources SET metadata=?, status='forgotten' WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), row["id"]),
            )
            old = db.execute("SELECT id FROM knowledge_chunks WHERE source_id=?", (row["id"],)).fetchall()
            if old:
                db.executemany("DELETE FROM knowledge_fts WHERE chunk_id=?", [(item["id"],) for item in old])
            # Remove chunks so retrieval cannot resurface forgotten content.
            db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (row["id"],))
        return 1

    # --- Conversation runs (HADES-10 Phase 3A) ---
    def _conversation_run_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = self._json(item.get("metadata"), {})
        return item

    def upsert_conversation_run(
        self,
        *,
        conversation_id: str,
        run_id: str,
        run_type: str,
        status: str = "running",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        meta = json.dumps(metadata or {}, ensure_ascii=False)
        with self.connection() as db:
            existing = db.execute(
                "SELECT id, created_at FROM conversation_runs WHERE conversation_id=? AND run_id=?",
                (conversation_id, run_id),
            ).fetchone()
            row_id = existing["id"] if existing else new_id("crun")
            created_at = existing["created_at"] if existing else now
            db.execute(
                """INSERT INTO conversation_runs
                   (id, conversation_id, run_id, run_type, status, title, metadata, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(conversation_id, run_id) DO UPDATE SET
                     run_type=excluded.run_type,
                     status=excluded.status,
                     title=CASE WHEN excluded.title != '' THEN excluded.title ELSE conversation_runs.title END,
                     metadata=excluded.metadata,
                     updated_at=excluded.updated_at""",
                (row_id, conversation_id, run_id, run_type, status, title or "", meta, created_at, now),
            )
            row = db.execute(
                "SELECT * FROM conversation_runs WHERE conversation_id=? AND run_id=?",
                (conversation_id, run_id),
            ).fetchone()
        return self._conversation_run_row(row) or {
            "id": row_id,
            "conversation_id": conversation_id,
            "run_id": run_id,
            "run_type": run_type,
            "status": status,
            "title": title,
            "metadata": metadata or {},
            "created_at": created_at,
            "updated_at": now,
        }

    def list_conversation_runs(self, conversation_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit or 50), 200))
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM conversation_runs
                   WHERE conversation_id=?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (conversation_id, capped),
            ).fetchall()
        return [item for item in (self._conversation_run_row(row) for row in rows) if item]

    def update_conversation_run_status(
        self,
        *,
        conversation_id: str,
        run_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM conversation_runs WHERE conversation_id=? AND run_id=?",
                (conversation_id, run_id),
            ).fetchone()
            if row is None:
                return None
            meta = self._json(row["metadata"], {})
            if metadata:
                meta.update(metadata)
            db.execute(
                """UPDATE conversation_runs
                   SET status=?, metadata=?, updated_at=?
                   WHERE conversation_id=? AND run_id=?""",
                (status, json.dumps(meta, ensure_ascii=False), now, conversation_id, run_id),
            )
            updated = db.execute(
                "SELECT * FROM conversation_runs WHERE conversation_id=? AND run_id=?",
                (conversation_id, run_id),
            ).fetchone()
        return self._conversation_run_row(updated)
