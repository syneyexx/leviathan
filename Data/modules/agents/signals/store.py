"""SQLite persistence for LEVIATHAN Signal Fabric (migration v50)."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .envelope import (
    AgentSignal,
    AgentSignalDeadLetter,
    AgentSignalDelivery,
    AgentSignalSubscription,
    utc_now,
)
from .types import (
    PRIORITY_RANK,
    DeliveryState,
    RecipientType,
    SignalPriority,
    SignalStatus,
    SignalType,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class SignalStore:
    """Owns agent_signals / deliveries / subscriptions / dead_letters / dedupe."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[Any]:
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
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            _ensure_schema(conn)

    # ── Signals ──────────────────────────────────────────────────────────

    def create_signal(self, signal: AgentSignal) -> AgentSignal:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_signals(
                    signal_id, signal_type, sender_type, sender_id,
                    recipient_type, recipient_id, mission_id, run_id, trace_id,
                    parent_signal_id, correlation_id, priority, subject,
                    payload_json, artifact_refs_json, evidence_refs_json,
                    confidence, requires_ack, expires_at, idempotency_key,
                    hop_count, max_hops, status, created_at, updated_at, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal.signal_id,
                    signal.signal_type.value,
                    signal.sender_type.value,
                    signal.sender_id,
                    signal.recipient_type.value,
                    signal.recipient_id,
                    signal.mission_id,
                    signal.run_id,
                    signal.trace_id,
                    signal.parent_signal_id,
                    signal.correlation_id,
                    signal.priority.value,
                    signal.subject,
                    json.dumps(signal.payload),
                    json.dumps(signal.artifact_refs),
                    json.dumps(signal.evidence_refs),
                    signal.confidence,
                    1 if signal.requires_ack else 0,
                    signal.expires_at,
                    signal.idempotency_key,
                    signal.hop_count,
                    signal.max_hops,
                    signal.status.value,
                    signal.created_at,
                    signal.updated_at,
                    json.dumps(signal.metadata),
                ),
            )
        return signal

    def get_signal(self, signal_id: str) -> AgentSignal | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_signals WHERE signal_id = ?", (signal_id,)
            ).fetchone()
            return AgentSignal.from_row(row) if row else None

    def update_signal_status(self, signal_id: str, status: SignalStatus) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE agent_signals SET status = ?, updated_at = ? WHERE signal_id = ?",
                (status.value, now, signal_id),
            )

    def list_signals(
        self,
        *,
        agent_id: str | None = None,
        sender_id: str | None = None,
        recipient_id: str | None = None,
        mission_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        signal_type: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        correlation_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentSignal]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("(sender_id = ? OR recipient_id = ?)")
            params.extend([agent_id, agent_id])
        if sender_id:
            clauses.append("sender_id = ?")
            params.append(sender_id)
        if recipient_id:
            clauses.append("recipient_id = ?")
            params.append(recipient_id)
        if mission_id:
            clauses.append("mission_id = ?")
            params.append(mission_id)
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if signal_type:
            clauses.append("signal_type = ?")
            params.append(signal_type)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if correlation_id:
            clauses.append("correlation_id = ?")
            params.append(correlation_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        lim = max(1, min(int(limit), 500))
        off = max(0, int(offset))
        sql = (
            f"SELECT * FROM agent_signals{where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([lim, off])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [AgentSignal.from_row(r) for r in rows]

    def count_mission_signals(self, mission_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signals WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
            return int(row["c"] if row else 0)

    def find_by_idempotency(self, idempotency_key: str) -> AgentSignal | None:
        if not idempotency_key:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_signals WHERE idempotency_key = ? ORDER BY created_at ASC LIMIT 1",
                (idempotency_key,),
            ).fetchone()
            return AgentSignal.from_row(row) if row else None

    # ── Deliveries ───────────────────────────────────────────────────────

    def create_delivery(self, delivery: AgentSignalDelivery) -> AgentSignalDelivery:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_signal_deliveries(
                    delivery_id, signal_id, recipient_type, recipient_id,
                    resolved_agent_id, state, attempt_count, max_attempts,
                    next_attempt_at, claimed_by, claimed_at, lease_expires_at,
                    delivered_at, acknowledged_at, consumed_at, ack_consumer,
                    last_error, created_at, updated_at, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    delivery.delivery_id,
                    delivery.signal_id,
                    delivery.recipient_type.value,
                    delivery.recipient_id,
                    delivery.resolved_agent_id,
                    delivery.state.value,
                    delivery.attempt_count,
                    delivery.max_attempts,
                    delivery.next_attempt_at,
                    delivery.claimed_by,
                    delivery.claimed_at,
                    delivery.lease_expires_at,
                    delivery.delivered_at,
                    delivery.acknowledged_at,
                    delivery.consumed_at,
                    delivery.ack_consumer,
                    delivery.last_error,
                    delivery.created_at,
                    delivery.updated_at,
                    json.dumps(delivery.metadata),
                ),
            )
        return delivery

    def get_delivery(self, delivery_id: str) -> AgentSignalDelivery | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_signal_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            return AgentSignalDelivery.from_row(row) if row else None

    def list_deliveries(
        self,
        *,
        signal_id: str | None = None,
        recipient_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[AgentSignalDelivery]:
        clauses: list[str] = []
        params: list[Any] = []
        if signal_id:
            clauses.append("signal_id = ?")
            params.append(signal_id)
        if recipient_id:
            clauses.append("recipient_id = ?")
            params.append(recipient_id)
        if state:
            clauses.append("state = ?")
            params.append(state)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        lim = max(1, min(int(limit), 500))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_signal_deliveries{where} "
                f"ORDER BY created_at DESC LIMIT ?",
                [*params, lim],
            ).fetchall()
            return [AgentSignalDelivery.from_row(r) for r in rows]

    def claim_pending_deliveries(
        self,
        *,
        worker_id: str,
        limit: int = 8,
        lease_ttl_seconds: float = 30.0,
    ) -> list[AgentSignalDelivery]:
        """Concurrency-safe claim: UPDATE … WHERE state still PENDING/RETRY_WAIT."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")
        lease_exp = (now + timedelta(seconds=lease_ttl_seconds)).isoformat(timespec="seconds")
        claimed: list[AgentSignalDelivery] = []
        lim = max(1, min(int(limit), 32))

        with self.connect() as conn:
            # Prefer higher urgency (lower priority rank) then older created_at.
            candidates = conn.execute(
                """
                SELECT d.delivery_id, s.priority
                FROM agent_signal_deliveries d
                JOIN agent_signals s ON s.signal_id = d.signal_id
                WHERE (
                    d.state = 'PENDING'
                    OR (d.state = 'RETRY_WAIT' AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?))
                    OR (d.state = 'CLAIMED' AND d.lease_expires_at IS NOT NULL AND d.lease_expires_at < ?)
                )
                AND (s.expires_at IS NULL OR s.expires_at > ?)
                ORDER BY
                    CASE s.priority
                        WHEN 'CRITICAL' THEN 0
                        WHEN 'HIGH' THEN 10
                        WHEN 'NORMAL' THEN 50
                        WHEN 'LOW' THEN 80
                        WHEN 'TELEMETRY' THEN 100
                        ELSE 50
                    END ASC,
                    d.created_at ASC
                LIMIT ?
                """,
                (now_iso, now_iso, now_iso, lim * 3),
            ).fetchall()

            for cand in candidates:
                if len(claimed) >= lim:
                    break
                did = cand["delivery_id"]
                cur = conn.execute(
                    """
                    UPDATE agent_signal_deliveries
                    SET state = 'CLAIMED',
                        claimed_by = ?,
                        claimed_at = ?,
                        lease_expires_at = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE delivery_id = ?
                      AND (
                        state IN ('PENDING', 'RETRY_WAIT')
                        OR (state = 'CLAIMED' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                      )
                    """,
                    (worker_id, now_iso, lease_exp, now_iso, did, now_iso),
                )
                if cur.rowcount == 1:
                    row = conn.execute(
                        "SELECT * FROM agent_signal_deliveries WHERE delivery_id = ?",
                        (did,),
                    ).fetchone()
                    if row:
                        claimed.append(AgentSignalDelivery.from_row(row))
        return claimed

    def update_delivery(self, delivery: AgentSignalDelivery) -> AgentSignalDelivery:
        delivery.updated_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agent_signal_deliveries SET
                    resolved_agent_id=?, state=?, attempt_count=?, max_attempts=?,
                    next_attempt_at=?, claimed_by=?, claimed_at=?, lease_expires_at=?,
                    delivered_at=?, acknowledged_at=?, consumed_at=?, ack_consumer=?,
                    last_error=?, updated_at=?, metadata_json=?
                WHERE delivery_id=?
                """,
                (
                    delivery.resolved_agent_id,
                    delivery.state.value,
                    delivery.attempt_count,
                    delivery.max_attempts,
                    delivery.next_attempt_at,
                    delivery.claimed_by,
                    delivery.claimed_at,
                    delivery.lease_expires_at,
                    delivery.delivered_at,
                    delivery.acknowledged_at,
                    delivery.consumed_at,
                    delivery.ack_consumer,
                    delivery.last_error,
                    delivery.updated_at,
                    json.dumps(delivery.metadata),
                    delivery.delivery_id,
                ),
            )
        return delivery

    def ack_delivery(
        self,
        delivery_id: str,
        *,
        consumer: str,
    ) -> AgentSignalDelivery | None:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_signal_deliveries
                SET state = 'ACKNOWLEDGED',
                    acknowledged_at = ?,
                    ack_consumer = ?,
                    updated_at = ?
                WHERE delivery_id = ?
                  AND state IN ('DELIVERED', 'CLAIMED', 'ACKNOWLEDGED')
                """,
                (now, consumer, now, delivery_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM agent_signal_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            return AgentSignalDelivery.from_row(row) if row else None

    def mark_consumed(self, delivery_id: str) -> AgentSignalDelivery | None:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_signal_deliveries
                SET state = 'CONSUMED', consumed_at = ?, updated_at = ?
                WHERE delivery_id = ?
                  AND state IN ('DELIVERED', 'ACKNOWLEDGED', 'CONSUMED')
                """,
                (now, now, delivery_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM agent_signal_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            return AgentSignalDelivery.from_row(row) if row else None

    def schedule_retry(
        self,
        delivery_id: str,
        *,
        delay_seconds: float,
        error: str,
    ) -> AgentSignalDelivery | None:
        now = datetime.now(timezone.utc)
        next_at = (now + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_signal_deliveries
                SET state = 'RETRY_WAIT',
                    next_attempt_at = ?,
                    last_error = ?,
                    claimed_by = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE delivery_id = ?
                """,
                (next_at, error[:500], now.isoformat(timespec="seconds"), delivery_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM agent_signal_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            return AgentSignalDelivery.from_row(row) if row else None

    # ── Dead letters ─────────────────────────────────────────────────────

    def move_dead_letter(self, dead: AgentSignalDeadLetter) -> AgentSignalDeadLetter:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_signal_dead_letters(
                    dead_letter_id, signal_id, delivery_id, recipient_type, recipient_id,
                    attempt_count, last_error, first_failure_at, last_failure_at,
                    reason, retryable, signal_snapshot_json, created_at, retried_at, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    dead.dead_letter_id,
                    dead.signal_id,
                    dead.delivery_id,
                    dead.recipient_type,
                    dead.recipient_id,
                    dead.attempt_count,
                    dead.last_error,
                    dead.first_failure_at,
                    dead.last_failure_at,
                    dead.reason,
                    1 if dead.retryable else 0,
                    json.dumps(dead.signal_snapshot),
                    dead.created_at or utc_now(),
                    dead.retried_at,
                    json.dumps(dead.metadata),
                ),
            )
            if dead.delivery_id:
                conn.execute(
                    """
                    UPDATE agent_signal_deliveries
                    SET state = 'DEAD_LETTER', updated_at = ?, last_error = ?
                    WHERE delivery_id = ?
                    """,
                    (utc_now(), dead.last_error, dead.delivery_id),
                )
            conn.execute(
                "UPDATE agent_signals SET status = ?, updated_at = ? WHERE signal_id = ?",
                (SignalStatus.DEAD_LETTERED.value, utc_now(), dead.signal_id),
            )
        return dead

    def list_dead_letters(self, *, limit: int = 100, offset: int = 0) -> list[AgentSignalDeadLetter]:
        lim = max(1, min(int(limit), 500))
        off = max(0, int(offset))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_signal_dead_letters
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (lim, off),
            ).fetchall()
            return [AgentSignalDeadLetter.from_row(r) for r in rows]

    def get_dead_letter(self, dead_letter_id: str) -> AgentSignalDeadLetter | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_signal_dead_letters WHERE dead_letter_id = ?",
                (dead_letter_id,),
            ).fetchone()
            return AgentSignalDeadLetter.from_row(row) if row else None

    def mark_dead_letter_retried(self, dead_letter_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE agent_signal_dead_letters SET retried_at = ? WHERE dead_letter_id = ?",
                (utc_now(), dead_letter_id),
            )

    # ── Dedupe ───────────────────────────────────────────────────────────

    def dedupe_lookup(self, dedupe_key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT signal_id FROM agent_signal_dedupe WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            return str(row["signal_id"]) if row else None

    def dedupe_register(self, dedupe_key: str, signal_id: str, *, scope: str = "signal") -> bool:
        """Return True if newly registered; False if key already existed."""
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO agent_signal_dedupe(dedupe_key, signal_id, scope, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (dedupe_key, signal_id, scope, utc_now()),
                )
                return True
            except Exception:  # noqa: BLE001 — unique constraint
                return False

    # ── Subscriptions ────────────────────────────────────────────────────

    def create_subscription(self, sub: AgentSignalSubscription) -> AgentSignalSubscription:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_signal_subscriptions(
                    subscription_id, subscriber_type, subscriber_id, signal_type,
                    role, capability, mission_id, enabled, created_at, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sub.subscription_id,
                    sub.subscriber_type,
                    sub.subscriber_id,
                    sub.signal_type,
                    sub.role,
                    sub.capability,
                    sub.mission_id,
                    1 if sub.enabled else 0,
                    sub.created_at or utc_now(),
                    json.dumps(sub.metadata),
                ),
            )
        return sub

    def list_subscriptions(
        self,
        *,
        signal_type: str | None = None,
        enabled_only: bool = True,
        limit: int = 200,
    ) -> list[AgentSignalSubscription]:
        clauses: list[str] = []
        params: list[Any] = []
        if enabled_only:
            clauses.append("enabled = 1")
        if signal_type:
            clauses.append("(signal_type IS NULL OR signal_type = ?)")
            params.append(signal_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_signal_subscriptions{where} LIMIT ?",
                [*params, max(1, min(limit, 500))],
            ).fetchall()
            out: list[AgentSignalSubscription] = []
            for r in rows:
                out.append(
                    AgentSignalSubscription(
                        subscription_id=r["subscription_id"],
                        subscriber_type=r["subscriber_type"],
                        subscriber_id=r["subscriber_id"],
                        signal_type=r["signal_type"],
                        role=r["role"],
                        capability=r["capability"],
                        mission_id=r["mission_id"],
                        enabled=bool(r["enabled"]),
                        created_at=r["created_at"],
                        metadata=json.loads(r["metadata_json"] or "{}"),
                    )
                )
            return out

    # ── Metrics / graph helpers ──────────────────────────────────────────

    def metrics_snapshot(self, *, since: str | None = None, window_minutes: int = 60) -> dict[str, Any]:
        if not since:
            since = (
                datetime.now(timezone.utc) - timedelta(minutes=max(1, window_minutes))
            ).isoformat(timespec="seconds")
        with self.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signals WHERE created_at >= ?", (since,)
            ).fetchone()["c"]
            by_type = {
                r["signal_type"]: r["c"]
                for r in conn.execute(
                    "SELECT signal_type, COUNT(*) AS c FROM agent_signals "
                    "WHERE created_at >= ? GROUP BY signal_type",
                    (since,),
                ).fetchall()
            }
            delivered = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_deliveries "
                "WHERE state IN ('DELIVERED','ACKNOWLEDGED','CONSUMED') AND created_at >= ?",
                (since,),
            ).fetchone()["c"]
            acked = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_deliveries "
                "WHERE state IN ('ACKNOWLEDGED','CONSUMED') AND created_at >= ?",
                (since,),
            ).fetchone()["c"]
            failed = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_deliveries "
                "WHERE state IN ('FAILED','DEAD_LETTER') AND created_at >= ?",
                (since,),
            ).fetchone()["c"]
            dead = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_dead_letters WHERE created_at >= ?",
                (since,),
            ).fetchone()["c"]
            expired = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signals WHERE status = 'EXPIRED' AND created_at >= ?",
                (since,),
            ).fetchone()["c"]
            lat_rows = conn.execute(
                """
                SELECT
                    (julianday(delivered_at) - julianday(created_at)) * 86400.0 AS lat
                FROM agent_signal_deliveries
                WHERE delivered_at IS NOT NULL AND created_at >= ?
                ORDER BY lat ASC
                """,
                (since,),
            ).fetchall()
            lats = [float(r["lat"]) for r in lat_rows if r["lat"] is not None]
            avg_lat = sum(lats) / len(lats) if lats else None
            p95_lat = lats[int(len(lats) * 0.95)] if len(lats) >= 2 else (lats[0] if lats else None)
            ack_rows = conn.execute(
                """
                SELECT
                    (julianday(acknowledged_at) - julianday(delivered_at)) * 86400.0 AS lat
                FROM agent_signal_deliveries
                WHERE acknowledged_at IS NOT NULL AND delivered_at IS NOT NULL AND created_at >= ?
                """,
                (since,),
            ).fetchall()
            ack_lats = [float(r["lat"]) for r in ack_rows if r["lat"] is not None]
            avg_ack = sum(ack_lats) / len(ack_lats) if ack_lats else None
            dedupe_suppressed = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_dedupe WHERE created_at >= ?",
                (since,),
            ).fetchone()["c"]
            retries = conn.execute(
                "SELECT COUNT(*) AS c FROM agent_signal_deliveries "
                "WHERE attempt_count > 1 AND created_at >= ?",
                (since,),
            ).fetchone()["c"]
            minutes = max(1.0, window_minutes)
            return {
                "windowMinutes": window_minutes,
                "since": since,
                "signalsTotal": int(total),
                "signalsPerMinute": round(float(total) / minutes, 3),
                "byType": by_type,
                "delivered": int(delivered),
                "acknowledged": int(acked),
                "failed": int(failed),
                "deadLetter": int(dead),
                "expired": int(expired),
                "handoffs": int(by_type.get("TASK_HANDOFF", 0)),
                "verificationRequests": int(by_type.get("VERIFY_REQUEST", 0)),
                "rejections": int(by_type.get("REJECTED", 0)),
                "blocks": int(by_type.get("BLOCK", 0)),
                "knowledgeCandidates": int(by_type.get("KNOWLEDGE_CANDIDATE", 0)),
                "avgDeliveryLatencyS": round(avg_lat, 4) if avg_lat is not None else None,
                "p95DeliveryLatencyS": round(p95_lat, 4) if p95_lat is not None else None,
                "avgAckLatencyS": round(avg_ack, 4) if avg_ack is not None else None,
                "retryRate": round(float(retries) / max(1, int(delivered) + int(failed)), 4),
                "dedupeKeys": int(dedupe_suppressed),
                "truth": {
                    "metrics_from_durable_store": True,
                    "no_fabricated_values": True,
                },
            }

    def communication_graph(
        self,
        *,
        since: str | None = None,
        mission_id: str | None = None,
        window_hours: int = 24,
        limit_edges: int = 200,
    ) -> dict[str, Any]:
        if not since:
            since = (
                datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
            ).isoformat(timespec="seconds")
        clauses = ["created_at >= ?"]
        params: list[Any] = [since]
        if mission_id:
            clauses.append("mission_id = ?")
            params.append(mission_id)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT sender_id, recipient_id, signal_type, COUNT(*) AS c,
                       AVG(
                         CASE WHEN priority = 'CRITICAL' THEN 1 ELSE 0 END
                       ) AS crit_share
                FROM agent_signals
                WHERE {where}
                GROUP BY sender_id, recipient_id, signal_type
                ORDER BY c DESC
                LIMIT ?
                """,
                [*params, max(1, min(limit_edges, 500))],
            ).fetchall()
            nodes: dict[str, dict[str, Any]] = {}
            edges: list[dict[str, Any]] = []
            agg: dict[tuple[str, str], dict[str, Any]] = {}
            for r in rows:
                src, dst = r["sender_id"], r["recipient_id"]
                nodes.setdefault(src, {"id": src, "kind": "participant"})
                nodes.setdefault(dst, {"id": dst, "kind": "participant"})
                key = (src, dst)
                edge = agg.setdefault(
                    key,
                    {
                        "from": src,
                        "to": dst,
                        "signalCount": 0,
                        "handoffs": 0,
                        "verificationRequests": 0,
                        "blocks": 0,
                        "errors": 0,
                        "byType": {},
                    },
                )
                edge["signalCount"] += int(r["c"])
                edge["byType"][r["signal_type"]] = int(r["c"])
                if r["signal_type"] == "TASK_HANDOFF":
                    edge["handoffs"] += int(r["c"])
                elif r["signal_type"] == "VERIFY_REQUEST":
                    edge["verificationRequests"] += int(r["c"])
                elif r["signal_type"] == "BLOCK":
                    edge["blocks"] += int(r["c"])
                elif r["signal_type"] == "ERROR":
                    edge["errors"] += int(r["c"])
            edges = list(agg.values())
            # Latency per edge (bounded).
            for edge in edges[:limit_edges]:
                lat = conn.execute(
                    """
                    SELECT AVG((julianday(d.delivered_at) - julianday(d.created_at)) * 86400.0) AS avg_lat
                    FROM agent_signal_deliveries d
                    JOIN agent_signals s ON s.signal_id = d.signal_id
                    WHERE s.sender_id = ? AND s.recipient_id = ?
                      AND d.delivered_at IS NOT NULL AND s.created_at >= ?
                    """,
                    (edge["from"], edge["to"], since),
                ).fetchone()
                edge["avgDeliveryLatencyS"] = (
                    round(float(lat["avg_lat"]), 4) if lat and lat["avg_lat"] is not None else None
                )
            return {
                "since": since,
                "missionId": mission_id,
                "nodes": list(nodes.values()),
                "edges": edges[:limit_edges],
                "truth": {
                    "aggregated_edges": True,
                    "not_per_signal_svg": True,
                },
            }

    def expire_due_signals(self) -> int:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_signals SET status = 'EXPIRED', updated_at = ?
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                  AND status NOT IN ('COMPLETED','EXPIRED','CANCELLED','DEAD_LETTERED')
                """,
                (now, now),
            )
            conn.execute(
                """
                UPDATE agent_signal_deliveries SET state = 'EXPIRED', updated_at = ?
                WHERE signal_id IN (
                    SELECT signal_id FROM agent_signals WHERE status = 'EXPIRED'
                ) AND state IN ('PENDING','RETRY_WAIT','CLAIMED')
                """,
                (now,),
            )
            return int(cur.rowcount or 0)

    def purge_old_telemetry(self, *, older_than_days: int = 3) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))
        ).isoformat(timespec="seconds")
        with self.connect() as conn:
            ids = [
                r["signal_id"]
                for r in conn.execute(
                    """
                    SELECT signal_id FROM agent_signals
                    WHERE signal_type IN ('HEARTBEAT','PROGRESS')
                      AND priority = 'TELEMETRY'
                      AND created_at < ?
                    LIMIT 2000
                    """,
                    (cutoff,),
                ).fetchall()
            ]
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM agent_signal_deliveries WHERE signal_id IN ({placeholders})",
                ids,
            )
            cur = conn.execute(
                f"DELETE FROM agent_signals WHERE signal_id IN ({placeholders})",
                ids,
            )
            return int(cur.rowcount or 0)

    @staticmethod
    def new_id(prefix: str) -> str:
        return _new_id(prefix)


def _ensure_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_signals (
            signal_id TEXT PRIMARY KEY,
            signal_type TEXT NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            recipient_type TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            mission_id TEXT,
            run_id TEXT,
            trace_id TEXT,
            parent_signal_id TEXT,
            correlation_id TEXT,
            priority TEXT NOT NULL DEFAULT 'NORMAL',
            subject TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            artifact_refs_json TEXT NOT NULL DEFAULT '[]',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL,
            requires_ack INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            idempotency_key TEXT,
            hop_count INTEGER NOT NULL DEFAULT 0,
            max_hops INTEGER NOT NULL DEFAULT 8,
            status TEXT NOT NULL DEFAULT 'CREATED',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_signal_deliveries (
            delivery_id TEXT PRIMARY KEY,
            signal_id TEXT NOT NULL,
            recipient_type TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            resolved_agent_id TEXT,
            state TEXT NOT NULL DEFAULT 'PENDING',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            next_attempt_at TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            lease_expires_at TEXT,
            delivered_at TEXT,
            acknowledged_at TEXT,
            consumed_at TEXT,
            ack_consumer TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(signal_id) REFERENCES agent_signals(signal_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_signal_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            subscriber_type TEXT NOT NULL,
            subscriber_id TEXT NOT NULL,
            signal_type TEXT,
            role TEXT,
            capability TEXT,
            mission_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_signal_dead_letters (
            dead_letter_id TEXT PRIMARY KEY,
            signal_id TEXT NOT NULL,
            delivery_id TEXT,
            recipient_type TEXT,
            recipient_id TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            first_failure_at TEXT,
            last_failure_at TEXT,
            reason TEXT NOT NULL DEFAULT '',
            retryable INTEGER NOT NULL DEFAULT 1,
            signal_snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            retried_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_signal_dedupe (
            dedupe_key TEXT PRIMARY KEY,
            signal_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'signal',
            created_at TEXT NOT NULL
        )
        """
    )
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_created ON agent_signals(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_type ON agent_signals(signal_type)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_mission ON agent_signals(mission_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_run ON agent_signals(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_trace ON agent_signals(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_sender ON agent_signals(sender_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_recipient ON agent_signals(recipient_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_correlation ON agent_signals(correlation_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_signals_idempotency "
        "ON agent_signals(idempotency_key) WHERE idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_agent_signal_deliveries_state "
        "ON agent_signal_deliveries(state, next_attempt_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signal_deliveries_recipient "
        "ON agent_signal_deliveries(recipient_id, state)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signal_deliveries_signal "
        "ON agent_signal_deliveries(signal_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_signal_dead_letters_created "
        "ON agent_signal_dead_letters(created_at)",
    ):
        conn.execute(ddl)
