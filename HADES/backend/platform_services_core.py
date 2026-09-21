from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.robotparser
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup

from platform_db import PlatformDatabase, utc_now

_LOG = logging.getLogger("hades.plugin_manager")


def knowledge_ingest_verified(result: Any) -> bool:
    """True only when a knowledge ingest payload did not report verification failure."""
    if not isinstance(result, dict) or not result:
        return False
    status = str(result.get("status") or "")
    if status in {"verification_failed", "error", "failed"}:
        return False
    persistence = result.get("persistence")
    if isinstance(persistence, dict) and persistence.get("verification_passed") is False:
        return False
    # Empty ingest (0 chunks) must not count as verified success.
    if "chunks" in result:
        try:
            if int(result.get("chunks") or 0) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


SUPPORTED_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".sql", ".html", ".htm", ".xml", ".log",
    ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".ps1", ".bat", ".sh",
}
DOCUMENT_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | {".pdf", ".docx", ".epub", ".pptx", ".xlsx", ".xlsm"}

# Defaults preserved from pre-control-plane behavior; runtime uses helpers below.
MAX_TEXT_BYTES = 40 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_PLUGIN_UPLOAD_BYTES = 256 * 1024 * 1024


def _setting(name: str, fallback: Any = None) -> Any:
    """Resolve a Control Plane setting by id; fall back when control is unavailable."""
    try:
        from control.service import resolve_setting

        return resolve_setting(name, default=fallback)
    except Exception:
        return fallback


def _fs_limit(name: str, fallback: int) -> int | None:
    """Resolve a filesystem safety ceiling from the control plane when available."""
    return _setting(name, fallback)


def max_text_bytes() -> int | None:
    return _fs_limit("filesystem.max_text_bytes", MAX_TEXT_BYTES)


def max_archive_files() -> int | None:
    return _fs_limit("filesystem.max_archive_files", MAX_ARCHIVE_FILES)


def max_archive_bytes() -> int | None:
    return _fs_limit("filesystem.max_archive_bytes", MAX_ARCHIVE_BYTES)


def max_plugin_upload_bytes() -> int | None:
    return _fs_limit("filesystem.max_plugin_upload_bytes", MAX_PLUGIN_UPLOAD_BYTES)


PLUGIN_UPLOAD_SKIP_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".turbo",
    ".next",
    "target",
    ".tox",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned[:100] or "plugin"


_UNSET = object()


