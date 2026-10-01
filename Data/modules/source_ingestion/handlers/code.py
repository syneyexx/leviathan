"""Source-code and plain-text handlers."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

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
from .documents import materialize_text_content

_CODE_EXTS = frozenset(
    {
        ".py", ".pyw", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
        ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs",
        ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".scala",
        ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".sql",
        ".css", ".scss", ".sass", ".less",
    }
)

_LANG_BY_EXT = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".cs": "csharp", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".ps1": "powershell", ".bat": "batch", ".cmd": "batch", ".sql": "sql",
    ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
}


class SourceCodeHandler:
    capabilities = HandlerCapabilities(
        handler_id="source_code",
        kinds=frozenset({SourceKind.SOURCE_CODE}),
        extensions=_CODE_EXTS,
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        if detection.kind == SourceKind.SOURCE_CODE:
            return True
        return detection.extension.lower() in _CODE_EXTS

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "source_code", "language": _LANG_BY_EXT.get(detection.extension.lower())}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        ref, digest = materialize_text_content(path, staging_root=staging_root)
        # Symbol extraction needs text; for large files skip in-memory AST (honest).
        lang = _LANG_BY_EXT.get(detection.extension.lower()) or _LANG_BY_EXT.get(Path(relative_path).suffix.lower())
        text_for_meta = ref.text if ref.text is not None else ""
        size = path.stat().st_size if path.is_file() else 0
        from .documents import INLINE_TEXT_BYTES

        if lang == "python" and ref.path is not None and size <= INLINE_TEXT_BYTES:
            text_for_meta = ref.read_text()
        elif lang == "python" and ref.path is not None and size > INLINE_TEXT_BYTES:
            text_for_meta = ""  # refuse full-string symbol pass on large sources
        elif ref.text is not None:
            text_for_meta = ref.text
        meta: dict[str, Any] = {
            "language": lang,
            "line_count": (
                text_for_meta.count("\n") + (1 if text_for_meta else 0)
                if text_for_meta or ref.text is not None
                else None
            ),
        }
        if lang == "python" and text_for_meta:
            meta.update(_python_symbols(text_for_meta))
        elif lang == "python" and size > INLINE_TEXT_BYTES:
            meta["symbols_skipped"] = "file_exceeds_inline_bound"
            meta["symbols_skipped_bytes"] = size
        # Honest text ingestion for other languages — no fragile regex AST claims.
        return NormalizedArtifact(
            source_kind=SourceKind.SOURCE_CODE,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/plain",
            parser=f"source_code:{lang or 'text'}",
            parser_version=PARSER_VERSION,
            content_hash=digest,
            content=ref,
            structured_metadata=meta,
            provenance={
                "relative_path": relative_path,
                "language": lang,
                "module_path": relative_path.replace("\\", "/"),
                "streaming": ref.path is not None,
                **{k: meta[k] for k in ("classes", "functions", "imports") if k in meta},
            },
            outcome=MemberOutcome.SUCCESS,
        )


class PlainTextHandler:
    capabilities = HandlerCapabilities(
        handler_id="plain_text",
        kinds=frozenset({SourceKind.PLAIN_TEXT}),
        extensions=frozenset({".txt", ".log", ".md", ".markdown", ".rst"}),
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        if detection.kind == SourceKind.PLAIN_TEXT:
            return True
        if detection.signals.get("unknown_text_fallback"):
            return True
        return False

    def inspect(self, path: Path, *, detection: DetectionResult, settings: SourceIngestionSettings) -> dict[str, Any]:
        return {"handler": "plain_text"}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        ref, digest = materialize_text_content(path, staging_root=staging_root)
        empty = path.stat().st_size == 0
        return NormalizedArtifact(
            source_kind=SourceKind.PLAIN_TEXT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/plain",
            parser="plain_text",
            parser_version=PARSER_VERSION,
            content_hash=digest,
            content=ref,
            provenance={
                "relative_path": relative_path,
                "detection_confidence": detection.confidence.value,
                "unknown_text_fallback": bool(detection.signals.get("unknown_text_fallback")),
                "streaming": ref.path is not None,
            },
            outcome=MemberOutcome.SUCCESS,
            warnings=["empty_file"] if empty else [],
            skip_reason="empty" if empty else None,
            # Empty files: explicit empty semantics — success with empty content, not silent skip.
        )


def _python_symbols(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    classes: list[str] = []
    functions: list[str] = []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append(mod)
    return {
        "classes": classes[:200],
        "functions": functions[:500],
        "imports": imports[:200],
    }
