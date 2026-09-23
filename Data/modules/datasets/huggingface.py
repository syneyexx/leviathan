"""Hugging Face dataset download: recursive discovery, resumable parallel shards."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.retry import RetryPolicy, compute_backoff_seconds
from Data.modules.common.secrets import redact_secrets

from .offline import disk_free_bytes
from .types import DatasetError


CancelCheck = Callable[[], bool]
SleepFn = Callable[[float], None]
ProgressCb = Callable[[dict[str, Any]], None]


# --- Configuration ---------------------------------------------------------

def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def hf_download_chunk_bytes() -> int:
    """Network read size. Default 16 MiB; bounded 4–64 MiB."""
    mb = _env_int("LEVIATHAN_HF_DOWNLOAD_CHUNK_MB", 16, minimum=4, maximum=64)
    return mb * 1024 * 1024


def hf_download_workers() -> int:
    """Bounded concurrent file downloads. Default 6; hard-capped at 16."""
    return _env_int("LEVIATHAN_HF_DOWNLOAD_WORKERS", 6, minimum=1, maximum=16)


def hf_parquet_batch_rows() -> int:
    return _env_int("LEVIATHAN_HF_PARQUET_BATCH_ROWS", 16_384, minimum=512, maximum=65_536)


# --- File classification ---------------------------------------------------

class HfFileKind(str, Enum):
    DATA = "DATA"
    METADATA = "METADATA"
    IGNORED = "IGNORED"
    UNSUPPORTED_DATA = "UNSUPPORTED_DATA"


DATA_EXTENSIONS = {
    ".parquet",
    ".jsonl",
    ".ndjson",
    ".json",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".markdown",
}

# Formats that look like dataset data but we do not materialize yet.
UNSUPPORTED_DATA_EXTENSIONS = {
    ".arrow",
    ".feather",
    ".orc",
    ".avro",
    ".tfrecord",
    ".bin",
    ".pt",
    ".pth",
    ".safetensors",
    ".npy",
}

METADATA_BASENAMES = {
    "readme",
    "readme.md",
    "readme.txt",
    "license",
    "license.md",
    "license.txt",
    "licence",
    "licence.md",
    "citation.cff",
    "citations.bib",
    ".gitattributes",
    ".gitignore",
    "dataset_infos.json",
    "dataset_info.json",
    "data_cards.json",
    "datapackage.json",
}

METADATA_DIR_HINTS = {".git", ".huggingface", "docs", "doc", "images", "assets", "media"}

# Paths under these dirs with image/video extensions are documentation, not rows.
DOC_MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".webm",
}


def normalize_repo_path(filename: str) -> str:
    """Normalize a HF relative path; reject traversal / absolute / null bytes."""
    text = (filename or "").replace("\\", "/").strip()
    if not text:
        raise DatasetError("Empty Hugging Face path", code="path_traversal", http_status=400)
    if "\x00" in text:
        raise DatasetError("Null byte in Hugging Face path", code="path_traversal", http_status=400)
    if text.startswith("/") or text.startswith("~"):
        raise DatasetError("Absolute Hugging Face path refused", code="path_traversal", http_status=400)
    if len(text) >= 2 and text[1] == ":":
        raise DatasetError("Drive path refused", code="path_traversal", http_status=400)
    parts = Path(text).parts
    if ".." in parts or any(p in {"", "."} and False for p in parts):
        raise DatasetError("Unsafe Hugging Face filename", code="path_traversal", http_status=400)
    if ".." in parts:
        raise DatasetError("Unsafe Hugging Face filename", code="path_traversal", http_status=400)
    # Rebuild without Windows drive / UNC
    cleaned = "/".join(p for p in parts if p not in {".", ""})
    if not cleaned:
        raise DatasetError("Empty Hugging Face path", code="path_traversal", http_status=400)
    return cleaned


def classify_hf_file(path: str) -> HfFileKind:
    """Deterministic classification of a repository-relative path."""
    rel = normalize_repo_path(path)
    lower = rel.lower()
    name = Path(lower).name
    parts = PurePosixParts(lower)
    suffix = Path(lower).suffix

    if name.startswith(".") and name not in {".gitattributes", ".gitignore"}:
        return HfFileKind.IGNORED
    if name in METADATA_BASENAMES or any(name.startswith(b) for b in ("license-", "licence-")):
        return HfFileKind.METADATA
    if parts and parts[0] in METADATA_DIR_HINTS:
        if suffix in DOC_MEDIA_EXTENSIONS or suffix not in DATA_EXTENSIONS:
            return HfFileKind.METADATA
        # docs/*.md is documentation; data under docs that looks like corpus is rare —
        # treat markdown/json under docs/ as METADATA.
        if suffix in {".md", ".markdown", ".txt", ".json"}:
            return HfFileKind.METADATA

    # Root-level README / LICENSE already covered; root dataset card yaml
    if name in {"readme.md", "dataset_card.md", "card.yaml", "card.yml"}:
        return HfFileKind.METADATA

    if suffix in DATA_EXTENSIONS:
        # Root README.md already caught; corpus .md under data/ remains DATA.
        if suffix in {".md", ".markdown"} and Path(lower).parent.as_posix() in {".", ""}:
            return HfFileKind.METADATA
        return HfFileKind.DATA

    if suffix in UNSUPPORTED_DATA_EXTENSIONS:
        # Heuristic: under data/train/test → likely dataset shard we cannot parse.
        if any(seg in {"data", "train", "test", "validation", "val", "dev", "shards"} for seg in parts):
            return HfFileKind.UNSUPPORTED_DATA
        return HfFileKind.IGNORED

    if suffix in DOC_MEDIA_EXTENSIONS:
        return HfFileKind.METADATA

    return HfFileKind.IGNORED


def PurePosixParts(path: str) -> tuple[str, ...]:
    return tuple(p for p in path.replace("\\", "/").split("/") if p and p != ".")


def infer_split_from_path(path: str) -> str | None:
    lower = path.replace("\\", "/").lower()
    parts = PurePosixParts(lower)
    name = Path(lower).stem
    for candidate in ("train", "validation", "test", "dev", "val"):
        if candidate in parts:
            if candidate == "val":
                return "validation"
            if candidate == "dev":
                return "validation"
            return candidate
        if name == candidate or name.startswith(f"{candidate}-") or name.startswith(f"{candidate}_"):
            if candidate == "val":
                return "validation"
            if candidate == "dev":
                return "validation"
            return candidate
        if f"/{candidate}/" in f"/{lower}/" or f"/{candidate}-" in f"/{lower}":
            if candidate == "val":
                return "validation"
            if candidate == "dev":
                return "validation"
            return candidate
    return None


def infer_config_from_path(path: str) -> str | None:
    """Best-effort config/subset from first non-generic directory segment."""
    parts = PurePosixParts(path.replace("\\", "/"))
    generic = {
        "data",
        "dataset",
        "datasets",
        "train",
        "test",
        "validation",
        "val",
        "dev",
        "shards",
        "raw",
        "processed",
        "default",
    }
    for part in parts[:-1]:
        low = part.lower()
        if low in generic:
            continue
        if part.startswith("."):
            continue
        return part
    return None


# --- Checkpoints / results -------------------------------------------------

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
    content_hash: str | None = None
    completed: bool = False

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
            "contentHash": self.content_hash,
            "completed": self.completed,
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
            content_hash=data.get("contentHash") or data.get("content_hash"),
            completed=bool(data.get("completed") or False),
        )


@dataclass
class HfDownloadResult:
    path: Path
    content_hash: str
    byte_size: int
    checkpoint: HfDownloadCheckpoint
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class HfRepoFile:
    path: str
    size: int | None = None
    kind: HfFileKind = HfFileKind.DATA
    lfs_oid: str | None = None
    blob_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "kind": self.kind.value,
            "lfsOid": self.lfs_oid,
            "blobId": self.blob_id,
            "split": infer_split_from_path(self.path),
            "config": infer_config_from_path(self.path),
        }


@dataclass
class HfRepoPlan:
    repository_id: str
    revision: str
    resolved_revision: str | None
    files: list[HfRepoFile]
    classification: dict[str, str]
    data_files: list[HfRepoFile]
    unsupported_files: list[HfRepoFile]
    metadata_files: list[HfRepoFile]
    bytes_total: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repositoryId": self.repository_id,
            "revision": self.revision,
            "resolvedRevision": self.resolved_revision,
            "filesTotal": len(self.data_files),
            "bytesTotal": self.bytes_total,
            "classification": dict(self.classification),
            "dataFiles": [f.to_dict() for f in self.data_files],
            "unsupportedFiles": [f.to_dict() for f in self.unsupported_files],
            "metadataFiles": [f.to_dict() for f in self.metadata_files],
            "discoveredFiles": len(self.files),
        }


@dataclass
class HfFileState:
    path: str
    size: int | None = None
    downloaded: int = 0
    status: str = "pending"  # pending|downloading|complete|failed|partial
    hash: str | None = None
    etag: str | None = None
    lfs_oid: str | None = None
    retry_count: int = 0
    last_http_status: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "downloaded": self.downloaded,
            "status": self.status,
            "hash": self.hash,
            "etag": self.etag,
            "lfsOid": self.lfs_oid,
            "retryCount": self.retry_count,
            "lastHttpStatus": self.last_http_status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HfFileState":
        return cls(
            path=str(data.get("path") or ""),
            size=data.get("size"),
            downloaded=int(data.get("downloaded") or 0),
            status=str(data.get("status") or "pending"),
            hash=data.get("hash"),
            etag=data.get("etag"),
            lfs_oid=data.get("lfsOid") or data.get("lfs_oid"),
            retry_count=int(data.get("retryCount") or data.get("retry_count") or 0),
            last_http_status=data.get("lastHttpStatus") if data.get("lastHttpStatus") is not None else data.get("last_http_status"),
            error=data.get("error"),
        )


@dataclass
class HfRepoManifest:
    repository_id: str
    revision: str
    resolved_revision: str | None = None
    files_total: int = 0
    bytes_total: int | None = None
    files_completed: int = 0
    files_failed: int = 0
    bytes_downloaded: int = 0
    files: dict[str, HfFileState] = field(default_factory=dict)
    classification: dict[str, str] = field(default_factory=dict)
    phase: str = "planned"
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repositoryId": self.repository_id,
            "revision": self.revision,
            "resolvedRevision": self.resolved_revision,
            "filesTotal": self.files_total,
            "bytesTotal": self.bytes_total,
            "filesCompleted": self.files_completed,
            "filesFailed": self.files_failed,
            "bytesDownloaded": self.bytes_downloaded,
            "files": {k: v.to_dict() for k, v in sorted(self.files.items())},
            "classification": dict(self.classification),
            "phase": self.phase,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HfRepoManifest":
        files_raw = data.get("files") or {}
        files: dict[str, HfFileState] = {}
        if isinstance(files_raw, dict):
            for key, val in files_raw.items():
                if isinstance(val, dict):
                    files[str(key)] = HfFileState.from_dict(val)
        elif isinstance(files_raw, list):
            for val in files_raw:
                if isinstance(val, dict) and val.get("path"):
                    files[str(val["path"])] = HfFileState.from_dict(val)
        return cls(
            repository_id=str(data.get("repositoryId") or data.get("repository_id") or ""),
            revision=str(data.get("revision") or "main"),
            resolved_revision=data.get("resolvedRevision") or data.get("resolved_revision"),
            files_total=int(data.get("filesTotal") or data.get("files_total") or len(files)),
            bytes_total=data.get("bytesTotal") if data.get("bytesTotal") is not None else data.get("bytes_total"),
            files_completed=int(data.get("filesCompleted") or data.get("files_completed") or 0),
            files_failed=int(data.get("filesFailed") or data.get("files_failed") or 0),
            bytes_downloaded=int(data.get("bytesDownloaded") or data.get("bytes_downloaded") or 0),
            files=files,
            classification=dict(data.get("classification") or {}),
            phase=str(data.get("phase") or "planned"),
            updated_at=float(data.get("updatedAt") or data.get("updated_at") or time.time()),
        )

    def recompute(self) -> None:
        completed = 0
        failed = 0
        downloaded = 0
        for state in self.files.values():
            if state.status == "complete":
                completed += 1
                downloaded += int(state.size or state.downloaded or 0)
            else:
                downloaded += int(state.downloaded or 0)
                if state.status == "failed":
                    failed += 1
        self.files_completed = completed
        self.files_failed = failed
        self.bytes_downloaded = downloaded
        self.updated_at = time.time()


class RateLimitCoordinator:
    """Shared 429 gate so parallel workers do not independently hammer retries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._resume_at = 0.0
        self.events = 0

    def wait_if_needed(self, sleep_fn: SleepFn, cancel_check: CancelCheck) -> None:
        while True:
            if cancel_check():
                raise DatasetError("Download cancelled", code="cancelled", http_status=409)
            with self._lock:
                delay = self._resume_at - time.monotonic()
            if delay <= 0:
                return
            sleep_fn(min(delay, 1.0))

    def register_429(self, retry_after: float | None, attempt: int, policy: RetryPolicy) -> float:
        delay = compute_backoff_seconds(attempt, policy=policy, retry_after=retry_after)
        with self._lock:
            self.events += 1
            self._resume_at = max(self._resume_at, time.monotonic() + delay)
        return delay


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


