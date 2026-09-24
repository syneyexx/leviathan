"""News & Event Intelligence — feeds → items with a causal ``available_at`` boundary.

Fetching is I/O and belongs to the ``provider_io`` pool (``provider.http``). Parsing is
Tier 0 (stdlib XML/JSON) and runs wherever the poll job runs. Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Protocol

from .store import OrchestraStore, new_id, utc_now
from .types import NewsFeed, NewsItem


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(raw: str | None) -> str | None:
    """RFC 2822 (RSS), ISO 8601 (Atom) or epoch seconds → UTC ISO string; None when unknown."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return _iso(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass
    try:
        cleaned = text.replace("Z", "+00:00")
        return _iso(datetime.fromisoformat(cleaned))
    except ValueError:
        pass
    if text.isdigit() and 9 <= len(text) <= 10:
        return _iso(datetime.fromtimestamp(int(text), tz=timezone.utc))
    return None


def compute_available_at(*, published_at: str | None, fetched_at: str, declared_latency_seconds: int = 0) -> str:
    """Causal boundary: the item is usable no earlier than max(published, fetched) + latency.

    For live polling ``fetched_at`` dominates (we cannot have known it before we saw it).
    For historical archives the operator supplies ``published_at``; ``fetched_at`` is then
    the archive import time and the caller passes ``fetched_at=published_at`` explicitly.
    """
    candidates = [datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))]
    if published_at:
        candidates.append(datetime.fromisoformat(published_at.replace("Z", "+00:00")))
    base = max(candidates)
    return _iso(base + timedelta(seconds=max(0, int(declared_latency_seconds))))


