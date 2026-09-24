"""Dataset routing + image + unsupported binary handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_text

from ..settings import SourceIngestionSettings
from ..types import (
    ContentRef,
    DetectionResult,
    MemberOutcome,
    NormalizedArtifact,
    PARSER_VERSION,
    SourceKind,
)
from .base import HandlerCapabilities
from .documents import _read_text_streaming
import hashlib


class DatasetRouteHandler:
    """Route dataset-like files to Dataset architecture instead of Brain text."""

    capabilities = HandlerCapabilities(
        handler_id="dataset",
        kinds=frozenset({SourceKind.DATASET}),
        extensions=frozenset({".parquet", ".jsonl", ".ndjson"}),
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        if detection.kind == SourceKind.DATASET:
            return True
        return detection.extension.lower() in self.capabilities.extensions

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "dataset", "size": path.stat().st_size}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        ext = detection.extension.lower() or Path(relative_path).suffix.lower()
        size = path.stat().st_size
        # Always route parquet. Route large jsonl/ndjson. Small jsonl may still be structured text.
        route = ext == ".parquet" or size >= settings.dataset_route_min_bytes or ext in settings.dataset_route_formats
        if ext in {".jsonl", ".ndjson"} and size < settings.dataset_route_min_bytes:
            # Small jsonl: ingest as structured text AND mark dataset-candidate.
            text = _read_text_streaming(path)
            return NormalizedArtifact(
                source_kind=SourceKind.STRUCTURED,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type=detection.mime_type or "application/x-ndjson",
                parser="jsonl_text",
                parser_version=PARSER_VERSION,
                content_hash=sha256_text(text),
                content=ContentRef(text=text),
                structured_metadata={"line_count": text.count("\n") + (1 if text else 0)},
                provenance={"relative_path": relative_path, "dataset_candidate": True},
                outcome=MemberOutcome.SUCCESS,
                warnings=["small_jsonl_ingested_as_text"],
            )
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 256)
                if not chunk:
                    break
                digest.update(chunk)
        return NormalizedArtifact(
            source_kind=SourceKind.DATASET,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type,
            parser="dataset_route",
            parser_version=PARSER_VERSION,
            content_hash=digest.hexdigest(),
            content=ContentRef(text=""),
            structured_metadata={"size_bytes": size, "format": ext.lstrip(".")},
            provenance={"relative_path": relative_path, "raw_path": str(path), "size_bytes": size},
            outcome=MemberOutcome.ROUTED,
            route_target="dataset",
            skip_reason="routed_to_dataset",
        )


class ImageHandler:
    capabilities = HandlerCapabilities(
        handler_id="image",
        kinds=frozenset({SourceKind.IMAGE}),
        extensions=frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif"}),
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        return detection.kind == SourceKind.IMAGE

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "image", "ocr": False}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        # Honest: no OCR/vision unless genuinely configured. Never fabricate OCR.
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 256)
                if not chunk:
                    break
                digest.update(chunk)
        return NormalizedArtifact(
            source_kind=SourceKind.IMAGE,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type,
            parser="image_metadata",
            parser_version=PARSER_VERSION,
            content_hash=digest.hexdigest(),
            content=ContentRef(text=""),
            structured_metadata={"size_bytes": path.stat().st_size},
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SKIPPED,
            skip_reason="ocr_unavailable",
            unsupported_features=["ocr", "vision"],
        )


class UnsupportedBinaryHandler:
    capabilities = HandlerCapabilities(
        handler_id="unsupported_binary",
        kinds=frozenset({SourceKind.BINARY, SourceKind.UNKNOWN}),
        extensions=frozenset(),
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        return detection.kind in {SourceKind.BINARY, SourceKind.UNKNOWN} or detection.is_binary

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "unsupported_binary"}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 256)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return NormalizedArtifact(
            source_kind=SourceKind.BINARY,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "application/octet-stream",
            parser="unsupported_binary",
            parser_version=PARSER_VERSION,
            content_hash=digest.hexdigest(),
            content=ContentRef(text=""),
            structured_metadata={"size_bytes": size},
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SKIPPED,
            skip_reason="binary",
        )
