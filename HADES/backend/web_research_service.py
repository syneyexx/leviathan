"""Web research crawl helpers extracted from platform_services_core (Wave 28).

Zero intended behavior change — moved for god-file diet with facade re-exports.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from pathlib import Path
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from platform_services_core import KnowledgeService


def _psc():
    """Lazy import — avoids circular import with platform_services_core facade."""
    import platform_services_core as psc

    return psc


_LOCAL_UNSET = object()


@dataclass
class CrawlResult:
    url: str
    title: str
    text: str
    links: list[str]
    metadata: dict[str, Any]
    raw_html: str


class WebResearchService:
    def __init__(self, knowledge: "KnowledgeService", timeout: float = 30.0) -> None:
        self.knowledge = knowledge
        self.timeout = timeout
        self.user_agent = "HADES-Research/0.4 (+local-user-agent)"

    async def allowed_by_robots(self, url: str) -> bool:
        from url_security import UrlSecurityError, assert_public_http_url, redirect_location, safe_public_url

        parsed = urllib.parse.urlparse(url)
        robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        try:
            assert_public_http_url(robots_url, purpose="robots", allow_loopback=True)
        except UrlSecurityError:
            # Fail closed: cannot evaluate robots for private/blocked hosts.
            return False
        try:
            # follow_redirects=False: each hop must pass SSRF validation.
            current = robots_url
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": self.user_agent},
                follow_redirects=False,
            ) as client:
                response = None
                for _ in range(5):
                    response = await client.get(current)
                    nxt = redirect_location(response, current)
                    if nxt is None:
                        break
                safe = safe_public_url(nxt, allow_private=False, allow_loopback=False)
                if not safe:
                    return False
                current = safe
            if response is None:
                return False
            if response.status_code in {404, 410}:
                return True
            if response.status_code >= 400:
                # Fail closed when robots.txt cannot be evaluated (non-missing errors).
                return False
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return False

    async def _get(self, url: str, *, respect_robots: bool = True) -> httpx.Response:
        from url_security import (
            UrlSecurityError,
            assert_public_http_url,
            load_network_domain_policy,
            redirect_location,
            safe_public_url,
        )

        try:
            # Explicit loopback is allowed for the *initial* user-supplied URL
            # (local-first research against preview/docs servers). Redirect hops
            # must never inherit that privilege (SSRF to other loopback services).
            assert_public_http_url(url, purpose="web_research", allow_loopback=True)
        except UrlSecurityError as exc:
            raise ValueError(str(exc)) from exc
        if respect_robots and not await self.allowed_by_robots(url):
            raise PermissionError("robots.txt staat crawling van deze URL niet toe.")
        _, _, redirect_limit = load_network_domain_policy()
        # redirect_limit=0 means no redirects allowed; keep a hard ceiling of 32.
        max_hops = 0 if redirect_limit <= 0 else min(int(redirect_limit), 32)
        current = url
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=False,
        ) as client:
            response = None
            for hop in range(max_hops + 1):
                response = await client.get(current)
                nxt = redirect_location(response, current)
                if nxt is None:
                    break
                if hop >= max_hops:
                    raise PermissionError(f"Redirect limit ({max_hops}) overschreden voor {url}")
                safe = safe_public_url(nxt, allow_private=False, allow_loopback=False)
                if not safe:
                    raise PermissionError(f"Redirect naar geblokkeerde of private host geweigerd: {nxt}")
                current = safe
            if response is None:
                raise RuntimeError("Geen HTTP-respons ontvangen.")
            response.raise_for_status()
        return response

    async def fetch(self, url: str, *, respect_robots: bool = True) -> CrawlResult:
        response = await self._get(url, respect_robots=respect_robots)
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            raise ValueError(f"Niet-ondersteund web-content-type: {content_type or 'onbekend'}")
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "header", "footer"]):
            node.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else str(response.url)
        text = soup.get_text("\n", strip=True)
        links = []
        for anchor in soup.find_all("a", href=True):
            absolute = urllib.parse.urljoin(str(response.url), anchor["href"])
            parsed = urllib.parse.urlparse(absolute)
            if parsed.scheme in {"http", "https"}:
                links.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "")))
        metadata = {
            "url": str(response.url),
            "status_code": response.status_code,
            "content_type": content_type,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        return CrawlResult(str(response.url), title, text, list(dict.fromkeys(links)), metadata, response.text)

    @staticmethod
    def _web_document_extension(url: str, content_type: str) -> str:
        extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if extension in {".pdf", ".epub", ".docx", ".txt", ".md", ".html", ".htm"}:
            return extension
        if "application/pdf" in content_type:
            return ".pdf"
        if "application/epub+zip" in content_type:
            return ".epub"
        if "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type:
            return ".docx"
        return ""

    async def ingest_document_url(self, url: str, *, respect_robots: bool = False) -> dict[str, Any]:
        """Download a directly authorized document URL and preserve URL provenance.

        Explicit user-authorized downloads skip robots.txt: the user instructed the fetch.
        Autonomous/default crawls should keep respect_robots=True via fetch/ingest_url.
        """
        response = await self._get(url, respect_robots=respect_robots)
        content_type = response.headers.get("content-type", "").lower()
        extension = self._web_document_extension(str(response.url), content_type)
        if extension not in {".pdf", ".epub", ".docx", ".txt", ".md", ".html", ".htm"}:
            raise ValueError(f"URL is geen ondersteund document ({content_type or 'onbekend'}).")
        data = response.content
        if len(data) > int((_psc()._fs_limit("filesystem.max_download_bytes", 250 * 1024 * 1024) or 250 * 1024 * 1024)):
            raise ValueError("Webdocument is groter dan 250 MB.")
        if extension == ".pdf" and not data.startswith(b"%PDF-"):
            raise ValueError("PDF-validatie mislukt: magic bytes ontbreken.")
        if extension in {".epub", ".docx"} and not data.startswith(b"PK"):
            raise ValueError("ZIP-container validatie voor EPUB/DOCX is mislukt.")
        name = Path(urllib.parse.urlparse(str(response.url)).path).name or f"web-document{extension}"
        if not Path(name).suffix:
            name += extension
        local_path = self.knowledge.store_upload(name, data)
        text, metadata = _psc().extract_document(local_path)
        metadata.update(
            {
                "source_url": str(response.url),
                "content_type": content_type,
                "sha256": _psc().sha256_bytes(data),
                "authorized_download": True,
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
            }
        )
        return self.knowledge.ingest_text(
            title=metadata.get("title") or name,
            text=text,
            source_type="web_document",
            uri=str(response.url),
            metadata=metadata,
            local_path=str(local_path),
        )

    async def ingest_url(self, url: str, authorized_downloads: bool = False) -> dict[str, Any]:
        try:
            result = await self.fetch(url)
        except ValueError as exc:
            # Only direct, explicitly authorized document acquisition may fetch binary documents.
            if authorized_downloads and "content-type" in str(exc).lower():
                return await self.ingest_document_url(url)
            raise
        snapshot_path, snapshot_hash = self.knowledge.store_web_snapshot(result.url, result.raw_html)
        return self.knowledge.ingest_text(
            title=result.title,
            text=result.text,
            source_type="web",
            uri=result.url,
            metadata={**result.metadata, "snapshot_sha256": snapshot_hash},
            local_path=str(snapshot_path),
        )

    _DOC_EXT = {".pdf", ".epub", ".docx", ".txt", ".md", ".html", ".htm"}
    _DOC_HINT_RE = re.compile(
        r"(ebook|e-book|download|\.pdf|\.epub|\.docx|/book/|/books/|/download/|getbook|freebook|full.?text)",
        re.IGNORECASE,
    )

    @classmethod
    def looks_like_document_url(cls, url: str, anchor_text: str = "") -> bool:
        parsed = urllib.parse.urlparse(url)
        extension = Path(parsed.path).suffix.lower()
        if extension in {".pdf", ".epub", ".docx"}:
            return True
        haystack = f"{url} {anchor_text}"
        return bool(cls._DOC_HINT_RE.search(haystack))

    async def _extract_page_links(
        self, url: str, *, respect_robots: bool = True
    ) -> tuple[CrawlResult | None, list[tuple[str, str]]]:
        """Return crawl result (if HTML) plus (absolute_url, anchor_text) pairs."""
        try:
            result = await self.fetch(url, respect_robots=respect_robots)
        except ValueError:
            return None, []
        except Exception:
            return None, []
        pairs: list[tuple[str, str]] = []
        soup = BeautifulSoup(result.raw_html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            absolute = urllib.parse.urljoin(result.url, anchor["href"])
            parsed = urllib.parse.urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))
            text = anchor.get_text(" ", strip=True)
            pairs.append((clean, text))
        # Prefer unique URLs, keep first seen anchor text.
        unique: dict[str, str] = {}
        for link, text in pairs:
            unique.setdefault(link, text)
        return result, list(unique.items())

    async def harvest_site_documents(
        self,
        seed_url: str,
        *,
        max_pages: Any = _LOCAL_UNSET,
        max_depth: Any = _LOCAL_UNSET,
        max_documents: Any = _LOCAL_UNSET,
        authorized_downloads: bool = False,
        include_html_pages: bool = True,
    ) -> dict[str, Any]:
        """Discover documents linked from a site and optionally download/ingest them.

        HTML discovery stays same-origin. When ``authorized_downloads`` is true,
        document URLs may be off-origin (common for ebook directories that link to file hosts).
        ``None`` limits mean Unlimited (no HADES-owned ceiling).
        """
        if max_pages is _LOCAL_UNSET:
            max_pages = _psc()._setting("research.harvest_max_pages", 25)
        if max_depth is _LOCAL_UNSET:
            max_depth = _psc()._setting("research.harvest_max_depth", 2)
        if max_documents is _LOCAL_UNSET:
            max_documents = _psc()._setting("research.harvest_max_documents", 40)
        if not authorized_downloads:
            raise PermissionError("Document-harvest vereist expliciete authorized_downloads=true.")
        seed = urllib.parse.urlparse(seed_url)
        if seed.scheme not in {"http", "https"} or not seed.netloc:
            raise ValueError("Ongeldige harvest-URL.")

        def _under(count: int, limit: int | None) -> bool:
            return True if limit is None else count < int(limit)

        # User-authorized harvest: the operator explicitly asked to fetch linked documents.
        respect_robots = False
        queue: list[tuple[str, int]] = [(seed_url, 0)]
        seen_pages: set[str] = set()
        seen_docs: set[str] = set()
        page_sources: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        discovered_doc_urls: list[str] = []

        while queue and _under(len(seen_pages), max_pages):
            current, depth = queue.pop(0)
            normalized = urllib.parse.urldefrag(current)[0]
            if normalized in seen_pages:
                continue
            parsed = urllib.parse.urlparse(normalized)
            if parsed.netloc.lower() != seed.netloc.lower():
                # Off-origin pages are never crawled for HTML discovery.
                if self.looks_like_document_url(normalized):
                    discovered_doc_urls.append(normalized)
                continue
            extension = Path(parsed.path).suffix.lower()
            if extension in {".pdf", ".epub", ".docx"}:
                discovered_doc_urls.append(normalized)
                continue

            seen_pages.add(normalized)
            result, links = await self._extract_page_links(normalized, respect_robots=respect_robots)
            if result is None:
                failures.append({"url": normalized, "error": "Pagina kon niet worden opgehaald."})
                continue

            if include_html_pages:
                snapshot_path, snapshot_hash = self.knowledge.store_web_snapshot(result.url, result.raw_html)
                page_source = self.knowledge.ingest_text(
                    title=result.title,
                    text=result.text,
                    source_type="web",
                    uri=result.url,
                    metadata={
                        **result.metadata,
                        "harvest_seed": seed_url,
                        "harvest_depth": depth,
                        "snapshot_sha256": snapshot_hash,
                        "authorized_download": True,
                        "respect_robots": respect_robots,
                    },
                    local_path=str(snapshot_path),
                )
                if _psc().knowledge_ingest_verified(page_source):
                    page_sources.append(page_source)
                else:
                    failures.append(
                        {
                            "url": result.url,
                            "error": "knowledge_verification_failed",
                            "status": (page_source or {}).get("status"),
                        }
                    )

            for link, anchor_text in links:
                target = urllib.parse.urlparse(link)
                if self.looks_like_document_url(link, anchor_text):
                    discovered_doc_urls.append(link)
                    continue
                if (
                    (max_depth is None or depth < int(max_depth))
                    and target.netloc.lower() == seed.netloc.lower()
                    and link not in seen_pages
                ):
                    queue.append((link, depth + 1))
            await asyncio.sleep(0.05)

        for doc_url in list(dict.fromkeys(discovered_doc_urls)):
            if max_documents is not None and len(documents) >= int(max_documents):
                break
            normalized_doc = urllib.parse.urldefrag(doc_url)[0]
            if normalized_doc in seen_docs:
                continue
            seen_docs.add(normalized_doc)
            try:
                source = await self.ingest_document_url(normalized_doc, respect_robots=respect_robots)
                if _psc().knowledge_ingest_verified(source):
                    documents.append(source)
                else:
                    failures.append(
                        {
                            "url": normalized_doc,
                            "error": "knowledge_verification_failed",
                            "status": (source or {}).get("status"),
                        }
                    )
            except Exception as first_exc:
                # One-hop: HTML "download" pages often wrap the real PDF/EPUB URL.
                followed = False
                try:
                    hop, hop_links = await self._extract_page_links(normalized_doc, respect_robots=respect_robots)
                    if hop is not None:
                        for hop_url, hop_text in hop_links:
                            if not self.looks_like_document_url(hop_url, hop_text):
                                continue
                            hop_norm = urllib.parse.urldefrag(hop_url)[0]
                            if hop_norm in seen_docs:
                                continue
                            if Path(urllib.parse.urlparse(hop_norm).path).suffix.lower() not in {".pdf", ".epub", ".docx"}:
                                if not re.search(r"\.(pdf|epub|docx)(\?|$)", hop_norm, re.I):
                                    continue
                            seen_docs.add(hop_norm)
                            source = await self.ingest_document_url(hop_norm, respect_robots=respect_robots)
                            if _psc().knowledge_ingest_verified(source):
                                documents.append(source)
                                followed = True
                                break
                            failures.append(
                                {
                                    "url": hop_norm,
                                    "error": "knowledge_verification_failed",
                                    "status": (source or {}).get("status"),
                                }
                            )
                            followed = True
                            break
                except Exception:
                    followed = False
                if not followed:
                    failures.append({"url": normalized_doc, "error": str(first_exc)})
            await asyncio.sleep(0.05)

        return {
            "seed_url": seed_url,
            "pages_crawled": len(seen_pages),
            "documents_discovered": len(seen_docs),
            "documents_ingested": len(documents),
            "page_sources": page_sources,
            "documents": documents,
            "failures": failures,
            "authorized_downloads": True,
        }

    async def crawl_site(
        self,
        seed_url: str,
        *,
        max_pages: Any = _LOCAL_UNSET,
        max_depth: Any = _LOCAL_UNSET,
        authorized_downloads: bool = False,
    ) -> list[dict[str, Any]]:
        """Bounded same-origin BFS crawler with robots checks and optional authorized documents."""
        if max_pages is _LOCAL_UNSET:
            max_pages = _psc()._setting("research.crawl_max_pages", 10)
        if max_depth is _LOCAL_UNSET:
            max_depth = _psc()._setting("research.crawl_max_depth", 1)
        if authorized_downloads:
            doc_cap = None if max_pages is None else max(10, int(max_pages))
            harvest = await self.harvest_site_documents(
                seed_url,
                max_pages=max_pages,
                max_depth=max_depth,
                max_documents=doc_cap,
                authorized_downloads=True,
                include_html_pages=True,
            )
            return list(harvest.get("page_sources") or []) + list(harvest.get("documents") or [])

        seed = urllib.parse.urlparse(seed_url)
        if seed.scheme not in {"http", "https"} or not seed.netloc:
            raise ValueError("Ongeldige crawl-URL.")
        queue: list[tuple[str, int]] = [(seed_url, 0)]
        seen: set[str] = set()
        sources: list[dict[str, Any]] = []
        fetch_attempts = 0
        fetch_failures = 0
        fetch_errors: list[dict[str, str]] = []
        while queue and (max_pages is None or len(sources) < int(max_pages)):
            current, depth = queue.pop(0)
            normalized = urllib.parse.urldefrag(current)[0]
            if normalized in seen:
                continue
            seen.add(normalized)
            parsed = urllib.parse.urlparse(normalized)
            if parsed.netloc.lower() != seed.netloc.lower():
                continue
            extension = Path(parsed.path).suffix.lower()
            if extension in {".pdf", ".epub", ".docx"}:
                continue
            fetch_attempts += 1
            try:
                result = await self.fetch(normalized)
            except Exception as exc:
                fetch_failures += 1
                fetch_errors.append({"url": normalized, "error": str(exc)})
                continue
            snapshot_path, snapshot_hash = self.knowledge.store_web_snapshot(result.url, result.raw_html)
            source = self.knowledge.ingest_text(
                title=result.title,
                text=result.text,
                source_type="web",
                uri=result.url,
                metadata={**result.metadata, "crawl_seed": seed_url, "crawl_depth": depth, "snapshot_sha256": snapshot_hash},
                local_path=str(snapshot_path),
            )
            sources.append(source)
            if max_depth is not None and depth >= int(max_depth):
                continue
            for link in result.links:
                target = urllib.parse.urlparse(link)
                if target.netloc.lower() != seed.netloc.lower():
                    continue
                if link not in seen:
                    queue.append((link, depth + 1))
            await asyncio.sleep(0.12)
        # All attempted fetches failed — not a legitimate empty crawl (PDF-only sites still return []).
        if not sources and fetch_attempts > 0 and fetch_failures == fetch_attempts:
            detail = fetch_errors[0]["error"] if fetch_errors else "unknown"
            raise RuntimeError(f"crawl_site: all {fetch_failures} page fetches failed for {seed_url}: {detail}")
        return sources

    async def discover_duckduckgo(self, query: str, max_results: int = 8) -> list[str]:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": self.user_agent}, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[str] = []
        for anchor in soup.select("a.result__a, a.result-link"):
            href = anchor.get("href", "")
            if href.startswith("//duckduckgo.com/l/?") or "duckduckgo.com/l/?" in href:
                parsed = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href)
                target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
                href = urllib.parse.unquote(target)
            if href.startswith("http"):
                results.append(href)
            if len(results) >= max_results:
                break
        return list(dict.fromkeys(results))


