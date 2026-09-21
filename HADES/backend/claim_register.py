"""Claim register over Memory/Knowledge/Evidence/Temporal graph concepts (Phase I).

In-memory + optional SQLite persistence. Prevents circular confirmation of derived AI answers.

Verification statuses are honest enums derived from observable evidence signals —
never invent probabilistic “expertise” confidence.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _id() -> str:
    return f"claim_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Canonical claim/evidence verification states (uppercase).
SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
CONTRADICTED = "CONTRADICTED"
UNVERIFIED = "UNVERIFIED"
STALE = "STALE"
SUPERSEDED = "SUPERSEDED"

CLAIM_VERIFICATION_STATES = frozenset(
    {
        SUPPORTED,
        PARTIALLY_SUPPORTED,
        CONTRADICTED,
        UNVERIFIED,
        STALE,
        SUPERSEDED,
    }
)

# Legacy / lowercase aliases → canonical.
_STATUS_ALIASES: dict[str, str] = {
    "supported": SUPPORTED,
    "partially_supported": PARTIALLY_SUPPORTED,
    "partial": PARTIALLY_SUPPORTED,
    "partially-supported": PARTIALLY_SUPPORTED,
    "contradicted": CONTRADICTED,
    "conflict": CONTRADICTED,
    "conflicting": CONTRADICTED,
    "unverified": UNVERIFIED,
    "pending": UNVERIFIED,
    "unknown": UNVERIFIED,
    "revised": UNVERIFIED,  # new claim after supersede starts unverified
    "stale": STALE,
    "expired": STALE,
    "superseded": SUPERSEDED,
    "obsolete": SUPERSEDED,
}

EVIDENCE_RELATIONS = frozenset({"supports", "contradicts"})


def normalize_verification_status(raw: str | None, *, default: str = UNVERIFIED) -> str:
    """Map free-form status strings onto the canonical claim states."""
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    upper = text.upper().replace("-", "_").replace(" ", "_")
    if upper in CLAIM_VERIFICATION_STATES:
        return upper
    mapped = _STATUS_ALIASES.get(text.lower().replace("-", "_").replace(" ", "_"))
    if mapped:
        return mapped
    return default


DERIVED_SOURCE_TYPES = frozenset(
    {"ai_answer", "derived", "assistant", "model_output", "derived_analysis", "chat_summary", "conversation"}
)


def is_derived_knowledge_record(record: dict[str, Any]) -> bool:
    """True when a Knowledge hit cannot serve as independent confirmation."""
    st = str(record.get("source_type") or "").strip().lower()
    uri = str(record.get("uri") or record.get("provenance") or "").strip().lower()
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if not meta and isinstance(record.get("metadata"), str):
        try:
            meta = json.loads(record["metadata"])
        except json.JSONDecodeError:
            meta = {}
    kind = str(meta.get("source_kind") or meta.get("kind") or "").strip().lower()
    if st in DERIVED_SOURCE_TYPES or kind in DERIVED_SOURCE_TYPES:
        return True
    if uri.startswith("knowledge:derived") or uri.startswith("ai:") or uri.startswith("assistant:"):
        return True
    if uri.startswith("conversation:"):
        return True
    return False


def is_active_conversation_knowledge(record: dict[str, Any], conversation_id: str | None) -> bool:
    """True when a hit is the indexed transcript of the conversation currently being answered."""
    if not conversation_id:
        return False
    cid = str(conversation_id)
    uri = str(record.get("uri") or record.get("provenance") or "")
    if uri == f"conversation:{cid}" or uri.endswith(f"/{cid}") or f"conversation:{cid}" in uri:
        return True
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if not meta and isinstance(record.get("metadata"), str):
        try:
            meta = json.loads(record["metadata"])
        except json.JSONDecodeError:
            meta = {}
    if str(meta.get("conversation_id") or "") == cid:
        return True
    return False


def filter_circular_knowledge(
    matches: list[dict[str, Any]],
    *,
    exclude_derived: bool = True,
    active_conversation_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split knowledge hits into independent vs derived (circular-risk) lists.

    Active-conversation transcripts are always treated as circular for the live
    chat turn — they already appear in message history.
    """
    independent: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    for item in matches:
        row = dict(item)
        if is_active_conversation_knowledge(row, active_conversation_id) or is_derived_knowledge_record(row):
            row["circular_risk"] = True
            row["independent_confirmation"] = False
            if is_active_conversation_knowledge(row, active_conversation_id):
                row["excluded_reason"] = "active_conversation_transcript"
            derived.append(row)
        else:
            row["circular_risk"] = False
            row["independent_confirmation"] = True
            independent.append(row)
    if exclude_derived:
        return independent, derived
    return independent + derived, derived