def resolve_hf_token(token: str | None = None) -> str | None:
    tok = (
        token
        or os.getenv("LEVIATHAN_HF_TOKEN")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or ""
    ).strip()
    return tok or None


def resolve_hf_file_url(repository_id: str, revision: str, filename: str) -> str:
    repo = repository_id.strip().strip("/")
    rev = quote(revision.strip() or "main", safe="")
    safe_name = normalize_repo_path(filename)
    parts = Path(safe_name).parts
    file_path = "/".join(quote(p, safe="") for p in parts)
    return f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{file_path}"


def safe_dest_path(raw_root: Path, relative: str) -> Path:
    """Map a repository-relative path under raw_root without traversal."""
    from Data.modules.common.paths import PathEscapeError, safe_join

    rel = normalize_repo_path(relative)
    try:
        return safe_join(raw_root, *PurePosixParts(rel))
    except PathEscapeError as exc:
        raise DatasetError(str(exc), code="path_traversal", http_status=400) from exc


# --- Discovery -------------------------------------------------------------

def list_hf_dataset_files(
    repository_id: str,
    *,
    revision: str = "main",
    token: str | None = None,
    client: httpx.Client | None = None,
    recursive: bool = True,
) -> list[dict[str, Any]]:
    """List repository files. Prefer huggingface_hub recursive tree when available."""
    repo = repository_id.strip().strip("/")
    rev = revision.strip() or "main"
    tok = resolve_hf_token(token)

    if recursive:
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=tok)
            items: list[dict[str, Any]] = []
            for entry in api.list_repo_tree(
                repo_id=repo,
                repo_type="dataset",
                revision=rev,
                recursive=True,
                expand=True,
            ):
                # RepoFolder vs RepoFile
                path = getattr(entry, "path", None) or getattr(entry, "rfilename", None)
                if path is None:
                    continue
                kind = getattr(entry, "type", None) or entry.__class__.__name__
                if str(kind).lower() in {"folder", "repofolder"} or type(entry).__name__ == "RepoFolder":
                    continue
                size = getattr(entry, "size", None)
                lfs = getattr(entry, "lfs", None)
                lfs_oid = None
                if isinstance(lfs, dict):
                    lfs_oid = lfs.get("oid") or lfs.get("sha256")
                    if size is None:
                        size = lfs.get("size")
                items.append(
                    {
                        "path": str(path),
                        "type": "file",
                        "size": int(size) if size is not None else None,
                        "lfsOid": lfs_oid,
                        "blobId": getattr(entry, "blob_id", None) or getattr(entry, "oid", None),
                    }
                )
            items.sort(key=lambda x: str(x.get("path") or ""))
            return items
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            # Fall through to HTTP tree API
            if "404" in str(exc) or getattr(exc, "response", None) is not None:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404:
                    raise DatasetError(
                        f"Dataset not found: {repository_id}",
                        code="hf_not_found",
                        http_status=404,
                    ) from exc
            # Continue to legacy HTTP listing (non-recursive fallback + recursive walk)

    return _list_hf_tree_http(repo, revision=rev, token=tok, client=client, recursive=recursive)


