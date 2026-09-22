"""Offline / local dataset discovery and brain-projection helpers.

External-First: discovery and indexing run as dataset jobs; Core owns manifests.
No remote embedding fallback when offline_only=True.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_relpath

from .formats import detect_format
from .types import DetectedFormat

ALLOWED_EXTENSIONS = {
    ".jsonl",
    ".ndjson",
    ".json",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".markdown",
}

IGNORE_NAMES = {".git", ".svn", "__pycache__", "node_modules", ".DS_Store", "Thumbs.db"}


@dataclass(frozen=True)
class DiscoveredSource:
    path: str
    relative_path: str
    root_id: str
    size_bytes: int
    mtime_ns: int
    extension: str
    format: str
    fingerprint: str
    readable: bool
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "relativePath": self.relative_path,
            "rootId": self.root_id,
            "sizeBytes": self.size_bytes,
            "mtimeNs": self.mtime_ns,
            "extension": self.extension,
            "format": self.format,
            "fingerprint": self.fingerprint,
            "readable": self.readable,
            "error": self.error,
        }


@dataclass
class OfflinePreflight:
    ok: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disk_free_bytes: int | None = None
    required_bytes: int | None = None
    embedding_provider: str | None = None
    embedding_local: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "diskFreeBytes": self.disk_free_bytes,
            "requiredBytes": self.required_bytes,
            "embeddingProvider": self.embedding_provider,
            "embeddingLocal": self.embedding_local,
            "details": dict(self.details),
            "truth": {
                "offline_means_no_remote_embedding_fallback": True,
                "no_invented_readiness": True,
            },
        }


def fingerprint_file(path: Path, *, content_hash: bool = False) -> str:
    stat = path.stat()
    base = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    if content_hash:
        digest = sha256_file(path)
        return hashlib.sha256(f"{base}|{digest}".encode("utf-8")).hexdigest()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def discover_under_roots(
    roots: Iterable[tuple[str, Path]],
    *,
    max_files: int = 500,
    follow_symlinks: bool = False,
    max_depth: int = 8,
) -> list[DiscoveredSource]:
    """Deterministic, bounded discovery under explicit allowed roots."""
    found: list[DiscoveredSource] = []
    for root_id, root in roots:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            continue
        root_resolved = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root_resolved, followlinks=follow_symlinks):
            rel_dir = Path(dirpath).resolve().relative_to(root_resolved)
            depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(
                d for d in dirnames if d not in IGNORE_NAMES and not d.startswith(".")
            )
            for name in sorted(filenames):
                if len(found) >= max_files:
                    return found
                if name in IGNORE_NAMES or name.startswith("."):
                    continue
                path = Path(dirpath) / name
                if path.is_symlink() and not follow_symlinks:
                    continue
                suffix = path.suffix.lower()
                if suffix not in ALLOWED_EXTENSIONS:
                    continue
                try:
                    safe_relpath(root_resolved, path)
                    stat = path.stat()
                    detection = detect_format(path)
                    fmt_value = detection.format.value
                    found.append(
                        DiscoveredSource(
                            path=str(path.resolve()),
                            relative_path=str(path.resolve().relative_to(root_resolved)),
                            root_id=root_id,
                            size_bytes=int(stat.st_size),
                            mtime_ns=int(stat.st_mtime_ns),
                            extension=suffix,
                            format=fmt_value,
                            fingerprint=fingerprint_file(path, content_hash=False),
                            readable=os.access(path, os.R_OK),
                        )
                    )
                except (OSError, PathEscapeError, ValueError) as exc:
                    found.append(
                        DiscoveredSource(
                            path=str(path),
                            relative_path=name,
                            root_id=root_id,
                            size_bytes=0,
                            mtime_ns=0,
                            extension=suffix,
                            format=DetectedFormat.UNKNOWN.value,
                            fingerprint="",
                            readable=False,
                            error=str(exc),
                        )
                    )
    found.sort(key=lambda s: (s.root_id, s.relative_path))
    return found


def disk_free_bytes(path: Path) -> int | None:
    try:
        usage = os.statvfs(path) if hasattr(os, "statvfs") else None
        if usage is not None:
            return int(usage.f_bavail * usage.f_frsize)
    except OSError:
        pass
    try:
        import shutil

        return int(shutil.disk_usage(path).free)
    except OSError:
        return None


def offline_index_preflight(
    *,
    target_dir: Path,
    source_size_bytes: int,
    embedding_status: dict[str, Any] | None,
    offline_only: bool = True,
    reserve_bytes: int = 256 * 1024 * 1024,
) -> OfflinePreflight:
    blockers: list[str] = []
    warnings: list[str] = []
    free = disk_free_bytes(target_dir)
    required = source_size_bytes + reserve_bytes
    if free is not None and free < required:
        blockers.append(
            f"Insufficient disk: free={free} required≈{required} (includes {reserve_bytes} reserve)"
        )
    provider_id = None
    embedding_local = False
    if embedding_status:
        provider_id = str(embedding_status.get("provider_id") or embedding_status.get("kind") or "")
        available = bool(embedding_status.get("available"))
        # Local hash / null are offline-safe; anything else claiming remote is blocked in offline mode.
        embedding_local = provider_id in {"local_hash", "null", "lexical", ""} or bool(
            embedding_status.get("local")
        )
        if offline_only and not embedding_local and available:
            blockers.append(
                f"OFFLINE_EMBEDDING_REMOTE_REFUSED provider={provider_id or 'unknown'}"
            )
        if offline_only and not available and provider_id not in {"null", "lexical", ""}:
            warnings.append(
                f"Embedding provider unavailable ({provider_id}); lexical/chunk index only"
            )
    elif offline_only:
        warnings.append("No embedding status provided — proceeding with lexical knowledge index only")

    return OfflinePreflight(
        ok=not blockers,
        blockers=blockers,
        warnings=warnings,
        disk_free_bytes=free,
        required_bytes=required,
        embedding_provider=provider_id,
        embedding_local=embedding_local,
        details={"offlineOnly": offline_only, "reserveBytes": reserve_bytes},
    )


def build_projection_manifest(
    *,
    projection_id: str,
    dataset_id: str,
    version_id: str,
    source_fingerprint: str,
    job_id: str | None,
    outcome: dict[str, Any],
    embedding_status: dict[str, Any] | None,
    offline_only: bool,
    parser_version: str = "dataset-formats-1",
    chunker_version: str = "knowledge-chunk-1",
) -> dict[str, Any]:
    return {
        "projectionId": projection_id,
        "datasetId": dataset_id,
        "versionId": version_id,
        "sourceFingerprint": source_fingerprint,
        "jobId": job_id,
        "documentCount": outcome.get("documentCount"),
        "chunkCount": outcome.get("chunkCount"),
        "scope": outcome.get("scope"),
        "parserVersion": parser_version,
        "chunkerVersion": chunker_version,
        "embedding": embedding_status or {"provider_id": "none", "available": False},
        "offlineOnly": offline_only,
        "status": "ready",
        "truth": {
            "manifest_published_after_index": True,
            "index_is_not_training": True,
            "offline_no_remote_fallback": offline_only,
        },
    }
