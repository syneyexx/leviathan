"""Cognitive persistence — versioned, rebuildable derived indexes.

Owns only cognitive-pillar tables on the shared HADES SQLite file.
Does not replace Gen2Store, database.py, or platform_db ownership.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .contracts import new_id, utc_now


SCHEMA_VERSION = 1


class CognitiveStore:
    """Additive cognitive tables with an independent migration ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=15)
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

    def initialize(self) -> None:
        with self.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(r[0])
                for r in db.execute("SELECT version FROM cognitive_schema_migrations").fetchall()
            }
            if SCHEMA_VERSION not in applied:
                self._migrate_v1(db)
                db.execute(
                    "INSERT OR IGNORE INTO cognitive_schema_migrations(version, applied_at) VALUES(?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )

    def _migrate_v1(self, db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cognitive_decisions (
                id TEXT PRIMARY KEY,
                controller TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                mode TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cognitive_decisions_ctrl
                ON cognitive_decisions(controller, created_at);

            CREATE TABLE IF NOT EXISTS cognitive_quarantine (
                id TEXT PRIMARY KEY,
                artifact_kind TEXT NOT NULL,
                trust_category TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                released_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cognitive_quarantine_hash
                ON cognitive_quarantine(content_hash);

            CREATE TABLE IF NOT EXISTS cognitive_concepts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                definition TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL,
                scope TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                evidence_json TEXT NOT NULL,
                relations_json TEXT NOT NULL,
                supersedes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cognitive_concepts_name
                ON cognitive_concepts(name);

            CREATE TABLE IF NOT EXISTS cognitive_agent_models (
                agent_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cognitive_credit (
                id TEXT PRIMARY KEY,
                outcome_ref TEXT NOT NULL,
                decision_ref TEXT NOT NULL,
                actor_ref TEXT,
                contribution_type TEXT NOT NULL,
                polarity TEXT NOT NULL,
                confidence REAL,
                causal_evidence_level TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cognitive_credit_outcome
                ON cognitive_credit(outcome_ref);

            CREATE TABLE IF NOT EXISTS cognitive_hypotheses (
                id TEXT PRIMARY KEY,
                claim TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cognitive_repair_proposals (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cognitive_homeostasis_events (
                id TEXT PRIMARY KEY,
                signal TEXT NOT NULL,
                severity TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    # --- decisions / observability -------------------------------------------------

    def append_decision(self, decision: dict[str, Any]) -> str:
        did = str(decision.get("id") or new_id("cdec"))
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO cognitive_decisions(id, controller, decision, reason_code, mode, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    did,
                    str(decision.get("controller") or ""),
                    str(decision.get("decision") or ""),
                    str(decision.get("reason_code") or ""),
                    str(decision.get("mode") or "shadow"),
                    json.dumps(decision, ensure_ascii=False, sort_keys=True),
                    str(decision.get("timestamp") or utc_now()),
                ),
            )
        return did

    def list_decisions(self, *, controller: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            if controller:
                rows = db.execute(
                    """
                    SELECT payload_json FROM cognitive_decisions
                    WHERE controller=? ORDER BY created_at DESC LIMIT ?
                    """,
                    (controller, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT payload_json FROM cognitive_decisions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    # --- quarantine ----------------------------------------------------------------

    def quarantine(
        self,
        *,
        artifact_kind: str,
        trust_category: str,
        reason_code: str,
        content_hash: str,
        provenance: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        qid = new_id("cq")
        now = utc_now()
        record = {
            "id": qid,
            "artifact_kind": artifact_kind,
            "trust_category": trust_category,
            "reason_code": reason_code,
            "content_hash": content_hash,
            "provenance": provenance or {},
            "payload": payload or {},
            "created_at": now,
            "released_at": None,
        }
        with self.connection() as db:
            existing = db.execute(
                "SELECT id, payload_json FROM cognitive_quarantine WHERE content_hash=? AND released_at IS NULL",
                (content_hash,),
            ).fetchone()
            if existing:
                prior = json.loads(existing["payload_json"])
                prior["already_quarantined"] = True
                return prior
            db.execute(
                """
                INSERT INTO cognitive_quarantine(
                    id, artifact_kind, trust_category, reason_code, content_hash,
                    provenance_json, payload_json, created_at, released_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    qid,
                    artifact_kind,
                    trust_category,
                    reason_code,
                    content_hash,
                    json.dumps(provenance or {}, ensure_ascii=False),
                    json.dumps(record, ensure_ascii=False),
                    now,
                ),
            )
        return record

    def list_quarantine(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT payload_json FROM cognitive_quarantine
                WHERE released_at IS NULL
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def is_quarantined(self, content_hash: str) -> bool:
        with self.connection() as db:
            row = db.execute(
                "SELECT 1 FROM cognitive_quarantine WHERE content_hash=? AND released_at IS NULL LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    # --- concepts ------------------------------------------------------------------

    def upsert_concept(self, concept: dict[str, Any]) -> dict[str, Any]:
        cid = str(concept.get("id") or new_id("concept"))
        now = utc_now()
        name = str(concept.get("name") or "").strip().lower()
        with self.connection() as db:
            existing = db.execute(
                "SELECT * FROM cognitive_concepts WHERE name=?",
                (name,),
            ).fetchone()
            if existing:
                cid = existing["id"]
                evidence = json.loads(existing["evidence_json"] or "[]")
                incoming = list(concept.get("supporting_examples") or concept.get("evidence") or [])
                for item in incoming:
                    if item not in evidence:
                        evidence.append(item)
                relations = json.loads(existing["relations_json"] or "[]")
                for rel in list(concept.get("relations") or []):
                    if rel not in relations:
                        relations.append(rel)
                version = int(existing["version"] or 1) + (1 if concept.get("promote") else 0)
                status = str(concept.get("status") or existing["status"])
                db.execute(
                    """
                    UPDATE cognitive_concepts
                    SET definition=?, status=?, confidence=?, scope=?, version=?,
                        evidence_json=?, relations_json=?, supersedes=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        str(concept.get("definition") or existing["definition"]),
                        status,
                        concept.get("confidence", existing["confidence"]),
                        concept.get("scope", existing["scope"]),
                        version,
                        json.dumps(evidence, ensure_ascii=False),
                        json.dumps(relations, ensure_ascii=False),
                        concept.get("supersedes", existing["supersedes"]),
                        now,
                        cid,
                    ),
                )
                out = dict(concept)
                out.update(
                    {
                        "id": cid,
                        "name": name,
                        "evidence": evidence,
                        "relations": relations,
                        "version": version,
                        "status": status,
                        "updated_at": now,
                    }
                )
                return out
            evidence = list(concept.get("supporting_examples") or concept.get("evidence") or [])
            relations = list(concept.get("relations") or [])
            record = {
                "id": cid,
                "name": name,
                "definition": str(concept.get("definition") or ""),
                "status": str(concept.get("status") or "candidate"),
                "confidence": concept.get("confidence"),
                "scope": concept.get("scope"),
                "version": int(concept.get("version") or 1),
                "evidence": evidence,
                "relations": relations,
                "supersedes": concept.get("supersedes"),
                "created_at": now,
                "updated_at": now,
            }
            db.execute(
                """
                INSERT INTO cognitive_concepts(
                    id, name, definition, status, confidence, scope, version,
                    evidence_json, relations_json, supersedes, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    name,
                    record["definition"],
                    record["status"],
                    record["confidence"],
                    record["scope"],
                    record["version"],
                    json.dumps(evidence, ensure_ascii=False),
                    json.dumps(relations, ensure_ascii=False),
                    record["supersedes"],
                    now,
                    now,
                ),
            )
            return record

    def get_concept_by_name(self, name: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM cognitive_concepts WHERE name=?",
                (str(name or "").strip().lower(),),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "definition": row["definition"],
            "status": row["status"],
            "confidence": row["confidence"],
            "scope": row["scope"],
            "version": row["version"],
            "evidence": json.loads(row["evidence_json"] or "[]"),
            "relations": json.loads(row["relations_json"] or "[]"),
            "supersedes": row["supersedes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_concepts(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM cognitive_concepts WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM cognitive_concepts ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "definition": row["definition"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "scope": row["scope"],
                    "version": row["version"],
                    "evidence": json.loads(row["evidence_json"] or "[]"),
                    "relations": json.loads(row["relations_json"] or "[]"),
                    "supersedes": row["supersedes"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    # --- agent models --------------------------------------------------------------

    def upsert_agent_model(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        record = dict(payload)
        record["agent_id"] = agent_id
        record["updated_at"] = now
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO cognitive_agent_models(agent_id, payload_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (agent_id, json.dumps(record, ensure_ascii=False), now),
            )
        return record

    def get_agent_model(self, agent_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload_json FROM cognitive_agent_models WHERE agent_id=?",
                (agent_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_agent_models(self, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload_json FROM cognitive_agent_models ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    # --- credit --------------------------------------------------------------------

    def append_credit(self, record: dict[str, Any]) -> str:
        cid = str(record.get("id") or new_id("credit"))
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO cognitive_credit(
                    id, outcome_ref, decision_ref, actor_ref, contribution_type,
                    polarity, confidence, causal_evidence_level, evidence_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    str(record.get("outcome_ref") or ""),
                    str(record.get("decision_ref") or ""),
                    record.get("actor_ref"),
                    str(record.get("contribution_type") or "unknown"),
                    str(record.get("polarity") or "neutral"),
                    record.get("confidence"),
                    str(record.get("causal_evidence_level") or "coincidental"),
                    json.dumps(record.get("evidence_refs") or [], ensure_ascii=False),
                    now,
                ),
            )
        return cid

    def list_credit(self, *, outcome_ref: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            if outcome_ref:
                rows = db.execute(
                    "SELECT * FROM cognitive_credit WHERE outcome_ref=? ORDER BY created_at DESC LIMIT ?",
                    (outcome_ref, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM cognitive_credit ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "id": r["id"],
                "outcome_ref": r["outcome_ref"],
                "decision_ref": r["decision_ref"],
                "actor_ref": r["actor_ref"],
                "contribution_type": r["contribution_type"],
                "polarity": r["polarity"],
                "confidence": r["confidence"],
                "causal_evidence_level": r["causal_evidence_level"],
                "evidence_refs": json.loads(r["evidence_json"] or "[]"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # --- hypotheses / repair / homeostasis ----------------------------------------

    def upsert_hypothesis(self, hypothesis: dict[str, Any]) -> dict[str, Any]:
        hid = str(hypothesis.get("id") or new_id("hyp"))
        now = utc_now()
        record = dict(hypothesis)
        record["id"] = hid
        record.setdefault("created_at", now)
        record["updated_at"] = now
        with self.connection() as db:
            existing = db.execute("SELECT id FROM cognitive_hypotheses WHERE id=?", (hid,)).fetchone()
            if existing:
                db.execute(
                    """
                    UPDATE cognitive_hypotheses
                    SET claim=?, scope=?, status=?, payload_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        str(record.get("claim") or ""),
                        str(record.get("scope") or ""),
                        str(record.get("status") or "open"),
                        json.dumps(record, ensure_ascii=False),
                        now,
                        hid,
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO cognitive_hypotheses(id, claim, scope, status, payload_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hid,
                        str(record.get("claim") or ""),
                        str(record.get("scope") or ""),
                        str(record.get("status") or "open"),
                        json.dumps(record, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        return record

    def get_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload_json FROM cognitive_hypotheses WHERE id=?",
                (hypothesis_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_hypotheses(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            if status:
                rows = db.execute(
                    "SELECT payload_json FROM cognitive_hypotheses WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT payload_json FROM cognitive_hypotheses ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def upsert_repair_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        rid = str(proposal.get("id") or new_id("repair"))
        now = utc_now()
        record = dict(proposal)
        record["id"] = rid
        record.setdefault("created_at", now)
        record["updated_at"] = now
        with self.connection() as db:
            existing = db.execute("SELECT id FROM cognitive_repair_proposals WHERE id=?", (rid,)).fetchone()
            if existing:
                db.execute(
                    """
                    UPDATE cognitive_repair_proposals
                    SET trigger=?, status=?, payload_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        str(record.get("trigger") or ""),
                        str(record.get("status") or "proposed"),
                        json.dumps(record, ensure_ascii=False),
                        now,
                        rid,
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO cognitive_repair_proposals(id, trigger, status, payload_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        str(record.get("trigger") or ""),
                        str(record.get("status") or "proposed"),
                        json.dumps(record, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        return record

    def list_repair_proposals(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload_json FROM cognitive_repair_proposals ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def append_homeostasis_event(self, event: dict[str, Any]) -> str:
        eid = str(event.get("id") or new_id("homeo"))
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO cognitive_homeostasis_events(id, signal, severity, action, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    str(event.get("signal") or ""),
                    str(event.get("severity") or "medium"),
                    str(event.get("action") or ""),
                    json.dumps(event, ensure_ascii=False),
                    now,
                ),
            )
        return eid

    def list_homeostasis_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload_json FROM cognitive_homeostasis_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]
