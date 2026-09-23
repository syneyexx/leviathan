"""KnowledgeAssimilationService — orchestration seam into KnowledgeStore (not a second store)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _claim_status_value(claim: Any) -> str:
    status = getattr(claim, "status", None)
    if status is None and isinstance(claim, dict):
        status = claim.get("status")
    if hasattr(status, "value"):
        return str(status.value).lower()
    return str(status or "").lower()


def _claim_field(claim: Any, name: str, default: Any = None) -> Any:
    if isinstance(claim, dict):
        return claim.get(name, default)
    return getattr(claim, name, default)


def _project_id(project: Any) -> str:
    if isinstance(project, dict):
        return str(project.get("project_id") or project.get("id") or "")
    return str(getattr(project, "project_id", None) or getattr(project, "id", "") or "")


def _project_title(project: Any) -> str:
    if isinstance(project, dict):
        return str(project.get("title") or project.get("topic") or _project_id(project))
    return str(
        getattr(project, "title", None)
        or getattr(project, "topic", None)
        or _project_id(project)
    )


@dataclass
class AssimilationReceipt:
    receipt_id: str
    kind: str
    created_at: str
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0
    document_ids: list[str] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    ok: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "ok": self.ok,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
            "document_ids": list(self.document_ids),
            "skipped": list(self.skipped),
            "failures": list(self.failures),
            "metadata": dict(self.metadata),
            "truth": {
                "assimilation_is_not_a_second_store": True,
                "speculative_claims_are_not_promoted": True,
                "contradicted_claims_are_not_promoted": True,
                "evidence_required_for_promotion": True,
                "ok_requires_zero_failures": self.ok == (self.failure_count == 0),
            },
        }


class KnowledgeAssimilationService:
    """Quality-gated promotion into the existing KnowledgeStore / AtlasStore."""

    def __init__(
        self,
        *,
        database_path: Path | str | None = None,
        knowledge_store: Any | None = None,
        atlas_store: Any | None = None,
        observability_emit: Any | None = None,
    ) -> None:
        self.database_path = Path(database_path) if database_path else None
        self.knowledge_store = knowledge_store
        self.atlas_store = atlas_store
        self._emit = observability_emit
        self._lock = threading.RLock()
        self._memory_receipts: list[AssimilationReceipt] = []
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_sqlite()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.database_path is None:
            raise RuntimeError("database_path not configured")
        conn = sqlite3.connect(self.database_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_sqlite(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS intelligence_assimilation_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        ok INTEGER NOT NULL,
                        success_count INTEGER NOT NULL,
                        failure_count INTEGER NOT NULL,
                        skipped_count INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )

    def _store_receipt(self, receipt: AssimilationReceipt) -> None:
        with self._lock:
            if self.database_path is None:
                self._memory_receipts.append(receipt)
            else:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO intelligence_assimilation_receipts(
                            receipt_id, kind, created_at, ok, success_count,
                            failure_count, skipped_count, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            receipt.receipt_id,
                            receipt.kind,
                            receipt.created_at,
                            1 if receipt.ok else 0,
                            receipt.success_count,
                            receipt.failure_count,
                            receipt.skipped_count,
                            json.dumps(receipt.public_dict()),
                        ),
                    )
        if self._emit is not None:
            try:
                self._emit(
                    "intelligence",
                    "assimilation",
                    payload={
                        "receipt_id": receipt.receipt_id,
                        "kind": receipt.kind,
                        "ok": receipt.ok,
                        "success_count": receipt.success_count,
                        "failure_count": receipt.failure_count,
                        "skipped_count": receipt.skipped_count,
                        "research_project_id": (receipt.metadata or {}).get("research_project_id"),
                        "dataset_id": (receipt.metadata or {}).get("dataset_id"),
                    },
                    level="info" if receipt.ok else "warning",
                    success=receipt.ok,
                )
            except Exception:  # noqa: BLE001
                pass

    def list_receipts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if self.database_path is None:
                return [r.public_dict() for r in self._memory_receipts[-limit:]]
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM intelligence_assimilation_receipts
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                try:
                    out.append(json.loads(row["payload_json"]))
                except Exception:  # noqa: BLE001
                    continue
            return out

    def _promotion_gate(self, claim: Any) -> tuple[bool, str | None]:
        claim_id = str(_claim_field(claim, "claim_id") or "")
        status = _claim_status_value(claim)
        supporting = list(_claim_field(claim, "supporting_evidence_ids") or [])
        contradicting = list(_claim_field(claim, "contradicting_evidence_ids") or [])
        metadata = dict(_claim_field(claim, "metadata") or {})
        speculative = bool(metadata.get("speculative")) or status in {
            "unsupported",
            "unresolved",
            "speculative",
        }

        if not claim_id:
            return False, "missing_claim_id"
        if not supporting:
            return False, "no_evidence_links"
        if contradicting or status == "disputed":
            return False, "contradicted"
        if speculative:
            return False, "speculative"
        if status and status not in {"supported", "weakly_supported", ""}:
            return False, f"status_not_promotable:{status}"
        return True, None

    def _confidence_for(self, claim: Any) -> float:
        metadata = dict(_claim_field(claim, "metadata") or {})
        if "confidence" in metadata:
            try:
                return max(0.0, min(1.0, float(metadata["confidence"])))
            except (TypeError, ValueError):
                pass
        status = _claim_status_value(claim)
        if status == "supported":
            return 0.85
        if status == "weakly_supported":
            return 0.6
        return 0.5

    def assimilate_research_project(
        self,
        project: Any,
        *,
        claims: Sequence[Any],
        evidence: Sequence[Any] | None = None,
        knowledge_store: Any | None = None,
        atlas_store: Any | None = None,
    ) -> AssimilationReceipt:
        """Promote evidence-backed, non-contradicted claims into KnowledgeStore."""
        knowledge_store = knowledge_store if knowledge_store is not None else self.knowledge_store
        atlas_store = atlas_store if atlas_store is not None else self.atlas_store
        project_id = _project_id(project)
        receipt = AssimilationReceipt(
            receipt_id=str(uuid.uuid4()),
            kind="research_project",
            created_at=utc_now(),
            metadata={
                "research_project_id": project_id,
                "project_title": _project_title(project),
                "claims_considered": len(list(claims)),
                "evidence_provided": len(list(evidence or [])),
            },
        )
        if knowledge_store is None:
            receipt.failure_count = 1
            receipt.failures.append(
                {"error": "knowledge_store_required", "reason": "no_store"}
            )
            receipt.ok = False
            self._store_receipt(receipt)
            return receipt

        evidence_by_id: dict[str, Any] = {}
        for item in evidence or []:
            eid = _claim_field(item, "evidence_id") or (
                item.get("evidence_id") if isinstance(item, dict) else None
            )
            if eid:
                evidence_by_id[str(eid)] = item

        if hasattr(knowledge_store, "initialize"):
            try:
                knowledge_store.initialize()
            except Exception:  # noqa: BLE001
                pass

        for claim in claims:
            claim_id = str(_claim_field(claim, "claim_id") or "")
            ok, reason = self._promotion_gate(claim)
            if not ok:
                receipt.skipped_count += 1
                receipt.skipped.append(
                    {"claim_id": claim_id, "reason": reason or "gated"}
                )
                continue

            supporting = [str(x) for x in (_claim_field(claim, "supporting_evidence_ids") or [])]
            proposition = str(
                _claim_field(claim, "proposition")
                or _claim_field(claim, "raw_wording")
                or ""
            ).strip()
            if not proposition:
                receipt.skipped_count += 1
                receipt.skipped.append({"claim_id": claim_id, "reason": "empty_proposition"})
                continue

            confidence = self._confidence_for(claim)
            document_id = f"research:{project_id}:claim:{claim_id}"
            evidence_spans: list[str] = []
            for eid in supporting:
                ev = evidence_by_id.get(eid)
                if ev is None:
                    continue
                span = _claim_field(ev, "span_text") or ""
                if span:
                    evidence_spans.append(f"[{eid}] {span}")
            body_parts = [proposition]
            if evidence_spans:
                body_parts.append("")
                body_parts.append("Evidence:")
                body_parts.extend(evidence_spans)
            content = "\n".join(body_parts)
            trust = {
                "trust": "research_assimilation",
                "research_project_id": project_id,
                "claim_id": claim_id,
                "evidence_ids": supporting,
                "confidence": confidence,
                "claim_status": _claim_status_value(claim),
                "source_diversity": int(_claim_field(claim, "source_diversity") or 0),
                "provenance": "KnowledgeAssimilationService.assimilate_research_project",
            }
            try:
                doc = knowledge_store.upsert_document(
                    title=f"research/{project_id}/{claim_id}",
                    content=content,
                    source=f"research:{project_id}",
                    document_id=document_id,
                    trust_metadata=trust,
                    source_type="research_claim",
                    confidence=confidence,
                    uncertainty_notes=(
                        "Assimilated research claim — advisory until independently verified"
                    ),
                )
                doc_id = getattr(doc, "document_id", None) or document_id
                receipt.success_count += 1
                receipt.document_ids.append(str(doc_id))

                if atlas_store is not None and hasattr(atlas_store, "create"):
                    try:
                        from Data.modules.knowledge.atlas import AtlasScale

                        atlas_store.create(
                            atlas_id=f"atlas:research:{project_id}:claim:{claim_id}",
                            title=f"Claim {claim_id}",
                            summary=proposition[:2000],
                            scale=AtlasScale.THREAD,
                            scope=f"research:{project_id}",
                            projects=[project_id],
                            confidence=confidence,
                            evidence_record_refs=supporting,
                            revision_reason="research_assimilation",
                            metadata={
                                "claim_id": claim_id,
                                "document_id": doc_id,
                                "research_project_id": project_id,
                            },
                        )
                    except Exception as atlas_exc:  # noqa: BLE001
                        receipt.metadata.setdefault("atlas_errors", []).append(
                            {"claim_id": claim_id, "error": str(atlas_exc)}
                        )
            except Exception as exc:  # noqa: BLE001
                receipt.failure_count += 1
                receipt.failures.append(
                    {"claim_id": claim_id, "error": str(exc)}
                )

        receipt.ok = receipt.failure_count == 0 and receipt.success_count > 0
        if receipt.success_count == 0 and receipt.failure_count == 0:
            # Nothing promoted is not fake success.
            receipt.ok = False
            receipt.metadata["note"] = "no_claims_promoted"
        self._store_receipt(receipt)
        return receipt

    def assimilate_dataset_version(
        self,
        *,
        knowledge_store: Any | None = None,
        dataset_id: str,
        version_id: str,
        storage_path: Path | str | None = None,
        records: Sequence[Any] | None = None,
        scope: str = "dataset",
        max_records: int | None = None,
    ) -> AssimilationReceipt:
        """Thin-wrap datasets.indexing into a truthful assimilation receipt."""
        knowledge_store = knowledge_store if knowledge_store is not None else self.knowledge_store
        receipt = AssimilationReceipt(
            receipt_id=str(uuid.uuid4()),
            kind="dataset_version",
            created_at=utc_now(),
            metadata={
                "dataset_id": dataset_id,
                "version_id": version_id,
                "scope": scope,
            },
        )
        if knowledge_store is None:
            receipt.failure_count = 1
            receipt.failures.append({"error": "knowledge_store_required"})
            receipt.ok = False
            self._store_receipt(receipt)
            return receipt

        try:
            from Data.modules.datasets.indexing import index_records, index_version_file
        except Exception as exc:  # noqa: BLE001
            receipt.failure_count = 1
            receipt.failures.append({"error": f"indexing_import_failed: {exc}"})
            receipt.ok = False
            self._store_receipt(receipt)
            return receipt

        try:
            if records is not None:
                result = index_records(
                    knowledge_store,
                    list(records),
                    dataset_id=dataset_id,
                    version_id=version_id,
                    scope=scope,
                    max_records=max_records,
                )
            elif storage_path is not None:
                result = index_version_file(
                    knowledge_store,
                    Path(storage_path),
                    dataset_id=dataset_id,
                    version_id=version_id,
                    scope=scope,
                    max_records=max_records,
                )
            else:
                receipt.failure_count = 1
                receipt.failures.append(
                    {"error": "storage_path_or_records_required"}
                )
                receipt.ok = False
                self._store_receipt(receipt)
                return receipt

            doc_count = int(result.get("documentCount") or 0)
            sample = list(result.get("documentIdsSample") or [])
            receipt.success_count = doc_count
            receipt.document_ids = sample
            receipt.metadata["index_result"] = result
            receipt.ok = doc_count > 0
            if doc_count == 0:
                receipt.metadata["note"] = "no_documents_indexed"
                receipt.ok = False
        except Exception as exc:  # noqa: BLE001
            receipt.failure_count = 1
            receipt.failures.append({"error": str(exc)})
            receipt.ok = False

        self._store_receipt(receipt)
        return receipt

    def health(self) -> dict[str, Any]:
        receipts = self.list_receipts(limit=5)
        return {
            "consumer": "KnowledgeAssimilationService",
            "consumer_active": True,
            "capability_available": True,
            "database_path": str(self.database_path) if self.database_path else None,
            "durable": self.database_path is not None,
            "recent_receipts": len(receipts),
            "truth": {
                "assimilation_is_not_a_second_store": True,
                "in_memory_receipts_when_no_db": self.database_path is None,
            },
        }
