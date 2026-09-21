"""Priority BFS multi-hop crawler (discover only — never full PDF download)."""

from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .browser import BrowserEscalator
from .cancel import CancelToken
from .html_extract import extract_scored_links
from .http_client import USER_AGENT, HttpClient
from .index import ResourceIndex
from .models import (
    CrawlConfig,
    CrawlNode,
    CrawlStats,
    DownloadStatus,
    ErrorClass,
    NodeState,
    ResourceRecord,
    ResourceStatus,
    new_resource_id,
    new_session_id,
    utc_now_iso,
)
from .pdf_detect import is_likely_pdf_candidate_url
from .rate_limit import HostRateLimiter
from .robots import RobotsCache
from .scoring import classify_barrier
from .storage import StoragePaths, atomic_write_json
from .urls import hostname_of, join_click_path, normalize_url, same_registrable_host, safe_normalize


@dataclass(order=True)
class QueueItem:
    priority: float
    seq: int
    node: CrawlNode = field(compare=False)


class CrawlerEngine:
    def __init__(
        self,
        config: CrawlConfig,
        *,
        index: ResourceIndex | None = None,
        paths: StoragePaths | None = None,
        cancel: CancelToken | None = None,
    ) -> None:
        self.config = config
        self.paths = (paths or StoragePaths(config.data_dir)).ensure()
        self.index = index or ResourceIndex(self.paths)
        self.cancel = cancel or CancelToken(self.paths.cancel_flag)
        self.stats = CrawlStats(session_id=new_session_id(), started_at=utc_now_iso())
        self._seq = 0
        self._queue: list[QueueItem] = []
        self._queued: set[str] = set()
        self._visited: set[str] = set()
        self._seed_hosts: set[str] = set()
        self._nodes: dict[str, CrawlNode] = {}
        self._queue_lock: asyncio.Lock | None = None

    def _push(self, node: CrawlNode) -> bool:
        url = node.normalized_url
        if url in self._queued or url in self._visited:
            self.stats.duplicate_urls += 1
            return False
        if len(self._visited) + len(self._queued) >= self.config.max_pages and url not in self._queued:
            return False
        self._queued.add(url)
        self._nodes[url] = node
        # Lower priority value = higher urgency for heapq
        priority = -float(node.relevance_score)
        if self.config.same_domain_first and self._seed_hosts:
            if not any(same_registrable_host(node.hostname, h) for h in self._seed_hosts):
                priority += 50  # deprioritize external
        self._seq += 1
        heapq.heappush(self._queue, QueueItem(priority, self._seq, node))
        self.stats.pages_queued = len(self._queue)
        return True

    async def _push_safe(self, node: CrawlNode) -> bool:
        if self._queue_lock is None:
            return self._push(node)
        async with self._queue_lock:
            return self._push(node)

    def _persist_state(self) -> None:
        payload = {
            "session_id": self.stats.session_id,
            "config": self.config.to_dict(),
            "stats": self.stats.to_dict(),
            "visited": sorted(self._visited),
            "queued": [item.node.to_dict() for item in sorted(self._queue, key=lambda q: (q.priority, q.seq))],
            "updated_at": utc_now_iso(),
        }
        atomic_write_json(self.paths.crawl_state, payload)
        atomic_write_json(self.paths.session_stats, self.stats.to_dict())

    def _load_resume(self) -> None:
        path = self.paths.crawl_state
        if not path.exists():
            return
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        self._visited = set(data.get("visited") or [])
        for raw in data.get("queued") or []:
            try:
                node = CrawlNode.from_dict(raw)
                if node.normalized_url not in self._visited:
                    self._push(node)
            except Exception:
                continue
        prior_stats = data.get("stats") or {}
        self.stats.pages_visited = int(prior_stats.get("pages_visited") or 0)
        self.stats.pdfs_confirmed = int(prior_stats.get("pdfs_confirmed") or 0)
        self.stats.pdf_candidates = int(prior_stats.get("pdf_candidates") or 0)
        if data.get("session_id"):
            self.stats.session_id = str(data["session_id"])

    def _record_resource(
        self,
        *,
        node: CrawlNode,
        final_url: str,
        confirmed: bool,
        mime_type: str | None,
        filename: str | None,
        content_length: int | None,
        redirect_chain: list[str],
        discovery_method: str,
        title: str | None = None,
    ) -> ResourceRecord:
        normalized = normalize_url(final_url, allow_private=self.config.allow_private_hosts)
        rid = new_resource_id(normalized)
        existing = self.index.get(rid) or self.index.get_by_normalized_url(normalized)
        record = ResourceRecord(
            id=rid,
            title=title or node.page_title,
            source_page=node.parent_url or (node.click_path[-2] if len(node.click_path) > 1 else None),
            source_site=next(iter(self._seed_hosts), None),
            discovered_url=node.url,
            final_url=final_url,
            normalized_url=normalized,
            hostname=hostname_of(normalized),
            mime_type=mime_type,
            filename=filename,
            content_length=content_length,
            status=ResourceStatus.CONFIRMED.value if confirmed else ResourceStatus.CANDIDATE.value,
            download_status=(existing.download_status if existing else DownloadStatus.NOT_DOWNLOADED.value),
            local_path=existing.local_path if existing else None,
            sha256=existing.sha256 if existing else None,
            depth=node.depth,
            anchor_text=node.anchor_text,
            discovery_method=discovery_method,
            click_path=list(node.click_path),
            redirect_chain=list(redirect_chain),
            verified_at=utc_now_iso() if confirmed else None,
            session_id=self.stats.session_id,
            format_hint="pdf",
        )
        self.index.upsert(record)
        if confirmed:
            self.stats.pdfs_confirmed += 1
        else:
            self.stats.pdf_candidates += 1
        return record

    async def run(self) -> dict[str, Any]:
        self.cancel.install_signal_handlers()
        if self.config.resume:
            self._load_resume()
        else:
            # Fresh crawl: clear cancel flag only
            self.cancel.clear()

        started = time.perf_counter()
        for raw in self.config.start_urls:
            try:
                normalized = normalize_url(raw, allow_private=self.config.allow_private_hosts)
            except Exception as exc:
                self.stats.errors += 1
                continue
            host = hostname_of(normalized)
            self._seed_hosts.add(host)
            node = CrawlNode(
                url=raw,
                normalized_url=normalized,
                depth=0,
                hostname=host,
                discovery_method="seed",
                click_path=[normalized],
                relevance_score=10.0,
            )
            self._push(node)

        if not self._queue and not self._visited:
            return self._result(success=False, error="No valid start_urls", error_class=ErrorClass.INVALID_URL.value)

        # Resume with empty queue + already-visited seeds is a silent no-op unless callers
        # intentionally continue an interrupted crawl that still has queued URLs.
        if self.config.resume and not self._queue:
            return self._result(
                success=False,
                error=(
                    "Resume found no queued URLs (seeds already visited). "
                    "Pass resume=false for a fresh crawl, or provide new start_urls."
                ),
                error_class=ErrorClass.CRAWL_BUDGET_EXCEEDED.value,
            )

        pages_visited_before = int(self.stats.pages_visited)
        pdfs_confirmed_before = int(self.stats.pdfs_confirmed)

        async with HttpClient(
            timeout=self.config.request_timeout_seconds,
            max_retries=self.config.max_retries,
            max_redirects=self.config.max_redirects,
            allow_private=self.config.allow_private_hosts,
            rate_limiter=HostRateLimiter(self.config.rate_limit_ms),
        ) as http:
            robots = RobotsCache(USER_AGENT)
            browser = BrowserEscalator(
                timeout_ms=int(self.config.browser_timeout_seconds * 1000),
                max_pages=self.config.max_browser_pages,
                allow_private=self.config.allow_private_hosts,
            )
            browser_started = False
            if self.config.use_browser:
                browser_started = await browser.start()

            sem = asyncio.Semaphore(self.config.max_concurrent_requests)
            queue_lock = asyncio.Lock()
            self._queue_lock = queue_lock

            async def process(node: CrawlNode) -> None:
                async with sem:
                    if self.cancel.is_cancelled():
                        self.stats.cancelled = True
                        return
                    if node.depth <= self.config.max_depth:
                        await self._visit(
                            node,
                            http=http,
                            robots=robots,
                            browser=browser if browser_started else None,
                        )
                    if self.stats.pages_visited and self.stats.pages_visited % 20 == 0:
                        self._persist_state()
                        self.index.export_jsonl_and_links()

            try:
                tasks: set[asyncio.Task] = set()

                async def spawn(node: CrawlNode) -> None:
                    task = asyncio.create_task(process(node))
                    tasks.add(task)

                    def _done(t: asyncio.Task) -> None:
                        tasks.discard(t)

                    task.add_done_callback(_done)

                # Seed already queued; mark visited as we take items.
                while True:
                    if self.cancel.is_cancelled():
                        self.stats.cancelled = True
                        break
                    if self.stats.pages_visited >= self.config.max_pages:
                        break

                    batch: list[CrawlNode] = []
                    async with queue_lock:
                        while self._queue and len(batch) < self.config.max_concurrent_requests:
                            item = heapq.heappop(self._queue)
                            self.stats.pages_queued = len(self._queue)
                            node = item.node
                            if node.normalized_url in self._visited:
                                self.stats.duplicate_urls += 1
                                continue
                            self._visited.add(node.normalized_url)
                            self._queued.discard(node.normalized_url)
                            batch.append(node)

                    if not batch:
                        if not tasks:
                            break
                        # Wait for at least one in-flight task to finish (may enqueue more)
                        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for finished in done:
                            exc = finished.exception()
                            if exc:
                                self.stats.errors += 1
                        continue

                    for node in batch:
                        await spawn(node)

                    # Bound outstanding tasks
                    if len(tasks) >= self.config.max_concurrent_requests:
                        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for finished in done:
                            if finished.exception():
                                self.stats.errors += 1

                if tasks:
                    await asyncio.wait(tasks)
            finally:
                await browser.close()
                self.stats.finished_at = utc_now_iso()
                self.stats.duration_seconds = round(time.perf_counter() - started, 3)
                self._persist_state()
                exports = self.index.export_jsonl_and_links()

        success = not self.stats.cancelled
        error = None
        error_class = None
        pages_delta = int(self.stats.pages_visited) - pages_visited_before
        pdfs_delta = int(self.stats.pdfs_confirmed) - pdfs_confirmed_before
        if self.stats.cancelled:
            error = self.cancel.reason
            error_class = ErrorClass.CANCELLED.value
        elif self.stats.pages_visited == 0 and self.stats.pdfs_confirmed == 0:
            success = False
            error = "Crawl produced no visited pages"
            error_class = ErrorClass.UNKNOWN.value
        elif self.config.resume and pages_delta == 0 and pdfs_delta == 0 and not self.stats.cancelled:
            # Loaded prior state but performed no new work this invocation.
            success = False
            error = (
                "Resume crawl made no new progress (0 new pages / PDFs). "
                "Pass resume=false to restart discovery."
            )
            error_class = ErrorClass.CRAWL_BUDGET_EXCEEDED.value

        payload = self._result(success=success, error=error, error_class=error_class, exports=exports)
        payload["pages_visited_this_run"] = pages_delta
        payload["pdfs_confirmed_this_run"] = pdfs_delta
        return payload

    async def _visit(
        self,
        node: CrawlNode,
        *,
        http: HttpClient,
        robots: RobotsCache,
        browser: BrowserEscalator | None,
    ) -> None:
        self.stats.current_host = node.hostname
        node.state = NodeState.VISITING.value

        allowed = await robots.allowed(
            node.normalized_url,
            http.fetch_robots_text,
            enabled=self.config.respect_robots_txt,
        )
        if not allowed:
            node.state = NodeState.BLOCKED.value
            node.error_class = ErrorClass.ROBOTS_BLOCKED.value
            node.error = "Blocked by robots.txt"
            self.stats.blocked_pages += 1
            return

        try:
            result = await http.fetch(node.normalized_url, referer=node.referrer, read_body=True, probe_pdf=True)
        except Exception as exc:
            node.state = NodeState.FAILED.value
            node.error = str(exc)
            node.error_class = ErrorClass.NETWORK_ERROR.value
            self.stats.errors += 1
            return

        if result.redirect_chain and len(result.redirect_chain) > 1:
            self.stats.redirects += 1
            node.redirect_chain = list(result.redirect_chain)
            node.state = NodeState.REDIRECTED.value

        if result.error and result.status_code == 0:
            node.state = NodeState.FAILED.value
            node.error = result.error
            node.error_class = result.error_class
            self.stats.errors += 1
            return

        if result.status_code in {401, 403}:
            node.state = NodeState.BLOCKED.value
            node.error_class = ErrorClass.AUTH_REQUIRED.value
            self.stats.blocked_pages += 1
            return

        detection = result.detection
        final_url = result.final_url
        node.click_path = join_click_path(node.click_path, final_url)

        if detection and detection.is_pdf and detection.confidence >= 0.8:
            # Confirmed PDF — record only, do NOT download body to disk
            self._record_resource(
                node=node,
                final_url=final_url,
                confirmed=True,
                mime_type=detection.mime_type or "application/pdf",
                filename=detection.filename,
                content_length=detection.content_length,
                redirect_chain=result.redirect_chain,
                discovery_method=detection.method,
                title=node.page_title,
            )
            node.state = NodeState.PDF_CONFIRMED.value
            self.stats.pages_visited += 1
            return

        if detection and detection.method == "url_pdf_but_html_mime":
            # False .pdf — treat as HTML page if we have text, else candidate fail
            pass

        html = result.text or ""
        barrier = classify_barrier(html, result.status_code)
        if barrier:
            node.state = NodeState.BLOCKED.value
            node.error_class = barrier
            self.stats.blocked_pages += 1
            # Still record as blocked candidate if it looked like download
            if is_likely_pdf_candidate_url(final_url, node.anchor_text or ""):
                rec = self._record_resource(
                    node=node,
                    final_url=final_url,
                    confirmed=False,
                    mime_type=detection.mime_type if detection else None,
                    filename=detection.filename if detection else None,
                    content_length=None,
                    redirect_chain=result.redirect_chain,
                    discovery_method="blocked",
                )
                rec.status = ResourceStatus.BLOCKED.value
                rec.error_class = barrier
                self.index.upsert(rec)
            self.stats.pages_visited += 1
            return

        # Escalate to browser when HTML is empty/thin or likely JS shell
        if browser and (len(html.strip()) < 200 or "javascript" in html.lower()[:500]):
            self.stats.browser_fallbacks += 1
            discovery = await browser.discover(final_url, referer=node.referrer)
            if discovery.html:
                html = discovery.html
            if discovery.title:
                node.page_title = discovery.title
            for discovered in discovery.discovered_urls:
                child = self._make_child(
                    parent=node,
                    url=discovered,
                    anchor_text="browser",
                    score=25.0,
                    method="browser",
                )
                if child:
                    # Immediate PDF check via headers
                    probe = await http.fetch(child.normalized_url, referer=final_url, method="GET", read_body=False, probe_pdf=True)
                    if probe.detection and probe.detection.is_pdf:
                        child.click_path = join_click_path(node.click_path, probe.final_url)
                        child.redirect_chain = probe.redirect_chain
                        self._record_resource(
                            node=child,
                            final_url=probe.final_url,
                            confirmed=True,
                            mime_type=probe.detection.mime_type,
                            filename=probe.detection.filename,
                            content_length=probe.detection.content_length,
                            redirect_chain=probe.redirect_chain,
                            discovery_method="browser",
                            title=discovery.title,
                        )
                    else:
                        await self._push_safe(child)

        scored, title, canonical = extract_scored_links(
            html,
            final_url,
            parent_score=node.relevance_score,
            allow_private=self.config.allow_private_hosts,
            max_urls=self.config.max_urls_per_page,
        )
        if title:
            node.page_title = title
        if canonical and canonical != final_url:
            child = self._make_child(parent=node, url=canonical, anchor_text="canonical", score=12.0, method="canonical")
            if child:
                await self._push_safe(child)

        # If current page looks like download landing but no PDF yet, mark candidate
        if is_likely_pdf_candidate_url(final_url, node.anchor_text or "") and not any(
            s.score >= 30 and s.url.endswith(".pdf") for s in scored[:5]
        ):
            self._record_resource(
                node=node,
                final_url=final_url,
                confirmed=False,
                mime_type=detection.mime_type if detection else None,
                filename=detection.filename if detection else None,
                content_length=detection.content_length if detection else None,
                redirect_chain=result.redirect_chain,
                discovery_method="candidate_page",
                title=title,
            )

        for link in scored:
            if link.score < self.config.min_enqueue_score and not link.url.lower().endswith(".pdf"):
                continue
            child = self._make_child(
                parent=node,
                url=link.url,
                anchor_text=link.anchor_text,
                score=link.score,
                method="link",
            )
            if not child:
                continue
            # Fast-path: URL itself looks like PDF — probe headers without enqueueing deep crawl when confirmed
            if link.url.lower().endswith(".pdf") or link.score >= 35:
                probe = await http.fetch(child.normalized_url, referer=final_url, read_body=False, probe_pdf=True)
                if probe.detection and probe.detection.is_pdf and probe.detection.confidence >= 0.8:
                    child.click_path = join_click_path(node.click_path, probe.final_url)
                    child.redirect_chain = probe.redirect_chain
                    child.anchor_text = link.anchor_text
                    self._record_resource(
                        node=child,
                        final_url=probe.final_url,
                        confirmed=True,
                        mime_type=probe.detection.mime_type,
                        filename=probe.detection.filename,
                        content_length=probe.detection.content_length,
                        redirect_chain=probe.redirect_chain,
                        discovery_method=probe.detection.method,
                        title=title,
                    )
                    continue
                if probe.detection and probe.detection.method == "url_pdf_but_html_mime":
                    # Fake PDF URL — enqueue as HTML page
                    pass
            await self._push_safe(child)

        node.state = NodeState.VISITED.value
        self.stats.pages_visited += 1

    def _make_child(
        self,
        *,
        parent: CrawlNode,
        url: str,
        anchor_text: str,
        score: float,
        method: str,
    ) -> CrawlNode | None:
        normalized = safe_normalize(url, allow_private=self.config.allow_private_hosts)
        if not normalized:
            return None
        host = hostname_of(normalized)
        external = 0
        if self._seed_hosts and not any(same_registrable_host(host, h) for h in self._seed_hosts):
            external = parent.external_hops + 1
            if not self.config.allow_external_resource_hosts:
                return None
            # Only follow external when strong resource signal
            if score < 12 and not normalized.lower().endswith(".pdf"):
                return None
            if external > self.config.max_external_hops:
                return None
            self.stats.external_hosts_followed += 1
        if parent.depth + 1 > self.config.max_depth:
            return None
        return CrawlNode(
            url=url,
            normalized_url=normalized,
            parent_url=parent.normalized_url,
            referrer=parent.normalized_url,
            depth=parent.depth + 1,
            external_hops=external,
            hostname=host,
            anchor_text=anchor_text[:300] if anchor_text else None,
            discovery_method=method,
            click_path=join_click_path(parent.click_path, normalized),
            relevance_score=score,
        )

    def _result(
        self,
        *,
        success: bool,
        error: str | None = None,
        error_class: str | None = None,
        exports: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        exports = exports or self.index.export_jsonl_and_links()
        counts = self.index.counts()
        return {
            "success": success,
            "action": "discover",
            "session_id": self.stats.session_id,
            "stats": self.stats.to_dict(),
            "index_counts": counts,
            "index_path": exports.get("index_path"),
            "sqlite_path": exports.get("sqlite_path"),
            "links_export_path": exports.get("links_export_path"),
            "download_available": counts.get("confirmed", 0) > 0,
            "size_estimate": self.index.size_estimate(),
            "error": error,
            "error_class": error_class,
            "cancelled": self.stats.cancelled,
        }
