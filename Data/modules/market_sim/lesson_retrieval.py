"""Canonical lesson retrieval for autonomous research generation.

Lessons are advisory. Negative experience is first-class. Historical lessons
must not prevent novel exploration — they inform failure modes and ranking.

Lifecycle metadata uses LearningEpistemicState:
PROPOSED / OBSERVED / MEASURED / REPLICATED / VERIFIED / REJECTED / SUPERSEDED.
"""

from __future__ import annotations

from typing import Any, Sequence

from .learning_memory import (
    LearningEpistemicState,
    map_epistemic_to_trust,
    map_legacy_epistemic_state,
)


# Bounded ranked context — avoid naive prompt stuffing.
_MAX_PRIOR_LESSONS = 12
_MAX_NEGATIVE_FIRST = 6

# Canonical lifecycle states persisted on lesson metadata (no new DB).
LESSON_LIFECYCLE_STATES: tuple[str, ...] = tuple(s.value for s in LearningEpistemicState)

_ADAPTIVE_LIFECYCLE = frozenset(
    {
        LearningEpistemicState.PROPOSED.value,
        LearningEpistemicState.OBSERVED.value,
        LearningEpistemicState.MEASURED.value,
        LearningEpistemicState.REPLICATED.value,
        LearningEpistemicState.VERIFIED.value,
    }
)
# Rejected / superseded remain first-class advisory priors (not eternal bans).
_ADVISORY_LIFECYCLE = _ADAPTIVE_LIFECYCLE | {
    LearningEpistemicState.REJECTED.value,
    LearningEpistemicState.SUPERSEDED.value,
}

_ADAPTIVE_TRUST = frozenset(
    {"VALIDATED", "AGENT_PROPOSED", "MEASURED", "REPLICATED", "VERIFIED", "OBSERVED", "PROPOSED"}
)
_NEGATIVE_MARKERS = (
    "transaction-cost",
    "transaction_cost",
    "cost_sensitivity",
    "regime brittleness",
    "regime_brittleness",
    "unstable parameter",
    "leakage",
    "insufficient sample",
    "walk-forward",
    "walk_forward",
    "capacity",
    "liquidity",
    "high-turnover",
    "high_turnover",
    "survivorship",
    "model dependency",
    "rejected",
    "no strategy qualified",
    "drawdown",
    "overfit",
)


def _as_dict(lesson: Any) -> dict[str, Any]:
    if isinstance(lesson, dict):
        return dict(lesson)
    if hasattr(lesson, "public_dict"):
        return dict(lesson.public_dict())
    out: dict[str, Any] = {}
    for key in (
        "lesson_id",
        "claim",
        "evidence_refs",
        "evidenceRefs",
        "applies_to",
        "appliesTo",
        "confidence",
        "trust",
        "epistemic_state",
        "epistemicState",
        "lifecycle_state",
        "available_at",
        "availableAt",
        "created_at",
        "createdAt",
        "rejected",
        "outcome_summary",
        "metadata",
        "validation_stage",
        "failure_categories",
        "supersedes",
        "cost_assumptions",
        "strategy_id",
        "origin",
    ):
        if hasattr(lesson, key):
            out[key] = getattr(lesson, key)
    return out


