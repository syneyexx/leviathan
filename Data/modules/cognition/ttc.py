"""Test-time compute — candidate search under Cognition (W4).

When neural.candidate_count > 1 (or caller requests TTC), generate scored
candidates, prune weak ones, optionally repair with verifier feedback.

Does NOT persist raw rejected private chain-of-thought.
May persist hashes, scores, public summaries, selected answer, evaluation metadata.

IntegrityScorer checks TECHNICAL integrity only — never moral/political/ideological
content moderation. BehaviorProfile owns conversational policy.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class CandidateScore:
    scorer: str
    score: float
    detail: str | None = None
    hard_fail: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "scorer": self.scorer,
            "score": self.score,
            "detail": self.detail,
            "hard_fail": self.hard_fail,
        }


@dataclass
class Candidate:
    candidate_id: str
    output: str
    structured: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    scores: list[CandidateScore] = field(default_factory=list)
    public_summary: str = ""
    rejected: bool = False
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                (self.output or "").encode("utf-8")
            ).hexdigest()[:24]
        if not self.public_summary:
            text = (self.output or "").strip()
            self.public_summary = text[:240] + ("…" if len(text) > 240 else "")

    @property
    def aggregate_score(self) -> float:
        if not self.scores:
            return 0.0
        if any(s.hard_fail for s in self.scores):
            return -1.0
        return sum(s.score for s in self.scores) / max(1, len(self.scores))

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "content_hash": self.content_hash,
            "public_summary": self.public_summary,
            "usage": dict(self.usage),
            "scores": [s.public_dict() for s in self.scores],
            "aggregate_score": self.aggregate_score,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "structured": self.structured,
            "truth": {
                "raw_private_reasoning_not_persisted": True,
                "hash_and_scores_ok_to_persist": True,
            },
        }


@dataclass
class CandidateSet:
    candidates: list[Candidate] = field(default_factory=list)
    selected_id: str | None = None
    evaluation: dict[str, Any] = field(default_factory=dict)

    @property
    def selected(self) -> Candidate | None:
        if not self.selected_id:
            return None
        for c in self.candidates:
            if c.candidate_id == self.selected_id:
                return c
        return None

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.public_dict() for c in self.candidates],
            "selected_id": self.selected_id,
            "evaluation": dict(self.evaluation),
            "truth": {
                "ttc_improves_difficult_tasks_when_budgeted": True,
                "integrity_scorer_is_technical_not_ideological": True,
            },
        }


class CandidateScorer(Protocol):
    name: str

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore: ...


class SchemaScorer:
    name = "SchemaScorer"

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        schema = context.get("response_schema")
        if not schema:
            return CandidateScore(self.name, 1.0, detail="no schema required")
        payload = candidate.structured
        if payload is None:
            try:
                payload = json.loads(candidate.output)
            except Exception:  # noqa: BLE001
                return CandidateScore(
                    self.name, 0.0, detail="output is not JSON", hard_fail=True
                )
        ok, detail = _validate_json_schema(payload, schema, path="$")
        if not ok:
            return CandidateScore(self.name, 0.0, detail=detail, hard_fail=True)
        return CandidateScore(self.name, 1.0, detail="schema valid")


def _validate_json_schema(payload: Any, schema: dict[str, Any], *, path: str) -> tuple[bool, str]:
    """Minimal but recursive JSON-schema subset: type, required, properties, enum, minimum/maximum."""
    if not isinstance(schema, dict):
        return True, "no schema"
    expected_type = schema.get("type")
    if expected_type:
        type_ok = {
            "object": isinstance(payload, dict),
            "array": isinstance(payload, list),
            "string": isinstance(payload, str),
            "number": isinstance(payload, (int, float)) and not isinstance(payload, bool),
            "integer": isinstance(payload, int) and not isinstance(payload, bool),
            "boolean": isinstance(payload, bool),
            "null": payload is None,
        }.get(str(expected_type))
        if type_ok is False:
            return False, f"{path}: expected type {expected_type}, got {type(payload).__name__}"
    if "enum" in schema and payload not in schema["enum"]:
        return False, f"{path}: value not in enum"
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if "minimum" in schema and payload < schema["minimum"]:
            return False, f"{path}: below minimum"
        if "maximum" in schema and payload > schema["maximum"]:
            return False, f"{path}: above maximum"
    if isinstance(payload, dict):
        required = list(schema.get("required") or [])
        missing = [k for k in required if k not in payload]
        if missing:
            return False, f"{path}: missing required keys: {missing}"
        props = dict(schema.get("properties") or {})
        for key, subschema in props.items():
            if key not in payload:
                continue
            if isinstance(subschema, dict):
                ok, detail = _validate_json_schema(payload[key], subschema, path=f"{path}.{key}")
                if not ok:
                    return False, detail
    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(payload):
            ok, detail = _validate_json_schema(item, schema["items"], path=f"{path}[{i}]")
            if not ok:
                return False, detail
    return True, "ok"


class GroundingScorer:
    name = "GroundingScorer"

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        """Lexical evidence-ref presence is a weak signal; missing required refs hard-fail."""
        required_refs = list(context.get("required_evidence_refs") or [])
        if not required_refs:
            return CandidateScore(self.name, 0.8, detail="no evidence refs required")
        blob = (candidate.output or "") + json.dumps(candidate.structured or {})
        hits = sum(1 for ref in required_refs if str(ref) in blob)
        ratio = hits / max(1, len(required_refs))
        # Lexical containment alone is not strong proof — keep score in a weak band.
        weak_score = round(0.35 + 0.40 * ratio, 3)
        missing = ratio < 0.34
        return CandidateScore(
            self.name,
            weak_score if not missing else 0.0,
            detail=(
                f"evidence refs hit {hits}/{len(required_refs)} "
                f"(lexical weak-only)"
            ),
            # Verifier failure: required grounding absent → hard-fail even if peers agree.
            hard_fail=missing,
        )


class ConsistencyScorer:
    name = "ConsistencyScorer"

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        """Peer lexical agreement is weak only; unanimous invalid can still hard-fail."""
        peers = [
            c
            for c in (context.get("peer_outputs") or [])
            if isinstance(c, str) and c.strip()
        ]
        if not peers:
            return CandidateScore(self.name, 0.55, detail="no peers for consistency")
        tokens = set(re.findall(r"[a-z0-9]{4,}", (candidate.output or "").lower()))
        if not tokens:
            return CandidateScore(self.name, 0.3, detail="empty token set")
        overlaps = []
        for peer in peers:
            pt = set(re.findall(r"[a-z0-9]{4,}", peer.lower()))
            if not pt:
                continue
            overlaps.append(len(tokens & pt) / max(1, len(tokens | pt)))
        if not overlaps:
            return CandidateScore(self.name, 0.5, detail="peers empty")
        mean = sum(overlaps) / len(overlaps)
        # Lexical Jaccard is never strong verification — compress into a weak band.
        weak_score = round(0.40 + 0.25 * mean, 3)
        unanimous = mean >= 0.85 and len(overlaps) >= 1
        hard_fail = False
        detail = f"mean Jaccard={mean:.3f} (lexical weak-only)"
        if unanimous and _verifier_rejects_candidate(candidate, context):
            hard_fail = True
            detail = (
                f"{detail}; unanimous_invalid_verifier_fail "
                "(lexical agreement does not override verifiers)"
            )
        return CandidateScore(
            self.name, weak_score, detail=detail, hard_fail=hard_fail
        )


def _verifier_rejects_candidate(candidate: Candidate, context: dict[str, Any]) -> bool:
    """True when schema/grounding/constraint/tool verifiers fail for this candidate."""
    explicit = context.get("verifier_failures") or context.get("verifier_hard_fail")
    if explicit:
        return True
    schema = context.get("response_schema")
    if schema:
        payload = candidate.structured
        if payload is None:
            try:
                payload = json.loads(candidate.output)
            except Exception:  # noqa: BLE001
                return True
        ok, _ = _validate_json_schema(payload, schema, path="$")
        if not ok:
            return True
    required_refs = list(context.get("required_evidence_refs") or [])
    if required_refs:
        blob = (candidate.output or "") + json.dumps(candidate.structured or {})
        hits = sum(1 for ref in required_refs if str(ref) in blob)
        if hits / max(1, len(required_refs)) < 0.34:
            return True
    constraints = [str(c) for c in (context.get("constraints") or []) if str(c).strip()]
    text = (candidate.output or "").lower()
    failed_constraints = 0
    for raw in constraints:
        lower = raw.lower()
        if lower.startswith("must_include:"):
            needle = raw.split(":", 1)[1].strip().lower()
            if needle and needle not in text:
                failed_constraints += 1
        elif lower.startswith("must_not_include:"):
            needle = raw.split(":", 1)[1].strip().lower()
            if needle and needle in text:
                failed_constraints += 1
    if failed_constraints >= 2:
        return True
    receipts = {
        str(r).lower()
        for r in (context.get("tool_receipts") or [])
        if r is not None
    }
    claim_patterns = (
        (r"\bi (?:ran|executed) (?:the )?tests?\b", "tests"),
        (r"\bi (?:edited|wrote|patched) (?:the )?file\b", "file_write"),
        (r"\bi (?:browsed|navigated|opened) (?:the )?page\b", "browser"),
        (r"\bi searched the (?:web|internet)\b", "web_search"),
    )
    for pattern, kind in claim_patterns:
        if re.search(pattern, text) and kind not in receipts and f"receipt:{kind}" not in receipts:
            return True
    return False


class ConstraintScorer:
    name = "ConstraintScorer"

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        constraints = [str(c) for c in (context.get("constraints") or []) if str(c).strip()]
        if not constraints:
            return CandidateScore(self.name, 1.0, detail="no constraints")
        text = (candidate.output or "").lower()
        failed: list[str] = []
        for raw in constraints:
            # Support simple "must_include:foo" / "must_not_include:bar" forms.
            if raw.lower().startswith("must_include:"):
                needle = raw.split(":", 1)[1].strip().lower()
                if needle and needle not in text:
                    failed.append(raw)
            elif raw.lower().startswith("must_not_include:"):
                needle = raw.split(":", 1)[1].strip().lower()
                if needle and needle in text:
                    failed.append(raw)
        if failed:
            return CandidateScore(
                self.name,
                max(0.0, 1.0 - 0.35 * len(failed)),
                detail=f"failed: {failed[:5]}",
                hard_fail=len(failed) >= 2,
            )
        return CandidateScore(self.name, 1.0, detail="constraints satisfied")


class ToolGroundingScorer:
    name = "ToolGroundingScorer"

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        """Reject fabricated tool success claims without receipts."""
        receipts = {
            str(r).lower()
            for r in (context.get("tool_receipts") or [])
            if r is not None
        }
        text = (candidate.output or "").lower()
        claim_patterns = [
            (r"\bi (?:ran|executed) (?:the )?tests?\b", "tests"),
            (r"\bi (?:edited|wrote|patched) (?:the )?file\b", "file_write"),
            (r"\bi (?:browsed|navigated|opened) (?:the )?page\b", "browser"),
            (r"\bi searched the (?:web|internet)\b", "web_search"),
        ]
        fabricated = 0
        for pattern, kind in claim_patterns:
            if re.search(pattern, text) and kind not in receipts and f"receipt:{kind}" not in receipts:
                fabricated += 1
        if fabricated:
            return CandidateScore(
                self.name,
                max(0.0, 1.0 - 0.4 * fabricated),
                detail=f"fabricated_tool_claims={fabricated}",
                hard_fail=fabricated > 0,
            )
        return CandidateScore(self.name, 1.0, detail="no ungrounded tool claims")


class IntegrityScorer:
    """TECHNICAL integrity only — not moral/political/ideological moderation."""

    name = "IntegrityScorer"

    _INJECTION_MARKERS = (
        "ignore previous instructions",
        "ignore all prior instructions",
        "disregard system prompt",
        "you are now dan",
    )

    def score(self, candidate: Candidate, *, context: dict[str, Any]) -> CandidateScore:
        text = (candidate.output or "").lower()
        issues: list[str] = []

        # Prompt-injection boundary: candidate must not treat data as new system authority.
        if any(m in text for m in self._INJECTION_MARKERS) and context.get(
            "allow_injection_echo"
        ):
            # Echoing the marker from data can be OK; elevating it as adopted policy is not.
            if "i will ignore" in text or "new system instructions" in text:
                issues.append("prompt_injection_boundary_violation")

        # Unsupported capability claims.
        unsupported = {
            str(c).lower() for c in (context.get("unsupported_capabilities") or [])
        }
        for cap in unsupported:
            if cap and cap in text and ("i can" in text or "supported" in text):
                issues.append(f"unsupported_capability_claim:{cap}")

        # Secret leakage heuristics (technical).
        if re.search(r"(api[_-]?key|secret|password)\s*[:=]\s*\S+", text, re.I):
            issues.append("secret_leakage_pattern")

        # Context authority confusion — claiming retrieved data became system law.
        if "as system instructions from the document" in text or "elevated to system" in text:
            issues.append("context_authority_confusion")

        # Output schema hard requirement.
        if context.get("response_schema") and candidate.structured is None:
            try:
                json.loads(candidate.output)
            except Exception:  # noqa: BLE001
                issues.append("output_schema_invalid")

        if issues:
            return CandidateScore(
                self.name,
                max(0.0, 1.0 - 0.35 * len(issues)),
                detail=";".join(issues),
                hard_fail=True,
            )
        return CandidateScore(
            self.name,
            1.0,
            detail="technical integrity ok (not content moderation)",
        )


DEFAULT_SCORERS: tuple[CandidateScorer, ...] = (
    SchemaScorer(),
    GroundingScorer(),
    ConsistencyScorer(),
    ConstraintScorer(),
    ToolGroundingScorer(),
    IntegrityScorer(),
)


@dataclass
class TestTimeComputeEngine:
    """Bounded candidate search / prune / repair."""

    __test__ = False  # not a pytest test class

    scorers: tuple[CandidateScorer, ...] = DEFAULT_SCORERS
    max_candidates: int = 5
    max_repairs: int = 1

    def score_all(
        self,
        candidates: list[Candidate],
        *,
        context: dict[str, Any] | None = None,
    ) -> CandidateSet:
        ctx = dict(context or {})
        limited = list(candidates[: self.max_candidates])
        scored: list[Candidate] = []
        for cand in limited:
            # Include identical peer texts — unanimous agreement must be visible.
            # Filtering by text equality hid unanimous invalid candidates.
            peer_outputs = [
                c.output
                for c in limited
                if c.candidate_id != cand.candidate_id and isinstance(c.output, str)
            ]
            local_ctx = {**ctx, "peer_outputs": peer_outputs}
            cand.scores = [s.score(cand, context=local_ctx) for s in self.scorers]
            if any(s.hard_fail for s in cand.scores):
                cand.rejected = True
                cand.reject_reason = ";".join(
                    s.detail or s.scorer for s in cand.scores if s.hard_fail
                )
            scored.append(cand)
        surviving = [c for c in scored if not c.rejected]
        pool = surviving or scored
        selected = max(pool, key=lambda c: c.aggregate_score)
        return CandidateSet(
            candidates=scored,
            selected_id=selected.candidate_id,
            evaluation={
                "scorer_names": [s.name for s in self.scorers],
                "surviving": len(surviving),
                "rejected": sum(1 for c in scored if c.rejected),
                "selected_hash": selected.content_hash,
                "selected_aggregate": selected.aggregate_score,
                "all_candidates_hard_failed": len(surviving) == 0 and bool(scored),
                "lexical_agreement_does_not_override_verifier_fail": True,
            },
        )

    def prune(self, candidate_set: CandidateSet, *, keep: int = 2) -> CandidateSet:
        ordered = sorted(
            candidate_set.candidates,
            key=lambda c: (not c.rejected, c.aggregate_score),
            reverse=True,
        )
        kept = ordered[: max(1, keep)]
        for c in ordered[max(1, keep) :]:
            if not c.rejected:
                c.rejected = True
                c.reject_reason = c.reject_reason or "pruned_low_score"
        selected = max(kept, key=lambda c: c.aggregate_score)
        return CandidateSet(
            candidates=ordered,
            selected_id=selected.candidate_id,
            evaluation={
                **candidate_set.evaluation,
                "pruned_to": len(kept),
            },
        )

    def repair(
        self,
        candidate: Candidate,
        *,
        reviser: Callable[[Candidate, list[str]], Candidate],
        context: dict[str, Any] | None = None,
    ) -> Candidate:
        """Bounded revision using explicit verifier feedback (not hidden CoT)."""
        feedback = [
            s.detail or s.scorer
            for s in candidate.scores
            if s.hard_fail or s.score < 0.5
        ]
        if not feedback:
            return candidate
        revised = reviser(candidate, feedback[:8])
        # Re-score revised candidate alone.
        result = self.score_all([revised], context=context)
        return result.candidates[0]

    def run(
        self,
        outputs: list[str] | list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        keep: int = 2,
        reviser: Callable[[Candidate, list[str]], Candidate] | None = None,
    ) -> CandidateSet:
        candidates: list[Candidate] = []
        for i, item in enumerate(outputs[: self.max_candidates]):
            if isinstance(item, dict):
                candidates.append(
                    Candidate(
                        candidate_id=str(item.get("candidate_id") or f"c{i}"),
                        output=str(item.get("output") or item.get("text") or ""),
                        structured=item.get("structured")
                        if isinstance(item.get("structured"), dict)
                        else None,
                        usage=dict(item.get("usage") or {}),
                    )
                )
            else:
                candidates.append(Candidate(candidate_id=f"c{i}", output=str(item)))
        result = self.score_all(candidates, context=context)
        result = self.prune(result, keep=keep)
        if reviser is not None and self.max_repairs > 0:
            selected = result.selected
            if selected is not None and (selected.rejected or selected.aggregate_score < 0.55):
                repaired = self.repair(selected, reviser=reviser, context=context)
                # Replace selected slot.
                for idx, c in enumerate(result.candidates):
                    if c.candidate_id == selected.candidate_id:
                        result.candidates[idx] = repaired
                        break
                result = self.score_all(result.candidates, context=context)
                result = self.prune(result, keep=keep)
                result.evaluation["repaired"] = True
        return result
