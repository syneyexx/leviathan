from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from sqlite_runtime import sqlite_connection, wal_owner


DEFAULT_SETTINGS: dict[str, Any] = {
    "lm_studio_base_url": "http://127.0.0.1:1234/v1",
    "lm_studio_api_key": "lm-studio",
    "request_timeout_seconds": 120,
    "model_refresh_seconds": 60,
    "streaming": True,
    "auto_connect": True,
    "language": "nl",
    "theme": "light",
    # Presentation is intentionally separate from the color theme: users can
    # switch shells without changing their persisted workspace data.
    "ui_style": "lux",  # lux default; finalbeta optional Phase 1 shell; legacy classic|obsidian|beta|beta2 coerced in UI
    "motion_level": "standard",  # reduced | standard | cinematic
    "native_runtime_mode": "auto",  # auto | enabled | disabled
    # Monotonic revision for optimistic concurrency between Settings / Control Center editors.
    "config_revision": 0,
    "max_concurrent_tasks": 2,
    "file_read_policy": "allow",
    "file_write_policy": "ask",
    "network_policy": "block",
    "subprocess_policy": "allow",
    "reasoning_profile": "adaptive",
    "conversation_learning": True,
    "auto_memory_mode": "project",
    "max_retrieval_items": 8,
    "max_retrieval_chars": 6000,
    "max_retrieval_chars_per_hit": 1200,
    "research_default_depth": "deep",
    "system_prompt": "Je bent HADES, een scherpe lokale AI-assistent. Antwoord standaard in het Nederlands, wees feitelijk, gebruik beschikbare HADES-tools wanneer ze de taak aantoonbaar verbeteren en benoem onzekerheid duidelijk.",
    "plugin_autonomous_tools": True,
    "auto_web_research": True,
    "plugin_auto_install_dependencies": True,
    "max_tool_rounds": 3,
    "expert_mastery_target": 90,
    "expert_max_cycles": 6,
    # Orchestration / specialists / scheduler
    "max_model_calls_per_task": 24,
    "max_specialist_steps": 32,
    "max_subtasks": 8,
    "max_dependency_depth": 6,
    "max_parallel_steps": 2,
    "max_model_concurrency": 1,
    "model_fallback_order": [],
    "role_model_overrides": {},
    "allow_cloud_model_fallback": False,
    # Retrieval
    "retrieval_lexical_weight": 0.55,
    "retrieval_semantic_weight": 0.45,
    "retrieval_multilingual_expand": False,
    "enable_semantic_retrieval": False,
    "embedding_model_id": "",
    "enable_context_compiler_chat": True,
    # Neural Brain (default OFF — conventional HADES unchanged)
    "neural_allow": False,
    "neural_mode": "off",  # off | shadow | read | learn
    "neural_requirement": "off",  # off | preferred | required
    "neural_shadow_sample_rate": 0.0,
    "neural_dual_memory_enabled": False,
    "neural_domain_coding_enabled": True,
    "neural_domain_research_enabled": True,
    "neural_domain_trading_enabled": False,
    "neural_max_concurrent_infer": 1,
    "embedding_timeout_seconds": 30.0,
    "embedding_batch_size": 16,
    "retrieval_diversity_window": 3,
    # Memory
    "memory_auto_promote": False,
    "memory_default_scope": "project",
    "memory_write_enabled": True,
    # Research
    "research_max_questions": 8,
    "research_prefer_local": True,
    # Progress / streaming
    "progress_events_enabled": True,
    "stream_provisional_text": True,
    # Terminal / onboarding
    "terminal_allowlist": [],
    "onboarding_completed_at": "",
    # Voice / speech (local ASR+TTS; separate from paste voice-to-task)
    "voice_enabled": True,
    "voice_asr_provider": "faster_whisper",
    "voice_asr_model": "base",
    "voice_asr_device": "auto",
    "voice_asr_compute_type": "auto",
    "voice_tts_provider": "piper",
    "voice_tts_voice": "nl_NL-pim-medium",
    "voice_tts_speed": 1.0,
    "voice_tts_volume": 1.0,
    "voice_language": "nl",
    "voice_spoken_answers_default": False,
    "voice_speak_style": "compact",
    "voice_turn_mode": "manual",
    "voice_vad_sensitivity": 0.55,
    "voice_vad_end_silence_ms": 900,
    "voice_barge_in": True,
    "voice_wake_word_enabled": False,
    "voice_session_idle_seconds": 120,
    "voice_keep_recordings": False,
    "voice_input_device_id": "",
    "voice_output_device_id": "",
    "voice_setup_completed_at": "",
    # Speech — TTS independent from LM Studio model selection
    "spoken_answers_enabled": False,
    "tts_provider": "none",
    "tts_base_url": "http://127.0.0.1:3900/v1",
    "tts_api_key": "",
    "tts_voice_id": "default",
    "tts_model": "tts-1",
    "tts_speed": 1.0,
    "tts_language": "nl",
    "tts_response_format": "wav",
    "tts_sentence_chunking": True,
    "tts_min_free_ram_mb": 1500,
    "tts_min_free_vram_mb": 0,
    "tts_instruct": "",
    "tts_description": "",
    # Speech recognition — separately configurable from TTS
    "stt_provider": "paste",
    "stt_base_url": "http://127.0.0.1:3900/v1",
    "stt_api_key": "",
    "stt_model": "whisper-1",
    "stt_language": "nl",
    "stt_echo_guard_ms": 750,
}

