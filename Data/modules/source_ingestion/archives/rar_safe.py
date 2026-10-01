"""Safe RAR archive inspection and bounded member extraction.

Uses the ``rarfile`` package plus a system UnRAR/7-Zip/bsdtar backend.
Never calls extractall — members are streamed one at a time with the same
path-traversal / bomb limits as ZIP and TAR.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

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

_WINDOWS_UNRAR_CANDIDATES = (
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    r"C:\Program Files\WinRAR\unrar.exe",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)


@dataclass
class RarMemberInfo:
    raw_name: str
    relative_path: str
    is_dir: bool
    is_symlink: bool
    is_encrypted: bool
    file_size: int
    compress_size: int | None


def _import_rarfile():
    try:
        import rarfile  # type: ignore
    except ImportError as exc:
        raise IngestionError(
            "ARCHIVE_RAR_DEPENDENCY_MISSING",
            "RAR support requires the 'rarfile' Python package",
            http_status=503,
            details={"package": "rarfile"},
        ) from exc
    return rarfile


@lru_cache(maxsize=1)
def probe_rar_tool() -> dict[str, Any]:
    """Discover whether a RAR extraction backend is available on this host."""
    rarfile = None
    try:
        import rarfile as _rf  # type: ignore

        rarfile = _rf
    except ImportError:
        return {
            "available": False,
            "package": False,
            "tool": None,
            "reason": "rarfile package not installed",
        }

    ensure_rar_backend(configure=True)
    tool = getattr(rarfile, "UNRAR_TOOL", None) or getattr(rarfile, "ALT_TOOL", None)
    # Confirm the configured tool actually exists / is callable.
    which = None
    if isinstance(tool, str) and tool:
        which = shutil.which(tool) or (tool if Path(tool).is_file() else None)
    if which:
        return {
            "available": True,
            "package": True,
            "tool": which,
            "reason": None,
        }
    # rarfile may have configured a custom OpenSSL-less path already used by open().
    # Fall back: try a tiny capability check via get_rar_version if present.
    try:
        get_ver = getattr(rarfile, "get_rar_version", None)
        if callable(get_ver):
            ver = get_ver()
            if ver:
                return {
                    "available": True,
                    "package": True,
                    "tool": str(tool or "configured"),
                    "reason": None,
                    "version": str(ver),
                }
    except Exception:  # noqa: BLE001
        pass
    return {
        "available": False,
        "package": True,
        "tool": None,
        "reason": (
            "No UnRAR / 7-Zip / bsdtar backend found. "
            "Install UnRAR (https://www.rarlab.com/rar_add.htm) or 7-Zip and ensure it is on PATH."
        ),
    }


def ensure_rar_backend(*, configure: bool = True) -> str | None:
    """Locate a RAR extraction tool and optionally configure rarfile to use it."""
    rarfile = _import_rarfile()
    candidates: list[str] = []
    env_tool = (os.environ.get("LEVIATHAN_UNRAR_TOOL") or "").strip()
    if env_tool:
        candidates.append(env_tool)
    for name in ("unrar", "UnRAR", "unar", "bsdtar", "7z", "7za"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    if os.name == "nt":
        candidates.extend(_WINDOWS_UNRAR_CANDIDATES)

    chosen: str | None = None
    for cand in candidates:
        if cand and (shutil.which(cand) or Path(cand).is_file()):
            chosen = cand
            break

    if chosen and configure:
        lower = Path(chosen).name.lower()
        if lower in {"7z", "7z.exe", "7za", "7za.exe"}:
            # rarfile 4.x supports 7z as an alternate extractor.
            try:
                rarfile.ALT_TOOL = chosen
                rarfile.USE_EXTRACTOR = getattr(rarfile, "ED_7Z", "7z")
            except Exception:  # noqa: BLE001
                rarfile.UNRAR_TOOL = chosen
        else:
            rarfile.UNRAR_TOOL = chosen
    return chosen


def open_rar(path: Path):
    rarfile = _import_rarfile()
    ensure_rar_backend(configure=True)
    try:
        return rarfile.RarFile(str(path))
    except rarfile.NeedFirstVolume as exc:
        raise IngestionError(
            "ARCHIVE_RAR_MULTI_VOLUME",
            "Multi-volume RAR archives are not supported; provide the complete first volume set",
            http_status=422,
            details={"path": str(path)},
        ) from exc
    except rarfile.RarCannotExec as exc:
        raise IngestionError(
            "ARCHIVE_RAR_TOOL_MISSING",
            "RAR extraction backend is not available on this host",
            http_status=503,
            details={"path": str(path), "hint": probe_rar_tool().get("reason")},
        ) from exc
    except rarfile.Error as exc:
        raise IngestionError(
            "ARCHIVE_CORRUPT",
            f"Corrupt or invalid RAR: {exc}",
            http_status=422,
            details={"path": str(path)},
        ) from exc


def inspect_rar(
    path: Path,
    *,
    container_source_id: str,
    settings: SourceIngestionSettings,
) -> tuple[list[RarMemberInfo], dict[str, Any]]:
    """Inspect RAR without extractall. Enforces bomb/count limits on declared sizes."""
    archive_size = path.stat().st_size
    members: list[RarMemberInfo] = []
    declared_total = 0
    with open_rar(path) as rf:
        infos = list(rf.infolist())
        if len(infos) > settings.max_member_count:
            raise IngestionError(
                "ARCHIVE_TOO_MANY_MEMBERS",
                f"Archive declares {len(infos)} members (max {settings.max_member_count})",
                http_status=422,
                details={"count": len(infos), "max_member_count": settings.max_member_count},
            )
        for idx, info in enumerate(infos):
            raw_name = str(getattr(info, "filename", "") or "")
            try:
                rel = normalize_member_path(raw_name)
            except PathEscapeError as exc:
                raise IngestionError(
                    "ARCHIVE_PATH_TRAVERSAL",
                    str(exc),
                    http_status=422,
                    details={"raw_name": raw_name},
                ) from exc
            is_dir = False
            if callable(getattr(info, "is_dir", None)):
                is_dir = bool(info.is_dir())
            elif callable(getattr(info, "isdir", None)):
                is_dir = bool(info.isdir())
            is_dir = is_dir or raw_name.endswith("/") or raw_name.endswith("\\")
            is_symlink = bool(getattr(info, "is_symlink", lambda: False)())
            is_encrypted = False
            if callable(getattr(info, "needs_password", None)):
                is_encrypted = bool(info.needs_password())
            size = int(getattr(info, "file_size", 0) or 0)
            csize_raw = getattr(info, "compress_size", None)
            csize = int(csize_raw) if csize_raw is not None else None
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
                RarMemberInfo(
                    raw_name=raw_name,
                    relative_path=rel,
                    is_dir=is_dir,
                    is_symlink=is_symlink,
                    is_encrypted=is_encrypted,
                    file_size=size,
                    compress_size=csize,
                )
            )
    check_declared_bomb(
        settings=settings,
        declared_uncompressed_total=declared_total,
        compressed_archive_size=archive_size,
    )
    meta = {
        "archive_type": "rar",
        "compressed_bytes": archive_size,
        "declared_uncompressed_bytes": declared_total,
        "member_count": len([m for m in members if not m.is_dir]),
        "rar_tool": probe_rar_tool().get("tool"),
    }
    return members, meta


def iter_rar_members(
    path: Path,
    *,
    settings: SourceIngestionSettings,
) -> Iterator[tuple[RarMemberInfo, Any]]:
    del settings  # limits enforced at inspect time
    with open_rar(path) as rf:
        for info in rf.infolist():
            raw_name = str(getattr(info, "filename", "") or "")
            try:
                rel = normalize_member_path(raw_name)
            except PathEscapeError:
                continue
            is_dir = bool(info.is_dir()) if callable(getattr(info, "is_dir", None)) else False
            yield (
                RarMemberInfo(
                    raw_name=raw_name,
                    relative_path=rel,
                    is_dir=is_dir or raw_name.endswith("/"),
                    is_symlink=bool(getattr(info, "is_symlink", lambda: False)()),
                    is_encrypted=bool(info.needs_password()) if callable(
                        getattr(info, "needs_password", None)
                    ) else False,
                    file_size=int(getattr(info, "file_size", 0) or 0),
                    compress_size=(
                        int(info.compress_size)
                        if getattr(info, "compress_size", None) is not None
                        else None
                    ),
                ),
                info,
            )


def extract_member_to_staging(
    rf: Any,
    info: Any,
    *,
    relative_path: str,
    staging_root: Path,
    settings: SourceIngestionSettings,
) -> tuple[Path, str, int]:
    """Stream one RAR member to staging. Returns (path, sha256, size)."""
    if callable(getattr(info, "needs_password", None)) and info.needs_password():
        raise IngestionError(
            "ARCHIVE_MEMBER_ENCRYPTED",
            "Encrypted RAR member",
            http_status=422,
            details={"relative_path": relative_path},
        )
    if callable(getattr(info, "is_symlink", None)) and info.is_symlink():
        raise IngestionError(
            "ARCHIVE_SYMLINK_REFUSED",
            "Symlink members are not followed",
            http_status=422,
            details={"relative_path": relative_path},
        )

    dest = staging_root / relative_path
    ensure_dir(dest.parent)
    assert_safe_staging_path(staging_root, dest.parent)
    assert_safe_staging_path(staging_root, dest)

    hasher = hashlib.sha256()
    total = 0
    tmp = dest.with_suffix(dest.suffix + ".partial")
    rarfile = _import_rarfile()
    try:
        with rf.open(info) as src, open(tmp, "wb") as out:
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
                declared = int(getattr(info, "file_size", 0) or 0)
                if declared and total > declared + 1024:
                    if total > max(declared * 2, declared + 1024 * 1024):
                        raise IngestionError(
                            "ARCHIVE_ZIP_BOMB",
                            "Extracted size greatly exceeds declared size",
                            http_status=422,
                            details={
                                "relative_path": relative_path,
                                "declared": declared,
                                "extracted": total,
                            },
                        )
                hasher.update(chunk)
                out.write(chunk)
        tmp.replace(dest)
        assert_safe_staging_path(staging_root, dest)
    except IngestionError:
        tmp.unlink(missing_ok=True)
        raise
    except rarfile.RarCannotExec as exc:
        tmp.unlink(missing_ok=True)
        raise IngestionError(
            "ARCHIVE_RAR_TOOL_MISSING",
            "RAR extraction backend is not available on this host",
            http_status=503,
            details={"relative_path": relative_path, "hint": probe_rar_tool().get("reason")},
        ) from exc
    except rarfile.BadRarFile as exc:
        tmp.unlink(missing_ok=True)
        raise IngestionError(
            "ARCHIVE_CORRUPT",
            f"Corrupt RAR member: {exc}",
            http_status=422,
            details={"relative_path": relative_path},
        ) from exc
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest, hasher.hexdigest(), total


def read_member_sample(rf: Any, info: Any, *, max_bytes: int = 8192) -> bytes:
    if callable(getattr(info, "needs_password", None)) and info.needs_password():
        return b""
    if callable(getattr(info, "is_symlink", None)) and info.is_symlink():
        return b""
    if callable(getattr(info, "is_dir", None)) and info.is_dir():
        return b""
    with rf.open(info) as src:
        return src.read(max_bytes)


def member_to_manifest(
    info: RarMemberInfo,
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
        metadata={"raw_name": info.raw_name, "archive_type": "rar"},
    )
