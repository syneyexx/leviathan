from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from deep_utils import (
    DEFAULT_MAX_FILE_BYTES, HTML_MAX_BYTES, USER_AGENT, extract_links,
    extension_from_content_type, filename_from_headers, is_probable_download,
    normalize_url, same_site, sanitize_filename, assert_public_crawl_url,
)


@dataclass
class CrawlItem:
    url: str
    depth: int
    referer: str | None


class DeepCrawler:
    def __init__(
        self, *, seed_url: str, output_dir: Path, max_depth: int = 6,
        max_pages: int = 500, max_files: int = 500,
        allowed_domains: str = "", save_html: bool = True,
        delay_seconds: float = 0.20,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, timeout_seconds: float = 25.0,
    ) -> None:
        self.seed_url = normalize_url(seed_url)
        self.seed_host = urllib.parse.urlsplit(self.seed_url).hostname or ""
        extras = {part.strip().lower() for part in allowed_domains.split(",") if part.strip()}
        self.allowed_hosts = {self.seed_host, *extras}
        self.output_dir = output_dir.expanduser().resolve()
        self.max_depth = max(0, int(max_depth))
        self.max_pages = max(1, int(max_pages))
        self.max_files = max(1, int(max_files))
        self.save_html = bool(save_html)
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.timeout_seconds = max(1.0, float(timeout_seconds))

        self.pages_dir = self.output_dir / "pages"
        self.files_dir = self.output_dir / "files"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        # Manual redirect handling: validate each hop (SSRF). Do not auto-follow.
        self.opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
        self.visited: set[str] = set()
        self.enqueued: set[str] = set()
        self.hash_to_path: dict[str, str] = {}
        self.records: list[dict] = []
        self.errors: list[dict] = []
        self.robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _request(self, url: str, referer: str | None = None):
        current = assert_public_crawl_url(url)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream,*/*;q=0.8",
            "Accept-Encoding": "identity",
        }
        if referer:
            headers["Referer"] = referer
        for _ in range(8):
            if not self._allowed_domain(current):
                raise PermissionError(f"Redirect left allowed domain: {current}")
            try:
                response = self.opener.open(
                    urllib.request.Request(current, headers=headers, method="GET"),
                    timeout=self.timeout_seconds,
                )
                return response
            except urllib.error.HTTPError as exc:
                if int(getattr(exc, "code", 0) or 0) not in {301, 302, 303, 307, 308}:
                    raise
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    raise
                nxt = urllib.parse.urljoin(current, location)
                current = assert_public_crawl_url(nxt)
                continue
        raise RuntimeError(f"Too many redirects for {url}")

    def _robots_allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc.lower()
        if host not in self.robots:
            robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
                with self.opener.open(req, timeout=min(10.0, self.timeout_seconds)) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    body = response.read(512 * 1024).decode("utf-8", errors="replace")
                if status in {404, 410}:
                    # Missing robots.txt → allow (standard crawler behavior).
                    rp.parse([])
                else:
                    rp.parse(body.splitlines())
            except urllib.error.HTTPError as exc:
                if int(getattr(exc, "code", 0) or 0) in {404, 410}:
                    rp.parse([])
                else:
                    # Fail closed when robots.txt cannot be evaluated.
                    rp.parse(["User-agent: *", "Disallow: /"])
            except Exception:
                rp.parse(["User-agent: *", "Disallow: /"])
            self.robots[host] = rp
        return self.robots[host].can_fetch(USER_AGENT, url)

    def _allowed_domain(self, url: str) -> bool:
        host = urllib.parse.urlsplit(url).hostname or ""
        return any(same_site(host, allowed) for allowed in self.allowed_hosts)

    def _unique_path(self, directory: Path, filename: str) -> Path:
        candidate = directory / sanitize_filename(filename)
        stem, suffix, n = candidate.stem or "download", candidate.suffix, 2
        while candidate.exists():
            candidate = directory / f"{stem}-{n}{suffix}"
            n += 1
        return candidate

    def _save_html(self, url: str, data: bytes) -> str | None:
        if not self.save_html:
            return None
        parsed = urllib.parse.urlsplit(url)
        host_dir = self.pages_dir / sanitize_filename(parsed.hostname or "site")
        host_dir.mkdir(parents=True, exist_ok=True)
        name = sanitize_filename(Path(parsed.path).name or "index.html")
        if not Path(name).suffix:
            name += ".html"
        path = self._unique_path(host_dir, name)
        path.write_bytes(data)
        return str(path)

    def _download_stream(self, response, url: str, content_type: str) -> dict:
        filename = filename_from_headers(url, response.headers)
        if not Path(filename).suffix:
            filename += extension_from_content_type(content_type)
        target = self._unique_path(self.files_dir, sanitize_filename(filename, "download"))
        temp_path = target.with_suffix(target.suffix + ".part")
        digest, total = hashlib.sha256(), 0
        try:
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_file_bytes:
                        raise ValueError(f"File exceeds max_file_bytes={self.max_file_bytes}")
                    digest.update(chunk)
                    handle.write(chunk)
            sha = digest.hexdigest()
            duplicate_of = self.hash_to_path.get(sha)
            if duplicate_of:
                temp_path.unlink(missing_ok=True)
                return {"kind": "file", "url": url, "path": duplicate_of, "sha256": sha,
                        "bytes": total, "content_type": content_type, "duplicate": True}
            temp_path.replace(target)
            self.hash_to_path[sha] = str(target)
            return {"kind": "file", "url": url, "path": str(target), "sha256": sha,
                    "bytes": total, "content_type": content_type, "duplicate": False}
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def crawl(self) -> dict:
        queue: deque[CrawlItem] = deque([CrawlItem(self.seed_url, 0, None)])
        self.enqueued.add(self.seed_url)
        pages_fetched = files_downloaded = 0

        while queue and pages_fetched < self.max_pages and files_downloaded < self.max_files:
            item = queue.popleft()
            if item.url in self.visited or not self._allowed_domain(item.url):
                continue
            if not self._robots_allowed(item.url):
                self.records.append({"kind": "blocked_by_robots", "url": item.url, "depth": item.depth})
                self.visited.add(item.url)
                continue

            self.visited.add(item.url)
            try:
                with self._request(item.url, item.referer) as response:
                    final_url = normalize_url(response.geturl())
                    if not self._allowed_domain(final_url):
                        self.records.append({
                            "kind": "blocked_domain", "url": final_url, "depth": item.depth,
                            "reason": "Final redirect host is not in allowed_domains."
                        })
                        continue

                    content_type = response.headers.get("Content-Type", "")
                    disposition = response.headers.get("Content-Disposition", "")
                    if is_probable_download(final_url, content_type, disposition):
                        record = self._download_stream(response, final_url, content_type)
                        record.update({"depth": item.depth, "referer": item.referer})
                        self.records.append(record)
                        files_downloaded += 0 if record.get("duplicate") else 1
                    else:
                        data = response.read(HTML_MAX_BYTES + 1)
                        if len(data) > HTML_MAX_BYTES:
                            raise ValueError(f"HTML response exceeds {HTML_MAX_BYTES} bytes")
                        pages_fetched += 1
                        charset = response.headers.get_content_charset() or "utf-8"
                        text = data.decode(charset, errors="replace")
                        links = extract_links(text, final_url)
                        self.records.append({
                            "kind": "page", "url": final_url, "path": self._save_html(final_url, data),
                            "depth": item.depth, "links_found": len(links), "bytes": len(data),
                            "content_type": content_type,
                        })
                        if item.depth < self.max_depth:
                            for link in links:
                                if (link not in self.visited and link not in self.enqueued
                                        and self._allowed_domain(link)):
                                    queue.append(CrawlItem(link, item.depth + 1, final_url))
                                    self.enqueued.add(link)
            except urllib.error.HTTPError as exc:
                self.errors.append({"url": item.url, "depth": item.depth, "type": "HTTPError",
                                    "status": exc.code, "error": str(exc)})
            except Exception as exc:
                self.errors.append({"url": item.url, "depth": item.depth,
                                    "type": type(exc).__name__, "error": str(exc)})
            if self.delay_seconds:
                time.sleep(self.delay_seconds)

        manifest = {
            "seed_url": self.seed_url,
            "output_dir": str(self.output_dir),
            "settings": {
                "max_depth": self.max_depth, "max_pages": self.max_pages,
                "max_files": self.max_files, "allowed_domains": sorted(self.allowed_hosts),
                "save_html": self.save_html, "robots_txt": "always_enforced",
                "max_file_bytes": self.max_file_bytes,
            },
            "summary": {
                "visited_urls": len(self.visited),
                "pages_fetched": sum(r.get("kind") == "page" for r in self.records),
                "files_downloaded": sum(r.get("kind") == "file" and not r.get("duplicate") for r in self.records),
                "duplicate_files": sum(r.get("kind") == "file" and r.get("duplicate") for r in self.records),
                "errors": len(self.errors), "queue_remaining": len(queue),
            },
            "records": self.records, "errors": self.errors,
        }
        manifest_path = self.output_dir / "crawl-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path)
        return manifest
