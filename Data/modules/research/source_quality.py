"""Contextual source quality assessment — not simplistic TLD heuristics."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .types import ResearchSource, SourceType


@dataclass
class SourceAssessment:
    source_id: str
    source_type: str
    primary_or_secondary: str
    authority: float
    expertise: float
    relevance: float
    freshness: float
    independence: float
    methodological_strength: float
    directness: float
    citation_quality: float
    bias_risk: float
    accessibility: float
    source_class: str
    independence_cluster: str | None = None
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "primary_or_secondary": self.primary_or_secondary,
            "authority": self.authority,
            "expertise": self.expertise,
            "relevance": self.relevance,
            "freshness": self.freshness,
            "independence": self.independence,
            "methodological_strength": self.methodological_strength,
            "directness": self.directness,
            "citation_quality": self.citation_quality,
            "bias_risk": self.bias_risk,
            "accessibility": self.accessibility,
            "source_class": self.source_class,
            "independence_cluster": self.independence_cluster,
            "notes": list(self.notes),
            "overall_weight": self.overall_weight(),
            "truth": {
                "weight_is_not_truth_probability": True,
                "contextual_assessment_only": True,
            },
        }

    def overall_weight(self) -> float:
        """Contextual composite for retrieval ranking — not a truth probability."""
        positives = (
            0.18 * self.authority
            + 0.14 * self.expertise
            + 0.18 * self.relevance
            + 0.10 * self.freshness
            + 0.12 * self.independence
            + 0.10 * self.methodological_strength
            + 0.10 * self.directness
            + 0.08 * self.citation_quality
        )
        # Bias risk and poor accessibility penalize.
        penalty = 0.35 * self.bias_risk + 0.15 * (1.0 - self.accessibility)
        return max(0.0, min(1.0, positives * (1.0 - 0.4 * penalty) + 0.05 * self.accessibility))


_MARKETING_HINTS = re.compile(
    r"\b(buy now|sign up|pricing|our product|we offer|contact sales|free trial)\b",
    re.I,
)
_FORUM_HOSTS = frozenset(
    {
        "reddit.com",
        "www.reddit.com",
        "news.ycombinator.com",
        "stackoverflow.com",
        "stackexchange.com",
        "quora.com",
        "www.quora.com",
    }
)
_SOCIAL_HOSTS = frozenset(
    {
        "twitter.com",
        "x.com",
        "facebook.com",
        "www.facebook.com",
        "linkedin.com",
        "www.linkedin.com",
        "medium.com",
    }
)
_SYNDICATE_HINTS = ("syndication", "wire-service", "reprinted", "via reuters", "via ap ")


def _host(uri: str | None) -> str | None:
    if not uri:
        return None
    try:
        host = urlparse(uri).hostname
    except Exception:
        return None
    if not host:
        if uri.startswith("knowledge://"):
            return "local.knowledge"
        if uri.startswith("seed://"):
            return "local.seed"
        return None
    return host.lower().removeprefix("www.")


def _org_cluster_host(host: str | None) -> str | None:
    if not host:
        return None
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "gov", "ac", "org"}:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _classify_source(source: ResearchSource, host: str | None, title: str, uri: str) -> tuple[str, str, list[str]]:
    """Return (source_class, primary_or_secondary, notes)."""
    notes: list[str] = []
    st = source.source_type.value if isinstance(source.source_type, SourceType) else str(source.source_type)
    meta = source.metadata if isinstance(source.metadata, dict) else {}
    explicit = meta.get("source_class")
    if explicit:
        por = str(meta.get("primary_or_secondary") or "unknown")
        return str(explicit), por, notes

    lower_uri = (uri or "").lower()
    lower_title = (title or "").lower()

    if st == SourceType.KNOWLEDGE.value:
        return "technical_docs", "secondary", ["local knowledge chunk"]
    if st == SourceType.SEED.value:
        return "seed", "unknown", ["operator-provided seed"]

    if host in _FORUM_HOSTS or any(h in (host or "") for h in ("stackexchange", "reddit")):
        return "forum", "secondary", ["community discussion venue"]
    if host in _SOCIAL_HOSTS:
        return "social", "secondary", ["social / short-form platform"]

    if host and (
        host.endswith(".gov")
        or host.endswith(".gov.uk")
        or ".gov." in host
        or host.endswith(".mil")
    ):
        notes.append("government / official domain — still needs topical relevance")
        return "official_primary", "primary", notes

    if host and (
        host.endswith(".edu")
        or "arxiv.org" in host
        or "pubmed" in host
        or "doi.org" in lower_uri
        or "scholar" in host
    ):
        notes.append("academic / scholarly venue signal")
        return "peer_reviewed", "primary", notes

    if any(tok in lower_uri for tok in ("/docs/", "/documentation", "readthedocs", "developer.", "/api/")):
        return "technical_docs", "primary", ["technical documentation path"]

    if _MARKETING_HINTS.search(lower_title) or _MARKETING_HINTS.search(lower_uri):
        return "marketing", "secondary", ["marketing language detected"]

    if host and any(tok in host for tok in ("blog", "substack", "wordpress", "medium")):
        return "blog", "secondary", []

    if "anonymous" in lower_title or meta.get("anonymous"):
        return "anonymous", "unknown", ["anonymous authorship"]

    if st in {SourceType.WEB_PAGE.value, SourceType.WEB_SEARCH.value}:
        return "journalism", "secondary", ["default web classification pending richer metadata"]

    return "unknown", "unknown", notes


def assess_source(
    source: ResearchSource,
    *,
    topic_tokens: list[str] | None = None,
    retrieved_at: str | None = None,
) -> SourceAssessment:
    uri = source.canonical_uri or source.original_uri or ""
    host = _host(uri)
    title = source.title or ""
    source_type = (
        source.source_type.value if isinstance(source.source_type, SourceType) else str(source.source_type)
    )
    source_class, primary_or_secondary, notes = _classify_source(source, host, title, uri)

    # Authority / expertise are contextual — .gov is not automatically "true".
    authority = 0.45
    expertise = 0.4
    methodological_strength = 0.35
    citation_quality = 0.35
    bias_risk = 0.35
    independence = 0.55
    directness = 0.5 if primary_or_secondary == "primary" else 0.35
    accessibility = 0.7

    if source_class == "official_primary":
        authority = 0.75
        expertise = 0.65
        methodological_strength = 0.55
        bias_risk = 0.4  # official sources can still be incomplete or agenda-driven
        notes.append("official venue raises authority, not correctness")
    elif source_class == "peer_reviewed":
        authority = 0.8
        expertise = 0.85
        methodological_strength = 0.8
        citation_quality = 0.75
        bias_risk = 0.3
    elif source_class == "technical_docs":
        authority = 0.65
        expertise = 0.7
        methodological_strength = 0.6
        directness = 0.7
        bias_risk = 0.35
    elif source_class == "journalism":
        authority = 0.5
        expertise = 0.45
        methodological_strength = 0.4
        citation_quality = 0.45
        bias_risk = 0.45
    elif source_class == "marketing":
        authority = 0.25
        expertise = 0.3
        bias_risk = 0.85
        independence = 0.2
        notes.append("marketing incentives elevate bias risk")
    elif source_class == "blog":
        authority = 0.3
        expertise = 0.35
        bias_risk = 0.55
        methodological_strength = 0.25
    elif source_class == "forum":
        authority = 0.2
        expertise = 0.3
        bias_risk = 0.5
        methodological_strength = 0.2
        citation_quality = 0.2
    elif source_class == "social":
        authority = 0.15
        expertise = 0.2
        bias_risk = 0.65
        methodological_strength = 0.1
    elif source_class == "anonymous":
        authority = 0.1
        expertise = 0.15
        bias_risk = 0.7
        independence = 0.4
    elif source_class == "seed":
        authority = 0.4
        expertise = 0.4
        notes.append("seed material depends on operator provenance")

    # Relevance from topic token overlap with title + uri.
    tokens = [t.lower() for t in (topic_tokens or []) if len(t) > 2]
    hay = f"{title} {uri}".lower()
    if tokens:
        hits = sum(1 for t in tokens if t in hay)
        relevance = _clamp(hits / max(3.0, float(len(tokens))) * 2.0)
        if relevance < 0.15:
            notes.append("low topical overlap with query tokens")
    else:
        relevance = 0.5

    # Freshness from published_at / fetched_at relative to retrieved_at.
    ref = _parse_dt(retrieved_at) or datetime.now(timezone.utc)
    published = _parse_dt(source.published_at) or _parse_dt(source.fetched_at)
    if published is None:
        freshness = 0.45
        notes.append("no reliable publication date")
    else:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (ref - published).total_seconds() / 86400.0)
        if age_days <= 30:
            freshness = 0.95
        elif age_days <= 180:
            freshness = 0.75
        elif age_days <= 730:
            freshness = 0.5
        else:
            freshness = 0.25
            notes.append("source may be outdated relative to retrieval time")

    if source.snapshot_path:
        accessibility = 0.9
    elif source_type == SourceType.WEB_SEARCH.value:
        accessibility = 0.4
        notes.append("search hit may lack body snapshot")

    meta = source.metadata if isinstance(source.metadata, dict) else {}
    if meta.get("paywalled"):
        accessibility = min(accessibility, 0.3)
        notes.append("paywalled or restricted access")

    return SourceAssessment(
        source_id=source.source_id,
        source_type=source_type,
        primary_or_secondary=primary_or_secondary,
        authority=_clamp(authority),
        expertise=_clamp(expertise),
        relevance=_clamp(relevance),
        freshness=_clamp(freshness),
        independence=_clamp(independence),
        methodological_strength=_clamp(methodological_strength),
        directness=_clamp(directness),
        citation_quality=_clamp(citation_quality),
        bias_risk=_clamp(bias_risk),
        accessibility=_clamp(accessibility),
        source_class=source_class,
        independence_cluster=None,
        notes=notes,
    )


def cluster_dependent_sources(sources: list[ResearchSource]) -> dict[str, str]:
    """Map source_id → cluster_id for dependent / syndicated copies."""
    clusters: dict[str, str] = {}
    hash_to_cluster: dict[str, str] = {}
    host_to_cluster: dict[str, str] = {}
    wire_to_cluster: dict[str, str] = {}

    for src in sources:
        uri = src.canonical_uri or src.original_uri or ""
        host = _org_cluster_host(_host(uri))
        content_hash = (src.content_hash or "").strip().lower()
        title = (src.title or "").strip().lower()
        meta = src.metadata if isinstance(src.metadata, dict) else {}
        syndicated = any(
            hint in f"{title} {uri} {meta}".lower() for hint in _SYNDICATE_HINTS
        )

        cluster_id: str | None = None
        if content_hash and content_hash in hash_to_cluster:
            cluster_id = hash_to_cluster[content_hash]
        elif syndicated:
            wire_key = title or host or src.source_id
            if wire_key in wire_to_cluster:
                cluster_id = wire_to_cluster[wire_key]
            else:
                cluster_id = "wire:" + hashlib.sha1(wire_key.encode("utf-8")).hexdigest()[:10]
                wire_to_cluster[wire_key] = cluster_id
        elif host and host in host_to_cluster:
            # Same org host → same independence cluster.
            cluster_id = host_to_cluster[host]

        if cluster_id is None:
            if host:
                cluster_id = f"org:{host}"
            elif content_hash:
                cluster_id = f"hash:{content_hash[:12]}"
            else:
                cluster_id = f"solo:{src.source_id}"

        clusters[src.source_id] = cluster_id
        if host:
            host_to_cluster.setdefault(host, cluster_id)
        if content_hash:
            hash_to_cluster.setdefault(content_hash, cluster_id)

    return clusters


def independent_support_count(
    claim_support_source_ids: list[str],
    clusters: dict[str, str],
) -> int:
    """Count unique independence clusters among supporting source ids."""
    seen: set[str] = set()
    for sid in claim_support_source_ids:
        cluster = clusters.get(sid) or f"solo:{sid}"
        seen.add(cluster)
    return len(seen)
