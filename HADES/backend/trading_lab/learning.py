"""Deterministic aggregation, evidence quality and belief updates.

The language model never calculates these numbers. It may interpret a finding after the
finding exists, and only if every claim cites an evidence reference that this module can
resolve. No evidence → the claim is refused and does not become a durable belief.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from trading_lab.contracts import stable_hash
from trading_lab.evaluation import block_bootstrap_interval, sharpe_ratio

MIN_SAMPLES_FOR_FINDING = 20
MIN_SAMPLES_FOR_CONFIRMED = 60
MIN_INDEPENDENT_PERIODS = 2
MAX_CONFIDENCE = 0.95
DEVELOPMENT_CAP = 0.45
VALIDATION_CAP = 0.75
PAPER_CAP = 0.9
SYNTHETIC_PENALTY = 0.25
RECENCY_HALF_LIFE_DAYS = 365.0

BELIEF_STATUSES = (
    "proposed",
    "supported",
    "confirmed",
    "weakened",
    "contradicted",
    "superseded",
    "retired",
)

LEARNING_SPLITS = frozenset({"development", "prospective_paper", "synthetic"})
VALIDATION_SPLITS = frozenset({"validation", "sealed_test"})


def group_key(experience: dict[str, Any], *, include_version: bool = True) -> str:
    parts = {
        "family": experience.get("strategy_family") or "",
        "instrument": experience.get("instrument_id") or "",
        "timeframe": experience.get("timeframe") or "",
        "regime": experience.get("regime_key") or "unavailable",
        "action": experience.get("action") or "",
        "split": experience.get("split") or "development",
        "dataset": experience.get("dataset_checksum") or "",
    }
    if include_version:
        parts["strategy_id"] = experience.get("strategy_id") or ""
        parts["version"] = experience.get("strategy_version")
    return stable_hash(parts)[:32]


def aggregate_experiences(
    rows: Sequence[dict[str, Any]],
    *,
    include_version: bool = True,
    min_samples: int = MIN_SAMPLES_FOR_FINDING,
    seed: int = 7,
) -> list[dict[str, Any]]:
    """Group experiences and compute metrics in code.

    Incompatible strategy versions are not mixed when ``include_version`` is true, which is
    the default. A family-level pass can be requested separately.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(group_key(row, include_version=include_version), []).append(row)

    findings: list[dict[str, Any]] = []
    for key, items in sorted(buckets.items()):
        returns = [float(item["gross_pnl"]) for item in items if item.get("gross_pnl") is not None]
        price_changes = [float(item["price_change"]) for item in items if item.get("price_change") is not None]
        wins = sum(1 for item in items if item.get("outcome_class") == "favorable")
        losses = sum(1 for item in items if item.get("outcome_class") == "adverse")
        decided = [item for item in items if item.get("outcome_class") in {"favorable", "adverse"}]
        maes = [float(item["mae"]) for item in items if item.get("mae") is not None]
        mfes = [float(item["mfe"]) for item in items if item.get("mfe") is not None]
        fees = [float(item["fees"]) for item in items if item.get("fees") is not None]
        excess = [float(item["excess_return"]) for item in items if item.get("excess_return") is not None]
        periods = sorted({str(item.get("event_time") or "")[:10] for item in items if item.get("event_time")})
        instruments = {item.get("instrument_id") for item in items if item.get("instrument_id")}
        versions = {item.get("strategy_version") for item in items}
        sample = len(items)
        mean_return = _mean(returns)
        median_return = _median(returns)
        downside = _downside_deviation(returns)
        concentration = _concentration(returns)
        effect = None
        stdev = _stdev(returns)
        if stdev and stdev > 1e-12 and mean_return is not None:
            effect = mean_return / stdev
        interval = block_bootstrap_interval(returns, "mean", seed=seed) if len(returns) >= 30 else None
        sharpe = sharpe_ratio(returns) if len(returns) >= 3 else None
        sufficient = sample >= min_samples and len(decided) >= max(5, min_samples // 4)
        status = "sufficient" if sufficient else "insufficient_evidence"
        representative = items[0]
        finding_id = "lfind_" + stable_hash({"group": key, "n": sample, "split": representative.get("split")})[:20]
        refs = []
        for item in items[:40]:
            refs.append(f"experience:{item.get('experience_id')}")
        if representative.get("experiment_id"):
            refs.append(f"experiment:{representative.get('experiment_id')}")
        findings.append(
            {
                "finding_id": finding_id,
                "group_key": key,
                "group": {
                    "strategy_family": representative.get("strategy_family"),
                    "strategy_id": representative.get("strategy_id") if include_version else None,
                    "strategy_version": representative.get("strategy_version") if include_version else None,
                    "instrument_id": representative.get("instrument_id"),
                    "timeframe": representative.get("timeframe"),
                    "regime_key": representative.get("regime_key"),
                    "action": representative.get("action"),
                    "split": representative.get("split"),
                    "dataset_checksum": representative.get("dataset_checksum"),
                    "include_version": include_version,
                    "versions_present": sorted(item for item in versions if item is not None),
                },
                "metrics": {
                    "count": sample,
                    "decided": len(decided),
                    "win_rate": (wins / len(decided)) if decided else None,
                    "wins": wins,
                    "losses": losses,
                    "expectancy": mean_return,
                    "mean_return": mean_return,
                    "median_return": median_return,
                    "sharpe_like": sharpe,
                    "downside_deviation": downside,
                    "max_adverse_excursion": min(maes) if maes else None,
                    "max_favorable_excursion": max(mfes) if mfes else None,
                    "cost_drag": _mean(fees),
                    "excess_return": _mean(excess),
                    "consistency_periods": len(periods),
                    "stability_instruments": len(instruments),
                    "concentration_top3": concentration,
                    "confidence_interval_mean": interval,
                    "sample_sufficiency": sufficient,
                    "effect_size": effect,
                    "price_change_mean": _mean(price_changes),
                    "negative_evidence_count": losses,
                },
                "evidence_status": status,
                "sample_count": sample,
                "split": representative.get("split") or "development",
                "evidence_refs": refs,
                "claim": _template_claim(representative, mean_return, sample, sufficient, wins, losses),
            }
        )
    return findings


def _template_claim(
    representative: dict[str, Any],
    expectancy: float | None,
    sample: int,
    sufficient: bool,
    wins: int,
    losses: int,
) -> str:
    family = representative.get("strategy_family") or "strategy"
    instrument = representative.get("instrument_id") or "instrument"
    timeframe = representative.get("timeframe") or "?"
    regime = representative.get("regime_key") or "unclassified"
    if not sufficient:
        return (
            f"{family} on {instrument} {timeframe} in regime {regime}: insufficient_evidence "
            f"(n={sample}; {wins} favorable / {losses} adverse). Not durable knowledge."
        )
    direction = "positive" if (expectancy or 0) > 0 else "negative" if (expectancy or 0) < 0 else "flat"
    return (
        f"{family} on {instrument} {timeframe} showed {direction} expectancy "
        f"{expectancy:.6f} during {regime} (n={sample}; {wins} favorable / {losses} adverse)."
    )


def evidence_confidence(
    finding: dict[str, Any],
    *,
    now: str | None = None,
    last_evidence_at: str | None = None,
) -> dict[str, Any]:
    """Auditable confidence bound. An LLM may not raise this number."""
    metrics = finding.get("metrics") or {}
    sample = int(metrics.get("count") or finding.get("sample_count") or 0)
    split = str(finding.get("split") or "development")
    sufficient = bool(metrics.get("sample_sufficiency"))
    periods = int(metrics.get("consistency_periods") or 0)
    synthetic = bool((finding.get("group") or {}).get("synthetic"))
    if finding.get("is_synthetic"):
        synthetic = True

    if sample <= 0:
        return {"confidence": 0.0, "cap": 0.0, "reasons": ["no_samples"]}

    sample_score = min(1.0, math.log(max(2, sample)) / math.log(200))
    period_score = min(1.0, periods / max(1, MIN_INDEPENDENT_PERIODS * 4))
    effect = abs(float(metrics.get("effect_size") or 0.0))
    effect_score = min(1.0, effect)
    raw = 0.5 * sample_score + 0.25 * period_score + 0.25 * effect_score

    if split == "sealed_test":
        cap = VALIDATION_CAP
    elif split == "validation":
        cap = VALIDATION_CAP
    elif split == "prospective_paper":
        cap = PAPER_CAP
    else:
        cap = DEVELOPMENT_CAP
    if not sufficient:
        cap = min(cap, 0.25)
        raw = min(raw, 0.2)
    if synthetic:
        raw = max(0.0, raw - SYNTHETIC_PENALTY)
        cap = min(cap, 0.35)
    if split in LEARNING_SPLITS and split != "prospective_paper":
        cap = min(cap, DEVELOPMENT_CAP)

    recency = 1.0
    if now and last_evidence_at:
        recency = _recency_factor(last_evidence_at, now)
        raw *= recency

    confidence = max(0.0, min(MAX_CONFIDENCE, min(raw, cap)))
    reasons = [
        f"sample_score={sample_score:.3f}",
        f"period_score={period_score:.3f}",
        f"effect_score={effect_score:.3f}",
        f"split_cap={cap:.3f}",
        f"recency={recency:.3f}",
        f"sufficient={sufficient}",
    ]
    if synthetic:
        reasons.append("synthetic_penalty")
    return {"confidence": round(confidence, 4), "cap": cap, "reasons": reasons, "raw": round(raw, 4)}


def _recency_factor(last_evidence_at: str, now: str) -> float:
    try:
        from datetime import datetime

        last = datetime.fromisoformat(last_evidence_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        days = max(0.0, (current - last).total_seconds() / 86400.0)
    except Exception:
        return 1.0
    # Half-life decay: 1.0 today, 0.5 after RECENCY_HALF_LIFE_DAYS. Old evidence remains
    # auditable; only the confidence weight fades.
    return 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


def belief_scope_key(finding: dict[str, Any]) -> str:
    group = finding.get("group") or {}
    return stable_hash(
        {
            "family": group.get("strategy_family"),
            "instrument": group.get("instrument_id"),
            "timeframe": group.get("timeframe"),
            "regime": group.get("regime_key"),
            "split_class": "validation" if finding.get("split") in VALIDATION_SPLITS else "development",
        }
    )[:24]


def finding_to_belief_proposal(finding: dict[str, Any], *, now: str) -> dict[str, Any] | None:
    refs = list(finding.get("evidence_refs") or [])
    if not refs:
        return None
    metrics = finding.get("metrics") or {}
    expectancy = metrics.get("expectancy")
    quality = evidence_confidence(finding, now=now)
    status = "proposed"
    if finding.get("evidence_status") == "insufficient_evidence":
        status = "proposed"
    elif expectancy is None:
        status = "proposed"
    elif expectancy > 0:
        status = "confirmed" if metrics.get("count", 0) >= MIN_SAMPLES_FOR_CONFIRMED and quality["confidence"] >= 0.35 else "supported"
    elif expectancy < 0:
        status = "contradicted"
    else:
        status = "weakened"
    group = finding.get("group") or {}
    return {
        "claim": finding.get("claim") or "",
        "scope": group,
        "strategy_family": group.get("strategy_family"),
        "instrument_id": group.get("instrument_id"),
        "asset_family": _asset_family(group.get("instrument_id")),
        "timeframe": group.get("timeframe"),
        "regime_key": group.get("regime_key"),
        "evidence_refs": refs,
        "supporting_count": int(metrics.get("wins") or 0),
        "contradicting_count": int(metrics.get("losses") or 0),
        "confidence": quality["confidence"],
        "confidence_cap": quality["cap"],
        "status": status,
        "source_finding_id": finding.get("finding_id"),
        "evidence_quality": quality,
        "scope_key": belief_scope_key(finding),
    }


def apply_curator_output(
    payload: dict[str, Any],
    *,
    allowed_refs: set[str],
    findings: Sequence[dict[str, Any]],
    prior_beliefs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Validate Learning Curator JSON. Unsupported claims are refused, not stored."""
    if not isinstance(payload, dict):
        return {"accepted": [], "rejected": [{"reason": "output_not_an_object"}]}

    known_findings = {item.get("finding_id"): item for item in findings}
    known_beliefs = {item.get("belief_id"): item for item in prior_beliefs}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def _check_refs(refs: Any, label: str) -> list[str]:
        if not isinstance(refs, list) or not refs:
            rejected.append({"reason": "missing_evidence_refs", "item": label})
            return []
        clean: list[str] = []
        for ref in refs:
            text = str(ref)
            if text not in allowed_refs and not any(text.startswith(prefix) for prefix in ("experience:", "finding:", "experiment:", "evaluation:", "decision:", "belief:")):
                rejected.append({"reason": "unknown_evidence_ref", "ref": text, "item": label})
                continue
            if text.startswith("finding:") and text.split(":", 1)[-1] not in known_findings:
                rejected.append({"reason": "unknown_finding_ref", "ref": text, "item": label})
                continue
            if allowed_refs and text not in allowed_refs and not text.startswith(("experience:", "finding:", "experiment:", "evaluation:", "decision:", "belief:")):
                rejected.append({"reason": "evidence_ref_not_in_context", "ref": text, "item": label})
                continue
            clean.append(text)
        return clean

    for key in ("new_findings", "confirmed_beliefs", "weakened_beliefs", "contradicted_beliefs", "superseded_beliefs", "retired_beliefs"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                rejected.append({"reason": "malformed_item", "bucket": key})
                continue
            refs = _check_refs(item.get("evidence_refs") or item.get("evidence_ref") and [item.get("evidence_ref")], key)
            if not refs:
                continue
            claim = str(item.get("claim") or item.get("belief_id") or "").strip()
            if not claim:
                rejected.append({"reason": "empty_claim", "bucket": key})
                continue
            target = None
            if item.get("belief_id") and item["belief_id"] in known_beliefs:
                target = item["belief_id"]
            accepted.append(
                {
                    "bucket": key,
                    "claim": claim,
                    "evidence_refs": refs,
                    "belief_id": target,
                    "applies_to": item.get("applies_to") or item.get("scope") or {},
                    "suggested_status": _status_for_bucket(key),
                    "open_question": False,
                    "mutation": item.get("mutation"),
                }
            )

    for item in payload.get("open_questions") or []:
        if isinstance(item, str) and item.strip():
            accepted.append({"bucket": "open_questions", "claim": item.strip(), "evidence_refs": [], "open_question": True})
        elif isinstance(item, dict) and item.get("question"):
            accepted.append({"bucket": "open_questions", "claim": str(item["question"]), "evidence_refs": list(item.get("evidence_refs") or []), "open_question": True})

    for item in payload.get("suggested_next_hypotheses") or payload.get("suggested_candidate_mutations") or []:
        if not isinstance(item, dict):
            continue
        refs = _check_refs(item.get("evidence_refs") or [], "mutation")
        accepted.append(
            {
                "bucket": "candidate_suggestions",
                "claim": str(item.get("reason") or item.get("hypothesis") or item.get("mutation") or "suggestion"),
                "evidence_refs": refs,
                "mutation": item,
            }
        )

    return {"accepted": accepted, "rejected": rejected}


def _status_for_bucket(bucket: str) -> str:
    return {
        "new_findings": "proposed",
        "confirmed_beliefs": "supported",
        "weakened_beliefs": "weakened",
        "contradicted_beliefs": "contradicted",
        "superseded_beliefs": "superseded",
        "retired_beliefs": "retired",
    }.get(bucket, "proposed")


def retrieve_beliefs(
    rows: Sequence[dict[str, Any]],
    *,
    instrument_id: str | None = None,
    strategy_family: str | None = None,
    timeframe: str | None = None,
    regime_key: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Targeted retrieval. Never dump the whole belief store into a prompt."""
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        if row.get("status") == "retired":
            continue
        score = 0
        if instrument_id and row.get("instrument_id") == instrument_id:
            score += 4
        if strategy_family and row.get("strategy_family") == strategy_family:
            score += 4
        if timeframe and row.get("timeframe") == timeframe:
            score += 2
        if regime_key and row.get("regime_key") == regime_key:
            score += 3
        if row.get("status") in {"confirmed", "supported", "contradicted"}:
            score += 1
        score += int(10 * float(row.get("confidence") or 0))
        if score <= 0 and (instrument_id or strategy_family or timeframe or regime_key):
            continue
        scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("updated_at") or "")))
    compact = []
    for _, row in scored[: max(1, min(int(limit), 16))]:
        compact.append(
            {
                "belief_id": row.get("belief_id"),
                "claim": row.get("claim"),
                "status": row.get("status"),
                "confidence": row.get("confidence"),
                "regime_key": row.get("regime_key"),
                "strategy_family": row.get("strategy_family"),
                "instrument_id": row.get("instrument_id"),
                "timeframe": row.get("timeframe"),
                "supporting_count": row.get("supporting_count"),
                "contradicting_count": row.get("contradicting_count"),
                "evidence_refs": (row.get("evidence_refs") or [])[:8],
            }
        )
    return compact


