"""Persistence for trade orchestras (central leviathan.db, migration 43)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import DecisionRecord, NewsFeed, NewsItem, NewsSignal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class OrchestraStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.backend.migrations import MigrationRunner
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
        MigrationRunner(self.db_path).apply_all()

    # --- News feeds ---

    def upsert_feed(self, feed: NewsFeed) -> NewsFeed:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_news_feeds(
                    feed_id, name, url, kind, enabled, declared_latency_seconds, license_state,
                    symbols_hint_json, last_polled_at, last_status, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_id) DO UPDATE SET
                    name=excluded.name, url=excluded.url, kind=excluded.kind, enabled=excluded.enabled,
                    declared_latency_seconds=excluded.declared_latency_seconds,
                    license_state=excluded.license_state, symbols_hint_json=excluded.symbols_hint_json,
                    last_polled_at=excluded.last_polled_at, last_status=excluded.last_status,
                    last_error=excluded.last_error, updated_at=excluded.updated_at
                """,
                (
                    feed.feed_id,
                    feed.name,
                    feed.url,
                    feed.kind,
                    1 if feed.enabled else 0,
                    int(feed.declared_latency_seconds),
                    feed.license_state,
                    json.dumps(list(feed.symbols_hint)),
                    feed.last_polled_at,
                    feed.last_status,
                    feed.last_error,
                    feed.created_at,
                    feed.updated_at,
                ),
            )
        return feed

    def get_feed(self, feed_id: str) -> NewsFeed | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM market_news_feeds WHERE feed_id = ?", (feed_id,)).fetchone()
        return self._feed_from_row(row) if row else None

    def get_feed_by_url(self, url: str) -> NewsFeed | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM market_news_feeds WHERE url = ?", (url,)).fetchone()
        return self._feed_from_row(row) if row else None

    def list_feeds(self, *, enabled_only: bool = False) -> list[NewsFeed]:
        sql = "SELECT * FROM market_news_feeds"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at ASC"
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._feed_from_row(r) for r in rows]

    def delete_feed(self, feed_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM market_news_feeds WHERE feed_id = ?", (feed_id,))
            return cur.rowcount > 0

    @staticmethod
    def _feed_from_row(row: sqlite3.Row) -> NewsFeed:
        return NewsFeed(
            feed_id=row["feed_id"],
            name=row["name"],
            url=row["url"],
            kind=row["kind"],
            enabled=bool(row["enabled"]),
            declared_latency_seconds=int(row["declared_latency_seconds"] or 0),
            license_state=row["license_state"] or "UNKNOWN",
            symbols_hint=list(_loads(row["symbols_hint_json"], [])),
            last_polled_at=row["last_polled_at"],
            last_status=row["last_status"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- News items ---

    def insert_items(self, items: list[NewsItem]) -> list[NewsItem]:
        """Insert new items; duplicates (by content_hash) are skipped. Returns inserted items."""
        inserted: list[NewsItem] = []
        with self.connect() as conn:
            for item in items:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO market_news_items(
                        item_id, feed_id, source, url, title, summary, content_hash, published_at,
                        fetched_at, available_at, license_state, symbols_hint_json, knowledge_document_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.item_id,
                        item.feed_id,
                        item.source,
                        item.url,
                        item.title,
                        item.summary,
                        item.content_hash,
                        item.published_at,
                        item.fetched_at,
                        item.available_at,
                        item.license_state,
                        json.dumps(list(item.symbols_hint)),
                        item.knowledge_document_id,
                    ),
                )
                if cur.rowcount > 0:
                    inserted.append(item)
        return inserted

    def get_item(self, item_id: str) -> NewsItem | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM market_news_items WHERE item_id = ?", (item_id,)).fetchone()
        return self._item_from_row(row) if row else None

    def list_items(
        self,
        *,
        as_of: str | None = None,
        since: str | None = None,
        feed_id: str | None = None,
        limit: int = 100,
        unanalyzed_only: bool = False,
    ) -> list[NewsItem]:
        """Items visible at ``as_of`` (available_at <= as_of). Newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if as_of:
            clauses.append("available_at <= ?")
            params.append(as_of)
        if since:
            clauses.append("available_at >= ?")
            params.append(since)
        if feed_id:
            clauses.append("feed_id = ?")
            params.append(feed_id)
        if unanalyzed_only:
            clauses.append("item_id NOT IN (SELECT item_id FROM market_news_signals)")
        sql = "SELECT * FROM market_news_items"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY available_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._item_from_row(r) for r in rows]

    def count_items(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM market_news_items").fetchone()[0])

    def set_item_document(self, item_id: str, document_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE market_news_items SET knowledge_document_id = ? WHERE item_id = ?",
                (document_id, item_id),
            )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> NewsItem:
        return NewsItem(
            item_id=row["item_id"],
            feed_id=row["feed_id"],
            source=row["source"],
            url=row["url"],
            title=row["title"],
            summary=row["summary"] or "",
            content_hash=row["content_hash"],
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            available_at=row["available_at"],
            license_state=row["license_state"] or "UNKNOWN",
            symbols_hint=list(_loads(row["symbols_hint_json"], [])),
            knowledge_document_id=row["knowledge_document_id"],
        )

    # --- News signals ---

    def insert_signal(self, signal: NewsSignal) -> NewsSignal:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_news_signals(
                    signal_id, item_id, agent_id, mission_id, instruments_json, event_type, direction,
                    magnitude, confidence, horizon, rationale, as_of, model_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.item_id,
                    signal.agent_id,
                    signal.mission_id,
                    json.dumps(list(signal.instruments)),
                    signal.event_type,
                    signal.direction,
                    float(signal.magnitude),
                    float(signal.confidence),
                    signal.horizon,
                    signal.rationale,
                    signal.as_of,
                    signal.model_id,
                    signal.created_at,
                ),
            )
        return signal

    def list_signals(
        self,
        *,
        as_of: str | None = None,
        instrument: str | None = None,
        limit: int = 100,
    ) -> list[NewsSignal]:
        clauses: list[str] = []
        params: list[Any] = []
        if as_of:
            clauses.append("as_of <= ?")
            params.append(as_of)
        if instrument:
            clauses.append("instruments_json LIKE ?")
            params.append(f'%"{instrument.upper()}"%')
        sql = "SELECT * FROM market_news_signals"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY as_of DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            NewsSignal(
                signal_id=r["signal_id"],
                item_id=r["item_id"],
                agent_id=r["agent_id"],
                mission_id=r["mission_id"],
                instruments=list(_loads(r["instruments_json"], [])),
                event_type=r["event_type"],
                direction=r["direction"],
                magnitude=float(r["magnitude"]),
                confidence=float(r["confidence"]),
                horizon=r["horizon"],
                rationale=r["rationale"] or "",
                as_of=r["as_of"],
                model_id=r["model_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # --- Decisions (append-only) ---

    def append_decision(self, record: DecisionRecord) -> DecisionRecord:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_decisions(
                    decision_id, orchestra_id, mission_id, agent_id, role, stage, as_of, payload_json,
                    parent_decision_id, model_id, prompt_artifact_id, output_artifact_id,
                    mandate_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.decision_id,
                    record.orchestra_id,
                    record.mission_id,
                    record.agent_id,
                    record.role,
                    record.stage,
                    record.as_of,
                    json.dumps(record.payload, sort_keys=True, default=str),
                    record.parent_decision_id,
                    record.model_id,
                    record.prompt_artifact_id,
                    record.output_artifact_id,
                    record.mandate_fingerprint,
                    record.created_at,
                ),
            )
        return record

    def list_decisions(
        self,
        *,
        orchestra_id: str | None = None,
        mission_id: str | None = None,
        stage: str | None = None,
        limit: int = 200,
    ) -> list[DecisionRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if orchestra_id:
            clauses.append("orchestra_id = ?")
            params.append(orchestra_id)
        if mission_id:
            clauses.append("mission_id = ?")
            params.append(mission_id)
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        sql = "SELECT * FROM market_decisions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decision_from_row(r) for r in rows]

    def decision_stats(self, orchestra_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT stage, COUNT(*) AS n FROM market_decisions WHERE orchestra_id = ? GROUP BY stage",
                (orchestra_id,),
            ).fetchall()
            last = conn.execute(
                "SELECT MAX(created_at) FROM market_decisions WHERE orchestra_id = ?",
                (orchestra_id,),
            ).fetchone()[0]
            vetoes = conn.execute(
                "SELECT COUNT(*) FROM market_decisions WHERE orchestra_id = ? AND stage = 'risk_decision' "
                "AND payload_json LIKE '%\"allowed\": false%'",
                (orchestra_id,),
            ).fetchone()[0]
        by_stage = {str(r["stage"]): int(r["n"]) for r in rows}
        return {
            "byStage": by_stage,
            "total": sum(by_stage.values()),
            "riskRejections": int(vetoes or 0),
            "lastDecisionAt": last,
        }

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            decision_id=row["decision_id"],
            orchestra_id=row["orchestra_id"],
            mission_id=row["mission_id"],
            agent_id=row["agent_id"],
            role=row["role"],
            stage=row["stage"],
            as_of=row["as_of"],
            payload=dict(_loads(row["payload_json"], {})),
            parent_decision_id=row["parent_decision_id"],
            model_id=row["model_id"],
            prompt_artifact_id=row["prompt_artifact_id"],
            output_artifact_id=row["output_artifact_id"],
            mandate_fingerprint=row["mandate_fingerprint"] or "",
            created_at=row["created_at"],
        )