def chunk_text(text: str, target_chars: int | None = None, overlap_chars: int | None = None) -> list[dict[str, Any]]:
    if target_chars is None:
        target_chars = int(_setting("knowledge.chunk_target_chars", 5000) or 5000)
    if overlap_chars is None:
        overlap_chars = int(_setting("knowledge.chunk_overlap_chars", 500) or 0)
    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars * 2:
            if current:
                chunks.append(current)
                current = ""
            step = max(500, target_chars - overlap_chars)
            for start in range(0, len(paragraph), step):
                chunks.append(paragraph[start : start + target_chars])
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    result = []
    for content in chunks:
        result.append(
            {
                "content": content,
                "heading": "",
                "content_hash": sha256_bytes(content.encode("utf-8", "ignore")),
                "token_estimate": max(1, len(content) // 4),
            }
        )
    return result


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    limit = max_text_bytes()
    if limit is not None and len(data) > int(limit):
        raise ValueError(f"Bestand is te groot voor tekstextractie ({len(data)} bytes).")
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_document(path: Path) -> tuple[str, dict[str, Any]]:
    extension = path.suffix.lower()
    metadata: dict[str, Any] = {"extension": extension, "size_bytes": path.stat().st_size}
    if extension in SUPPORTED_TEXT_EXTENSIONS:
        text = _read_text_file(path)
        if extension in {".html", ".htm", ".xml"}:
            soup = BeautifulSoup(text, "html.parser")
            for node in soup(["script", "style", "noscript", "svg"]):
                node.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else path.name
            metadata["title"] = title
            text = soup.get_text("\n", strip=True)
        return text, metadata
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF-ondersteuning ontbreekt. Installeer pypdf.") from exc
        reader = PdfReader(str(path))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            pages.append(f"[Pagina {page_number}]\n{page.extract_text() or ''}")
        metadata["pages"] = len(reader.pages)
        if reader.metadata:
            metadata["pdf_metadata"] = {str(key): str(value) for key, value in reader.metadata.items()}
        return "\n\n".join(pages), metadata
    if extension == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX-ondersteuning ontbreekt. Installeer python-docx.") from exc
        document = Document(str(path))
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                paragraphs.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n\n".join(paragraphs), metadata
    if extension == ".pptx":
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("PPTX-ondersteuning ontbreekt. Installeer python-pptx.") from exc
        presentation = Presentation(str(path))
        slides: list[str] = []
        for index, slide in enumerate(presentation.slides, start=1):
            parts = []
            for shape in slide.shapes:
                text = getattr(shape, "text", "")
                if text and text.strip():
                    parts.append(text.strip())
            if parts:
                slides.append(f"[Slide {index}]\n" + "\n".join(parts))
        metadata["slides"] = len(presentation.slides)
        return "\n\n".join(slides), metadata
    if extension in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("XLSX-ondersteuning ontbreekt. Installeer openpyxl.") from exc
        workbook = load_workbook(str(path), read_only=True, data_only=True)
        parts: list[str] = []
        try:
            for sheet in workbook.worksheets:
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    values = ["" if value is None else str(value) for value in row]
                    if any(value.strip() for value in values):
                        rows.append(" | ".join(values))
                if rows:
                    parts.append(f"[Werkblad: {sheet.title}]\n" + "\n".join(rows))
            metadata["worksheets"] = len(workbook.worksheets)
        finally:
            workbook.close()
        return "\n\n".join(parts), metadata
    if extension == ".epub":
        parts: list[str] = []
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                data = archive.read(name)
                soup = BeautifulSoup(data, "html.parser")
                for node in soup(["script", "style", "nav", "svg"]):
                    node.decompose()
                text = soup.get_text("\n", strip=True)
                if text:
                    parts.append(text)
        if not parts:
            raise ValueError("EPUB bevat geen leesbare HTML/XHTML-inhoud.")
        metadata["sections"] = len(parts)
        return "\n\n".join(parts), metadata
    raise ValueError(f"Niet-ondersteund documenttype: {extension or '(geen extensie)'}")


class KnowledgeService:
    def __init__(self, db: PlatformDatabase, data_root: Path) -> None:
        self.db = db
        self.data_root = data_root
        self.library_root = data_root / "knowledge" / "raw"
        self.upload_root = data_root / "uploads"
        self.evidence_root = data_root / "evidence" / "web"
        self.library_root.mkdir(parents=True, exist_ok=True)
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.evidence_root.mkdir(parents=True, exist_ok=True)

    def ingest_text(self, *, title: str, text: str, source_type: str, uri: str, metadata: dict[str, Any] | None = None, local_path: str | None = None) -> dict[str, Any]:
        from execution_truth import make_persistence_result, verify_rows_exist

        if not (text or "").strip():
            persistence = make_persistence_result(
                entity_type="knowledge",
                requested_count=1,
                inserted_ids=[],
                verified_ids=[],
                error="empty_knowledge_text",
                error_type="EmptyIngestError",
                metadata={"uri": uri, "source_type": source_type},
            )
            return {
                "title": title,
                "source_type": source_type,
                "uri": uri,
                "chunks": 0,
                "unchanged": False,
                "reimported": False,
                "persistence": persistence.to_dict(),
                "status": "verification_failed",
                "error": "empty_knowledge_text",
            }
        content_hash = sha256_bytes(text.encode("utf-8", "ignore"))
        existing = None
        try:
            existing = self.db.get_knowledge_source_by_uri(source_type, uri)
        except Exception:
            existing = None
        if existing and existing.get("content_hash") == content_hash and existing.get("status") == "ready":
            chunks = self.db.list_knowledge_chunks(existing["id"], limit=5000)
            persistence = verify_rows_exist(
                entity_type="knowledge",
                ids=[str(existing["id"])],
                fetch_one=self.db.get_knowledge_source,
                required_fields=["id", "uri", "status"],
                metadata={"unchanged": True, "chunks": len(chunks)},
            )
            if len(chunks) == 0:
                persistence = make_persistence_result(
                    entity_type="knowledge",
                    requested_count=1,
                    inserted_ids=[str(existing["id"])],
                    verified_ids=[],
                    error="empty_knowledge_chunks",
                    error_type="EmptyIngestError",
                    metadata={"uri": uri, "source_type": source_type, "unchanged": True},
                )
                return {
                    **existing,
                    "chunks": 0,
                    "unchanged": True,
                    "reimported": False,
                    "persistence": persistence.to_dict(),
                    "status": "verification_failed",
                    "error": "empty_knowledge_chunks",
                }
            return {
                **existing,
                "chunks": len(chunks),
                "unchanged": True,
                "reimported": False,
                "persistence": persistence.to_dict(),
            }
        previous_hash = (existing or {}).get("content_hash")
        try:
            chunks = chunk_text(text)
            source = self.db.upsert_knowledge_with_chunks(
                title=title,
                source_type=source_type,
                uri=uri,
                chunks=chunks,
                local_path=local_path,
                content_hash=content_hash,
                metadata={**(metadata or {}), "role": "knowledge", "content_is_data_not_policy": True},
                status="ready",
            )
            chunk_count = int(source.pop("chunks_written", 0) or 0)
        except Exception as exc:
            from execution_truth import PersistenceError

            persistence = make_persistence_result(
                entity_type="knowledge",
                requested_count=1,
                inserted_ids=[],
                verified_ids=[],
                error=str(exc),
                error_type=type(exc).__name__,
                metadata={"uri": uri, "source_type": source_type},
            )
            raise PersistenceError(f"knowledge_ingest_failed:{exc}") from exc
        # Read-after-write: source row + chunk rows must exist after commit.
        persistence = verify_rows_exist(
            entity_type="knowledge",
            ids=[str(source["id"])],
            fetch_one=self.db.get_knowledge_source,
            required_fields=["id", "uri", "status"],
            metadata={"uri": uri, "source_type": source_type, "content_hash": content_hash},
        )
        verified_chunks = self.db.list_knowledge_chunks(source["id"], limit=5000)
        if chunk_count <= 0 or len(verified_chunks) == 0:
            persistence = make_persistence_result(
                entity_type="knowledge",
                requested_count=1,
                inserted_ids=[str(source["id"])],
                verified_ids=[],
                error="empty_knowledge_chunks" if chunk_count <= 0 else "knowledge_chunks_missing_after_write",
                error_type="EmptyIngestError" if chunk_count <= 0 else "PersistenceVerificationError",
                metadata={"expected_chunks": chunk_count},
            )
        elif persistence.verification_passed:
            persistence.metadata["chunks"] = len(verified_chunks)
        invalidated: list[dict[str, Any]] = []
        if existing and previous_hash and previous_hash != content_hash:
            # Only dependent conclusions are marked for recheck — no full research re-run.
            try:
                from claim_register import default_claim_register

                evidence_keys = [source["id"], uri, f"knowledge:{source['id']}", f"{source_type}:{uri}"]
                for key in evidence_keys:
                    invalidated.extend(
                        default_claim_register.mark_dependent_claims_for_recheck(
                            evidence_id=str(key),
                            previous_hash=str(previous_hash),
                            new_hash=str(content_hash),
                            reason="evidence_content_hash_changed",
                        )
                    )
            except Exception:
                invalidated = []
        if not persistence.verification_passed:
            # Do not present an unverified insert as a successful knowledge update.
            return {
                **source,
                "chunks": chunk_count,
                "unchanged": False,
                "reimported": bool(existing),
                "previous_content_hash": previous_hash,
                "dependent_claims_marked_for_recheck": len(invalidated),
                "recheck_claim_ids": [c.get("id") for c in invalidated if c.get("id")],
                "persistence": persistence.to_dict(),
                "status": "verification_failed",
            }
        return {
            **source,
            "chunks": chunk_count,
            "unchanged": False,
            "reimported": bool(existing),
            "previous_content_hash": previous_hash,
            "dependent_claims_marked_for_recheck": len(invalidated),
            "recheck_claim_ids": [c.get("id") for c in invalidated if c.get("id")],
            "persistence": persistence.to_dict(),
        }

    def ingest_file(self, path: Path, workspace_id: str | None = None) -> dict[str, Any]:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        extension = path.suffix.lower()
        if extension not in DOCUMENT_EXTENSIONS:
            record = self.db.upsert_indexed_file(
                workspace_id=workspace_id,
                path=str(path),
                name=path.name,
                extension=extension,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                content_hash=None,
                source_id=None,
                status="unsupported",
                error=f"Niet-ondersteund type: {extension or 'geen extensie'}",
            )
            return {"file": record, "source": None, "chunks": 0}
        file_hash = sha256_file(path)
        existing = next((item for item in self.db.list_indexed_files(workspace_id, 10_000) if item["path"] == str(path)), None)
        if existing and existing.get("content_hash") == file_hash and existing.get("status") == "ready":
            source_id = existing.get("source_id")
            chunks = self.db.list_knowledge_chunks(source_id, limit=5000) if source_id else []
            if not chunks:
                # Stale ready+empty must not short-circuit as successful unchanged.
                pass
            else:
                return {
                    "file": existing,
                    "source": self.db.get_knowledge_source(source_id) if source_id else None,
                    "chunks": len(chunks),
                    "unchanged": True,
                }
        try:
            text, metadata = extract_document(path)
            source = self.ingest_text(
                title=metadata.get("title") or path.name,
                text=text,
                source_type="file",
                uri=str(path),
                local_path=str(path),
                metadata={**metadata, "sha256": file_hash},
            )
            persistence = source.get("persistence") if isinstance(source, dict) else None
            verified = str(source.get("status") or "") != "verification_failed" and not (
                isinstance(persistence, dict) and persistence.get("verification_passed") is False
            )
            record = self.db.upsert_indexed_file(
                workspace_id=workspace_id,
                path=str(path),
                name=path.name,
                extension=extension,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                content_hash=file_hash,
                source_id=source.get("id"),
                status="ready" if verified else "error",
                error=None if verified else "knowledge_verification_failed",
            )
            return {
                "file": record,
                "source": source,
                "chunks": int(source.get("chunks") or 0),
                **({} if verified else {"error": "knowledge_verification_failed"}),
            }
        except Exception as exc:
            record = self.db.upsert_indexed_file(
                workspace_id=workspace_id,
                path=str(path),
                name=path.name,
                extension=extension,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                content_hash=file_hash,
                source_id=None,
                status="error",
                error=str(exc),
            )
            return {"file": record, "source": None, "chunks": 0, "error": str(exc)}

    def ingest_folder(self, folder: Path, name: str | None = None, recursive: bool = True, max_files: int = 5000) -> dict[str, Any]:
        root = folder.expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        workspace = self.db.upsert_workspace(name or root.name or "Workspace", str(root))
        files: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
        processed = ready = failed = unsupported = unchanged = skipped_secret = 0
        skipped_secret_paths: list[dict[str, str]] = []
        try:
            from conversation_pins import is_blocked_pin_path
        except Exception:  # pragma: no cover - defensive import
            is_blocked_pin_path = None  # type: ignore[assignment]
        for path in files:
            if not path.is_file():
                continue
            if processed >= max_files:
                break
            if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            if is_blocked_pin_path is not None:
                blocked, reason = is_blocked_pin_path(path)
                if blocked:
                    skipped_secret += 1
                    if len(skipped_secret_paths) < 40:
                        skipped_secret_paths.append({"path": str(path), "reason": reason})
                    continue
            processed += 1
            result = self.ingest_file(path, workspace["id"])
            status = result["file"]["status"]
            ready += status == "ready"
            failed += status == "error"
            unsupported += status == "unsupported"
            unchanged += bool(result.get("unchanged"))
        return {
            "workspace": workspace,
            "processed": processed,
            "ready": ready,
            "failed": failed,
            "unsupported": unsupported,
            "unchanged": unchanged,
            "skipped_secret": skipped_secret,
            "skipped_secret_paths": skipped_secret_paths,
            "limited": processed >= max_files,
            # Zero successfully ingested items is not a green success signal.
            "success": ready > 0,
        }

    def file_detail(self, file_id: str, chunk_limit: int = 40) -> dict[str, Any] | None:
        record = self.db.get_indexed_file(file_id)
        if not record:
            return None
        source = self.db.get_knowledge_source(record["source_id"]) if record.get("source_id") else None
        chunks = self.db.list_knowledge_chunks(record["source_id"], chunk_limit) if record.get("source_id") else []
        return {"file": record, "source": source, "chunks": chunks}

    def reindex_file(self, file_id: str) -> dict[str, Any]:
        record = self.db.get_indexed_file(file_id)
        if not record:
            raise FileNotFoundError(file_id)
        path = Path(str(record["path"]))
        if not path.is_file():
            raise FileNotFoundError(path)
        return self.ingest_file(path, record.get("workspace_id"))

    def rescan_workspace(self, workspace_id: str, *, recursive: bool = True, max_files: int = 5000) -> dict[str, Any]:
        workspace = self.db.get_workspace(workspace_id)
        if not workspace:
            raise FileNotFoundError(workspace_id)
        return self.ingest_folder(Path(workspace["root_path"]), workspace["name"], recursive, max_files)

    def remove_indexed_file(self, file_id: str, *, delete_upload: bool = True) -> dict[str, Any]:
        record = self.db.delete_indexed_file(file_id, remove_knowledge=True)
        if not record:
            raise FileNotFoundError(file_id)
        path = Path(str(record.get("path") or ""))
        if delete_upload and path.is_file():
            try:
                resolved = path.resolve()
                upload_root = self.upload_root.resolve()
                if str(resolved).startswith(str(upload_root) + os.sep) or resolved == upload_root:
                    resolved.unlink(missing_ok=True)
            except OSError:
                pass
        return record

    def remove_workspace(self, workspace_id: str) -> dict[str, Any]:
        removed = self.db.delete_workspace(workspace_id, remove_files=True)
        if not removed:
            raise FileNotFoundError(workspace_id)
        return removed

    def store_web_snapshot(self, url: str, raw_html: str) -> tuple[Path, str]:
        data = raw_html.encode("utf-8", "replace")
        digest = sha256_bytes(data)
        target = self.evidence_root / f"{digest}.html"
        if not target.exists():
            target.write_bytes(data)
        return target, digest

    def store_upload(self, filename: str, data: bytes) -> Path:
        if len(data) > int((_fs_limit("filesystem.max_download_bytes", 250 * 1024 * 1024) or 250 * 1024 * 1024)):
            raise ValueError("Upload is groter dan 250 MB.")
        target = self.upload_root / safe_name(Path(filename).name)
        if target.exists():
            target = self.upload_root / f"{target.stem}-{sha256_bytes(data)[:10]}{target.suffix}"
        target.write_bytes(data)
        return target

    def index_conversation(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        *,
        include_assistant: bool = False,
        verified_write_back: bool = False,
        eligible_assistant_ids: set[str] | frozenset[str] | None = None,
        require_assistant_verified_meta: bool = False,
        exchange_uri: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild a conversation knowledge source from the authoritative raw transcript.

        Rebuilding from source messages avoids recursively re-chunking overlapping chunks.
        Assistant prose is excluded by default so unverified model claims are not promoted
        into Knowledge. When ``include_assistant`` is True, callers should pass
        ``eligible_assistant_ids`` and/or message metadata ``verification.eligible`` so a
        newly verified turn does not promote older unchecked assistant text.
        Returns a PersistenceResult-bearing dict — never invents success.
        """
        from execution_truth import make_persistence_result

        if not verified_write_back and not include_assistant:
            # Transcript index of user turns only — still not a "knowledge_updated" product claim.
            pass
        uri = exchange_uri or f"conversation:{conversation_id}"
        labels = {"user": "Gebruiker", "assistant": "HADES", "system": "Systeem"}
        parts = []
        included_assistant_ids: list[str] = []
        for message in messages:
            role_key = str(message.get("role", ""))
            if role_key == "assistant":
                if not include_assistant:
                    continue
                msg_id = str(message.get("id") or "").strip()
                meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                verified_meta = meta.get("verification") if isinstance(meta.get("verification"), dict) else {}
                eligible = False
                if eligible_assistant_ids is not None:
                    eligible = bool(msg_id and msg_id in eligible_assistant_ids)
                elif require_assistant_verified_meta:
                    eligible = bool(
                        verified_meta.get("eligible")
                        or verified_meta.get("factual_verified")
                        or meta.get("verified_write_back")
                        or message.get("verified_write_back")
                    )
                elif message.get("verified_write_back") or meta.get("verified_write_back"):
                    eligible = True
                else:
                    # Conservative default: without eligibility metadata, skip historical
                    # assistants even when include_assistant=True (prevents whole-transcript
                    # promotion from one successful current verification).
                    eligible = bool(message.get("_force_include_assistant"))
                if not eligible:
                    continue
                if msg_id:
                    included_assistant_ids.append(msg_id)
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            role = labels.get(role_key, role_key.title() or "Bericht")
            parts.append(f"{role}:\n{content}")
        text = "\n\n".join(parts)
        if not text.strip():
            return {
                "conversation_id": conversation_id,
                "indexed": False,
                "persistence": make_persistence_result(
                    entity_type="knowledge",
                    requested_count=0,
                    inserted_ids=[],
                    verified_ids=[],
                    metadata={"reason": "empty_transcript", "conversation_id": conversation_id},
                ).to_dict(),
            }
        result = self.ingest_text(
            title=f"Gesprek {conversation_id}",
            text=text,
            source_type="conversation",
            uri=uri,
            metadata={
                "conversation_id": conversation_id,
                "include_assistant": bool(include_assistant),
                "verified_write_back": bool(verified_write_back),
                "role": "conversation_transcript" if not verified_write_back else "verified_exchange",
                "included_assistant_ids": included_assistant_ids,
                **(provenance or {}),
            },
        )
        return {
            **result,
            "conversation_id": conversation_id,
            "indexed": bool((result.get("persistence") or {}).get("verification_passed")),
            "included_assistant_ids": included_assistant_ids,
        }

    def index_conversation_exchange(
        self,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        *,
        verified_write_back: bool = False,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
        branch_id: str | None = None,
        verification_ref: str | None = None,
    ) -> dict[str, Any]:
        """Index one user/assistant exchange. Verified path includes only this assistant turn."""
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text,
            "id": assistant_message_id or "pending-assistant",
            "metadata": {
                "verification": {"eligible": bool(verified_write_back)},
                "verified_write_back": bool(verified_write_back),
            },
            "_force_include_assistant": bool(verified_write_back),
        }
        exchange_uri = (
            f"conversation:{conversation_id}:exchange:{user_message_id or 'latest'}"
            if verified_write_back
            else f"conversation:{conversation_id}"
        )
        return self.index_conversation(
            conversation_id,
            [
                {"role": "user", "content": user_text, "id": user_message_id},
                assistant_msg,
            ],
            include_assistant=bool(verified_write_back),
            verified_write_back=bool(verified_write_back),
            eligible_assistant_ids=(
                {str(assistant_message_id or "pending-assistant")} if verified_write_back else None
            ),
            exchange_uri=exchange_uri,
            provenance={
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "branch_id": branch_id,
                "verification_ref": verification_ref,
            },
        )


# Wave 28: WebResearchService / CrawlResult live in web_research_service.py
from web_research_service import CrawlResult, WebResearchService  # noqa: E402

class ResearchRunner:
    DEPTH_CONFIG = {
        "quick": {"search_queries": 1, "urls_per_query": 3, "max_sources": 5, "rounds": 1, "crawl_pages": 2, "crawl_depth": 0, "agents": 1},
        "standard": {"search_queries": 2, "urls_per_query": 4, "max_sources": 10, "rounds": 1, "crawl_pages": 5, "crawl_depth": 1, "agents": 1},
        "deep": {"search_queries": 3, "urls_per_query": 5, "max_sources": 22, "rounds": 2, "crawl_pages": 10, "crawl_depth": 1, "agents": 2},
        "expert": {"search_queries": 8, "urls_per_query": 10, "max_sources": 180, "rounds": 6, "crawl_pages": 80, "crawl_depth": 3, "agents": 3},
    }

    def __init__(self, db: PlatformDatabase, knowledge: KnowledgeService, web: WebResearchService, lm_resolver: Any, lm_client_factory: Any, payload_builder: Any, network_policy: Any, runtime_settings: Any | None = None) -> None:
        self.db = db
        self.knowledge = knowledge
        self.web = web
        self.lm_resolver = lm_resolver
        self.lm_client_factory = lm_client_factory
        self.payload_builder = payload_builder
        self.network_policy = network_policy
        self.runtime_settings = runtime_settings or (lambda: {})
        self.jobs: dict[str, asyncio.Task[None]] = {}

    def schedule(self, project_id: str) -> None:
        job = self.jobs.get(project_id)
        if job and not job.done():
            return
        task = asyncio.create_task(self._run(project_id), name=f"hades-research-{project_id}")
        self.jobs[project_id] = task
        task.add_done_callback(lambda _: self.jobs.pop(project_id, None))

    def cancel(self, project_id: str) -> bool:
        job = self.jobs.get(project_id)
        if not job or job.done():
            return False
        job.cancel()
        return True

    async def shutdown(self) -> None:
        jobs = [job for job in self.jobs.values() if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def _llm(self, prompt: str, max_tokens: int = 2500) -> str:
        model_id, profile = await self.lm_resolver(None)
        profile = {**profile, "temperature": min(float(profile.get("temperature", 0.7)), 0.4), "max_tokens": min(int(profile.get("max_tokens", max_tokens)), max_tokens)}
        payload = self.payload_builder(model_id, profile, [{"role": "user", "content": prompt}])
        response = await self.lm_client_factory().chat(payload)
        return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    def _resolve_run_config(self, project: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        config = dict(self.DEPTH_CONFIG.get(project["depth"], self.DEPTH_CONFIG["deep"]))
        depth_key = f"research_depth_{project['depth']}"
        override = runtime.get(depth_key)
        if isinstance(override, dict) and override:
            config.update(
                {
                    k: override[k]
                    for k in override
                    if k in config
                    or k in {"search_queries", "urls_per_query", "max_sources", "rounds", "crawl_pages", "crawl_depth", "agents"}
                }
            )
        if project["depth"] == "expert":
            # Settings label: evidence-rondes — use as round budget directly (not cycles*3).
            cycles = runtime.get("expert_max_cycles", 6)
            if cycles is not None:
                cycles = max(1, int(cycles))
                config["rounds"] = cycles
                per_cycle = runtime.get("expert_sources_per_cycle", 30)
                per_cycle = 30 if per_cycle is None else int(per_cycle)
                config["max_sources"] = max(int(config["max_sources"]), cycles * max(1, per_cycle))
        project_rounds = project.get("max_rounds")
        if project_rounds is not None:
            config["rounds"] = max(1, min(int(project_rounds), 60))
        project_agents = project.get("agent_count")
        if project_agents is not None:
            config["agents"] = max(1, min(int(project_agents), 8))
        else:
            config["agents"] = max(1, min(int(config.get("agents") or 1), 8))
        config["rounds"] = max(1, min(int(config["rounds"]), 60))
        return config

    @staticmethod
    def _coverage_diversity(evidence: list[dict[str, Any]]) -> tuple[int, int, int]:
        """Return (diversity_score, domain_count, local_source_count).

        Local multi-file research must be able to reach the expert threshold; the old
        formula capped local-only evidence below 90% even with full source coverage.
        """
        domains = {
            urllib.parse.urlparse(item["uri"]).netloc
            for item in evidence
            if item.get("source_type") in {"web", "web_document"} and urllib.parse.urlparse(str(item.get("uri") or "")).netloc
        }
        local_uris = {
            str(item.get("uri") or "")
            for item in evidence
            if item.get("source_type") not in {"web", "web_document"} and str(item.get("uri") or "").strip()
        }
        types = {str(item.get("source_type") or "") for item in evidence if item.get("source_type")}
        diversity_score = min(
            100,
            30
            + len(domains) * 12
            + min(36, len(local_uris) * 4)
            + min(40, len(types) * 15),
        )
        return diversity_score, len(domains), len(local_uris)
    async def _run(self, project_id: str) -> None:
        project = self.db.get_research_project(project_id)
        if not project or project["status"] not in {"queued", "failed", "cancelled"}:
            return
        runtime = self.runtime_settings() or {}
        config = self._resolve_run_config(project, runtime)
        agent_count = int(config["agents"])
        try:
            self.db.update_research_project(project_id, status="running", progress=5, started_at=utc_now(), error=None)
            self.db.add_research_event(
                project_id,
                "info",
                f"Research Planner gestart ({project['depth']}: {config['rounds']} ronde(s), {agent_count} agent(s)).",
            )
            # Preserve prior evidence when an Expert project is continued/re-run.
            existing_sources = self.db.research_sources(project_id)
            source_ids: list[str] = [item["id"] for item in existing_sources]

            # Explicit local folders/files/URLs first.
            for source_input in project["source_inputs"]:
                source_input = source_input.strip()
                if not source_input:
                    continue
                if source_input.startswith(("http://", "https://")):
                    if not project["allow_web"]:
                        self.db.add_research_event(project_id, "warning", f"Webbron overgeslagen omdat web uit staat: {source_input}")
                        continue
                    if self.network_policy() == "block":
                        raise PermissionError("Netwerkbeleid staat op 'block'. Zet netwerk op toestaan/allow voor webresearch.")
                    try:
                        crawled = await self.web.crawl_site(
                            source_input,
                            max_pages=config["crawl_pages"],
                            max_depth=config["crawl_depth"],
                            authorized_downloads=bool(project.get("authorized_downloads")),
                        )
                        if not crawled:
                            source = await self.web.ingest_url(source_input, bool(project.get("authorized_downloads")))
                            crawled = [source]
                        verified_sources: list[dict[str, Any]] = []
                        failed_sources = 0
                        for source in crawled:
                            if not isinstance(source, dict) or not source.get("id"):
                                failed_sources += 1
                                continue
                            persistence = source.get("persistence")
                            if str(source.get("status") or "") == "verification_failed" or (
                                isinstance(persistence, dict) and persistence.get("verification_passed") is False
                            ):
                                failed_sources += 1
                                continue
                            verified_sources.append(source)
                            source_ids.append(source["id"])
                            self.db.link_research_source(project_id, source["id"])
                        if not verified_sources:
                            self.db.add_research_event(
                                project_id,
                                "warning",
                                f"Webbron/crawl zonder geverifieerde bronnen: {source_input} (failed={failed_sources or len(crawled)})",
                            )
                        elif failed_sources:
                            self.db.add_research_event(
                                project_id,
                                "warning",
                                f"Webbron/crawl deels geïndexeerd: {len(verified_sources)} ok, {failed_sources} mislukt vanaf {source_input}",
                            )
                        else:
                            self.db.add_research_event(
                                project_id,
                                "success",
                                f"Webbron/crawl geïndexeerd: {len(verified_sources)} bron(nen) vanaf {source_input}",
                            )
                    except Exception as exc:
                        self.db.add_research_event(project_id, "warning", f"Webbron mislukt: {source_input} — {exc}")
                    continue
                local = Path(source_input).expanduser()
                if local.is_dir():
                    summary = await asyncio.to_thread(self.knowledge.ingest_folder, local, local.name, True, 100_000)
                    for item in self.db.list_indexed_files(summary["workspace"]["id"], 100_000):
                        if item.get("source_id") and str(item.get("status") or "") == "ready":
                            source_ids.append(item["source_id"])
                            self.db.link_research_source(project_id, item["source_id"])
                    ready = int(summary.get("ready") or 0)
                    failed = int(summary.get("failed") or 0)
                    processed = int(summary.get("processed") or 0)
                    if ready <= 0 and (failed > 0 or processed == 0):
                        event_kind = "warning"
                        note = f"Map-indexatie zonder gereede bronnen: {local} (ready={ready}, failed={failed}, processed={processed})"
                    elif failed > 0 and ready > 0:
                        event_kind = "warning"
                        note = f"Map deels geïndexeerd: {local} ({ready} gereed, {failed} mislukt)"
                    else:
                        event_kind = "success"
                        note = f"Map geïndexeerd: {local} ({ready} gereed)"
                    self.db.add_research_event(project_id, event_kind, note)
                elif local.is_file():
                    result = await asyncio.to_thread(self.knowledge.ingest_file, local, None)
                    file_status = str((result.get("file") or {}).get("status") or "")
                    source = result.get("source") if isinstance(result.get("source"), dict) else None
                    if file_status == "ready" and source and knowledge_ingest_verified(source):
                        source_ids.append(source["id"])
                        self.db.link_research_source(project_id, source["id"])
                        self.db.add_research_event(project_id, "success", f"Bestand verwerkt: {local.name} — ready")
                    else:
                        self.db.add_research_event(
                            project_id,
                            "warning",
                            f"Bestand niet als geverifieerde bron gekoppeld: {local.name} — {file_status or 'unknown'}",
                        )
                else:
                    self.db.add_research_event(project_id, "warning", f"Bron bestaat niet: {source_input}")

            self.db.update_research_project(project_id, progress=25)

            # Topic discovery with bounded iterative gap-filling for Deep/Expert modes.
            research_rounds = 0
            searched_queries: list[str] = []
            allow_web_rounds = bool(project["allow_web"]) and self.network_policy() != "block"
            if project["allow_web"] and not allow_web_rounds:
                self.db.add_research_event(
                    project_id,
                    "warning",
                    "Web research aangezet maar netwerkbeleid blokkeert discovery — alleen lokale bronnen.",
                )
            if allow_web_rounds or config["rounds"] > 1 or project["depth"] in {"deep", "expert"}:
                queries = [project["topic"]]
                try:
                    planned = await self._llm(
                        "Maak alleen een lijst met gerichte zoekqueries, één per regel, voor diep brononderzoek. "
                        f"Onderwerp: {project['topic']}\nAantal: {config['search_queries']}\n"
                        "Gebruik verschillende invalshoeken, primaire bronnen, definities, kritiek en recente informatie waar relevant.",
                        700,
                    )
                    generated = [line.strip(" -•\t") for line in planned.splitlines() if line.strip()]
                    queries = list(dict.fromkeys([project["topic"], *generated]))[: config["search_queries"]]
                except Exception as exc:
                    self.db.add_research_event(project_id, "warning", f"Query-expansie via model niet beschikbaar: {exc}")
                visited: set[str] = {
                    item["uri"] for item in existing_sources if item.get("source_type") in {"web", "web_document"}
                }
                auth_downloads = bool(project.get("authorized_downloads"))
                worker_lock = asyncio.Lock()

                async def _ingest_discovered(url: str, agent_label: str) -> None:
                    nonlocal source_ids
                    async with worker_lock:
                        if url in visited or len(set(source_ids)) >= config["max_sources"]:
                            return
                        visited.add(url)
                    try:
                        source = await self.web.ingest_url(url, auth_downloads)
                        if not knowledge_ingest_verified(source):
                            self.db.add_research_event(
                                project_id,
                                "warning",
                                f"{agent_label}: bron overgeslagen (niet geverifieerd): {url}",
                            )
                            return
                        async with worker_lock:
                            source_ids.append(source["id"])
                        self.db.link_research_source(project_id, source["id"])
                        self.db.add_research_event(project_id, "info", f"{agent_label}: bron gelezen: {source['title']}")
                    except Exception as exc:
                        self.db.add_research_event(project_id, "warning", f"{agent_label}: bron overgeslagen: {url} — {exc}")

                async def _run_agent_queries(agent_index: int, agent_queries: list[str]) -> None:
                    agent_label = f"Research Worker {agent_index}/{agent_count}"
                    for query in agent_queries:
                        async with worker_lock:
                            if not query or query in searched_queries:
                                continue
                            searched_queries.append(query)
                            at_cap = len(set(source_ids)) >= config["max_sources"]
                        if at_cap:
                            break
                        if not allow_web_rounds:
                            # Local deepening: pull additional knowledge hits for gap queries.
                            hits = self.db.search_knowledge(query, limit=config["urls_per_query"])
                            for hit in hits:
                                sid = hit.get("source_id")
                                if not sid:
                                    continue
                                async with worker_lock:
                                    if sid in source_ids or len(set(source_ids)) >= config["max_sources"]:
                                        continue
                                    source_ids.append(sid)
                                self.db.link_research_source(project_id, sid)
                                self.db.add_research_event(
                                    project_id,
                                    "info",
                                    f"{agent_label}: lokale kennis gekoppeld voor '{query}': {hit.get('title') or sid}",
                                )
                            continue
                        try:
                            urls = await self.web.discover_duckduckgo(query, config["urls_per_query"])
                        except Exception as exc:
                            self.db.add_research_event(
                                project_id,
                                "warning",
                                f"{agent_label}: web discovery mislukt voor '{query}': {exc}",
                            )
                            continue
                        ingest_jobs = [_ingest_discovered(url, agent_label) for url in urls]
                        if ingest_jobs:
                            await asyncio.gather(*ingest_jobs)
                        await asyncio.sleep(0.05)

                for round_index in range(config["rounds"]):
                    research_rounds += 1
                    self.db.add_research_event(
                        project_id,
                        "info",
                        f"Research Worker ronde {round_index + 1}/{config['rounds']} gestart ({agent_count} agent(s)).",
                    )
                    current_queries = [q for q in queries if q and q not in searched_queries][: config["search_queries"]]
                    if not current_queries:
                        current_queries = [project["topic"]]
                    # Partition queries across parallel research agents.
                    buckets: list[list[str]] = [[] for _ in range(agent_count)]
                    for index, query in enumerate(current_queries):
                        buckets[index % agent_count].append(query)
                    await asyncio.gather(
                        *[
                            _run_agent_queries(agent_index + 1, bucket)
                            for agent_index, bucket in enumerate(buckets)
                            if bucket
                        ]
                    )
                    if len(set(source_ids)) >= config["max_sources"] or round_index + 1 >= config["rounds"]:
                        break
                    # Build next round from currently weak/under-covered areas without claiming mastery yet.
                    interim = self.db.search_knowledge(project["topic"], limit=16)
                    interim_text = "\n".join(f"- {item['title']}: {item['content'][:500]}" for item in interim[:10])
                    try:
                        gap_queries = await self._llm(
                            "Je bent HADES Research Critic. Identificeer ontbrekende invalshoeken/kennishiaten en geef ALLEEN "
                            f"{config['search_queries']} nieuwe zoekqueries, één per regel. Herhaal geen bestaande queries.\n"
                            f"Onderwerp: {project['topic']}\nBestaande queries: {searched_queries}\nHuidige evidence:\n{interim_text}",
                            700,
                        )
                        queries = [line.strip(" -•\t") for line in gap_queries.splitlines() if line.strip()]
                    except Exception as exc:
                        self.db.add_research_event(project_id, "warning", f"Gap-analyse via model niet beschikbaar: {exc}")
                        queries = [project["topic"]]
                    # Deterministic information-gain filter: skip duplicates / already-answered
                    # questions and prefer steps that can change the current decision.
                    try:
                        from reasoning.information_gain import rank_research_steps

                        remaining_tools = max(0, int(config.get("max_sources") or 10) - len(source_ids))
                        ranked = rank_research_steps(
                            candidates=[
                                {
                                    "step_id": f"gap_{i+1}",
                                    "query": q,
                                    "open_question": q,
                                    "expected_decision_change": "May change coverage/contradiction resolution.",
                                    "cost_tool_calls": 1,
                                    "cost_tokens_est": 400,
                                }
                                for i, q in enumerate(queries)
                            ],
                            searched_queries=searched_queries,
                            known_evidence_text=interim_text,
                            open_questions=queries,
                            remaining_tool_budget=remaining_tools,
                            acceptance_satisfied=False,
                        )
                        selected_queries = [item["query"] for item in ranked.get("selected") or [] if item.get("query")]
                        if selected_queries:
                            queries = selected_queries
                        elif ranked.get("ask_for_budget_expansion"):
                            self.db.add_research_event(
                                project_id,
                                "warning",
                                "Noodzakelijk vervolgonderzoek valt buiten het huidige toolbudget; uitbreiding vereist.",
                            )
                        if ranked.get("remaining_uncertainty"):
                            self.db.add_research_event(
                                project_id,
                                "info",
                                "Resterende onzekerheid: " + "; ".join(ranked["remaining_uncertainty"][:5]),
                            )
                    except Exception as exc:
                        self.db.add_research_event(project_id, "warning", f"Information-gain ranking overgeslagen: {exc}")
                    self.db.update_research_project(
                        project_id,
                        progress=min(55, 25 + round((round_index + 1) / max(1, config["rounds"]) * 30)),
                    )

            self.db.update_research_project(project_id, progress=60)
            matches = self.db.search_knowledge(project["topic"], limit=24)
            linked = set(source_ids)
            evidence = [item for item in matches if not linked or item["source_id"] in linked]
            if not evidence:
                evidence = matches
            evidence_text = "\n\n".join(
                f"[BRON {index+1}] {item['title']} | {item['uri']}\n{item['content'][:4500]}"
                for index, item in enumerate(evidence[:18])
            )
            if not evidence_text:
                raise RuntimeError("Geen bruikbare kennisbronnen gevonden. Voeg documenten/URLs toe of sta webresearch toe.")

            self.db.add_research_event(project_id, "info", "Knowledge Builder en Critic voeren synthese uit.")
            synthesis = "llm"
            synthesis_error: str | None = None
            try:
                report = await self._llm(
                    "Je bent de HADES Research Synthesizer + Critic. Maak een brongebonden onderzoeksrapport in het Nederlands. "
                    "Gebruik alleen de meegeleverde evidence, benoem tegenstrijdigheden en onzekerheden, verzin niets. "
                    "Verwijs naar bronnen als [BRON n]. Eindig met 'Kennishiaten' en 'Volgende onderzoeksvragen'.\n\n"
                    f"ONDERWERP:\n{project['topic']}\n\nEVIDENCE:\n{evidence_text}",
                    5000,
                )
            except Exception as exc:
                # Deterministic fallback still produces a source-grounded evidence pack — not a green completion.
                synthesis = "fallback_no_llm"
                synthesis_error = str(exc)
                report = "Onderzoeksrapport kon niet door het lokale model worden gesynthetiseerd.\n\n" + "\n\n".join(
                    f"[BRON {index+1}] {item['title']}\n{item['content'][:1200]}" for index, item in enumerate(evidence[:10])
                ) + f"\n\nModelmelding: {exc}"

            source_count = len(set(item["source_id"] for item in evidence))
            diversity_score, domain_count, local_source_count = self._coverage_diversity(evidence)
            coverage_target = {"quick": 4, "standard": 8, "deep": 14, "expert": 24}.get(project["depth"], 14)
            source_score = min(100, round(source_count / max(1, coverage_target) * 100))
            # Honest label: this metric measures source coverage/diversity, not proven expertise.
            coverage_score = round(source_score * 0.65 + diversity_score * 0.35)
            mastery = coverage_score  # retained for API compatibility
            mastery_target = max(60, min(100, int(runtime.get("expert_mastery_target", 90))))
            expert_reached = project["depth"] == "expert" and coverage_score >= mastery_target
            # Lightweight contradiction scan across evidence snippets (deterministic).
            contradictions: list[str] = []
            snippets = [(item.get("title") or "", (item.get("content") or "")[:800]) for item in evidence[:24]]
            negations = ("niet ", "geen ", "never ", "not ", "false", "onjuist")
            for index, (title_a, text_a) in enumerate(snippets):
                for title_b, text_b in snippets[index + 1 :]:
                    shared = set(text_a.lower().split()) & set(text_b.lower().split())
                    if len(shared) < 6:
                        continue
                    a_neg = any(token in text_a.lower() for token in negations)
                    b_neg = any(token in text_b.lower() for token in negations)
                    if a_neg != b_neg:
                        contradictions.append(f"{title_a[:60]} ↔ {title_b[:60]}")
            if contradictions:
                report = report + "\n\n## Zichtbare tegenstrijdigheden\n" + "\n".join(f"- {item}" for item in contradictions[:8])
                report = report + "\n\n## Open vragen\n- Welke bronversie of context verklaart de tegenstrijdigheid?"
                # Record contradictions as CONTRADICTED claims — coverage metric only, not mastery.
                try:
                    from claim_register import default_claim_register, register_research_contradiction_claims

                    claim_ids = register_research_contradiction_claims(
                        default_claim_register,
                        topic=str(project.get("topic") or project.get("title") or ""),
                        contradictions=contradictions[:12],
                        task_id=project_id,
                        metric_kind="source_coverage_diversity",
                    )
                except Exception:
                    claim_ids = []
            else:
                claim_ids = []
            metrics = {
                "mastery": mastery,
                "coverage_score": coverage_score,
                "metric_kind": "source_coverage_diversity",
                "metric_note": "Geen aangetoonde expertise; alleen brondekking/diversiteit.",
                "source_count": source_count,
                "evidence_chunks": len(evidence),
                "domain_diversity": domain_count,
                "local_source_diversity": local_source_count,
                "research_rounds": research_rounds,
                "configured_rounds": config["rounds"],
                "agent_count": agent_count,
                "queries": searched_queries[-50:],
                "authorized_downloads": bool(project.get("authorized_downloads")),
                "mastery_target": mastery_target,
                "contradictions": contradictions[:12],
                "contradiction_claim_ids": claim_ids,
                "synthesis": synthesis,
                "synthesis_error": synthesis_error,
                "status": (
                    "needs-more-evidence"
                    if synthesis != "llm"
                    else (
                        "expert-threshold"
                        if expert_reached
                        else "needs-more-evidence"
                        if coverage_score < mastery_target or project["depth"] == "expert"
                        else "advanced"
                    )
                ),
            }
            # LLM synthesis failure never claims green completion — evidence pack is degraded output.
            if synthesis != "llm":
                final_status = "needs_more_evidence"
            elif project["depth"] != "expert" or expert_reached:
                final_status = "completed"
            else:
                final_status = "needs_more_evidence"
            self.db.update_research_project(project_id, status=final_status, progress=100, report=report, findings=report[:4000], metrics=metrics, finished_at=utc_now())
            if synthesis != "llm":
                self.db.add_research_event(
                    project_id,
                    "warning",
                    f"Synthese via model mislukt; evidence-pack fallback ({coverage_score}% brondekking). Project blijft hervatbaar.",
                )
            elif final_status == "completed":
                self.db.add_research_event(project_id, "success", f"Onderzoek afgerond. Brondekking/diversiteit: {coverage_score}%.")
            else:
                self.db.add_research_event(project_id, "warning", f"Expert-drempel (brondekking) nog niet bereikt ({coverage_score}%). Project blijft hervatbaar.")
        except asyncio.CancelledError:
            self.db.update_research_project(project_id, status="cancelled", progress=0, error="Handmatig geannuleerd.", finished_at=utc_now())
            self.db.add_research_event(project_id, "warning", "Onderzoek geannuleerd.")
            raise
        except Exception as exc:
            self.db.update_research_project(project_id, status="failed", progress=0, error=str(exc), finished_at=utc_now())
            self.db.add_research_event(project_id, "error", f"Onderzoek mislukt: {exc}")

@dataclass
class ManagedPluginProcess:
    process: subprocess.Popen[str]
    stdout_handle: Any
    stderr_handle: Any
    command: list[str]


class PluginManager:
    """Converts reproducible local/Git sources into inspectable .HadesPlugin packages."""

    def __init__(self, db: PlatformDatabase, data_root: Path) -> None:
        self.db = db
        self.data_root = Path(data_root)
        self.root = self.data_root / "plugins"
        self.sources = self.root / "sources"
        self.packages = self.root / "packages"
        self.runtimes = self.root / "runtimes"
        self.history = self.root / "history"
        self._processes: dict[str, ManagedPluginProcess] = {}
        self._process_lock = threading.RLock()
        self._service_locks: dict[str, threading.Lock] = {}
        self._artifact_hook = None
        self._envelope_gate = None  # optional Gen2 sandbox check callable
        self._mcp_call_handler = None  # optional managed MCP session invoke (mcp_host)
        self._native_runtime = None  # optional NativeRuntimeClient for process/service supervision
        self._effect_ledger = None
        for path in (self.sources, self.packages, self.runtimes, self.history):
            path.mkdir(parents=True, exist_ok=True)

    def _service_lock_for(self, plugin_id: str) -> threading.Lock:
        with self._process_lock:
            lock = self._service_locks.get(plugin_id)
            if lock is None:
                lock = threading.Lock()
                self._service_locks[plugin_id] = lock
            return lock

    def effect_ledger(self) -> Any:
        """Lazy EffectLedger under platform data root — shared at-least-once intent log."""
        if self._effect_ledger is None:
            from runtime.effect_ledger import EffectLedger

            self._effect_ledger = EffectLedger(self.data_root / "effect_ledger.db")
        return self._effect_ledger

    def set_effect_ledger(self, ledger: Any | None) -> None:
        self._effect_ledger = ledger

    def set_native_runtime(self, client: Any | None) -> None:
        """Attach optional native companion for process/service execution (not a second policy engine)."""
        self._native_runtime = client

    def set_envelope_gate(self, gate: Any | None) -> None:
        """Attach an optional Gen2 capability-envelope checker (no second policy engine)."""
        self._envelope_gate = gate

    def set_mcp_call_handler(self, handler: Any | None) -> None:
        """Attach managed MCP host invoke for mirrored mcp_managed tools (same policy path)."""
        self._mcp_call_handler = handler

    def set_policy_settings_provider(self, provider: Any | None) -> None:
        """Attach callable () -> dict for MCP allowlists / tool-boundary settings (A09)."""
        self._policy_settings_provider = provider

    def set_policy_settings(self, settings: dict[str, Any] | None) -> None:
        self._policy_settings = dict(settings or {})

    @staticmethod
    def safe_extract_zip(archive_path: Path, destination: Path) -> None:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                archive_file_limit = max_archive_files()
                if archive_file_limit is not None and len(members) > int(archive_file_limit):
                    raise ValueError("Archief bevat te veel bestanden.")
                root = destination.resolve()
                extracted = 0
                for member in members:
                    raw = member.filename.replace("\\", "/")
                    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
                        raise ValueError("Archief bevat een absoluut pad.")
                    target = (destination / raw).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError as exc:
                        raise ValueError("Archief probeert buiten de pluginmap te schrijven.") from exc
                    mode = (member.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise ValueError("Symlinks zijn niet toegestaan in pluginarchieven.")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            extracted += len(chunk)
                            archive_byte_limit = max_archive_bytes()
                            if archive_byte_limit is not None and extracted > int(archive_byte_limit):
                                raise ValueError("Uitgepakt archief overschrijdt de veiligheidslimiet.")
                            output.write(chunk)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    @staticmethod
    def _reject_unsafe_symlinks(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Pluginbron bevat een niet-toegestane symlink: {path.relative_to(root)}")

    def _flatten_single_root(self, path: Path) -> Path:
        children = [item for item in path.iterdir() if item.name not in {"__MACOSX"}]
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return path

    def _refresh_capability_intel(self, plugin_id: str) -> None:
        """Normalize plugin capabilities into the canonical registry. Fail-open."""
        try:
            from capability_intel.service import get_service

            plugin = self.db.get_plugin(plugin_id)
            if not plugin:
                return
            get_service(self.db).on_plugin_imported(plugin, self.db.plugin_tools(plugin_id))
        except Exception as exc:
            try:
                self.db.add_plugin_event(plugin_id, "warning", f"Capability intelligence refresh overgeslagen: {exc}")
            except Exception:
                pass

    def import_local_folder(self, source_path: Path, install_dependencies: bool = True) -> dict[str, Any]:
        source_path = source_path.expanduser().resolve()
        if not source_path.is_dir():
            raise NotADirectoryError(source_path)
        self._reject_unsafe_symlinks(source_path)
        target = self.sources / f"{safe_name(source_path.name)}-{sha256_bytes(str(source_path).encode())[:8]}"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_path, target, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__"))
        return self._convert(target, "local-folder", str(source_path), install_dependencies)

    @staticmethod
    def resolve_upload_relative(raw: str) -> Path | None:
        text = str(raw or "").replace("\\", "/").strip()
        if not text:
            raise ValueError("Bestand mist een relatief pad.")
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            raise ValueError("Uploadpad mag niet absoluut zijn.")
        parts = [part for part in text.split("/") if part not in {"", "."}]
        if not parts or any(part == ".." for part in parts):
            raise ValueError("Uploadpad mag de pluginmap niet verlaten.")
        if any("\x00" in part for part in parts):
            raise ValueError("Uploadpad bevat ongeldige tekens.")
        if any(part in PLUGIN_UPLOAD_SKIP_PARTS for part in parts):
            return None
        return Path(*parts)

    def import_uploaded_folder(self, files: Iterable[tuple[str, bytes]], install_dependencies: bool = True) -> dict[str, Any]:
        staging = Path(tempfile.mkdtemp(prefix="hades-folder-import-", dir=self.root))
        try:
            written = 0
            count = 0
            for relative, payload in files:
                resolved = self.resolve_upload_relative(relative)
                if resolved is None:
                    continue
                count += 1
                upload_file_limit = max_archive_files()
                if upload_file_limit is not None and count > int(upload_file_limit):
                    raise ValueError("De geselecteerde map bevat te veel bestanden.")
                target = (staging / resolved).resolve()
                try:
                    target.relative_to(staging.resolve())
                except ValueError as exc:
                    raise ValueError("Uploadpad mag de pluginmap niet verlaten.") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                data = payload if isinstance(payload, (bytes, bytearray)) else bytes(payload)
                written += len(data)
                upload_byte_limit = max_plugin_upload_bytes()
                if upload_byte_limit is not None and written > int(upload_byte_limit):
                    raise ValueError("Geselecteerde map overschrijdt de uploadlimiet van 256 MB.")
                target.write_bytes(data)
            return self.import_staged_folder(staging, install_dependencies)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def import_staged_folder(self, staging: Path, install_dependencies: bool = True) -> dict[str, Any]:
        staging = staging.expanduser().resolve()
        if not staging.is_dir():
            raise NotADirectoryError(staging)
        source = self._flatten_single_root(staging)
        if not any(path.is_file() and not path.is_symlink() for path in source.rglob("*")):
            raise ValueError("De geselecteerde map bevat geen bruikbare bestanden.")
        return self.import_local_folder(source, install_dependencies)

    def import_zip(self, archive_path: Path, install_dependencies: bool = True) -> dict[str, Any]:
        archive_path = archive_path.expanduser().resolve()
        target = self.sources / f"{safe_name(archive_path.stem)}-{sha256_file(archive_path)[:8]}"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        self.safe_extract_zip(archive_path, target)
        package_root = self._flatten_single_root(target)
        manifest_path = package_root / "hades-plugin.json"
        source_root = package_root / "source"
        if manifest_path.is_file() and source_root.is_dir():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            integrity = manifest.get("integrity", {})
            if not isinstance(integrity, dict) or not integrity:
                raise ValueError(".HadesPlugin met source/ vereist een niet-lege integrity-map.")
            for relative, expected in integrity.items():
                candidate = (source_root / str(relative)).resolve()
                try:
                    candidate.relative_to(source_root.resolve())
                except ValueError as exc:
                    raise ValueError(".HadesPlugin integrity-pad verlaat source/.") from exc
                if not candidate.is_file():
                    raise ValueError(f".HadesPlugin mist sourcebestand: {relative}")
                actual = sha256_file(candidate)
                if actual.lower() != str(expected).lower():
                    raise ValueError(f".HadesPlugin integrity-check mislukt voor: {relative}")
            # The converter expects the manifest next to the runtime source.
            (source_root / "hades-plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._convert(source_root, "hades-plugin", str(archive_path), install_dependencies)
        return self._convert(package_root, "zip", str(archive_path), install_dependencies)

    def import_git(self, url: str, ref: str = "", install_dependencies: bool = True) -> dict[str, Any]:
        from url_security import UrlSecurityError, assert_public_http_url

        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git is niet geïnstalleerd of niet beschikbaar via PATH.")
        try:
            parsed = assert_public_http_url(url, purpose="git_import")
        except UrlSecurityError as exc:
            raise ValueError(str(exc)) from exc
        name = safe_name(Path(parsed.path).stem or "github-plugin")
        target = self.sources / f"{name}-{sha256_bytes((url+ref).encode())[:8]}"
        if target.exists():
            shutil.rmtree(target)
        process = subprocess.run(
            [git, "clone", "--depth", "1", url, str(target)],
            capture_output=True,
            text=True,
            timeout=int(_setting("plugins.install_git_clone_timeout_seconds", 180) or 180),
            shell=False,
        )
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout).strip() or "Git clone is mislukt.")
        if ref:
            fetch_timeout = int(_setting("plugins.install_git_fetch_timeout_seconds", 120) or 120)
            fetch = subprocess.run(
                [git, "-C", str(target), "fetch", "--depth", "1", "origin", ref],
                capture_output=True,
                text=True,
                timeout=fetch_timeout,
                shell=False,
            )
            if fetch.returncode == 0:
                checkout = subprocess.run([git, "-C", str(target), "checkout", "--detach", "FETCH_HEAD"], capture_output=True, text=True, timeout=30, shell=False)
            else:
                checkout = subprocess.run([git, "-C", str(target), "checkout", ref], capture_output=True, text=True, timeout=30, shell=False)
            if checkout.returncode != 0:
                raise RuntimeError((checkout.stderr or fetch.stderr or checkout.stdout).strip() or f"Git ref '{ref}' kon niet worden uitgecheckt.")
        commit = subprocess.run([git, "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, shell=False)
        source_ref = commit.stdout.strip() if commit.returncode == 0 else ref
        shutil.rmtree(target / ".git", ignore_errors=True)
        return self._convert(target, "git", f"{url}@{source_ref}", install_dependencies)

    def _detect(self, root: Path) -> dict[str, Any]:
        manifest_path = root / "hades-plugin.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("Pluginmanifest moet een JSON-object zijn.")
            required = ("id", "name", "version")
            missing = [field for field in required if not str(manifest.get(field, "")).strip()]
            if missing:
                raise ValueError("Pluginmanifest mist verplichte velden: " + ", ".join(missing))
            if not isinstance(manifest.get("format", 1), int) or int(manifest.get("format", 1)) != 1:
                raise ValueError("Alleen HADES pluginmanifest-formaat 1 wordt ondersteund.")
            declared_id = str(manifest["id"]).strip()
            if safe_name(declared_id).lower().replace(".", "-") != declared_id.lower().replace(".", "-"):
                raise ValueError("Pluginmanifest id bevat ongeldige tekens.")
            return {"runtime": manifest.get("runtime_type", manifest.get("runtime", "custom")), "manifest": manifest, "entrypoint": manifest.get("entrypoint", ""), "tools": manifest.get("tools", [])}

        readme = next((path for path in [root / "README.md", root / "README.txt", root / "readme.md"] if path.exists()), None)
        description = ""
        if readme:
            description = re.sub(r"[#>*_`]", "", readme.read_text(encoding="utf-8", errors="ignore"))[:500].strip()

        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
            candidates = [root / "main.py", root / "app.py", root / "cli.py"]
            entry = next((path.name for path in candidates if path.exists()), "")
            tools = []
            if entry:
                tools.append({"name": "run", "description": "Voer de gedetecteerde Python-entrypoint uit.", "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}}, "command": ["{python}", entry, "{args}"], "action": "run"})
            return {"runtime": "python", "entrypoint": entry, "tools": tools, "description": description}

        if (root / "package.json").exists():
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            preferred = next((key for key in ("start", "cli", "serve", "dev") if key in scripts), "")
            tools = [
                {
                    "name": str(name),
                    "description": f"Voer npm-script '{name}' uit.",
                    "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}},
                    "command": ["{npm}", "run", str(name), "--", "{args}"],
                    "action": str(name).lower(),
                    "mode": "service" if str(name).lower() in {"start", "serve", "dev"} else "command",
                }
                for name in scripts
                if isinstance(name, str) and name.strip()
            ]
            return {"runtime": "node", "entrypoint": preferred, "tools": tools, "description": package.get("description", description)}

        if (root / "Cargo.toml").exists():
            return {"runtime": "rust", "entrypoint": "", "tools": [], "description": description}
        if (root / "go.mod").exists():
            return {"runtime": "go", "entrypoint": "", "tools": [], "description": description}
        if list(root.glob("*.csproj")):
            return {"runtime": "dotnet", "entrypoint": "", "tools": [], "description": description}
        if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return {"runtime": "java", "entrypoint": "", "tools": [], "description": description}
        executables = [path for path in root.iterdir() if path.is_file() and os.access(path, os.X_OK)]
        if executables:
            entry = executables[0].name
            return {"runtime": "native", "entrypoint": entry, "tools": [{"name": "run", "description": "Voer het gedetecteerde executable uit.", "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}}, "command": [f"{{root}}/{entry}", "{args}"], "action": "run"}], "description": description}
        return {"runtime": "unknown", "entrypoint": "", "tools": [], "description": description}

    def _dependency_plan(self, root: Path, runtime: str) -> dict[str, Any]:
        plan = {"runtime": runtime, "commands": [], "system_missing": [], "ready": True}
        if runtime == "python":
            if not sys.executable:
                plan["system_missing"].append("Python")
            requirement = root / "requirements.txt"
            if requirement.exists():
                plan["commands"].append(["{python}", "-m", "pip", "install", "-r", str(requirement)])
            elif (root / "pyproject.toml").exists():
                plan["commands"].append(["{python}", "-m", "pip", "install", str(root)])
        elif runtime == "node":
            if not shutil.which("npm"):
                plan["system_missing"].append("Node.js/npm")
            else:
                plan["commands"].append(["npm", "ci"] if (root / "package-lock.json").exists() else ["npm", "install"])
        elif runtime == "rust":
            if not shutil.which("cargo"):
                plan["system_missing"].append("Rust/Cargo")
            else:
                plan["commands"].append(["cargo", "build", "--release"])
        elif runtime == "go":
            if not shutil.which("go"):
                plan["system_missing"].append("Go")
            else:
                plan["commands"].append(["go", "build", "./..."])
        elif runtime == "java":
            if not shutil.which("java"):
                plan["system_missing"].append("Java")
            if (root / "pom.xml").exists() and shutil.which("mvn"):
                plan["commands"].append(["mvn", "-q", "-DskipTests", "package"])
            elif (root / "gradlew").exists():
                plan["commands"].append([str(root / "gradlew"), "build", "-x", "test"])
        elif runtime == "dotnet":
            if not shutil.which("dotnet"):
                plan["system_missing"].append(".NET SDK")
            else:
                plan["commands"].append(["dotnet", "restore"])
        plan["ready"] = not plan["system_missing"]
        return plan

    def _install_dependencies(self, root: Path, runtime: str, plugin_id: str) -> dict[str, Any]:
        plan = self._dependency_plan(root, runtime)
        call_id = self.db.create_tool_call(
            plugin_id,
            "__dependencies__",
            {"runtime": runtime, "commands": plan["commands"]},
            invocation_type="install",
            approved_by_user=True,
            metadata={"kind": "dependency_install"},
        )
        started = time.perf_counter()
        if plan["system_missing"]:
            error = "Ontbrekende systeemruntime: " + ", ".join(plan["system_missing"])
            self.db.finish_tool_call(call_id, "failed", error=error, stderr=error, duration_ms=round((time.perf_counter() - started) * 1000))
            return {**plan, "installed": False, "error": error, "call_id": call_id}
        env = os.environ.copy()
        runtime_dir = self.runtimes / plugin_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        python_bin = sys.executable
        logs: list[dict[str, Any]] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            if runtime == "python":
                venv = runtime_dir / "venv"
                if not (venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).exists():
                    created = subprocess.run(
                        [sys.executable, "-m", "venv", str(venv)],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        shell=False,
                    )
                    stdout_parts.append(created.stdout or "")
                    stderr_parts.append(created.stderr or "")
                    if created.returncode != 0:
                        raise RuntimeError((created.stderr or created.stdout).strip() or "Python virtual environment kon niet worden gemaakt.")
                python_bin = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
            for raw in plan["commands"]:
                command = [python_bin if part == "{python}" else part for part in raw]
                if command and command[0] == "npm":
                    command[0] = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
                process = subprocess.run(
                    command,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=int(
                        (
                            _setting("plugins.install_npm_timeout_seconds", 600)
                            if command and str(command[0]).lower().startswith("npm")
                            else _setting("plugins.install_pip_timeout_seconds", 600)
                        )
                        or 600
                    ),
                    shell=False,
                )
                stdout_parts.append(process.stdout or "")
                stderr_parts.append(process.stderr or "")
                logs.append({"command": command, "returncode": process.returncode, "stdout": (process.stdout or "")[-4000:], "stderr": (process.stderr or "")[-4000:]})
                if process.returncode != 0:
                    raise RuntimeError((process.stderr or process.stdout)[-2000:] or f"Dependency-commando eindigde met exitcode {process.returncode}.")
        except Exception as exc:
            error = str(exc)
            duration = round((time.perf_counter() - started) * 1000)
            self.db.finish_tool_call(
                call_id,
                "failed",
                output="\n".join(part for part in [*stdout_parts, *stderr_parts] if part).strip()[-100_000:],
                stdout="\n".join(stdout_parts),
                stderr="\n".join([*stderr_parts, error]),
                error=error,
                exit_code=logs[-1]["returncode"] if logs else None,
                duration_ms=duration,
                metadata={"kind": "dependency_install", "commands": len(plan["commands"])},
            )
            return {**plan, "installed": False, "error": error, "logs": logs, "python": python_bin, "call_id": call_id}
        duration = round((time.perf_counter() - started) * 1000)
        output = "\n".join(part for part in [*stdout_parts, *stderr_parts] if part).strip()[-100_000:]
        self.db.finish_tool_call(
            call_id,
            "completed",
            output=output,
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            exit_code=0,
            duration_ms=duration,
            metadata={"kind": "dependency_install", "commands": len(plan["commands"])},
        )
        return {**plan, "installed": True, "logs": logs, "python": python_bin, "call_id": call_id}

    def _convert(self, root: Path, source: str, source_ref: str, install_dependencies: bool) -> dict[str, Any]:
        self._reject_unsafe_symlinks(root)
        detected = self._detect(root)
        runtime = detected["runtime"]
        plugin_id = safe_name(root.name).lower().replace(".", "-")
        manifest = detected.get("manifest") or {
            "format": 1,
            "id": plugin_id,
            "name": root.name,
            "version": "0.1.0",
            "description": detected.get("description", ""),
            "source": source,
            "source_ref": source_ref,
            "runtime_type": runtime,
            "entrypoint": detected.get("entrypoint", ""),
            "permissions": ["subprocess"],
            "tools": detected.get("tools", []),
            "hades_api": ">=0.3",
        }
        plugin_id = safe_name(str(manifest.get("id") or plugin_id)).lower().replace(".", "-")
        manifest["id"] = plugin_id
        raw_tools = manifest.get("tools", [])
        if not isinstance(raw_tools, list):
            raise ValueError("Pluginmanifest 'tools' moet een lijst zijn.")
        tools: list[dict[str, Any]] = []
        seen_tool_names: set[str] = set()
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                raise ValueError("Iedere plugin-tool moet een JSON-object zijn.")
            name = str(raw_tool.get("name", "")).strip()
            if not name or len(name) > 120:
                raise ValueError("Iedere plugin-tool heeft een geldige naam van maximaal 120 tekens nodig.")
            if name in seen_tool_names:
                raise ValueError(f"Dubbele plugin-toolnaam: {name}")
            seen_tool_names.add(name)
            command = raw_tool.get("command", "")
            if not isinstance(command, (str, list)) or isinstance(command, list) and not all(isinstance(part, str) for part in command):
                raise ValueError(f"Tool '{name}' moet een command-string of argv-array met strings gebruiken.")
            action = str(raw_tool.get("action") or name).strip().lower()
            normalized = {
                **raw_tool,
                "name": name,
                "description": str(raw_tool.get("description", "")),
                "input_schema": raw_tool.get("input_schema") if isinstance(raw_tool.get("input_schema"), dict) else {"type": "object", "properties": {}},
                "output_schema": raw_tool.get("output_schema") if isinstance(raw_tool.get("output_schema"), dict) else {},
                "command": command,
                "action": action,
                "mode": str(raw_tool.get("mode") or ("service" if action in {"start", "serve", "dev"} else "command")),
            }
            tools.append(normalized)
        manifest["tools"] = tools
        if not manifest.get("category"):
            haystack = f"{manifest.get('name','')} {manifest.get('description','')} {runtime}".lower()
            category = "Browser" if any(x in haystack for x in ("browser", "puppeteer", "playwright")) else "Research" if any(x in haystack for x in ("research", "search")) else "Data" if any(x in haystack for x in ("data", "database", "etl")) else "Security" if any(x in haystack for x in ("security", "osint", "scan", "hacker")) else "Developer" if any(x in haystack for x in ("code", "build", "developer")) else "Tool"
            manifest["category"] = category
        raw_labels = manifest.get("labels", [])
        labels = [str(item).strip()[:40] for item in raw_labels if str(item).strip()] if isinstance(raw_labels, list) else []
        for default_label in (str(manifest["category"]), runtime):
            if default_label and default_label.lower() not in {item.lower() for item in labels}:
                labels.append(default_label)
        manifest["labels"] = labels[:8]
        manifest.setdefault("autonomous", True)
        from plugin_runtime_v2 import enrich_manifest, normalize_isolation, normalize_trust, validate_marketplace_hygiene

        manifest = enrich_manifest(manifest)
        tools = list(manifest.get("tools") or tools)
        for warning in validate_marketplace_hygiene(manifest):
            self.db.add_plugin_event(plugin_id, "warning", f"Marketplace-hygiëne: {warning}")
        status = "detected" if runtime != "unknown" else "needs_review"
        trust_value = normalize_trust(manifest.get("trust_default") or "untrusted")
        isolation_value = normalize_isolation(manifest.get("isolation"))
        record = self.db.save_plugin(
            {
                "id": plugin_id,
                "name": manifest.get("name", root.name),
                "version": manifest.get("version", "0.1.0"),
                "description": manifest.get("description", ""),
                "source": source,
                "source_ref": source_ref,
                "local_path": str(root),
                "plugin_type": manifest.get("plugin_type", "tool"),
                "runtime_type": runtime,
                "entrypoint": manifest.get("entrypoint", ""),
                "manifest": manifest,
                "permissions": manifest.get("permissions", ["subprocess"]),
                "status": status,
                "enabled": False,
                "health": "unknown",
                "trust": trust_value,
                "isolation": isolation_value,
                "failure_state": None,
            }
        )
        self.db.replace_plugin_tools(plugin_id, tools)
        self.db.add_plugin_event(plugin_id, "info", f"Bron gedetecteerd als runtime: {runtime}.")
        self.db.add_plugin_event(
            plugin_id,
            "info",
            f"Runtime v2: trust={trust_value}, isolation={isolation_value}, capabilities={manifest.get('capabilities', {}).get('effects', [])}.",
        )
        dependency_result = {"installed": False, "skipped": True}
        if install_dependencies and runtime != "unknown":
            self.db.set_plugin_state(plugin_id, status="preparing")
            try:
                dependency_result = self._install_dependencies(root, runtime, plugin_id)
                if dependency_result.get("installed"):
                    self.db.add_plugin_event(plugin_id, "success", "Plugin-lokale dependencies zijn voorbereid.")
                else:
                    self.db.add_plugin_event(plugin_id, "warning", dependency_result.get("error", "Dependencies niet gereed."))
            except Exception as exc:
                dependency_result = {"installed": False, "error": str(exc)}
                self.db.add_plugin_event(plugin_id, "error", f"Dependency-installatie mislukt: {exc}")

        ready = runtime != "unknown" and bool(tools) and (dependency_result.get("installed") or not install_dependencies or not self._dependency_plan(root, runtime)["commands"])
        final_status = "ready" if ready else "needs_review" if runtime != "unknown" else "unsupported"
        health = "prepared" if ready else "needs_attention"
        last_error = "" if ready else str(dependency_result.get("error") or ("Geen uitvoerbaar toolcontract gedetecteerd." if not tools else "Runtime is niet gereed."))
        failure = None if ready else ("dependency_failed" if dependency_result.get("error") else ("unsupported_runtime" if runtime == "unknown" else "not_ready"))
        if ready:
            # Successful Ready convert proves local integrity/deps → trust verified.
            # Remain disabled until the user explicitly enables (trust ladder / autonomous gate).
            # Explicit user promote remains required for trust=trusted (high-risk write+network).
            record = self.db.set_plugin_state(
                plugin_id,
                status=final_status,
                health=health,
                enabled=False,
                last_error=last_error,
                trust="verified",
                clear_failure=True,
            ) or record
        else:
            record = self.db.set_plugin_state(
                plugin_id, status=final_status, health=health, enabled=False, last_error=last_error, failure_state=failure
            ) or record
        # MCP first-class expansion (best-effort; wrappers remain). Runs privileged while disabled.
        if ready:
            try:
                self.expand_mcp_tools(plugin_id)
            except Exception as exc:
                self.db.add_plugin_event(plugin_id, "warning", f"MCP tool-expansie overgeslagen: {exc}")
        package_path = self._pack(self.db.get_plugin(plugin_id) or record, root)
        self.db.add_plugin_event(plugin_id, "success" if ready else "warning", f"Conversie afgerond met status: {final_status}.")
        try:
            from plugin_knowledge_index import reindex_plugin

            reindex_plugin(self.db, self.db.get_plugin(plugin_id) or record)
        except Exception as exc:
            self.db.add_plugin_event(plugin_id, "warning", f"Plugin knowledge index overgeslagen: {exc}")
        self._refresh_capability_intel(plugin_id)
        return {"plugin": self.db.get_plugin(plugin_id) or record, "tools": self.db.plugin_tools(plugin_id), "dependencies": dependency_result, "package_path": str(package_path)}

    def _pack(self, plugin: dict[str, Any], root: Path) -> Path:
        package_path = self.packages / f"{safe_name(plugin['id'])}-{safe_name(plugin['version'])}.HadesPlugin"
        manifest = {**plugin["manifest"], "integrity": {}}
        files = []
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if any(part in {"node_modules", ".venv", "venv", ".git"} for part in path.parts):
                continue
            relative = path.relative_to(root).as_posix()
            manifest["integrity"][relative] = sha256_file(path)
            files.append((path, f"source/{relative}"))
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("hades-plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path, archive_name in files:
                archive.write(path, archive_name)
        return package_path

    def export_package(self, plugin_id: str) -> Path:
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        root = Path(plugin["local_path"]).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Plugin-source ontbreekt: {root}")
        return self._pack(plugin, root)

    def _snapshot_for_rollback(self, plugin_id: str) -> Path:
        package = self.export_package(plugin_id)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = self.history / f"{safe_name(plugin_id)}-{stamp}.HadesPlugin"
        shutil.copy2(package, destination)
        return destination

    def update_git(self, plugin_id: str, install_dependencies: bool = True) -> dict[str, Any]:
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        if plugin.get("source") != "git":
            raise RuntimeError("Automatische update is alleen beschikbaar voor Git-plugins.")
        ref_value = str(plugin.get("source_ref") or "")
        url = ref_value.rsplit("@", 1)[0] if "@" in ref_value else ref_value
        if not url.startswith(("https://", "http://")):
            raise RuntimeError("De oorspronkelijke Git repository-URL ontbreekt.")
        self._snapshot_for_rollback(plugin_id)
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git is niet geïnstalleerd of niet beschikbaar via PATH.")
        current_root = Path(plugin["local_path"]).resolve()
        previous_tools = self.db.plugin_tools(plugin_id)
        staging = Path(tempfile.mkdtemp(prefix="hades-plugin-update-", dir=str(self.sources)))
        try:
            process = subprocess.run([git, "clone", "--depth", "1", url, str(staging / "source")], capture_output=True, text=True, timeout=180, shell=False)
            if process.returncode != 0:
                raise RuntimeError((process.stderr or process.stdout).strip() or "Git update-clone is mislukt.")
            fetched = staging / "source"
            commit = subprocess.run([git, "-C", str(fetched), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, shell=False)
            source_ref = commit.stdout.strip() if commit.returncode == 0 else "HEAD"
            shutil.rmtree(fetched / ".git", ignore_errors=True)
            detected = self._detect(fetched)
            incoming = detected.get("manifest")
            if isinstance(incoming, dict):
                incoming_id = safe_name(str(incoming.get("id", ""))).lower().replace(".", "-")
                if incoming_id != plugin_id:
                    raise RuntimeError("Git-update geweigerd: het nieuwe manifest heeft een andere plugin-id.")
            replacement = current_root.with_name(current_root.name + ".updating")
            backup = current_root.with_name(current_root.name + ".previous")
            if replacement.exists():
                shutil.rmtree(replacement)
            if backup.exists():
                shutil.rmtree(backup)
            shutil.copytree(fetched, replacement, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__"))
            if current_root.exists():
                current_root.rename(backup)
            replacement.rename(current_root)
            try:
                result = self._convert(current_root, "git", f"{url}@{source_ref}", install_dependencies)
                if result["plugin"].get("status") != "ready":
                    raise RuntimeError(result["plugin"].get("last_error") or "Bijgewerkte plugin is niet runtime-ready.")
            except Exception:
                shutil.rmtree(current_root, ignore_errors=True)
                if backup.exists():
                    backup.rename(current_root)
                self.db.save_plugin(plugin)
                self.db.replace_plugin_tools(plugin_id, previous_tools)
                self.db.add_plugin_event(plugin_id, "error", "Git-update teruggedraaid; de bestaande werkende plugin bleef behouden.")
                raise
            shutil.rmtree(backup, ignore_errors=True)
            self.db.add_plugin_event(plugin_id, "success", f"Git-plugin bijgewerkt naar commit {source_ref[:12]}.")
            return result
        except Exception:
            # Source rollback remains available even if conversion fails.
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def rollback_latest(self, plugin_id: str, install_dependencies: bool = True) -> dict[str, Any]:
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        candidates = sorted(self.history.glob(f"{safe_name(plugin_id)}-*.HadesPlugin"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("Geen rollback-snapshot beschikbaar voor deze plugin.")
        result = self.import_zip(candidates[0], install_dependencies=install_dependencies)
        self.db.add_plugin_event(plugin_id, "success", f"Rollback uitgevoerd vanuit {candidates[0].name}.")
        return result

    def uninstall(self, plugin_id: str) -> bool:
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            return False
        self._terminate_managed_process(plugin_id)
        local_path = Path(plugin["local_path"]).resolve()
        runtime_path = (self.runtimes / plugin_id).resolve()
        try:
            local_path.relative_to(self.sources.resolve())
            shutil.rmtree(local_path, ignore_errors=True)
        except ValueError:
            pass
        shutil.rmtree(runtime_path, ignore_errors=True)
        for package in self.packages.glob(f"{safe_name(plugin_id)}-*.HadesPlugin"):
            package.unlink(missing_ok=True)
        try:
            from capability_intel.service import get_service

            get_service(self.db).on_plugin_removed(plugin_id)
        except Exception:
            pass
        try:
            from plugin_knowledge_index import remove_plugin_index

            remove_plugin_index(self.db, plugin_id)
        except Exception:
            pass
        return self.db.delete_plugin(plugin_id)

    def repair(self, plugin_id: str) -> dict[str, Any]:
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        from plugin_runtime_v2 import enrich_manifest, normalize_isolation, normalize_trust

        manifest = enrich_manifest(dict(plugin.get("manifest") or {}))
        self.db.save_plugin(
            {
                **plugin,
                "manifest": manifest,
                "permissions": manifest.get("permissions", plugin.get("permissions") or []),
                "trust": normalize_trust(plugin.get("trust") or manifest.get("trust_default")),
                "isolation": normalize_isolation(plugin.get("isolation") or manifest.get("isolation")),
                "failure_state": plugin.get("failure_state"),
            }
        )
        # Re-normalize tool capability contracts without dropping existing rows' enabled flags.
        existing = {item["name"]: item for item in self.db.plugin_tools(plugin_id)}
        refreshed = []
        for tool in manifest.get("tools") or []:
            prior = existing.get(tool["name"])
            merged = {**tool}
            if prior:
                merged["enabled"] = prior.get("enabled", True)
            refreshed.append(merged)
        # Keep any previously expanded MCP remote tools.
        for name, prior in existing.items():
            if name not in {item["name"] for item in refreshed} and prior.get("metadata", {}).get("mcp_remote"):
                refreshed.append(
                    {
                        "name": prior["name"],
                        "description": prior.get("description", ""),
                        "input_schema": prior.get("input_schema", {}),
                        "output_schema": prior.get("output_schema", {}),
                        "command": prior.get("command", ""),
                        **prior.get("metadata", {}),
                        "enabled": prior.get("enabled", True),
                    }
                )
        if refreshed:
            self.db.replace_plugin_tools(plugin_id, refreshed)
        result = self._install_dependencies(Path(plugin["local_path"]), plugin["runtime_type"], plugin_id)
        tools_ready = bool(self.db.plugin_tools(plugin_id))
        runtime_ready = plugin.get("runtime_type") != "unknown"
        if (result.get("installed") or not result.get("commands")) and tools_ready and runtime_ready:
            self.db.set_plugin_state(
                plugin_id,
                status="ready",
                health="prepared",
                last_error="",
                clear_failure=True,
                trust="verified" if normalize_trust(plugin.get("trust")) in {"untrusted", "manual", "verified"} else plugin.get("trust"),
            )
            # Successful repair promotes at least to verified (integrity/deps proven).
            current = self.db.get_plugin(plugin_id) or plugin
            if normalize_trust(current.get("trust")) == "untrusted":
                self.db.set_plugin_state(plugin_id, trust="verified")
            elif normalize_trust(current.get("trust")) == "manual":
                self.db.set_plugin_state(plugin_id, trust="verified")
            self.db.add_plugin_event(plugin_id, "success", "Dependencies opnieuw gevalideerd; runtime is voorbereid en wacht op een geslaagde tooltest voor health=healthy.")
            try:
                self.expand_mcp_tools(plugin_id)
            except Exception as exc:
                self.db.add_plugin_event(plugin_id, "warning", f"MCP tool-expansie overgeslagen: {exc}")
        else:
            error = result.get("error") or ("Geen uitvoerbaar toolcontract gedetecteerd." if not tools_ready else "Runtime wordt niet ondersteund.")
            self.db.set_plugin_state(
                plugin_id,
                status="needs_review",
                health="needs_attention",
                last_error=error,
                failure_state="dependency_failed",
            )
        return {"plugin": self.db.get_plugin(plugin_id), "dependencies": result}

    def expand_mcp_tools(self, plugin_id: str) -> dict[str, Any]:
        """Register remote MCP tools as first-class HADES tool rows (wrappers stay)."""
        max_conn = _setting("mcp.max_connections", 8)
        if max_conn is not None:
            ready_mcp = [
                p
                for p in self.db.list_plugins()
                if str(p.get("runtime_type") or p.get("runtime") or "").lower().find("mcp") >= 0
                and p.get("enabled")
                and str(p.get("status") or "").lower() == "ready"
            ]
            if len(ready_mcp) >= int(max_conn) and plugin_id not in {p.get("id") for p in ready_mcp}:
                raise RuntimeError(
                    f"mcp_max_connections_reached:{max_conn}; disable another MCP plugin first"
                )
        from plugin_runtime_v2 import mcp_wrapper_tool

        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        manifest = plugin.get("manifest") or {}
        mcp = manifest.get("mcp") if isinstance(manifest.get("mcp"), dict) else {}
        tools = self.db.plugin_tools(plugin_id)
        names = {item["name"] for item in tools}
        if "list_tools" not in names or "call_tool" not in names:
            return {"expanded": 0, "skipped": True, "reason": "no_mcp_wrappers"}
        if mcp.get("expand_tools") is False:
            return {"expanded": 0, "skipped": True, "reason": "expand_tools=false"}
        list_tool = next(item for item in tools if item["name"] == "list_tools")
        # Privileged install invoke may run while Ready-but-disabled; never fake Ready/enabled
        # or clear structural failure_state for expansion eligibility.
        if str(plugin.get("status") or "").lower() != "ready":
            return {"expanded": 0, "skipped": True, "reason": "not_ready"}
        if plugin.get("failure_state") in {"dependency_failed", "integrity_failed", "unsupported_runtime", "not_ready"}:
            return {"expanded": 0, "skipped": True, "reason": f"failure_state={plugin.get('failure_state')}"}
        _ = list_tool
        result = self.invoke(
            plugin_id,
            "list_tools",
            {},
            timeout=int(_setting("mcp.timeout_seconds", 90) or 90),
            invocation_type="install",
            approved_by_user=True,
            privileged_policy_skip=True,
        )
        if result.get("status") != "completed":
            raise RuntimeError(result.get("error") or "list_tools faalde")
        payload = {}
        try:
            payload = json.loads(str(result.get("stdout") or result.get("output") or "{}"))
        except Exception as exc:
            raise RuntimeError(f"list_tools gaf geen JSON: {exc}") from exc
        remote_tools = payload.get("tools") if isinstance(payload, dict) else None
        if not isinstance(remote_tools, list):
            # Some bridges nest under result.content
            remote_tools = []
            if isinstance(payload, dict):
                for key in ("tools", "items", "result"):
                    candidate = payload.get(key)
                    if isinstance(candidate, list):
                        remote_tools = candidate
                        break
                    if isinstance(candidate, dict) and isinstance(candidate.get("tools"), list):
                        remote_tools = candidate["tools"]
                        break
        existing_names = {item["name"] for item in self.db.plugin_tools(plugin_id)}
        base_tools = []
        for item in self.db.plugin_tools(plugin_id):
            if item.get("metadata", {}).get("mcp_remote"):
                continue  # rebuild remote rows
            base_tools.append(
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "input_schema": item.get("input_schema", {}),
                    "output_schema": item.get("output_schema", {}),
                    "command": item.get("command", ""),
                    **item.get("metadata", {}),
                    "enabled": item.get("enabled", True),
                }
            )
        added = 0
        for remote in remote_tools:
            if not isinstance(remote, dict):
                continue
            remote_name = str(remote.get("name") or "").strip()
            if not remote_name:
                continue
            wrapper = mcp_wrapper_tool(
                remote_name,
                str(remote.get("description") or remote_name),
                remote.get("inputSchema") if isinstance(remote.get("inputSchema"), dict) else remote.get("input_schema"),
            )
            if wrapper["name"] in existing_names and wrapper["name"] in {t["name"] for t in base_tools}:
                continue
            base_tools.append(wrapper)
            added += 1
        self.db.replace_plugin_tools(plugin_id, base_tools)
        if added:
            self.db.add_plugin_event(plugin_id, "success", f"MCP first-class: {added} remote tools geregistreerd.")
            self._refresh_capability_intel(plugin_id)
            return {"ok": True, "expanded": added, "skipped": False, "tools": len(base_tools)}
        self._refresh_capability_intel(plugin_id)
        return {
            "ok": False,
            "expanded": 0,
            "skipped": False,
            "tools": len(base_tools),
            "error": "no_remote_mcp_tools",
        }

    @staticmethod
    def _tool_action(tool: dict[str, Any]) -> str:
        return str(tool.get("metadata", {}).get("action") or tool.get("name") or "run").strip().lower()

    @staticmethod
    def _validate_tool_input(schema: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        if schema.get("type", "object") != "object":
            raise ValueError("HADES ondersteunt voor plugin-input een JSON-object als hoofdniveau.")
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        required = schema.get("required", [])
        required_names = {str(item) for item in required} if isinstance(required, list) else set()
        value = dict(input_data)
        for name, definition in properties.items():
            if not isinstance(definition, dict):
                continue
            if name not in value and "default" in definition:
                value[name] = definition["default"]
            if name in required_names and name not in value:
                raise ValueError(f"Verplicht toolveld ontbreekt: {name}")
            if name not in value:
                continue
            expected = definition.get("type")
            actual = value[name]
            expected_types = expected if isinstance(expected, list) else [expected]

            def _matches(type_name: Any) -> bool:
                return (
                    type_name in {None, "any"}
                    or type_name == "string" and isinstance(actual, str)
                    or type_name == "array" and isinstance(actual, list)
                    or type_name == "object" and isinstance(actual, dict)
                    or type_name == "boolean" and isinstance(actual, bool)
                    or type_name == "integer" and isinstance(actual, int) and not isinstance(actual, bool)
                    or type_name == "number" and isinstance(actual, (int, float)) and not isinstance(actual, bool)
                    or type_name == "null" and actual is None
                )

            valid = any(_matches(type_name) for type_name in expected_types)
            if not valid:
                raise ValueError(f"Toolveld '{name}' heeft type {expected} nodig.")
            if "enum" in definition and actual not in definition["enum"]:
                raise ValueError(f"Toolveld '{name}' moet één van de toegestane waarden gebruiken.")
            if isinstance(actual, (str, list, dict)):
                if "minLength" in definition and len(actual) < int(definition["minLength"]):
                    raise ValueError(f"Toolveld '{name}' is te kort.")
                if "maxLength" in definition and len(actual) > int(definition["maxLength"]):
                    raise ValueError(f"Toolveld '{name}' is te lang.")
                if "minItems" in definition and isinstance(actual, list) and len(actual) < int(definition["minItems"]):
                    raise ValueError(f"Toolveld '{name}' bevat te weinig waarden.")
                if "maxItems" in definition and isinstance(actual, list) and len(actual) > int(definition["maxItems"]):
                    raise ValueError(f"Toolveld '{name}' bevat te veel waarden.")
            if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                if "minimum" in definition and actual < definition["minimum"]:
                    raise ValueError(f"Toolveld '{name}' ligt onder de minimumwaarde.")
                if "maximum" in definition and actual > definition["maximum"]:
                    raise ValueError(f"Toolveld '{name}' ligt boven de maximumwaarde.")
            if "string" in expected_types and isinstance(actual, str) and definition.get("pattern"):
                try:
                    if not re.search(str(definition["pattern"]), actual):
                        raise ValueError(f"Toolveld '{name}' voldoet niet aan het vereiste patroon.")
                except re.error as exc:
                    raise ValueError(f"Tool-schema voor '{name}' bevat een ongeldig patroon.") from exc
            if "array" in expected_types and isinstance(actual, list) and isinstance(definition.get("items"), dict):
                item_type = definition["items"].get("type")
                if item_type == "string" and not all(isinstance(item, str) for item in actual):
                    raise ValueError(f"Alle waarden van toolveld '{name}' moeten strings zijn.")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ValueError("Onbekende toolvelden: " + ", ".join(unknown))
        return value

    def _command_argv(self, plugin: dict[str, Any], tool: dict[str, Any], input_data: dict[str, Any]) -> list[str]:
        command_template = tool.get("command", "")
        if isinstance(command_template, list):
            template_tokens = list(command_template)
        elif isinstance(command_template, str):
            # Legacy string commands remain supported, but do not parse Windows paths
            # with POSIX escaping rules. New manifests should use argv arrays.
            template_tokens = shlex.split(command_template, posix=os.name != "nt")
        else:
            raise ValueError("Plugin-tool heeft geen geldige command-string of argv-array.")
        runtime_dir = self.runtimes / plugin["id"]
        python_bin = runtime_dir / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        replacements: dict[str, Any] = {
            **input_data,
            "python": str(python_bin if python_bin.exists() else sys.executable),
            "npm": shutil.which("npm") or shutil.which("npm.cmd") or "npm",
            "root": str(Path(plugin["local_path"]).resolve()),
        }
        args = replacements.get("args", [])
        if args is None:
            args = []
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError("Toolveld 'args' moet een lijst strings zijn.")
        command: list[str] = []
        placeholder = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        for token in template_tokens:
            if token == "{args}":
                command.extend(args)
                continue
            names = placeholder.findall(token)
            rendered = token
            skip_optional = False
            for name in names:
                if name not in replacements:
                    if token == f"{{{name}}}":
                        skip_optional = True
                        break
                    raise ValueError(f"Commandoplaceholder heeft geen toolinput: {name}")
                raw = replacements[name]
                if isinstance(raw, (dict, list)):
                    if token != f"{{{name}}}":
                        raise ValueError(f"Complex toolveld '{name}' moet als los commandotoken worden gebruikt.")
                    # Dict/list tool inputs are JSON values. Keep them as one argv token so
                    # adapters can parse structured GeoJSON, bbox arrays, filters, etc.
                    # Intentional multi-argv spreading remains available via the {args} token.
                    command.append(json.dumps(raw, ensure_ascii=False))
                    rendered = ""
                    break
                rendered = rendered.replace(f"{{{name}}}", "" if raw is None else str(raw).lower() if isinstance(raw, bool) else str(raw))
            if skip_optional:
                continue
            if rendered:
                command.append(rendered)
        if not command:
            raise ValueError("Plugin-tool heeft geen uitvoerbaar commando.")
        if any("\x00" in part for part in command):
            raise ValueError("Nulbytes zijn niet toegestaan in subprocess-argumenten.")
        return command

    @staticmethod
    def _plugin_isolation_tier(plugin: dict[str, Any]) -> str:
        """Resolve isolation tier: plugin field, else process HADES_PLUGIN_ISOLATION=secured."""
        from plugin_runtime_v2 import normalize_isolation

        raw = plugin.get("isolation") or (plugin.get("manifest") or {}).get("isolation")
        env_iso = str(os.environ.get("HADES_PLUGIN_ISOLATION") or "").strip().lower()
        # Process-level secured request hardens all plugin commands fail-closed.
        if env_iso == "secured":
            return normalize_isolation("secured")
        return normalize_isolation(raw)

    def _command_environment(self, plugin: dict[str, Any], tool: dict[str, Any]) -> dict[str, str]:
        from plugin_runtime_v2 import authorized_plugin_environment

        isolation = self._plugin_isolation_tier(plugin)
        env = authorized_plugin_environment(os.environ.copy(), plugin, tool)
        configured = tool.get("metadata", {}).get("env", {})
        if configured:
            if not isinstance(configured, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in configured.items()):
                raise ValueError("Tool-env moet een object met alleen stringwaarden zijn.")
            env.update(configured)
        env["HADES_PLUGIN_ID"] = str(plugin.get("id") or "")
        env["HADES_PLUGIN_ISOLATION"] = isolation
        env["HADES_PLUGIN_REQUESTED_ISOLATION"] = isolation
        # Force UTF-8 for plugin Python/Node children. Windows CI defaults to a
        # legacy code page; bridges that print JSON with Unicode (em dash, Dutch
        # accents) otherwise exit 1 with UnicodeEncodeError.
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        # Isolation honesty: weaker host-process tiers are not OS/container sandboxes.
        # Container is fail-closed until a real adapter exists (never degrade to restricted_env).
        # Secured never falls back to unbounded subprocess — see _run_command_secured.
        if isolation == "container":
            env["HADES_PLUGIN_ISOLATION"] = "container"
            env["HADES_PLUGIN_ISOLATION_NOTE"] = "container_not_implemented"
            env["HADES_PLUGIN_EFFECTIVE_ISOLATION"] = "none"
            env["HADES_PLUGIN_FS_SANDBOX"] = "false"
            env["HADES_PLUGIN_ISOLATION_KIND"] = "unavailable"
        elif isolation == "secured":
            # restricted_environment stamps restricted_env; restore secured label.
            env["HADES_PLUGIN_ISOLATION"] = "secured"
            env["HADES_PLUGIN_EFFECTIVE_ISOLATION"] = "secured"
            # Actual FS enforcement is confirmed only after run_isolated succeeds.
            env["HADES_PLUGIN_FS_SANDBOX"] = "pending"
            env["HADES_PLUGIN_ISOLATION_KIND"] = "secured"
        elif isolation in {"restricted_env", "temp_workspace"}:
            env["HADES_PLUGIN_EFFECTIVE_ISOLATION"] = isolation
            env["HADES_PLUGIN_FS_SANDBOX"] = "false"
            env["HADES_PLUGIN_ISOLATION_KIND"] = "host_process_env"
        else:
            # plugin_cwd / none — working-directory / no isolation claim.
            env["HADES_PLUGIN_EFFECTIVE_ISOLATION"] = isolation or "plugin_cwd"
            env["HADES_PLUGIN_FS_SANDBOX"] = "false"
            env["HADES_PLUGIN_ISOLATION_KIND"] = "host_process"
        return env

    def _plugin_workdir(self, plugin: dict[str, Any]) -> Path:
        from plugin_runtime_v2 import resolve_workdir

        isolation = self._plugin_isolation_tier(plugin)
        # Container is refused at _run_command; workdir resolution still uses restricted paths.
        if isolation == "container":
            isolation = "restricted_env"
        return resolve_workdir(plugin, isolation, self.runtimes)

    @staticmethod
    def _combined_output(stdout: str, stderr: str) -> str:
        return "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)[-100_000:]

    @staticmethod
    def _invocation_fields_from_command_result(result: dict[str, Any]) -> dict[str, Any]:
        """Map _run_command output to _finish_invocation kwargs (ignore honesty extras)."""
        known = {
            "stdout": result.get("stdout") or "",
            "stderr": result.get("stderr") or "",
            "exit_code": result.get("exit_code"),
            "error": result.get("error"),
        }
        meta: dict[str, Any] = {}
        for key in (
            "error_code",
            "effective_executor",
            "executor_requested",
            "executor_effective",
            "native_fallback",
            "native_error",
            "effective_isolation",
            "requested_isolation",
            "native_runtime_mode",
            "isolation_mode",
            "isolation_enforced",
            "fs_isolation",
            "filesystem_sandbox",
            "network_isolation",
            "adapter",
            "isolation_kind",
        ):
            if key in result and result.get(key) is not None:
                meta[key] = result.get(key)
        if meta:
            known["metadata"] = meta
        return known

    @staticmethod
    def _isolation_truth_from_env(env: dict[str, str]) -> dict[str, Any]:
        """Propagate requested vs effective isolation honesty from command env."""
        requested = str(
            env.get("HADES_PLUGIN_REQUESTED_ISOLATION") or env.get("HADES_PLUGIN_ISOLATION") or ""
        ).strip().lower()
        effective = str(env.get("HADES_PLUGIN_EFFECTIVE_ISOLATION") or requested or "").strip().lower()
        fs_raw = str(env.get("HADES_PLUGIN_FS_SANDBOX") or "false").strip().lower()
        filesystem_sandbox = fs_raw in {"true", "1", "yes"}
        # Host-process tiers never claim FS sandbox even if env is incomplete.
        if effective in {"plugin_cwd", "restricted_env", "temp_workspace", "none", ""}:
            filesystem_sandbox = False
        return {
            "requested_isolation": requested or None,
            "effective_isolation": effective or None,
            "filesystem_sandbox": filesystem_sandbox,
            "isolation_kind": str(env.get("HADES_PLUGIN_ISOLATION_KIND") or "").strip() or None,
        }

    @staticmethod
    def _wants_secured_execution(env: dict[str, str]) -> bool:
        return str(env.get("HADES_PLUGIN_ISOLATION") or "").strip().lower() == "secured"

    def _run_command_secured(
        self,
        command: list[str],
        *,
        root: Path,
        env: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        """Fail-closed secured execution via execution_isolation (no native/unbounded fallback)."""
        from execution_isolation import (
            IsolationPolicy,
            IsolationUnavailable,
            SECURED_MODE,
            run_isolated,
        )

        truth = self._isolation_truth_from_env(env)
        workdir = Path(root).expanduser().resolve(strict=False)
        allowlist = list(IsolationPolicy().env_allowlist)
        for key in env:
            upper = str(key).upper()
            if upper.startswith("HADES_PLUGIN_") or upper in {"PYTHONPATH", "VIRTUAL_ENV"}:
                allowlist.append(str(key))
        policy = IsolationPolicy(
            read_roots=[workdir],
            write_roots=[workdir],
            allow_network=False,
            mode=SECURED_MODE,
            env_allowlist=allowlist,
        )
        try:
            isolated = run_isolated(
                command,
                cwd=workdir,
                policy=policy,
                timeout_seconds=float(timeout) if timeout else None,
                env=env,
            )
        except IsolationUnavailable as exc:
            detail = str(exc)
            return {
                "stdout": "",
                "stderr": detail,
                "exit_code": None,
                "error": (
                    "Secured plugin isolation unavailable; refusing unbounded execution. "
                    f"{detail}"
                ),
                "error_code": "secured_isolation_unavailable",
                "isolation_mode": SECURED_MODE,
                "isolation_enforced": False,
                "fs_isolation": False,
                "filesystem_sandbox": False,
                "adapter": None,
                "requested_isolation": truth.get("requested_isolation") or "secured",
                "effective_isolation": "none",
                "executor_requested": "secured",
                "executor_effective": "none",
                "effective_executor": "secured_failed",
            }
        if isolated.reason == "timeout" or isolated.exit_code == 124:
            return {
                "stdout": isolated.stdout or "",
                "stderr": isolated.stderr or "",
                "exit_code": None,
                "error": f"Tooltimeout na {timeout} seconden.",
                "isolation_mode": isolated.mode,
                "isolation_enforced": isolated.isolation_enforced,
                "fs_isolation": isolated.fs_isolation,
                "filesystem_sandbox": bool(isolated.fs_isolation),
                "adapter": isolated.adapter,
                "requested_isolation": truth.get("requested_isolation") or "secured",
                "effective_isolation": "secured" if isolated.isolation_enforced else "none",
                "executor_effective": "secured",
                "effective_executor": "secured",
            }
        exit_code = isolated.exit_code
        return {
            "stdout": isolated.stdout or "",
            "stderr": isolated.stderr or "",
            "exit_code": exit_code,
            "error": None if exit_code == 0 else f"Subprocess eindigde met exitcode {exit_code}.",
            "isolation_mode": isolated.mode,
            "isolation_enforced": isolated.isolation_enforced,
            "fs_isolation": isolated.fs_isolation,
            "filesystem_sandbox": bool(isolated.fs_isolation),
            "network_isolation": isolated.network_isolation,
            "adapter": isolated.adapter,
            "requested_isolation": truth.get("requested_isolation") or "secured",
            "effective_isolation": "secured" if isolated.isolation_enforced else "none",
            "executor_effective": "secured",
            "effective_executor": "secured",
        }

    def _run_command(
        self,
        command: list[str],
        *,
        root: Path,
        env: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        # Secured: never use native companion or unbounded subprocess — fail closed via run_isolated.
        if self._wants_secured_execution(env):
            return self._run_command_secured(command, root=root, env=env, timeout=timeout)

        truth = self._isolation_truth_from_env(env)
        requested_isolation = str(truth.get("requested_isolation") or "").strip().lower()
        # Container means real container execution only — not implemented ⇒ refuse.
        # Docker on PATH is irrelevant without a HADES container adapter.
        if requested_isolation == "container" or str(env.get("HADES_PLUGIN_ISOLATION_NOTE") or "").startswith(
            "container_not_implemented"
        ):
            return {
                "stdout": "",
                "stderr": "container_not_implemented",
                "exit_code": None,
                "error": (
                    "Plugin requested isolation=container but HADES has no container "
                    "execution adapter; refusing host subprocess execution."
                ),
                "error_code": "container_not_implemented",
                "requested_isolation": "container",
                "effective_isolation": "none",
                "isolation_enforced": False,
                "filesystem_sandbox": False,
                "executor_requested": "container",
                "executor_effective": "none",
                "effective_executor": "refused",
            }

        native = self._native_runtime
        native_mode = "auto"
        native_required = False
        native_fallback = False
        native_error: str | None = None
        executor_requested = "python"
        if native is not None:
            try:
                status = native.status()
                native_mode = str(getattr(status, "mode", None) or "auto").lower()
                native_required = native_mode == "enabled"
                if status.connected and not status.fallback_active:
                    executor_requested = "native"
                    executable = command[0]
                    argv = list(command[1:])
                    try:
                        result = native.process_run(
                            executable=executable,
                            argv=argv,
                            cwd=str(root),
                            env=env,
                            timeout_ms=int(timeout) * 1000 if timeout else None,
                        )
                    except Exception as exc:
                        # Required native boundary must not silently weaken to subprocess.
                        if native_required:
                            return {
                                "stdout": "",
                                "stderr": str(exc),
                                "exit_code": None,
                                "error": f"native_executor_failed: {type(exc).__name__}",
                                "error_code": "native_executor_failed",
                                "native_runtime_mode": native_mode,
                                "executor_requested": "native",
                                "executor_effective": "none",
                                "effective_executor": "native_failed",
                                "native_fallback": False,
                                "native_error": type(exc).__name__,
                                **{k: v for k, v in truth.items() if v is not None},
                            }
                        # auto mode: Python fallback only for non-security-bound host tiers.
                        native_fallback = True
                        native_error = type(exc).__name__
                    else:
                        exit_code = result.get("exit_code")
                        timed_out = bool(result.get("timed_out"))
                        cancelled = bool(result.get("cancelled"))
                        stdout = result.get("stdout") or ""
                        stderr = result.get("stderr") or ""
                        base = {
                            "executor_requested": "native",
                            "executor_effective": "native",
                            "effective_executor": "native",
                            "native_fallback": False,
                            "native_runtime_mode": native_mode,
                            **{k: v for k, v in truth.items() if v is not None},
                        }
                        if timed_out:
                            return {
                                "stdout": stdout,
                                "stderr": stderr,
                                "exit_code": None,
                                "error": f"Tooltimeout na {timeout} seconden.",
                                **base,
                            }
                        if cancelled:
                            return {
                                "stdout": stdout,
                                "stderr": stderr,
                                "exit_code": exit_code,
                                "error": "Proces geannuleerd.",
                                **base,
                            }
                        return {
                            "stdout": stdout,
                            "stderr": stderr,
                            "exit_code": exit_code,
                            "error": None if exit_code == 0 else f"Subprocess eindigde met exitcode {exit_code}.",
                            **base,
                        }
                elif native_required and not status.connected:
                    return {
                        "stdout": "",
                        "stderr": status.last_error or "native runtime not connected",
                        "exit_code": None,
                        "error": "native_executor_failed: native runtime required but not connected",
                        "error_code": "native_executor_failed",
                        "native_runtime_mode": native_mode,
                        "executor_requested": "native",
                        "executor_effective": "none",
                        "effective_executor": "native_unavailable",
                        "native_fallback": False,
                        **{k: v for k, v in truth.items() if v is not None},
                    }
            except Exception as exc:
                if native_required:
                    return {
                        "stdout": "",
                        "stderr": str(exc),
                        "exit_code": None,
                        "error": f"native_executor_failed: {type(exc).__name__}",
                        "error_code": "native_executor_failed",
                        "native_runtime_mode": native_mode,
                        "executor_requested": "native",
                        "executor_effective": "none",
                        "effective_executor": "native_failed",
                        "native_fallback": False,
                        "native_error": type(exc).__name__,
                        **{k: v for k, v in truth.items() if v is not None},
                    }
                # auto: observe fallback then continue to Python executor.
                native_fallback = True
                native_error = type(exc).__name__
                executor_requested = "native"
        try:
            process = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
            return {
                "stdout": process.stdout or "",
                "stderr": process.stderr or "",
                "exit_code": process.returncode,
                "error": None if process.returncode == 0 else f"Subprocess eindigde met exitcode {process.returncode}.",
                "executor_requested": executor_requested,
                "executor_effective": "python",
                "effective_executor": "python",
                "native_fallback": bool(native_fallback),
                "native_error": native_error,
                "native_runtime_mode": native_mode if native is not None else None,
                **{k: v for k, v in truth.items() if v is not None},
            }
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": None,
                "error": f"Tooltimeout na {timeout} seconden.",
                "executor_requested": executor_requested,
                "executor_effective": "python",
                "effective_executor": "python",
                "native_fallback": bool(native_fallback),
                "native_error": native_error,
                **{k: v for k, v in truth.items() if v is not None},
            }
        except OSError as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "exit_code": None,
                "error": f"Subprocess kon niet starten: {exc}",
                "executor_requested": executor_requested,
                "executor_effective": "python",
                "effective_executor": "python",
                "native_fallback": bool(native_fallback),
                "native_error": native_error,
                **{k: v for k, v in truth.items() if v is not None},
            }

    def _service_log_paths(self, plugin_id: str) -> tuple[Path, Path]:
        runtime = self.runtimes / plugin_id
        runtime.mkdir(parents=True, exist_ok=True)
        return runtime / "service.stdout.log", runtime / "service.stderr.log"

    def _read_service_logs(self, plugin_id: str) -> tuple[str, str]:
        stdout_path, stderr_path = self._service_log_paths(plugin_id)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")[-100_000:] if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[-100_000:] if stderr_path.exists() else ""
        return stdout, stderr

    def _terminate_managed_process(self, plugin_id: str) -> bool:
        native = self._native_runtime
        native_stopped = False
        if native is not None:
            try:
                from plugin_runtime_v2 import read_service_state

                state = read_service_state(self.runtimes, plugin_id) or {}
                service_id = state.get("native_service_id") or f"plugin:{plugin_id}"
                if state.get("executor") == "native" or native.status().connected:
                    try:
                        native.service_stop(str(service_id))
                        native_stopped = True
                    except Exception:
                        pass
            except Exception:
                pass
        with self._process_lock:
            managed = self._processes.pop(plugin_id, None)
        if not managed:
            return native_stopped
        try:
            if managed.process.poll() is None:
                if os.name != "nt":
                    try:
                        os.killpg(os.getpgid(managed.process.pid), signal.SIGTERM)
                    except (AttributeError, OSError):
                        managed.process.terminate()
                else:
                    managed.process.terminate()
                try:
                    managed.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        try:
                            os.killpg(os.getpgid(managed.process.pid), signal.SIGKILL)
                        except (AttributeError, OSError):
                            managed.process.kill()
                    else:
                        managed.process.kill()
                    managed.process.wait(timeout=5)
        finally:
            managed.stdout_handle.close()
            managed.stderr_handle.close()
        return True

    def reconcile_services(self) -> None:
        """Correct stale persisted service health after a HADES process restart.

        Truth sources: service.state.json (PID + start identity) AND declared healthcheck.
        Persisted 'healthy' without proof becomes needs_attention/stopped.
        """
        from plugin_runtime_v2 import clear_service_state, process_identity_matches, read_service_state, write_service_state

        for plugin in self.db.list_plugins():
            plugin_id = plugin["id"]
            with self._service_lock_for(plugin_id):
                self._reconcile_one_service(plugin, clear_service_state, process_identity_matches, read_service_state, write_service_state)

    def _reconcile_one_service(
        self,
        plugin: dict[str, Any],
        clear_service_state: Any,
        process_identity_matches: Any,
        read_service_state: Any,
        write_service_state: Any,
    ) -> None:
        plugin_id = plugin["id"]
        state = read_service_state(self.runtimes, plugin_id)
        claimed_healthy = plugin.get("health") in {"healthy", "running", "starting"}
        if not claimed_healthy and not state:
            return
        healthcheck = self._explicit_healthcheck(plugin)
        pid = int(state.get("pid") or 0) if state else 0
        started_at = state.get("started_at") if state else None
        alive = process_identity_matches(pid, started_at) if pid else False
        if state:
            write_service_state(
                self.runtimes,
                plugin_id,
                {**state, "alive": alive, "reconciled": True, "status": "alive" if alive else "dead"},
            )
        if not healthcheck:
            if claimed_healthy:
                self.db.set_plugin_state(
                    plugin_id,
                    health="needs_attention",
                    last_error="Service-status kon na herstart niet worden geverifieerd (geen healthcheck).",
                    failure_state="health_unverified",
                )
                self.db.add_plugin_event(plugin_id, "warning", "Restart reconcile: geen healthcheck; status gecorrigeerd.")
            if state and not alive:
                clear_service_state(self.runtimes, plugin_id)
            return
        health = self._healthcheck(plugin, healthcheck, allow_remote=False)
        if health["healthy"]:
            # Externally healthy (e.g. docker-compose) is allowed, but management may be orphaned.
            note = ""
            if state and not alive:
                note = "Service bereikbaar na herstart, maar beheerd proces is niet meer van HADES."
                clear_service_state(self.runtimes, plugin_id)
            elif state and alive:
                # Re-attach in-memory handle is impossible for arbitrary children; keep state file as truth.
                note = f"Service bereikbaar; PID {pid} nog actief."
            self.db.set_plugin_state(plugin_id, health="healthy", last_error=note, clear_failure=True)
            self.db.add_plugin_event(plugin_id, "info", f"Restart reconcile: healthy. {note}".strip())
        else:
            if alive:
                # PID alive but unhealthy → terminate if we still manage it in-memory; else mark attention.
                self._terminate_managed_process(plugin_id)
            clear_service_state(self.runtimes, plugin_id)
            self.db.set_plugin_state(
                plugin_id,
                health="stopped",
                last_error=f"Service-status na herstart: {health.get('detail', 'niet bereikbaar')}",
                failure_state="health_failed",
            )
            self.db.add_plugin_event(plugin_id, "warning", "Restart reconcile: service niet bereikbaar; status=stopped.")

    def _explicit_healthcheck(self, plugin: dict[str, Any], tool: dict[str, Any] | None = None) -> dict[str, Any] | None:
        healthcheck = tool.get("metadata", {}).get("healthcheck") if tool else None
        if healthcheck is None:
            healthcheck = plugin.get("manifest", {}).get("healthcheck")
        if healthcheck is None and tool and self._tool_action(tool) in {"start", "serve", "dev", "stop"}:
            health_tool = next(
                (
                    item for item in self.db.plugin_tools(plugin["id"])
                    if self._tool_action(item) in {"health", "status"} and item.get("command")
                ),
                None,
            )
            if health_tool:
                healthcheck = {"type": "command", "command": health_tool["command"]}
        if isinstance(healthcheck, str):
            healthcheck = {"type": "http", "url": healthcheck}
        return healthcheck if isinstance(healthcheck, dict) else None

    @staticmethod
    def _loopback_host(host: str | None) -> bool:
        value = str(host or "").strip().lower().strip("[]")
        return value in {"127.0.0.1", "localhost", "::1"}

    def _plugin_allows_remote_healthcheck(self, plugin: dict[str, Any]) -> bool:
        permissions = plugin.get("permissions") or []
        if isinstance(permissions, list) and "network" in permissions:
            return True
        caps = (plugin.get("manifest") or {}).get("capabilities") or plugin.get("capabilities") or {}
        effects = caps.get("effects") if isinstance(caps, dict) else []
        return isinstance(effects, list) and "network" in effects

    def _healthcheck(
        self,
        plugin: dict[str, Any],
        definition: dict[str, Any],
        timeout: float = 3.0,
        *,
        allow_remote: bool | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        check_type = str(definition.get("type", "http")).lower()
        remote_ok = self._plugin_allows_remote_healthcheck(plugin) if allow_remote is None else bool(allow_remote)
        try:
            if check_type == "http":
                url = str(definition.get("url", "")).strip()
                if not url.startswith(("http://", "https://")):
                    raise ValueError("HTTP-healthcheck mist een geldige http(s)-URL.")
                from urllib.parse import urlparse

                host = urlparse(url).hostname or ""
                if not self._loopback_host(host) and not remote_ok:
                    return {
                        "healthy": False,
                        "detail": f"HTTP-healthcheck host '{host}' is niet-lokaal; network-capability of goedkeuring vereist.",
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                method = str(definition.get("method", "GET")).upper()
                if method not in {"GET", "HEAD"}:
                    raise ValueError("HTTP-healthcheck ondersteunt alleen GET of HEAD.")
                # No redirects: loopback healthchecks must not follow open redirects off-host (SSRF).
                with httpx.Client(timeout=max(.1, timeout), follow_redirects=False, trust_env=False) as client:
                    response = client.request(method, url)
                expected = definition.get("expected_status", definition.get("status", [200]))
                expected_codes = {int(item) for item in expected} if isinstance(expected, list) else {int(expected)}
                if response.status_code in {301, 302, 303, 307, 308}:
                    return {
                        "healthy": False,
                        "detail": f"HTTP-healthcheck weigerde redirect ({response.status_code}).",
                        "status_code": response.status_code,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                if response.status_code not in expected_codes:
                    return {"healthy": False, "detail": f"HTTP {response.status_code}; verwacht {sorted(expected_codes)}.", "status_code": response.status_code, "latency_ms": round((time.perf_counter() - started) * 1000)}
                contains = str(definition.get("contains", ""))
                if contains and contains not in response.text:
                    return {"healthy": False, "detail": "Healthresponse mist de vereiste inhoud.", "status_code": response.status_code, "latency_ms": round((time.perf_counter() - started) * 1000)}
                return {"healthy": True, "detail": f"HTTP-healthcheck bereikbaar ({response.status_code}).", "status_code": response.status_code, "latency_ms": round((time.perf_counter() - started) * 1000)}
            if check_type == "tcp":
                host = str(definition.get("host", "127.0.0.1"))
                if not self._loopback_host(host) and not remote_ok:
                    return {
                        "healthy": False,
                        "detail": f"TCP-healthcheck host '{host}' is niet-lokaal; network-capability of goedkeuring vereist.",
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                port = int(definition.get("port", 0))
                if not 1 <= port <= 65535:
                    raise ValueError("TCP-healthcheck heeft een geldige poort nodig.")
                with socket.create_connection((host, port), timeout=max(.1, timeout)):
                    pass
                return {"healthy": True, "detail": f"TCP-healthcheck bereikbaar op {host}:{port}.", "latency_ms": round((time.perf_counter() - started) * 1000)}
            if check_type == "command":
                command = definition.get("command", [])
                temp_tool = {"command": command, "metadata": {}}
                argv = self._command_argv(plugin, temp_tool, {})
                result = self._run_command(argv, root=self._plugin_workdir(plugin), env=self._command_environment(plugin, temp_tool), timeout=max(1, round(timeout)))
                return {
                    "healthy": result["exit_code"] == 0,
                    "detail": result["stdout"].strip() or result["stderr"].strip() or result["error"] or "Healthcommando geslaagd.",
                    "exit_code": result["exit_code"],
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            raise ValueError(f"Niet-ondersteund healthchecktype: {check_type}")
        except Exception as exc:
            return {"healthy": False, "detail": str(exc), "latency_ms": round((time.perf_counter() - started) * 1000)}

    def _wait_for_health(
        self,
        plugin: dict[str, Any],
        definition: dict[str, Any],
        *,
        timeout: int,
        wanted: bool,
    ) -> dict[str, Any]:
        configured_timeout = max(.2, min(float(definition.get("timeout_seconds", timeout)), float(timeout)))
        interval = max(.05, min(float(definition.get("interval_seconds", .25)), 5.0))
        deadline = time.monotonic() + configured_timeout
        last = {"healthy": False, "detail": "Healthcheck is nog niet uitgevoerd."}
        while True:
            last = self._healthcheck(plugin, definition, timeout=min(3.0, configured_timeout))
            if bool(last["healthy"]) is wanted:
                return last
            if time.monotonic() >= deadline:
                return last
            time.sleep(min(interval, max(0, deadline - time.monotonic())))

    def _finish_invocation(
        self,
        call_id: str,
        plugin: dict[str, Any],
        tool: dict[str, Any],
        *,
        status: str,
        started: float,
        stdout: str = "",
        stderr: str = "",
        exit_code: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        health: str | None = None,
    ) -> dict[str, Any]:
        duration = round((time.perf_counter() - started) * 1000)
        output = self._combined_output(stdout, stderr)
        record = self.db.finish_tool_call(
            call_id,
            status,
            output=output,
            stdout=stdout,
            stderr=stderr,
            error=error,
            exit_code=exit_code,
            duration_ms=duration,
            metadata={"action": self._tool_action(tool), **(metadata or {})},
        ) or {}
        if status == "completed":
            self.db.set_plugin_state(plugin["id"], health=health or plugin.get("health", "prepared"), last_error="")
            self.db.add_plugin_event(plugin["id"], "success", f"Tool '{tool['name']}' voltooid in {duration} ms.")
        else:
            self.db.set_plugin_state(plugin["id"], health=health or "needs_attention", last_error=error or stderr[-2000:] or "Tooluitvoering mislukt.")
            self.db.add_plugin_event(plugin["id"], "error", f"Tool '{tool['name']}' {status}: {error or stderr[-500:] or 'onbekende fout'}")
        return record

    def record_rejected_call(
        self,
        plugin_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        *,
        invocation_type: str,
        approved_by_user: bool,
        status: str,
        error: str,
    ) -> dict[str, Any]:
        call_id = self.db.create_tool_call(
            plugin_id,
            tool_name,
            input_data,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            metadata={"rejected": True},
        )
        record = self.db.finish_tool_call(call_id, status, stderr=error, error=error, duration_ms=0, metadata={"rejected": True}) or {}
        self.db.add_plugin_event(plugin_id, "warning", f"Tool '{tool_name}' geblokkeerd: {error}")
        return record

    def _start_service(
        self,
        plugin: dict[str, Any],
        tool: dict[str, Any],
        command: list[str],
        input_data: dict[str, Any],
        call_id: str,
        started: float,
        timeout: int,
    ) -> dict[str, Any]:
        # Isolation must match one-shot invoke: never silently start a host process
        # when container/secured was requested but cannot be established.
        start_env = self._command_environment(plugin, tool)
        truth = self._isolation_truth_from_env(start_env)
        requested_isolation = str(truth.get("requested_isolation") or "").strip().lower()
        if requested_isolation == "container" or str(start_env.get("HADES_PLUGIN_ISOLATION_NOTE") or "").startswith(
            "container_not_implemented"
        ):
            return self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="failed",
                started=started,
                stderr="container_not_implemented",
                error=(
                    "Plugin requested isolation=container but HADES has no container "
                    "adapter; refusing service start (no host-process fallback)."
                ),
                metadata={
                    "error_code": "container_not_implemented",
                    "requested_isolation": "container",
                    "effective_isolation": "none",
                    "filesystem_sandbox": False,
                    "executor_requested": "container",
                    "executor_effective": "none",
                    "action": "start",
                },
                health="unhealthy",
            )
        if requested_isolation == "secured" or self._wants_secured_execution(start_env):
            return self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="failed",
                started=started,
                stderr="secured_service_start_not_implemented",
                error=(
                    "Plugin requested isolation=secured but service start has no "
                    "secured long-running adapter; refusing ordinary subprocess.Popen."
                ),
                metadata={
                    "error_code": "secured_service_start_not_implemented",
                    "requested_isolation": "secured",
                    "effective_isolation": "none",
                    "filesystem_sandbox": False,
                    "executor_requested": "secured",
                    "executor_effective": "none",
                    "action": "start",
                },
                health="unhealthy",
            )
        healthcheck = self._explicit_healthcheck(plugin, tool)
        if not healthcheck:
            return self._finish_invocation(
                call_id, plugin, tool, status="failed", started=started,
                error="Start geweigerd: een service-tool heeft een expliciete HTTP-, TCP- of command-healthcheck nodig.",
                health="unhealthy",
            )
        initial = self._healthcheck(plugin, healthcheck, timeout=1.0)
        if initial["healthy"]:
            from plugin_runtime_v2 import process_identity_matches, read_service_state

            state = read_service_state(self.runtimes, plugin["id"]) or {}
            pid = int(state.get("pid") or 0)
            started_at = state.get("started_at")
            managed_alive = bool(pid) and process_identity_matches(pid, started_at)
            in_memory = plugin["id"] in self._processes
            if managed_alive or in_memory:
                return self._finish_invocation(
                    call_id, plugin, tool, status="completed", started=started, stdout="Service was al bereikbaar.",
                    exit_code=0, metadata={"healthcheck": initial, "already_running": True, "managed": True}, health="healthy",
                )
            return self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="failed",
                started=started,
                error=(
                    "Healthcheck is bereikbaar, maar HADES beheert dit proces niet "
                    "(poort/service mogelijk bezet door een externe instantie)."
                ),
                metadata={"healthcheck": initial, "already_running": True, "managed": False},
                health="needs_attention",
            )
        self._terminate_managed_process(plugin["id"])
        stdout_path, stderr_path = self._service_log_paths(plugin["id"])
        native = self._native_runtime
        native_service_id = f"plugin:{plugin['id']}"
        if native is not None:
            try:
                nstatus = native.status()
                if nstatus.connected and not nstatus.fallback_active:
                    try:
                        native.service_stop(native_service_id)
                    except Exception:
                        pass
                    native_started = native.service_start(
                        id=native_service_id,
                        executable=command[0],
                        argv=list(command[1:]),
                        cwd=str(self._plugin_workdir(plugin)),
                        env=self._command_environment(plugin, tool),
                        log_dir=str(self.runtimes / plugin["id"]),
                    )
                    from plugin_runtime_v2 import clear_service_state, write_service_state

                    started_at = float(native_started.get("started_at") or time.time())
                    pid = int(native_started.get("pid") or 0)
                    creation_time = native_started.get("creation_time") or native_started.get("process_creation_time")
                    write_service_state(
                        self.runtimes,
                        plugin["id"],
                        {
                            "pid": pid,
                            "started_at": started_at,
                            "command": command,
                            "status": "starting",
                            "health": "starting",
                            "executor": "native",
                            "native_service_id": native_service_id,
                            "process_creation_time": creation_time,
                        },
                    )
                    health = self._wait_for_health(plugin, healthcheck, timeout=timeout, wanted=True)
                    if health["healthy"]:
                        write_service_state(
                            self.runtimes,
                            plugin["id"],
                            {
                                "pid": pid,
                                "started_at": started_at,
                                "command": command,
                                "status": "running",
                                "health": "healthy",
                                "alive": True,
                                "executor": "native",
                                "native_service_id": native_service_id,
                                "process_creation_time": creation_time,
                            },
                        )
                        stdout, stderr = self._read_service_logs(plugin["id"])
                        return self._finish_invocation(
                            call_id,
                            plugin,
                            tool,
                            status="completed",
                            started=started,
                            stdout=stdout,
                            stderr=stderr,
                            exit_code=None,
                            metadata={"healthcheck": health, "pid": pid, "executor": "native"},
                            health="healthy",
                        )
                    try:
                        native.service_stop(native_service_id)
                    except Exception:
                        pass
                    clear_service_state(self.runtimes, plugin["id"])
                    stdout, stderr = self._read_service_logs(plugin["id"])
                    error = f"Service is niet bereikbaar na start: {health.get('detail', 'healthcheck mislukt')}."
                    return self._finish_invocation(
                        call_id,
                        plugin,
                        tool,
                        status="failed",
                        started=started,
                        stdout=stdout,
                        stderr=stderr,
                        exit_code=None,
                        error=error,
                        metadata={"healthcheck": health, "executor": "native"},
                        health="unhealthy",
                    )
            except Exception:
                pass
        stdout_handle = stdout_path.open("a", encoding="utf-8", buffering=1)
        stderr_handle = stderr_path.open("a", encoding="utf-8", buffering=1)
        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                cwd=self._plugin_workdir(plugin),
                env=self._command_environment(plugin, tool),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except Exception as exc:
            stdout_handle.close()
            stderr_handle.close()
            return self._finish_invocation(call_id, plugin, tool, status="failed", started=started, stderr=str(exc), error=f"Serviceproces kon niet starten: {exc}", health="unhealthy")
        from plugin_runtime_v2 import clear_service_state, write_service_state

        started_at = time.time()
        write_service_state(
            self.runtimes,
            plugin["id"],
            {
                "pid": process.pid,
                "started_at": started_at,
                "command": command,
                "status": "starting",
                "health": "starting",
            },
        )
        managed = ManagedPluginProcess(process, stdout_handle, stderr_handle, command)
        with self._process_lock:
            self._processes[plugin["id"]] = managed
        health = self._wait_for_health(plugin, healthcheck, timeout=timeout, wanted=True)
        if health["healthy"]:
            if process.poll() is not None:
                with self._process_lock:
                    self._processes.pop(plugin["id"], None)
                stdout_handle.close()
                stderr_handle.close()
                clear_service_state(self.runtimes, plugin["id"])
                stdout, stderr = self._read_service_logs(plugin["id"])
                exit_code = process.returncode
                error = (
                    f"Service process exited immediately after start "
                    f"(exit_code={exit_code})."
                )
                return self._finish_invocation(
                    call_id,
                    plugin,
                    tool,
                    status="failed",
                    started=started,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code if exit_code is not None else 1,
                    error=error,
                    metadata={"healthcheck": health, "pid": process.pid, "process_exited_after_start": True},
                    health="unhealthy",
                )
            write_service_state(
                self.runtimes,
                plugin["id"],
                {
                    "pid": process.pid,
                    "started_at": started_at,
                    "command": command,
                    "status": "running",
                    "health": "healthy",
                    "alive": True,
                },
            )
            stdout, stderr = self._read_service_logs(plugin["id"])
            return self._finish_invocation(
                call_id, plugin, tool, status="completed", started=started, stdout=stdout, stderr=stderr,
                exit_code=process.returncode, metadata={"healthcheck": health, "pid": process.pid}, health="healthy",
            )
        self._terminate_managed_process(plugin["id"])
        clear_service_state(self.runtimes, plugin["id"])
        stdout, stderr = self._read_service_logs(plugin["id"])
        error = f"Service is niet bereikbaar na start: {health.get('detail', 'healthcheck mislukt')}."
        return self._finish_invocation(
            call_id, plugin, tool, status="failed", started=started, stdout=stdout, stderr=stderr,
            exit_code=process.returncode, error=error, metadata={"healthcheck": health}, health="unhealthy",
        )

    def _stop_service(
        self,
        plugin: dict[str, Any],
        tool: dict[str, Any],
        command: list[str] | None,
        call_id: str,
        started: float,
        timeout: int,
    ) -> dict[str, Any]:
        from plugin_runtime_v2 import clear_service_state

        command_result = {"stdout": "", "stderr": "", "exit_code": 0, "error": None}
        if command:
            command_result = self._run_command(command, root=self._plugin_workdir(plugin), env=self._command_environment(plugin, tool), timeout=timeout)
        managed_stopped = self._terminate_managed_process(plugin["id"])
        if not command and not managed_stopped:
            return self._finish_invocation(call_id, plugin, tool, status="failed", started=started, error="Geen actief HADES-serviceproces of stopcommando beschikbaar.")
        if command_result["error"]:
            return self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="failed",
                started=started,
                **self._invocation_fields_from_command_result(command_result),
            )
        healthcheck = self._explicit_healthcheck(plugin, tool)
        if healthcheck:
            health = self._wait_for_health(plugin, healthcheck, timeout=timeout, wanted=False)
            if health["healthy"]:
                return self._finish_invocation(
                    call_id, plugin, tool, status="failed", started=started,
                    stdout=command_result["stdout"], stderr=command_result["stderr"], exit_code=command_result["exit_code"],
                    error="Stopcommando eindigde, maar de service-healthcheck is nog bereikbaar.",
                    metadata={"healthcheck": health}, health="healthy",
                )
        else:
            if not managed_stopped:
                return self._finish_invocation(
                    call_id, plugin, tool, status="failed", started=started,
                    stdout=command_result["stdout"], stderr=command_result["stderr"], exit_code=command_result["exit_code"],
                    error="Stopcommando eindigde, maar zonder healthcheck of door HADES beheerd proces kan gestopte status niet worden bewezen.",
                )
            health = {"healthy": False, "detail": "Geen healthcheck geconfigureerd; het door HADES beheerde proces is aantoonbaar beëindigd."}
        clear_service_state(self.runtimes, plugin["id"])
        stdout, stderr = self._read_service_logs(plugin["id"])
        return self._finish_invocation(
            call_id, plugin, tool, status="completed", started=started,
            stdout=self._combined_output(command_result["stdout"], stdout), stderr=self._combined_output(command_result["stderr"], stderr),
            exit_code=command_result["exit_code"], metadata={"healthcheck": health}, health="stopped",
        )

    def invoke(
        self,
        plugin_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        timeout: int | None = None,
        *,
        invocation_type: str = "manual",
        approved_by_user: bool = False,
        approved_network: bool = False,
        approved_file_read: bool = False,
        approved_file_write: bool = False,
        approved_subprocess: bool = False,
        approvals: dict[str, bool] | None = None,
        privileged_policy_skip: bool = False,
    ) -> dict[str, Any]:
        if timeout is None:
            resolved = _setting("plugins.invoke_timeout_seconds", 120)
            timeout = None if resolved is None else int(resolved)
        plugin = self.db.get_plugin(plugin_id)
        if not plugin:
            raise KeyError(plugin_id)
        from plugin_runtime_v2 import eligible_for_manual, normalize_trust, trust_rank
        from runtime.execution_gateway import may_skip_tool_policies, normalize_invocation_type

        invocation_type = normalize_invocation_type(invocation_type)
        # Install/system may skip interactive trust only via trusted internal flag.
        skip_policies = may_skip_tool_policies(
            invocation_type=invocation_type,
            privileged_policy_skip=privileged_policy_skip,
        )
        structural = {"dependency_failed", "integrity_failed", "unsupported_runtime", "not_ready"}
        if plugin.get("failure_state") in structural:
            raise RuntimeError(f"Plugin heeft failure_state={plugin.get('failure_state')}; repair vereist.")
        if skip_policies:
            # Privileged install (e.g. MCP list_tools during convert) may run Ready-but-disabled.
            if plugin["status"] != "ready":
                raise RuntimeError("Plugin is niet Ready.")
        elif not plugin["enabled"] or plugin["status"] != "ready":
            raise RuntimeError("Plugin is niet Ready/enabled.")
        if not skip_policies and trust_rank(plugin.get("trust")) < trust_rank("manual"):
            raise RuntimeError(
                f"Plugin-trust '{normalize_trust(plugin.get('trust'))}' is te laag voor runs; schakel de plugin in of verhoog trust."
            )
        tool = next((item for item in self.db.plugin_tools(plugin_id) if item["name"] == tool_name and item["enabled"]), None)
        if not tool:
            raise KeyError(tool_name)
        # Global block/ask side-effect policies — block always wins (even privileged);
        # autonomous never promotes ask→allow. Must run before any subprocess spawn.
        # Per-kind flags are the only ask authority (F-03); approved_by_user is audit-only.
        from plugin_runtime_v2 import (
            build_capability_contract,
            evaluate_global_side_effect_policies,
            normalize_capability_approvals,
            required_policy_kinds,
        )

        contract = build_capability_contract(plugin, tool)
        grant_kinds = required_policy_kinds(contract) if skip_policies else None
        kind_approvals = normalize_capability_approvals(
            approvals,
            approved_network=approved_network,
            approved_file_read=approved_file_read,
            approved_file_write=approved_file_write,
            approved_subprocess=approved_subprocess,
            grant_kinds=grant_kinds,
        )
        side_effect_settings: dict[str, Any] = {}
        attached_settings = getattr(self, "_policy_settings", None)
        if isinstance(attached_settings, dict):
            side_effect_settings.update(attached_settings)
        if callable(getattr(self, "_policy_settings_provider", None)):
            try:
                provided_settings = self._policy_settings_provider()  # type: ignore[misc]
                if isinstance(provided_settings, dict):
                    side_effect_settings.update(provided_settings)
            except Exception:
                # Missing settings must not invent allow for unknown keys; defaults inside evaluator.
                pass
        side_effect_gate = evaluate_global_side_effect_policies(
            contract=contract,
            settings=side_effect_settings,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            approvals=kind_approvals,
        )
        if not side_effect_gate.get("allowed", False):
            call_id = self.db.create_tool_call(
                plugin_id,
                tool_name,
                input_data,
                invocation_type=invocation_type,
                approved_by_user=approved_by_user,
                metadata={"action": self._tool_action(tool), "side_effect_policy": side_effect_gate},
            )
            started = time.perf_counter()
            message = f"Policy blocked tool call: {side_effect_gate.get('reason')}"
            return self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="blocked",
                started=started,
                error=message,
                stderr=message,
                metadata={"side_effect_policy": side_effect_gate, "effect_applied": False},
            )
        # A09 / frontier — G11/G8 on every non-privileged invoke. Fail closed.
        if not skip_policies:
            from runtime.execution_gateway import PolicyModuleUnavailable, enforce_policies_fail_closed

            settings: dict[str, Any] = {}
            # Optional process-wide settings attached by the app (MCP lists, boundary mode).
            attached = getattr(self, "_policy_settings", None)
            if isinstance(attached, dict):
                settings.update(attached)
            tool_meta_probe = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
            is_mcp = bool(
                tool_meta_probe.get("mcp")
                or tool_meta_probe.get("mcp_remote")
                or tool_meta_probe.get("mcp_managed")
                or tool_meta_probe.get("mcp_tool")
                or str(tool_name).startswith("mcp.")
                or str(tool_name).startswith("mcp__")
                or "mcp" in str(plugin.get("plugin_type") or "").lower()
                or "mcp" in str(plugin.get("runtime_type") or "").lower()
            )
            if callable(getattr(self, "_policy_settings_provider", None)):
                try:
                    provided = self._policy_settings_provider()  # type: ignore[misc]
                    if isinstance(provided, dict):
                        settings.update(provided)
                except Exception as settings_exc:
                    # Fail closed for MCP tools — never pretend allowlists loaded.
                    if is_mcp:
                        call_id = self.db.create_tool_call(
                            plugin_id,
                            tool_name,
                            input_data,
                            invocation_type=invocation_type,
                            approved_by_user=approved_by_user,
                            metadata={"action": self._tool_action(tool), "policy_settings_error": str(settings_exc)},
                        )
                        started = time.perf_counter()
                        message = f"Policy settings provider failed (fail-closed): {settings_exc}"
                        return self._finish_invocation(
                            call_id,
                            plugin,
                            tool,
                            status="blocked",
                            started=started,
                            error=message,
                            stderr=message,
                            metadata={"policy_settings_error": str(settings_exc)},
                        )
            # Pull MCP lists from plugin capabilities / tool metadata when present.
            caps = plugin.get("capabilities") if isinstance(plugin.get("capabilities"), dict) else {}
            meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
            for key in ("mcp_allowed_tools", "mcp_denied_tools", "mcp_enabled", "allowed_tools", "denied_tools"):
                if key in caps:
                    settings[key] = caps[key]
                if key in meta:
                    settings[key] = meta[key]
            try:
                policy = enforce_policies_fail_closed(
                    tool_name=tool_name,
                    arguments=input_data,
                    settings=settings,
                    source=f"plugin_manager:{invocation_type}",
                    is_mcp_tool=is_mcp,
                )
            except PolicyModuleUnavailable as exc:
                call_id = self.db.create_tool_call(
                    plugin_id,
                    tool_name,
                    input_data,
                    invocation_type=invocation_type,
                    approved_by_user=approved_by_user,
                    metadata={"action": self._tool_action(tool), "policy_error": str(exc)},
                )
                started = time.perf_counter()
                message = f"Policy module unavailable (fail-closed): {exc}"
                return self._finish_invocation(
                    call_id,
                    plugin,
                    tool,
                    status="blocked",
                    started=started,
                    error=message,
                    stderr=message,
                    metadata={"policy_error": str(exc)},
                )
            if not policy.get("allowed"):
                call_id = self.db.create_tool_call(
                    plugin_id,
                    tool_name,
                    input_data,
                    invocation_type=invocation_type,
                    approved_by_user=approved_by_user,
                    metadata={"action": self._tool_action(tool), "policy": policy},
                )
                started = time.perf_counter()
                message = f"Policy blocked tool call: {policy.get('reason')}"
                return self._finish_invocation(
                    call_id,
                    plugin,
                    tool,
                    status="blocked",
                    started=started,
                    error=message,
                    stderr=message,
                    metadata={"policy": policy},
                )
            if isinstance(policy.get("args"), dict):
                input_data = policy["args"]
        call_id = self.db.create_tool_call(
            plugin_id,
            tool_name,
            input_data,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            metadata={"action": self._tool_action(tool)},
        )
        started = time.perf_counter()
        # WP6: record mutating intent before execution; classify unknown outcomes conservatively.
        effect_id: str | None = None
        effect_meta: dict[str, Any] = {}
        try:
            from runtime.tool_contracts import classify_tool_action, effect_class_for_tool

            tool_effect = classify_tool_action({**tool, "action": self._tool_action(tool)})
            effect_meta = tool_effect
            if tool_effect.get("mutating"):
                ledger = self.effect_ledger()
                rec = ledger.prepare(
                    tool=f"{plugin_id}:{tool_name}",
                    arguments=input_data if isinstance(input_data, dict) else {"input": input_data},
                    effect_class=effect_class_for_tool({**tool, "action": self._tool_action(tool)}),
                    task_id=None,
                    run_id=call_id,
                    detail={"invocation_type": invocation_type, "plugin_id": plugin_id},
                )
                effect_id = rec.effect_id
        except Exception as ledger_exc:
            # Ledger failure must not invent success; continue but mark metadata.
            effect_meta = {**effect_meta, "ledger_error": str(ledger_exc)}
        try:
            validated = self._validate_tool_input(tool.get("input_schema", {}), input_data)
            action = self._tool_action(tool)
            cache_lookup_key: str | None = None
            if not skip_policies:
                try:
                    from tool_result_cache import (
                        attach_cache_hit_metadata,
                        cache_key as tool_cache_key,
                        get_cached_result,
                        tool_invocation_cacheable,
                    )

                    if tool_invocation_cacheable(plugin, tool):
                        cache_lookup_key = tool_cache_key(plugin_id, tool_name, validated)
                        cached = get_cached_result(cache_lookup_key)
                        if cached:
                            finished = self._finish_invocation(
                                call_id,
                                plugin,
                                tool,
                                status=str(cached.get("status") or "completed"),
                                started=started,
                                stdout=str(cached.get("stdout") or cached.get("output") or ""),
                                stderr=str(cached.get("stderr") or ""),
                                exit_code=cached.get("exit_code"),
                                error=cached.get("error"),
                                metadata={
                                    "tool_result_cache": attach_cache_hit_metadata(cached).get("_tool_result_cache"),
                                    "effect_id": effect_id,
                                    **effect_meta,
                                },
                            )
                            self._ledger_finalize(effect_id, finished)
                            return attach_cache_hit_metadata(finished)
                except Exception:
                    cache_lookup_key = None
            try:
                from plugin_knowledge_index import knowledge_fast_path_result

                fast = knowledge_fast_path_result(self.db, plugin, tool, validated)
                if fast:
                    finished = self._finish_invocation(
                        call_id,
                        plugin,
                        tool,
                        status="completed",
                        started=started,
                        stdout=str(fast.get("output") or fast.get("stdout") or ""),
                        stderr=str(fast.get("stderr") or ""),
                        exit_code=0,
                        metadata={
                            "knowledge_fast_path": True,
                            "effect_id": effect_id,
                            **effect_meta,
                        },
                    )
                    self._ledger_finalize(effect_id, finished)
                    return finished
            except Exception:
                pass
            if self._envelope_gate is not None and not skip_policies:
                gate_result = self._envelope_gate(
                    plugin,
                    tool,
                    validated,
                    invocation_type=invocation_type,
                    approved_by_user=approved_by_user,
                )
                if isinstance(gate_result, dict) and not gate_result.get("ok", True):
                    message = "Gen2 envelope blocked: " + ", ".join(gate_result.get("violations") or ["denied"])
                    if effect_id:
                        try:
                            self.effect_ledger().mark_failed(
                                effect_id,
                                detail={
                                    "error": message,
                                    "effect_applied": False,
                                    "failure_stage": "before_execute",
                                },
                            )
                        except Exception:
                            pass
                    return self._finish_invocation(
                        call_id,
                        plugin,
                        tool,
                        status="blocked",
                        started=started,
                        error=message,
                        stderr=message,
                        metadata={"envelope": gate_result, "effect_id": effect_id, **effect_meta},
                    )
            command = self._command_argv(plugin, tool, validated) if tool.get("command") else None
            if action in {"start", "serve", "dev"} or tool.get("metadata", {}).get("mode") == "service":
                if not command:
                    raise ValueError("Start-tool heeft een subprocess-commando nodig.")
                with self._service_lock_for(plugin["id"]):
                    finished = self._start_service(plugin, tool, command, validated, call_id, started, timeout)
                self._ledger_finalize(effect_id, finished)
                return finished
            if action == "stop":
                with self._service_lock_for(plugin["id"]):
                    finished = self._stop_service(plugin, tool, command, call_id, started, timeout)
                self._ledger_finalize(effect_id, finished)
                return finished
            if action == "logs" and not command:
                stdout, stderr = self._read_service_logs(plugin_id)
                has_output = bool(str(stdout or "").strip() or str(stderr or "").strip())
                finished = self._finish_invocation(
                    call_id,
                    plugin,
                    tool,
                    status="completed" if has_output else "failed",
                    started=started,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=0 if has_output else 2,
                    error=None if has_output else "empty_service_logs",
                )
                self._ledger_finalize(effect_id, finished)
                return finished
            if action in {"health", "status"} and not command:
                healthcheck = self._explicit_healthcheck(plugin, tool)
                if not healthcheck:
                    raise ValueError(f"Tool '{tool_name}' heeft geen commando of expliciete healthcheck.")
                health = self._healthcheck(plugin, healthcheck, timeout=min(5.0, float(timeout)))
                finished = self._finish_invocation(
                    call_id, plugin, tool, status="completed" if health["healthy"] else "failed", started=started,
                    stdout=health.get("detail", ""), exit_code=0 if health["healthy"] else 1,
                    error=None if health["healthy"] else health.get("detail", "Healthcheck mislukt."),
                    metadata={"healthcheck": health, "effect_id": effect_id}, health="healthy" if health["healthy"] else "unhealthy",
                )
                self._ledger_finalize(effect_id, finished)
                return finished
            tool_meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
            if tool_meta.get("mcp_managed") and self._mcp_call_handler is not None:
                try:
                    try:
                        mcp_payload = self._mcp_call_handler(
                            plugin,
                            tool,
                            validated,
                            invocation_type=invocation_type,
                            approved_by_user=approved_by_user,
                        )
                    except TypeError:
                        # Backward-compatible handlers that only accept (plugin, tool, validated).
                        mcp_payload = self._mcp_call_handler(plugin, tool, validated)
                except Exception as mcp_exc:
                    finished = self._finish_invocation(
                        call_id,
                        plugin,
                        tool,
                        status="failed",
                        started=started,
                        error=str(mcp_exc),
                        stderr=str(mcp_exc),
                        exit_code=1,
                        metadata={"mcp_managed": True, "effect_id": effect_id, **effect_meta},
                    )
                    self._ledger_finalize(effect_id, finished)
                    return finished
                is_error = bool(isinstance(mcp_payload, dict) and mcp_payload.get("isError"))
                stdout_text = json.dumps(mcp_payload if isinstance(mcp_payload, dict) else {"result": mcp_payload}, ensure_ascii=False)
                finished = self._finish_invocation(
                    call_id,
                    plugin,
                    tool,
                    status="failed" if is_error else "completed",
                    started=started,
                    stdout=stdout_text,
                    stderr=str((mcp_payload or {}).get("stderr_tail") or "") if isinstance(mcp_payload, dict) else "",
                    exit_code=None if str(tool_meta.get("transport") or "").startswith("http") or (isinstance(mcp_payload, dict) and mcp_payload.get("transport") == "streamable_http") else (1 if is_error else 0),
                    error=str(mcp_payload.get("error") or "MCP tool error") if is_error and isinstance(mcp_payload, dict) else None,
                    metadata={
                        "mcp_managed": True,
                        "mcp": {
                            "isError": is_error,
                            "error_kind": (mcp_payload or {}).get("error_kind") if isinstance(mcp_payload, dict) else None,
                            "transport": (mcp_payload or {}).get("transport") if isinstance(mcp_payload, dict) else None,
                        },
                        "effect_id": effect_id,
                        **effect_meta,
                    },
                )
                self._ledger_finalize(effect_id, finished)
                return finished
            if not command:
                raise ValueError("Plugin-tool heeft geen uitvoerbaar commando.")
            result = self._run_command(command, root=self._plugin_workdir(plugin), env=self._command_environment(plugin, tool), timeout=timeout)
            health_state: str | None = None
            metadata: dict[str, Any] = {"argv_length": len(command), "effect_id": effect_id, **effect_meta}
            # MCP / structured bridges may return exit 0 with isError=true or ok=false in JSON stdout.
            stdout_text = str(result.get("stdout") or "")
            mcp_error = False
            mcp_payload: dict[str, Any] | None = None
            # Exit 0 with no stdout is not evidence of success for plugin tool runs.
            if action not in {"stop"} and int(result.get("exit_code") or 0) == 0 and not stdout_text.strip():
                mcp_error = True
                result["error"] = result.get("error") or "empty command stdout"
                result["exit_code"] = 1
            try:
                parsed_out = json.loads(stdout_text.strip() or "{}")
                if isinstance(parsed_out, dict):
                    mcp_payload = parsed_out
                    nested = parsed_out.get("result") if isinstance(parsed_out.get("result"), dict) else None
                    nested_dict = nested if isinstance(nested, dict) else {}
                    ok_false = parsed_out.get("ok") is False or nested_dict.get("ok") is False
                    is_error = (
                        parsed_out.get("isError") is True
                        or nested_dict.get("isError") is True
                        or bool(parsed_out.get("error"))
                        or bool(nested_dict.get("error"))
                        or ok_false
                    )
                    if is_error:
                        mcp_error = True
                        err_text = (
                            parsed_out.get("error")
                            or nested_dict.get("error")
                            or ("ok=false" if ok_false else "MCP tool returned isError=true")
                        )
                        result["error"] = result.get("error") or str(err_text)
                        if int(result.get("exit_code") or 0) == 0:
                            result["exit_code"] = 1
                    metadata["mcp"] = {
                        "isError": bool(parsed_out.get("isError") or nested_dict.get("isError") or ok_false),
                        "ok": parsed_out.get("ok", nested_dict.get("ok")),
                        "protocol_version": parsed_out.get("protocol_version"),
                        "has_structuredContent": "structuredContent" in (parsed_out.get("result") or parsed_out),
                    }
            except Exception:
                mcp_payload = None
            explicit_health = self._explicit_healthcheck(plugin, tool)
            if action in {"health", "status"} and result["exit_code"] == 0 and not mcp_error:
                if explicit_health:
                    health = self._healthcheck(plugin, explicit_health, timeout=min(5.0, float(timeout)))
                    metadata["healthcheck"] = health
                    if not health["healthy"]:
                        result["error"] = health.get("detail", "Healthcheck mislukt.")
                        result["exit_code"] = 1
                    health_state = "healthy" if health["healthy"] else "unhealthy"
                else:
                    # A successful status command is operational evidence, not an
                    # independently verified service-health proof.
                    health_state = "operational"
            elif result["exit_code"] == 0 and not mcp_error and plugin.get("health") in {"unknown", "prepared"}:
                health_state = "operational"
            final_status = "completed" if int(result.get("exit_code") or 0) == 0 and not mcp_error else "failed"
            fields = self._invocation_fields_from_command_result(result)
            extra_meta = dict(fields.pop("metadata", None) or {})
            if extra_meta:
                metadata = {**metadata, **extra_meta}
            finished = self._finish_invocation(
                call_id, plugin, tool, status=final_status,
                started=started, metadata=metadata, health=health_state, **fields,
            )
            if mcp_payload and self._artifact_hook:
                try:
                    self._artifact_hook(finished, mcp_payload)
                except Exception:
                    pass
            self._ledger_finalize(effect_id, finished)
            if cache_lookup_key and final_status == "completed":
                try:
                    from tool_result_cache import store_cached_result

                    store_cached_result(cache_lookup_key, finished)
                except Exception:
                    pass
            return finished
        except Exception as exc:
            if effect_id:
                try:
                    # Unknown whether side effect applied once execution may have started.
                    self.effect_ledger().mark_failed(
                        effect_id,
                        detail={
                            "error": str(exc),
                            "failure_stage": "unknown",
                            "effect_applied": None,
                        },
                    )
                    decision = self.effect_ledger().classify_on_restart(effect_id)
                except Exception:
                    decision = {"class": "UNKNOWN_EXTERNAL_STATE"}
            else:
                decision = None
            finished = self._finish_invocation(
                call_id,
                plugin,
                tool,
                status="failed",
                started=started,
                stderr=str(exc),
                error=str(exc),
                metadata={"effect_id": effect_id, "restart_class": decision, **effect_meta},
            )
            return finished

    def _ledger_finalize(self, effect_id: str | None, finished: dict[str, Any] | None) -> None:
        if not effect_id:
            return
        try:
            ledger = self.effect_ledger()
            status = str((finished or {}).get("status") or "").lower()
            if status in {"completed", "ok", "success"}:
                ledger.mark_committed(effect_id, detail={"status": status})
            elif status in {"blocked"}:
                ledger.mark_failed(
                    effect_id,
                    detail={"error": (finished or {}).get("error"), "effect_applied": False, "failure_stage": "before_execute"},
                )
            elif status in {"failed", "error"}:
                # Conservatively unknown unless metadata proves otherwise.
                ledger.mark_failed(
                    effect_id,
                    detail={
                        "error": (finished or {}).get("error"),
                        "failure_stage": "after_possible_effect",
                        "effect_applied": True,
                    },
                )
            else:
                ledger.mark_unknown(effect_id, detail={"status": status})
        except Exception as exc:
            # Never leave a committed-looking effect unmarked after side effects.
            _LOG.exception("effect ledger finalize failed for %s: %s", effect_id, exc)
            try:
                self.effect_ledger().mark_unknown(
                    effect_id,
                    detail={"finalize_error": str(exc), "status": str((finished or {}).get("status") or "")},
                )
            except Exception as nested:
                _LOG.exception("effect ledger mark_unknown also failed for %s: %s", effect_id, nested)

    def restart_effect_decision(self, effect_id: str) -> dict[str, Any]:
        """Expose ledger classification for resume/UI — no blind double mutation."""
        decision = self.effect_ledger().classify_on_restart(effect_id)
        decision["blind_retry_allowed"] = decision.get("class") == "SAFE_TO_RETRY"
        decision["human_review_required"] = decision.get("class") in {
            "REQUIRES_RECONCILIATION",
            "UNKNOWN_EXTERNAL_STATE",
        }
        return decision
