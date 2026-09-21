from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "from", "at", "by", "as", "is", "are", "was", "were",
    "de", "het", "een", "en", "of", "van", "voor", "met", "op", "in", "bij", "als", "is", "zijn", "wordt",
    "der", "die", "das", "und", "oder", "von", "zu", "mit", "im", "in", "auf", "ist", "sind",
    "le", "la", "les", "un", "une", "et", "ou", "de", "des", "du", "dans", "sur", "pour", "avec", "est", "sont",
    "el", "la", "los", "las", "un", "una", "y", "o", "de", "del", "en", "para", "con", "es", "son",
    "il", "lo", "la", "i", "gli", "le", "un", "una", "e", "o", "di", "del", "in", "per", "con", "è", "sono",
}


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w\-]{3,}", (text or "").casefold(), flags=re.UNICODE)
    return {token.strip("-_") for token in raw if token not in _STOPWORDS and not token.isdigit() and len(token.strip("-_")) >= 3}


def _article_key(article: Any) -> str:
    return (getattr(article, "canonical_url", "") or getattr(article, "url", "") or "").strip().casefold()


def evidence_quality(article: Any) -> float:
    status = getattr(article, "crawl_status", "")
    text_len = len(getattr(article, "article_text", "") or "")
    snippet_len = len(getattr(article, "snippet", "") or "")
    if status == "ok":
        return round(min(1.0, 0.62 + min(text_len, 6000) / 16000), 3)
    if status == "limited_access":
        return round(min(0.52, 0.30 + min(snippet_len, 1500) / 8000), 3)
    if snippet_len:
        return round(min(0.42, 0.22 + min(snippet_len, 1500) / 7500), 3)
    return 0.12


def deduplicate_articles(articles: list[Any]) -> list[Any]:
    by_key: dict[str, Any] = {}
    for article in articles:
        key = _article_key(article) or getattr(article, "id", "")
        if key not in by_key:
            by_key[key] = article
            continue
        current = by_key[key]
        cur_score = evidence_quality(current)
        new_score = evidence_quality(article)
        keeper, other = (article, current) if new_score > cur_score else (current, article)
        keeper.duplicate_count = int(getattr(keeper, "duplicate_count", 0) or 0) + int(getattr(other, "duplicate_count", 0) or 0) + 1
        provenance = list(getattr(keeper, "provenance_urls", []) or [])
        for value in [getattr(other, "url", ""), getattr(other, "feed_url", ""), *list(getattr(other, "provenance_urls", []) or [])]:
            if value and value not in provenance:
                provenance.append(value)
        keeper.provenance_urls = provenance[:20]
        by_key[key] = keeper
    return list(by_key.values())


@dataclass
class StoryCluster:
    story_id: str
    representative_title: str
    article_ids: list[str]
    publishers: list[str]
    countries: list[str]
    regions: list[str]
    source_count: int
    direct_source_count: int
    evidence_quality: float
    corroboration_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_story_clusters(articles: list[Any]) -> list[StoryCluster]:
    if not articles:
        return []
    token_sets = [_tokens(getattr(a, "title", "")) for a in articles]
    inverted: dict[str, list[int]] = defaultdict(list)
    parent = list(range(len(articles)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, tokens in enumerate(token_sets):
        counts: Counter[int] = Counter()
        for token in tokens:
            for j in inverted[token]:
                counts[j] += 1
        for j, shared in counts.items():
            a, b = tokens, token_sets[j]
            if not a or not b:
                continue
            union_size = len(a | b)
            jaccard = shared / union_size if union_size else 0.0
            containment = shared / max(1, min(len(a), len(b)))
            if shared >= 3 and (jaccard >= 0.42 or containment >= 0.68):
                union(i, j)
        for token in tokens:
            inverted[token].append(i)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(articles)):
        groups[find(i)].append(i)

    clusters: list[StoryCluster] = []
    for indices in groups.values():
        members = [articles[i] for i in indices]
        publishers = sorted({(getattr(a, "publisher", "") or "unknown").strip() for a in members})
        countries = sorted({(getattr(a, "country_code", "") or "unknown").strip() for a in members})
        regions = sorted({(getattr(a, "region", "") or "unknown").strip() for a in members})
        direct = sum(getattr(a, "source_kind", "") == "direct" for a in members)
        avg_quality = sum(evidence_quality(a) for a in members) / len(members)
        source_bonus = min(0.30, math.log2(max(1, len(publishers))) * 0.10)
        country_bonus = min(0.12, max(0, len(countries) - 1) * 0.04)
        direct_bonus = min(0.08, direct * 0.02)
        corroboration = round(min(1.0, 0.28 + source_bonus + country_bonus + direct_bonus + avg_quality * 0.25), 3)
        title = max((getattr(a, "title", "") or "" for a in members), key=len, default="")
        seed = "\x1f".join(sorted(getattr(a, "id", "") for a in members))
        story_id = hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest()[:20]
        cluster = StoryCluster(
            story_id=story_id,
            representative_title=title,
            article_ids=[getattr(a, "id", "") for a in members],
            publishers=publishers,
            countries=countries,
            regions=regions,
            source_count=len(publishers),
            direct_source_count=direct,
            evidence_quality=round(avg_quality, 3),
            corroboration_score=corroboration,
        )
        clusters.append(cluster)
        for article in members:
            article.story_id = story_id
            article.story_cluster_size = len(members)
            article.corroborating_publishers = len(publishers)
            article.corroborating_countries = len(countries)
            article.evidence_quality = round(evidence_quality(article), 3)
            article.corroboration_score = corroboration
    clusters.sort(key=lambda c: (c.source_count, c.corroboration_score, len(c.article_ids)), reverse=True)
    return clusters
