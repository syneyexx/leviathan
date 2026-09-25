"""Claim extraction and factuality gate for assistant answers.

Extends VerificationEngine ownership — not a second TruthEngine.
Model prose claiming verified=true is never treated as verification.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClaimKind(str, Enum):
    SELF_SYSTEM = "SELF_SYSTEM"
    CURRENT_TIME_SENSITIVE = "CURRENT_TIME_SENSITIVE"
    FILE = "FILE"
    TOOL_SUCCESS = "TOOL_SUCCESS"
    COMPUTATIONAL = "COMPUTATIONAL"
    REPOSITORY = "REPOSITORY"
    CREATIVE = "CREATIVE"
    ORDINARY_FACTUAL = "ORDINARY_FACTUAL"
    OPINION = "OPINION"


class ClaimSupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONFLICTED = "CONFLICTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNMEASURED = "UNMEASURED"
    INFERRED = "INFERRED"
    MODEL_PRIOR = "MODEL_PRIOR"
    TOOL_VERIFIED = "TOOL_VERIFIED"
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    CORROBORATED = "CORROBORATED"
    UNAVAILABLE = "UNAVAILABLE"


class FactualityMode(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    REQUIRED = "REQUIRED"
    CORROBORATED = "CORROBORATED"


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    claim_text: str
    claim_kind: ClaimKind
    status: ClaimSupportStatus
    source_refs: tuple[str, ...] = ()
    tool_receipt_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    freshness_requirement: str | None = None
    as_of: str | None = None
    confidence: float | None = None
    contradiction_refs: tuple[str, ...] = ()
    reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "claim_kind": self.claim_kind.value,
            "status": self.status.value,
            "source_refs": list(self.source_refs),
            "tool_receipt_refs": list(self.tool_receipt_refs),
            "evidence_refs": list(self.evidence_refs),
            "artifact_refs": list(self.artifact_refs),
            "freshness_requirement": self.freshness_requirement,
            "as_of": self.as_of,
            "confidence": self.confidence,
            "contradiction_refs": list(self.contradiction_refs),
            "reason": self.reason,
            "truth": {
                "model_verified_flag_is_not_verification": True,
                "invented_evidence_refs_are_rejected": True,
            },
        }


@dataclass(frozen=True)
class FactualityResult:
    mode: FactualityMode
    original_text: str
    revised_text: str
    assessments: tuple[ClaimAssessment, ...] = ()
    qualified: bool = False
    blocked: bool = False
    reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "original_text": self.original_text,
            "revised_text": self.revised_text,
            "assessments": [a.public_dict() for a in self.assessments],
            "qualified": self.qualified,
            "blocked": self.blocked,
            "reason": self.reason,
            "truth": {
                "model_output_is_not_evidence": True,
                "unmeasured_is_not_supported": True,
                "creative_content_is_not_broken": True,
            },
        }


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Deterministic extractors — ordered most-specific first.
_SELF_METRIC = re.compile(
    r"(?i)\b(?:i(?:'m| am)?|we(?:'re| are)?|the\s+(?:system|brain|runtime|model|assistant))"
    r"[^.!?\n]{0,80}?\b(\d{1,3})\s*%\b"
    r"|"
    r"\b(\d{1,3})\s*%\s*(?:of\s+)?(?:my\s+)?(?:brain|cpu|gpu|ram|memory|capacity|utilization|load|compute)\b"
)
_TOOL_SUCCESS = re.compile(
    r"(?i)\b(?:"
    r"successfully\s+(?:wrote|created|updated|deleted|ran|executed|called|invoked)|"
    r"(?:tool|command|script)\s+(?:succeeded|completed\s+successfully|returned\s+success)|"
    r"(?:wrote|created|saved|deleted)\s+(?:the\s+)?file|"
    r"tests?\s+passed|"
    r"execution\s+(?:succeeded|completed)"
    r")\b"
)
_FILE_CLAIM = re.compile(
    r"(?i)\b(?:"
    r"file\s+(?:exists|is\s+present|was\s+created|was\s+written|was\s+saved)|"
    r"(?:created|wrote|saved|updated|deleted)\s+(?:file\s+)?"
    r"[`\"']?[\w./\\-]+\.(?:py|ts|tsx|js|json|md|txt|yml|yaml|toml|cfg|ini)[`\"']?"
    r")\b"
)
_CURRENT_INFO = re.compile(
    r"(?i)\b(?:"
    r"currently|right\s+now|as\s+of\s+(?:today|now)|"
    r"latest\s+(?:version|release|news|data|figure|price)|"
    r"today(?:'s)?\s+(?:date|price|rate|version)|"
    r"the\s+current\s+(?:version|price|rate|status|count)"
    r")\b"
)
_CREATIVE = re.compile(
    r"(?i)\b(?:"
    r"once\s+upon\s+a\s+time|in\s+a\s+fictional|imagine\s+that|"
    r"here(?:'s| is)\s+a\s+(?:short\s+)?(?:story|poem|haiku|fiction)|"
    r"let(?:'s| us)\s+(?:write|compose|invent)\b"
    r")"
)
_OPINION = re.compile(
    r"(?i)\b(?:i\s+(?:think|believe|feel|prefer)|in\s+my\s+(?:view|opinion)|seems\s+to\s+me)\b"
)
_COMPUTATIONAL = re.compile(
    r"(?i)\b(?:equals?|sum\s+is|product\s+is|\d+\s*[+\-*/×÷]\s*\d+)\b"
)
_REPO = re.compile(
    r"(?i)\b(?:repository|repo|commit|branch|pull\s+request|git\s+status)\b"
)


def _stable_claim_id(text: str, kind: ClaimKind) -> str:
    digest = hashlib.sha256(f"{kind.value}:{text.strip()}".encode("utf-8")).hexdigest()[:16]
    return f"claim:{digest}"


def _split_units(text: str) -> list[str]:
    raw = [p.strip() for p in _SENTENCE_SPLIT.split(text or "") if p and p.strip()]
    if raw:
        return raw
    stripped = (text or "").strip()
    return [stripped] if stripped else []


class ClaimExtractor:
    """Heuristic, deterministic claim extraction for assistant drafts."""

    def extract(self, draft_text: str) -> list[ClaimAssessment]:
        units = _split_units(draft_text)
        claims: list[ClaimAssessment] = []
        seen: set[str] = set()
        for unit in units:
            kind = self._classify(unit)
            if kind is None:
                continue
            claim_id = _stable_claim_id(unit, kind)
            if claim_id in seen:
                continue
            seen.add(claim_id)
            freshness = "fresh_source" if kind == ClaimKind.CURRENT_TIME_SENSITIVE else None
            claims.append(
                ClaimAssessment(
                    claim_id=claim_id,
                    claim_text=unit,
                    claim_kind=kind,
                    status=ClaimSupportStatus.UNMEASURED,
                    freshness_requirement=freshness,
                    reason="extracted_checkable_claim",
                )
            )
        return claims

    def _classify(self, unit: str) -> ClaimKind | None:
        if _CREATIVE.search(unit):
            return ClaimKind.CREATIVE
        if _SELF_METRIC.search(unit):
            return ClaimKind.SELF_SYSTEM
        if _TOOL_SUCCESS.search(unit):
            return ClaimKind.TOOL_SUCCESS
        if _FILE_CLAIM.search(unit):
            return ClaimKind.FILE
        if _CURRENT_INFO.search(unit):
            return ClaimKind.CURRENT_TIME_SENSITIVE
        if _COMPUTATIONAL.search(unit) and re.search(r"\d", unit):
            return ClaimKind.COMPUTATIONAL
        if _REPO.search(unit):
            return ClaimKind.REPOSITORY
        if _OPINION.search(unit):
            return ClaimKind.OPINION
        # Ordinary factual only when declarative and not purely conversational fluff.
        if len(unit) >= 40 and not unit.rstrip().endswith("?"):
            if re.search(r"(?i)\b(?:is|are|was|were|has|have|contains|includes)\b", unit):
                return ClaimKind.ORDINARY_FACTUAL
        return None


@dataclass(frozen=True)
class VerificationPool:
    """Concrete support pool — model flags are ignored."""

    evidence_ids: frozenset[str] = frozenset()
    tool_receipt_ids: frozenset[str] = frozenset()
    source_refs: frozenset[str] = frozenset()
    artifact_ids: frozenset[str] = frozenset()
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    fresh_source_refs: frozenset[str] = frozenset()
    as_of: str | None = None

    @classmethod
    def from_inputs(
        cls,
        *,
        evidence: Sequence[Any] | None = None,
        evidence_ids: Iterable[str] | None = None,
        tool_receipts: Sequence[Any] | None = None,
        tool_receipt_ids: Iterable[str] | None = None,
        source_refs: Iterable[str] | None = None,
        artifact_ids: Iterable[str] | None = None,
        telemetry: Mapping[str, Any] | None = None,
        fresh_source_refs: Iterable[str] | None = None,
        as_of: str | None = None,
    ) -> VerificationPool:
        eids: set[str] = set(evidence_ids or ())
        for item in evidence or ():
            eid = getattr(item, "evidence_id", None)
            if eid is None and isinstance(item, Mapping):
                eid = item.get("evidence_id") or item.get("id")
            if eid:
                eids.add(str(eid))
        rids: set[str] = set(tool_receipt_ids or ())
        for item in tool_receipts or ():
            rid = getattr(item, "receipt_id", None)
            if rid is None and isinstance(item, Mapping):
                rid = item.get("receipt_id") or item.get("id")
            if rid:
                rids.add(str(rid))
        return cls(
            evidence_ids=frozenset(eids),
            tool_receipt_ids=frozenset(rids),
            source_refs=frozenset(str(x) for x in (source_refs or ())),
            artifact_ids=frozenset(str(x) for x in (artifact_ids or ())),
            telemetry=dict(telemetry or {}),
            fresh_source_refs=frozenset(str(x) for x in (fresh_source_refs or ())),
            as_of=as_of,
        )


class ClaimVerifier:
    """Match claims to evidence/tool receipts. Reject invented evidence_refs."""

    def verify(
        self,
        claims: Sequence[ClaimAssessment],
        pool: VerificationPool,
        *,
        proposed_evidence_refs: Mapping[str, Sequence[str]] | None = None,
        proposed_tool_receipt_refs: Mapping[str, Sequence[str]] | None = None,
        model_verified_flags: Mapping[str, bool] | None = None,
    ) -> list[ClaimAssessment]:
        """Return assessed claims.

        ``model_verified_flags`` (critic/model saying verified=true) is ignored
        for support status — never upgrades a claim to TOOL_VERIFIED/SUPPORTED.
        """
        _ = model_verified_flags  # explicitly unused: model flag ≠ verification
        proposed_evidence_refs = proposed_evidence_refs or {}
        proposed_tool_receipt_refs = proposed_tool_receipt_refs or {}
        out: list[ClaimAssessment] = []
        for claim in claims:
            out.append(
                self._verify_one(
                    claim,
                    pool,
                    evidence_refs=tuple(proposed_evidence_refs.get(claim.claim_id, claim.evidence_refs)),
                    tool_refs=tuple(
                        proposed_tool_receipt_refs.get(claim.claim_id, claim.tool_receipt_refs)
                    ),
                )
            )
        return out

    def _verify_one(
        self,
        claim: ClaimAssessment,
        pool: VerificationPool,
        *,
        evidence_refs: tuple[str, ...],
        tool_refs: tuple[str, ...],
    ) -> ClaimAssessment:
        # Creative / opinion: do not force measurement.
        if claim.claim_kind in {ClaimKind.CREATIVE, ClaimKind.OPINION}:
            return replace(
                claim,
                status=ClaimSupportStatus.UNMEASURED,
                evidence_refs=(),
                tool_receipt_refs=(),
                reason="non_checkable_content_left_intact",
                confidence=None,
            )

        # Reject invented evidence IDs — never PASS on fake refs.
        fake_evidence = tuple(ref for ref in evidence_refs if ref not in pool.evidence_ids)
        real_evidence = tuple(ref for ref in evidence_refs if ref in pool.evidence_ids)
        fake_tools = tuple(ref for ref in tool_refs if ref not in pool.tool_receipt_ids)
        real_tools = tuple(ref for ref in tool_refs if ref in pool.tool_receipt_ids)

        if fake_evidence or fake_tools:
            return replace(
                claim,
                status=ClaimSupportStatus.UNSUPPORTED,
                evidence_refs=real_evidence,
                tool_receipt_refs=real_tools,
                contradiction_refs=fake_evidence + fake_tools,
                reason="invented_evidence_refs_rejected",
                confidence=0.0,
            )

        if claim.claim_kind == ClaimKind.SELF_SYSTEM:
            return self._verify_self_system(claim, pool, real_evidence)

        if claim.claim_kind == ClaimKind.TOOL_SUCCESS:
            if real_tools:
                return replace(
                    claim,
                    status=ClaimSupportStatus.TOOL_VERIFIED,
                    tool_receipt_refs=real_tools,
                    evidence_refs=real_evidence,
                    reason="tool_receipt_present",
                    confidence=0.9,
                    as_of=pool.as_of or utc_now(),
                )
            return replace(
                claim,
                status=ClaimSupportStatus.UNSUPPORTED,
                tool_receipt_refs=(),
                evidence_refs=real_evidence,
                reason="tool_claim_without_receipt",
                confidence=0.0,
            )

        if claim.claim_kind == ClaimKind.FILE:
            if real_evidence or real_tools or any(
                a for a in claim.artifact_refs if a in pool.artifact_ids
            ):
                return replace(
                    claim,
                    status=ClaimSupportStatus.TOOL_VERIFIED
                    if real_tools
                    else ClaimSupportStatus.SUPPORTED,
                    evidence_refs=real_evidence,
                    tool_receipt_refs=real_tools,
                    reason="file_claim_backed",
                    confidence=0.85,
                )
            return replace(
                claim,
                status=ClaimSupportStatus.UNMEASURED,
                evidence_refs=(),
                tool_receipt_refs=(),
                reason="file_claim_unmeasured",
                confidence=None,
            )

        if claim.claim_kind == ClaimKind.CURRENT_TIME_SENSITIVE:
            fresh = tuple(ref for ref in (claim.source_refs + real_evidence) if ref in pool.fresh_source_refs)
            if fresh or (pool.fresh_source_refs and real_evidence):
                return replace(
                    claim,
                    status=ClaimSupportStatus.SOURCE_SUPPORTED,
                    source_refs=fresh or tuple(pool.fresh_source_refs)[:3],
                    evidence_refs=real_evidence,
                    reason="fresh_source_present",
                    confidence=0.8,
                    as_of=pool.as_of or utc_now(),
                )
            return replace(
                claim,
                status=ClaimSupportStatus.UNMEASURED,
                evidence_refs=real_evidence,
                reason="current_info_without_fresh_source",
                confidence=None,
                freshness_requirement=claim.freshness_requirement or "fresh_source",
            )

        if real_evidence and len(real_evidence) >= 2:
            return replace(
                claim,
                status=ClaimSupportStatus.CORROBORATED,
                evidence_refs=real_evidence,
                reason="multiple_evidence_refs",
                confidence=0.9,
            )
        if real_evidence:
            return replace(
                claim,
                status=ClaimSupportStatus.SOURCE_SUPPORTED,
                evidence_refs=real_evidence,
                reason="evidence_ref_in_pool",
                confidence=0.75,
            )
        if claim.claim_kind == ClaimKind.COMPUTATIONAL:
            return replace(
                claim,
                status=ClaimSupportStatus.INFERRED,
                reason="computational_unchecked",
                confidence=0.4,
            )
        return replace(
            claim,
            status=ClaimSupportStatus.UNMEASURED,
            evidence_refs=(),
            reason="no_matching_support",
            confidence=None,
        )

    def _verify_self_system(
        self,
        claim: ClaimAssessment,
        pool: VerificationPool,
        real_evidence: tuple[str, ...],
    ) -> ClaimAssessment:
        telemetry = pool.telemetry or {}
        has_telemetry = bool(telemetry)
        metric_match = _SELF_METRIC.search(claim.claim_text)
        claimed_pct: int | None = None
        if metric_match:
            for g in metric_match.groups():
                if g is not None:
                    try:
                        claimed_pct = int(g)
                    except ValueError:
                        claimed_pct = None
                    break

        if not has_telemetry and not real_evidence:
            return replace(
                claim,
                status=ClaimSupportStatus.UNMEASURED,
                evidence_refs=(),
                reason="self_metric_without_telemetry",
                confidence=None,
            )

        # If telemetry exists, try to corroborate numeric claim.
        measured = None
        for key in ("brain_pct", "utilization_pct", "cpu_pct", "memory_pct", "load_pct"):
            if key in telemetry:
                try:
                    measured = float(telemetry[key])
                except (TypeError, ValueError):
                    measured = None
                break
        if claimed_pct is not None and measured is not None:
            if abs(measured - claimed_pct) <= 2.0:
                return replace(
                    claim,
                    status=ClaimSupportStatus.SUPPORTED,
                    evidence_refs=real_evidence,
                    reason="self_metric_matches_telemetry",
                    confidence=0.95,
                    as_of=pool.as_of or utc_now(),
                )
            return replace(
                claim,
                status=ClaimSupportStatus.CONFLICTED,
                evidence_refs=real_evidence,
                reason=f"self_metric_conflicts_telemetry claimed={claimed_pct} measured={measured}",
                confidence=0.2,
            )
        if has_telemetry or real_evidence:
            return replace(
                claim,
                status=ClaimSupportStatus.SUPPORTED if real_evidence else ClaimSupportStatus.INFERRED,
                evidence_refs=real_evidence,
                reason="telemetry_present",
                confidence=0.7,
            )
        return replace(
            claim,
            status=ClaimSupportStatus.UNMEASURED,
            reason="self_metric_without_telemetry",
            confidence=None,
        )


_QUALIFY_CURRENT = (
    " [Note: current/latest claim is unverified — no fresh source available.]"
)
_QUALIFY_TOOL = (
    " [Note: tool/file success claim is unsupported — no capability receipt.]"
)
_QUALIFY_SELF = (
    " [Note: system metric is unmeasured — no telemetry backing this percentage.]"
)


class FactualityGate:
    """draft → extract → verify → revise/qualify unsupported claims."""

    def __init__(
        self,
        *,
        extractor: ClaimExtractor | None = None,
        verifier: ClaimVerifier | None = None,
    ) -> None:
        self.extractor = extractor or ClaimExtractor()
        self.verifier = verifier or ClaimVerifier()

    def apply(
        self,
        draft_text: str,
        *,
        mode: FactualityMode | str = FactualityMode.LIGHT,
        pool: VerificationPool | None = None,
        proposed_evidence_refs: Mapping[str, Sequence[str]] | None = None,
        proposed_tool_receipt_refs: Mapping[str, Sequence[str]] | None = None,
        model_verified_flags: Mapping[str, bool] | None = None,
    ) -> FactualityResult:
        mode_e = FactualityMode(mode) if not isinstance(mode, FactualityMode) else mode
        text = draft_text or ""
        if mode_e == FactualityMode.NONE or not text.strip():
            return FactualityResult(
                mode=mode_e,
                original_text=text,
                revised_text=text,
                assessments=(),
                reason="factuality_skipped",
            )

        pool = pool or VerificationPool()
        extracted = self.extractor.extract(text)
        assessed = self.verifier.verify(
            extracted,
            pool,
            proposed_evidence_refs=proposed_evidence_refs,
            proposed_tool_receipt_refs=proposed_tool_receipt_refs,
            model_verified_flags=model_verified_flags,
        )

        if mode_e == FactualityMode.CORROBORATED:
            assessed = [
                a
                if a.claim_kind in {ClaimKind.CREATIVE, ClaimKind.OPINION}
                or a.status
                in {
                    ClaimSupportStatus.CORROBORATED,
                    ClaimSupportStatus.TOOL_VERIFIED,
                    ClaimSupportStatus.SOURCE_SUPPORTED,
                    ClaimSupportStatus.SUPPORTED,
                }
                else replace(
                    a,
                    status=ClaimSupportStatus.UNSUPPORTED
                    if a.status != ClaimSupportStatus.UNMEASURED
                    else a.status,
                    reason=(a.reason or "") + ";corroboration_required",
                )
                for a in assessed
            ]

        revised, qualified = self._revise(text, assessed, mode=mode_e)
        blocked = False
        reason = "ok"
        if mode_e == FactualityMode.REQUIRED:
            hard = [
                a
                for a in assessed
                if a.claim_kind
                in {
                    ClaimKind.SELF_SYSTEM,
                    ClaimKind.TOOL_SUCCESS,
                    ClaimKind.FILE,
                    ClaimKind.CURRENT_TIME_SENSITIVE,
                }
                and a.status
                in {
                    ClaimSupportStatus.UNSUPPORTED,
                    ClaimSupportStatus.UNMEASURED,
                    ClaimSupportStatus.CONFLICTED,
                }
            ]
            if hard and revised == text:
                # Ensure qualification happened; if still identical, append gate notice.
                revised, qualified = self._revise(text, assessed, mode=mode_e, force=True)
            if any(a.status == ClaimSupportStatus.UNSUPPORTED for a in hard):
                reason = "unsupported_checkable_claims_qualified"
            elif hard:
                reason = "unmeasured_checkable_claims_qualified"

        return FactualityResult(
            mode=mode_e,
            original_text=text,
            revised_text=revised,
            assessments=tuple(assessed),
            qualified=qualified,
            blocked=blocked,
            reason=reason,
        )

    def _revise(
        self,
        text: str,
        assessments: Sequence[ClaimAssessment],
        *,
        mode: FactualityMode,
        force: bool = False,
    ) -> tuple[str, bool]:
        revised = text
        qualified = False
        for claim in assessments:
            if claim.claim_kind == ClaimKind.CREATIVE:
                continue
            if claim.claim_kind == ClaimKind.OPINION:
                continue

            if claim.claim_kind == ClaimKind.SELF_SYSTEM and claim.status in {
                ClaimSupportStatus.UNMEASURED,
                ClaimSupportStatus.UNSUPPORTED,
                ClaimSupportStatus.CONFLICTED,
            }:
                # Strip invented percentages — do not invent a replacement %.
                scrubbed = _SELF_METRIC.sub(
                    lambda m: re.sub(r"\d{1,3}\s*%", "[unmeasured]", m.group(0), count=1),
                    revised,
                )
                if scrubbed != revised:
                    revised = scrubbed
                    qualified = True
                if claim.claim_text in revised and _QUALIFY_SELF not in revised:
                    revised = revised.replace(claim.claim_text, claim.claim_text + _QUALIFY_SELF, 1)
                    qualified = True
                elif force and _QUALIFY_SELF not in revised:
                    revised = revised.rstrip() + _QUALIFY_SELF
                    qualified = True
                continue

            if claim.claim_kind == ClaimKind.TOOL_SUCCESS and claim.status == ClaimSupportStatus.UNSUPPORTED:
                if claim.claim_text in revised and _QUALIFY_TOOL not in revised:
                    revised = revised.replace(claim.claim_text, claim.claim_text + _QUALIFY_TOOL, 1)
                    qualified = True
                elif force and _QUALIFY_TOOL not in revised:
                    revised = revised.rstrip() + _QUALIFY_TOOL
                    qualified = True
                continue

            if claim.claim_kind == ClaimKind.FILE and claim.status in {
                ClaimSupportStatus.UNSUPPORTED,
                ClaimSupportStatus.UNMEASURED,
            }:
                if mode in {FactualityMode.REQUIRED, FactualityMode.CORROBORATED} or force:
                    if claim.claim_text in revised and _QUALIFY_TOOL not in revised:
                        revised = revised.replace(claim.claim_text, claim.claim_text + _QUALIFY_TOOL, 1)
                        qualified = True
                continue

            if (
                claim.claim_kind == ClaimKind.CURRENT_TIME_SENSITIVE
                and claim.status
                in {
                    ClaimSupportStatus.UNMEASURED,
                    ClaimSupportStatus.UNSUPPORTED,
                    ClaimSupportStatus.UNAVAILABLE,
                }
            ):
                if claim.claim_text in revised and _QUALIFY_CURRENT not in revised:
                    revised = revised.replace(
                        claim.claim_text, claim.claim_text + _QUALIFY_CURRENT, 1
                    )
                    qualified = True
                elif force and _QUALIFY_CURRENT not in revised:
                    revised = revised.rstrip() + _QUALIFY_CURRENT
                    qualified = True
                continue

            if (
                mode in {FactualityMode.REQUIRED, FactualityMode.CORROBORATED}
                and claim.status == ClaimSupportStatus.UNSUPPORTED
                and claim.claim_text in revised
            ):
                note = " [Note: claim unsupported by evidence pool.]"
                if note not in revised:
                    revised = revised.replace(claim.claim_text, claim.claim_text + note, 1)
                    qualified = True

        return revised, qualified
