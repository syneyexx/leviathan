"""Hugging Face dataset download with resumable 429 handling."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

from Data.modules.common.atomic import atomic_write_bytes, ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.retry import RetryPolicy, compute_backoff_seconds
from Data.modules.common.secrets import redact_secrets

from .types import DatasetError


CancelCheck = Callable[[], bool]
SleepFn = Callable[[float], None]
ProgressCb = Callable[[dict[str, Any]], None]


@dataclass
class HfDownloadCheckpoint:
    repository_id: str
    revision: str = "main"
    filename: str = ""
    bytes_downloaded: int = 0
    total_bytes: int | None = None
    etag: str | None = None
    attempts: int = 0
    last_status: int | None = None
    rate_limit_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "repositoryId": self.repository_id,
            "revision": self.revision,
            "filename": self.filename,
            "bytesDownloaded": self.bytes_downloaded,
            "totalBytes": self.total_bytes,
            "etag": self.etag,
            "attempts": self.attempts,
            "lastStatus": self.last_status,
            "rateLimitEvents": self.rate_limit_events,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HfDownloadCheckpoint":
        return cls(
            repository_id=str(data.get("repositoryId") or data.get("repository_id") or ""),
            revision=str(data.get("revision") or "main"),
            filename=str(data.get("filename") or ""),
            bytes_downloaded=int(data.get("bytesDownloaded") or data.get("bytes_downloaded") or 0),
            total_bytes=data.get("totalBytes") if data.get("totalBytes") is not None else data.get("total_bytes"),
            etag=data.get("etag"),
            attempts=int(data.get("attempts") or 0),
            last_status=data.get("lastStatus") if data.get("lastStatus") is not None else data.get("last_status"),
            rate_limit_events=int(data.get("rateLimitEvents") or data.get("rate_limit_events") or 0),
        )


@dataclass
class HfDownloadResult:
    path: Path
    content_hash: str
    byte_size: int
    checkpoint: HfDownloadCheckpoint
    url: str
    headers: dict[str, str] = field(default_factory=dict)


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _auth_headers(token: str | None) -> dict[str, str]:
    tok = (
        token
        or os.getenv("LEVIATHAN_HF_TOKEN")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or ""
    ).strip()
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}"}


def resolve_hf_file_url(repository_id: str, revision: str, filename: str) -> str:
    repo = repository_id.strip().strip("/")
    rev = quote(revision.strip() or "main", safe="")
    # Keep nested paths but reject traversal
    parts = Path(filename.replace("\\", "/")).parts
    if ".." in parts or filename.startswith("/"):
        raise DatasetError("Unsafe Hugging Face filename", code="path_traversal", http_status=400)
    file_path = "/".join(quote(p, safe="") for p in parts)
    return f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{file_path}"


def list_hf_dataset_files(
    repository_id: str,
    *,
    revision: str = "main",
    token: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    repo = repository_id.strip().strip("/")
    rev = quote(revision.strip() or "main", safe="")
    url = f"https://huggingface.co/api/datasets/{repo}/tree/{rev}"
    owns = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        response = client.get(url, headers=_auth_headers(token))
        if response.status_code == 404:
            raise DatasetError(
                f"Dataset not found: {repository_id}",
                code="hf_not_found",
                http_status=404,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise DatasetError("Unexpected HF tree response", code="hf_api_error", http_status=502)
        return [item for item in data if isinstance(item, dict)]
    finally:
        if owns:
            client.close()


def download_hf_file(
    *,
    repository_id: str,
    filename: str,
    dest_path: Path,
    revision: str = "main",
    token: str | None = None,
    checkpoint: HfDownloadCheckpoint | None = None,
    policy: RetryPolicy | None = None,
    cancel_check: CancelCheck | None = None,
    sleep_fn: SleepFn | None = None,
    progress_cb: ProgressCb | None = None,
    client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
) -> HfDownloadResult:
    """Download a single file from a HF dataset repo with resume + 429 backoff.

    Resumes via HTTP Range when ``dest_path`` partial exists / checkpoint bytes > 0.
    """
    policy = policy or RetryPolicy(max_attempts=8, base_seconds=1.0, max_seconds=60.0)
    sleep_fn = sleep_fn or time.sleep
    cancel_check = cancel_check or (lambda: False)
    cp = checkpoint or HfDownloadCheckpoint(
        repository_id=repository_id, revision=revision, filename=filename
    )
    cp.repository_id = repository_id
    cp.revision = revision
    cp.filename = filename

    url = resolve_hf_file_url(repository_id, revision, filename)
    ensure_dir(dest_path.parent)
    partial = dest_path.with_suffix(dest_path.suffix + ".partial")

    # Resume from partial file if present
    existing = 0
    if partial.exists():
        existing = partial.stat().st_size
    elif dest_path.exists() and cp.bytes_downloaded > 0:
        # Already complete?
        digest = sha256_file(dest_path)
        return HfDownloadResult(
            path=dest_path,
            content_hash=digest,
            byte_size=dest_path.stat().st_size,
            checkpoint=cp,
            url=url,
        )
    if cp.bytes_downloaded and existing and existing != cp.bytes_downloaded:
        # Prefer on-disk partial size
        cp.bytes_downloaded = existing
    elif existing and not cp.bytes_downloaded:
        cp.bytes_downloaded = existing

    owns_client = client is None
    client = client or httpx.Client(timeout=None, follow_redirects=True, transport=transport)
    headers_base = _auth_headers(token)

    try:
        attempt = 0
        while attempt < policy.max_attempts:
            if cancel_check():
                raise DatasetError("Download cancelled", code="cancelled", http_status=409)
            cp.attempts = attempt + 1
            headers = dict(headers_base)
            if cp.bytes_downloaded > 0:
                headers["Range"] = f"bytes={cp.bytes_downloaded}-"

            try:
                with client.stream("GET", url, headers=headers) as response:
                    cp.last_status = response.status_code
                    if response.status_code == 429:
                        cp.rate_limit_events += 1
                        retry_after = _parse_retry_after(response)
                        delay = compute_backoff_seconds(
                            attempt, policy=policy, retry_after=retry_after
                        )
                        if progress_cb:
                            progress_cb(
                                {
                                    "phase": "rate_limited",
                                    "attempt": attempt,
                                    "sleepSeconds": delay,
                                    "retryAfter": retry_after,
                                    "checkpoint": cp.to_dict(),
                                }
                            )
                        attempt += 1
                        sleep_fn(delay)
                        continue

                    if response.status_code in {500, 502, 503, 504}:
                        delay = compute_backoff_seconds(attempt, policy=policy)
                        attempt += 1
                        sleep_fn(delay)
                        continue

                    if response.status_code == 404:
                        raise DatasetError(
                            f"HF file not found: {filename}",
                            code="hf_not_found",
                            http_status=404,
                        )

                    if response.status_code not in {200, 206}:
                        body = ""
                        try:
                            body = response.read().decode("utf-8", errors="replace")[:300]
                        except Exception:  # noqa: BLE001
                            pass
                        raise DatasetError(
                            redact_secrets(f"HF download failed HTTP {response.status_code}: {body}"),
                            code="hf_download_failed",
                            http_status=502,
                        )

                    # If server ignored Range and returned 200, restart file
                    if response.status_code == 200 and cp.bytes_downloaded > 0:
                        cp.bytes_downloaded = 0
                        if partial.exists():
                            partial.unlink()

                    total_header = response.headers.get("content-length")
                    content_range = response.headers.get("content-range")
                    if content_range and "/" in content_range:
                        try:
                            cp.total_bytes = int(content_range.split("/")[-1])
                        except ValueError:
                            pass
                    elif total_header and total_header.isdigit():
                        # For 206, content-length is remaining; for 200 it's full
                        if response.status_code == 200:
                            cp.total_bytes = int(total_header)
                        elif cp.total_bytes is None:
                            cp.total_bytes = cp.bytes_downloaded + int(total_header)

                    cp.etag = response.headers.get("etag") or cp.etag
                    mode = "ab" if cp.bytes_downloaded > 0 else "wb"
                    with partial.open(mode) as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if cancel_check():
                                raise DatasetError(
                                    "Download cancelled", code="cancelled", http_status=409
                                )
                            if not chunk:
                                continue
                            handle.write(chunk)
                            cp.bytes_downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(
                                    {
                                        "phase": "downloading",
                                        "bytesDownloaded": cp.bytes_downloaded,
                                        "totalBytes": cp.total_bytes,
                                        "checkpoint": cp.to_dict(),
                                    }
                                )

                    # Success for this attempt
                    partial.replace(dest_path)
                    digest = sha256_file(dest_path)
                    size = dest_path.stat().st_size
                    cp.bytes_downloaded = size
                    if progress_cb:
                        progress_cb(
                            {
                                "phase": "completed",
                                "bytesDownloaded": size,
                                "contentHash": digest,
                                "checkpoint": cp.to_dict(),
                            }
                        )
                    return HfDownloadResult(
                        path=dest_path,
                        content_hash=digest,
                        byte_size=size,
                        checkpoint=cp,
                        url=url,
                        headers={k: v for k, v in response.headers.items() if k.lower() != "authorization"},
                    )
            except DatasetError:
                raise
            except httpx.HTTPError as exc:
                delay = compute_backoff_seconds(attempt, policy=policy)
                attempt += 1
                if attempt >= policy.max_attempts:
                    raise DatasetError(
                        redact_secrets(f"HF download error: {exc}"),
                        code="hf_download_failed",
                        http_status=502,
                    ) from exc
                sleep_fn(delay)

        raise DatasetError(
            f"HF download exhausted retries after {policy.max_attempts} attempts "
            f"(429 events={cp.rate_limit_events})",
            code="hf_rate_limited",
            http_status=429,
        )
    finally:
        if owns_client:
            client.close()


def write_bytes_atomic(path: Path, data: bytes) -> str:
    atomic_write_bytes(path, data)
    return sha256_file(path)
