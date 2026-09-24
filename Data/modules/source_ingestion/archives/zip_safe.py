"""Safe ZIP archive inspection and bounded member extraction."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.paths import PathEscapeError

from ..settings import SourceIngestionSettings
from ..types import IngestionError, ManifestMember, MemberOutcome
from .security import (
    assert_safe_staging_path,
    check_declared_bomb,
    check_member_limits,
    normalize_member_path,
)


@dataclass
class ZipMemberInfo:
    raw_name: str
    relative_path: str
    is_dir: bool
    is_symlink: bool
    is_encrypted: bool
    file_size: int
    compress_size: int
    compress_type: int


def _is_symlink_info(info: zipfile.ZipInfo) -> bool:
    # UNIX symlink: external_attr high bits 0o120000
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path, mode="r")
    except zipfile.BadZipFile as exc:
        raise IngestionError(
            "ARCHIVE_CORRUPT",
            f"Corrupt or invalid ZIP: {exc}",
            http_status=422,
            details={"path": str(path)},
        ) from exc


def inspect_zip(
    path: Path,
    *,
    container_source_id: str,
    settings: SourceIngestionSettings,
) -> tuple[list[ZipMemberInfo], dict[str, Any]]:
    """Inspect ZIP without extractall. Enforces bomb/count limits on declared sizes."""
    archive_size = path.stat().st_size
    members: list[ZipMemberInfo] = []
    declared_total = 0
    with open_zip(path) as zf:
        infos = list(zf.infolist())
        if len(infos) > settings.max_member_count:
            raise IngestionError(
                "ARCHIVE_TOO_MANY_MEMBERS",
                f"Archive declares {len(infos)} members (max {settings.max_member_count})",
                http_status=422,
                details={"count": len(infos), "max_member_count": settings.max_member_count},
            )
        for idx, info in enumerate(infos):
            try:
                rel = normalize_member_path(info.filename)
            except PathEscapeError as exc:
                raise IngestionError(
                    "ARCHIVE_PATH_TRAVERSAL",
                    str(exc),
                    http_status=422,
                    details={"raw_name": info.filename},
                ) from exc
            is_dir = info.is_dir() or info.filename.endswith("/")
            is_symlink = _is_symlink_info(info)
            is_encrypted = bool(info.flag_bits & 0x1)
            size = int(info.file_size or 0)
            csize = int(info.compress_size or 0)
            if not is_dir:
                declared_total += size
                check_member_limits(
                    settings=settings,
                    relative_path=rel,
                    uncompressed_size=size,
                    compressed_size=csize,
                    member_index=idx,
                    total_uncompressed_so_far=declared_total - size,
                )
            members.append(
                ZipMemberInfo(
                    raw_name=info.filename,
                    relative_path=rel,
                    is_dir=is_dir,
                    is_symlink=is_symlink,
                    is_encrypted=is_encrypted,
                    file_size=size,
                    compress_size=csize,
                    compress_type=info.compress_type,
                )
            )
    check_declared_bomb(
        settings=settings,
        declared_uncompressed_total=declared_total,
        compressed_archive_size=archive_size,
    )
    meta = {
        "archive_type": "zip",
        "compressed_bytes": archive_size,
        "declared_uncompressed_bytes": declared_total,
        "member_count": len([m for m in members if not m.is_dir]),
    }
    return members, meta


def iter_zip_members(
    path: Path,
    *,
    container_source_id: str,
    settings: SourceIngestionSettings,
) -> Iterator[tuple[ZipMemberInfo, zipfile.ZipInfo]]:
    with open_zip(path) as zf:
        for info in zf.infolist():
            try:
                rel = normalize_member_path(info.filename)
            except PathEscapeError:
                continue
            yield (
                ZipMemberInfo(
                    raw_name=info.filename,
                    relative_path=rel,
                    is_dir=info.is_dir() or info.filename.endswith("/"),
                    is_symlink=_is_symlink_info(info),
                    is_encrypted=bool(info.flag_bits & 0x1),
                    file_size=int(info.file_size or 0),
                    compress_size=int(info.compress_size or 0),
                    compress_type=info.compress_type,
                ),
                info,
            )


def extract_member_to_staging(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    relative_path: str,
    staging_root: Path,
    settings: SourceIngestionSettings,
) -> tuple[Path, str, int]:
    """Stream one member to staging. Returns (path, sha256, size). Never extractall."""
    if info.flag_bits & 0x1:
        raise IngestionError(
            "ARCHIVE_MEMBER_ENCRYPTED",
            "Encrypted ZIP member",
            http_status=422,
            details={"relative_path": relative_path},
        )
    if _is_symlink_info(info):
        raise IngestionError(
            "ARCHIVE_SYMLINK_REFUSED",
            "Symlink members are not followed",
            http_status=422,
            details={"relative_path": relative_path},
        )

    dest = staging_root / relative_path
    # Defensive: ensure parent under staging
    ensure_dir(dest.parent)
    assert_safe_staging_path(staging_root, dest.parent)
    assert_safe_staging_path(staging_root, dest)

    hasher = hashlib.sha256()
    total = 0
    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        with zf.open(info, "r") as src, open(tmp, "wb") as out:
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
                        details={"relative_path": relative_path, "size": total},
                    )
                # Also guard against lying file_size (zip bomb via stream)
                if info.file_size and total > int(info.file_size) + 1024:
                    # Allow small slack; hard-stop if wildly over declared
                    if total > max(int(info.file_size) * 2, int(info.file_size) + 1024 * 1024):
                        raise IngestionError(
                            "ARCHIVE_ZIP_BOMB",
                            "Extracted size greatly exceeds declared size",
                            http_status=422,
                            details={
                                "relative_path": relative_path,
                                "declared": info.file_size,
                                "extracted": total,
                            },
                        )
                hasher.update(chunk)
                out.write(chunk)
        tmp.replace(dest)
        assert_safe_staging_path(staging_root, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest, hasher.hexdigest(), total


def stream_member_hash(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    settings: SourceIngestionSettings,
    sink: BinaryIO | None = None,
) -> tuple[str, int]:
    """Hash (and optionally copy) a member without loading whole file into RAM."""
    hasher = hashlib.sha256()
    total = 0
    with zf.open(info, "r") as src:
        while True:
            chunk = src.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_member_bytes:
                raise IngestionError(
                    "ARCHIVE_MEMBER_TOO_LARGE",
                    "Member exceeded size while reading",
                    http_status=422,
                )
            hasher.update(chunk)
            if sink is not None:
                sink.write(chunk)
    return hasher.hexdigest(), total


def member_to_manifest(
    info: ZipMemberInfo,
    *,
    container_source_id: str,
    member_id: str,
) -> ManifestMember:
    outcome = MemberOutcome.PENDING
    skip_reason = None
    if info.is_dir:
        outcome = MemberOutcome.SKIPPED
        skip_reason = "directory"
    elif info.is_symlink:
        outcome = MemberOutcome.SKIPPED
        skip_reason = "symlink"
    elif info.is_encrypted:
        outcome = MemberOutcome.QUARANTINED
        skip_reason = "encrypted"
    return ManifestMember(
        member_id=member_id,
        container_source_id=container_source_id,
        relative_path=info.relative_path,
        original_filename=Path(info.relative_path).name,
        size_bytes=info.file_size,
        compressed_size_bytes=info.compress_size,
        outcome=outcome,
        skip_reason=skip_reason,
        is_encrypted=info.is_encrypted,
        is_symlink=info.is_symlink,
        is_directory=info.is_dir,
    )


def read_member_sample(zf: zipfile.ZipFile, info: zipfile.ZipInfo, *, max_bytes: int = 8192) -> bytes:
    if info.flag_bits & 0x1 or _is_symlink_info(info) or info.is_dir():
        return b""
    with zf.open(info, "r") as src:
        return src.read(max_bytes)
