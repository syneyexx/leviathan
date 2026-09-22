from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .atlas import AtlasRecord, AtlasStore
from .retrieval import HybridRetriever, RetrievalHit, RetrievalQuery
from .store import KnowledgeStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DeepRecallRequest:
    current_question: str
    remembered_gist: str = ""
    missing_detail: str = ""
    candidate_entities: tuple[str, ...] = ()
    candidate_projects: tuple[str, ...] = ()
    time_range: tuple[str | None, str | None] = (None, None)
    relation: str | None = None
    required_precision: str = "normal"  # low | normal | high
    maximum_context_budget: int = 1200
    stop_conditions: tuple[str, ...] = ()
    hydrate_limit: int = 5


@dataclass(frozen=True)
class DeepRecallResult:
    atlas_matches: tuple[dict[str, Any], ...]
    hydrated_evidence_refs: tuple[str, ...]
    exact_details: tuple[dict[str, Any], ...]
    unresolved_gaps: tuple[str, ...]
    contradictions_found: tuple[str, ...]
    confidence: float
    context_cost: int
    retrieval_steps: tuple[str, ...]
    stopped_reason: str = "completed"
    available: bool = True
    reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "atlas_matches": list(self.atlas_matches),
            "hydrated_evidence_refs": list(self.hydrated_evidence_refs),
            "exact_details": list(self.exact_details),
            "unresolved_gaps": list(self.unresolved_gaps),
            "contradictions_found": list(self.contradictions_found),
            "confidence": self.confidence,
            "context_cost": self.context_cost,
            "retrieval_steps": list(self.retrieval_steps),
            "stopped_reason": self.stopped_reason,
            "available": self.available,
            "reason": self.reason,
            "truth": {
                "deep_recall_is_not_authority": True,
                "atlas_is_not_evidence": True,
                "model_output_is_not_evidence": True,
            },
        }


