"""SQLite persistence for the Media Intelligence subsystem.

Uses a dedicated `media_schema_migrations` ledger (Gen2 pattern) so platform
integer migration IDs cannot mask Media tables.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from media.models import AutonomyLevel, ProjectStage


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def clamp_limit(limit: int, *, default: int = 50, maximum: int = 200) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


class MediaStore:
    """Owns Media tables on the shared HADES SQLite database file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 8000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _record_migration(self, db: sqlite3.Connection, version: int, now: str) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS media_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT OR IGNORE INTO media_schema_migrations(version, applied_at) VALUES(?, ?)",
            (int(version), now),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        # Use high non-colliding namespace for shared ledger visibility.
        shared_version = 9000 + int(version)
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (shared_version, now),
        )

    def initialize(self) -> None:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS media_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in db.execute("SELECT version FROM media_schema_migrations").fetchall()
            }
            if 1 not in applied:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS media_channels (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        niche TEXT NOT NULL DEFAULT '',
                        sub_niches_json TEXT NOT NULL DEFAULT '[]',
                        language TEXT NOT NULL DEFAULT 'en',
                        target_region TEXT NOT NULL DEFAULT '',
                        target_audience TEXT NOT NULL DEFAULT '',
                        platforms_json TEXT NOT NULL DEFAULT '[]',
                        content_formats_json TEXT NOT NULL DEFAULT '[]',
                        posting_frequency TEXT NOT NULL DEFAULT '1/day',
                        schedule_windows_json TEXT NOT NULL DEFAULT '[]',
                        timezone TEXT NOT NULL DEFAULT 'UTC',
                        autonomy_level TEXT NOT NULL DEFAULT 'OFF',
                        voice_persona_json TEXT NOT NULL DEFAULT '{}',
                        visual_persona_json TEXT NOT NULL DEFAULT '{}',
                        tone TEXT NOT NULL DEFAULT '',
                        content_length TEXT NOT NULL DEFAULT 'short',
                        preferred_topics_json TEXT NOT NULL DEFAULT '[]',
                        excluded_topics_json TEXT NOT NULL DEFAULT '[]',
                        fact_strictness TEXT NOT NULL DEFAULT 'high',
                        cta_strategy TEXT NOT NULL DEFAULT '',
                        music_policy TEXT NOT NULL DEFAULT 'generated_or_licensed',
                        asset_policy TEXT NOT NULL DEFAULT 'generated_or_user',
                        ai_disclosure_policy TEXT NOT NULL DEFAULT 'disclose',
                        budget_json TEXT NOT NULL DEFAULT '{}',
                        experiment_policy_json TEXT NOT NULL DEFAULT '{}',
                        account_mappings_json TEXT NOT NULL DEFAULT '{}',
                        max_projects_per_day INTEGER NOT NULL DEFAULT 3,
                        max_published_per_day INTEGER NOT NULL DEFAULT 3,
                        max_llm_calls INTEGER NOT NULL DEFAULT 200,
                        max_image_generations INTEGER NOT NULL DEFAULT 40,
                        max_video_generations INTEGER NOT NULL DEFAULT 5,
                        max_voice_generations INTEGER NOT NULL DEFAULT 40,
                        max_retries INTEGER NOT NULL DEFAULT 3,
                        exploration_rate REAL NOT NULL DEFAULT 0.2,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_channels_updated ON media_channels(updated_at DESC);

                    CREATE TABLE IF NOT EXISTS media_accounts (
                        id TEXT PRIMARY KEY,
                        platform TEXT NOT NULL,
                        external_account_id TEXT NOT NULL DEFAULT '',
                        display_name TEXT NOT NULL DEFAULT '',
                        auth_status TEXT NOT NULL DEFAULT 'AUTH_REQUIRED',
                        scopes_json TEXT NOT NULL DEFAULT '[]',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        secret_ref TEXT NOT NULL DEFAULT '',
                        last_verified_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(platform, external_account_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_accounts_platform ON media_accounts(platform);

                    CREATE TABLE IF NOT EXISTS media_projects (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        title TEXT NOT NULL DEFAULT '',
                        topic TEXT NOT NULL DEFAULT '',
                        stage TEXT NOT NULL DEFAULT 'CREATED',
                        platforms_json TEXT NOT NULL DEFAULT '[]',
                        autonomy_level TEXT NOT NULL DEFAULT 'OFF',
                        progress REAL NOT NULL DEFAULT 0,
                        stage_checkpoint_json TEXT NOT NULL DEFAULT '{}',
                        artifacts_json TEXT NOT NULL DEFAULT '{}',
                        content_dna_json TEXT NOT NULL DEFAULT '{}',
                        error TEXT,
                        lease_owner TEXT,
                        lease_until TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(channel_id) REFERENCES media_channels(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_projects_channel ON media_projects(channel_id, updated_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_media_projects_stage ON media_projects(stage, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS media_project_events (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        detail TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(project_id) REFERENCES media_projects(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_project_events_project ON media_project_events(project_id, created_at);

                    CREATE TABLE IF NOT EXISTS media_sources (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        project_id TEXT,
                        source_kind TEXT NOT NULL,
                        uri TEXT NOT NULL DEFAULT '',
                        content_hash TEXT NOT NULL DEFAULT '',
                        text_excerpt TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_sources_hash ON media_sources(content_hash);
                    CREATE INDEX IF NOT EXISTS idx_media_sources_project ON media_sources(project_id);

                    CREATE TABLE IF NOT EXISTS media_transcripts (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        language TEXT NOT NULL DEFAULT '',
                        confidence REAL,
                        segments_json TEXT NOT NULL DEFAULT '[]',
                        words_json TEXT NOT NULL DEFAULT '[]',
                        full_text TEXT NOT NULL DEFAULT '',
                        provider_config_hash TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        UNIQUE(content_hash, provider, provider_config_hash),
                        FOREIGN KEY(source_id) REFERENCES media_sources(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_transcripts_source ON media_transcripts(source_id);

                    CREATE TABLE IF NOT EXISTS media_patterns (
                        id TEXT PRIMARY KEY,
                        source_id TEXT,
                        project_id TEXT,
                        pattern_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_trend_signals (
                        id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        platform TEXT NOT NULL DEFAULT '',
                        topic TEXT NOT NULL,
                        keyword TEXT NOT NULL DEFAULT '',
                        region TEXT NOT NULL DEFAULT '',
                        language TEXT NOT NULL DEFAULT '',
                        observed_at TEXT NOT NULL,
                        rank REAL,
                        views REAL,
                        velocity REAL,
                        engagement REAL,
                        growth REAL,
                        freshness REAL,
                        competition REAL,
                        saturation REAL,
                        source_ref TEXT NOT NULL DEFAULT '',
                        confidence REAL,
                        raw_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_trend_signals_topic ON media_trend_signals(topic, observed_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_media_trend_signals_platform ON media_trend_signals(platform, observed_at DESC);

                    CREATE TABLE IF NOT EXISTS media_trends (
                        id TEXT PRIMARY KEY,
                        topic_key TEXT NOT NULL UNIQUE,
                        display_topic TEXT NOT NULL,
                        evidence_json TEXT NOT NULL DEFAULT '[]',
                        scores_json TEXT NOT NULL DEFAULT '{}',
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_opportunities (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        trend_id TEXT,
                        score REAL NOT NULL DEFAULT 0,
                        components_json TEXT NOT NULL DEFAULT '{}',
                        explanation TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'open',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_opportunities_score ON media_opportunities(score DESC, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS media_ideas (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        opportunity_id TEXT,
                        project_id TEXT,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        rank_score REAL NOT NULL DEFAULT 0,
                        rejected INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_research_claims (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        evidence TEXT NOT NULL DEFAULT '',
                        source_ref TEXT NOT NULL DEFAULT '',
                        confidence REAL,
                        contradictions_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_research_claims_project ON media_research_claims(project_id);

                    CREATE TABLE IF NOT EXISTS media_hypotheses (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_scripts (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        body TEXT NOT NULL DEFAULT '',
                        critiques_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        UNIQUE(project_id, version)
                    );

                    CREATE TABLE IF NOT EXISTS media_storyboards (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        scenes_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        UNIQUE(project_id, version)
                    );

                    CREATE TABLE IF NOT EXISTS media_assets (
                        id TEXT PRIMARY KEY,
                        project_id TEXT,
                        channel_id TEXT,
                        asset_type TEXT NOT NULL,
                        origin TEXT NOT NULL DEFAULT '',
                        source_ref TEXT NOT NULL DEFAULT '',
                        provider TEXT NOT NULL DEFAULT '',
                        model TEXT NOT NULL DEFAULT '',
                        license_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                        content_hash TEXT NOT NULL DEFAULT '',
                        prompt_hash TEXT NOT NULL DEFAULT '',
                        storage_path TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_assets_project ON media_assets(project_id);
                    CREATE INDEX IF NOT EXISTS idx_media_assets_hash ON media_assets(content_hash);

                    CREATE TABLE IF NOT EXISTS media_platform_variants (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        format_key TEXT NOT NULL DEFAULT '',
                        render_asset_id TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(project_id, platform, format_key)
                    );

                    CREATE TABLE IF NOT EXISTS media_publish_jobs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        variant_id TEXT,
                        platform TEXT NOT NULL,
                        account_id TEXT,
                        scheduled_for TEXT,
                        approval_state TEXT NOT NULL DEFAULT 'pending',
                        platform_consent_state TEXT NOT NULL DEFAULT 'not_required',
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        last_attempt_at TEXT,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        external_upload_id TEXT,
                        external_post_id TEXT,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        error TEXT,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_publish_jobs_status ON media_publish_jobs(status, scheduled_for);
                    CREATE INDEX IF NOT EXISTS idx_media_publish_jobs_project ON media_publish_jobs(project_id);

                    CREATE TABLE IF NOT EXISTS media_publish_records (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        external_post_id TEXT,
                        status TEXT NOT NULL,
                        raw_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(job_id) REFERENCES media_publish_jobs(id)
                    );

                    CREATE TABLE IF NOT EXISTS media_metric_snapshots (
                        id TEXT PRIMARY KEY,
                        project_id TEXT,
                        platform TEXT NOT NULL,
                        external_post_id TEXT NOT NULL,
                        captured_at TEXT NOT NULL,
                        hours_since_publish REAL,
                        metrics_json TEXT NOT NULL DEFAULT '{}',
                        raw_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_metrics_post ON media_metric_snapshots(platform, external_post_id, captured_at);

                    CREATE TABLE IF NOT EXISTS media_experiments (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        name TEXT NOT NULL,
                        hypothesis TEXT NOT NULL DEFAULT '',
                        control_json TEXT NOT NULL DEFAULT '{}',
                        variant_json TEXT NOT NULL DEFAULT '{}',
                        primary_metric TEXT NOT NULL DEFAULT '',
                        min_samples INTEGER NOT NULL DEFAULT 20,
                        status TEXT NOT NULL DEFAULT 'active',
                        results_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_learning_findings (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        scope TEXT NOT NULL DEFAULT 'CHANNEL',
                        platform TEXT NOT NULL DEFAULT '',
                        format_key TEXT NOT NULL DEFAULT '',
                        niche TEXT NOT NULL DEFAULT '',
                        finding TEXT NOT NULL,
                        sample_size INTEGER NOT NULL DEFAULT 0,
                        effect_size REAL,
                        confidence TEXT NOT NULL DEFAULT 'low',
                        recommendation TEXT NOT NULL DEFAULT '',
                        evidence_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_learning_channel ON media_learning_findings(channel_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS media_policy_history (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        policy_key TEXT NOT NULL,
                        old_value_json TEXT NOT NULL DEFAULT '{}',
                        new_value_json TEXT NOT NULL DEFAULT '{}',
                        reason TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS media_scheduler_leases (
                        job_key TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        lease_until TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                self._record_migration(db, 1, now)

    # ---- channels ----
    def create_channel(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        channel_id = new_id("mch")
        record = {
            "id": channel_id,
            "name": payload["name"],
            "description": payload.get("description", ""),
            "niche": payload.get("niche", ""),
            "sub_niches": payload.get("sub_niches", []),
            "language": payload.get("language", "en"),
            "target_region": payload.get("target_region", ""),
            "target_audience": payload.get("target_audience", ""),
            "platforms": payload.get("platforms", []),
            "content_formats": payload.get("content_formats", []),
            "posting_frequency": payload.get("posting_frequency", "1/day"),
            "schedule_windows": payload.get("schedule_windows", []),
            "timezone": payload.get("timezone", "UTC"),
            "autonomy_level": payload.get("autonomy_level", AutonomyLevel.OFF.value),
            "voice_persona": payload.get("voice_persona", {}),
            "visual_persona": payload.get("visual_persona", {}),
            "tone": payload.get("tone", ""),
            "content_length": payload.get("content_length", "short"),
            "preferred_topics": payload.get("preferred_topics", []),
            "excluded_topics": payload.get("excluded_topics", []),
            "fact_strictness": payload.get("fact_strictness", "high"),
            "cta_strategy": payload.get("cta_strategy", ""),
            "music_policy": payload.get("music_policy", "generated_or_licensed"),
            "asset_policy": payload.get("asset_policy", "generated_or_user"),
            "ai_disclosure_policy": payload.get("ai_disclosure_policy", "disclose"),
            "budget": payload.get("budget", {}),
            "experiment_policy": payload.get("experiment_policy", {}),
            "account_mappings": payload.get("account_mappings", {}),
            "max_projects_per_day": int(payload.get("max_projects_per_day", 3)),
            "max_published_per_day": int(payload.get("max_published_per_day", 3)),
            "max_llm_calls": int(payload.get("max_llm_calls", 200)),
            "max_image_generations": int(payload.get("max_image_generations", 40)),
            "max_video_generations": int(payload.get("max_video_generations", 5)),
            "max_voice_generations": int(payload.get("max_voice_generations", 40)),
            "max_retries": int(payload.get("max_retries", 3)),
            "exploration_rate": float(payload.get("exploration_rate", 0.2)),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "created_at": now,
            "updated_at": now,
        }
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_channels(
                    id,name,description,niche,sub_niches_json,language,target_region,target_audience,
                    platforms_json,content_formats_json,posting_frequency,schedule_windows_json,timezone,
                    autonomy_level,voice_persona_json,visual_persona_json,tone,content_length,
                    preferred_topics_json,excluded_topics_json,fact_strictness,cta_strategy,music_policy,
                    asset_policy,ai_disclosure_policy,budget_json,experiment_policy_json,account_mappings_json,
                    max_projects_per_day,max_published_per_day,max_llm_calls,max_image_generations,
                    max_video_generations,max_voice_generations,max_retries,exploration_rate,enabled,
                    created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record["id"], record["name"], record["description"], record["niche"],
                    _dumps(record["sub_niches"]), record["language"], record["target_region"],
                    record["target_audience"], _dumps(record["platforms"]), _dumps(record["content_formats"]),
                    record["posting_frequency"], _dumps(record["schedule_windows"]), record["timezone"],
                    record["autonomy_level"], _dumps(record["voice_persona"]), _dumps(record["visual_persona"]),
                    record["tone"], record["content_length"], _dumps(record["preferred_topics"]),
                    _dumps(record["excluded_topics"]), record["fact_strictness"], record["cta_strategy"],
                    record["music_policy"], record["asset_policy"], record["ai_disclosure_policy"],
                    _dumps(record["budget"]), _dumps(record["experiment_policy"]),
                    _dumps(record["account_mappings"]), record["max_projects_per_day"],
                    record["max_published_per_day"], record["max_llm_calls"], record["max_image_generations"],
                    record["max_video_generations"], record["max_voice_generations"], record["max_retries"],
                    record["exploration_rate"], record["enabled"], record["created_at"], record["updated_at"],
                ),
            )
        return self.get_channel(channel_id)  # type: ignore[return-value]

    def _hydrate_channel(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data["id"],
            "name": data["name"],
            "description": data.get("description", ""),
            "niche": data.get("niche", ""),
            "sub_niches": _loads(data.get("sub_niches_json"), []),
            "language": data.get("language", "en"),
            "target_region": data.get("target_region", ""),
            "target_audience": data.get("target_audience", ""),
            "platforms": _loads(data.get("platforms_json"), []),
            "content_formats": _loads(data.get("content_formats_json"), []),
            "posting_frequency": data.get("posting_frequency", "1/day"),
            "schedule_windows": _loads(data.get("schedule_windows_json"), []),
            "timezone": data.get("timezone", "UTC"),
            "autonomy_level": data.get("autonomy_level", "OFF"),
            "voice_persona": _loads(data.get("voice_persona_json"), {}),
            "visual_persona": _loads(data.get("visual_persona_json"), {}),
            "tone": data.get("tone", ""),
            "content_length": data.get("content_length", "short"),
            "preferred_topics": _loads(data.get("preferred_topics_json"), []),
            "excluded_topics": _loads(data.get("excluded_topics_json"), []),
            "fact_strictness": data.get("fact_strictness", "high"),
            "cta_strategy": data.get("cta_strategy", ""),
            "music_policy": data.get("music_policy", "generated_or_licensed"),
            "asset_policy": data.get("asset_policy", "generated_or_user"),
            "ai_disclosure_policy": data.get("ai_disclosure_policy", "disclose"),
            "budget": _loads(data.get("budget_json"), {}),
            "experiment_policy": _loads(data.get("experiment_policy_json"), {}),
            "account_mappings": _loads(data.get("account_mappings_json"), {}),
            "max_projects_per_day": data.get("max_projects_per_day", 3),
            "max_published_per_day": data.get("max_published_per_day", 3),
            "max_llm_calls": data.get("max_llm_calls", 200),
            "max_image_generations": data.get("max_image_generations", 40),
            "max_video_generations": data.get("max_video_generations", 5),
            "max_voice_generations": data.get("max_voice_generations", 40),
            "max_retries": data.get("max_retries", 3),
            "exploration_rate": data.get("exploration_rate", 0.2),
            "enabled": bool(data.get("enabled", 1)),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_channels WHERE id=?", (channel_id,)).fetchone()
        return self._hydrate_channel(row) if row else None

    def list_channels(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        offset = max(0, int(offset))
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM media_channels ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._hydrate_channel(row) for row in rows]

    def update_channel(self, channel_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_channel(channel_id)
        if not current:
            return None
        merged = {**current, **{k: v for k, v in updates.items() if v is not None}}
        merged["updated_at"] = utc_now()
        with self.connection() as db:
            db.execute(
                """
                UPDATE media_channels SET
                    name=?, description=?, niche=?, sub_niches_json=?, language=?, target_region=?,
                    target_audience=?, platforms_json=?, content_formats_json=?, posting_frequency=?,
                    schedule_windows_json=?, timezone=?, autonomy_level=?, voice_persona_json=?,
                    visual_persona_json=?, tone=?, content_length=?, preferred_topics_json=?,
                    excluded_topics_json=?, fact_strictness=?, cta_strategy=?, music_policy=?,
                    asset_policy=?, ai_disclosure_policy=?, budget_json=?, experiment_policy_json=?,
                    account_mappings_json=?, max_projects_per_day=?, max_published_per_day=?,
                    max_llm_calls=?, max_image_generations=?, max_video_generations=?,
                    max_voice_generations=?, max_retries=?, exploration_rate=?, enabled=?, updated_at=?
                WHERE id=?
                """,
                (
                    merged["name"], merged["description"], merged["niche"], _dumps(merged["sub_niches"]),
                    merged["language"], merged["target_region"], merged["target_audience"],
                    _dumps(merged["platforms"]), _dumps(merged["content_formats"]), merged["posting_frequency"],
                    _dumps(merged["schedule_windows"]), merged["timezone"], merged["autonomy_level"],
                    _dumps(merged["voice_persona"]), _dumps(merged["visual_persona"]), merged["tone"],
                    merged["content_length"], _dumps(merged["preferred_topics"]), _dumps(merged["excluded_topics"]),
                    merged["fact_strictness"], merged["cta_strategy"], merged["music_policy"],
                    merged["asset_policy"], merged["ai_disclosure_policy"], _dumps(merged["budget"]),
                    _dumps(merged["experiment_policy"]), _dumps(merged["account_mappings"]),
                    int(merged["max_projects_per_day"]), int(merged["max_published_per_day"]),
                    int(merged["max_llm_calls"]), int(merged["max_image_generations"]),
                    int(merged["max_video_generations"]), int(merged["max_voice_generations"]),
                    int(merged["max_retries"]), float(merged["exploration_rate"]),
                    1 if merged.get("enabled", True) else 0, merged["updated_at"], channel_id,
                ),
            )
        return self.get_channel(channel_id)

    def count_channels(self) -> int:
        with self.connection() as db:
            row = db.execute("SELECT COUNT(*) AS c FROM media_channels").fetchone()
        return int(row["c"] if row else 0)

    # ---- projects ----
    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        project_id = new_id("mprj")
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_projects(
                    id,channel_id,title,topic,stage,platforms_json,autonomy_level,progress,
                    stage_checkpoint_json,artifacts_json,content_dna_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    payload["channel_id"],
                    payload.get("title", "") or payload.get("topic", "") or "Untitled project",
                    payload.get("topic", ""),
                    ProjectStage.CREATED.value,
                    _dumps(payload.get("platforms", [])),
                    payload.get("autonomy_level", AutonomyLevel.OFF.value),
                    0.0,
                    _dumps({}),
                    _dumps(payload.get("artifacts", {})),
                    _dumps({}),
                    now,
                    now,
                ),
            )
        return self.get_project(project_id)  # type: ignore[return-value]

    def _hydrate_project(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data["id"],
            "channel_id": data["channel_id"],
            "title": data.get("title", ""),
            "topic": data.get("topic", ""),
            "stage": data.get("stage", ProjectStage.CREATED.value),
            "platforms": _loads(data.get("platforms_json"), []),
            "autonomy_level": data.get("autonomy_level", "OFF"),
            "progress": float(data.get("progress") or 0),
            "stage_checkpoint": _loads(data.get("stage_checkpoint_json"), {}),
            "artifacts": _loads(data.get("artifacts_json"), {}),
            "content_dna": _loads(data.get("content_dna_json"), {}),
            "error": data.get("error"),
            "lease_owner": data.get("lease_owner"),
            "lease_until": data.get("lease_until"),
            "cancel_requested": bool(data.get("cancel_requested", 0)),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_projects WHERE id=?", (project_id,)).fetchone()
        return self._hydrate_project(row) if row else None

    def list_projects(
        self,
        *,
        channel_id: str | None = None,
        stage: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        offset = max(0, int(offset))
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id:
            clauses.append("channel_id=?")
            params.append(channel_id)
        if stage:
            clauses.append("stage=?")
            params.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM media_projects {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [self._hydrate_project(row) for row in rows]

    def update_project(self, project_id: str, **fields: Any) -> dict[str, Any] | None:
        current = self.get_project(project_id)
        if not current:
            return None
        mapping = {
            "title": "title",
            "topic": "topic",
            "stage": "stage",
            "platforms": "platforms_json",
            "autonomy_level": "autonomy_level",
            "progress": "progress",
            "stage_checkpoint": "stage_checkpoint_json",
            "artifacts": "artifacts_json",
            "content_dna": "content_dna_json",
            "error": "error",
            "lease_owner": "lease_owner",
            "lease_until": "lease_until",
            "cancel_requested": "cancel_requested",
        }
        sets: list[str] = []
        params: list[Any] = []
        for key, column in mapping.items():
            if key not in fields:
                continue
            value = fields[key]
            if key in {"platforms", "stage_checkpoint", "artifacts", "content_dna"}:
                value = _dumps(value)
            elif key == "cancel_requested":
                value = 1 if value else 0
            sets.append(f"{column}=?")
            params.append(value)
        if not sets:
            return current
        sets.append("updated_at=?")
        params.append(utc_now())
        params.append(project_id)
        with self.connection() as db:
            db.execute(f"UPDATE media_projects SET {', '.join(sets)} WHERE id=?", params)
        return self.get_project(project_id)

    def append_project_event(
        self,
        project_id: str,
        *,
        stage: str,
        event_type: str,
        detail: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = new_id("mevt")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_project_events(id,project_id,stage,event_type,detail,payload_json,created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (event_id, project_id, stage, event_type, detail, _dumps(payload or {}), now),
            )
        return {
            "id": event_id,
            "project_id": project_id,
            "stage": stage,
            "event_type": event_type,
            "detail": detail,
            "payload": payload or {},
            "created_at": now,
        }

    def list_project_events(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = clamp_limit(limit, default=100, maximum=500)
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT * FROM media_project_events
                WHERE project_id=? ORDER BY created_at ASC LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "project_id": data["project_id"],
                    "stage": data["stage"],
                    "event_type": data["event_type"],
                    "detail": data.get("detail", ""),
                    "payload": _loads(data.get("payload_json"), {}),
                    "created_at": data["created_at"],
                }
            )
        return out

    def claim_project_lease(self, project_id: str, owner: str, *, ttl_seconds: int = 120) -> bool:
        now = datetime.now(UTC)
        until = datetime.fromtimestamp(now.timestamp() + max(5, int(ttl_seconds)), tz=UTC).isoformat(timespec="seconds")
        now_s = now.isoformat(timespec="seconds")
        with self.connection() as db:
            row = db.execute("SELECT lease_owner, lease_until FROM media_projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return False
            current_owner = row["lease_owner"]
            current_until = row["lease_until"]
            if current_owner and current_until and current_until > now_s and current_owner != owner:
                return False
            db.execute(
                "UPDATE media_projects SET lease_owner=?, lease_until=?, updated_at=? WHERE id=?",
                (owner, until, now_s, project_id),
            )
        return True

    def release_project_lease(self, project_id: str, owner: str) -> None:
        with self.connection() as db:
            db.execute(
                """
                UPDATE media_projects SET lease_owner=NULL, lease_until=NULL, updated_at=?
                WHERE id=? AND lease_owner=?
                """,
                (utc_now(), project_id, owner),
            )

    # ---- sources / transcripts ----
    def create_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_id = new_id("msrc")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_sources(
                    id,channel_id,project_id,source_kind,uri,content_hash,text_excerpt,metadata_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_id,
                    payload.get("channel_id"),
                    payload.get("project_id"),
                    payload["source_kind"],
                    payload.get("uri", ""),
                    payload.get("content_hash", ""),
                    (payload.get("text_excerpt") or "")[:4000],
                    _dumps(payload.get("metadata", {})),
                    now,
                ),
            )
        return self.get_source(source_id)  # type: ignore[return-value]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "channel_id": data.get("channel_id"),
            "project_id": data.get("project_id"),
            "source_kind": data["source_kind"],
            "uri": data.get("uri", ""),
            "content_hash": data.get("content_hash", ""),
            "text_excerpt": data.get("text_excerpt", ""),
            "metadata": _loads(data.get("metadata_json"), {}),
            "created_at": data["created_at"],
        }

    def get_transcript_by_hash(
        self, content_hash: str, provider: str, provider_config_hash: str
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT * FROM media_transcripts
                WHERE content_hash=? AND provider=? AND provider_config_hash=?
                """,
                (content_hash, provider, provider_config_hash),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "source_id": data["source_id"],
            "content_hash": data["content_hash"],
            "provider": data["provider"],
            "language": data.get("language", ""),
            "confidence": data.get("confidence"),
            "segments": _loads(data.get("segments_json"), []),
            "words": _loads(data.get("words_json"), []),
            "full_text": data.get("full_text", ""),
            "provider_config_hash": data.get("provider_config_hash", ""),
            "created_at": data["created_at"],
        }

    def save_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_transcript_by_hash(
            payload["content_hash"], payload["provider"], payload.get("provider_config_hash", "")
        )
        if existing:
            return existing
        transcript_id = new_id("mtr")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_transcripts(
                    id,source_id,content_hash,provider,language,confidence,segments_json,words_json,
                    full_text,provider_config_hash,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    transcript_id,
                    payload["source_id"],
                    payload["content_hash"],
                    payload["provider"],
                    payload.get("language", ""),
                    payload.get("confidence"),
                    _dumps(payload.get("segments", [])),
                    _dumps(payload.get("words", [])),
                    payload.get("full_text", ""),
                    payload.get("provider_config_hash", ""),
                    now,
                ),
            )
        return self.get_transcript_by_hash(
            payload["content_hash"], payload["provider"], payload.get("provider_config_hash", "")
        )  # type: ignore[return-value]

    # ---- trends / opportunities ----
    def insert_trend_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        signal_id = new_id("mts")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_trend_signals(
                    id,provider,platform,topic,keyword,region,language,observed_at,rank,views,velocity,
                    engagement,growth,freshness,competition,saturation,source_ref,confidence,raw_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal_id,
                    payload["provider"],
                    payload.get("platform", ""),
                    payload["topic"],
                    payload.get("keyword", ""),
                    payload.get("region", ""),
                    payload.get("language", ""),
                    payload.get("observed_at", now),
                    payload.get("rank"),
                    payload.get("views"),
                    payload.get("velocity"),
                    payload.get("engagement"),
                    payload.get("growth"),
                    payload.get("freshness"),
                    payload.get("competition"),
                    payload.get("saturation"),
                    payload.get("source_ref", ""),
                    payload.get("confidence"),
                    _dumps(payload.get("raw", {})),
                    now,
                ),
            )
        return {"id": signal_id, **payload, "created_at": now}

    def upsert_trend(self, topic_key: str, display_topic: str, evidence: list[dict[str, Any]], scores: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_trends WHERE topic_key=?", (topic_key,)).fetchone()
            if row:
                db.execute(
                    """
                    UPDATE media_trends SET display_topic=?, evidence_json=?, scores_json=?, last_seen_at=?, updated_at=?
                    WHERE topic_key=?
                    """,
                    (display_topic, _dumps(evidence), _dumps(scores), now, now, topic_key),
                )
                trend_id = row["id"]
            else:
                trend_id = new_id("mtrd")
                db.execute(
                    """
                    INSERT INTO media_trends(id,topic_key,display_topic,evidence_json,scores_json,first_seen_at,last_seen_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (trend_id, topic_key, display_topic, _dumps(evidence), _dumps(scores), now, now, now),
                )
        return self.get_trend(trend_id)  # type: ignore[return-value]

    def get_trend(self, trend_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_trends WHERE id=?", (trend_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "topic_key": data["topic_key"],
            "display_topic": data["display_topic"],
            "evidence": _loads(data.get("evidence_json"), []),
            "scores": _loads(data.get("scores_json"), {}),
            "first_seen_at": data["first_seen_at"],
            "last_seen_at": data["last_seen_at"],
            "updated_at": data["updated_at"],
        }

    def list_trends(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM media_trends ORDER BY last_seen_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self.get_trend(row["id"]) for row in rows]  # type: ignore[misc]

    def count_trend_signals(self) -> int:
        with self.connection() as db:
            row = db.execute("SELECT COUNT(*) AS c FROM media_trend_signals").fetchone()
        return int(row["c"] if row else 0)

    def create_opportunity(self, payload: dict[str, Any]) -> dict[str, Any]:
        opp_id = new_id("mopp")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_opportunities(
                    id,channel_id,trend_id,score,components_json,explanation,status,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    opp_id,
                    payload.get("channel_id"),
                    payload.get("trend_id"),
                    float(payload.get("score", 0)),
                    _dumps(payload.get("components", {})),
                    payload.get("explanation", ""),
                    payload.get("status", "open"),
                    now,
                    now,
                ),
            )
        return self.get_opportunity(opp_id)  # type: ignore[return-value]

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "channel_id": data.get("channel_id"),
            "trend_id": data.get("trend_id"),
            "score": float(data.get("score") or 0),
            "components": _loads(data.get("components_json"), {}),
            "explanation": data.get("explanation", ""),
            "status": data.get("status", "open"),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def list_opportunities(self, *, channel_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with self.connection() as db:
            if channel_id:
                rows = db.execute(
                    "SELECT * FROM media_opportunities WHERE channel_id=? ORDER BY score DESC LIMIT ?",
                    (channel_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM media_opportunities ORDER BY score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self.get_opportunity(row["id"]) for row in rows]  # type: ignore[misc]

    def count_opportunities(self) -> int:
        with self.connection() as db:
            row = db.execute("SELECT COUNT(*) AS c FROM media_opportunities WHERE status='open'").fetchone()
        return int(row["c"] if row else 0)

    # ---- creative artifacts ----
    def save_research_claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        claim_id = new_id("mrc")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_research_claims(
                    id,project_id,claim,evidence,source_ref,confidence,contradictions_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    claim_id,
                    payload["project_id"],
                    payload["claim"],
                    payload.get("evidence", ""),
                    payload.get("source_ref", ""),
                    payload.get("confidence"),
                    _dumps(payload.get("contradictions", [])),
                    now,
                ),
            )
        return {"id": claim_id, **payload, "created_at": now}

    def list_research_claims(self, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM media_research_claims WHERE project_id=? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "project_id": data["project_id"],
                    "claim": data["claim"],
                    "evidence": data.get("evidence", ""),
                    "source_ref": data.get("source_ref", ""),
                    "confidence": data.get("confidence"),
                    "contradictions": _loads(data.get("contradictions_json"), []),
                    "created_at": data["created_at"],
                }
            )
        return out

    def save_hypothesis(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        hyp_id = new_id("mhyp")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO media_hypotheses(id,project_id,payload_json,created_at) VALUES (?,?,?,?)",
                (hyp_id, project_id, _dumps(payload), now),
            )
        return {"id": hyp_id, "project_id": project_id, "payload": payload, "created_at": now}

    def save_script(self, project_id: str, body: str, critiques: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM media_scripts WHERE project_id=?",
                (project_id,),
            ).fetchone()
            version = int(row["v"] if row else 0) + 1
            script_id = new_id("msc")
            now = utc_now()
            db.execute(
                """
                INSERT INTO media_scripts(id,project_id,version,body,critiques_json,created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (script_id, project_id, version, body, _dumps(critiques or []), now),
            )
        return {
            "id": script_id,
            "project_id": project_id,
            "version": version,
            "body": body,
            "critiques": critiques or [],
            "created_at": now,
        }

    def latest_script(self, project_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM media_scripts WHERE project_id=? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "project_id": data["project_id"],
            "version": data["version"],
            "body": data["body"],
            "critiques": _loads(data.get("critiques_json"), []),
            "created_at": data["created_at"],
        }

    def save_storyboard(self, project_id: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM media_storyboards WHERE project_id=?",
                (project_id,),
            ).fetchone()
            version = int(row["v"] if row else 0) + 1
            board_id = new_id("msb")
            now = utc_now()
            db.execute(
                """
                INSERT INTO media_storyboards(id,project_id,version,scenes_json,created_at)
                VALUES (?,?,?,?,?)
                """,
                (board_id, project_id, version, _dumps(scenes), now),
            )
        return {"id": board_id, "project_id": project_id, "version": version, "scenes": scenes, "created_at": now}

    def latest_storyboard(self, project_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM media_storyboards WHERE project_id=? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "project_id": data["project_id"],
            "version": data["version"],
            "scenes": _loads(data.get("scenes_json"), []),
            "created_at": data["created_at"],
        }

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_id = new_id("mast")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_assets(
                    id,project_id,channel_id,asset_type,origin,source_ref,provider,model,license_state,
                    content_hash,prompt_hash,storage_path,metadata_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    asset_id,
                    payload.get("project_id"),
                    payload.get("channel_id"),
                    payload["asset_type"],
                    payload.get("origin", ""),
                    payload.get("source_ref", ""),
                    payload.get("provider", ""),
                    payload.get("model", ""),
                    payload.get("license_state", "UNKNOWN"),
                    payload.get("content_hash", ""),
                    payload.get("prompt_hash", ""),
                    payload.get("storage_path", ""),
                    _dumps(payload.get("metadata", {})),
                    now,
                ),
            )
        return {"id": asset_id, **payload, "created_at": now}

    def list_assets(self, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = clamp_limit(limit, default=100, maximum=500)
        with self.connection() as db:
            if project_id:
                rows = db.execute(
                    "SELECT * FROM media_assets WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM media_assets ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "project_id": data.get("project_id"),
                    "channel_id": data.get("channel_id"),
                    "asset_type": data["asset_type"],
                    "origin": data.get("origin", ""),
                    "source_ref": data.get("source_ref", ""),
                    "provider": data.get("provider", ""),
                    "model": data.get("model", ""),
                    "license_state": data.get("license_state", "UNKNOWN"),
                    "content_hash": data.get("content_hash", ""),
                    "prompt_hash": data.get("prompt_hash", ""),
                    "storage_path": data.get("storage_path", ""),
                    "metadata": _loads(data.get("metadata_json"), {}),
                    "created_at": data["created_at"],
                }
            )
        return out

    def upsert_variant(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                """
                SELECT id FROM media_platform_variants
                WHERE project_id=? AND platform=? AND format_key=?
                """,
                (payload["project_id"], payload["platform"], payload.get("format_key", "")),
            ).fetchone()
            if row:
                variant_id = row["id"]
                db.execute(
                    """
                    UPDATE media_platform_variants
                    SET render_asset_id=?, metadata_json=?, status=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        payload.get("render_asset_id"),
                        _dumps(payload.get("metadata", {})),
                        payload.get("status", "pending"),
                        now,
                        variant_id,
                    ),
                )
            else:
                variant_id = new_id("mvar")
                db.execute(
                    """
                    INSERT INTO media_platform_variants(
                        id,project_id,platform,format_key,render_asset_id,metadata_json,status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        variant_id,
                        payload["project_id"],
                        payload["platform"],
                        payload.get("format_key", ""),
                        payload.get("render_asset_id"),
                        _dumps(payload.get("metadata", {})),
                        payload.get("status", "pending"),
                        now,
                        now,
                    ),
                )
        return self.get_variant(variant_id)  # type: ignore[return-value]

    def get_variant(self, variant_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_platform_variants WHERE id=?", (variant_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "project_id": data["project_id"],
            "platform": data["platform"],
            "format_key": data.get("format_key", ""),
            "render_asset_id": data.get("render_asset_id"),
            "metadata": _loads(data.get("metadata_json"), {}),
            "status": data.get("status", "pending"),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def list_variants(self, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id FROM media_platform_variants WHERE project_id=? ORDER BY platform",
                (project_id,),
            ).fetchall()
        return [self.get_variant(row["id"]) for row in rows]  # type: ignore[misc]

    # ---- publishing ----
    def create_publish_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = new_id("mpub")
        now = utc_now()
        idem = payload.get("idempotency_key") or f"{payload['project_id']}:{payload['platform']}:{payload.get('variant_id') or 'none'}"
        with self.connection() as db:
            existing = db.execute(
                "SELECT id FROM media_publish_jobs WHERE idempotency_key=?",
                (idem,),
            ).fetchone()
            if existing:
                return self.get_publish_job(existing["id"])  # type: ignore[return-value]
            db.execute(
                """
                INSERT INTO media_publish_jobs(
                    id,project_id,variant_id,platform,account_id,scheduled_for,approval_state,
                    platform_consent_state,attempt_count,idempotency_key,status,payload_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    payload["project_id"],
                    payload.get("variant_id"),
                    payload["platform"],
                    payload.get("account_id"),
                    payload.get("scheduled_for"),
                    payload.get("approval_state", "pending"),
                    payload.get("platform_consent_state", "not_required"),
                    0,
                    idem,
                    payload.get("status", "PENDING"),
                    _dumps(payload.get("payload", {})),
                    now,
                    now,
                ),
            )
        return self.get_publish_job(job_id)  # type: ignore[return-value]

    def get_publish_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_publish_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "project_id": data["project_id"],
            "variant_id": data.get("variant_id"),
            "platform": data["platform"],
            "account_id": data.get("account_id"),
            "scheduled_for": data.get("scheduled_for"),
            "approval_state": data.get("approval_state", "pending"),
            "platform_consent_state": data.get("platform_consent_state", "not_required"),
            "attempt_count": int(data.get("attempt_count") or 0),
            "last_attempt_at": data.get("last_attempt_at"),
            "idempotency_key": data["idempotency_key"],
            "external_upload_id": data.get("external_upload_id"),
            "external_post_id": data.get("external_post_id"),
            "status": data.get("status", "PENDING"),
            "error": data.get("error"),
            "payload": _loads(data.get("payload_json"), {}),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def update_publish_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "scheduled_for",
            "approval_state",
            "platform_consent_state",
            "attempt_count",
            "last_attempt_at",
            "external_upload_id",
            "external_post_id",
            "status",
            "error",
            "payload",
            "account_id",
            "variant_id",
        }
        sets: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            column = "payload_json" if key == "payload" else key
            if key == "payload":
                value = _dumps(value)
            sets.append(f"{column}=?")
            params.append(value)
        if not sets:
            return self.get_publish_job(job_id)
        sets.append("updated_at=?")
        params.append(utc_now())
        params.append(job_id)
        with self.connection() as db:
            db.execute(f"UPDATE media_publish_jobs SET {', '.join(sets)} WHERE id=?", params)
        return self.get_publish_job(job_id)

    def list_publish_jobs(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as db:
            rows = db.execute(
                f"SELECT id FROM media_publish_jobs {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self.get_publish_job(row["id"]) for row in rows]  # type: ignore[misc]

    def add_publish_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        record_id = new_id("mprec")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_publish_records(id,job_id,platform,external_post_id,status,raw_json,created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    record_id,
                    payload["job_id"],
                    payload["platform"],
                    payload.get("external_post_id"),
                    payload["status"],
                    _dumps(payload.get("raw", {})),
                    now,
                ),
            )
        return {"id": record_id, **payload, "created_at": now}

    # ---- analytics / learning / experiments ----
    def add_metric_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        snap_id = new_id("mmet")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_metric_snapshots(
                    id,project_id,platform,external_post_id,captured_at,hours_since_publish,metrics_json,raw_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    snap_id,
                    payload.get("project_id"),
                    payload["platform"],
                    payload["external_post_id"],
                    payload.get("captured_at", now),
                    payload.get("hours_since_publish"),
                    _dumps(payload.get("metrics", {})),
                    _dumps(payload.get("raw", {})),
                    now,
                ),
            )
        return {"id": snap_id, **payload, "created_at": now}

    def list_metric_snapshots(
        self,
        *,
        platform: str | None = None,
        external_post_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = clamp_limit(limit, default=100, maximum=500)
        clauses: list[str] = []
        params: list[Any] = []
        if platform:
            clauses.append("platform=?")
            params.append(platform)
        if external_post_id:
            clauses.append("external_post_id=?")
            params.append(external_post_id)
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM media_metric_snapshots {where} ORDER BY captured_at ASC LIMIT ?",
                (*params, limit),
            ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "project_id": data.get("project_id"),
                    "platform": data["platform"],
                    "external_post_id": data["external_post_id"],
                    "captured_at": data["captured_at"],
                    "hours_since_publish": data.get("hours_since_publish"),
                    "metrics": _loads(data.get("metrics_json"), {}),
                    "raw": _loads(data.get("raw_json"), {}),
                    "created_at": data["created_at"],
                }
            )
        return out

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        exp_id = new_id("mexp")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_experiments(
                    id,channel_id,name,hypothesis,control_json,variant_json,primary_metric,min_samples,status,results_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    exp_id,
                    payload.get("channel_id"),
                    payload["name"],
                    payload.get("hypothesis", ""),
                    _dumps(payload.get("control", {})),
                    _dumps(payload.get("variant", {})),
                    payload.get("primary_metric", ""),
                    int(payload.get("min_samples", 20)),
                    payload.get("status", "active"),
                    _dumps(payload.get("results", {})),
                    now,
                    now,
                ),
            )
        return self.get_experiment(exp_id)  # type: ignore[return-value]

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_experiments WHERE id=?", (experiment_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "channel_id": data.get("channel_id"),
            "name": data["name"],
            "hypothesis": data.get("hypothesis", ""),
            "control": _loads(data.get("control_json"), {}),
            "variant": _loads(data.get("variant_json"), {}),
            "primary_metric": data.get("primary_metric", ""),
            "min_samples": int(data.get("min_samples") or 20),
            "status": data.get("status", "active"),
            "results": _loads(data.get("results_json"), {}),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def list_experiments(self, *, channel_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with self.connection() as db:
            if channel_id:
                rows = db.execute(
                    "SELECT id FROM media_experiments WHERE channel_id=? ORDER BY updated_at DESC LIMIT ?",
                    (channel_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id FROM media_experiments ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self.get_experiment(row["id"]) for row in rows]  # type: ignore[misc]

    def add_learning_finding(self, payload: dict[str, Any]) -> dict[str, Any]:
        finding_id = new_id("mlrn")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_learning_findings(
                    id,channel_id,scope,platform,format_key,niche,finding,sample_size,effect_size,
                    confidence,recommendation,evidence_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    finding_id,
                    payload.get("channel_id"),
                    payload.get("scope", "CHANNEL"),
                    payload.get("platform", ""),
                    payload.get("format_key", ""),
                    payload.get("niche", ""),
                    payload["finding"],
                    int(payload.get("sample_size", 0)),
                    payload.get("effect_size"),
                    payload.get("confidence", "low"),
                    payload.get("recommendation", ""),
                    _dumps(payload.get("evidence", {})),
                    now,
                ),
            )
        return {"id": finding_id, **payload, "created_at": now}

    def list_learning_findings(self, *, channel_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with self.connection() as db:
            if channel_id:
                rows = db.execute(
                    "SELECT * FROM media_learning_findings WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
                    (channel_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM media_learning_findings ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "channel_id": data.get("channel_id"),
                    "scope": data.get("scope", "CHANNEL"),
                    "platform": data.get("platform", ""),
                    "format_key": data.get("format_key", ""),
                    "niche": data.get("niche", ""),
                    "finding": data["finding"],
                    "sample_size": int(data.get("sample_size") or 0),
                    "effect_size": data.get("effect_size"),
                    "confidence": data.get("confidence", "low"),
                    "recommendation": data.get("recommendation", ""),
                    "evidence": _loads(data.get("evidence_json"), {}),
                    "created_at": data["created_at"],
                }
            )
        return out

    def create_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        idea_id = new_id("midea")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO media_ideas(id,channel_id,opportunity_id,project_id,payload_json,rank_score,rejected,created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    idea_id,
                    payload.get("channel_id"),
                    payload.get("opportunity_id"),
                    payload.get("project_id"),
                    _dumps(payload.get("payload", {})),
                    float(payload.get("rank_score", 0)),
                    1 if payload.get("rejected") else 0,
                    now,
                ),
            )
        return {"id": idea_id, **payload, "created_at": now}

    def list_ideas(self, *, channel_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with self.connection() as db:
            if channel_id:
                rows = db.execute(
                    "SELECT * FROM media_ideas WHERE channel_id=? ORDER BY rank_score DESC LIMIT ?",
                    (channel_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM media_ideas ORDER BY rank_score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            out.append(
                {
                    "id": data["id"],
                    "channel_id": data.get("channel_id"),
                    "opportunity_id": data.get("opportunity_id"),
                    "project_id": data.get("project_id"),
                    "payload": _loads(data.get("payload_json"), {}),
                    "rank_score": float(data.get("rank_score") or 0),
                    "rejected": bool(data.get("rejected")),
                    "created_at": data["created_at"],
                }
            )
        return out

    def save_pattern(self, payload: dict[str, Any]) -> dict[str, Any]:
        pattern_id = new_id("mpat")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO media_patterns(id,source_id,project_id,pattern_json,created_at) VALUES (?,?,?,?,?)",
                (
                    pattern_id,
                    payload.get("source_id"),
                    payload.get("project_id"),
                    _dumps(payload.get("pattern", {})),
                    now,
                ),
            )
        return {"id": pattern_id, **payload, "created_at": now}

    def upsert_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute(
                "SELECT id FROM media_accounts WHERE platform=? AND external_account_id=?",
                (payload["platform"], payload.get("external_account_id", "")),
            ).fetchone()
            if row:
                account_id = row["id"]
                db.execute(
                    """
                    UPDATE media_accounts SET display_name=?, auth_status=?, scopes_json=?, metadata_json=?,
                        secret_ref=?, last_verified_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        payload.get("display_name", ""),
                        payload.get("auth_status", "AUTH_REQUIRED"),
                        _dumps(payload.get("scopes", [])),
                        _dumps(payload.get("metadata", {})),
                        payload.get("secret_ref", ""),
                        payload.get("last_verified_at"),
                        now,
                        account_id,
                    ),
                )
            else:
                account_id = new_id("macc")
                db.execute(
                    """
                    INSERT INTO media_accounts(
                        id,platform,external_account_id,display_name,auth_status,scopes_json,metadata_json,
                        secret_ref,last_verified_at,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        account_id,
                        payload["platform"],
                        payload.get("external_account_id", ""),
                        payload.get("display_name", ""),
                        payload.get("auth_status", "AUTH_REQUIRED"),
                        _dumps(payload.get("scopes", [])),
                        _dumps(payload.get("metadata", {})),
                        payload.get("secret_ref", ""),
                        payload.get("last_verified_at"),
                        now,
                        now,
                    ),
                )
        return self.get_account(account_id)  # type: ignore[return-value]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media_accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        return {
            "id": data["id"],
            "platform": data["platform"],
            "external_account_id": data.get("external_account_id", ""),
            "display_name": data.get("display_name", ""),
            "auth_status": data.get("auth_status", "AUTH_REQUIRED"),
            "scopes": _loads(data.get("scopes_json"), []),
            "metadata": _loads(data.get("metadata_json"), {}),
            "secret_ref": data.get("secret_ref", ""),
            "last_verified_at": data.get("last_verified_at"),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def list_accounts(self, *, platform: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as db:
            if platform:
                rows = db.execute(
                    "SELECT id FROM media_accounts WHERE platform=? ORDER BY updated_at DESC",
                    (platform,),
                ).fetchall()
            else:
                rows = db.execute("SELECT id FROM media_accounts ORDER BY updated_at DESC").fetchall()
        return [self.get_account(row["id"]) for row in rows]  # type: ignore[misc]

    # ---- overview counters ----
    def count_projects_by_stages(self, stages: list[str]) -> int:
        if not stages:
            return 0
        placeholders = ",".join("?" for _ in stages)
        with self.connection() as db:
            row = db.execute(
                f"SELECT COUNT(*) AS c FROM media_projects WHERE stage IN ({placeholders})",
                tuple(stages),
            ).fetchone()
        return int(row["c"] if row else 0)

    def count_publish_jobs(self, status: str) -> int:
        with self.connection() as db:
            row = db.execute(
                "SELECT COUNT(*) AS c FROM media_publish_jobs WHERE status=?",
                (status,),
            ).fetchone()
        return int(row["c"] if row else 0)

    def count_published_since(self, iso_prefix: str) -> int:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT COUNT(*) AS c FROM media_publish_jobs
                WHERE status='PUBLISHED' AND updated_at >= ?
                """,
                (iso_prefix,),
            ).fetchone()
        return int(row["c"] if row else 0)

    def claim_scheduler_lease(self, job_key: str, owner: str, *, ttl_seconds: int = 60) -> bool:
        now = datetime.now(UTC)
        until = datetime.fromtimestamp(now.timestamp() + max(5, int(ttl_seconds)), tz=UTC).isoformat(timespec="seconds")
        now_s = now.isoformat(timespec="seconds")
        with self.connection() as db:
            row = db.execute(
                "SELECT owner, lease_until FROM media_scheduler_leases WHERE job_key=?",
                (job_key,),
            ).fetchone()
            if row and row["lease_until"] and row["lease_until"] > now_s and row["owner"] != owner:
                return False
            db.execute(
                """
                INSERT INTO media_scheduler_leases(job_key,owner,lease_until,payload_json,updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(job_key) DO UPDATE SET
                    owner=excluded.owner,
                    lease_until=excluded.lease_until,
                    updated_at=excluded.updated_at
                """,
                (job_key, owner, until, _dumps({}), now_s),
            )
        return True

    def release_scheduler_lease(self, job_key: str, owner: str) -> None:
        with self.connection() as db:
            db.execute(
                "DELETE FROM media_scheduler_leases WHERE job_key=? AND owner=?",
                (job_key, owner),
            )