def _parse_iso_instant(value: str | None) -> datetime | None:
    """Parse ISO-8601 timestamps as absolute instants.

    Supports timezone offsets and trailing Z. Historical naive timestamps are
    interpreted as UTC so existing persisted claim rows stay deterministic.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            # Tolerate fractional-second truncation / minor format drift.
            parsed = datetime.fromisoformat(text[:19])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_utc(value: str | None) -> float | None:
    """Legacy epoch helper; prefer `_parse_iso_instant` for new comparisons."""
    instant = _parse_iso_instant(value)
    if instant is None:
        return None
    return instant.timestamp()


def _is_past_valid_until(valid_until: str | None, *, now: str | None = None) -> bool:
    """True when valid_until is strictly before now as absolute UTC instants."""
    if not valid_until:
        return False
    current = now or _now()
    parsed_vu = _parse_iso_instant(str(valid_until).strip())
    parsed_now = _parse_iso_instant(str(current).strip())
    if parsed_vu is not None and parsed_now is not None:
        return parsed_vu < parsed_now
    # Last-resort lexical compare for non-ISO forms already used historically.
    vu = str(valid_until).strip()
    cur = str(current).strip()
    if len(vu) >= 19 and len(cur) >= 19:
        return vu[:19] < cur[:19]
    return False


def collect_evidence_signals(claim: dict[str, Any]) -> dict[str, Any]:
    """Countable, observable signals used for status/confidence — no invented expertise."""
    supports = [str(x) for x in (claim.get("supports") or []) if str(x).strip()]
    contradicts = [str(x) for x in (claim.get("contradicts") or []) if str(x).strip()]
    evidence_links = claim.get("evidence_links") if isinstance(claim.get("evidence_links"), list) else []

    provenance = str(claim.get("provenance") or "")
    source_kind = str(claim.get("source_kind") or "")
    independent_supports: list[str] = []
    derived_supports: list[str] = []
    for eid in supports:
        derived_uri = is_derived_knowledge_record({"uri": eid})
        self_derived = source_kind == "derived_analysis" and eid == provenance
        if derived_uri or self_derived:
            derived_supports.append(eid)
        else:
            # Primary provenance cited as support counts as one primary signal;
            # multi-source independence uses distinct ids (see below).
            independent_supports.append(eid)

    # Deduplicate while preserving order.
    def _uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    independent_supports = _uniq(independent_supports)
    derived_supports = _uniq(derived_supports)
    contradicts = _uniq(contradicts)

    # Distinct independent sources beyond the claim's own provenance.
    distinct_independent = [e for e in independent_supports if e != provenance]

    return {
        "support_count": len(_uniq(supports)),
        "contradict_count": len(contradicts),
        "independent_support_count": len(independent_supports),
        "distinct_independent_support_count": len(distinct_independent),
        "derived_support_count": len(derived_supports),
        "evidence_link_count": len(evidence_links),
        "has_primary_provenance": source_kind == "primary" and bool(provenance),
        "past_valid_until": _is_past_valid_until(claim.get("valid_until")),
        "superseded": bool(claim.get("superseded_by")),
        "supports": independent_supports + derived_supports,
        "independent_supports": independent_supports,
        "derived_supports": derived_supports,
        "contradicts": contradicts,
    }


def derive_confidence_from_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Confidence from countable evidence signals only — never a fabricated expertise score.

    Returns confidence=None when there are no usable independent support/contradict signals.
    Otherwise a simple ratio in [0, 1] labeled as signal-derived.
    """
    independent = int(signals.get("independent_support_count") or 0)
    contradicts = int(signals.get("contradict_count") or 0)
    derived_only = int(signals.get("derived_support_count") or 0)

    usable = independent + contradicts
    if usable <= 0:
        return {
            "confidence": None,
            "confidence_basis": "observable_evidence_signals",
            "confidence_note": "No independent support/contradict signals — confidence withheld.",
            "signal_ratio_numerator": 0,
            "signal_ratio_denominator": 0,
            "derived_support_count": derived_only,
        }

    # Contradictions weigh equally with supports in the denominator (honest balance).
    numerator = independent
    denominator = independent + contradicts
    ratio = round(numerator / denominator, 4)
    return {
        "confidence": ratio,
        "confidence_basis": "observable_evidence_signals",
        "confidence_note": (
            "Ratio of independent supports to supports+contradicts; "
            "not a model-estimated expertise score."
        ),
        "signal_ratio_numerator": numerator,
        "signal_ratio_denominator": denominator,
        "derived_support_count": derived_only,
    }


