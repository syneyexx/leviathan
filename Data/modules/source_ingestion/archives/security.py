"""Safe archive path normalization and bomb/limit checks (Windows + POSIX)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from Data.modules.common.paths import PathEscapeError

from ..settings import SourceIngestionSettings
from ..types import IngestionError

_WINDOWS_RESERVED = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$",
    re.IGNORECASE,
)


def normalize_member_path(raw_name: str) -> str:
    """Normalize archive member name to a relative POSIX path or raise."""
    if raw_name is None:
        raise PathEscapeError("Empty archive member name")
    text = str(raw_name)
    if "\x00" in text:
        raise PathEscapeError("Null byte in archive member name")
    # UNC / URL-like
    if text.startswith("\\\\") or text.startswith("//"):
        raise PathEscapeError(f"UNC path refused: {raw_name!r}")
    # Absolute POSIX
    if text.startswith("/"):
        raise PathEscapeError(f"Absolute path refused: {raw_name!r}")
    # Windows drive / absolute
    win = PureWindowsPath(text)
    if win.drive or win.is_absolute() or text.startswith("\\"):
        raise PathEscapeError(f"Absolute/Windows path refused: {raw_name!r}")

    # Collapse separators to POSIX for inspection
    posix_text = text.replace("\\", "/")
    while "//" in posix_text:
        posix_text = posix_text.replace("//", "/")
    posix_text = posix_text.lstrip("/")

    pure = PurePosixPath(posix_text)
    if pure.is_absolute():
        raise PathEscapeError(f"Absolute path refused: {raw_name!r}")
    parts: list[str] = []
    for part in pure.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise PathEscapeError(f"Parent traversal refused: {raw_name!r}")
        if _WINDOWS_RESERVED.match(part):
            raise PathEscapeError(f"Reserved Windows filename refused: {part!r}")
        parts.append(part)
    if not parts:
        raise PathEscapeError(f"Empty relative path after normalization: {raw_name!r}")
    return "/".join(parts)


def assert_safe_staging_path(staging_root: Path, candidate: Path) -> Path:
    """Prove candidate resolves under staging_root."""
    root = Path(staging_root).resolve()
    resolved = Path(candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathEscapeError(f"Path escapes staging root: {resolved}") from exc
    return resolved


def check_member_limits(
    *,
    settings: SourceIngestionSettings,
    relative_path: str,
    uncompressed_size: int,
    compressed_size: int | None,
    member_index: int,
    total_uncompressed_so_far: int,
) -> None:
    parts = relative_path.split("/")
    if len(parts) > settings.max_path_depth:
        raise IngestionError(
            "ARCHIVE_PATH_TOO_DEEP",
            f"Member path depth exceeds limit ({settings.max_path_depth})",
            http_status=422,
            details={"relative_path": relative_path, "depth": len(parts)},
        )
    for part in parts:
        if len(part) > settings.max_filename_length:
            raise IngestionError(
                "ARCHIVE_FILENAME_TOO_LONG",
                f"Filename exceeds limit ({settings.max_filename_length})",
                http_status=422,
                details={"part": part[:64]},
            )
    if member_index >= settings.max_member_count:
        raise IngestionError(
            "ARCHIVE_TOO_MANY_MEMBERS",
            f"Archive exceeds max member count ({settings.max_member_count})",
            http_status=422,
            details={"max_member_count": settings.max_member_count},
        )
    if uncompressed_size < 0:
        raise IngestionError(
            "ARCHIVE_INVALID_SIZE",
            "Negative uncompressed size",
            http_status=422,
        )
    if uncompressed_size > settings.max_member_bytes:
        raise IngestionError(
            "ARCHIVE_MEMBER_TOO_LARGE",
            f"Member exceeds max size ({settings.max_member_bytes})",
            http_status=422,
            details={
                "relative_path": relative_path,
                "size": uncompressed_size,
                "max_member_bytes": settings.max_member_bytes,
            },
        )
    projected = total_uncompressed_so_far + max(0, uncompressed_size)
    if projected > settings.max_total_uncompressed_bytes:
        raise IngestionError(
            "ARCHIVE_EXPANSION_BUDGET_EXCEEDED",
            "Total uncompressed size exceeds budget",
            http_status=422,
            details={
                "projected": projected,
                "max_total_uncompressed_bytes": settings.max_total_uncompressed_bytes,
            },
        )
    if compressed_size is not None and compressed_size > 0 and uncompressed_size > 0:
        ratio = uncompressed_size / max(1, compressed_size)
        if ratio > settings.max_compression_ratio:
            raise IngestionError(
                "ARCHIVE_COMPRESSION_RATIO",
                f"Compression ratio {ratio:.1f} exceeds limit {settings.max_compression_ratio}",
                http_status=422,
                details={
                    "relative_path": relative_path,
                    "ratio": ratio,
                    "uncompressed": uncompressed_size,
                    "compressed": compressed_size,
                },
                retryable=False,
            )


def check_declared_bomb(
    *,
    settings: SourceIngestionSettings,
    declared_uncompressed_total: int,
    compressed_archive_size: int,
) -> None:
    """Reject extreme declared expansion without allocating huge data."""
    if declared_uncompressed_total > settings.max_total_uncompressed_bytes:
        raise IngestionError(
            "ARCHIVE_ZIP_BOMB",
            "Declared uncompressed total exceeds budget",
            http_status=422,
            details={
                "declared_uncompressed_total": declared_uncompressed_total,
                "max_total_uncompressed_bytes": settings.max_total_uncompressed_bytes,
            },
        )
    if compressed_archive_size > 0 and declared_uncompressed_total > 0:
        ratio = declared_uncompressed_total / max(1, compressed_archive_size)
        if ratio > settings.max_compression_ratio:
            raise IngestionError(
                "ARCHIVE_ZIP_BOMB",
                f"Declared compression ratio {ratio:.1f} exceeds limit",
                http_status=422,
                details={
                    "ratio": ratio,
                    "declared_uncompressed_total": declared_uncompressed_total,
                    "compressed_archive_size": compressed_archive_size,
                },
            )


def project_signals(relative_paths: list[str]) -> dict[str, Any]:
    """Deterministic structural metadata for software-repository archives."""
    roots = set()
    langs: set[str] = set()
    manifest_files: list[str] = []
    test_files = 0
    doc_files = 0
    has_src = False
    has_tests = False
    markers = {
        "pyproject.toml": "python",
        "package.json": "javascript",
        "cargo.toml": "rust",
        "go.mod": "go",
        "pom.xml": "java",
        "composer.json": "php",
        "gemfile": "ruby",
        ".sln": "dotnet",
        "cmakelists.txt": "c/cpp",
    }
    lang_ext = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".swift": "swift",
        ".kt": "kotlin",
    }
    for rel in relative_paths:
        posix = rel.replace("\\", "/")
        parts = posix.split("/")
        if len(parts) == 1:
            roots.add(parts[0])
        name = parts[-1].lower()
        for marker, lang in markers.items():
            if name == marker or name.endswith(marker):
                langs.add(lang)
                manifest_files.append(posix)
        if parts and parts[0] in {"src", "lib"}:
            has_src = True
        if parts and parts[0] in {"tests", "test", "__tests__", "spec"}:
            has_tests = True
            test_files += 1
        if parts and parts[0] in {"docs", "doc", "documentation"}:
            doc_files += 1
        ext = PurePosixPath(name).suffix.lower()
        if ext in lang_ext:
            langs.add(lang_ext[ext])
        if name.startswith("readme"):
            doc_files += 1

    project_kind = None
    if langs or has_src or manifest_files:
        project_kind = "software_repository"
    return {
        "project_kind": project_kind,
        "languages_detected": sorted(langs),
        "root_files": sorted(roots)[:50],
        "manifest_files": sorted(set(manifest_files))[:50],
        "test_files": test_files,
        "documentation_files": doc_files,
        "has_src": has_src,
        "has_tests": has_tests,
        "file_count": len(relative_paths),
    }
