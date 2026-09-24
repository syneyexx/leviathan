"""Offline / local dataset discovery and brain-projection helpers.

External-First: discovery and indexing run as dataset jobs; Core owns manifests.
No remote embedding fallback when offline_only=True.

Discovery scans the configured data root (typically ``D:/ModelData``) and
corpus dataset directories. Physical presence ≠ Brain knowledge — registration
into the dataset library is separate from Brain ingestion.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, normalize_path_key, safe_relpath

from .formats import detect_format
from .importers import SUPPORTED_SUFFIXES
from .types import DetectedFormat

# Single authoritative extension set — shared with upload/import.
ALLOWED_EXTENSIONS = set(SUPPORTED_SUFFIXES)

IGNORE_NAMES = {
    ".git",
    ".svn",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
    ".leviathan-dataset.json",
    ".leviathan-dataset.deleted",
}

# Derived / internal trees under the data root that must not be re-registered
# as independent source datasets (they are projections of registered ones).
SKIP_DIR_NAMES = {
    "materialized",
    "processed",
    "exports",
    "manifests",
    "training",
    "research",
    "models",
    "checkpoints",
    "adapters",
    "logs",
    "__pycache__",
}

HF_REPO_DIR_RE = re.compile(r"^datasets--(?P<ns>.+)--(?P<name>.+)$")
HF_MARKERS = {
    "dataset_info.json",
    "dataset_infos.json",
    "datapackage.json",
    "readme.md",
}


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
    kind: str = "file"  # file | directory | hf_cache
    display_name: str | None = None
    hf_repo_id: str | None = None
    file_count: int | None = None
    path_key: str = ""

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
            "kind": self.kind,
            "displayName": self.display_name,
            "hfRepoId": self.hf_repo_id,
            "fileCount": self.file_count,
            "pathKey": self.path_key or normalize_path_key(self.path),
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
    base = f"{normalize_path_key(path)}|{stat.st_size}|{stat.st_mtime_ns}"
    if content_hash:
        digest = sha256_file(path)
        return hashlib.sha256(f"{base}|{digest}".encode("utf-8")).hexdigest()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def fingerprint_directory(path: Path, *, file_count: int, size_bytes: int, mtime_ns: int) -> str:
    base = f"{normalize_path_key(path)}|dir|{file_count}|{size_bytes}|{mtime_ns}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def build_discovery_roots(
    *,
    data_root: Path,
    corpus_root: Path,
    datasets_raw: Path,
    hf_cache: Path,
) -> list[tuple[str, Path]]:
    """Ordered, deduplicated discovery roots from central storage config."""
    candidates: list[tuple[str, Path]] = [
        ("data_root", Path(data_root)),
        ("corpus_root", Path(corpus_root)),
        ("datasets_raw", Path(datasets_raw)),
        ("hf_cache", Path(hf_cache)),
    ]
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for root_id, root in candidates:
        key = normalize_path_key(root)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((root_id, root))
    return out


def _should_skip_dirname(name: str) -> bool:
    if name in IGNORE_NAMES or name.startswith("."):
        return True
    return name in SKIP_DIR_NAMES


def _hf_repo_id_from_dirname(name: str) -> str | None:
    match = HF_REPO_DIR_RE.match(name)
    if not match:
        return None
    ns = match.group("ns").replace("--", "/")
    ds = match.group("name").replace("--", "/")
    return f"{ns}/{ds}"


def _directory_looks_like_dataset(path: Path) -> bool:
    """Cheap heuristic: marker metadata or multiple supported data files."""
    try:
        names = {p.name.lower() for p in path.iterdir() if p.is_file()}
    except OSError:
        return False
    if names & HF_MARKERS:
        return True
    data_files = [
        p
        for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS and p.name not in IGNORE_NAMES
    ]
    return len(data_files) >= 2


def _summarize_directory(path: Path) -> tuple[int, int, int, str]:
    """Return file_count, size_bytes, mtime_ns, primary_format (shallow)."""
    file_count = 0
    size_bytes = 0
    mtime_ns = 0
    primary_format = DetectedFormat.UNKNOWN.value
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return 0, 0, 0, primary_format
    for entry in entries:
        if entry.name in IGNORE_NAMES or entry.name.startswith("."):
            continue
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        file_count += 1
        size_bytes += int(stat.st_size)
        mtime_ns = max(mtime_ns, int(stat.st_mtime_ns))
        if primary_format == DetectedFormat.UNKNOWN.value:
            primary_format = detect_format(entry).format.value
    if file_count == 0:
        try:
            stat = path.stat()
            mtime_ns = int(stat.st_mtime_ns)
        except OSError:
            pass
    return file_count, size_bytes, mtime_ns, primary_format


def discover_hf_cache_units(
    hf_cache: Path,
    *,
    root_id: str = "hf_cache",
    max_units: int = 200,
) -> list[DiscoveredSource]:
    """Discover HF hub dataset units (repo dirs), not individual shards."""
    root = Path(hf_cache)
    if not root.exists() or not root.is_dir():
        return []
    found: list[DiscoveredSource] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        if len(found) >= max_units:
            break
        if not child.is_dir() or child.name in IGNORE_NAMES or child.name.startswith("."):
            continue
        repo_id = _hf_repo_id_from_dirname(child.name)
        # Prefer hub-style dirs; also accept folders with dataset markers.
        if repo_id is None and not _directory_looks_like_dataset(child):
            continue
        # Prefer snapshot leaf when present (hub layout).
        target = child
        snapshots = child / "snapshots"
        if snapshots.is_dir():
            try:
                snaps = sorted(
                    (p for p in snapshots.iterdir() if p.is_dir()),
                    key=lambda p: p.name,
                )
                if snaps:
                    target = snaps[-1]
            except OSError:
                pass
        file_count, size_bytes, mtime_ns, fmt = _summarize_directory(target)
        if file_count == 0 and repo_id is None:
            continue
        display = repo_id or child.name
        try:
            safe_relpath(root.resolve(), target.resolve())
        except (PathEscapeError, ValueError, OSError) as exc:
            found.append(
                DiscoveredSource(
                    path=str(target),
                    relative_path=child.name,
                    root_id=root_id,
                    size_bytes=0,
                    mtime_ns=0,
                    extension="",
                    format=DetectedFormat.UNKNOWN.value,
                    fingerprint="",
                    readable=False,
                    error=str(exc),
                    kind="hf_cache",
                    display_name=display,
                    hf_repo_id=repo_id,
                    path_key=normalize_path_key(target),
                )
            )
            continue
        found.append(
            DiscoveredSource(
                path=str(target.resolve()),
                relative_path=str(target.resolve().relative_to(root.resolve())),
                root_id=root_id,
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                extension="",
                format=fmt,
                fingerprint=fingerprint_directory(
                    target, file_count=file_count, size_bytes=size_bytes, mtime_ns=mtime_ns
                ),
                readable=os.access(target, os.R_OK),
                kind="hf_cache",
                display_name=display,
                hf_repo_id=repo_id,
                file_count=file_count,
                path_key=normalize_path_key(target),
            )
        )
    found.sort(key=lambda s: (s.root_id, s.relative_path))
    return found


def discover_under_roots(
    roots: Iterable[tuple[str, Path]],
    *,
    max_files: int = 500,
    follow_symlinks: bool = False,
    max_depth: int = 8,
    skip_under: Iterable[Path] | None = None,
) -> list[DiscoveredSource]:
    """Deterministic, bounded discovery under explicit allowed roots."""
    skip_keys = {normalize_path_key(p) for p in (skip_under or []) if normalize_path_key(p)}
    found: list[DiscoveredSource] = []
    seen_keys: set[str] = set()

    def _accept(source: DiscoveredSource) -> None:
        key = source.path_key or normalize_path_key(source.path)
        if not key or key in seen_keys:
            return
        # Skip derived trees (materialized/processed/…) when nested under data_root.
        for skip in skip_keys:
            if key == skip or key.startswith(skip.rstrip("/") + "/"):
                return
        seen_keys.add(key)
        found.append(source)

    for root_id, root in roots:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            continue
        if root_id == "hf_cache":
            for unit in discover_hf_cache_units(root, root_id=root_id, max_units=max_files):
                if len(found) >= max_files:
                    return found
                _accept(unit)
            continue
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        for dirpath, dirnames, filenames in os.walk(root_resolved, followlinks=follow_symlinks):
            if len(found) >= max_files:
                found.sort(key=lambda s: (s.root_id, s.relative_path))
                return found
            try:
                current = Path(dirpath).resolve()
            except OSError:
                dirnames[:] = []
                continue
            rel_dir = current.relative_to(root_resolved) if current != root_resolved else Path(".")
            depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
            # Prune derived / ignored dirs
            pruned: list[str] = []
            for d in sorted(dirnames):
                if _should_skip_dirname(d):
                    continue
                child = current / d
                child_key = normalize_path_key(child)
                if any(child_key == sk or child_key.startswith(sk.rstrip("/") + "/") for sk in skip_keys):
                    continue
                # Treat dataset-like directories as units (do not descend into shards).
                if depth >= 1 and _directory_looks_like_dataset(child):
                    file_count, size_bytes, mtime_ns, fmt = _summarize_directory(child)
                    if file_count > 0:
                        try:
                            safe_relpath(root_resolved, child)
                            _accept(
                                DiscoveredSource(
                                    path=str(child.resolve()),
                                    relative_path=str(child.resolve().relative_to(root_resolved)),
                                    root_id=root_id,
                                    size_bytes=size_bytes,
                                    mtime_ns=mtime_ns,
                                    extension="",
                                    format=fmt,
                                    fingerprint=fingerprint_directory(
                                        child,
                                        file_count=file_count,
                                        size_bytes=size_bytes,
                                        mtime_ns=mtime_ns,
                                    ),
                                    readable=os.access(child, os.R_OK),
                                    kind="directory",
                                    display_name=child.name,
                                    file_count=file_count,
                                    path_key=normalize_path_key(child),
                                )
                            )
                        except (OSError, PathEscapeError, ValueError) as exc:
                            _accept(
                                DiscoveredSource(
                                    path=str(child),
                                    relative_path=d,
                                    root_id=root_id,
                                    size_bytes=0,
                                    mtime_ns=0,
                                    extension="",
                                    format=DetectedFormat.UNKNOWN.value,
                                    fingerprint="",
                                    readable=False,
                                    error=str(exc),
                                    kind="directory",
                                    display_name=d,
                                    path_key=normalize_path_key(child),
                                )
                            )
                    continue  # do not descend
                pruned.append(d)
            dirnames[:] = pruned

            for name in sorted(filenames):
                if len(found) >= max_files:
                    break
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
                    _accept(
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
                            kind="file",
                            display_name=path.stem or path.name,
                            path_key=normalize_path_key(path),
                        )
                    )
                except (OSError, PathEscapeError, ValueError) as exc:
                    _accept(
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
                            kind="file",
                            display_name=name,
                            path_key=normalize_path_key(path),
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
            "local_dataset_is_not_learned_knowledge": True,
        },
    }
