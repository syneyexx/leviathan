"""Multi-signal source type detection — never trust extension or browser MIME alone."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .binary import classify_bytes
from .types import DetectionConfidence, DetectionResult, SourceKind

# Extension → kind hints (not authoritative alone).
EXT_KIND: dict[str, SourceKind] = {
    ".pdf": SourceKind.DOCUMENT,
    ".txt": SourceKind.PLAIN_TEXT,
    ".md": SourceKind.DOCUMENT,
    ".markdown": SourceKind.DOCUMENT,
    ".rst": SourceKind.DOCUMENT,
    ".log": SourceKind.PLAIN_TEXT,
    ".html": SourceKind.DOCUMENT,
    ".htm": SourceKind.DOCUMENT,
    ".xhtml": SourceKind.DOCUMENT,
    ".xml": SourceKind.STRUCTURED,
    ".json": SourceKind.STRUCTURED,
    ".jsonl": SourceKind.DATASET,
    ".ndjson": SourceKind.DATASET,
    ".csv": SourceKind.STRUCTURED,
    ".tsv": SourceKind.STRUCTURED,
    ".yaml": SourceKind.STRUCTURED,
    ".yml": SourceKind.STRUCTURED,
    ".toml": SourceKind.STRUCTURED,
    ".ini": SourceKind.STRUCTURED,
    ".cfg": SourceKind.STRUCTURED,
    ".conf": SourceKind.STRUCTURED,
    ".properties": SourceKind.STRUCTURED,
    ".parquet": SourceKind.DATASET,
    ".docx": SourceKind.OFFICE,
    ".xlsx": SourceKind.OFFICE,
    ".pptx": SourceKind.OFFICE,
    ".png": SourceKind.IMAGE,
    ".jpg": SourceKind.IMAGE,
    ".jpeg": SourceKind.IMAGE,
    ".webp": SourceKind.IMAGE,
    ".tif": SourceKind.IMAGE,
    ".tiff": SourceKind.IMAGE,
    ".gif": SourceKind.IMAGE,
    ".zip": SourceKind.ARCHIVE,
    ".tar": SourceKind.ARCHIVE,
    ".gz": SourceKind.ARCHIVE,
    ".tgz": SourceKind.ARCHIVE,
    ".bz2": SourceKind.ARCHIVE,
    ".tbz2": SourceKind.ARCHIVE,
    ".xz": SourceKind.ARCHIVE,
    ".txz": SourceKind.ARCHIVE,
    ".7z": SourceKind.ARCHIVE,
    ".rar": SourceKind.ARCHIVE,
    ".py": SourceKind.SOURCE_CODE,
    ".pyw": SourceKind.SOURCE_CODE,
    ".js": SourceKind.SOURCE_CODE,
    ".mjs": SourceKind.SOURCE_CODE,
    ".cjs": SourceKind.SOURCE_CODE,
    ".jsx": SourceKind.SOURCE_CODE,
    ".ts": SourceKind.SOURCE_CODE,
    ".tsx": SourceKind.SOURCE_CODE,
    ".java": SourceKind.SOURCE_CODE,
    ".c": SourceKind.SOURCE_CODE,
    ".h": SourceKind.SOURCE_CODE,
    ".cc": SourceKind.SOURCE_CODE,
    ".cpp": SourceKind.SOURCE_CODE,
    ".cxx": SourceKind.SOURCE_CODE,
    ".hpp": SourceKind.SOURCE_CODE,
    ".cs": SourceKind.SOURCE_CODE,
    ".go": SourceKind.SOURCE_CODE,
    ".rs": SourceKind.SOURCE_CODE,
    ".rb": SourceKind.SOURCE_CODE,
    ".php": SourceKind.SOURCE_CODE,
    ".swift": SourceKind.SOURCE_CODE,
    ".kt": SourceKind.SOURCE_CODE,
    ".kts": SourceKind.SOURCE_CODE,
    ".scala": SourceKind.SOURCE_CODE,
    ".sh": SourceKind.SOURCE_CODE,
    ".bash": SourceKind.SOURCE_CODE,
    ".zsh": SourceKind.SOURCE_CODE,
    ".ps1": SourceKind.SOURCE_CODE,
    ".bat": SourceKind.SOURCE_CODE,
    ".cmd": SourceKind.SOURCE_CODE,
    ".sql": SourceKind.SOURCE_CODE,
    ".css": SourceKind.SOURCE_CODE,
    ".scss": SourceKind.SOURCE_CODE,
    ".sass": SourceKind.SOURCE_CODE,
    ".less": SourceKind.SOURCE_CODE,
}

# Extensionless / special project filenames.
SPECIAL_FILENAMES: dict[str, SourceKind] = {
    "readme": SourceKind.DOCUMENT,
    "readme.md": SourceKind.DOCUMENT,
    "license": SourceKind.PLAIN_TEXT,
    "licence": SourceKind.PLAIN_TEXT,
    "dockerfile": SourceKind.SOURCE_CODE,
    "makefile": SourceKind.SOURCE_CODE,
    "cmakelists.txt": SourceKind.SOURCE_CODE,
    "pyproject.toml": SourceKind.STRUCTURED,
    "package.json": SourceKind.STRUCTURED,
    "package-lock.json": SourceKind.STRUCTURED,
    "tsconfig.json": SourceKind.STRUCTURED,
    "requirements.txt": SourceKind.PLAIN_TEXT,
    "pipfile": SourceKind.STRUCTURED,
    "gemfile": SourceKind.SOURCE_CODE,
    "go.mod": SourceKind.STRUCTURED,
    "cargo.toml": SourceKind.STRUCTURED,
    ".gitignore": SourceKind.PLAIN_TEXT,
    ".dockerignore": SourceKind.PLAIN_TEXT,
}

MIME_BY_EXT: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".rst": "text/x-rst",
    ".log": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".xml": "application/xml",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".ndjson": "application/x-ndjson",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".parquet": "application/vnd.apache.parquet",
    ".py": "text/x-python",
    ".ts": "text/typescript",
    ".js": "text/javascript",
}

# Magic signatures (prefix match).
MAGIC_SIGNATURES: list[tuple[bytes, SourceKind, str, str]] = [
    (b"%PDF", SourceKind.DOCUMENT, "application/pdf", "pdf"),
    (b"PK\x03\x04", SourceKind.ARCHIVE, "application/zip", "zip_or_office"),
    (b"PK\x05\x06", SourceKind.ARCHIVE, "application/zip", "zip_empty"),
    (b"\x1f\x8b", SourceKind.ARCHIVE, "application/gzip", "gzip"),
    (b"BZh", SourceKind.ARCHIVE, "application/x-bzip2", "bzip2"),
    (b"\xfd7zXZ\x00", SourceKind.ARCHIVE, "application/x-xz", "xz"),
    (b"PAR1", SourceKind.DATASET, "application/vnd.apache.parquet", "parquet"),
    (b"\x89PNG\r\n\x1a\n", SourceKind.IMAGE, "image/png", "png"),
    (b"\xff\xd8\xff", SourceKind.IMAGE, "image/jpeg", "jpeg"),
    (b"RIFF", SourceKind.IMAGE, "image/webp", "riff"),  # may be webp/wav
    (b"II*\x00", SourceKind.IMAGE, "image/tiff", "tiff_le"),
    (b"MM\x00*", SourceKind.IMAGE, "image/tiff", "tiff_be"),
    (b"GIF87a", SourceKind.IMAGE, "image/gif", "gif"),
    (b"GIF89a", SourceKind.IMAGE, "image/gif", "gif"),
    (b"ustar", SourceKind.ARCHIVE, "application/x-tar", "tar"),  # offset 257 handled separately
    (b"7z\xbc\xaf'\x1c", SourceKind.ARCHIVE, "application/x-7z-compressed", "7z"),
    (b"Rar!\x1a\x07", SourceKind.ARCHIVE, "application/vnd.rar", "rar"),
]


def _ext(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    # Double extensions for tar.gz etc.
    lower = name.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(compound):
            return compound
    return Path(name).suffix.lower()


def _basename(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).name.lower()


def sniff_magic(sample: bytes) -> tuple[SourceKind | None, str | None, str | None]:
    if len(sample) >= 262 and sample[257:262] == b"ustar":
        return SourceKind.ARCHIVE, "application/x-tar", "tar"
    for magic, kind, mime, label in MAGIC_SIGNATURES:
        if sample.startswith(magic):
            return kind, mime, label
    return None, None, None


def detect_source_type(
    *,
    filename: str,
    sample: bytes | None = None,
    content_type_hint: str | None = None,
    allow_unknown_text: bool = True,
) -> DetectionResult:
    """Detect source kind using filename, extension, MIME hint, magic, and sniffing."""
    safe_name = PurePosixPath((filename or "upload.bin").replace("\\", "/")).name
    ext = _ext(safe_name)
    base = _basename(safe_name)
    signals: dict[str, object] = {
        "filename": safe_name,
        "extension": ext,
        "content_type_hint": content_type_hint,
    }

    # Dangerous double-extension tricks: .jpg.exe → trust final ext + magic.
    final_ext = Path(safe_name).suffix.lower()
    if final_ext in {".exe", ".dll", ".bat", ".cmd", ".ps1", ".scr", ".com"}:
        # Still detect via magic if it's actually something else, but default binary.
        signals["suspicious_executable_ext"] = True
        return DetectionResult(
            kind=SourceKind.BINARY,
            mime_type="application/octet-stream",
            extension=final_ext,
            confidence=DetectionConfidence.HIGH,
            signals={**signals, "reason": "executable_extension"},
            handler_hint="unsupported_binary",
            is_archive=False,
            is_text=False,
            is_binary=True,
        )
    magic_kind, magic_mime, magic_label = sniff_magic(sample or b"")
    if magic_label:
        signals["magic"] = magic_label

    special_kind = SPECIAL_FILENAMES.get(base)
    ext_kind = EXT_KIND.get(ext) or EXT_KIND.get(final_ext)

    # Office OpenXML is ZIP magic + office extension.
    if magic_label in {"zip_or_office", "zip_empty"} and final_ext in {".docx", ".xlsx", ".pptx"}:
        return DetectionResult(
            kind=SourceKind.OFFICE,
            mime_type=MIME_BY_EXT.get(final_ext, magic_mime),
            extension=final_ext,
            confidence=DetectionConfidence.HIGH,
            signals={**signals, "office_in_zip_container": True},
            handler_hint=final_ext.lstrip("."),
            is_archive=False,
            is_text=False,
            is_binary=True,
        )

    # Compound archives
    if ext in {".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}:
        return DetectionResult(
            kind=SourceKind.ARCHIVE,
            mime_type="application/gzip" if "gz" in ext else (
                "application/x-bzip2" if "bz" in ext else "application/x-xz"
            ),
            extension=ext,
            confidence=DetectionConfidence.HIGH,
            signals=signals,
            handler_hint="tar",
            is_archive=True,
            is_text=False,
            is_binary=True,
        )

    binary_info = classify_bytes(sample or b"") if sample is not None else None
    if binary_info:
        signals["binary_class"] = binary_info

    # Magic wins over mismatched extension for archives/pdf/images when strong.
    if magic_kind == SourceKind.ARCHIVE and final_ext not in {".docx", ".xlsx", ".pptx"}:
        # .gz alone may be single-file compression
        handler = "zip" if magic_label and magic_label.startswith("zip") else (
            "gzip" if magic_label == "gzip" and ext == ".gz" else "tar" if magic_label == "tar" else magic_label
        )
        if magic_label == "gzip" and ext in {".gz"} and not safe_name.lower().endswith((".tar.gz", ".tgz")):
            handler = "gzip"
        elif magic_label and magic_label.startswith("zip"):
            handler = "zip"
        return DetectionResult(
            kind=SourceKind.ARCHIVE,
            mime_type=magic_mime,
            extension=ext or final_ext,
            confidence=DetectionConfidence.HIGH,
            signals=signals,
            handler_hint=handler,
            is_archive=True,
            is_text=False,
            is_binary=True,
        )

    if magic_kind == SourceKind.DOCUMENT and (ext_kind == SourceKind.DOCUMENT or not ext_kind):
        return DetectionResult(
            kind=SourceKind.DOCUMENT,
            mime_type=magic_mime or MIME_BY_EXT.get(ext),
            extension=ext or ".pdf",
            confidence=DetectionConfidence.HIGH,
            signals=signals,
            handler_hint="pdf",
            is_archive=False,
            is_text=False,
            is_binary=True,
        )

    if magic_kind == SourceKind.IMAGE:
        # .jpg.exe must NOT become an image solely from naming — magic can still
        # identify real image bytes, but executable ext forces binary skip.
        if signals.get("suspicious_executable_ext"):
            return DetectionResult(
                kind=SourceKind.BINARY,
                mime_type="application/octet-stream",
                extension=final_ext,
                confidence=DetectionConfidence.HIGH,
                signals={**signals, "reason": "executable_extension_overrides_image_magic"},
                handler_hint="unsupported_binary",
                is_archive=False,
                is_text=False,
                is_binary=True,
            )
        return DetectionResult(
            kind=SourceKind.IMAGE,
            mime_type=magic_mime or MIME_BY_EXT.get(final_ext),
            extension=final_ext or ext,
            confidence=DetectionConfidence.HIGH,
            signals=signals,
            handler_hint="image",
            is_archive=False,
            is_text=False,
            is_binary=True,
        )

    if magic_kind == SourceKind.DATASET:
        return DetectionResult(
            kind=SourceKind.DATASET,
            mime_type=magic_mime,
            extension=ext or ".parquet",
            confidence=DetectionConfidence.HIGH,
            signals=signals,
            handler_hint="dataset",
            is_archive=False,
            is_text=False,
            is_binary=True,
        )

    kind = special_kind or ext_kind or SourceKind.UNKNOWN
    confidence = (
        DetectionConfidence.HIGH
        if special_kind or (ext_kind and magic_kind is None)
        else DetectionConfidence.MEDIUM
        if ext_kind
        else DetectionConfidence.LOW
    )

    # PDF extension must resemble PDF
    if ext == ".pdf":
        if sample is not None and not (sample.startswith(b"%PDF") or not sample):
            if not sample.startswith(b"%PDF"):
                return DetectionResult(
                    kind=SourceKind.BINARY,
                    mime_type="application/octet-stream",
                    extension=ext,
                    confidence=DetectionConfidence.HIGH,
                    signals={**signals, "reason": "pdf_extension_without_magic"},
                    handler_hint="unsupported_binary",
                    is_binary=True,
                )

    is_text = False
    is_binary = False
    if binary_info:
        is_text = bool(binary_info.get("is_text"))
        is_binary = bool(binary_info.get("is_binary"))

    if kind == SourceKind.UNKNOWN and allow_unknown_text and is_text:
        kind = SourceKind.PLAIN_TEXT
        confidence = DetectionConfidence.MEDIUM
        signals["unknown_text_fallback"] = True

    if kind == SourceKind.UNKNOWN and is_binary:
        kind = SourceKind.BINARY
        confidence = DetectionConfidence.HIGH

    if kind in {
        SourceKind.SOURCE_CODE,
        SourceKind.PLAIN_TEXT,
        SourceKind.DOCUMENT,
        SourceKind.STRUCTURED,
    } and kind != SourceKind.DOCUMENT:
        # Documents like PDF are binary containers; textish kinds should be text.
        if kind != SourceKind.DOCUMENT or ext not in {".pdf"}:
            is_text = True if is_text or sample is None else is_text

    if kind == SourceKind.ARCHIVE:
        is_archive = True
        is_binary = True
        is_text = False
    else:
        is_archive = False

    if kind in {SourceKind.IMAGE, SourceKind.BINARY, SourceKind.OFFICE, SourceKind.DATASET}:
        is_binary = True
        is_text = False

    handler_hint = None
    if kind == SourceKind.ARCHIVE:
        handler_hint = "zip" if ext == ".zip" else "tar" if "tar" in ext else "gzip" if ext == ".gz" else "archive"
    elif kind == SourceKind.DOCUMENT and ext == ".pdf":
        handler_hint = "pdf"
    elif kind == SourceKind.OFFICE:
        handler_hint = final_ext.lstrip(".")
    elif kind == SourceKind.DATASET:
        handler_hint = "dataset"
    elif kind == SourceKind.SOURCE_CODE:
        handler_hint = "source_code"
    elif kind == SourceKind.STRUCTURED:
        handler_hint = "structured"
    elif kind == SourceKind.PLAIN_TEXT:
        handler_hint = "plain_text"
    elif kind == SourceKind.IMAGE:
        handler_hint = "image"
    elif kind == SourceKind.BINARY:
        handler_hint = "unsupported_binary"

    mime = MIME_BY_EXT.get(ext) or MIME_BY_EXT.get(final_ext) or magic_mime
    if content_type_hint and not mime:
        mime = content_type_hint

    return DetectionResult(
        kind=kind,
        mime_type=mime,
        extension=ext or final_ext,
        confidence=confidence,
        signals=signals,
        handler_hint=handler_hint,
        is_archive=is_archive,
        is_text=is_text if kind != SourceKind.BINARY else False,
        is_binary=is_binary if kind != SourceKind.PLAIN_TEXT else False,
    )