def _normalize_lesson(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    claim = str(
        raw.get("claim")
        or raw.get("outcome_summary")
        or raw.get("lesson")
        or meta.get("claim")
        or ""
    ).strip()
    applies = list(raw.get("applies_to") or raw.get("appliesTo") or [])
    if not applies:
        app = raw.get("applicability") if isinstance(raw.get("applicability"), dict) else {}
        applies = list(app.get("applies_to") or app.get("symbols") or [])
    evidence = list(raw.get("evidence_refs") or raw.get("evidenceRefs") or meta.get("evidence_refs") or [])
    raw_trust = str(
        raw.get("trust")
        or raw.get("epistemic_state")
        or raw.get("epistemicState")
        or meta.get("trust")
        or meta.get("epistemic_state")
        or meta.get("lifecycle_state")
        or ("REJECTED" if raw.get("rejected") else "PROPOSED")
    )
    lifecycle = map_legacy_epistemic_state(raw_trust)
    trust = map_epistemic_to_trust(lifecycle)
    available_at = str(raw.get("available_at") or raw.get("availableAt") or raw.get("created_at") or "")
    rejected = bool(raw.get("rejected")) or lifecycle in {
        LearningEpistemicState.REJECTED,
        LearningEpistemicState.SUPERSEDED,
    }
    supersedes = list(raw.get("supersedes") or meta.get("supersedes") or [])
    cost_assumptions: dict[str, Any] = {}
    if isinstance(raw.get("cost_assumptions"), dict):
        cost_assumptions = dict(raw["cost_assumptions"])
    elif isinstance(meta.get("cost_assumptions"), dict):
        cost_assumptions = dict(meta["cost_assumptions"])
    elif meta.get("cost_assumption_fingerprint"):
        cost_assumptions = {"fingerprint": meta.get("cost_assumption_fingerprint")}
    failure_categories = list(
        raw.get("failure_categories")
        or meta.get("failure_categories")
        or []
    )
    claim_l = claim.lower()
    for marker in _NEGATIVE_MARKERS:
        if marker in claim_l and marker not in failure_categories:
            failure_categories.append(marker.replace(" ", "_").replace("-", "_"))
    if rejected and "rejected" not in failure_categories:
        failure_categories.append("rejected")

    return {
        "lesson_id": str(raw.get("lesson_id") or raw.get("memory_id") or meta.get("lesson_id") or ""),
        "claim": claim,
        "evidence_refs": evidence[:12],
        "applies_to": [str(a) for a in applies][:12],
        "confidence": float(raw.get("confidence") or meta.get("confidence") or 0.0),
        "trust": trust,
        "epistemic_state": lifecycle.value,
        "lifecycle_state": lifecycle.value,
        "available_at": available_at,
        "created_at": str(raw.get("created_at") or raw.get("createdAt") or available_at),
        "rejected": rejected,
        "origin": str(raw.get("origin") or meta.get("origin") or source),
        "strategy_id": str(raw.get("strategy_id") or meta.get("strategy_id") or ""),
        "validation_stage": str(
            raw.get("validation_stage")
            or meta.get("validation_stage")
            or meta.get("split_role")
            or ""
        ),
        "failure_categories": failure_categories[:12],
        "supersedes": supersedes[:12],
        "cost_assumptions": cost_assumptions,
        "asset_class": str(raw.get("asset_class") or meta.get("asset_class") or ""),
        "regime": str(raw.get("regime") or meta.get("regime") or ""),
        "strategy_family": str(raw.get("strategy_family") or meta.get("strategy_family") or ""),
        "timeframe": str(raw.get("timeframe") or meta.get("timeframe") or ""),
        "source": source,
        "metadata": {
            "source": source,
            "epistemic_state": lifecycle.value,
            "lifecycle_state": lifecycle.value,
            "contradiction": bool(meta.get("contradiction") or raw.get("contradiction")),
            "supersedes": supersedes[:12],
            "cost_assumptions": cost_assumptions,
        },
    }


def _pit_ok(lesson: dict[str, Any], *, as_of: str | None) -> bool:
    if not as_of:
        return True
    available = str(lesson.get("available_at") or "")
    if not available:
        # Timeless reference lessons are advisory-only and allowed.
        return True
    return available <= as_of


def _matches_scope(
    lesson: dict[str, Any],
    *,
    symbols: Sequence[str] | None,
    asset_classes: Sequence[str] | None,
    strategy_family: str | None,
    regime: str | None,
    timeframe: str | None,
) -> float:
    """Return a relevance score; 0 means keep only as weak background."""
    score = 0.5  # baseline — exploration retains weak matches
    applies = {str(a).upper() for a in (lesson.get("applies_to") or [])}
    claim = str(lesson.get("claim") or "").lower()
    if symbols:
        for sym in symbols:
            su = str(sym).upper()
            if su in applies or su.lower() in claim:
                score += 2.0
                break
    if asset_classes:
        ac = str(lesson.get("asset_class") or "").lower()
        for item in asset_classes:
            if item and (str(item).lower() == ac or str(item).lower() in claim):
                score += 1.0
                break
    if strategy_family:
        sf = str(lesson.get("strategy_family") or "").lower()
        if strategy_family.lower() == sf or strategy_family.lower() in claim:
            score += 1.5
    if regime:
        lr = str(lesson.get("regime") or "").lower()
        if regime.lower() == lr or regime.lower() in claim:
            score += 1.5
    if timeframe:
        tf = str(lesson.get("timeframe") or "").lower()
        if timeframe.lower() == tf or timeframe.lower() in claim:
            score += 0.5
    if lesson.get("rejected") or lesson.get("failure_categories"):
        score += 1.0  # negative experience is first-class
    lifecycle = str(lesson.get("lifecycle_state") or lesson.get("epistemic_state") or "").upper()
    trust = str(lesson.get("trust") or "").upper()
    if lifecycle == LearningEpistemicState.VERIFIED.value or trust == "VALIDATED":
        score += 1.5
    elif lifecycle in {
        LearningEpistemicState.MEASURED.value,
        LearningEpistemicState.REPLICATED.value,
        LearningEpistemicState.OBSERVED.value,
    }:
        score += 1.0
    elif lifecycle == LearningEpistemicState.PROPOSED.value or trust == "AGENT_PROPOSED":
        score += 0.25  # advisory, never treated as proof
    elif lifecycle == LearningEpistemicState.SUPERSEDED.value:
        score *= 0.35  # retained history, weak influence
    conf = float(lesson.get("confidence") or 0.0)
    score += min(max(conf, 0.0), 1.0)
    return score


def retrieve_prior_lessons_for_generation(
    plane: Any,
    run: Any,
    *,
    perception: dict[str, Any] | None = None,
    as_of: str | None = None,
    limit: int = _MAX_PRIOR_LESSONS,
) -> list[dict[str, Any]]:
    """Canonical bounded ranked prior lessons for candidate generation.

    Pulls from:
    * Agent lab lessons (when lab_id present)
    * Durable StrategyMemory (PIT via available_at)

    Filters by trust, PIT, scope overlap. Negative lessons ranked first.
    Does NOT prevent novel exploration — callers use lessons as advisory context.
    """
    perception = dict(perception or {})
    meta = dict(getattr(run, "metadata", None) or {})
    obj_meta = dict(meta.get("objective") or {}) if isinstance(meta.get("objective"), dict) else {}

    symbols = list(
        perception.get("symbols")
        or meta.get("symbols")
        or obj_meta.get("symbols")
        or ([perception.get("symbol")] if perception.get("symbol") else [])
        or []
    )
    symbols = [str(s) for s in symbols if s]
    regime = str(perception.get("regime") or meta.get("regime") or "")
    timeframe = str(perception.get("timeframe") or meta.get("timeframe") or obj_meta.get("timeframe") or "")
    strategy_family = str(meta.get("strategy_family") or obj_meta.get("strategy_family") or "")
    asset_classes = list(meta.get("asset_classes") or obj_meta.get("asset_classes") or [])
    decision_as_of = str(as_of or perception.get("as_of") or "")

    collected: list[dict[str, Any]] = []

    # 1) Lab lessons
    lab_id = getattr(run, "lab_id", None) or meta.get("lab_id")
    store = getattr(plane, "store", None)
    if lab_id and store is not None and hasattr(store, "get_agent_lab"):
        try:
            lab = store.get_agent_lab(lab_id)
            for raw in list((lab or {}).get("lessons") or []):
                lesson = _normalize_lesson(_as_dict(raw), source="lab_lesson")
                if not lesson.get("claim"):
                    continue
                if not _pit_ok(lesson, as_of=decision_as_of):
                    continue
                lifecycle = str(lesson.get("lifecycle_state") or lesson.get("epistemic_state") or "").upper()
                trust = str(lesson.get("trust") or "").upper()
                if lifecycle and lifecycle not in _ADVISORY_LIFECYCLE:
                    if trust and trust not in _ADAPTIVE_TRUST and trust not in {"REJECTED", "SUPERSEDED"}:
                        continue
                collected.append(lesson)
        except Exception:  # noqa: BLE001
            pass

    # 2) Durable StrategyMemory — include rejected / negative as first-class
    if store is not None and hasattr(store, "list_strategy_memories"):
        try:
            rows = store.list_strategy_memories(as_of_ts=decision_as_of or None, limit=max(limit * 4, 48))
            for row in rows or []:
                lesson = _normalize_lesson(_as_dict(row), source="strategy_memory")
                if not lesson.get("claim"):
                    continue
                # SEALED is an epistemic sink — skip for adaptive generation priors
                stage = str(lesson.get("validation_stage") or "").upper()
                meta_row = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                ec = str(meta_row.get("evidence_class") or "").upper()
                if "SEALED" in stage or "SEALED" in ec:
                    # Still allow rejected sealed? No — sealed never adaptive.
                    continue
                collected.append(lesson)
        except Exception:  # noqa: BLE001
            pass

    # Deduplicate by claim prefix + applies_to
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for lesson in collected:
        key = (
            str(lesson.get("claim") or "")[:160].lower()
            + "|"
            + ",".join(sorted(str(a).upper() for a in (lesson.get("applies_to") or [])[:4]))
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(lesson)

    scored: list[tuple[float, dict[str, Any]]] = []
    for lesson in unique:
        score = _matches_scope(
            lesson,
            symbols=symbols,
            asset_classes=asset_classes,
            strategy_family=strategy_family or None,
            regime=regime or None,
            timeframe=timeframe or None,
        )
        scored.append((score, lesson))
    scored.sort(
        key=lambda item: (
            0 if item[1].get("rejected") or item[1].get("failure_categories") else 1,
            -item[0],
            str(item[1].get("available_at") or ""),
        )
    )

    # Exploration/exploitation: keep top negatives + mix of positives.
    negatives = [L for s, L in scored if L.get("rejected") or L.get("failure_categories")]
    positives = [L for s, L in scored if not (L.get("rejected") or L.get("failure_categories"))]
    out: list[dict[str, Any]] = []
    out.extend(negatives[:_MAX_NEGATIVE_FIRST])
    remaining = max(0, limit - len(out))
    out.extend(positives[:remaining])
    # If still short, fill from remaining scored
    if len(out) < limit:
        for _, lesson in scored:
            if lesson in out:
                continue
            out.append(lesson)
            if len(out) >= limit:
                break
    return out[:limit]