def _list_hf_tree_http(
    repository_id: str,
    *,
    revision: str,
    token: str | None,
    client: httpx.Client | None,
    recursive: bool,
) -> list[dict[str, Any]]:
    rev = quote(revision.strip() or "main", safe="")
    owns = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    headers = _auth_headers(token)
    try:
        collected: list[dict[str, Any]] = []

        def walk(prefix: str = "") -> None:
            url = f"https://huggingface.co/api/datasets/{repository_id}/tree/{rev}"
            if prefix:
                url = f"{url}/{quote(prefix, safe='/')}"
            params = {"recursive": "1"} if recursive and not prefix else None
            response = client.get(url, headers=headers, params=params)
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
            for item in data:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or item.get("rfilename") or "")
                typ = str(item.get("type") or "file")
                if typ == "directory" and recursive and not params:
                    walk(path)
                    continue
                if typ == "directory":
                    continue
                if not path:
                    continue
                collected.append(
                    {
                        "path": path,
                        "type": "file",
                        "size": item.get("size"),
                        "lfsOid": (item.get("lfs") or {}).get("oid") if isinstance(item.get("lfs"), dict) else None,
                        "blobId": item.get("oid") or item.get("blob_id"),
                    }
                )

        walk()
        collected.sort(key=lambda x: str(x.get("path") or ""))
        return collected
    finally:
        if owns:
            client.close()


