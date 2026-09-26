"""Persistent repositories for institutional_core against the canonical LEVIATHAN DB.

Uses MarketSimStore.db_path / MigrationRunner — never a second metadata database.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from Data.modules.common.sqlite_policy import open_sqlite_connection

from .timeutil import now_canonical, to_canonical


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class InstitutionalRepository:
    """Runtime owner for migration 55+ institutional tables."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
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

    def ensure_schema(self) -> None:
        from Data.backend.db_upgrade import ensure_domain_schema
        from Data.modules.common.database_domains import DatabaseDomain

        ensure_domain_schema(self.db_path, DatabaseDomain.MARKET)

    # --- Instruments ---

    def upsert_instrument(self, instrument: Mapping[str, Any]) -> dict[str, Any]:
        now = now_canonical()
        row = {
            "instrument_id": str(instrument["instrument_id"]),
            "family": str(instrument.get("family") or ""),
            "primary_symbol": str(instrument.get("primary_symbol") or "").upper(),
            "currency": str(instrument.get("currency") or "").upper(),
            "exchange": str(instrument.get("exchange") or ""),
            "multiplier": str(instrument.get("multiplier") or "1"),
            "valid_from": to_canonical(instrument.get("valid_from") or "1970-01-01T00:00:00+00:00"),
            "valid_to": (
                to_canonical(instrument["valid_to"])
                if instrument.get("valid_to")
                else ""
            ),
            "attributes_json": _canon(instrument.get("attributes") or {}),
            "status": str(instrument.get("status") or "ACTIVE"),
            "created_at": str(instrument.get("created_at") or now),
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_instruments(
                    instrument_id, family, primary_symbol, currency, exchange,
                    multiplier, valid_from, valid_to, attributes_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id) DO UPDATE SET
                    family=excluded.family,
                    primary_symbol=excluded.primary_symbol,
                    currency=excluded.currency,
                    exchange=excluded.exchange,
                    multiplier=excluded.multiplier,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    attributes_json=excluded.attributes_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    row["instrument_id"],
                    row["family"],
                    row["primary_symbol"],
                    row["currency"],
                    row["exchange"],
                    row["multiplier"],
                    row["valid_from"],
                    row["valid_to"],
                    row["attributes_json"],
                    row["status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        return row

    def upsert_alias(self, alias: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "alias_id": str(alias.get("alias_id") or uuid.uuid4()),
            "alias": str(alias["alias"]).upper(),
            "alias_type": str(alias.get("alias_type") or "ticker"),
            "instrument_id": str(alias["instrument_id"]),
            "valid_from": to_canonical(alias.get("valid_from") or "1970-01-01T00:00:00+00:00"),
            "valid_to": to_canonical(alias["valid_to"]) if alias.get("valid_to") else "",
            "source": str(alias.get("source") or ""),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_instrument_aliases(
                    alias_id, alias, alias_type, instrument_id,
                    valid_from, valid_to, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alias_id) DO UPDATE SET
                    alias=excluded.alias,
                    alias_type=excluded.alias_type,
                    instrument_id=excluded.instrument_id,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    source=excluded.source
                """,
                (
                    row["alias_id"],
                    row["alias"],
                    row["alias_type"],
                    row["instrument_id"],
                    row["valid_from"],
                    row["valid_to"],
                    row["source"],
                ),
            )
        return row

    def get_instrument(self, instrument_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_instruments WHERE instrument_id = ?",
                (instrument_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def list_aliases_for(self, alias: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_instrument_aliases WHERE alias = ? ORDER BY alias_id",
                (str(alias).upper(),),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def list_instruments(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_instruments ORDER BY primary_symbol LIMIT ?",
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # --- Breaks / reconciliation ---

    def upsert_break(self, brk: Mapping[str, Any]) -> dict[str, Any]:
        now = now_canonical()
        row = {
            "break_id": str(brk["break_id"]),
            "domain": str(brk.get("domain") or ""),
            "field": str(brk.get("field") or ""),
            "left_system": str(brk.get("left_system") or ""),
            "right_system": str(brk.get("right_system") or ""),
            "left_key": str(brk.get("left_key") or ""),
            "right_key": str(brk.get("right_key") or ""),
            "left_value": None if brk.get("left_value") is None else _canon(brk.get("left_value")),
            "right_value": None if brk.get("right_value") is None else _canon(brk.get("right_value")),
            "status": str(brk.get("status") or "OPEN"),
            "fingerprint": str(brk.get("fingerprint") or ""),
            "correlation_id": brk.get("correlation_id"),
            "history_json": _canon(brk.get("history") or []),
            "explanation": brk.get("explanation"),
            "created_at": str(brk.get("created_at") or now),
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_breaks(
                    break_id, domain, field, left_system, right_system,
                    left_key, right_key, left_value, right_value, status,
                    fingerprint, correlation_id, history_json, explanation,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(break_id) DO UPDATE SET
                    status=excluded.status,
                    history_json=excluded.history_json,
                    explanation=excluded.explanation,
                    correlation_id=excluded.correlation_id,
                    updated_at=excluded.updated_at
                """,
                (
                    row["break_id"],
                    row["domain"],
                    row["field"],
                    row["left_system"],
                    row["right_system"],
                    row["left_key"],
                    row["right_key"],
                    row["left_value"],
                    row["right_value"],
                    row["status"],
                    row["fingerprint"],
                    row["correlation_id"],
                    row["history_json"],
                    row["explanation"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        return row

    def list_breaks(self, *, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM institutional_breaks WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, int(limit)),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM institutional_breaks ORDER BY updated_at DESC LIMIT ?",
                    (int(limit),),
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def get_break(self, break_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_breaks WHERE break_id = ?",
                (break_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    # --- Decision packets ---

    def upsert_decision_packet(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "decision_id": str(packet["decision_id"]),
            "packet_hash": str(packet.get("packet_hash") or ""),
            "payload_json": _canon(packet.get("payload") or {}),
            "created_at": str(packet.get("created_at") or now_canonical()),
            "actor": str(packet.get("actor") or ""),
            "status": str(packet.get("status") or "RECORDED"),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_decision_packets(
                    decision_id, packet_hash, payload_json, created_at, actor, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    packet_hash=excluded.packet_hash,
                    payload_json=excluded.payload_json,
                    status=excluded.status
                """,
                (
                    row["decision_id"],
                    row["packet_hash"],
                    row["payload_json"],
                    row["created_at"],
                    row["actor"],
                    row["status"],
                ),
            )
        return row

    def get_decision_packet(self, decision_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_decision_packets WHERE decision_id = ?",
                (decision_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            out = dict(zip(cols, row))
            out["payload"] = json.loads(out.pop("payload_json") or "{}")
            return out

    def list_decision_packets(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_decision_packets ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                rows.append(item)
            return rows

    # --- Audit chain ---

    def append_audit_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        import hashlib

        with self.connect() as conn:
            prev = conn.execute(
                "SELECT event_hash FROM institutional_audit_chain ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev[0] if prev else ("0" * 64)
            event_id = str(event.get("event_id") or uuid.uuid4())
            kind = str(event.get("kind") or "")
            actor = str(event.get("actor") or "")
            detail = str(event.get("detail") or "")
            ts = str(event.get("ts") or now_canonical())
            metadata = dict(event.get("metadata") or {})
            body = _canon(
                {
                    "event_id": event_id,
                    "kind": kind,
                    "actor": actor,
                    "detail": detail,
                    "ts": ts,
                    "prev_hash": prev_hash,
                    "metadata": metadata,
                }
            )
            event_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO institutional_audit_chain(
                    event_id, kind, actor, detail, ts, prev_hash, event_hash, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, kind, actor, detail, ts, prev_hash, event_hash, _canon(metadata)),
            )
            return {
                "event_id": event_id,
                "kind": kind,
                "actor": actor,
                "detail": detail,
                "ts": ts,
                "prev_hash": prev_hash,
                "event_hash": event_hash,
                "metadata": metadata,
            }

    def list_audit_events(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_audit_chain ORDER BY seq ASC LIMIT ?",
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                rows.append(item)
            return rows

    def verify_audit_chain(self) -> dict[str, Any]:
        import hashlib

        events = self.list_audit_events(limit=100_000)
        prev = "0" * 64
        for ev in events:
            body = _canon(
                {
                    "event_id": ev["event_id"],
                    "kind": ev["kind"],
                    "actor": ev["actor"],
                    "detail": ev["detail"],
                    "ts": ev["ts"],
                    "prev_hash": prev,
                    "metadata": ev.get("metadata") or {},
                }
            )
            expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if ev.get("prev_hash") != prev or ev.get("event_hash") != expected:
                return {
                    "ok": False,
                    "status": "FAIL",
                    "brokenAt": ev.get("event_id"),
                    "count": len(events),
                }
            prev = ev["event_hash"]
        return {"ok": True, "status": "PASS", "count": len(events)}

    # --- Exceptions ---

    def upsert_exception(self, exc: Mapping[str, Any]) -> dict[str, Any]:
        now = now_canonical()
        row = {
            "exception_id": str(exc["exception_id"]),
            "kind": str(exc.get("kind") or ""),
            "severity": str(exc.get("severity") or ""),
            "status": str(exc.get("status") or "OPEN"),
            "owner": str(exc.get("owner") or ""),
            "first_seen": str(exc.get("first_seen") or now),
            "last_seen": now,
            "evidence_json": _canon(exc.get("evidence") or {}),
            "linked_json": _canon(exc.get("linked") or {}),
            "remediation": exc.get("remediation"),
            "resolution": exc.get("resolution"),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_exceptions(
                    exception_id, kind, severity, status, owner,
                    first_seen, last_seen, evidence_json, linked_json,
                    remediation, resolution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exception_id) DO UPDATE SET
                    status=excluded.status,
                    last_seen=excluded.last_seen,
                    evidence_json=excluded.evidence_json,
                    linked_json=excluded.linked_json,
                    remediation=excluded.remediation,
                    resolution=excluded.resolution,
                    severity=excluded.severity,
                    owner=excluded.owner
                """,
                (
                    row["exception_id"],
                    row["kind"],
                    row["severity"],
                    row["status"],
                    row["owner"],
                    row["first_seen"],
                    row["last_seen"],
                    row["evidence_json"],
                    row["linked_json"],
                    row["remediation"],
                    row["resolution"],
                ),
            )
        return row

    def list_exceptions(self, *, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM institutional_exceptions WHERE status = ? ORDER BY last_seen DESC LIMIT ?",
                    (status, int(limit)),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM institutional_exceptions ORDER BY last_seen DESC LIMIT ?",
                    (int(limit),),
                )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
                item["linked"] = json.loads(item.pop("linked_json") or "{}")
                rows.append(item)
            return rows

    # --- Extended tables (migration 56+) ---

    def append_ibor_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "event_id": str(event["event_id"]),
            "portfolio_id": str(event.get("portfolio_id") or ""),
            "sequence": int(event.get("sequence") or 0),
            "kind": str(event.get("kind") or "").upper(),
            "ts": to_canonical(event.get("ts") or now_canonical()),
            "payload_json": _canon(event.get("payload") or {}),
            "idempotency_key": str(event.get("idempotency_key") or event["event_id"]),
        }
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT event_id FROM institutional_ibor_events WHERE idempotency_key = ?",
                (row["idempotency_key"],),
            ).fetchone()
            if existing:
                return {**row, "duplicate": True, "event_id": existing[0]}
            conn.execute(
                """
                INSERT INTO institutional_ibor_events(
                    event_id, portfolio_id, sequence, kind, ts, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["event_id"],
                    row["portfolio_id"],
                    row["sequence"],
                    row["kind"],
                    row["ts"],
                    row["payload_json"],
                    row["idempotency_key"],
                ),
            )
        return {**row, "duplicate": False}

    def list_ibor_events(self, portfolio_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM institutional_ibor_events
                WHERE portfolio_id = ?
                ORDER BY sequence ASC, event_id ASC
                """,
                (portfolio_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                rows.append(item)
            return rows

    def next_ibor_sequence(self, portfolio_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM institutional_ibor_events WHERE portfolio_id = ?",
                (portfolio_id,),
            ).fetchone()
            return int(row[0] or 0) + 1

    def append_journal_entry(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "entry_id": str(entry["entry_id"]),
            "portfolio_id": str(entry.get("portfolio_id") or ""),
            "ts": to_canonical(entry.get("ts") or now_canonical()),
            "kind": str(entry.get("kind") or ""),
            "lines_json": _canon(entry.get("lines") or []),
            "refs_json": _canon(entry.get("refs") or {}),
            "currency": str(entry.get("currency") or "").upper(),
            "idempotency_key": str(entry.get("idempotency_key") or entry["entry_id"]),
            "status": str(entry.get("status") or "POSTED"),
        }
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT entry_id FROM institutional_journal_entries WHERE idempotency_key = ?",
                (row["idempotency_key"],),
            ).fetchone()
            if existing:
                return {**row, "duplicate": True, "entry_id": existing[0]}
            conn.execute(
                """
                INSERT INTO institutional_journal_entries(
                    entry_id, portfolio_id, ts, kind, lines_json, refs_json,
                    currency, idempotency_key, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["entry_id"],
                    row["portfolio_id"],
                    row["ts"],
                    row["kind"],
                    row["lines_json"],
                    row["refs_json"],
                    row["currency"],
                    row["idempotency_key"],
                    row["status"],
                ),
            )
        return {**row, "duplicate": False}

    def list_journal_entries(self, portfolio_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM institutional_journal_entries
                WHERE portfolio_id = ?
                ORDER BY ts ASC, entry_id ASC
                """,
                (portfolio_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["lines"] = json.loads(item.pop("lines_json") or "[]")
                item["refs"] = json.loads(item.pop("refs_json") or "{}")
                rows.append(item)
            return rows

    def upsert_recon_run(self, run: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "run_id": str(run["run_id"]),
            "domain": str(run.get("domain") or ""),
            "contract_json": _canon(run.get("contract") or {}),
            "status": str(run.get("status") or ""),
            "open_count": int(run.get("open_count") or 0),
            "break_count": int(run.get("break_count") or 0),
            "payload_json": _canon(run.get("payload") or {}),
            "created_at": str(run.get("created_at") or now_canonical()),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_recon_runs(
                    run_id, domain, contract_json, status, open_count,
                    break_count, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    open_count=excluded.open_count,
                    break_count=excluded.break_count,
                    payload_json=excluded.payload_json
                """,
                (
                    row["run_id"],
                    row["domain"],
                    row["contract_json"],
                    row["status"],
                    row["open_count"],
                    row["break_count"],
                    row["payload_json"],
                    row["created_at"],
                ),
            )
        return row

    def list_recon_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_recon_runs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["contract"] = json.loads(item.pop("contract_json") or "{}")
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                rows.append(item)
            return rows

    def upsert_mandate(self, mandate: Mapping[str, Any]) -> dict[str, Any]:
        now = now_canonical()
        row = {
            "mandate_id": str(mandate["mandate_id"]),
            "portfolio_id": str(mandate.get("portfolio_id") or ""),
            "version": int(mandate.get("version") or 1),
            "payload_json": _canon(mandate.get("payload") or {}),
            "fingerprint": str(mandate.get("fingerprint") or ""),
            "status": str(mandate.get("status") or "ACTIVE"),
            "created_at": str(mandate.get("created_at") or now),
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_mandates(
                    mandate_id, portfolio_id, version, payload_json,
                    fingerprint, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mandate_id) DO UPDATE SET
                    version=excluded.version,
                    payload_json=excluded.payload_json,
                    fingerprint=excluded.fingerprint,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    row["mandate_id"],
                    row["portfolio_id"],
                    row["version"],
                    row["payload_json"],
                    row["fingerprint"],
                    row["status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        return row

    def get_mandate_for_portfolio(self, portfolio_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM institutional_mandates
                WHERE portfolio_id = ? AND status = 'ACTIVE'
                ORDER BY version DESC LIMIT 1
                """,
                (portfolio_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            item = dict(zip(cols, row))
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            return item

    def upsert_workflow_checkpoint(self, cp: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "workflow_id": str(cp["workflow_id"]),
            "job_id": str(cp.get("job_id") or ""),
            "step_index": int(cp.get("step_index") or 0),
            "state_json": _canon(cp.get("state") or {}),
            "status": str(cp.get("status") or "RUNNING"),
            "updated_at": now_canonical(),
            "idempotency_key": str(cp.get("idempotency_key") or cp["workflow_id"]),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_workflow_checkpoints(
                    workflow_id, job_id, step_index, state_json, status,
                    updated_at, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    step_index=excluded.step_index,
                    state_json=excluded.state_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    row["workflow_id"],
                    row["job_id"],
                    row["step_index"],
                    row["state_json"],
                    row["status"],
                    row["updated_at"],
                    row["idempotency_key"],
                ),
            )
        return row

    def get_workflow_checkpoint(self, workflow_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_workflow_checkpoints WHERE workflow_id = ?",
                (workflow_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            item = dict(zip(cols, row))
            item["state"] = json.loads(item.pop("state_json") or "{}")
            return item

    def upsert_valuation_snapshot(self, snap: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "snapshot_id": str(snap["snapshot_id"]),
            "portfolio_id": str(snap.get("portfolio_id") or ""),
            "as_of": to_canonical(snap.get("as_of") or now_canonical()),
            "base_currency": str(snap.get("base_currency") or "").upper(),
            "payload_json": _canon(snap.get("payload") or {}),
            "quality": str(snap.get("quality") or "OBSERVED"),
            "created_at": now_canonical(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_valuation_snapshots(
                    snapshot_id, portfolio_id, as_of, base_currency,
                    payload_json, quality, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    quality=excluded.quality
                """,
                (
                    row["snapshot_id"],
                    row["portfolio_id"],
                    row["as_of"],
                    row["base_currency"],
                    row["payload_json"],
                    row["quality"],
                    row["created_at"],
                ),
            )
        return row

    def upsert_bitemporal_record(self, rec: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "record_id": str(rec["record_id"]),
            "entity_type": str(rec.get("entity_type") or ""),
            "entity_id": str(rec.get("entity_id") or ""),
            "effective_time": to_canonical(rec["effective_time"]),
            "observed_at": to_canonical(rec.get("observed_at") or rec["effective_time"]),
            "recorded_at": to_canonical(rec.get("recorded_at") or now_canonical()),
            "superseded_at": (
                to_canonical(rec["superseded_at"]) if rec.get("superseded_at") else ""
            ),
            "source": str(rec.get("source") or ""),
            "source_version": str(rec.get("source_version") or ""),
            "payload_json": _canon(rec.get("payload") or {}),
            "quality": str(rec.get("quality") or "OBSERVED"),
            "content_hash": str(rec.get("content_hash") or ""),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_bitemporal_records(
                    record_id, entity_type, entity_id, effective_time, observed_at,
                    recorded_at, superseded_at, source, source_version,
                    payload_json, quality, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    superseded_at=excluded.superseded_at,
                    payload_json=excluded.payload_json,
                    quality=excluded.quality
                """,
                (
                    row["record_id"],
                    row["entity_type"],
                    row["entity_id"],
                    row["effective_time"],
                    row["observed_at"],
                    row["recorded_at"],
                    row["superseded_at"],
                    row["source"],
                    row["source_version"],
                    row["payload_json"],
                    row["quality"],
                    row["content_hash"],
                ),
            )
        return row

    def query_bitemporal_as_of(
        self,
        *,
        entity_type: str,
        entity_id: str,
        as_of: str,
        knowledge_time: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return versions effective at as_of that were known by knowledge_time."""
        from .timeutil import parse_ts, ts_le

        knowledge = knowledge_time or now_canonical()
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM institutional_bitemporal_records
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY recorded_at ASC
                """,
                (entity_type, entity_id),
            )
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                if not ts_le(item["effective_time"], as_of):
                    continue
                if not ts_le(item["recorded_at"], knowledge):
                    continue
                if item.get("superseded_at") and ts_le(item["superseded_at"], knowledge):
                    continue
                out.append(item)
            # Keep latest by effective_time among survivors
            if not out:
                return []
            out.sort(key=lambda x: (parse_ts(x["effective_time"]), parse_ts(x["recorded_at"])))
            return [out[-1]]

    def upsert_approval_record(self, rec: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "approval_id": str(rec["approval_id"]),
            "change_id": str(rec.get("change_id") or ""),
            "kind": str(rec.get("kind") or ""),
            "maker_id": str(rec.get("maker_id") or ""),
            "checker_id": str(rec.get("checker_id") or ""),
            "status": str(rec.get("status") or ""),
            "payload_json": _canon(rec.get("payload") or {}),
            "created_at": str(rec.get("created_at") or now_canonical()),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_authority_approvals(
                    approval_id, change_id, kind, maker_id, checker_id,
                    status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    status=excluded.status,
                    checker_id=excluded.checker_id,
                    payload_json=excluded.payload_json
                """,
                (
                    row["approval_id"],
                    row["change_id"],
                    row["kind"],
                    row["maker_id"],
                    row["checker_id"],
                    row["status"],
                    row["payload_json"],
                    row["created_at"],
                ),
            )
        return row

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM institutional_authority_approvals WHERE approval_id = ?",
                (approval_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            item = dict(zip(cols, row))
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            return item