DEFAULT_PROFILE: dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_tokens": 2048,
    "repeat_penalty": 1.05,
    "seed": -1,
    "system_prompt": (
        "Je bent HADES, een scherpe lokale AI-assistent. Antwoord standaard in het "
        "Nederlands, wees feitelijk en benoem onzekerheid duidelijk."
    ),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class Database:
    """Small SQLite repository; every operation owns its connection."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with sqlite_connection(self.path, timeout=10, busy_timeout=5000) as connection:
            yield connection

    def checkpoint_wal(self, *, truncate: bool = False) -> None:
        if truncate:
            wal_owner.truncate_file(self.path)
        else:
            with sqlite_connection(self.path, timeout=10, busy_timeout=5000) as connection:
                wal_owner.checkpoint(connection, kind="passive", path=self.path)

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_profiles (
                    model_id TEXT PRIMARY KEY,
                    temperature REAL NOT NULL,
                    top_p REAL NOT NULL,
                    top_k INTEGER NOT NULL,
                    max_tokens INTEGER NOT NULL,
                    repeat_penalty REAL NOT NULL,
                    seed INTEGER NOT NULL,
                    system_prompt TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model_id TEXT,
                    system_prompt_override TEXT,
                    working_state TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    priority TEXT NOT NULL CHECK(priority IN ('low', 'normal', 'high')),
                    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
                    model_id TEXT,
                    progress INTEGER NOT NULL DEFAULT 0,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status_created
                    ON tasks(status, created_at);

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_events_task_id
                    ON task_events(task_id, id);

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    source TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL DEFAULT 0.8,
                    importance REAL NOT NULL DEFAULT 0.5,
                    supersedes TEXT,
                    superseded_by TEXT,
                    last_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_collection_updated
                    ON memories(collection, updated_at DESC);

                CREATE TABLE IF NOT EXISTS brain_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pos_x REAL,
                    pos_y REAL
                );

                CREATE TABLE IF NOT EXISTS brain_links (
                    source_id TEXT NOT NULL REFERENCES brain_nodes(id) ON DELETE CASCADE,
                    target_id TEXT NOT NULL REFERENCES brain_nodes(id) ON DELETE CASCADE,
                    relation TEXT NOT NULL,
                    PRIMARY KEY(source_id, target_id)
                );
                """
            )
            # Forward-compatible migration for v0.2/v0.3 databases created before typed/versioned Memory.
            memory_columns = {row["name"] for row in db.execute("PRAGMA table_info(memories)").fetchall()}
            memory_additions = {
                "memory_type": "TEXT NOT NULL DEFAULT 'general'",
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "confidence": "REAL NOT NULL DEFAULT 0.8",
                "importance": "REAL NOT NULL DEFAULT 0.5",
                "supersedes": "TEXT",
                "superseded_by": "TEXT",
                "last_verified_at": "TEXT",
            }
            for column, declaration in memory_additions.items():
                if column not in memory_columns:
                    db.execute(f"ALTER TABLE memories ADD COLUMN {column} {declaration}")

            conversation_columns = {row["name"] for row in db.execute("PRAGMA table_info(conversations)").fetchall()}
            if "system_prompt_override" not in conversation_columns:
                db.execute("ALTER TABLE conversations ADD COLUMN system_prompt_override TEXT")
            if "working_state" not in conversation_columns:
                db.execute("ALTER TABLE conversations ADD COLUMN working_state TEXT")

            brain_columns = {row["name"] for row in db.execute("PRAGMA table_info(brain_nodes)").fetchall()}
            if "pos_x" not in brain_columns:
                db.execute("ALTER TABLE brain_nodes ADD COLUMN pos_x REAL")
            if "pos_y" not in brain_columns:
                db.execute("ALTER TABLE brain_nodes ADD COLUMN pos_y REAL")

            # Per-view layout for any stable entity id (manual + derived overlays).
            # Positions/pins live here so knowledge/memory objects are not duplicated.
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_layout_positions (
                    view_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    pos_x REAL NOT NULL,
                    pos_y REAL NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(view_id, entity_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_viewports (
                    view_id TEXT PRIMARY KEY,
                    x REAL NOT NULL DEFAULT 0,
                    y REAL NOT NULL DEFAULT 0,
                    zoom REAL NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )

            task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
            if "control_state" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN control_state TEXT NOT NULL DEFAULT 'active'")
            if "plan_version" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN plan_version INTEGER NOT NULL DEFAULT 1")
            if "redirect_instruction" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN redirect_instruction TEXT")

            # Capability suite message/memory extensions
            message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)").fetchall()}
            message_additions = {
                "client_request_id": "TEXT",
                "parent_message_id": "TEXT",
                "branch_id": "TEXT",
                "revised_from_id": "TEXT",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, declaration in message_additions.items():
                if column not in message_columns:
                    db.execute(f"ALTER TABLE messages ADD COLUMN {column} {declaration}")
            db.execute("CREATE INDEX IF NOT EXISTS idx_messages_client_request ON messages(conversation_id, client_request_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_messages_branch ON messages(conversation_id, branch_id, created_at)")

            memory_columns = {row["name"] for row in db.execute("PRAGMA table_info(memories)").fetchall()}
            memory_extra = {
                "origin_kind": "TEXT NOT NULL DEFAULT 'user_fact'",
                "source_message_id": "TEXT",
                "source_artifact_id": "TEXT",
                "scope": "TEXT NOT NULL DEFAULT 'project'",
                "proposal_status": "TEXT",
                "forgotten_marker": "INTEGER NOT NULL DEFAULT 0",
                "content_version": "INTEGER NOT NULL DEFAULT 1",
            }
            for column, declaration in memory_extra.items():
                if column not in memory_columns:
                    db.execute(f"ALTER TABLE memories ADD COLUMN {column} {declaration}")
            self._ensure_memory_fts(db)

            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS message_attachments (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL,
                    artifact_id TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    extract_status TEXT NOT NULL DEFAULT 'pending',
                    extract_error TEXT,
                    used_in_context INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_message_attachments_message ON message_attachments(message_id);

                CREATE TABLE IF NOT EXISTS conversation_branches (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    parent_branch_id TEXT,
                    fork_message_id TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    working_state TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_drafts (
                    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                    content TEXT NOT NULL DEFAULT '',
                    attachment_ids_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS client_request_dedup (
                    conversation_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, client_request_id)
                );

                CREATE TABLE IF NOT EXISTS memory_proposals (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    collection TEXT NOT NULL DEFAULT 'Algemeen',
                    origin_kind TEXT NOT NULL DEFAULT 'model_inference',
                    source_message_id TEXT,
                    source_conversation_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    merge_into_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            conversation_columns = {row["name"] for row in db.execute("PRAGMA table_info(conversations)").fetchall()}
            if "active_branch_id" not in conversation_columns:
                db.execute("ALTER TABLE conversations ADD COLUMN active_branch_id TEXT")
            if "project_id" not in conversation_columns:
                db.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")

            now = utc_now()
            for key, value in DEFAULT_SETTINGS.items():
                db.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value), now),
                )
            self._seed(db)
            db.execute("PRAGMA optimize")

    def _seed(self, db: sqlite3.Connection) -> None:
        now = utc_now()
        if db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0:
            memories = [
                (
                    "Voorkeurstaal Nederlands",
                    "HADES communiceert standaard in het Nederlands, tenzij expliciet anders gevraagd.",
                    "Antwoorden standaard in het Nederlands.",
                    "Voorkeuren",
                    ["taal", "communicatie"],
                ),
                (
                    "HADES architectuur",
                    "De lokale architectuur bestaat uit een React-interface, FastAPI-bridge en SQLite-opslag.",
                    "React, FastAPI en SQLite vormen de lokale kern.",
                    "Architectuur",
                    ["core", "techniek"],
                ),
                (
                    "LM Studio-configuratie",
                    "LM Studio levert lokaal een OpenAI-compatibele API op poort 1234.",
                    "Lokale modelserver via het OpenAI-contract.",
                    "Systeem",
                    ["model", "lokaal"],
                ),
            ]
            for title, content, summary, collection, tags in memories:
                db.execute(
                    """INSERT INTO memories
                       (id, title, content, summary, collection, tags, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'Systeemseed', ?, ?)""",
                    (new_id("mem"), title, content, summary, collection, json.dumps(tags), now, now),
                )

        if db.execute("SELECT COUNT(*) FROM brain_nodes").fetchone()[0] == 0:
            nodes = [
                ("core_hades", "HADES", "core", "Centrale lokale AI-workspace.", ["core"]),
                ("core_chat", "Chat", "chat", "Gesprekken met het actieve lokale model.", ["chat"]),
                ("core_tasks", "Taken", "task", "Persistente uitvoeringswachtrij.", ["taken"]),
                ("core_models", "LM Studio", "model", "Lokale OpenAI-compatibele modelserver.", ["model"]),
                ("core_memory", "Geheugen", "memory", "Bewust opgeslagen feiten en keuzes.", ["geheugen"]),
                ("core_fastapi", "FastAPI", "tech", "Lokale brug tussen interface en runtimes.", ["python"]),
                ("core_sqlite", "SQLite", "tech", "Duurzame lokale applicatieopslag.", ["database"]),
                ("core_react", "React", "tech", "Browserinterface en interactieve werkruimte.", ["frontend"]),
            ]
            for node_id, label, kind, description, tags in nodes:
                db.execute(
                    """INSERT INTO brain_nodes
                       (id, label, kind, description, tags, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Systeem', ?, ?)""",
                    (node_id, label, kind, description, json.dumps(tags), now, now),
                )
            for source, target, relation in [
                ("core_hades", "core_chat", "bevat"),
                ("core_hades", "core_tasks", "bevat"),
                ("core_hades", "core_models", "gebruikt"),
                ("core_hades", "core_memory", "onthoudt via"),
                ("core_hades", "core_fastapi", "verbindt via"),
                ("core_chat", "core_models", "genereert met"),
                ("core_tasks", "core_models", "voert uit met"),
                ("core_memory", "core_sqlite", "bewaart in"),
                ("core_fastapi", "core_sqlite", "schrijft naar"),
                ("core_react", "core_fastapi", "roept aan"),
                ("core_hades", "core_react", "toont via"),
            ]:
                db.execute(
                    "INSERT OR IGNORE INTO brain_links(source_id, target_id, relation) VALUES (?, ?, ?)",
                    (source, target, relation),
                )

        if db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0:
            conversation_id = new_id("conv")
            db.execute(
                "INSERT INTO conversations(id, title, model_id, created_at, updated_at) VALUES (?, ?, NULL, ?, ?)",
                (conversation_id, "Welkom bij HADES", now, now),
            )
            db.execute(
                "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                (
                    new_id("msg"),
                    conversation_id,
                    "De lokale workspace staat klaar. Start LM Studio, laad een model en stuur daarna je eerste bericht.",
                    now,
                ),
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    @staticmethod
    def _memory(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        item["forgotten_marker"] = bool(item.get("forgotten_marker") or 0)
        return item

    def get_settings(self) -> dict[str, Any]:
        with self.connection() as db:
            rows = db.execute("SELECT key, value FROM app_settings").fetchall()
        values = DEFAULT_SETTINGS.copy()
        values.update({row["key"]: json.loads(row["value"]) for row in rows})
        return values

    def update_settings(self, values: dict[str, Any], *, bump_revision: bool = True) -> dict[str, Any]:
        now = utc_now()
        allowed = DEFAULT_SETTINGS.keys()
        with self.connection() as db:
            # Compute next revision inside the same transaction when any real key changes.
            touching = [k for k in values.keys() if k in allowed and k != "config_revision"]
            next_revision = None
            if bump_revision and touching:
                row = db.execute("SELECT value FROM app_settings WHERE key=?", ("config_revision",)).fetchone()
                current_rev = 0
                if row is not None:
                    try:
                        current_rev = int(json.loads(row["value"]))
                    except Exception:
                        current_rev = 0
                next_revision = current_rev + 1
            for key, value in values.items():
                if key not in allowed:
                    continue
                if key == "config_revision" and bump_revision:
                    continue
                db.execute(
                    """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                    (key, json.dumps(value), now),
                )
            if next_revision is not None:
                db.execute(
                    """INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                    ("config_revision", json.dumps(next_revision), now),
                )
        return self.get_settings()

    def reset_settings(self) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("DELETE FROM app_settings")
        return self.update_settings(DEFAULT_SETTINGS)

    def list_conversations(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT c.*, COUNT(m.id) AS message_count
                   FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                   GROUP BY c.id ORDER BY c.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, title: str = "Nieuw gesprek", model_id: str | None = None, system_prompt_override: str | None = None) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": new_id("conv"), "title": title.strip() or "Nieuw gesprek", "model_id": model_id,
            "system_prompt_override": (system_prompt_override or "").strip() or None,
            "created_at": now, "updated_at": now,
        }
        with self.connection() as db:
            db.execute(
                "INSERT INTO conversations(id, title, model_id, system_prompt_override, created_at, updated_at) VALUES (:id, :title, :model_id, :system_prompt_override, :created_at, :updated_at)",
                item,
            )
        item["message_count"] = 0
        return item

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        raw_state = item.get("working_state")
        if isinstance(raw_state, str) and raw_state.strip():
            try:
                item["working_state"] = json.loads(raw_state)
            except Exception:
                item["working_state"] = None
        else:
            item["working_state"] = None
        return item

    def save_conversation_working_state(
        self,
        conversation_id: str,
        state: dict[str, Any] | None,
        *,
        branch_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist compact derived conversation state. Raw message history remains authoritative.

        When ``branch_id`` is set, also snapshot onto that branch row so activate_branch
        can restore the correct lineage state.
        """
        current = self.get_conversation(conversation_id)
        if not current:
            raise KeyError(conversation_id)
        payload = json.dumps(state, ensure_ascii=False) if state else None
        active_branch = branch_id or current.get("active_branch_id")
        with self.connection() as db:
            db.execute(
                "UPDATE conversations SET working_state=?, updated_at=? WHERE id=?",
                (payload, utc_now(), conversation_id),
            )
            if active_branch:
                db.execute(
                    "UPDATE conversation_branches SET working_state=?, updated_at=? WHERE id=? AND conversation_id=?",
                    (payload, utc_now(), active_branch, conversation_id),
                )
        return self.get_conversation(conversation_id) or current

    def get_branch_working_state(self, conversation_id: str, branch_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT working_state FROM conversation_branches WHERE id=? AND conversation_id=?",
                (branch_id, conversation_id),
            ).fetchone()
        if not row:
            return None
        raw = row["working_state"] if "working_state" in row.keys() else None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def update_conversation(self, conversation_id: str, *, title: str | None = None, model_id: str | None = None, system_prompt_override: str | None = None, update_prompt: bool = False) -> dict[str, Any]:
        current = self.get_conversation(conversation_id)
        if not current:
            raise KeyError(conversation_id)
        values: dict[str, Any] = {"updated_at": utc_now()}
        if title is not None:
            values["title"] = title.strip()[:120] or "Nieuw gesprek"
        if model_id is not None:
            values["model_id"] = model_id
        if update_prompt:
            values["system_prompt_override"] = (system_prompt_override or "").strip() or None
        with self.connection() as db:
            db.execute("UPDATE conversations SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", [*values.values(), conversation_id])
        item = self.get_conversation(conversation_id) or {}
        with self.connection() as db:
            item["message_count"] = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
        return item

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.connection() as db:
            cursor = db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            db.execute("DELETE FROM client_request_dedup WHERE conversation_id=?", (conversation_id,))
            db.execute("DELETE FROM conversation_drafts WHERE conversation_id=?", (conversation_id,))
        return cursor.rowcount > 0

    def list_messages(self, conversation_id: str, *, branch_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM messages WHERE conversation_id = ?"
        params: list[Any] = [conversation_id]
        if branch_id:
            sql += " AND (branch_id = ? OR branch_id IS NULL)"
            params.append(branch_id)
        if active_only:
            sql += " AND COALESCE(is_active, 1) = 1"
        sql += " ORDER BY created_at, rowid"
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._message(row) for row in rows]

    def _message(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["is_active"] = bool(item.get("is_active", 1))
        raw_meta = item.pop("metadata_json", "{}")
        try:
            item["metadata"] = json.loads(raw_meta or "{}")
        except Exception:
            item["metadata"] = {}
        return item

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        client_request_id: str | None = None,
        parent_message_id: str | None = None,
        branch_id: str | None = None,
        revised_from_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": new_id("msg"),
            "conversation_id": conversation_id,
            "role": role,
            "content": content.strip(),
            "created_at": now,
            "client_request_id": client_request_id,
            "parent_message_id": parent_message_id,
            "branch_id": branch_id,
            "revised_from_id": revised_from_id,
            "is_active": 1,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        }
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
                raise KeyError(conversation_id)
            db.execute(
                """INSERT INTO messages(id, conversation_id, role, content, created_at, client_request_id, parent_message_id, branch_id, revised_from_id, is_active, metadata_json)
                   VALUES (:id, :conversation_id, :role, :content, :created_at, :client_request_id, :parent_message_id, :branch_id, :revised_from_id, :is_active, :metadata_json)""",
                item,
            )
            first_user_count = db.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user'",
                (conversation_id,),
            ).fetchone()[0]
            if role == "user" and first_user_count == 1:
                current_title = db.execute("SELECT title FROM conversations WHERE id=?", (conversation_id,)).fetchone()[0]
                if current_title == "Nieuw gesprek":
                    title = " ".join(content.strip().split())[:64]
                    db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return {
            "id": item["id"],
            "conversation_id": conversation_id,
            "role": role,
            "content": item["content"],
            "created_at": now,
            "client_request_id": client_request_id,
            "parent_message_id": parent_message_id,
            "branch_id": branch_id,
            "revised_from_id": revised_from_id,
            "is_active": True,
            "metadata": metadata or {},
        }

    def search_messages(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        needle = f"%{query}%"
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM messages
                   WHERE COALESCE(is_active,1)=1 AND content LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (needle, limit),
            ).fetchall()
        return [self._message(row) for row in rows]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return self._message(row) if row else None

    def deactivate_messages_after(self, conversation_id: str, message_id: str, *, branch_id: str | None = None) -> int:
        """Mark messages after a fork point inactive on the current line (keeps originals)."""
        target = self.get_message(message_id)
        if not target or target["conversation_id"] != conversation_id:
            raise KeyError(message_id)
        with self.connection() as db:
            sql = """UPDATE messages SET is_active=0
                      WHERE conversation_id=? AND created_at >= ? AND id != ? AND COALESCE(is_active,1)=1"""
            params: list[Any] = [conversation_id, target["created_at"], message_id]
            if branch_id:
                sql += " AND (branch_id=? OR branch_id IS NULL)"
                params.append(branch_id)
            # Also deactivate the edited message itself when revising.
            cursor = db.execute(sql, params)
            db.execute("UPDATE messages SET is_active=0 WHERE id=?", (message_id,))
        return int(cursor.rowcount or 0) + 1

    def create_branch(self, conversation_id: str, fork_message_id: str, *, title: str = "") -> dict[str, Any]:
        now = utc_now()
        branch_id = new_id("branch")
        with self.connection() as db:
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not conversation:
                raise KeyError(conversation_id)
            parent_branch = conversation["active_branch_id"] if "active_branch_id" in conversation.keys() else None
            # Snapshot current conversation working_state onto the parent branch before forking.
            parent_ws = conversation["working_state"] if "working_state" in conversation.keys() else None
            if parent_branch and parent_ws:
                db.execute(
                    "UPDATE conversation_branches SET working_state=?, updated_at=? WHERE id=? AND conversation_id=?",
                    (parent_ws, now, parent_branch, conversation_id),
                )
            db.execute(
                """INSERT INTO conversation_branches(id,conversation_id,parent_branch_id,fork_message_id,title,working_state,is_active,created_at,updated_at)
                   VALUES(?,?,?,?,?,NULL,1,?,?)""",
                (branch_id, conversation_id, parent_branch, fork_message_id, title or "Vertakking", now, now),
            )
            db.execute("UPDATE conversation_branches SET is_active=0 WHERE conversation_id=? AND id!=?", (conversation_id, branch_id))
            db.execute("UPDATE conversations SET active_branch_id=?, updated_at=? WHERE id=?", (branch_id, now, conversation_id))
            # New branch starts without inherited sibling constraints/state.
            db.execute("UPDATE conversations SET working_state=NULL WHERE id=?", (conversation_id,))
        return {
            "id": branch_id,
            "conversation_id": conversation_id,
            "parent_branch_id": parent_branch,
            "fork_message_id": fork_message_id,
            "title": title or "Vertakking",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

    def list_branches(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM conversation_branches WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["is_active"] = bool(item.get("is_active"))
            items.append(item)
        return items

    def activate_branch(self, conversation_id: str, branch_id: str) -> dict[str, Any]:
        """Switch active branch and reactivate messages for that lineage.

        Restores branch-scoped working_state onto the conversation row when a
        snapshot exists; otherwise clears conversation working_state so sibling
        constraints do not leak.
        """
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM conversation_branches WHERE id=? AND conversation_id=?",
                (branch_id, conversation_id),
            ).fetchone()
            if not row:
                raise KeyError(branch_id)
            branch = dict(row)
            # Snapshot the currently active branch's working_state before switching away.
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if conversation:
                current_active = conversation["active_branch_id"] if "active_branch_id" in conversation.keys() else None
                current_ws = conversation["working_state"] if "working_state" in conversation.keys() else None
                if current_active and current_active != branch_id and current_ws is not None:
                    db.execute(
                        "UPDATE conversation_branches SET working_state=?, updated_at=? WHERE id=? AND conversation_id=?",
                        (current_ws, now, current_active, conversation_id),
                    )
            fork_row = db.execute(
                "SELECT created_at, rowid FROM messages WHERE id=?",
                (branch["fork_message_id"],),
            ).fetchone()
            if not fork_row:
                raise KeyError(branch["fork_message_id"])
            fork_rowid = int(fork_row["rowid"])
            db.execute(
                "UPDATE messages SET is_active=0 WHERE conversation_id=? AND branch_id IS NOT NULL AND branch_id != ?",
                (conversation_id, branch_id),
            )
            db.execute(
                "UPDATE messages SET is_active=0 WHERE conversation_id=? AND branch_id IS NULL AND rowid > ?",
                (conversation_id, fork_rowid),
            )
            db.execute(
                "UPDATE messages SET is_active=1 WHERE conversation_id=? AND branch_id = ?",
                (conversation_id, branch_id),
            )
            db.execute(
                "UPDATE messages SET is_active=1 WHERE conversation_id=? AND branch_id IS NULL AND rowid <= ?",
                (conversation_id, fork_rowid),
            )
            db.execute(
                "UPDATE messages SET is_active=1, branch_id=? WHERE id=?",
                (branch_id, branch["fork_message_id"]),
            )
            db.execute("UPDATE conversation_branches SET is_active=0 WHERE conversation_id=?", (conversation_id,))
            db.execute(
                "UPDATE conversation_branches SET is_active=1, updated_at=? WHERE id=?",
                (now, branch_id),
            )
            restored_ws = branch.get("working_state")
            db.execute(
                "UPDATE conversations SET active_branch_id=?, working_state=?, updated_at=? WHERE id=?",
                (branch_id, restored_ws, now, conversation_id),
            )
        branch["is_active"] = True
        branch["updated_at"] = now
        if branch.get("working_state"):
            try:
                branch["working_state"] = json.loads(branch["working_state"]) if isinstance(branch["working_state"], str) else branch["working_state"]
            except Exception:
                branch["working_state"] = None
        return branch

    def save_draft(self, conversation_id: str, content: str, attachment_ids: list[str] | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO conversation_drafts(conversation_id, content, attachment_ids_json, updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(conversation_id) DO UPDATE SET content=excluded.content, attachment_ids_json=excluded.attachment_ids_json, updated_at=excluded.updated_at""",
                (conversation_id, content, json.dumps(attachment_ids or [], ensure_ascii=False), now),
            )
        return {"conversation_id": conversation_id, "content": content, "attachment_ids": attachment_ids or [], "updated_at": now}

    def get_draft(self, conversation_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM conversation_drafts WHERE conversation_id=?", (conversation_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["attachment_ids"] = json.loads(item.pop("attachment_ids_json") or "[]")
        except Exception:
            item["attachment_ids"] = []
        return item

    def get_deduped_response(self, conversation_id: str, client_request_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT response_json FROM client_request_dedup WHERE conversation_id=? AND client_request_id=?",
                (conversation_id, client_request_id),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["response_json"])
        except Exception:
            return None

    def store_deduped_response(self, conversation_id: str, client_request_id: str, response: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute(
                """INSERT OR REPLACE INTO client_request_dedup(conversation_id, client_request_id, response_json, created_at)
                   VALUES(?,?,?,?)""",
                (conversation_id, client_request_id, json.dumps(response, ensure_ascii=False), utc_now()),
            )

    def add_message_attachment(self, record: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": record.get("id") or new_id("matt"),
            "message_id": record["message_id"],
            "conversation_id": record["conversation_id"],
            "artifact_id": record.get("artifact_id"),
            "filename": record["filename"],
            "mime_type": record.get("mime_type") or "application/octet-stream",
            "size_bytes": int(record.get("size_bytes") or 0),
            "extract_status": record.get("extract_status") or "pending",
            "extract_error": record.get("extract_error"),
            "used_in_context": int(bool(record.get("used_in_context"))),
            "created_at": record.get("created_at") or utc_now(),
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO message_attachments(
                    id,message_id,conversation_id,artifact_id,filename,mime_type,size_bytes,extract_status,extract_error,used_in_context,created_at
                ) VALUES(:id,:message_id,:conversation_id,:artifact_id,:filename,:mime_type,:size_bytes,:extract_status,:extract_error,:used_in_context,:created_at)""",
                item,
            )
        item["used_in_context"] = bool(item["used_in_context"])
        return item

    def list_message_attachments(self, message_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM message_attachments WHERE message_id=? ORDER BY created_at", (message_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["used_in_context"] = bool(item.get("used_in_context"))
            items.append(item)
        return items

    def update_message_attachment(self, attachment_id: str, **values: Any) -> None:
        if "used_in_context" in values:
            values["used_in_context"] = int(bool(values["used_in_context"]))
        with self.connection() as db:
            db.execute(
                "UPDATE message_attachments SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                [*values.values(), attachment_id],
            )

    def active_profile(self) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM model_profiles WHERE is_active = 1 LIMIT 1").fetchone()
        if not row:
            return {"model_id": "", **DEFAULT_PROFILE, "is_active": False}
        item = dict(row)
        item["is_active"] = bool(item["is_active"])
        return item

    def profile_for(self, model_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM model_profiles WHERE model_id = ?", (model_id,)).fetchone()
        return dict(row) if row else {"model_id": model_id, **DEFAULT_PROFILE, "is_active": False}

    def save_profile(self, model_id: str, values: dict[str, Any], make_active: bool = True) -> dict[str, Any]:
        current = self.profile_for(model_id)
        profile = {**DEFAULT_PROFILE, **current, **values, "model_id": model_id, "updated_at": utc_now()}
        profile["is_active"] = int(make_active or bool(profile.get("is_active")))
        with self.connection() as db:
            if make_active:
                db.execute("UPDATE model_profiles SET is_active = 0")
            db.execute(
                """INSERT INTO model_profiles
                   (model_id, temperature, top_p, top_k, max_tokens, repeat_penalty, seed, system_prompt, is_active, updated_at)
                   VALUES (:model_id, :temperature, :top_p, :top_k, :max_tokens, :repeat_penalty, :seed, :system_prompt, :is_active, :updated_at)
                   ON CONFLICT(model_id) DO UPDATE SET
                     temperature=excluded.temperature, top_p=excluded.top_p, top_k=excluded.top_k,
                     max_tokens=excluded.max_tokens, repeat_penalty=excluded.repeat_penalty,
                     seed=excluded.seed, system_prompt=excluded.system_prompt,
                     is_active=excluded.is_active, updated_at=excluded.updated_at""",
                profile,
            )
        profile["is_active"] = bool(profile["is_active"])
        return profile

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_task(self, title: str, prompt: str, agent: str, priority: str, model_id: str | None) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": new_id("task"), "title": title.strip(), "prompt": prompt.strip(), "agent": agent.strip() or "Generalist",
            "priority": priority, "status": "queued", "model_id": model_id, "progress": 0, "result": None,
            "error": None, "created_at": now, "updated_at": now, "started_at": None, "finished_at": None,
            "control_state": "active", "plan_version": 1, "redirect_instruction": None,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO tasks(id, title, prompt, agent, priority, status, model_id, progress, result, error,
                   created_at, updated_at, started_at, finished_at, control_state, plan_version, redirect_instruction)
                   VALUES (:id, :title, :prompt, :agent, :priority, :status, :model_id, :progress, :result, :error,
                   :created_at, :updated_at, :started_at, :finished_at, :control_state, :plan_version, :redirect_instruction)""",
                item,
            )
        self.add_task_event(item["id"], "info", "Taak toegevoegd aan de lokale wachtrij.")
        return item

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            item = self._row(db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
        if not item:
            return None
        item.setdefault("control_state", "active")
        item.setdefault("plan_version", 1)
        item.setdefault("redirect_instruction", None)
        return item

    def set_task_control(
        self,
        task_id: str,
        *,
        control_state: str | None = None,
        plan_version: int | None = None,
        redirect_instruction: str | None = None,
        clear_redirect: bool = False,
    ) -> dict[str, Any] | None:
        current = self.get_task(task_id)
        if not current:
            return None
        values: dict[str, Any] = {"updated_at": utc_now()}
        if control_state is not None:
            values["control_state"] = control_state
        if plan_version is not None:
            values["plan_version"] = int(plan_version)
        if clear_redirect:
            values["redirect_instruction"] = None
        elif redirect_instruction is not None:
            values["redirect_instruction"] = redirect_instruction
        with self.connection() as db:
            db.execute(
                "UPDATE tasks SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                [*values.values(), task_id],
            )
        return self.get_task(task_id)

    def update_task(self, task_id: str, *, status: str, progress: int, result: str | None = None, error: str | None = None) -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as db:
            current = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if current and current["status"] == "cancelled" and status in {"running", "queued", "completed"}:
                # Annulering wint: geen late running/completed-commit.
                pass
            else:
                started = now if status == "running" else None
                finished = now if status in {"completed", "failed", "cancelled"} else None
                db.execute(
                    """UPDATE tasks SET status=?, progress=?, result=?, error=?, updated_at=?,
                       started_at=COALESCE(started_at, ?), finished_at=? WHERE id=?""",
                    (status, progress, result, error, now, started, finished, task_id),
                )
        return self.get_task(task_id)

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            if row["status"] not in {"queued", "failed"}:
                raise ValueError("Alleen wachtende of mislukte taken kunnen worden geannuleerd.")
        item = self.update_task(task_id, status="cancelled", progress=0)
        self.add_task_event(task_id, "warning", "Taak handmatig geannuleerd.")
        return item

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            if row["status"] not in {"failed", "cancelled", "completed"}:
                raise ValueError("Deze taak kan nu niet opnieuw worden gestart.")
            db.execute(
                "UPDATE tasks SET status='queued', progress=0, result=NULL, error=NULL, updated_at=?, started_at=NULL, finished_at=NULL WHERE id=?",
                (utc_now(), task_id),
            )
        self.add_task_event(task_id, "info", "Taak opnieuw in de wachtrij geplaatst.")
        return self.get_task(task_id)

    def recover_running_tasks(self) -> list[str]:
        with self.connection() as db:
            rows = db.execute("SELECT id FROM tasks WHERE status = 'running'").fetchall()
            db.execute(
                "UPDATE tasks SET status='queued', progress=0, error='Backend opnieuw gestart; taak veilig teruggezet.', updated_at=? WHERE status='running'",
                (utc_now(),),
            )
        for row in rows:
            self.add_task_event(row["id"], "warning", "Onderbroken taak na herstart teruggezet naar wachtrij.")
        return [row["id"] for row in rows]

    def add_task_event(self, task_id: str, level: str, message: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO task_events(task_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (task_id, level, message, utc_now()),
            )

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM task_events WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def recent_task_events(self, *, limit: int = 40) -> list[dict[str, Any]]:
        """Newest durable task log lines, joined with task agent/title for the Agents console."""
        with self.connection() as db:
            rows = db.execute(
                """SELECT te.id, te.task_id, te.level, te.message, te.created_at,
                          t.agent, t.title AS task_title
                   FROM task_events te
                   LEFT JOIN tasks t ON t.id = te.task_id
                   ORDER BY te.id DESC
                   LIMIT ?""",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def memory_stats(self) -> dict[str, Any]:
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0]
            collections = db.execute("SELECT COUNT(DISTINCT collection) FROM memories WHERE status='active'").fetchone()[0]
            historical = db.execute("SELECT COUNT(*) FROM memories WHERE status!='active'").fetchone()[0]
        return {"items": total, "collections": collections, "indexed": total, "historical": historical, "database_bytes": self.path.stat().st_size if self.path.exists() else 0}

    def list_memories(
        self,
        query: str = "",
        collection: str = "",
        limit: int = 100,
        *,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memories WHERE status='active' AND COALESCE(forgotten_marker,0)=0"
        params: list[Any] = []
        if query:
            sql += " AND (title LIKE ? OR content LIKE ? OR summary LIKE ? OR tags LIKE ?)"
            needle = f"%{query}%"
            params.extend([needle, needle, needle, needle])
        if collection:
            sql += " AND collection = ?"
            params.append(collection)
        if scope in {"session", "project", "global"}:
            sql += " AND COALESCE(scope,'project') = ?"
            params.append(scope)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._memory(row) for row in rows]

    @staticmethod
    def _memory_fts_query(query: str) -> str:
        cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in query)
        tokens = [token for token in cleaned.split() if len(token) > 1][:20]
        return " OR ".join(f'"{token}"' for token in tokens)

    def _ensure_memory_fts(self, db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                memory_id UNINDEXED,
                title,
                summary,
                content,
                tags,
                collection
            )
            """
        )
        indexed = db.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        active = db.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active' AND COALESCE(forgotten_marker,0)=0"
        ).fetchone()[0]
        if indexed == 0 and active:
            self._rebuild_memory_fts(db)

    def _rebuild_memory_fts(self, db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM memory_fts")
        rows = db.execute(
            """SELECT id, title, summary, content, tags, collection FROM memories
               WHERE status='active' AND COALESCE(forgotten_marker,0)=0"""
        ).fetchall()
        db.executemany(
            "INSERT INTO memory_fts(memory_id,title,summary,content,tags,collection) VALUES(?,?,?,?,?,?)",
            [(row["id"], row["title"], row["summary"], row["content"], row["tags"], row["collection"]) for row in rows],
        )

    def _upsert_memory_fts(self, db: sqlite3.Connection, item: dict[str, Any]) -> None:
        db.execute("DELETE FROM memory_fts WHERE memory_id=?", (item["id"],))
        forgotten = int(bool(item.get("forgotten_marker") or 0))
        status = str(item.get("status") or "active")
        if forgotten or status != "active":
            return
        tags = item.get("tags")
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)
        db.execute(
            "INSERT INTO memory_fts(memory_id,title,summary,content,tags,collection) VALUES(?,?,?,?,?,?)",
            (
                item["id"],
                item.get("title") or "",
                item.get("summary") or "",
                item.get("content") or "",
                tags or "[]",
                item.get("collection") or "",
            ),
        )

    def search_memory_candidates(
        self,
        query: str,
        limit: int = 50,
        *,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        fts_query = self._memory_fts_query(query)
        with self.connection() as db:
            self._ensure_memory_fts(db)
            rows: list[Any] = []
            try:
                if not fts_query:
                    raise sqlite3.OperationalError("empty fts query")
                sql = """
                    SELECT m.*, bm25(memory_fts) AS fts_rank
                    FROM memory_fts f
                    JOIN memories m ON m.id = f.memory_id
                    WHERE memory_fts MATCH ?
                      AND m.status='active' AND COALESCE(m.forgotten_marker,0)=0
                """
                params: list[Any] = [fts_query]
                if scope in {"session", "project", "global"}:
                    sql += " AND COALESCE(m.scope,'project') = ?"
                    params.append(scope)
                sql += " ORDER BY fts_rank LIMIT ?"
                params.append(max(1, int(limit)))
                rows = db.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if rows:
            return [self._memory(row) for row in rows]
        return self.list_memories(query=query, limit=limit, scope=scope)

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def save_memory(self, values: dict[str, Any], memory_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": memory_id or new_id("mem"),
            "title": values["title"].strip(),
            "content": values["content"].strip(),
            "summary": values.get("summary", "").strip(),
            "collection": values.get("collection", "Algemeen").strip() or "Algemeen",
            "tags": json.dumps(values.get("tags", []), ensure_ascii=False),
            "source": values.get("source", "Handmatig").strip() or "Handmatig",
            "memory_type": str(values.get("memory_type", "general") or "general"),
            "status": str(values.get("status", "active") or "active"),
            "confidence": max(0.0, min(1.0, float(values.get("confidence", 0.8)))),
            "importance": max(0.0, min(1.0, float(values.get("importance", 0.5)))),
            "supersedes": values.get("supersedes"),
            "superseded_by": values.get("superseded_by"),
            "last_verified_at": values.get("last_verified_at"),
            "origin_kind": str(values.get("origin_kind") or "user_fact"),
            "source_message_id": values.get("source_message_id"),
            "source_artifact_id": values.get("source_artifact_id"),
            "scope": str(values.get("scope") or "project"),
            "proposal_status": values.get("proposal_status"),
            "forgotten_marker": int(bool(values.get("forgotten_marker") or 0)),
            "content_version": int(values.get("content_version") or 1),
            "created_at": now,
            "updated_at": now,
        }
        with self.connection() as db:
            existing = db.execute("SELECT created_at FROM memories WHERE id = ?", (item["id"],)).fetchone()
            if existing:
                item["created_at"] = existing["created_at"]
                db.execute(
                    """UPDATE memories SET title=:title, content=:content, summary=:summary,
                       collection=:collection, tags=:tags, source=:source, memory_type=:memory_type,
                       status=:status, confidence=:confidence, importance=:importance, supersedes=:supersedes,
                       superseded_by=:superseded_by, last_verified_at=:last_verified_at,
                       origin_kind=:origin_kind, source_message_id=:source_message_id, source_artifact_id=:source_artifact_id,
                       scope=:scope, proposal_status=:proposal_status, forgotten_marker=:forgotten_marker,
                       content_version=:content_version, updated_at=:updated_at WHERE id=:id""",
                    item,
                )
            else:
                db.execute(
                    """INSERT INTO memories(id,title,content,summary,collection,tags,source,memory_type,status,confidence,importance,
                       supersedes,superseded_by,last_verified_at,origin_kind,source_message_id,source_artifact_id,scope,proposal_status,
                       forgotten_marker,content_version,created_at,updated_at)
                       VALUES (:id,:title,:content,:summary,:collection,:tags,:source,:memory_type,:status,:confidence,:importance,
                       :supersedes,:superseded_by,:last_verified_at,:origin_kind,:source_message_id,:source_artifact_id,:scope,:proposal_status,
                       :forgotten_marker,:content_version,:created_at,:updated_at)""",
                    item,
                )
            self._ensure_memory_fts(db)
            self._upsert_memory_fts(db, item)
        row = self.get_memory(item["id"])
        if not row:
            from execution_truth import make_persistence_result

            return {
                "id": item["id"],
                "persistence": make_persistence_result(
                    entity_type="memory",
                    requested_count=1,
                    inserted_ids=[item["id"]],
                    verified_ids=[],
                    error="memory_missing_after_write",
                    error_type="PersistenceVerificationError",
                ).to_dict(),
            }
        from execution_truth import verify_rows_exist

        persistence = verify_rows_exist(
            entity_type="memory",
            ids=[str(row["id"])],
            fetch_one=self.get_memory,
            required_fields=["id", "content", "title"],
        )
        return {**row, "persistence": persistence.to_dict()}

    def supersede_memory(self, memory_id: str, values: dict[str, Any]) -> dict[str, Any]:
        previous = self.get_memory(memory_id)
        if not previous:
            raise KeyError(memory_id)
        if previous.get("status") != "active":
            raise RuntimeError("Alleen een actieve memory kan worden vervangen.")
        replacement = self.save_memory({
            **values,
            "memory_type": values.get("memory_type", previous.get("memory_type", "general")),
            "confidence": values.get("confidence", previous.get("confidence", 0.8)),
            "importance": values.get("importance", previous.get("importance", 0.5)),
            "scope": values.get("scope") or previous.get("scope") or "project",
            "supersedes": memory_id,
            "status": "active",
            "last_verified_at": utc_now(),
        })
        with self.connection() as db:
            db.execute(
                "UPDATE memories SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
                (replacement["id"], utc_now(), memory_id),
            )
            db.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
        return self.get_memory(replacement["id"]) or replacement

    def memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            seed = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not seed:
                return []
            ids = {memory_id}
            cursor = seed
            while cursor and cursor["supersedes"] and cursor["supersedes"] not in ids:
                ids.add(cursor["supersedes"])
                cursor = db.execute("SELECT * FROM memories WHERE id=?", (cursor["supersedes"],)).fetchone()
            cursor = seed
            while cursor and cursor["superseded_by"] and cursor["superseded_by"] not in ids:
                ids.add(cursor["superseded_by"])
                cursor = db.execute("SELECT * FROM memories WHERE id=?", (cursor["superseded_by"],)).fetchone()
            rows = db.execute(
                f"SELECT * FROM memories WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY created_at",
                tuple(ids),
            ).fetchall()
        return [self._memory(row) for row in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self.connection() as db:
            try:
                self._ensure_memory_fts(db)
                db.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            except sqlite3.OperationalError:
                pass
            cursor = db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def forget_memory(self, memory_id: str) -> dict[str, Any]:
        """Mark memory forgotten without retaining content for retrieval."""
        current = self.get_memory(memory_id)
        if not current:
            raise KeyError(memory_id)
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """UPDATE memories SET status='forgotten', forgotten_marker=1,
                   content='[vergeten]', summary='[vergeten]', updated_at=? WHERE id=?""",
                (now, memory_id),
            )
            # Also mark supersession chain as forgotten for retrieval safety.
            db.execute(
                "UPDATE memories SET status='forgotten', forgotten_marker=1, updated_at=? WHERE supersedes=? OR superseded_by=? OR id=?",
                (now, memory_id, memory_id, memory_id),
            )
            db.execute(
                "DELETE FROM memory_fts WHERE memory_id=? OR memory_id IN (SELECT id FROM memories WHERE supersedes=? OR superseded_by=?)",
                (memory_id, memory_id, memory_id),
            )
        return self.get_memory(memory_id) or current

    def create_memory_proposal(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        source_message_id = values.get("source_message_id")
        origin_kind = values.get("origin_kind", "model_inference")
        # Idempotency: repeated scan of the same source message must not spam duplicates.
        if source_message_id:
            with self.connection() as db:
                existing = db.execute(
                    """SELECT * FROM memory_proposals
                       WHERE source_message_id=? AND origin_kind=? AND status='pending'
                       ORDER BY created_at DESC LIMIT 1""",
                    (source_message_id, origin_kind),
                ).fetchone()
            if existing:
                return dict(existing)
        item = {
            "id": new_id("mprop"),
            "memory_id": values.get("memory_id"),
            "title": values["title"].strip(),
            "content": values["content"].strip(),
            "summary": values.get("summary", "").strip(),
            "collection": values.get("collection", "Algemeen"),
            "origin_kind": origin_kind,
            "source_message_id": source_message_id,
            "source_conversation_id": values.get("source_conversation_id"),
            "status": "pending",
            "merge_into_id": values.get("merge_into_id"),
            "created_at": now,
            "updated_at": now,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO memory_proposals(
                    id,memory_id,title,content,summary,collection,origin_kind,source_message_id,source_conversation_id,status,merge_into_id,created_at,updated_at
                ) VALUES(:id,:memory_id,:title,:content,:summary,:collection,:origin_kind,:source_message_id,:source_conversation_id,:status,:merge_into_id,:created_at,:updated_at)""",
                item,
            )
        return item

    def list_memory_proposals(self, status: str = "pending") -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM memory_proposals WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]

    def decide_memory_proposal(self, proposal_id: str, *, action: str, edited: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM memory_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            raise KeyError(proposal_id)
        proposal = dict(row)
        if proposal["status"] != "pending":
            return {"proposal": proposal, "memory": self.get_memory(proposal["memory_id"]) if proposal.get("memory_id") else None}
        now = utc_now()
        if action == "reject":
            with self.connection() as db:
                db.execute("UPDATE memory_proposals SET status='rejected', updated_at=? WHERE id=?", (now, proposal_id))
            proposal["status"] = "rejected"
            return {"proposal": proposal, "memory": None}
        if action == "merge" and ((edited or {}).get("merge_into_id") or proposal.get("merge_into_id")):
            target_id = (edited or {}).get("merge_into_id") or proposal.get("merge_into_id")
            target = self.get_memory(str(target_id))
            if not target:
                raise KeyError(target_id)
            merged_content = f"{target['content'].rstrip()}\n\n{(edited or {}).get('content') or proposal['content']}".strip()
            memory = self.supersede_memory(target["id"], {
                "title": target["title"],
                "content": merged_content,
                "summary": (edited or {}).get("summary") or target.get("summary") or "",
                "collection": target["collection"],
                "tags": target.get("tags") or [],
                "source": "Memory-samenvoeging",
                "memory_type": target.get("memory_type") or "general",
                "origin_kind": proposal.get("origin_kind") or "user_fact",
            })
            with self.connection() as db:
                db.execute(
                    "UPDATE memory_proposals SET status='merged', memory_id=?, merge_into_id=?, updated_at=? WHERE id=?",
                    (memory["id"], target["id"], now, proposal_id),
                )
            proposal["status"] = "merged"
            return {"proposal": proposal, "memory": memory}
        # accept or edit -> create/update durable memory
        payload = {
            "title": (edited or {}).get("title") or proposal["title"],
            "content": (edited or {}).get("content") or proposal["content"],
            "summary": (edited or {}).get("summary") or proposal.get("summary") or "",
            "collection": (edited or {}).get("collection") or proposal.get("collection") or "Algemeen",
            "tags": (edited or {}).get("tags") or ["voorstel"],
            "source": "Geaccepteerd geheugenvoorstel",
            "memory_type": (edited or {}).get("memory_type") or "general",
            "origin_kind": proposal.get("origin_kind") or "user_fact",
            "source_message_id": proposal.get("source_message_id"),
            "status": "active",
        }
        if proposal.get("memory_id") and action == "edit":
            memory = self.supersede_memory(proposal["memory_id"], payload)
        else:
            memory = self.save_memory(payload)
        with self.connection() as db:
            db.execute(
                "UPDATE memory_proposals SET status=?, memory_id=?, updated_at=? WHERE id=?",
                ("accepted" if action != "edit" else "edited", memory["id"], now, proposal_id),
            )
        proposal["status"] = "accepted" if action != "edit" else "edited"
        return {"proposal": proposal, "memory": memory}

    def preview_forget_scope(self, *, conversation_id: str | None = None, memory_id: str | None = None) -> dict[str, Any]:
        scope: dict[str, Any] = {"conversations": [], "memories": [], "knowledge_uris": [], "message_count": 0}
        if conversation_id:
            conv = self.get_conversation(conversation_id)
            if conv:
                scope["conversations"].append(conv["id"])
                scope["message_count"] = len(self.list_messages(conversation_id, active_only=False))
                scope["knowledge_uris"].append(f"conversation:{conversation_id}")
        if memory_id:
            history = self.memory_history(memory_id)
            scope["memories"] = [item["id"] for item in history] or [memory_id]
        return scope

    def import_memories(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.save_memory(item, item.get("id")) for item in items]

    def collections(self) -> list[str]:
        with self.connection() as db:
            rows = db.execute("SELECT DISTINCT collection FROM memories ORDER BY collection").fetchall()
        return [row["collection"] for row in rows]

    def list_brain_nodes(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM brain_nodes ORDER BY created_at").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags"])
            result.append(item)
        return result

    def list_brain_links(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM brain_links ORDER BY source_id, target_id").fetchall()
        return [dict(row) for row in rows]

    def create_brain_node(
        self,
        label: str,
        kind: str,
        description: str,
        tags: list[str],
        connect_to: str | None,
        *,
        pos_x: float | None = None,
        pos_y: float | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": new_id("node"), "label": label.strip(), "kind": kind, "description": description.strip(),
            "tags": json.dumps(tags, ensure_ascii=False), "source": "Handmatig", "created_at": now, "updated_at": now,
            "pos_x": pos_x, "pos_y": pos_y,
        }
        with self.connection() as db:
            db.execute(
                """INSERT INTO brain_nodes(id, label, kind, description, tags, source, created_at, updated_at, pos_x, pos_y)
                   VALUES (:id, :label, :kind, :description, :tags, :source, :created_at, :updated_at, :pos_x, :pos_y)""",
                item,
            )
            if connect_to and db.execute("SELECT 1 FROM brain_nodes WHERE id = ?", (connect_to,)).fetchone():
                db.execute(
                    "INSERT INTO brain_links(source_id, target_id, relation) VALUES (?, ?, 'gerelateerd aan')",
                    (item["id"], connect_to),
                )
        result = dict(item)
        result["tags"] = tags
        return result

    def update_brain_node(
        self,
        node_id: str,
        *,
        label: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        pos_x: float | None = None,
        pos_y: float | None = None,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM brain_nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            if label is not None:
                item["label"] = label.strip()
            if description is not None:
                item["description"] = description.strip()
            if tags is not None:
                item["tags"] = json.dumps(tags, ensure_ascii=False)
            if kind is not None:
                item["kind"] = kind
            if pos_x is not None:
                item["pos_x"] = pos_x
            if pos_y is not None:
                item["pos_y"] = pos_y
            item["updated_at"] = utc_now()
            db.execute(
                """UPDATE brain_nodes
                   SET label=:label, description=:description, tags=:tags, kind=:kind,
                       pos_x=:pos_x, pos_y=:pos_y, updated_at=:updated_at
                   WHERE id=:id""",
                {**item, "id": node_id},
            )
        item["tags"] = json.loads(item["tags"]) if isinstance(item["tags"], str) else item["tags"]
        return item

    def delete_brain_node(self, node_id: str) -> bool:
        if str(node_id).startswith("core_"):
            return False
        with self.connection() as db:
            row = db.execute("SELECT source FROM brain_nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return False
            # Protect seeded architecture cores even if id naming differs.
            if str(row["source"]).lower() in {"systeem", "system"} and str(node_id).startswith("core_"):
                return False
            db.execute("DELETE FROM brain_links WHERE source_id = ? OR target_id = ?", (node_id, node_id))
            db.execute("DELETE FROM brain_nodes WHERE id = ?", (node_id,))
        return True

    def add_brain_link(self, source_id: str, target_id: str, relation: str = "gerelateerd aan") -> dict[str, Any] | None:
        if source_id == target_id:
            return None
        with self.connection() as db:
            ok_source = db.execute("SELECT 1 FROM brain_nodes WHERE id = ?", (source_id,)).fetchone()
            ok_target = db.execute("SELECT 1 FROM brain_nodes WHERE id = ?", (target_id,)).fetchone()
            if not ok_source or not ok_target:
                return None
            existing = db.execute(
                "SELECT 1 FROM brain_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            ).fetchone()
            if existing:
                return None
            db.execute(
                "INSERT INTO brain_links(source_id, target_id, relation) VALUES (?, ?, ?)",
                (source_id, target_id, relation.strip() or "gerelateerd aan"),
            )
        return {"source_id": source_id, "target_id": target_id, "relation": relation.strip() or "gerelateerd aan"}

    def update_brain_link(self, source_id: str, target_id: str, relation: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT source_id, target_id, relation FROM brain_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            ).fetchone()
            if not row:
                return None
            cleaned = relation.strip() or "gerelateerd aan"
            db.execute(
                "UPDATE brain_links SET relation = ? WHERE source_id = ? AND target_id = ?",
                (cleaned, source_id, target_id),
            )
        return {"source_id": source_id, "target_id": target_id, "relation": cleaned}

    def delete_brain_link(self, source_id: str, target_id: str) -> bool:
        with self.connection() as db:
            cur = db.execute(
                "DELETE FROM brain_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            )
            return cur.rowcount > 0

    def list_brain_layout(self, view_id: str = "default") -> dict[str, Any]:
        with self.connection() as db:
            positions = db.execute(
                "SELECT entity_id, pos_x, pos_y, pinned, updated_at FROM brain_layout_positions WHERE view_id = ? ORDER BY entity_id",
                (view_id,),
            ).fetchall()
            viewport = db.execute(
                "SELECT x, y, zoom, updated_at FROM brain_viewports WHERE view_id = ?",
                (view_id,),
            ).fetchone()
        return {
            "view_id": view_id,
            "viewport": dict(viewport) if viewport else {"x": 0.0, "y": 0.0, "zoom": 1.0, "updated_at": None},
            "positions": [
                {
                    "entity_id": row["entity_id"],
                    "pos_x": row["pos_x"],
                    "pos_y": row["pos_y"],
                    "pinned": bool(row["pinned"]),
                    "updated_at": row["updated_at"],
                }
                for row in positions
            ],
        }

    def upsert_brain_layout_position(
        self,
        entity_id: str,
        *,
        pos_x: float,
        pos_y: float,
        pinned: bool | None = None,
        view_id: str = "default",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            existing = db.execute(
                "SELECT pinned FROM brain_layout_positions WHERE view_id = ? AND entity_id = ?",
                (view_id, entity_id),
            ).fetchone()
            pin_value = int(bool(pinned)) if pinned is not None else (int(existing["pinned"]) if existing else 0)
            db.execute(
                """
                INSERT INTO brain_layout_positions(view_id, entity_id, pos_x, pos_y, pinned, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(view_id, entity_id) DO UPDATE SET
                    pos_x = excluded.pos_x,
                    pos_y = excluded.pos_y,
                    pinned = excluded.pinned,
                    updated_at = excluded.updated_at
                """,
                (view_id, entity_id, float(pos_x), float(pos_y), pin_value, now),
            )
        return {
            "view_id": view_id,
            "entity_id": entity_id,
            "pos_x": float(pos_x),
            "pos_y": float(pos_y),
            "pinned": bool(pin_value),
            "updated_at": now,
        }

    def save_brain_viewport(self, *, x: float, y: float, zoom: float, view_id: str = "default") -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO brain_viewports(view_id, x, y, zoom, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(view_id) DO UPDATE SET
                    x = excluded.x, y = excluded.y, zoom = excluded.zoom, updated_at = excluded.updated_at
                """,
                (view_id, float(x), float(y), float(zoom), now),
            )
        return {"view_id": view_id, "x": float(x), "y": float(y), "zoom": float(zoom), "updated_at": now}

    def count_memories(self, *, active_only: bool = True) -> int:
        with self.connection() as db:
            if active_only:
                return int(db.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0])
            return int(db.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def count_conversations(self) -> int:
        with self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])

    def count_tasks(self) -> int:
        with self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])

    def backup(self, destination: Path) -> None:
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.path, timeout=10)
        target = sqlite3.connect(destination, timeout=10)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def storage_info(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

