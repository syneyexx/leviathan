"""Structured data handlers — JSON/JSONL/CSV/YAML/TOML/INI/etc."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from configparser import ConfigParser
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


class StructuredDataHandler:
    capabilities = HandlerCapabilities(
        handler_id="structured",
        kinds=frozenset({SourceKind.STRUCTURED}),
        extensions=frozenset(
            {
                ".json",
                ".csv",
                ".tsv",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
                ".cfg",
                ".conf",
                ".properties",
                ".xml",
            }
        ),
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        if detection.kind == SourceKind.STRUCTURED:
            return True
        return detection.extension.lower() in self.capabilities.extensions

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "structured", "extension": detection.extension}

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
        try:
            if ext == ".json":
                return self._json(path, relative_path=relative_path, mime=detection.mime_type)
            if ext in {".csv", ".tsv"}:
                return self._csv(path, relative_path=relative_path, delim="," if ext == ".csv" else "\t", mime=detection.mime_type)
            if ext in {".yaml", ".yml"}:
                return self._yaml(path, relative_path=relative_path)
            if ext == ".toml":
                return self._toml(path, relative_path=relative_path)
            if ext in {".ini", ".cfg", ".conf", ".properties"}:
                return self._ini(path, relative_path=relative_path, ext=ext)
            if ext == ".xml":
                text = _read_text_streaming(path)
                return NormalizedArtifact(
                    source_kind=SourceKind.STRUCTURED,
                    title=Path(relative_path).name,
                    relative_path=relative_path,
                    mime_type="application/xml",
                    parser="xml_text",
                    parser_version=PARSER_VERSION,
                    content_hash=sha256_text(text),
                    content=ContentRef(text=text),
                    provenance={"relative_path": relative_path},
                    outcome=MemberOutcome.SUCCESS,
                )
            text = _read_text_streaming(path)
            return NormalizedArtifact(
                source_kind=SourceKind.STRUCTURED,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type=detection.mime_type or "text/plain",
                parser="structured_text",
                parser_version=PARSER_VERSION,
                content_hash=sha256_text(text),
                content=ContentRef(text=text),
                provenance={"relative_path": relative_path},
                outcome=MemberOutcome.SUCCESS,
            )
        except Exception as exc:  # noqa: BLE001
            return NormalizedArtifact(
                source_kind=SourceKind.STRUCTURED,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type=detection.mime_type,
                parser="structured",
                parser_version=PARSER_VERSION,
                content_hash=hashlib.sha256(path.read_bytes()[:1024]).hexdigest(),
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code="SOURCE_PARSE_FAILED",
                skip_reason=str(exc)[:200],
                retryable=True,
            )

    def _json(self, path: Path, *, relative_path: str, mime: str | None) -> NormalizedArtifact:
        text = _read_text_streaming(path)
        data = json.loads(text)
        pretty = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        return NormalizedArtifact(
            source_kind=SourceKind.STRUCTURED,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=mime or "application/json",
            parser="json",
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(pretty),
            content=ContentRef(text=pretty),
            structured_metadata={"structure_type": type(data).__name__},
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SUCCESS,
        )

    def _csv(self, path: Path, *, relative_path: str, delim: str, mime: str | None) -> NormalizedArtifact:
        text = _read_text_streaming(path)
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = [[str(c) for c in row] for row in reader]
        if not rows:
            raise ValueError("CSV contained no rows")
        header = rows[0]
        lines = [delim.join(header) if False else ", ".join(header)]
        for row_idx, row in enumerate(rows[1:], start=2):
            pairs = []
            for i, cell in enumerate(row):
                key = header[i] if i < len(header) else f"col_{i}"
                pairs.append(f"{key}={cell}")
            lines.append("; ".join(pairs))
        body = "\n".join(lines)
        return NormalizedArtifact(
            source_kind=SourceKind.STRUCTURED,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=mime or ("text/csv" if delim == "," else "text/tab-separated-values"),
            parser="csv" if delim == "," else "tsv",
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(body),
            content=ContentRef(text=body),
            structured_metadata={"headers": header, "row_count": max(0, len(rows) - 1)},
            provenance={
                "relative_path": relative_path,
                "row_count": max(0, len(rows) - 1),
                "headers": header,
            },
            outcome=MemberOutcome.SUCCESS,
        )

    def _yaml(self, path: Path, *, relative_path: str) -> NormalizedArtifact:
        text = _read_text_streaming(path)
        structure = None
        try:
            import yaml  # type: ignore[import-not-found]

            structure = yaml.safe_load(text)
            pretty = text if structure is None else json.dumps(structure, ensure_ascii=False, indent=2, default=str)
        except ImportError:
            pretty = text
        return NormalizedArtifact(
            source_kind=SourceKind.STRUCTURED,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/yaml",
            parser="yaml" if structure is not None else "yaml_text",
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(pretty),
            content=ContentRef(text=pretty),
            structured_metadata={"parsed": structure is not None},
            provenance={"relative_path": relative_path},
            warnings=[] if structure is not None else ["PyYAML not installed; stored as text"],
            outcome=MemberOutcome.SUCCESS,
        )

    def _toml(self, path: Path, *, relative_path: str) -> NormalizedArtifact:
        text = _read_text_streaming(path)
        structure = None
        try:
            import tomllib

            structure = tomllib.loads(text)
            pretty = json.dumps(structure, ensure_ascii=False, indent=2, default=str)
        except Exception:  # noqa: BLE001
            pretty = text
        return NormalizedArtifact(
            source_kind=SourceKind.STRUCTURED,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/toml",
            parser="toml",
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(pretty),
            content=ContentRef(text=pretty),
            structured_metadata={"parsed": structure is not None},
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SUCCESS,
        )

    def _ini(self, path: Path, *, relative_path: str, ext: str) -> NormalizedArtifact:
        text = _read_text_streaming(path)
        parser = ConfigParser()
        try:
            parser.read_string(text)
            data = {s: dict(parser.items(s)) for s in parser.sections()}
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            parsed = True
        except Exception:  # noqa: BLE001
            pretty = text
            parsed = False
        return NormalizedArtifact(
            source_kind=SourceKind.STRUCTURED,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="text/plain",
            parser="ini" if parsed else "ini_text",
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(pretty),
            content=ContentRef(text=pretty),
            provenance={"relative_path": relative_path, "extension": ext},
            outcome=MemberOutcome.SUCCESS,
        )
