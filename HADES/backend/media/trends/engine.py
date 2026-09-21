
"""Cross-platform trend graph + opportunity scoring."""

from __future__ import annotations

from typing import Any

from media.trends.providers import TrendProvider, topic_key, utc_now


def score_opportunity(
    *,
    trend: dict[str, Any],
    channel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scores = dict(trend.get("scores") or {})
    evidence = list(trend.get("evidence") or [])
    platforms = {str(e.get("platform") or "") for e in evidence if e.get("platform")}
    cross = min(30.0, 8.0 * max(0, len(platforms)))
    velocity = float(scores.get("velocity") or _avg_field(evidence, "velocity") or 0)
    freshness = float(scores.get("freshness") or _avg_field(evidence, "freshness") or 0)
    competition = float(scores.get("competition") if scores.get("competition") is not None else _avg_field(evidence, "competition") or 50)
    novelty = max(0.0, 100.0 - competition * 0.5)
    evidence_quality = min(25.0, 5.0 * len(evidence) + sum(1 for e in evidence if e.get("confidence")))

    audience_fit = 50.0
    if channel:
        niche = str(channel.get("niche") or "").lower()
        preferred = [str(t).lower() for t in channel.get("preferred_topics") or []]
        topic = str(trend.get("display_topic") or "").lower()
        if niche and niche in topic:
            audience_fit += 20
        if any(p and p in topic for p in preferred):
            audience_fit += 15
        excluded = [str(t).lower() for t in channel.get("excluded_topics") or []]
        if any(x and x in topic for x in excluded):
            audience_fit = 5

    velocity_n = _clamp(velocity if velocity <= 100 else velocity / 10.0)
    freshness_n = _clamp(freshness if freshness <= 100 else freshness)
    components = {
        "trend_velocity": round(velocity_n, 2),
        "freshness": round(freshness_n, 2),
        "cross_source_confirmation": round(cross, 2),
        "audience_fit": round(_clamp(audience_fit), 2),
        "novelty": round(_clamp(novelty), 2),
        "competition_penalty": round(_clamp(competition), 2),
        "evidence_quality": round(_clamp(evidence_quality * 4), 2),
        "visual_potential": 55.0,
        "hook_potential": 60.0,
        "production_cost": 40.0,
    }
    # Weighted explainable score /100 — not a virality probability.
    total = (
        0.18 * components["trend_velocity"]
        + 0.12 * components["freshness"]
        + 0.15 * components["cross_source_confirmation"]
        + 0.18 * components["audience_fit"]
        + 0.10 * components["novelty"]
        + 0.10 * components["evidence_quality"]
        + 0.07 * components["visual_potential"]
        + 0.07 * components["hook_potential"]
        + 0.03 * (100 - components["production_cost"])
        - 0.08 * components["competition_penalty"]
    )
    score = int(round(_clamp(total)))
    explanation = (
        f"Opportunity {score}/100 from {len(evidence)} evidence item(s) across "
        f"{len(platforms) or 1} source platform(s). Not a virality guarantee."
    )
    return {"score": score, "components": components, "explanation": explanation}


def _avg_field(evidence: list[dict[str, Any]], field: str) -> float | None:
    vals = [float(e[field]) for e in evidence if e.get(field) is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


class TrendEngine:
    def __init__(self, store: Any, providers: list[TrendProvider] | None = None) -> None:
        self.store = store
        self.providers = list(providers or [])

    async def discover(self, *, query: str = "", region: str = "", language: str = "", limit: int = 20) -> dict[str, Any]:
        all_signals: list[dict[str, Any]] = []
        provider_results: list[dict[str, Any]] = []
        for provider in self.providers:
            try:
                health = await provider.health()
                if not health.get("ok"):
                    provider_results.append({"provider": provider.id, "status": health.get("status", "UNAVAILABLE"), "health": health})
                    continue
                result = await provider.discover(query=query, region=region, language=language, limit=limit)
                provider_results.append({"provider": provider.id, "status": result.get("status", "READY"), "count": len(result.get("signals") or [])})
                for signal in result.get("signals") or []:
                    saved = self.store.insert_trend_signal(signal)
                    all_signals.append(saved)
            except Exception as exc:
                provider_results.append({"provider": provider.id, "status": "FAILED", "error": str(exc)[:300]})

        merged = self._merge_signals(all_signals)
        trends = []
        for item in merged:
            trend = self.store.upsert_trend(item["topic_key"], item["display_topic"], item["evidence"], item["scores"])
            trends.append(trend)
        return {
            "ok": True,
            "observed_at": utc_now(),
            "providers": provider_results,
            "signals": all_signals,
            "trends": trends,
        }

    def _merge_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for signal in signals:
            key = topic_key(str(signal.get("topic") or signal.get("keyword") or ""))
            bucket = buckets.setdefault(
                key,
                {
                    "topic_key": key,
                    "display_topic": signal.get("topic") or signal.get("keyword") or "unknown",
                    "evidence": [],
                    "scores": {},
                },
            )
            bucket["evidence"].append(
                {
                    "provider": signal.get("provider"),
                    "platform": signal.get("platform"),
                    "observed_at": signal.get("observed_at"),
                    "velocity": signal.get("velocity"),
                    "freshness": signal.get("freshness"),
                    "competition": signal.get("competition"),
                    "confidence": signal.get("confidence"),
                    "source_ref": signal.get("source_ref"),
                    "signal_id": signal.get("id"),
                }
            )
            # Unsupported fields stay absent — never coerced to zero in scores.
            for field in ("velocity", "freshness", "competition", "engagement", "growth"):
                if signal.get(field) is None:
                    continue
                scores = bucket["scores"]
                prev = scores.get(field)
                scores[field] = signal[field] if prev is None else max(float(prev), float(signal[field]))
        return list(buckets.values())

    def create_opportunity_for_trend(self, trend: dict[str, Any], channel: dict[str, Any] | None = None) -> dict[str, Any]:
        scored = score_opportunity(trend=trend, channel=channel)
        return self.store.create_opportunity(
            {
                "channel_id": (channel or {}).get("id"),
                "trend_id": trend.get("id"),
                "score": scored["score"],
                "components": scored["components"],
                "explanation": scored["explanation"],
                "status": "open",
            }
        )