def compact_findings(findings: Sequence[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    ordered = sorted(findings, key=lambda item: (-int(item.get("sample_count") or 0), str(item.get("finding_id"))))
    out = []
    for item in ordered[:limit]:
        metrics = item.get("metrics") or {}
        out.append(
            {
                "finding_id": item.get("finding_id"),
                "claim": item.get("claim"),
                "evidence_status": item.get("evidence_status"),
                "split": item.get("split"),
                "regime_key": (item.get("group") or {}).get("regime_key"),
                "strategy_family": (item.get("group") or {}).get("strategy_family"),
                "instrument_id": (item.get("group") or {}).get("instrument_id"),
                "count": metrics.get("count"),
                "expectancy": metrics.get("expectancy"),
                "win_rate": metrics.get("win_rate"),
                "losses": metrics.get("losses"),
                "evidence_refs": (item.get("evidence_refs") or [])[:6],
            }
        )
    return out


def _asset_family(instrument_id: Any) -> str | None:
    if not instrument_id:
        return None
    text = str(instrument_id)
    if ":" in text:
        return text.split(":", 1)[0]
    return None


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _downside_deviation(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    downside = [min(0.0, value) for value in values]
    return math.sqrt(sum(value * value for value in downside) / len(downside))


def _concentration(values: Sequence[float]) -> float | None:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    if total <= 0:
        return None
    return sum(positive[:3]) / total


__all__ = [
    "BELIEF_STATUSES",
    "DEVELOPMENT_CAP",
    "LEARNING_SPLITS",
    "MIN_SAMPLES_FOR_FINDING",
    "VALIDATION_SPLITS",
    "aggregate_experiences",
    "apply_curator_output",
    "compact_findings",
    "evidence_confidence",
    "finding_to_belief_proposal",
    "group_key",
    "retrieve_beliefs",
]