def discover_hf_repository(
    repository_id: str,
    *,
    revision: str = "main",
    token: str | None = None,
    client: httpx.Client | None = None,
) -> HfRepoPlan:
    """Resolve repo, recursively enumerate, classify, and build a download plan."""
    repo = repository_id.strip().strip("/")
    rev = revision.strip() or "main"
    resolved: str | None = None
    tok = resolve_hf_token(token)
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=tok)
        info = api.dataset_info(repo_id=repo, revision=rev)
        resolved = getattr(info, "sha", None) or getattr(info, "commit_hash", None)
    except Exception:  # noqa: BLE001
        resolved = None

    raw_files = list_hf_dataset_files(repo, revision=rev, token=token, client=client, recursive=True)
    files: list[HfRepoFile] = []
    classification: dict[str, str] = {}
    data_files: list[HfRepoFile] = []
    unsupported: list[HfRepoFile] = []
    metadata: list[HfRepoFile] = []

    for item in raw_files:
        path = str(item.get("path") or "")
        if not path:
            continue
        try:
            path = normalize_repo_path(path)
        except DatasetError:
            continue
        kind = classify_hf_file(path)
        size = item.get("size")
        entry = HfRepoFile(
            path=path,
            size=int(size) if size is not None else None,
            kind=kind,
            lfs_oid=item.get("lfsOid"),
            blob_id=str(item["blobId"]) if item.get("blobId") else None,
        )
        files.append(entry)
        classification[path] = kind.value
        if kind == HfFileKind.DATA:
            data_files.append(entry)
        elif kind == HfFileKind.UNSUPPORTED_DATA:
            unsupported.append(entry)
        elif kind == HfFileKind.METADATA:
            metadata.append(entry)

    data_files.sort(key=lambda f: f.path)
    sizes = [f.size for f in data_files if f.size is not None]
    bytes_total = sum(sizes) if sizes and len(sizes) == len(data_files) else (sum(sizes) if sizes else None)
    if bytes_total is not None and len(sizes) < len(data_files):
        # Partial size knowledge — still report known sum as lower bound via None? Prefer known sum.
        pass

    return HfRepoPlan(
        repository_id=repo,
        revision=rev,
        resolved_revision=str(resolved) if resolved else None,
        files=files,
        classification=classification,
        data_files=data_files,
        unsupported_files=unsupported,
        metadata_files=metadata,
        bytes_total=bytes_total,
    )


