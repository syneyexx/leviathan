
"""Trend provider interface and built-in compliant providers."""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def topic_key(topic: str) -> str:
    normalized = re.sub(r"\s+", " ", (topic or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9 #_-]+", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


class TrendProvider(ABC):
    id: str = "base"

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def discover(self, *, query: str = "", region: str = "", language: str = "", limit: int = 20) -> dict[str, Any]:
        raise NotImplementedError

    async def enrich(self, signal: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "signal": signal}


class StaticSeedTrendProvider(TrendProvider):
    """Deterministic local provider for offline operation / tests.

    Never claims live platform trending. Marks evidence as local/seed.
    """

    id = "local_seed"

    def __init__(self, seeds: list[dict[str, Any]] | None = None) -> None:
        self.seeds = seeds or []

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "READY", "provider": self.id}

    async def discover(self, *, query: str = "", region: str = "", language: str = "", limit: int = 20) -> dict[str, Any]:
        now = utc_now()
        q = (query or "").strip().lower()
        signals = []
        for seed in self.seeds:
            topic = str(seed.get("topic") or "")
            if q and q not in topic.lower() and q not in str(seed.get("keyword") or "").lower():
                continue
            signals.append(
                {
                    "provider": self.id,
                    "platform": seed.get("platform", ""),
                    "topic": topic,
                    "keyword": seed.get("keyword", topic),
                    "region": region or seed.get("region", ""),
                    "language": language or seed.get("language", "en"),
                    "observed_at": now,
                    "rank": seed.get("rank"),
                    "views": seed.get("views"),
                    "velocity": seed.get("velocity"),
                    "engagement": seed.get("engagement"),
                    "growth": seed.get("growth"),
                    "freshness": seed.get("freshness"),
                    "competition": seed.get("competition"),
                    "saturation": seed.get("saturation"),
                    "source_ref": seed.get("source_ref", "local_seed"),
                    "confidence": seed.get("confidence", 0.4),
                    "raw": {"note": "local_seed_not_live_platform_trend"},
                }
            )
            if len(signals) >= max(1, min(int(limit), 50)):
                break
        return {"ok": True, "status": "READY", "signals": signals}


class HistoricalPerformanceTrendProvider(TrendProvider):
    id = "media_history"

    def __init__(self, store: Any) -> None:
        self.store = store

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "READY", "provider": self.id}

    async def discover(self, *, query: str = "", region: str = "", language: str = "", limit: int = 20) -> dict[str, Any]:
        findings = self.store.list_learning_findings(limit=limit)
        now = utc_now()
        signals = []
        for finding in findings:
            topic = str(finding.get("finding") or "")[:160]
            if query and query.lower() not in topic.lower():
                continue
            signals.append(
                {
                    "provider": self.id,
                    "platform": finding.get("platform", ""),
                    "topic": topic or "historical_signal",
                    "keyword": topic,
                    "region": region,
                    "language": language,
                    "observed_at": now,
                    "rank": None,
                    "views": None,
                    "velocity": finding.get("effect_size"),
                    "engagement": None,
                    "growth": finding.get("effect_size"),
                    "freshness": 0.3,
                    "competition": None,
                    "saturation": None,
                    "source_ref": finding.get("id", ""),
                    "confidence": 0.35 if (finding.get("sample_size") or 0) < 20 else 0.55,
                    "raw": {"finding_id": finding.get("id"), "sample_size": finding.get("sample_size")},
                }
            )
        return {"ok": True, "status": "READY", "signals": signals}


class WebResearchTrendProvider(TrendProvider):
    """Optional bridge to HADES web research — never scrapes platforms privately."""

    id = "hades_web_research"

    def __init__(self, research_callable: Any | None = None) -> None:
        self.research_callable = research_callable

    async def health(self) -> dict[str, Any]:
        if self.research_callable is None:
            return {"ok": False, "status": "UNAVAILABLE", "provider": self.id, "detail": "research_bridge_not_bound"}
        return {"ok": True, "status": "READY", "provider": self.id}

    async def discover(self, *, query: str = "", region: str = "", language: str = "", limit: int = 20) -> dict[str, Any]:
        if self.research_callable is None:
            return {"ok": False, "status": "UNAVAILABLE", "signals": [], "detail": "research_bridge_not_bound"}
        if not query.strip():
            return {"ok": True, "status": "READY", "signals": [], "detail": "query_required"}
        try:
            result = await self.research_callable(query=query, limit=limit)
        except Exception as exc:
            return {"ok": False, "status": "FAILED", "signals": [], "error": str(exc)[:400]}
        now = utc_now()
        signals = []
        for item in (result or {}).get("items") or []:
            topic = str(item.get("title") or item.get("topic") or query)[:200]
            signals.append(
                {
                    "provider": self.id,
                    "platform": "web",
                    "topic": topic,
                    "keyword": query,
                    "region": region,
                    "language": language,
                    "observed_at": now,
                    "rank": None,
                    "views": None,
                    "velocity": None,
                    "engagement": None,
                    "growth": None,
                    "freshness": item.get("freshness"),
                    "competition": None,
                    "saturation": None,
                    "source_ref": item.get("url") or item.get("source_ref") or "",
                    "confidence": item.get("confidence", 0.45),
                    "raw": item,
                }
            )
        return {"ok": True, "status": "PARTIAL" if signals else "READY", "signals": signals}
