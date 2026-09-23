"""Champion/challenger shadow control + explicit promotion boundary (U319–U320).

Leviathan may propose/train challengers automatically, but cannot silently
replace a production (active) model without recorded promotion evidence.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol

from Data.modules.models.store import ModelStore

from .lineage import ModelLineageStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChallengerStatus(str, Enum):
    PROPOSED = "proposed"
    TRAINING = "training"
    READY = "ready"
    SHADOWING = "shadowing"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


@dataclass
class ChallengerProposal:
    proposal_id: str
    champion_model_id: str | None
    challenger_model_id: str
    rationale: str
    status: ChallengerStatus = ChallengerStatus.PROPOSED
    eval_report_id: str | None = None
    training_job_id: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "champion_model_id": self.champion_model_id,
            "challenger_model_id": self.challenger_model_id,
            "rationale": self.rationale,
            "status": self.status.value,
            "eval_report_id": self.eval_report_id,
            "training_job_id": self.training_job_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "proposal_is_not_promotion": True,
                "shadow_does_not_mutate_lineage_history": True,
            },
        }


@dataclass
class PromotionRecord:
    promotion_id: str
    proposal_id: str
    from_model_id: str | None
    to_model_id: str
    decided_by: str
    eval_report_id: str | None
    gates: dict[str, Any]
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "proposal_id": self.proposal_id,
            "from_model_id": self.from_model_id,
            "to_model_id": self.to_model_id,
            "decided_by": self.decided_by,
            "eval_report_id": self.eval_report_id,
            "gates": dict(self.gates),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "promotion_is_explicit_control_plane_operation": True,
                "no_silent_production_replace": True,
            },
        }


class PromotionGateProvider(Protocol):
    def promotion_gate(self, *, component: str | None = None, suite_id: str = "foundation") -> dict[str, Any]: ...


class PromotionError(Exception):
    def __init__(self, message: str, *, code: str = "promotion_denied") -> None:
        super().__init__(message)
        self.code = code

    def public_dict(self) -> dict[str, Any]:
        return {"error": str(self), "code": self.code}


class FlywheelControlPlane:
    """Propose challengers + promote only with measurable gates + durable evidence."""

    def __init__(
        self,
        db_path: Path,
        *,
        model_store: ModelStore,
        lineage: ModelLineageStore | None = None,
        evaluation: PromotionGateProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.model_store = model_store
        self.lineage = lineage or ModelLineageStore(db_path)
        self.evaluation = evaluation
        self._ensure_tables()
        self.lineage.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS flywheel_challenger_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    champion_model_id TEXT,
                    challenger_model_id TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    eval_report_id TEXT,
                    training_job_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS flywheel_promotions (
                    promotion_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    from_model_id TEXT,
                    to_model_id TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    eval_report_id TEXT,
                    gates_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )

    def propose_challenger(
        self,
        *,
        challenger_model_id: str,
        rationale: str,
        champion_model_id: str | None = None,
        training_job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChallengerProposal:
        champion = champion_model_id or self.model_store.get_active_model_id()
        proposal = ChallengerProposal(
            proposal_id=f"ch_{uuid.uuid4().hex[:12]}",
            champion_model_id=champion,
            challenger_model_id=challenger_model_id,
            rationale=rationale,
            status=ChallengerStatus.PROPOSED,
            training_job_id=training_job_id,
            metadata=dict(metadata or {}),
        )
        self._save_proposal(proposal)
        self.lineage.add_edge(
            parent_id=champion or "none",
            child_id=challenger_model_id,
            relation="challenger_proposal",
            metadata={"proposal_id": proposal.proposal_id},
        )
        return proposal

    def mark_shadowing(self, proposal_id: str) -> ChallengerProposal:
        proposal = self.require_proposal(proposal_id)
        proposal.status = ChallengerStatus.SHADOWING
        proposal.updated_at = _utc_now()
        self._save_proposal(proposal)
        return proposal

    def promote(
        self,
        proposal_id: str,
        *,
        decided_by: str,
        eval_report_id: str | None = None,
        require_eval_gate: bool = True,
        suite_id: str = "foundation",
        candidate_model_id: str | None = None,
        candidate_artifact_hashes: dict[str, str] | None = None,
        candidate_manifest_hash: str | None = None,
    ) -> PromotionRecord:
        proposal = self.require_proposal(proposal_id)
        if proposal.status in {ChallengerStatus.PROMOTED, ChallengerStatus.REJECTED}:
            raise PromotionError(f"Proposal already terminal: {proposal.status.value}")

        # Candidate binding: caller-supplied identity must match the proposal challenger.
        if candidate_model_id is not None and candidate_model_id != proposal.challenger_model_id:
            raise PromotionError(
                "Promotion refused — candidate_model_id does not match proposal challenger "
                f"({candidate_model_id!r} != {proposal.challenger_model_id!r})",
                code="candidate_mismatch",
            )

        gates: dict[str, Any] = {
            "require_eval_gate": require_eval_gate,
            "candidate_binding": {
                "challenger_model_id": proposal.challenger_model_id,
                "candidate_model_id": candidate_model_id or proposal.challenger_model_id,
                "candidate_manifest_hash": candidate_manifest_hash,
                "candidate_artifact_hashes": dict(candidate_artifact_hashes or {}),
                "eval_report_id": eval_report_id or proposal.eval_report_id,
            },
        }
        if require_eval_gate:
            if self.evaluation is None:
                raise PromotionError(
                    "Evaluation platform required for promotion gate",
                    code="eval_unavailable",
                )
            gate = self.evaluation.promotion_gate(suite_id=suite_id)
            gates["evaluation"] = gate
            if not gate.get("promotable"):
                raise PromotionError(
                    "Promotion refused — evaluation gate not promotable "
                    f"(measurement={gate.get('measurement')})",
                    code="eval_gate_failed",
                )

        bound_report_id = eval_report_id or proposal.eval_report_id
        # Bind evaluation report to the exact candidate when a real report is required/available.
        if (
            bound_report_id
            and require_eval_gate
            and self.evaluation is not None
            and hasattr(self.evaluation, "get_report")
        ):
            report = self.evaluation.get_report(bound_report_id)
            if report is None:
                raise PromotionError(
                    f"Promotion refused — eval report not found: {bound_report_id}",
                    code="eval_report_missing",
                )
            # Bind evaluation to the exact candidate when the report carries model identity.
            report_model = (
                report.get("model_id")
                or report.get("candidate_model_id")
                or report.get("model_revision")
                or (report.get("metadata") or {}).get("model_id")
                or (report.get("metadata") or {}).get("candidate_model_id")
            )
            gates["evaluation_report"] = {
                "eval_report_id": bound_report_id,
                "report_model": report_model,
            }
            if report_model and str(report_model) not in {
                proposal.challenger_model_id,
                str(candidate_model_id or ""),
            }:
                # Allow prefix/revision forms like "model@rev" when the base id matches.
                report_s = str(report_model)
                challenger = proposal.challenger_model_id
                if not (
                    report_s == challenger
                    or report_s.startswith(f"{challenger}@")
                    or report_s.startswith(f"{challenger}:")
                ):
                    raise PromotionError(
                        "Promotion refused — evaluation report is bound to a different candidate "
                        f"(report={report_s!r}, challenger={challenger!r})",
                        code="eval_candidate_mismatch",
                    )
        elif bound_report_id and not require_eval_gate:
            # Operator override path — record the claimed evidence id without inventing a report.
            gates["evaluation_report"] = {
                "eval_report_id": bound_report_id,
                "report_model": None,
                "unverified_operator_evidence": True,
            }

        # Explicit control-plane mutation — never silent.
        previous = self.model_store.get_active_model_id()
        self.model_store.set_active_model(proposal.challenger_model_id)
        record = PromotionRecord(
            promotion_id=f"promo_{uuid.uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            from_model_id=previous,
            to_model_id=proposal.challenger_model_id,
            decided_by=decided_by,
            eval_report_id=bound_report_id,
            gates=gates,
            metadata={
                "candidate_manifest_hash": candidate_manifest_hash,
                "candidate_artifact_hashes": dict(candidate_artifact_hashes or {}),
            },
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO flywheel_promotions(
                    promotion_id, proposal_id, from_model_id, to_model_id,
                    decided_by, eval_report_id, gates_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.promotion_id,
                    record.proposal_id,
                    record.from_model_id,
                    record.to_model_id,
                    record.decided_by,
                    record.eval_report_id,
                    json.dumps(record.gates),
                    json.dumps(record.metadata),
                    record.created_at,
                ),
            )
        proposal.status = ChallengerStatus.PROMOTED
        proposal.updated_at = _utc_now()
        self._save_proposal(proposal)
        self.lineage.add_edge(
            parent_id=previous or "none",
            child_id=proposal.challenger_model_id,
            relation="deployment",
            metadata={
                "promotion_id": record.promotion_id,
                "decided_by": decided_by,
            },
        )
        return record

    def rollback(self, promotion_id: str, *, decided_by: str) -> PromotionRecord:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM flywheel_promotions WHERE promotion_id = ?",
                (promotion_id,),
            ).fetchone()
        if row is None:
            raise PromotionError("Unknown promotion", code="not_found")
        from_id = row["from_model_id"]
        if not from_id:
            raise PromotionError("No prior champion to roll back to", code="no_prior")
        self.model_store.set_active_model(from_id)
        proposal = self.require_proposal(row["proposal_id"])
        proposal.status = ChallengerStatus.ROLLED_BACK
        proposal.updated_at = _utc_now()
        self._save_proposal(proposal)
        rb = PromotionRecord(
            promotion_id=f"promo_{uuid.uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            from_model_id=row["to_model_id"],
            to_model_id=from_id,
            decided_by=decided_by,
            eval_report_id=row["eval_report_id"],
            gates={"rollback_of": promotion_id},
            metadata={"rollback": True},
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO flywheel_promotions(
                    promotion_id, proposal_id, from_model_id, to_model_id,
                    decided_by, eval_report_id, gates_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rb.promotion_id,
                    rb.proposal_id,
                    rb.from_model_id,
                    rb.to_model_id,
                    rb.decided_by,
                    rb.eval_report_id,
                    json.dumps(rb.gates),
                    json.dumps(rb.metadata),
                    rb.created_at,
                ),
            )
        self.lineage.add_edge(
            parent_id=row["to_model_id"],
            child_id=from_id,
            relation="deployment",
            metadata={"rollback_of": promotion_id, "decided_by": decided_by},
        )
        return rb

    def require_proposal(self, proposal_id: str) -> ChallengerProposal:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM flywheel_challenger_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise PromotionError("Unknown proposal", code="not_found")
        return self._proposal_from_row(row)

    def list_proposals(self, *, limit: int = 50) -> list[ChallengerProposal]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM flywheel_challenger_proposals
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._proposal_from_row(r) for r in rows]

    def list_promotions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM flywheel_promotions
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "promotion_id": row["promotion_id"],
                    "proposal_id": row["proposal_id"],
                    "from_model_id": row["from_model_id"],
                    "to_model_id": row["to_model_id"],
                    "decided_by": row["decided_by"],
                    "eval_report_id": row["eval_report_id"],
                    "gates": json.loads(row["gates_json"] or "{}"),
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "created_at": row["created_at"],
                }
            )
        return out

    def try_silent_replace(self, model_id: str) -> dict[str, Any]:
        """Honesty helper for tests — documents that silent replace is forbidden."""
        return {
            "allowed": False,
            "attempted_model_id": model_id,
            "detail": "Use FlywheelControlPlane.promote() with recorded evidence",
            "truth": {"no_silent_production_replace": True},
        }

    def _save_proposal(self, proposal: ChallengerProposal) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO flywheel_challenger_proposals(
                    proposal_id, champion_model_id, challenger_model_id, rationale,
                    status, eval_report_id, training_job_id, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    status=excluded.status,
                    eval_report_id=excluded.eval_report_id,
                    training_job_id=excluded.training_job_id,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    proposal.proposal_id,
                    proposal.champion_model_id,
                    proposal.challenger_model_id,
                    proposal.rationale,
                    proposal.status.value,
                    proposal.eval_report_id,
                    proposal.training_job_id,
                    json.dumps(proposal.metadata),
                    proposal.created_at,
                    proposal.updated_at,
                ),
            )

    def _proposal_from_row(self, row: sqlite3.Row) -> ChallengerProposal:
        return ChallengerProposal(
            proposal_id=row["proposal_id"],
            champion_model_id=row["champion_model_id"],
            challenger_model_id=row["challenger_model_id"],
            rationale=row["rationale"],
            status=ChallengerStatus(row["status"]),
            eval_report_id=row["eval_report_id"],
            training_job_id=row["training_job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
