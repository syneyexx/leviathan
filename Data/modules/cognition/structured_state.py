"""Structured public reasoning state — no private chain-of-thought.

Contract:
  - Persistable / hydratable via ``public_dict`` / ``from_public_dict``
  - Candidate summaries are previews only (bounded)
  - Claims / questions are explicit public objects — never hidden CoT
  - Schema versioned for forward-compatible resume
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1"
_PREVIEW_CHARS = 200
_MAX_CANDIDATES = 32
_MAX_QUESTIONS = 64
_MAX_CLAIMS = 64
_MAX_EVIDENCE = 128
_MAX_NOTES = 48


def _clip(text: str | None, n: int = _PREVIEW_CHARS) -> str:
    s = (text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


@dataclass
class CandidateSummary:
    """Public summary of one TTC / generate candidate."""

    index: int
    text_preview: str
    text_chars: int = 0
    temperature: float | None = None
    ok: bool = True
    selected: bool = False
    error: str | None = None
    finish_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text_preview": self.text_preview,
            "text_chars": self.text_chars,
            "temperature": self.temperature,
            "ok": self.ok,
            "selected": self.selected,
            "error": self.error,
            "finish_reason": self.finish_reason,
            "truth": {"candidate_summary_is_not_private_cot": True},
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "CandidateSummary | None":
        if not isinstance(raw, Mapping):
            return None
        try:
            index = int(raw.get("index", 0))
        except (TypeError, ValueError):
            return None
        return cls(
            index=index,
            text_preview=_clip(str(raw.get("text_preview") or "")),
            text_chars=int(raw.get("text_chars") or 0),
            temperature=(
                float(raw["temperature"])
                if raw.get("temperature") is not None
                else None
            ),
            ok=bool(raw.get("ok", True)),
            selected=bool(raw.get("selected", False)),
            error=str(raw["error"]) if raw.get("error") else None,
            finish_reason=str(raw["finish_reason"]) if raw.get("finish_reason") else None,
        )


@dataclass
class OpenQuestion:
    question_id: str
    text: str
    status: str = "open"  # open | answered | deferred
    answer_preview: str | None = None
    source: str = "task"

    def public_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "status": self.status,
            "answer_preview": self.answer_preview,
            "source": self.source,
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "OpenQuestion | None":
        if not isinstance(raw, Mapping):
            return None
        text = str(raw.get("text") or "").strip()
        if not text:
            return None
        return cls(
            question_id=str(raw.get("question_id") or uuid.uuid4()),
            text=text,
            status=str(raw.get("status") or "open"),
            answer_preview=_clip(raw.get("answer_preview")) if raw.get("answer_preview") else None,
            source=str(raw.get("source") or "task"),
        )


@dataclass
class PublicClaim:
    claim_id: str
    statement: str
    status: str = "asserted"  # asserted | supported | contested | withdrawn
    evidence_ids: list[str] = field(default_factory=list)
    confidence_band: str = "moderate"
    source: str = "model_public"

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "confidence_band": self.confidence_band,
            "source": self.source,
            "truth": {
                "claim_is_not_verified_fact": True,
                "claim_is_not_private_cot": True,
            },
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "PublicClaim | None":
        if not isinstance(raw, Mapping):
            return None
        statement = str(raw.get("statement") or "").strip()
        if not statement:
            return None
        evidence = raw.get("evidence_ids") or []
        return cls(
            claim_id=str(raw.get("claim_id") or uuid.uuid4()),
            statement=_clip(statement, 500),
            status=str(raw.get("status") or "asserted"),
            evidence_ids=[str(x) for x in evidence if x][:32],
            confidence_band=str(raw.get("confidence_band") or "moderate"),
            source=str(raw.get("source") or "model_public"),
        )


@dataclass
class EvidenceRef:
    evidence_id: str
    kind: str = "unknown"
    preview: str = ""
    authority: str = "untrusted"

    def public_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "preview": self.preview,
            "authority": self.authority,
            "truth": {"evidence_ref_is_not_system_authority": self.authority != "system"},
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "EvidenceRef | None":
        if not isinstance(raw, Mapping):
            return None
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid:
            return None
        return cls(
            evidence_id=eid,
            kind=str(raw.get("kind") or "unknown"),
            preview=_clip(str(raw.get("preview") or "")),
            authority=str(raw.get("authority") or "untrusted"),
        )


@dataclass
class StructuredReasoningState:
    """Public structured reasoning surface for a cognitive run."""

    schema_version: str = SCHEMA_VERSION
    open_questions: list[OpenQuestion] = field(default_factory=list)
    claims: list[PublicClaim] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    candidate_summaries: list[CandidateSummary] = field(default_factory=list)
    inference_path: str | None = None
    native_effort_effective: str | None = None
    reasoning_tokens_status: str | None = None
    last_selection_method: str | None = None
    agreement_ratio: float | None = None
    model_calls_consumed: int | None = None
    critique_notes: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "open_questions": [q.public_dict() for q in self.open_questions[:_MAX_QUESTIONS]],
            "claims": [c.public_dict() for c in self.claims[:_MAX_CLAIMS]],
            "evidence_refs": [e.public_dict() for e in self.evidence_refs[:_MAX_EVIDENCE]],
            "candidate_summaries": [
                c.public_dict() for c in self.candidate_summaries[:_MAX_CANDIDATES]
            ],
            "inference_path": self.inference_path,
            "native_effort_effective": self.native_effort_effective,
            "reasoning_tokens_status": self.reasoning_tokens_status,
            "last_selection_method": self.last_selection_method,
            "agreement_ratio": self.agreement_ratio,
            "model_calls_consumed": self.model_calls_consumed,
            "critique_notes": list(self.critique_notes[:_MAX_NOTES]),
            "unresolved": list(self.unresolved[:_MAX_NOTES]),
            "notes": list(self.notes[:_MAX_NOTES]),
            "counts": {
                "open_questions": len(self.open_questions),
                "open_questions_open": sum(
                    1 for q in self.open_questions if q.status == "open"
                ),
                "claims": len(self.claims),
                "evidence_refs": len(self.evidence_refs),
                "candidates": len(self.candidate_summaries),
            },
            "truth": {
                "no_private_cot": True,
                "schema_versioned": True,
                "persistable_public_contract": True,
                "candidate_summaries_are_previews_only": True,
            },
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "StructuredReasoningState":
        if not isinstance(raw, Mapping) or not raw:
            return cls()
        questions = [
            q
            for item in (raw.get("open_questions") or [])
            if (q := OpenQuestion.from_public_dict(item)) is not None
        ]
        claims = [
            c
            for item in (raw.get("claims") or [])
            if (c := PublicClaim.from_public_dict(item)) is not None
        ]
        evidence = [
            e
            for item in (raw.get("evidence_refs") or [])
            if (e := EvidenceRef.from_public_dict(item)) is not None
        ]
        candidates = [
            c
            for item in (raw.get("candidate_summaries") or [])
            if (c := CandidateSummary.from_public_dict(item)) is not None
        ]
        agreement = raw.get("agreement_ratio")
        try:
            agreement_f = float(agreement) if agreement is not None else None
        except (TypeError, ValueError):
            agreement_f = None
        consumed = raw.get("model_calls_consumed")
        try:
            consumed_i = int(consumed) if consumed is not None else None
        except (TypeError, ValueError):
            consumed_i = None
        return cls(
            schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
            open_questions=questions[:_MAX_QUESTIONS],
            claims=claims[:_MAX_CLAIMS],
            evidence_refs=evidence[:_MAX_EVIDENCE],
            candidate_summaries=candidates[:_MAX_CANDIDATES],
            inference_path=str(raw["inference_path"]) if raw.get("inference_path") else None,
            native_effort_effective=(
                str(raw["native_effort_effective"])
                if raw.get("native_effort_effective")
                else None
            ),
            reasoning_tokens_status=(
                str(raw["reasoning_tokens_status"])
                if raw.get("reasoning_tokens_status")
                else None
            ),
            last_selection_method=(
                str(raw["last_selection_method"]) if raw.get("last_selection_method") else None
            ),
            agreement_ratio=agreement_f,
            model_calls_consumed=consumed_i,
            critique_notes=[str(x) for x in (raw.get("critique_notes") or []) if x][:_MAX_NOTES],
            unresolved=[str(x) for x in (raw.get("unresolved") or []) if x][:_MAX_NOTES],
            notes=[str(x) for x in (raw.get("notes") or []) if x][:_MAX_NOTES],
        )

    def seed_from_goal(self, goal: str | None, *, source: str = "task") -> OpenQuestion | None:
        text = (goal or "").strip()
        if not text:
            return None
        # Avoid duplicate identical open goals.
        for existing in self.open_questions:
            if existing.text == text and existing.status == "open":
                return existing
        q = OpenQuestion(
            question_id=str(uuid.uuid4()),
            text=_clip(text, 500),
            status="open",
            source=source,
        )
        self.open_questions.append(q)
        self.notes.append("seeded_open_question_from_goal")
        return q

    def answer_open_questions(self, answer: str | None) -> None:
        preview = _clip(answer)
        if not preview:
            return
        for q in self.open_questions:
            if q.status == "open":
                q.status = "answered"
                q.answer_preview = preview

    def add_claim(
        self,
        statement: str,
        *,
        status: str = "asserted",
        confidence_band: str = "moderate",
        evidence_ids: Sequence[str] | None = None,
        source: str = "model_public",
    ) -> PublicClaim | None:
        text = (statement or "").strip()
        if not text:
            return None
        claim = PublicClaim(
            claim_id=str(uuid.uuid4()),
            statement=_clip(text, 500),
            status=status,
            evidence_ids=[str(x) for x in (evidence_ids or []) if x][:32],
            confidence_band=confidence_band,
            source=source,
        )
        self.claims.append(claim)
        if len(self.claims) > _MAX_CLAIMS:
            self.claims = self.claims[-_MAX_CLAIMS:]
        return claim

    def add_evidence_ref(
        self,
        evidence_id: str,
        *,
        kind: str = "unknown",
        preview: str = "",
        authority: str = "untrusted",
    ) -> EvidenceRef | None:
        eid = (evidence_id or "").strip()
        if not eid:
            return None
        for existing in self.evidence_refs:
            if existing.evidence_id == eid:
                return existing
        ref = EvidenceRef(
            evidence_id=eid,
            kind=kind,
            preview=_clip(preview),
            authority=authority,
        )
        self.evidence_refs.append(ref)
        if len(self.evidence_refs) > _MAX_EVIDENCE:
            self.evidence_refs = self.evidence_refs[-_MAX_EVIDENCE:]
        return ref

    def add_critique(self, note: str) -> None:
        text = (note or "").strip()
        if not text:
            return
        self.critique_notes.append(_clip(text, 300))
        if len(self.critique_notes) > _MAX_NOTES:
            self.critique_notes = self.critique_notes[-_MAX_NOTES:]

    def add_unresolved(self, note: str) -> None:
        text = (note or "").strip()
        if not text:
            return
        self.unresolved.append(_clip(text, 300))
        if len(self.unresolved) > _MAX_NOTES:
            self.unresolved = self.unresolved[-_MAX_NOTES:]

    def ingest_inference_compute(self, meta: Mapping[str, Any] | None) -> None:
        """Update from public inference_compute telemetry (native or TTC)."""
        if not isinstance(meta, Mapping) or not meta:
            return
        self.inference_path = str(meta.get("path") or self.inference_path or "")
        if meta.get("native_effort_effective") is not None:
            self.native_effort_effective = str(meta.get("native_effort_effective"))
        if meta.get("reasoning_tokens_status") is not None:
            self.reasoning_tokens_status = str(meta.get("reasoning_tokens_status"))
        if meta.get("model_calls_consumed") is not None:
            try:
                self.model_calls_consumed = int(meta["model_calls_consumed"])
            except (TypeError, ValueError):
                pass

        ttc = meta.get("ttc")
        if isinstance(ttc, Mapping):
            self._ingest_ttc(ttc)

    def _ingest_ttc(self, ttc: Mapping[str, Any]) -> None:
        selection = ttc.get("selection") if isinstance(ttc.get("selection"), Mapping) else {}
        if selection:
            self.last_selection_method = str(selection.get("method") or "") or None
            try:
                ar = selection.get("agreement_ratio")
                self.agreement_ratio = float(ar) if ar is not None else None
            except (TypeError, ValueError):
                self.agreement_ratio = None

        chosen_index = selection.get("chosen_index") if selection else None
        summaries: list[CandidateSummary] = []
        for item in ttc.get("candidates") or []:
            if not isinstance(item, Mapping):
                continue
            try:
                idx = int(item.get("index", len(summaries)))
            except (TypeError, ValueError):
                continue
            selected = chosen_index is not None and idx == chosen_index
            summaries.append(
                CandidateSummary(
                    index=idx,
                    text_preview=_clip(str(item.get("text_preview") or "")),
                    text_chars=int(item.get("text_chars") or 0),
                    temperature=(
                        float(item["temperature"])
                        if item.get("temperature") is not None
                        else None
                    ),
                    ok=bool(item.get("ok", True)),
                    selected=selected,
                    error=str(item["error"]) if item.get("error") else None,
                    finish_reason=(
                        str(item["finish_reason"]) if item.get("finish_reason") else None
                    ),
                )
            )
        if summaries:
            self.candidate_summaries = summaries[:_MAX_CANDIDATES]
            self.notes.append(f"ttc_candidates_ingested={len(summaries)}")


def structured_state_from_mapping(raw: Mapping[str, Any] | None) -> StructuredReasoningState:
    return StructuredReasoningState.from_public_dict(raw)