def build_manifest_from_plan(plan: HfRepoPlan, *, existing: HfRepoManifest | None = None) -> HfRepoManifest:
    manifest = existing or HfRepoManifest(
        repository_id=plan.repository_id,
        revision=plan.revision,
        resolved_revision=plan.resolved_revision,
    )
    manifest.repository_id = plan.repository_id
    manifest.revision = plan.revision
    if plan.resolved_revision:
        manifest.resolved_revision = plan.resolved_revision
    manifest.classification = dict(plan.classification)
    manifest.files_total = len(plan.data_files)
    manifest.bytes_total = plan.bytes_total
    for entry in plan.data_files:
        prior = manifest.files.get(entry.path)
        if prior and prior.status == "complete":
            # Keep verified complete entries
            if entry.size is not None:
                prior.size = entry.size
            continue
        if prior:
            prior.size = entry.size if entry.size is not None else prior.size
            prior.lfs_oid = entry.lfs_oid or prior.lfs_oid
            continue
        manifest.files[entry.path] = HfFileState(
            path=entry.path,
            size=entry.size,
            status="pending",
            lfs_oid=entry.lfs_oid,
        )
    # Drop entries no longer in plan (revision change)
    keep = {f.path for f in plan.data_files}
    for path in list(manifest.files.keys()):
        if path not in keep:
            del manifest.files[path]
    manifest.recompute()
    manifest.phase = "planned"
    return manifest


def write_repo_manifest(path: Path, manifest: HfRepoManifest) -> None:
    ensure_dir(path.parent)
    atomic_write_text(path, json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")


def load_repo_manifest(path: Path) -> HfRepoManifest | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return HfRepoManifest.from_dict(data)


def disk_preflight_for_download(
    *,
    target_dir: Path,
    bytes_total: int | None,
    bytes_already: int = 0,
    materialize_overhead_ratio: float = 0.15,
    reserve_bytes: int = 512 * 1024 * 1024,
) -> dict[str, Any]:
    """Fail before download when free disk is insufficient."""
    ensure_dir(target_dir)
    free = disk_free_bytes(target_dir)
    remaining = max(0, (bytes_total or 0) - max(0, bytes_already)) if bytes_total is not None else None
    if remaining is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": "bytes_total_unknown",
            "diskFreeBytes": free,
            "targetPath": str(target_dir),
        }
    overhead = int(remaining * materialize_overhead_ratio)
    required = remaining + overhead + reserve_bytes
    ok = free is None or free >= required
    result = {
        "ok": ok,
        "requiredBytes": required,
        "availableBytes": free,
        "missingBytes": None if free is None else max(0, required - free),
        "datasetBytes": bytes_total,
        "remainingDownloadBytes": remaining,
        "materializationOverheadBytes": overhead,
        "reserveBytes": reserve_bytes,
        "targetPath": str(target_dir),
    }
    if not ok:
        raise DatasetError(
            (
                f"Insufficient disk space for Hugging Face import: "
                f"required={required} available={free} missing={result['missingBytes']} "
                f"datasetBytes={bytes_total} target={target_dir}"
            ),
            code="insufficient_disk",
            http_status=507,
        )
    return result