def assess_verification_state(
    claim: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Derive verification_status + signal confidence from claim fields and evidence lists."""
    signals = collect_evidence_signals(claim)
    if now is not None:
        signals["past_valid_until"] = _is_past_valid_until(claim.get("valid_until"), now=now)

    confidence_meta = derive_confidence_from_signals(signals)

    if claim.get("superseded_by") or signals["superseded"]:
        status = SUPERSEDED
    elif signals["past_valid_until"]:
        status = STALE
    elif signals["contradict_count"] > 0 and signals["distinct_independent_support_count"] == 0 and signals["independent_support_count"] == 0:
        status = CONTRADICTED
    elif signals["contradict_count"] > 0 and (
        signals["distinct_independent_support_count"] > 0 or signals["independent_support_count"] > 0
    ):
        # Mixed evidence: contradicted when contradicts ≥ supports, else partial.
        if signals["contradict_count"] >= max(1, signals["distinct_independent_support_count"] or signals["independent_support_count"]):
            status = CONTRADICTED
        else:
            status = PARTIALLY_SUPPORTED
    elif signals["distinct_independent_support_count"] >= 2:
        status = SUPPORTED
    elif signals["independent_support_count"] >= 2 and signals["distinct_independent_support_count"] >= 1:
        status = SUPPORTED
    elif signals["distinct_independent_support_count"] == 1 or (
        signals["independent_support_count"] == 1 and signals["has_primary_provenance"]
    ):
        status = PARTIALLY_SUPPORTED
    elif signals["independent_support_count"] >= 1:
        status = PARTIALLY_SUPPORTED
    else:
        # Derived-only or empty evidence stays UNVERIFIED (no circular confirmation).
        status = UNVERIFIED

    return {
        "verification_status": status,
        "evidence_signals": signals,
        **confidence_meta,
    }


class ClaimRegister:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._claims: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path else None
        if self._db_path:
            self._init_db()
            self._load()

    def set_db_path(self, path: Path | str | None) -> None:
        with self._lock:
            # Detach first so Windows can delete the previous temp claims.sqlite.
            self._release_db_locked()
            self._db_path = Path(path) if path else None
            if self._db_path:
                self._init_db()
                self._load()

    def detach(self) -> None:
        """Drop SQLite persistence (keeps in-memory claims). Safe for test teardown on Windows."""
        with self._lock:
            self._release_db_locked()

    def _release_db_locked(self) -> None:
        path = self._db_path
        self._db_path = None
        if not path:
            return
        # Touch-open with DELETE journal so Windows releases any lingering lock.
        try:
            conn = sqlite3.connect(str(path), timeout=2, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Avoid WAL sidecar locks on Windows temp teardown.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        if not self._db_path:
            return
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    task_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_task ON claims(task_id)")
            conn.commit()
        finally:
            conn.close()

    def _load(self) -> None:
        if not self._db_path or not self._db_path.is_file():
            return
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, payload FROM claims").fetchall()
        finally:
            conn.close()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "verification_status" in payload:
                payload["verification_status"] = normalize_verification_status(payload.get("verification_status"))
            self._claims[str(row["id"])] = payload

    def _persist(self, claim: dict[str, Any]) -> None:
        if not self._db_path:
            return
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO claims(id, payload, task_id, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  payload=excluded.payload,
                  task_id=excluded.task_id,
                  updated_at=excluded.updated_at
                """,
                (
                    claim["id"],
                    json.dumps(claim, ensure_ascii=False),
                    claim.get("task_id"),
                    _now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def add_claim(
        self,
        *,
        text: str,
        provenance: str,
        verification_status: str = UNVERIFIED,
        source_kind: str = "primary",
        observed_at: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        supports: list[str] | None = None,
        contradicts: list[str] | None = None,
        task_id: str | None = None,
        reassess: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        cid = _id()
        with self._lock:
            claim = {
                "id": cid,
                "text": text,
                "provenance": provenance,
                "verification_status": normalize_verification_status(verification_status),
                "source_kind": source_kind,  # primary | user | derived_analysis
                "observed_at": observed_at or _now(),
                "valid_from": valid_from,
                "valid_until": valid_until,
                "supports": list(supports or []),
                "contradicts": list(contradicts or []),
                "evidence_links": [],
                "task_id": task_id,
                "superseded_by": None,
                "confidence": None,
                "confidence_basis": "observable_evidence_signals",
            }
            if metadata:
                for key, value in metadata.items():
                    if key in claim:
                        continue
                    claim[key] = value
            if reassess:
                assessment = assess_verification_state(claim)
                # Explicit SUPERSEDED only sticks when superseded_by is set (via supersede()).
                requested = claim["verification_status"]
                if requested == SUPERSEDED and not claim.get("superseded_by"):
                    claim["verification_status"] = assessment["verification_status"]
                elif requested == STALE:
                    claim["verification_status"] = STALE
                    claim["confidence"] = None
                    claim["confidence_note"] = "Confidence withheld for STALE claims."
                else:
                    claim["verification_status"] = assessment["verification_status"]
                    claim["confidence"] = assessment["confidence"]
                    claim["confidence_basis"] = assessment["confidence_basis"]
                    claim["confidence_note"] = assessment.get("confidence_note")
                if requested != STALE:
                    claim["evidence_signals"] = {
                        k: assessment["evidence_signals"][k]
                        for k in (
                            "support_count",
                            "contradict_count",
                            "independent_support_count",
                            "distinct_independent_support_count",
                            "derived_support_count",
                            "past_valid_until",
                        )
                        if k in assessment["evidence_signals"]
                    }
            self._claims[cid] = claim
            self._persist(claim)
        return cid

    def get(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._claims.get(claim_id)
            return dict(item) if item else None

    def allows_independent_confirmation(self, claim_id: str, *, evidence_id: str) -> bool:
        """Derived AI knowledge cannot confirm itself via the same provenance chain."""
        claim = self.get(claim_id)
        if not claim:
            return False
        if claim.get("source_kind") == "derived_analysis":
            if evidence_id == claim.get("provenance") or str(evidence_id).startswith("knowledge:derived"):
                return False
            # Also reject derived knowledge records used as evidence.
            if is_derived_knowledge_record({"uri": evidence_id, "source_type": "derived"}):
                return False
        return evidence_id != claim.get("provenance") or claim.get("source_kind") == "primary"

    def attach_evidence(
        self,
        claim_id: str,
        *,
        evidence_id: str,
        relation: str = "supports",
        independent: bool | None = None,
        note: str = "",
        source_hash: str | None = None,
        source_version: str | None = None,
    ) -> dict[str, Any]:
        """Attach a support/contradict evidence id and reassess verification state.

        When ``source_hash`` / ``source_version`` are provided they are pinned on
        the evidence link so later content changes can mark dependents for recheck
        without discarding the historical conclusion.
        """
        rel = str(relation or "supports").strip().lower()
        if rel not in EVIDENCE_RELATIONS:
            raise ValueError("relation_must_be_supports_or_contradicts")
        with self._lock:
            claim = self._claims.get(claim_id)
            if not claim:
                raise ValueError("claim_not_found")
            if claim.get("superseded_by"):
                raise ValueError("claim_superseded")

            eid = str(evidence_id).strip()
            if not eid:
                raise ValueError("evidence_id_required")

            # Circular guard: derived claims cannot gain independent confirmation from themselves.
            is_independent = independent
            if is_independent is None:
                is_independent = self.allows_independent_confirmation(claim_id, evidence_id=eid)

            link: dict[str, Any] = {
                "evidence_id": eid,
                "relation": rel,
                "independent": bool(is_independent),
                "note": note,
                "attached_at": _now(),
            }
            if source_hash:
                link["source_hash"] = str(source_hash)
            if source_version:
                link["source_version"] = str(source_version)
            links = list(claim.get("evidence_links") or [])
            links.append(link)
            claim["evidence_links"] = links

            # Also keep a compact provenance map for quick invalidation lookups.
            pinned = dict(claim.get("evidence_source_versions") or {})
            if source_hash or source_version:
                pinned[eid] = {
                    "source_hash": source_hash,
                    "source_version": source_version,
                    "pinned_at": _now(),
                }
                claim["evidence_source_versions"] = pinned

            if rel == "supports":
                supports = list(claim.get("supports") or [])
                if eid not in supports:
                    supports.append(eid)
                claim["supports"] = supports
            else:
                contradicts = list(claim.get("contradicts") or [])
                if eid not in contradicts:
                    contradicts.append(eid)
                claim["contradicts"] = contradicts

            assessment = assess_verification_state(claim)
            claim["verification_status"] = assessment["verification_status"]
            claim["confidence"] = assessment["confidence"]
            claim["confidence_basis"] = assessment["confidence_basis"]
            claim["confidence_note"] = assessment.get("confidence_note")
            claim["evidence_signals"] = {
                k: assessment["evidence_signals"][k]
                for k in (
                    "support_count",
                    "contradict_count",
                    "independent_support_count",
                    "distinct_independent_support_count",
                    "derived_support_count",
                    "past_valid_until",
                )
            }
            self._persist(claim)
            return dict(claim)

    def mark_dependent_claims_for_recheck(
        self,
        *,
        evidence_id: str,
        previous_hash: str | None = None,
        new_hash: str | None = None,
        reason: str = "evidence_content_hash_changed",
    ) -> list[dict[str, Any]]:
        """Mark claims that depend on ``evidence_id`` as STALE / recheck-needed.

        Historical claim text and original evidence links are preserved. Only
        claims that actually reference the evidence (and optionally a pinned
        hash that no longer matches) are touched — no full research re-run.
        """
        eid = str(evidence_id).strip()
        touched: list[dict[str, Any]] = []
        if not eid:
            return touched
        with self._lock:
            for claim in list(self._claims.values()):
                if claim.get("superseded_by"):
                    continue
                refs = set(claim.get("supports") or []) | set(claim.get("contradicts") or [])
                link_ids = {
                    str(link.get("evidence_id"))
                    for link in (claim.get("evidence_links") or [])
                    if isinstance(link, dict)
                }
                if eid not in refs and eid not in link_ids and eid != claim.get("provenance"):
                    continue
                pinned = (claim.get("evidence_source_versions") or {}).get(eid) or {}
                pinned_hash = pinned.get("source_hash")
                # If we have a pin and it already matches the new hash, skip.
                if pinned_hash and new_hash and pinned_hash == new_hash:
                    continue
                # If a previous_hash is provided and the pin doesn't match it, still
                # invalidate when the evidence id is referenced (source changed under us).
                historical = {
                    "verification_status": claim.get("verification_status"),
                    "confidence": claim.get("confidence"),
                    "evidence_source_versions": dict(claim.get("evidence_source_versions") or {}),
                    "snapshot_at": _now(),
                }
                history = list(claim.get("historical_snapshots") or [])
                history.append(historical)
                claim["historical_snapshots"] = history[-20:]
                claim["verification_status"] = STALE
                claim["stale_reason"] = reason
                claim["recheck_required"] = True
                claim["recheck_evidence_id"] = eid
                claim["recheck_previous_hash"] = previous_hash
                claim["recheck_new_hash"] = new_hash
                claim["confidence"] = None
                claim["confidence_basis"] = "observable_evidence_signals"
                claim["confidence_note"] = "Confidence withheld — supporting evidence changed; recheck required."
                self._persist(claim)
                touched.append(dict(claim))
        return touched

    def mark_stale(self, claim_id: str, *, reason: str = "valid_until_elapsed") -> dict[str, Any]:
        with self._lock:
            claim = self._claims.get(claim_id)
            if not claim:
                raise ValueError("claim_not_found")
            if claim.get("superseded_by"):
                claim["verification_status"] = SUPERSEDED
            else:
                claim["verification_status"] = STALE
                claim["stale_reason"] = reason
            # Stale/superseded claims withhold confidence (no fresh confirmation).
            claim["confidence"] = None
            claim["confidence_basis"] = "observable_evidence_signals"
            claim["confidence_note"] = "Confidence withheld for STALE/SUPERSEDED claims."
            self._persist(claim)
            return dict(claim)

    def reassess(self, claim_id: str, *, now: str | None = None) -> dict[str, Any]:
        with self._lock:
            claim = self._claims.get(claim_id)
            if not claim:
                raise ValueError("claim_not_found")
            assessment = assess_verification_state(claim, now=now)
            claim["verification_status"] = assessment["verification_status"]
            claim["confidence"] = assessment["confidence"]
            claim["confidence_basis"] = assessment["confidence_basis"]
            claim["confidence_note"] = assessment.get("confidence_note")
            claim["evidence_signals"] = {
                k: assessment["evidence_signals"][k]
                for k in (
                    "support_count",
                    "contradict_count",
                    "independent_support_count",
                    "distinct_independent_support_count",
                    "derived_support_count",
                    "past_valid_until",
                )
            }
            self._persist(claim)
            return dict(claim)

    def supersede(self, claim_id: str, *, new_text: str, provenance: str, reason: str = "") -> str:
        with self._lock:
            old = self._claims.get(claim_id)
            if not old:
                raise ValueError("claim_not_found")
        new_id = self.add_claim(
            text=new_text,
            provenance=provenance,
            verification_status=UNVERIFIED,
            source_kind=str(old.get("source_kind") or "user"),
            supports=list(old.get("supports") or []),
            task_id=old.get("task_id"),
            reassess=True,
        )
        with self._lock:
            self._claims[claim_id]["superseded_by"] = new_id
            self._claims[claim_id]["verification_status"] = SUPERSEDED
            self._claims[claim_id]["supersede_reason"] = reason
            self._claims[claim_id]["confidence"] = None
            self._claims[claim_id]["confidence_note"] = "Confidence withheld for SUPERSEDED claims."
            self._persist(self._claims[claim_id])
        return new_id

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(c) for c in self._claims.values() if c.get("task_id") == task_id]

    def list_all(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(c) for c in self._claims.values()]
        items.sort(key=lambda c: str(c.get("observed_at") or ""), reverse=True)
        return items[:limit]


def honest_research_metric_kind(raw: str | None) -> str:
    """Keep mastery aliases as coverage diversity — never launder into expert completion."""
    kind = str(raw or "source_coverage_diversity").strip() or "source_coverage_diversity"
    if kind.lower() in {"expert_mastery", "mastery", "expertise", "expert_completion"}:
        return "source_coverage_diversity"
    return kind


def register_research_contradiction_claims(
    register: ClaimRegister,
    *,
    topic: str,
    contradictions: list[str],
    task_id: str | None = None,
    metric_kind: str = "source_coverage_diversity",
) -> list[str]:
    """Optional research-completion hook: record contradiction strings as CONTRADICTED claims.

    Does **not** invent mastery/expertise — metric_kind must remain a coverage label.
    """
    kind = honest_research_metric_kind(metric_kind)
    ids: list[str] = []
    for index, item in enumerate(contradictions or []):
        text = str(item).strip()
        if not text:
            continue
        cid = register.add_claim(
            text=f"Research contradiction on '{topic}': {text}",
            provenance=f"research:contradiction:{index}",
            source_kind="primary",
            verification_status=CONTRADICTED,
            contradicts=[f"research:contradiction:{index}:peer"],
            task_id=task_id,
            reassess=True,
            metadata={
                "metric_kind": kind,
                "metric_note": "Contradiction recorded from coverage scan; not expert mastery.",
            },
        )
        ids.append(cid)
    return ids


# Process-wide register; main.lifespan may attach SQLite persistence.
default_claim_register = ClaimRegister()
