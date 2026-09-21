
"""Research claims with provenance — no fabricated sources."""

from __future__ import annotations

from typing import Any, Callable, Awaitable


class ResearchEngine:
    def __init__(self, store: Any, *, retrieve: Callable[..., Any] | None = None) -> None:
        self.store = store
        self.retrieve = retrieve

    async def research_topic(self, *, project_id: str, topic: str, channel: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        evidence_items: list[dict[str, Any]] = []
        if self.retrieve is not None:
            try:
                result = self.retrieve(topic)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[misc]
                evidence_items = list((result or {}).get("items") or (result if isinstance(result, list) else []))
            except Exception:
                evidence_items = []

        if not evidence_items:
            # Honest weak claim — not a fabricated citation.
            claims.append(
                self.store.save_research_claim(
                    {
                        "project_id": project_id,
                        "claim": f"Public evidence for '{topic}' was not retrieved in this run; keep claims cautious.",
                        "evidence": "No retrieval hits / research bridge unavailable.",
                        "source_ref": "",
                        "confidence": 0.2,
                        "contradictions": [],
                    }
                )
            )
            return claims

        for item in evidence_items[:8]:
            text = str(item.get("text") or item.get("snippet") or item.get("claim") or "").strip()
            source = str(item.get("source") or item.get("url") or item.get("source_ref") or "").strip()
            if not text or not source:
                continue
            claims.append(
                self.store.save_research_claim(
                    {
                        "project_id": project_id,
                        "claim": text[:500],
                        "evidence": str(item.get("evidence") or text)[:1000],
                        "source_ref": source[:1000],
                        "confidence": float(item.get("confidence") or 0.55),
                        "contradictions": item.get("contradictions") or [],
                    }
                )
            )
        if not claims:
            claims.append(
                self.store.save_research_claim(
                    {
                        "project_id": project_id,
                        "claim": f"Retrieval returned items for '{topic}' without usable provenance; discarded unverifiable claims.",
                        "evidence": "Items lacked source_ref.",
                        "source_ref": "",
                        "confidence": 0.15,
                        "contradictions": [],
                    }
                )
            )
        return claims