# --- Single-file download --------------------------------------------------

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
    chunk_size: int | None = None,
    rate_limit: RateLimitCoordinator | None = None,
    expected_size: int | None = None,
    expected_hash: str | None = None,
) -> HfDownloadResult:
    """Download a single file from a HF dataset repo with resume + 429 backoff.

    Resumes via HTTP Range when ``dest_path`` partial exists / checkpoint bytes > 0.
    Hashes incrementally while streaming when starting from byte 0.
    """
    policy = policy or RetryPolicy(max_attempts=8, base_seconds=1.0, max_seconds=60.0)
    sleep_fn = sleep_fn or time.sleep
    cancel_check = cancel_check or (lambda: False)
    chunk_size = chunk_size or hf_download_chunk_bytes()
    rate_limit = rate_limit or RateLimitCoordinator()
    safe_name = normalize_repo_path(filename)
    cp = checkpoint or HfDownloadCheckpoint(
        repository_id=repository_id, revision=revision, filename=safe_name
    )
    cp.repository_id = repository_id
    cp.revision = revision
    cp.filename = safe_name
    if expected_size is not None:
        cp.total_bytes = expected_size

    url = resolve_hf_file_url(repository_id, revision, safe_name)
    ensure_dir(dest_path.parent)
    partial = Path(str(dest_path) + ".partial")

    # Already complete and verified?
    if dest_path.exists() and not partial.exists():
        size = dest_path.stat().st_size
        size_ok = expected_size is None or size == expected_size
        if size_ok and size > 0:
            digest = expected_hash or sha256_file(dest_path)
            if expected_hash and digest != expected_hash:
                dest_path.unlink(missing_ok=True)
            else:
                cp.bytes_downloaded = size
                cp.total_bytes = size
                cp.content_hash = digest
                cp.completed = True
                return HfDownloadResult(
                    path=dest_path,
                    content_hash=digest,
                    byte_size=size,
                    checkpoint=cp,
                    url=url,
                )

    existing = 0
    if partial.exists():
        existing = partial.stat().st_size
    if cp.bytes_downloaded and existing and existing != cp.bytes_downloaded:
        cp.bytes_downloaded = existing
    elif existing and not cp.bytes_downloaded:
        cp.bytes_downloaded = existing

    owns_client = client is None
    client = client or httpx.Client(timeout=None, follow_redirects=True, transport=transport)
    headers_base = _auth_headers(token)
    hasher: hashlib._Hash | None = None
    # Incremental hash only when starting from zero; resume requires final file hash.
    if cp.bytes_downloaded == 0:
        hasher = hashlib.sha256()

    try:
        attempt = 0
        while attempt < policy.max_attempts:
            if cancel_check():
                raise DatasetError("Download cancelled", code="cancelled", http_status=409)
            rate_limit.wait_if_needed(sleep_fn, cancel_check)
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
                        delay = rate_limit.register_429(retry_after, attempt, policy)
                        if progress_cb:
                            progress_cb(
                                {
                                    "phase": "rate_limited",
                                    "attempt": attempt,
                                    "sleepSeconds": delay,
                                    "retryAfter": retry_after,
                                    "checkpoint": cp.to_dict(),
                                    "filename": safe_name,
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
                            f"HF file not found: {safe_name}",
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

                    # Server ignored Range → restart partial safely (do NOT append).
                    if response.status_code == 200 and cp.bytes_downloaded > 0:
                        cp.bytes_downloaded = 0
                        if partial.exists():
                            partial.unlink()
                        hasher = hashlib.sha256()

                    total_header = response.headers.get("content-length")
                    content_range = response.headers.get("content-range")
                    if content_range and "/" in content_range:
                        try:
                            cp.total_bytes = int(content_range.split("/")[-1])
                        except ValueError:
                            pass
                    elif total_header and total_header.isdigit():
                        if response.status_code == 200:
                            cp.total_bytes = int(total_header)
                        elif cp.total_bytes is None:
                            cp.total_bytes = cp.bytes_downloaded + int(total_header)

                    cp.etag = response.headers.get("etag") or cp.etag
                    mode = "ab" if cp.bytes_downloaded > 0 else "wb"
                    with partial.open(mode) as handle:
                        for chunk in response.iter_bytes(chunk_size=chunk_size):
                            if cancel_check():
                                raise DatasetError(
                                    "Download cancelled", code="cancelled", http_status=409
                                )
                            if not chunk:
                                continue
                            handle.write(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                            cp.bytes_downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(
                                    {
                                        "phase": "downloading",
                                        "bytesDownloaded": cp.bytes_downloaded,
                                        "totalBytes": cp.total_bytes,
                                        "checkpoint": cp.to_dict(),
                                        "filename": safe_name,
                                        "chunkSize": chunk_size,
                                    }
                                )

                    # Promote partial → final after size check
                    if expected_size is not None and cp.bytes_downloaded != expected_size:
                        raise DatasetError(
                            f"Size mismatch for {safe_name}: got {cp.bytes_downloaded} expected {expected_size}",
                            code="hf_size_mismatch",
                            http_status=502,
                        )
                    partial.replace(dest_path)
                    if hasher is not None:
                        digest = hasher.hexdigest()
                    else:
                        digest = sha256_file(dest_path)
                    if expected_hash and digest != expected_hash:
                        dest_path.unlink(missing_ok=True)
                        raise DatasetError(
                            f"Hash mismatch for {safe_name}",
                            code="hf_hash_mismatch",
                            http_status=502,
                        )
                    size = dest_path.stat().st_size
                    cp.bytes_downloaded = size
                    cp.content_hash = digest
                    cp.completed = True
                    if progress_cb:
                        progress_cb(
                            {
                                "phase": "file_completed",
                                "bytesDownloaded": size,
                                "contentHash": digest,
                                "checkpoint": cp.to_dict(),
                                "filename": safe_name,
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
    from Data.modules.common.atomic import atomic_write_bytes

    atomic_write_bytes(path, data)
    return sha256_file(path)


# --- Repository parallel download ------------------------------------------

@dataclass
class HfRepoDownloadResult:
    manifest: HfRepoManifest
    files: list[HfDownloadResult]
    bytes_per_second: float | None
    elapsed_seconds: float


def download_hf_repository(
    *,
    plan: HfRepoPlan,
    raw_root: Path,
    token: str | None = None,
    manifest: HfRepoManifest | None = None,
    manifest_path: Path | None = None,
    workers: int | None = None,
    chunk_size: int | None = None,
    cancel_check: CancelCheck | None = None,
    sleep_fn: SleepFn | None = None,
    progress_cb: ProgressCb | None = None,
    transport: httpx.BaseTransport | None = None,
    progress_persist_interval: float = 0.75,
) -> HfRepoDownloadResult:
    """Download all DATA files from a plan with bounded concurrency + durable manifest."""
    cancel_check = cancel_check or (lambda: False)
    sleep_fn = sleep_fn or time.sleep
    workers = workers or hf_download_workers()
    chunk_size = chunk_size or hf_download_chunk_bytes()
    ensure_dir(raw_root)

    manifest = build_manifest_from_plan(plan, existing=manifest)
    # Disk preflight using remaining bytes
    already = sum(
        int(s.size or s.downloaded or 0)
        for s in manifest.files.values()
        if s.status == "complete"
    )
    disk_preflight_for_download(
        target_dir=raw_root,
        bytes_total=manifest.bytes_total,
        bytes_already=already,
    )

    rate_limit = RateLimitCoordinator()
    lock = threading.Lock()
    results: list[HfDownloadResult] = []
    errors: list[str] = []
    started = time.monotonic()
    last_persist = 0.0
    bytes_at_start = already

    def persist(force: bool = False) -> None:
        nonlocal last_persist
        now = time.monotonic()
        if not force and (now - last_persist) < progress_persist_interval:
            return
        last_persist = now
        manifest.recompute()
        if manifest_path is not None:
            write_repo_manifest(manifest_path, manifest)

    def emit(phase: str, **extra: Any) -> None:
        manifest.recompute()
        elapsed = max(1e-6, time.monotonic() - started)
        transferred = max(0, manifest.bytes_downloaded - bytes_at_start)
        bps = transferred / elapsed if transferred > 0 else None
        eta = None
        if (
            manifest.bytes_total is not None
            and bps
            and bps > 0
            and manifest.bytes_downloaded < manifest.bytes_total
        ):
            eta = (manifest.bytes_total - manifest.bytes_downloaded) / bps
        payload = {
            "phase": phase,
            "filesTotal": manifest.files_total,
            "filesCompleted": manifest.files_completed,
            "filesFailed": manifest.files_failed,
            "bytesTotal": manifest.bytes_total,
            "bytesDownloaded": manifest.bytes_downloaded,
            "bytesPerSecond": bps,
            "etaSeconds": eta,
            "workers": workers,
            "chunkSize": chunk_size,
            "rateLimitEvents": rate_limit.events,
            "manifest": manifest.to_dict(),
            **extra,
        }
        if progress_cb:
            progress_cb(payload)

    # Collect work: skip already-complete verified files
    pending: list[HfRepoFile] = []
    for entry in plan.data_files:
        state = manifest.files[entry.path]
        dest = safe_dest_path(raw_root, entry.path)
        if state.status == "complete" and dest.exists():
            size = dest.stat().st_size
            if entry.size is None or size == entry.size:
                results.append(
                    HfDownloadResult(
                        path=dest,
                        content_hash=state.hash or sha256_file(dest),
                        byte_size=size,
                        checkpoint=HfDownloadCheckpoint(
                            repository_id=plan.repository_id,
                            revision=plan.revision,
                            filename=entry.path,
                            bytes_downloaded=size,
                            total_bytes=size,
                            content_hash=state.hash,
                            completed=True,
                        ),
                        url=resolve_hf_file_url(plan.repository_id, plan.revision, entry.path),
                    )
                )
                continue
            state.status = "partial"
            state.downloaded = 0
        pending.append(entry)

    manifest.phase = "downloading"
    persist(force=True)
    emit("downloading")

    def worker_download(entry: HfRepoFile) -> HfDownloadResult:
        if cancel_check():
            raise DatasetError("Download cancelled", code="cancelled", http_status=409)
        dest = safe_dest_path(raw_root, entry.path)
        with lock:
            state = manifest.files[entry.path]
            state.status = "downloading"
        # Per-worker persistent client (keep-alive across chunks of one file)
        with httpx.Client(timeout=None, follow_redirects=True, transport=transport) as client:

            def file_progress(info: dict[str, Any]) -> None:
                with lock:
                    st = manifest.files[entry.path]
                    st.downloaded = int(info.get("bytesDownloaded") or st.downloaded)
                    st.last_http_status = (info.get("checkpoint") or {}).get("lastStatus")
                    st.etag = (info.get("checkpoint") or {}).get("etag") or st.etag
                    if info.get("phase") == "rate_limited":
                        manifest.phase = "rate_limited"
                    persist(force=False)
                    emit(str(info.get("phase") or "downloading"), filename=entry.path)

            result = download_hf_file(
                repository_id=plan.repository_id,
                filename=entry.path,
                dest_path=dest,
                revision=plan.revision,
                token=token,
                cancel_check=cancel_check,
                sleep_fn=sleep_fn,
                progress_cb=file_progress,
                client=client,
                transport=transport,
                chunk_size=chunk_size,
                rate_limit=rate_limit,
                expected_size=entry.size,
            )
        with lock:
            st = manifest.files[entry.path]
            st.status = "complete"
            st.downloaded = result.byte_size
            st.size = result.byte_size
            st.hash = result.content_hash
            st.etag = result.checkpoint.etag
            st.last_http_status = result.checkpoint.last_status
            st.error = None
            persist(force=True)
            emit("hf.download.file_completed", filename=entry.path)
        return result

    try:
        if not pending:
            manifest.phase = "download_completed"
            persist(force=True)
            emit("download_completed")
            elapsed = max(1e-6, time.monotonic() - started)
            return HfRepoDownloadResult(
                manifest=manifest,
                files=results,
                bytes_per_second=0.0,
                elapsed_seconds=elapsed,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(worker_download, entry): entry for entry in pending}
            for fut in as_completed(futures):
                entry = futures[fut]
                if cancel_check():
                    for other in futures:
                        other.cancel()
                    raise DatasetError("Download cancelled", code="cancelled", http_status=409)
                try:
                    results.append(fut.result())
                except DatasetError as exc:
                    if exc.code == "cancelled":
                        raise
                    with lock:
                        st = manifest.files[entry.path]
                        st.status = "failed"
                        st.error = redact_secrets(exc.message)
                        st.retry_count += 1
                        persist(force=True)
                    errors.append(f"{entry.path}: {exc.message}")
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        st = manifest.files[entry.path]
                        st.status = "failed"
                        st.error = redact_secrets(str(exc))
                        st.retry_count += 1
                        persist(force=True)
                    errors.append(f"{entry.path}: {exc}")
    finally:
        persist(force=True)

    manifest.recompute()
    if errors or manifest.files_failed:
        manifest.phase = "failed"
        persist(force=True)
        emit("failed")
        raise DatasetError(
            f"HF repository download incomplete: {manifest.files_completed}/{manifest.files_total} "
            f"files ok; failures={len(errors)}: " + "; ".join(errors[:5]),
            code="hf_download_incomplete",
            http_status=502,
        )

    manifest.phase = "download_completed"
    persist(force=True)
    elapsed = max(1e-6, time.monotonic() - started)
    transferred = max(0, manifest.bytes_downloaded - bytes_at_start)
    bps = transferred / elapsed if transferred > 0 else 0.0
    emit("download_completed")
    return HfRepoDownloadResult(
        manifest=manifest,
        files=results,
        bytes_per_second=bps,
        elapsed_seconds=elapsed,
    )