@dataclass(frozen=True)
class ParsedEntry:
    title: str
    url: str
    summary: str
    published_at: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed_document(body: str | bytes) -> list[ParsedEntry]:
    """Parse RSS 2.0 / Atom / minimal JSON feed into entries. Malformed → empty list, never raise."""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body or "")
    text = text.strip()
    if not text:
        return []
    if text.startswith("{"):
        return _parse_json_feed(text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    entries: list[ParsedEntry] = []
    for node in root.iter():
        name = _local(node.tag)
        if name not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        summary = ""
        published = None
        for child in list(node):
            cname = _local(child.tag)
            value = (child.text or "").strip()
            if cname == "title":
                title = _strip_html(value)
            elif cname == "link":
                link = value or str(child.attrib.get("href") or "").strip()
            elif cname in {"description", "summary", "content", "encoded"} and not summary:
                summary = _strip_html(value)
            elif cname in {"pubdate", "published", "updated", "date"} and published is None:
                published = parse_timestamp(value)
        if not title and not link:
            continue
        entries.append(ParsedEntry(title=title[:500], url=link[:2048], summary=summary[:2000], published_at=published))
    return entries


def _parse_json_feed(text: str) -> list[ParsedEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    entries: list[ParsedEntry] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        title = _strip_html(str(raw.get("title") or ""))
        url = str(raw.get("url") or raw.get("link") or "").strip()
        summary = _strip_html(str(raw.get("summary") or raw.get("content_text") or raw.get("description") or ""))
        published = parse_timestamp(str(raw.get("date_published") or raw.get("published_at") or raw.get("pubDate") or ""))
        if not title and not url:
            continue
        entries.append(ParsedEntry(title=title[:500], url=url[:2048], summary=summary[:2000], published_at=published))
    return entries


def entries_to_items(
    feed: NewsFeed,
    entries: list[ParsedEntry],
    *,
    fetched_at: str | None = None,
) -> list[NewsItem]:
    fetched = fetched_at or utc_now()
    items: list[NewsItem] = []
    for entry in entries:
        digest = hashlib.sha256(f"{feed.feed_id}|{entry.url}|{entry.title}".encode("utf-8")).hexdigest()
        items.append(
            NewsItem(
                item_id=new_id("news"),
                feed_id=feed.feed_id,
                source=feed.name,
                url=entry.url,
                title=entry.title,
                summary=entry.summary,
                content_hash=digest,
                published_at=entry.published_at,
                fetched_at=fetched,
                available_at=compute_available_at(
                    published_at=entry.published_at,
                    fetched_at=fetched,
                    declared_latency_seconds=feed.declared_latency_seconds,
                ),
                license_state=feed.license_state,
                symbols_hint=list(feed.symbols_hint),
            )
        )
    return items


class FeedFetcher(Protocol):
    def __call__(self, url: str) -> str | bytes: ...


class ProviderIoFeedFetcher:
    """Fetch a feed body through the provider_io pool (``provider.http``); never raw urllib."""

    def __init__(self, job_runtime: Any, *, deadline_seconds: float = 30.0, max_bytes: int = 2_000_000) -> None:
        self.job_runtime = job_runtime
        self.deadline_seconds = deadline_seconds
        self.max_bytes = max_bytes

    def __call__(self, url: str) -> str:
        from Data.modules.provider_io.facade import get_provider_client

        client = get_provider_client(self.job_runtime)
        result = client.submit_and_wait(
            provider="news_feed",
            capability="http",
            payload={"url": url, "method": "GET", "max_bytes": self.max_bytes},
            deadline_seconds=self.deadline_seconds,
            latency_class="background",
            requested_by="market_sim.news.poll",
            metadata={"domain": "market_sim", "kind": "news_feed"},
        )
        status = str(getattr(result, "status", "") or "").lower()
        if status != "succeeded":
            err = getattr(result, "error", None) or {}
            raise RuntimeError(f"provider.http {status or 'failed'}: {err.get('message') if isinstance(err, dict) else err}")
        content = getattr(result, "content", None)
        if content:
            return str(content)
        structured = getattr(result, "structured", None)
        return json.dumps(structured) if structured else ""


class NewsPoller:
    def __init__(self, store: OrchestraStore, fetcher: FeedFetcher | None) -> None:
        self.store = store
        self.fetcher = fetcher

    def poll_feed(self, feed: NewsFeed, *, fetched_at: str | None = None) -> dict[str, Any]:
        now = fetched_at or utc_now()
        if self.fetcher is None:
            feed.last_polled_at = now
            feed.last_status = "UNAVAILABLE"
            feed.last_error = "no feed fetcher bound (provider_io workers unavailable)"
            feed.updated_at = now
            self.store.upsert_feed(feed)
            return {"feedId": feed.feed_id, "status": "UNAVAILABLE", "inserted": 0, "error": feed.last_error}
        try:
            body = self.fetcher(feed.url)
        except Exception as exc:  # noqa: BLE001 — truthful per-feed failure
            feed.last_polled_at = now
            feed.last_status = "FAILED"
            feed.last_error = str(exc)[:500]
            feed.updated_at = now
            self.store.upsert_feed(feed)
            return {"feedId": feed.feed_id, "status": "FAILED", "inserted": 0, "error": feed.last_error}
        entries = parse_feed_document(body)
        items = entries_to_items(feed, entries, fetched_at=now)
        inserted = self.store.insert_items(items)
        feed.last_polled_at = now
        feed.last_status = "OK" if entries else "EMPTY"
        feed.last_error = None
        feed.updated_at = now
        self.store.upsert_feed(feed)
        return {
            "feedId": feed.feed_id,
            "status": feed.last_status,
            "parsed": len(entries),
            "inserted": len(inserted),
            "itemIds": [i.item_id for i in inserted],
        }

    def poll_all(self, *, fetched_at: str | None = None) -> list[dict[str, Any]]:
        return [self.poll_feed(feed, fetched_at=fetched_at) for feed in self.store.list_feeds(enabled_only=True)]


def make_fetcher(job_runtime: Any | None, *, allow_inline: bool = False, inline: Callable[[str], str] | None = None) -> FeedFetcher | None:
    """Production: provider_io only. Tests may inject ``inline``. No Control-Plane HTTP fallback."""
    if inline is not None and allow_inline:
        return inline
    if job_runtime is None:
        return None
    return ProviderIoFeedFetcher(job_runtime)