class DeepRecallService:
    """First-class host operation: hot → atlas → selective evidence hydrate."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeStore,
        atlas: AtlasStore,
        retriever: HybridRetriever,
        db_path: Path,
        enabled: bool = False,
        observability_emit: Any | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.atlas = atlas
        self.retriever = retriever
        self.db_path = db_path
        self.enabled = enabled
        self._emit = observability_emit
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deep_recall_logs (
                    recall_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    context_cost INTEGER NOT NULL,
                    stopped_reason TEXT NOT NULL
                )
                """
            )

    def recall(self, request: DeepRecallRequest) -> DeepRecallResult:
        if not self.enabled:
            result = DeepRecallResult(
                atlas_matches=(),
                hydrated_evidence_refs=(),
                exact_details=(),
                unresolved_gaps=("deep_recall_feature_disabled",),
                contradictions_found=(),
                confidence=0.0,
                context_cost=0,
                retrieval_steps=("disabled",),
                stopped_reason="feature_disabled",
                available=False,
                reason="LEVIATHAN_FEATURE_DEEP_RECALL=false",
            )
            self._log(request, result)
            return result

        steps: list[str] = ["hot_query"]
        budget = max(64, int(request.maximum_context_budget))
        cost = 0
        stop = "completed"

        # 1) Atlas search (cheap summaries)
        steps.append("atlas_search")
        atlas_hits: list[AtlasRecord] = []
        for entity in request.candidate_entities or (None,):
            for project in request.candidate_projects or (None,):
                atlas_hits.extend(
                    self.atlas.search(
                        request.current_question or request.remembered_gist,
                        limit=max(1, request.hydrate_limit),
                        entity=entity,
                        project=project,
                    )
                )
        # Dedupe atlas
        seen_atlas: set[str] = set()
        unique_atlas: list[AtlasRecord] = []
        for item in atlas_hits:
            if item.atlas_id in seen_atlas:
                continue
            seen_atlas.add(item.atlas_id)
            unique_atlas.append(item)

        atlas_payloads = []
        for item in unique_atlas[: request.hydrate_limit]:
            payload = item.public_dict()
            tokens = max(1, len(item.summary.split()))
            if cost + tokens > budget:
                stop = "budget_exceeded"
                steps.append("stop_budget_atlas")
                break
            cost += tokens
            atlas_payloads.append(payload)
            if "max_atlas" in request.stop_conditions and len(atlas_payloads) >= 1:
                stop = "stop_condition:max_atlas"
                break

        if "budget_exceeded" in request.stop_conditions and cost >= budget:
            stop = "stop_condition:budget_exceeded"

        # 2) Selective hydrate of evidence refs from atlas + direct retrieval
        steps.append("selective_hydrate")
        evidence_refs: list[str] = []
        exact_details: list[dict[str, Any]] = []
        contradictions: list[str] = []
        gaps: list[str] = []

        for atlas_item in unique_atlas:
            contradictions.extend(list(atlas_item.contradictions))
            gaps.extend(list(atlas_item.unresolved_questions))
            for ref in atlas_item.evidence_record_refs:
                if ref in evidence_refs:
                    continue
                chunk = self.knowledge.get_chunk(ref)
                if chunk is None:
                    # Treat as document id fallback.
                    doc = self.knowledge.get_document(ref)
                    if doc is None:
                        gaps.append(f"missing_evidence_ref:{ref}")
                        continue
                    detail = {
                        "ref": ref,
                        "layer": "evidence",
                        "title": doc.title,
                        "content": doc.content[: min(400, budget - cost + 1)],
                        "document_id": doc.document_id,
                        "content_hash": doc.content_hash,
                    }
                else:
                    detail = {
                        "ref": ref,
                        "layer": "evidence",
                        "content": chunk.content,
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.chunk_id,
                        "content_hash": chunk.content_hash,
                        "start_offset": chunk.start_offset,
                        "end_offset": chunk.end_offset,
                        "confidence": chunk.confidence,
                    }
                tokens = max(1, len(str(detail.get("content", "")).split()))
                if cost + tokens > budget:
                    stop = "budget_exceeded"
                    steps.append("stop_budget_evidence")
                    break
                cost += tokens
                evidence_refs.append(ref)
                exact_details.append(detail)
                if len(evidence_refs) >= request.hydrate_limit:
                    break
            if stop == "budget_exceeded" or len(evidence_refs) >= request.hydrate_limit:
                break

        # 3) If precision high or missing detail, run HybridRetriever for gaps.
        if request.required_precision == "high" or request.missing_detail:
            steps.append("hybrid_fill")
            query_text = " ".join(
                part
                for part in (request.current_question, request.missing_detail, request.remembered_gist)
                if part
            ).strip()
            time_after, time_before = request.time_range
            hits: list[RetrievalHit] = self.retriever.search(
                RetrievalQuery(
                    text=query_text or request.current_question,
                    limit=request.hydrate_limit,
                    relation_class=request.relation,
                    time_after=time_after,
                    time_before=time_before,
                )
            )
            for hit in hits:
                if hit.chunk_id in evidence_refs:
                    continue
                tokens = max(1, len(hit.content.split()))
                if cost + tokens > budget:
                    stop = "budget_exceeded"
                    steps.append("stop_budget_hybrid")
                    break
                cost += tokens
                evidence_refs.append(hit.chunk_id)
                exact_details.append(
                    {
                        "ref": hit.chunk_id,
                        "layer": "evidence",
                        "content": hit.content,
                        "document_id": hit.document_id,
                        "chunk_id": hit.chunk_id,
                        "content_hash": hit.chunk_hash,
                        "score": hit.score,
                        "modality": hit.modality,
                        "title": hit.title,
                    }
                )

        if request.missing_detail and not exact_details:
            gaps.append(f"unresolved_missing_detail:{request.missing_detail}")

        confidence = 0.0
        if atlas_payloads or exact_details:
            confidences = [float(a.get("confidence") or 0.4) for a in atlas_payloads]
            confidences.extend(float(d.get("confidence") or 0.55) for d in exact_details)
            confidence = round(sum(confidences) / max(len(confidences), 1), 3)
            if contradictions:
                confidence = round(max(0.05, confidence - 0.15), 3)

        result = DeepRecallResult(
            atlas_matches=tuple(atlas_payloads),
            hydrated_evidence_refs=tuple(evidence_refs),
            exact_details=tuple(exact_details),
            unresolved_gaps=tuple(dict.fromkeys(gaps)),
            contradictions_found=tuple(dict.fromkeys(contradictions)),
            confidence=confidence,
            context_cost=cost,
            retrieval_steps=tuple(steps),
            stopped_reason=stop,
            available=True,
            reason="",
        )
        self._log(request, result)
        if self._emit is not None:
            try:
                self._emit(
                    "knowledge.deep_recall",
                    {
                        "context_cost": result.context_cost,
                        "atlas_count": len(result.atlas_matches),
                        "evidence_count": len(result.hydrated_evidence_refs),
                        "stopped_reason": result.stopped_reason,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        return result

    def _log(self, request: DeepRecallRequest, result: DeepRecallResult) -> None:
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO deep_recall_logs(
                    recall_id, created_at, request_json, result_json, context_cost, stopped_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    utc_now(),
                    json.dumps(
                        {
                            "current_question": request.current_question,
                            "remembered_gist": request.remembered_gist,
                            "missing_detail": request.missing_detail,
                            "required_precision": request.required_precision,
                            "maximum_context_budget": request.maximum_context_budget,
                        }
                    ),
                    json.dumps(result.public_dict()),
                    result.context_cost,
                    result.stopped_reason,
                ),
            )

    def recent_logs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT recall_id, created_at, context_cost, stopped_reason, result_json
                FROM deep_recall_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            {
                "recall_id": row["recall_id"],
                "created_at": row["created_at"],
                "context_cost": row["context_cost"],
                "stopped_reason": row["stopped_reason"],
                "result": json.loads(row["result_json"] or "{}"),
            }
            for row in rows
        ]
