"""Streaming PDF downloads, separate from discovery."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import httpx

from .cancel import CancelToken
from .http_client import USER_AGENT
from .index import ResourceIndex
from .models import DownloadStatus, ErrorClass, ResourceRecord, utc_now_iso
from .pdf_detect import PDF_MAGIC, parse_content_disposition
from .rate_limit import HostRateLimiter
from .storage import StoragePaths, sanitize_filename
from .urls import hostname_of, normalize_url, safe_normalize


class Downloader:
    def __init__(
        self,
        *,
        index: ResourceIndex,
        paths: StoragePaths,
        cancel: CancelToken | None = None,
        concurrency: int = 3,
        chunk_size: int = 256 * 1024,
        timeout: float = 60.0,
        max_retries: int = 3,
        allow_private: bool = False,
    ) -> None:
        self.index = index
        self.paths = paths.ensure()
        self.cancel = cancel or CancelToken(self.paths.cancel_flag)
        self.concurrency = max(1, concurrency)
        self.chunk_size = max(8 * 1024, chunk_size)
        self.timeout = timeout
        self.max_retries = max_retries
        self.allow_private = allow_private
        self.rate_limiter = HostRateLimiter(500)

    async def download_ids(self, resource_ids: list[str]) -> dict[str, Any]:
        records = []
        missing = []
        for rid in resource_ids:
            rec = self.index.get(rid)
            if rec is None:
                missing.append(rid)
            else:
                records.append(rec)
        return await self._download_many(records, missing=missing)

    async def download_all(self) -> dict[str, Any]:
        confirmed = self.index.all_confirmed()
        if not confirmed:
            estimate = self.index.size_estimate()
            return {
                "success": False,
                "action": "download",
                "cancelled": False,
                "requested": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "missing_ids": [],
                "size_estimate_before": estimate,
                "results": [],
                "index_counts": self.index.counts(),
                "error": "No confirmed PDF resources to download",
                "error_class": ErrorClass.DOWNLOAD_FAILED.value,
                "no_work": True,
            }
        already = []
        pending = []
        for r in confirmed:
            if (
                r.download_status in {DownloadStatus.DOWNLOADED.value, DownloadStatus.SKIPPED_DUPLICATE.value}
                and r.local_path
                and Path(r.local_path).exists()
            ):
                already.append(r)
            else:
                pending.append(r)
        if not pending and already:
            estimate = self.index.size_estimate()
            return {
                "success": True,
                "action": "download",
                "cancelled": False,
                "requested": 0,
                "downloaded": 0,
                "skipped": len(already),
                "failed": 0,
                "missing_ids": [],
                "size_estimate_before": estimate,
                "results": [
                    {"id": r.id, "status": "skipped", "local_path": r.local_path, "sha256": r.sha256}
                    for r in already
                ],
                "index_counts": self.index.counts(),
                "error": None,
                "error_class": None,
                "already_downloaded": len(already),
                "no_work": False,
            }
        result = await self._download_many(pending)
        result["skipped"] = int(result.get("skipped") or 0) + len(already)
        result["already_downloaded"] = len(already)
        return result

    async def resume_downloads(self) -> dict[str, Any]:
        records = [
            r for r in self.index.all_confirmed()
            if r.download_status in {
                DownloadStatus.FAILED.value,
                DownloadStatus.PARTIAL.value,
                DownloadStatus.DOWNLOADING.value,
                DownloadStatus.NOT_DOWNLOADED.value,
            }
        ]
        if not records:
            estimate = self.index.size_estimate()
            return {
                "success": False,
                "action": "download",
                "cancelled": False,
                "requested": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "missing_ids": [],
                "size_estimate_before": estimate,
                "results": [],
                "index_counts": self.index.counts(),
                "error": "No failed/partial downloads to resume",
                "error_class": ErrorClass.DOWNLOAD_FAILED.value,
                "no_work": True,
            }
        return await self._download_many(records, resume=True)

    async def _download_many(
        self,
        records: list[ResourceRecord],
        *,
        missing: list[str] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        self.cancel.install_signal_handlers()
        estimate = self.index.size_estimate()
        results: list[dict[str, Any]] = []
        sem = asyncio.Semaphore(self.concurrency)

        # follow_redirects=False: each hop must pass SSRF validation (same as HttpClient crawl path).
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        ) as client:

            async def one(record: ResourceRecord) -> None:
                if self.cancel.is_cancelled():
                    return
                async with sem:
                    results.append(await self._download_one(client, record, resume=resume))

            await asyncio.gather(*(one(r) for r in records))

        self.index.export_jsonl_and_links()
        downloaded = sum(1 for r in results if r.get("status") == "downloaded")
        skipped = sum(1 for r in results if r.get("status") in {"skipped", "skipped_duplicate"})
        failed = sum(1 for r in results if r.get("status") == "failed")
        cancelled = self.cancel.is_cancelled()
        no_work = len(records) == 0 and not missing
        return {
            "success": (not cancelled) and failed == 0 and not missing and not no_work,
            "action": "download",
            "cancelled": cancelled,
            "requested": len(records),
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "missing_ids": missing or [],
            "size_estimate_before": estimate,
            "results": results,
            "index_counts": self.index.counts(),
            "error": (
                self.cancel.reason
                if cancelled
                else ("No downloadable resources in index" if no_work else None)
            ),
            "error_class": (
                ErrorClass.CANCELLED.value
                if cancelled
                else (ErrorClass.DOWNLOAD_FAILED.value if no_work else None)
            ),
            "no_work": no_work,
        }

    async def _download_one(
        self,
        client: httpx.AsyncClient,
        record: ResourceRecord,
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        url = record.final_url or record.normalized_url or record.discovered_url
        if not url:
            record.download_status = DownloadStatus.FAILED.value
            record.error = "Missing URL"
            record.error_class = ErrorClass.INVALID_URL.value
            self.index.upsert(record)
            return {"id": record.id, "status": "failed", "error": record.error}

        # Skip valid existing downloads
        if (
            record.download_status == DownloadStatus.DOWNLOADED.value
            and record.local_path
            and Path(record.local_path).exists()
            and record.sha256
        ):
            path = Path(record.local_path)
            if path.stat().st_size > 0:
                return {"id": record.id, "status": "skipped", "local_path": str(path), "sha256": record.sha256}

        try:
            normalized = normalize_url(url, allow_private=self.allow_private)
        except Exception as exc:
            record.download_status = DownloadStatus.FAILED.value
            record.error = str(exc)
            record.error_class = ErrorClass.SSRF_BLOCKED.value
            self.index.upsert(record)
            return {"id": record.id, "status": "failed", "error": str(exc)}

        filename = record.filename or parse_content_disposition(None) or f"unknown_{record.id}.pdf"
        if not filename.lower().endswith(".pdf"):
            filename = f"{sanitize_filename(filename, fallback=record.id)}.pdf"
        filename = sanitize_filename(filename, fallback=f"unknown_{record.id}.pdf")
        target = self.paths.download_target(hostname_of(normalized) or record.hostname, filename)
        part = target.with_suffix(target.suffix + ".part")

        record.download_status = DownloadStatus.DOWNLOADING.value
        record.error = None
        self.index.upsert(record)

        existing = part.stat().st_size if resume and part.exists() else 0
        headers: dict[str, str] = {}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

        last_error = None
        for attempt in range(self.max_retries + 1):
            if self.cancel.is_cancelled():
                record.download_status = DownloadStatus.PARTIAL.value
                record.error = "cancelled"
                record.error_class = ErrorClass.CANCELLED.value
                self.index.upsert(record)
                return {"id": record.id, "status": "cancelled", "partial_path": str(part)}
            try:
                current = normalized
                redirect_chain = [current]
                max_redirects = 10
                redirects = 0
                while True:
                    host = hostname_of(current)
                    await self.rate_limiter.wait(host)
                    async with client.stream("GET", current, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            await response.aclose()
                            if not location:
                                raise RuntimeError("Redirect without Location")
                            nxt = safe_normalize(
                                location, base=current, allow_private=self.allow_private
                            )
                            if not nxt:
                                raise RuntimeError("SSRF_BLOCKED: redirect target blocked/invalid")
                            if nxt in redirect_chain:
                                raise RuntimeError("Redirect loop")
                            redirect_chain.append(nxt)
                            current = nxt
                            redirects += 1
                            if redirects > max_redirects:
                                raise RuntimeError("Too many redirects")
                            continue

                        if existing and response.status_code == 200:
                            # Server ignored Range — restart
                            existing = 0
                            part.unlink(missing_ok=True)
                        if response.status_code not in {200, 206}:
                            raise RuntimeError(f"HTTP {response.status_code}")

                        ctype = (response.headers.get("content-type") or "").lower()
                        disposition = response.headers.get("content-disposition")
                        cd_name = parse_content_disposition(disposition)
                        if cd_name:
                            filename = sanitize_filename(cd_name, fallback=filename)
                            if not filename.lower().endswith(".pdf") and "pdf" in ctype:
                                filename += ".pdf"
                            target = self.paths.download_target(host or "unknown", filename)
                            part = target.with_suffix(target.suffix + ".part")

                        mode = "ab" if existing and response.status_code == 206 else "wb"
                        if mode == "wb":
                            existing = 0
                        digest = hashlib.sha256()
                        if existing and part.exists():
                            with part.open("rb") as prev:
                                while True:
                                    chunk = prev.read(self.chunk_size)
                                    if not chunk:
                                        break
                                    digest.update(chunk)

                        validated_magic = existing > 4
                        total = existing
                        with part.open(mode) as handle:
                            async for chunk in response.aiter_bytes(self.chunk_size):
                                if self.cancel.is_cancelled():
                                    record.download_status = DownloadStatus.PARTIAL.value
                                    record.error = "cancelled"
                                    record.error_class = ErrorClass.CANCELLED.value
                                    record.content_length = total
                                    self.index.upsert(record)
                                    return {"id": record.id, "status": "cancelled", "partial_path": str(part)}
                                if not validated_magic:
                                    if total == 0 and not chunk.startswith(PDF_MAGIC) and "pdf" in ctype:
                                        # Some servers prepend BOM/whitespace
                                        if not chunk.lstrip().startswith(PDF_MAGIC):
                                            raise RuntimeError("PDF_VALIDATION_FAILED: missing %PDF- magic")
                                    elif total == 0 and not chunk.lstrip().startswith(PDF_MAGIC):
                                        raise RuntimeError("PDF_VALIDATION_FAILED: not a PDF")
                                    validated_magic = True
                                handle.write(chunk)
                                digest.update(chunk)
                                total += len(chunk)

                        sha = digest.hexdigest()
                        # Dedup by content hash
                        dup = self.index.find_by_sha256(sha)
                        if dup and dup.id != record.id and dup.local_path and Path(dup.local_path).exists():
                            part.unlink(missing_ok=True)
                            record.sha256 = sha
                            record.local_path = dup.local_path
                            record.download_status = DownloadStatus.SKIPPED_DUPLICATE.value
                            record.content_length = total
                            record.mime_type = "application/pdf"
                            record.verified_at = utc_now_iso()
                            self.index.upsert(record)
                            return {
                                "id": record.id,
                                "status": "skipped_duplicate",
                                "sha256": sha,
                                "local_path": dup.local_path,
                                "duplicate_of": dup.id,
                            }

                        part.replace(target)
                        record.sha256 = sha
                        record.local_path = str(target)
                        record.download_status = DownloadStatus.DOWNLOADED.value
                        record.content_length = total
                        record.mime_type = "application/pdf"
                        record.filename = target.name
                        record.final_url = current
                        record.verified_at = utc_now_iso()
                        record.error = None
                        record.error_class = None
                        self.index.upsert(record)
                        return {
                            "id": record.id,
                            "status": "downloaded",
                            "sha256": sha,
                            "local_path": str(target),
                            "bytes": total,
                        }
            except Exception as exc:
                last_error = str(exc)
                continue

        record.download_status = DownloadStatus.FAILED.value
        record.error = last_error or "download failed"
        record.error_class = (
            ErrorClass.SSRF_BLOCKED.value
            if last_error and "SSRF_BLOCKED" in last_error
            else (
                ErrorClass.PDF_VALIDATION_FAILED.value
                if last_error and "PDF_VALIDATION" in last_error
                else ErrorClass.DOWNLOAD_FAILED.value
            )
        )
        self.index.upsert(record)
        return {"id": record.id, "status": "failed", "error": record.error}
