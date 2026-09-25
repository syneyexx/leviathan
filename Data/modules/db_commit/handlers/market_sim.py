"""MarketSim domain commit handlers — batched events/fills/trajectories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import open_sqlite_connection, write_transaction
from Data.modules.db_commit.handlers.registry import FunctionHandler
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus, utc_now


def handlers() -> list[FunctionHandler]:
    return [
        FunctionHandler(
            operation="market_sim.commit_events",
            fn=_commit_events,
            required_payload_keys=("run_id", "events"),
        ),
        FunctionHandler(
            operation="market_sim.commit_trajectory",
            fn=_commit_trajectory,
            required_payload_keys=("run_id",),
        ),
        FunctionHandler(
            operation="market_sim.commit_feed_checkpoint",
            fn=_commit_feed_checkpoint,
            required_payload_keys=("feed_id",),
        ),
        FunctionHandler(
            operation="market_sim.commit_feed_latency_rollups",
            fn=_commit_feed_latency_rollups,
            required_payload_keys=("feed_id", "rollups"),
        ),
    ]


def _commit_events(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Bounded checkpoint batch. Leases/run control remain CONTROL_WRITE elsewhere."""
    run_id = str(payload["run_id"])
    events = list(payload.get("events") or [])
    fills = list(payload.get("fills") or [])
    equity = list(payload.get("equity") or [])

    conn = open_sqlite_connection(db_path)
    applied = 0
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="market_sim",
            operation="commit_events",
            rows=len(events) + len(fills) + len(equity),
        ):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_sim_commit_batches (
                    run_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    commit_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL DEFAULT 0,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, record_id, kind)
                )
                """
            )
            for event in events:
                rid = str(event.get("event_id") or event.get("id") or "")
                if not rid:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_sim_commit_batches(
                        run_id, record_id, kind, payload_json, commit_id,
                        sequence_number, applied_at
                    ) VALUES (?, ?, 'event', ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        rid,
                        json.dumps(event, ensure_ascii=False),
                        intent.commit_id,
                        int(intent.sequence_number or 0),
                        utc_now(),
                    ),
                )
                applied += 1
            for fill in fills:
                rid = str(fill.get("fill_id") or fill.get("id") or "")
                if not rid:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_sim_commit_batches(
                        run_id, record_id, kind, payload_json, commit_id,
                        sequence_number, applied_at
                    ) VALUES (?, ?, 'fill', ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        rid,
                        json.dumps(fill, ensure_ascii=False),
                        intent.commit_id,
                        int(intent.sequence_number or 0),
                        utc_now(),
                    ),
                )
                applied += 1
            for snap in equity:
                rid = str(snap.get("id") or snap.get("ts") or f"eq-{applied}")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_sim_commit_batches(
                        run_id, record_id, kind, payload_json, commit_id,
                        sequence_number, applied_at
                    ) VALUES (?, ?, 'equity', ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        rid,
                        json.dumps(snap, ensure_ascii=False),
                        intent.commit_id,
                        int(intent.sequence_number or 0),
                        utc_now(),
                    ),
                )
                applied += 1
    finally:
        conn.close()

    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="market_sim",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="market_sim_run",
        entity_id=run_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=applied,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={"run_id": run_id, "events": len(events), "fills": len(fills)},
    )


def _commit_trajectory(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    run_id = str(payload["run_id"])
    trajectory = dict(payload.get("trajectory") or {})
    conn = open_sqlite_connection(db_path)
    try:
        with write_transaction(
            conn,
            immediate=True,
            store="market_sim",
            operation="commit_trajectory",
            rows=1,
        ):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_sim_commit_batches (
                    run_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    commit_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL DEFAULT 0,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, record_id, kind)
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO market_sim_commit_batches(
                    run_id, record_id, kind, payload_json, commit_id,
                    sequence_number, applied_at
                ) VALUES (?, 'trajectory', 'trajectory', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    json.dumps(trajectory, ensure_ascii=False),
                    intent.commit_id,
                    int(intent.sequence_number or 0),
                    utc_now(),
                ),
            )
    finally:
        conn.close()
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="market_sim",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="market_sim_run",
        entity_id=run_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=1,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"run_id": run_id, "trajectory": True},
    )


def _commit_feed_checkpoint(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    """Batch metadata checkpoint for a live feed — never per-tick rows."""
    del settings
    feed_id = str(payload["feed_id"])
    snapshot = dict(payload.get("snapshot") or payload.get("checkpoint") or {})
    metrics = dict(payload.get("metrics") or {})
    session = dict(payload.get("session") or {})

    from Data.modules.market_sim.feed.store import MarketFeedStore

    store = MarketFeedStore(db_path)
    store.ensure_schema()
    if session:
        session.setdefault("feed_id", feed_id)
        store.upsert_session(session)
    receipt = store.write_checkpoint(feed_id, snapshot=snapshot, metrics=metrics)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="market_sim",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="market_feed_session",
        entity_id=feed_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=1,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        batch_index=intent.batch_index,
        batch_count=intent.batch_count,
        result={"feed_id": feed_id, "written_at": receipt.get("written_at"), "batch_metadata_only": True},
    )


def _commit_feed_latency_rollups(
    intent: CommitIntent,
    payload: dict[str, Any],
    db_path: Path,
    settings: Any,
) -> CommitReceipt:
    del settings
    feed_id = str(payload["feed_id"])
    rollups = list(payload.get("rollups") or [])

    from Data.modules.market_sim.feed.store import MarketFeedStore

    store = MarketFeedStore(db_path)
    store.ensure_schema()
    applied = store.write_latency_rollups(feed_id, rollups)
    return CommitReceipt(
        commit_id=intent.commit_id,
        idempotency_key=intent.idempotency_key,
        domain="market_sim",
        operation=intent.operation,
        status=CommitReceiptStatus.APPLIED.value,
        entity_type="market_feed_session",
        entity_id=feed_id,
        payload_hash=intent.payload_hash,
        applied_at=utc_now(),
        record_count=applied,
        producer_job_id=intent.source_job_id,
        trace_id=intent.trace_id,
        result={"feed_id": feed_id, "rollups": applied},
    )
