"""Safe TAR / compressed-tar / single-file gzip inspection."""

from __future__ import annotations

import gzip
import hashlib
import tarfile
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.paths import PathEscapeError

from ..settings import SourceIngestionSettings
from ..types import IngestionError
from .security import (
    assert_safe_staging_path,
    check_declared_bomb,
    check_member_limits,
    normalize_member_path,
)


def _open_tar(path: Path) -> tarfile.TarFile:
    try:
        return tarfile.open(path, mode="r:*")
    except tarfile.TarError as exc:
        raise IngestionError(
            "ARCHIVE_CORRUPT",
            f"Corrupt or invalid TAR: {exc}",
            http_status=422,
            details={"path": str(path)},
        ) from exc


def inspect_tar(
    path: Path,
    *,
    settings: SourceIngestionSettings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    archive_size = path.stat().st_size
    members: list[dict[str, Any]] = []
    declared_total = 0
    with _open_tar(path) as tf:
        infos = list(tf.getmembers())
        if len(infos) > settings.max_member_count:
            raise IngestionError(
                "ARCHIVE_TOO_MANY_MEMBERS",
                f"Archive declares {len(infos)} members (max {settings.max_member_count})",
                http_status=422,
                details={"count": len(infos)},
            )
        for idx, info in enumerate(infos):
            try:
                rel = normalize_member_path(info.name)
            except PathEscapeError as exc:
                raise IngestionError(
                    "ARCHIVE_PATH_TRAVERSAL",
                    str(exc),
                    http_status=422,
                    details={"raw_name": info.name},
                ) from exc
            is_dir = info.isdir()
            is_symlink = info.issym() or info.islnk()
            size = int(info.size or 0)
            if not is_dir and not is_symlink:
                declared_total += size
                check_member_limits(
                    settings=settings,
                    relative_path=rel,
                    uncompressed_size=size,
                    compressed_size=None,
                    member_index=idx,
                    total_uncompressed_so_far=declared_total - size,
                )
            members.append(
                {
                    "raw_name": info.name,
                    "relative_path": rel,
                    "is_dir": is_dir,
                    "is_symlink": is_symlink,
                    "is_encrypted": False,
                    "file_size": size,
                    "compress_size": None,
                }
            )
    check_declared_bomb(
        settings=settings,
        declared_uncompressed_total=declared_total,
        compressed_archive_size=archive_size,
    )
    return members, {
        "archive_type": "tar",
        "compressed_bytes": archive_size,
        "declared_uncompressed_bytes": declared_total,
        "member_count": len([m for m in members if not m["is_dir"]]),
    }


def extract_tar_member(
    path: Path,
    member_name: str,
    *,
    relative_path: str,
    staging_root: Path,
    settings: SourceIngestionSettings,
) -> tuple[Path, str, int]:
    with _open_tar(path) as tf:
        info = tf.getmember(member_name)
        if info.issym() or info.islnk():
            raise IngestionError(
                "ARCHIVE_SYMLINK_REFUSED",
                "Symlink/hardlink members are not followed",
                http_status=422,
                details={"relative_path": relative_path},
            )
        dest = staging_root / relative_path
        ensure_dir(dest.parent)
        assert_safe_staging_path(staging_root, dest)
        src = tf.extractfile(info)
        if src is None:
            raise IngestionError(
                "ARCHIVE_MEMBER_UNREADABLE",
                "Cannot read tar member",
                http_status=422,
                details={"relative_path": relative_path},
            )
        hasher = hashlib.sha256()
        total = 0
        tmp = dest.with_suffix(dest.suffix + ".partial")
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > settings.max_member_bytes:
                        raise IngestionError(
                            "ARCHIVE_MEMBER_TOO_LARGE",
                            "Member exceeded size while extracting",
                            http_status=422,
                        )
                    hasher.update(chunk)
                    out.write(chunk)
            tmp.replace(dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return dest, hasher.hexdigest(), total


def decompress_gzip_single(
    path: Path,
    *,
    staging_root: Path,
    output_name: str,
    settings: SourceIngestionSettings,
) -> tuple[Path, str, int]:
    """Single-file .gz decompression only (not a multi-member archive)."""
    dest = staging_root / output_name
    ensure_dir(dest.parent)
    assert_safe_staging_path(staging_root, dest)
    hasher = hashlib.sha256()
    total = 0
    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        with gzip.open(path, "rb") as src, open(tmp, "wb") as out:
            while True:
                chunk = src.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_member_bytes:
                    raise IngestionError(
                        "ARCHIVE_MEMBER_TOO_LARGE",
                        "Gzip payload exceeded size limit",
                        http_status=422,
                    )
                hasher.update(chunk)
                out.write(chunk)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest, hasher.hexdigest(), total
