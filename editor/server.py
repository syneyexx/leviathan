#!/usr/bin/env python3
"""LEVIATHAN STUDIO — local editor API + Vite launcher.

Security model (local admin tool):
- Bound to 127.0.0.1
- Mutating requests require session token issued by GET /api/session
- Origin/Host allow-list (Vite + API)
- Body size limits before full read
- Atomic temp-file replace + journal for multi-file saves
- No global source-string replace endpoint for visual edits
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
FRONTEND = REPO / "Data" / "frontend"
STYLES = FRONTEND / "src" / "styles"
PUBLIC = FRONTEND / "public"
ASSETS = PUBLIC / "assets"
UPLOADS = ASSETS / "uploads"
CONTENT_FILE = PUBLIC / "lv-editor-content.json"
META_FILE = PUBLIC / "lv-editor-meta.json"
JOURNAL_DIR = ROOT / ".studio-journal"
CHECKPOINT_DIR = ROOT / ".studio-checkpoints"
AI_TEMP_DIR = ROOT / ".studio-ai-temp"
SRC_ROOT = FRONTEND / "src"
HOST = "127.0.0.1"
PORT = 5199
VITE_PORT = 5173
MAX_BODY = 2_000_000
MAX_UPLOAD = 12_000_000
# AI context may include bounded snapshots; still far below unchecked DoS sizes.
MAX_AI_BODY = 6_000_000
_AI_IMPORT_ERROR: str | None = None
_get_ai_gateway = None

ALLOWED_FILES = {
    "tokens.css": STYLES / "tokens.css",
    "leviathan.css": STYLES / "leviathan.css",
    "pages.css": STYLES / "pages.css",
    "chat.css": STYLES / "chat.css",
}

SAFE_NAME = re.compile(r"^[a-z0-9._-]+$", re.I)
SAFE_UPLOAD = re.compile(r"^[a-zA-Z0-9._-]+$")
ALLOWED_ORIGINS = {
    f"http://{HOST}:{VITE_PORT}",
    f"http://127.0.0.1:{VITE_PORT}",
    f"http://localhost:{VITE_PORT}",
    f"http://{HOST}:{PORT}",
    f"http://127.0.0.1:{PORT}",
    f"http://localhost:{PORT}",
}

vite_proc: subprocess.Popen | None = None
SESSION_TOKEN = secrets.token_urlsafe(32)
WRITE_LOCK = threading.RLock()
_doc_meta: dict = {"revision": 0, "hash": ""}
SCHEMA_VERSION = 3
# Threading lock is not inter-process. One API process per project directory.
PROCESS_LOCK_FILE = ROOT / ".studio-process.lock"
_process_lock_fd: int | None = None

# Durability note (honest): journal + per-file os.replace is NOT a single
# filesystem transaction. Crash between file writes can leave a journal that
# startup recovery rolls back to the pre-txn snapshot.


def default_content() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "revision": 0,
        "entries": {},
        "nodes": [],
        "components": [],
        "meta": {"ambiguous": []},
        "docId": uuid.uuid4().hex[:12],
    }


def load_meta() -> dict:
    global _doc_meta
    if META_FILE.is_file():
        try:
            data = json.loads(META_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _doc_meta = {
                    "revision": int(data.get("revision") or 0),
                    "hash": str(data.get("hash") or ""),
                }
                return _doc_meta
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    _doc_meta = {"revision": 0, "hash": ""}
    return _doc_meta


def save_meta(meta: dict) -> None:
    global _doc_meta
    _doc_meta = {"revision": int(meta.get("revision") or 0), "hash": str(meta.get("hash") or "")}
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(META_FILE, json.dumps(_doc_meta, ensure_ascii=False, indent=2) + "\n")


def content_hash(content: dict, files: dict | None = None) -> str:
    payload = json.dumps(
        {
            "entries": content.get("entries") or {},
            "nodes": content.get("nodes") or [],
            "components": content.get("components") or [],
            "files": files or {},
            "revision": content.get("revision") or 0,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_content() -> dict:
    if not CONTENT_FILE.is_file():
        return default_content()
    try:
        raw = CONTENT_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Never silently replace with empty — restore checkpoint if possible
        backup = CHECKPOINT_DIR / "last-good.json"
        if backup.is_file():
            try:
                data = json.loads(backup.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("meta", {})
                    data["meta"]["recoveredFromCorrupt"] = True
                    return normalize_content(data)
            except (json.JSONDecodeError, OSError):
                pass
        raise ValueError(f"Corrupt content JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Corrupt content JSON: root must be object")
    return normalize_content(data)


def normalize_content(data: dict, *, allow_migrate: bool = True) -> dict:
    """Validate and normalize a content document.

    Future schema versions are rejected — never silently coerced to v3.
    """
    if not isinstance(data, dict):
        raise ValueError("content root must be an object")
    data = dict(data)
    version = data.get("version", SCHEMA_VERSION)
    try:
        version_i = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError("schema version must be an integer") from exc
    if version_i > SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema version {version_i} (max {SCHEMA_VERSION})")
    if version_i < 1:
        raise ValueError("schema version out of range")
    if version_i < SCHEMA_VERSION and not allow_migrate:
        raise ValueError(f"Schema version {version_i} requires explicit migration")
    data["version"] = SCHEMA_VERSION if allow_migrate and version_i <= SCHEMA_VERSION else version_i
    data.setdefault("entries", {})
    data.setdefault("nodes", [])
    data.setdefault("components", [])
    data.setdefault("meta", {"ambiguous": []})
    data.setdefault("revision", load_meta().get("revision", 0))
    data.setdefault("docId", uuid.uuid4().hex[:12])
    if not isinstance(data["entries"], dict):
        raise ValueError("entries must be an object")
    if not isinstance(data["nodes"], list):
        raise ValueError("nodes must be a list")
    if not isinstance(data["components"], list):
        raise ValueError("components must be a list")
    if not isinstance(data["meta"], dict):
        raise ValueError("meta must be an object")
    return data


def read_persisted_files() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, path in ALLOWED_FILES.items():
        out[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return out


def canonical_persisted_hash(content: dict | None = None, files: dict[str, str] | None = None) -> str:
    """Server-owned concurrency hash over the complete persisted state.

    Clients must never substitute a non-equivalent algorithm (e.g. browser FNV
    helpers) for this token.
    """
    doc = content if content is not None else (read_content() if CONTENT_FILE.is_file() else default_content())
    file_map = files if files is not None else read_persisted_files()
    return content_hash(doc, file_map)


def validate_revision_precondition(base_rev, base_hash, meta: dict) -> tuple[bool, dict]:
    """Return (ok, conflict_payload). Call only while holding WRITE_LOCK."""
    try:
        if base_rev is not None:
            base_rev_i = int(base_rev)
            if base_rev_i < 0:
                return False, {"error": "baseRevision out of range", "revision": meta["revision"], "hash": meta["hash"]}
            if base_rev_i != int(meta["revision"]):
                return False, {"error": "conflict", "revision": meta["revision"], "hash": meta["hash"]}
    except (TypeError, ValueError):
        return False, {"error": "baseRevision must be an integer", "revision": meta["revision"], "hash": meta["hash"]}

    # Detect external disk drift vs sidecar meta before trusting the token
    try:
        disk_hash = canonical_persisted_hash()
    except ValueError:
        disk_hash = ""
    if meta.get("hash") and disk_hash and meta["hash"] != disk_hash:
        return False, {
            "error": "conflict",
            "reason": "external-disk-change",
            "revision": meta["revision"],
            "hash": disk_hash,
        }

    if base_hash not in (None, ""):
        if meta.get("hash") and str(base_hash) != str(meta["hash"]):
            return False, {"error": "conflict", "revision": meta["revision"], "hash": meta["hash"]}
        if disk_hash and str(base_hash) != str(disk_hash):
            return False, {"error": "conflict", "revision": meta["revision"], "hash": disk_hash}
    return True, {}


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_content(data: dict) -> None:
    CONTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(CONTENT_FILE, text)
    # Keep last-good checkpoint
    atomic_write_text(CHECKPOINT_DIR / "last-good.json", text)


def sanitize_svg(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SVG must be UTF-8") from exc
    # Strip scripts / handlers / javascript URLs
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text, flags=re.I)
    text = re.sub(r"(href|xlink:href)\s*=\s*([\"'])\s*javascript:[\s\S]*?\2", r'\1=#', text, flags=re.I)
    text = re.sub(r"<(foreignObject)[\s\S]*?</\1>", "", text, flags=re.I)
    return text.encode("utf-8")


def validate_image_bytes(ext: str, raw: bytes) -> bytes:
    if ext == ".svg":
        return sanitize_svg(raw)
    # Basic magic-byte checks for raster formats
    if ext in {".png"} and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG")
    if ext in {".jpg", ".jpeg"} and not raw.startswith(b"\xff\xd8"):
        raise ValueError("Invalid JPEG")
    if ext == ".gif" and not (raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a")):
        raise ValueError("Invalid GIF")
    if ext == ".webp" and not (raw[0:4] == b"RIFF" and raw[8:12] == b"WEBP"):
        raise ValueError("Invalid WEBP")
    if ext == ".ico" and len(raw) < 6:
        raise ValueError("Invalid ICO")
    return raw


def _ensure_ai_gateway_import() -> None:
    global _get_ai_gateway, _AI_IMPORT_ERROR
    if _get_ai_gateway is not None or _AI_IMPORT_ERROR:
        return
    try:
        import sys

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from ai.gateway import get_gateway as _gw

        _get_ai_gateway = _gw
    except Exception as exc:  # pragma: no cover
        _AI_IMPORT_ERROR = str(exc)


def ai_gateway():
    _ensure_ai_gateway_import()
    if _get_ai_gateway is None:
        raise RuntimeError(_AI_IMPORT_ERROR or "AI gateway unavailable")
    return _get_ai_gateway(AI_TEMP_DIR, validate_image=validate_image_bytes)


def journal_begin(
    txn_id: str,
    files: dict[str, str],
    content: dict | None,
    *,
    meta_before: dict | None = None,
) -> Path:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": txn_id,
        "started": time.time(),
        "files": {},
        "content": None,
        "contentExisted": CONTENT_FILE.is_file(),
        "meta": {"previous": dict(meta_before or load_meta())},
    }
    for name, text in files.items():
        path = ALLOWED_FILES[name]
        existed = path.is_file()
        prev = path.read_text(encoding="utf-8") if existed else None
        entry["files"][name] = {"previous": prev, "existed": existed, "next": text}
    if content is not None:
        if CONTENT_FILE.is_file():
            prev_c = read_content()
            entry["content"] = {"previous": prev_c, "existed": True, "next": content}
        else:
            entry["content"] = {"previous": None, "existed": False, "next": content}
    path = JOURNAL_DIR / f"{txn_id}.json"
    atomic_write_text(path, json.dumps(entry, ensure_ascii=False))
    return path


def journal_commit(txn_id: str) -> None:
    path = JOURNAL_DIR / f"{txn_id}.json"
    if path.is_file():
        path.unlink()


def journal_rollback(txn_id: str) -> None:
    path = JOURNAL_DIR / f"{txn_id}.json"
    if not path.is_file():
        return
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for name, pair in (entry.get("files") or {}).items():
        if name not in ALLOWED_FILES:
            continue
        target = ALLOWED_FILES[name]
        if pair.get("existed") is False or pair.get("previous") is None:
            # Absent prior file must not be restored as an invented empty file
            if target.is_file():
                target.unlink()
        else:
            atomic_write_text(target, pair.get("previous") or "")
    content_pair = entry.get("content")
    if content_pair:
        if content_pair.get("existed") is False or content_pair.get("previous") is None:
            if CONTENT_FILE.is_file():
                CONTENT_FILE.unlink()
        else:
            write_content(content_pair["previous"])
    meta_prev = (entry.get("meta") or {}).get("previous")
    if isinstance(meta_prev, dict):
        save_meta(meta_prev)
    path.unlink(missing_ok=True)


def recover_pending_journals() -> list[str]:
    """Deterministic startup policy: roll back any incomplete journal before accepting writes."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    recovered: list[str] = []
    for path in sorted(JOURNAL_DIR.glob("*.json")):
        txn_id = path.stem
        journal_rollback(txn_id)
        recovered.append(txn_id)
    return recovered


def acquire_process_lock() -> None:
    """Best-effort single-process guard for one project directory (not a substitute for FS transactions)."""
    global _process_lock_fd
    PROCESS_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(PROCESS_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if os.name == "nt":
            # Windows: advisory via exclusive create of a sidecar lock body
            pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _process_lock_fd = fd
    except OSError as exc:
        os.close(fd)
        raise SystemExit(
            "[studio] Another editor API process already holds this project. "
            "Two processes against one project are unsupported."
        ) from exc


class Handler(BaseHTTPRequestHandler):
    server_version = "LeviathanStudio/4.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[studio] {self.address_string()} - {fmt % args}", flush=True)

    def _cors_headers(self) -> dict[str, str]:
        origin = self.headers.get("Origin") or ""
        allow = origin if origin in ALLOWED_ORIGINS else f"http://{HOST}:{VITE_PORT}"
        return {
            "Access-Control-Allow-Origin": allow,
            "Access-Control-Allow-Methods": "GET, PUT, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-LVB-Session",
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            # non-CORS same-host tools (curl) — require Host match
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in {"127.0.0.1", "localhost", HOST}
        return origin in ALLOWED_ORIGINS

    def _require_session(self) -> bool:
        token = self.headers.get("X-LVB-Session") or ""
        return secrets.compare_digest(token, SESSION_TOKEN)

    def _read_body(self, limit: int = MAX_BODY) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0:
            return None
        if length > limit:
            return None
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_json(self, limit: int = MAX_BODY) -> dict | None:
        raw = self._read_body(limit)
        if raw is None:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _resolve_static(self, path: str) -> Path | None:
        if path in ("", "/"):
            return ROOT / "index.html"
        rel = path.lstrip("/")
        if ".." in rel.split("/"):
            return None
        if rel.startswith("styles/"):
            name = rel[len("styles/") :]
            if name in ALLOWED_FILES:
                return ALLOWED_FILES[name]
            return None
        if rel.startswith("assets/"):
            candidate = PUBLIC / rel
            if candidate.is_file() and PUBLIC in candidate.resolve().parents:
                return candidate
            return None
        candidate = ROOT / rel
        if candidate.is_file() and ROOT in candidate.resolve().parents:
            return candidate
        return None

    def do_OPTIONS(self) -> None:
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            meta = load_meta()
            self._json(
                200,
                {
                    "ok": True,
                    "styles": str(STYLES),
                    "content": str(CONTENT_FILE),
                    "repo": str(REPO),
                    "vite": f"http://{HOST}:{VITE_PORT}/",
                    "revision": meta["revision"],
                    "hash": meta["hash"],
                },
            )
            return

        if path == "/api/editor-ai/capabilities":
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            try:
                report = ai_gateway().capabilities()
            except Exception as exc:
                self._json(
                    200,
                    {
                        "available": False,
                        "aiEnabled": False,
                        "capabilities": {},
                        "providers": [],
                        "error": str(exc),
                        "unavailable": True,
                        "reason": "gateway-import-failed",
                    },
                )
                return
            self._json(200, report)
            return

        if path.startswith("/api/editor-ai/preview/"):
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            asset_id = path[len("/api/editor-ai/preview/") :].strip("/")
            if "/" in asset_id or ".." in asset_id:
                self._json(400, {"error": "Invalid preview id"})
                return
            try:
                got = ai_gateway().get_preview_bytes(asset_id)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            if not got:
                self._json(404, {"error": "Preview not found or expired"})
                return
            raw, record = got
            mime = record.get("mime") or "application/octet-stream"
            self._send(200, raw, mime)
            return

        if path == "/api/session":
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            self._json(
                200,
                {
                    "token": SESSION_TOKEN,
                    "expires": None,
                    "vite": f"http://{HOST}:{VITE_PORT}/",
                },
            )
            return

        if path == "/api/files":
            files = []
            for name, file_path in ALLOWED_FILES.items():
                files.append(
                    {
                        "name": name,
                        "exists": file_path.is_file(),
                        "bytes": file_path.stat().st_size if file_path.is_file() else 0,
                    }
                )
            self._json(200, {"files": files, "stylesDir": str(STYLES)})
            return

        if path == "/api/file":
            qs = parse_qs(parsed.query)
            name = (qs.get("name") or [""])[0]
            if name not in ALLOWED_FILES:
                self._json(400, {"error": "Unknown file"})
                return
            file_path = ALLOWED_FILES[name]
            if not file_path.is_file():
                self._json(404, {"error": "File not found"})
                return
            text = file_path.read_text(encoding="utf-8")
            self._json(200, {"name": name, "content": text, "path": str(file_path)})
            return

        if path == "/api/content":
            try:
                data = read_content()
            except ValueError as exc:
                self._json(500, {"error": str(exc), "hint": "Herstel vanaf .studio-checkpoints/last-good.json"})
                return
            meta = load_meta()
            try:
                h = meta["hash"] or canonical_persisted_hash(data)
            except ValueError:
                h = meta["hash"] or ""
            self._json(
                200,
                {
                    "content": data,
                    "path": str(CONTENT_FILE),
                    "revision": meta["revision"],
                    "hash": h,
                },
            )
            return

        if path == "/api/assets":
            exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"}
            assets = []
            roots = [
                (ASSETS, "/assets"),
                (UPLOADS, "/assets/uploads"),
            ]
            for folder, url_prefix in roots:
                if not folder.is_dir():
                    continue
                for file_path in sorted(folder.iterdir()):
                    if not file_path.is_file():
                        continue
                    if file_path.suffix.lower() not in exts:
                        continue
                    assets.append(
                        {
                            "name": file_path.name,
                            "url": f"{url_prefix}/{file_path.name}",
                            "bytes": file_path.stat().st_size,
                            "mtime": int(file_path.stat().st_mtime),
                            "ext": file_path.suffix.lower().lstrip("."),
                        }
                    )
            self._json(200, {"assets": assets, "count": len(assets)})
            return

        target = self._resolve_static(path)
        if target is None or not target.is_file():
            self._json(404, {"error": "Not found", "path": path})
            return

        data = target.read_bytes()
        mime, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif target.suffix in {".js", ".mjs"}:
            mime = "text/javascript; charset=utf-8"
        elif target.suffix == ".html":
            mime = "text/html; charset=utf-8"
        elif not mime:
            mime = "application/octet-stream"
        self._send(200, data, mime)

    def do_PUT(self) -> None:
        if not self._origin_ok():
            self._json(403, {"error": "Origin niet toegestaan"})
            return
        if not self._require_session():
            self._json(401, {"error": "Sessie vereist"})
            return

        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_BODY:
            self._json(413, {"error": "Body te groot"})
            return

        if parsed.path == "/api/file":
            qs = parse_qs(parsed.query)
            name = (qs.get("name") or [""])[0]
            if name not in ALLOWED_FILES or not SAFE_NAME.match(name):
                self._json(400, {"error": "Unknown file"})
                return
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body with content"})
                return
            content_text = payload.get("content")
            if not isinstance(content_text, str):
                self._json(400, {"error": "content must be a string"})
                return
            if len(content_text) > MAX_BODY:
                self._json(400, {"error": "File too large"})
                return
            # Same revision contract as /api/save — no silent bypass
            base_rev = payload.get("baseRevision")
            base_hash = payload.get("baseHash")
            if base_rev is None or base_hash in (None, ""):
                self._json(
                    400,
                    {
                        "error": "baseRevision and baseHash required",
                        "notes": "PUT /api/file follows the transactional revision contract; prefer POST /api/save for multi-file writes.",
                    },
                )
                return

            txn_id = uuid.uuid4().hex
            with WRITE_LOCK:
                meta = load_meta()
                ok, conflict = validate_revision_precondition(base_rev, base_hash, meta)
                if not ok:
                    code = 409 if conflict.get("error") == "conflict" else 400
                    self._json(code, conflict)
                    return
                try:
                    journal_begin(txn_id, {name: content_text}, None, meta_before=meta)
                    atomic_write_text(ALLOWED_FILES[name], content_text)
                    new_rev = int(meta["revision"]) + 1
                    files_now = read_persisted_files()
                    files_now[name] = content_text
                    doc = read_content() if CONTENT_FILE.is_file() else default_content()
                    doc["revision"] = new_rev
                    h = content_hash(doc, files_now)
                    save_meta({"revision": new_rev, "hash": h})
                    journal_commit(txn_id)
                except Exception as exc:
                    journal_rollback(txn_id)
                    self._json(500, {"error": f"File write mislukt: {exc}"})
                    return

            self._json(
                200,
                {
                    "ok": True,
                    "name": name,
                    "bytes": len(content_text.encode("utf-8")),
                    "path": str(ALLOWED_FILES[name]),
                    "revision": new_rev,
                    "hash": h,
                },
            )
            return

        if parsed.path == "/api/content":
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            content = payload.get("content")
            if not isinstance(content, dict):
                self._json(400, {"error": "content must be an object"})
                return
            try:
                content = normalize_content(content)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            base_rev = payload.get("baseRevision")
            base_hash = payload.get("baseHash")
            if base_rev is None:
                self._json(400, {"error": "baseRevision required"})
                return

            txn_id = uuid.uuid4().hex
            with WRITE_LOCK:
                meta = load_meta()
                ok, conflict = validate_revision_precondition(base_rev, base_hash, meta)
                if not ok:
                    code = 409 if conflict.get("error") == "conflict" else 400
                    self._json(code, conflict)
                    return
                try:
                    journal_begin(txn_id, {}, content, meta_before=meta)
                    new_rev = int(meta["revision"]) + 1
                    content["revision"] = new_rev
                    files_now = read_persisted_files()
                    h = content_hash(content, files_now)
                    write_content(content)
                    save_meta({"revision": new_rev, "hash": h})
                    journal_commit(txn_id)
                except Exception as exc:
                    journal_rollback(txn_id)
                    self._json(500, {"error": f"Content write mislukt: {exc}"})
                    return

            self._json(
                200,
                {
                    "ok": True,
                    "path": str(CONTENT_FILE),
                    "entries": len(content["entries"]),
                    "nodes": len(content["nodes"]),
                    "revision": new_rev,
                    "hash": h,
                },
            )
            return

        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        # OmniRoute Editor Gateway — generation does not mutate document content
        if parsed.path == "/api/editor-ai" or parsed.path == "/api/editor-ai/generate":
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            if not self._require_session():
                self._json(401, {"error": "Sessie vereist"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > MAX_AI_BODY:
                self._json(413, {"error": "Body te groot"})
                return
            payload = self._read_json(limit=MAX_AI_BODY)
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            # Snapshot of content hash before — generation must not write content
            meta_before = dict(load_meta())
            content_mtime_before = CONTENT_FILE.stat().st_mtime if CONTENT_FILE.is_file() else None
            try:
                status, body = ai_gateway().handle(payload)
            except Exception as exc:
                self._json(
                    501,
                    {
                        "error": "AI gateway unavailable",
                        "notes": str(exc),
                        "unavailable": True,
                        "reason": "gateway-error",
                    },
                )
                return
            meta_after = load_meta()
            content_mtime_after = CONTENT_FILE.stat().st_mtime if CONTENT_FILE.is_file() else None
            if meta_before != meta_after or content_mtime_before != content_mtime_after:
                # Hard invariant — generation must never persist document mutations
                self._json(
                    500,
                    {
                        "error": "AI generation mutated document state — aborted",
                        "unavailable": True,
                        "reason": "invariant-violation",
                    },
                )
                return
            # Legacy probe compatibility fields
            if status == 501 and isinstance(body, dict):
                body.setdefault("unavailable", True)
                err = (body.get("error") or {}) if isinstance(body.get("error"), dict) else {}
                body.setdefault("reason", err.get("code") or "no-provider")
            self._json(status, body)
            return

        if parsed.path == "/api/editor-ai/cancel":
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            if not self._require_session():
                self._json(401, {"error": "Sessie vereist"})
                return
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            request_id = payload.get("requestId")
            if not isinstance(request_id, str) or not request_id.strip():
                self._json(400, {"error": "requestId required"})
                return
            try:
                self._json(200, ai_gateway().cancel(request_id.strip()))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if parsed.path == "/api/editor-ai/preview/cleanup":
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            if not self._require_session():
                self._json(401, {"error": "Sessie vereist"})
                return
            payload = self._read_json() or {}
            try:
                self._json(
                    200,
                    ai_gateway().cleanup_preview(
                        request_id=payload.get("requestId") if isinstance(payload.get("requestId"), str) else None,
                        asset_id=payload.get("assetId") if isinstance(payload.get("assetId"), str) else None,
                    ),
                )
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if parsed.path == "/api/editor-ai/accept-asset":
            # Promote temp preview bytes into permanent uploads (still no document mutation)
            if not self._origin_ok():
                self._json(403, {"error": "Origin niet toegestaan"})
                return
            if not self._require_session():
                self._json(401, {"error": "Sessie vereist"})
                return
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            asset_id = payload.get("tempId") or payload.get("assetId")
            if not isinstance(asset_id, str) or not asset_id.strip():
                self._json(400, {"error": "tempId required"})
                return
            try:
                promoted = ai_gateway().accept_to_upload_bytes(asset_id.strip())
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            if not promoted:
                self._json(404, {"error": "Preview asset not found or expired"})
                return
            raw, ext, mime = promoted
            try:
                raw = validate_image_bytes(ext, raw)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            if len(raw) > MAX_UPLOAD:
                self._json(400, {"error": "Image too large (max 12MB)"})
                return
            UPLOADS.mkdir(parents=True, exist_ok=True)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            # Never store secrets; keep bounded generation provenance
            safe_meta = {
                k: meta[k]
                for k in (
                    "origin",
                    "requestId",
                    "task",
                    "provider",
                    "model",
                    "requestedWidth",
                    "requestedHeight",
                    "actualWidth",
                    "actualHeight",
                    "sourcePage",
                    "targetNode",
                    "isMock",
                )
                if k in meta and isinstance(meta[k], (str, int, float, bool))
            }
            safe_meta.setdefault("origin", "ai-generated")
            out_name = f"ai-{uuid.uuid4().hex[:10]}{ext}"
            out_path = UPLOADS / out_name
            atomic_write_bytes(out_path, raw)
            # Sidecar metadata (optional, non-secret)
            if safe_meta:
                atomic_write_text(
                    out_path.with_suffix(out_path.suffix + ".meta.json"),
                    json.dumps({**safe_meta, "mime": mime, "bytes": len(raw), "hash": hashlib.sha256(raw).hexdigest()}, ensure_ascii=False, indent=2)
                    + "\n",
                )
            # Cleanup temp after successful promote
            try:
                ai_gateway().cleanup_preview(asset_id=asset_id.strip())
            except Exception:
                pass
            self._json(
                200,
                {
                    "ok": True,
                    "url": f"/assets/uploads/{out_name}",
                    "path": str(out_path),
                    "bytes": len(raw),
                    "mime": mime,
                    "meta": safe_meta,
                },
            )
            return

        if not self._origin_ok():
            self._json(403, {"error": "Origin niet toegestaan"})
            return
        if not self._require_session():
            self._json(401, {"error": "Sessie vereist"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > max(MAX_BODY, MAX_UPLOAD):
            self._json(413, {"error": "Body te groot"})
            return

        if parsed.path == "/api/replace-text":
            # Explicitly disabled — visual text lives in content entries
            self._json(
                410,
                {
                    "error": "Bronvervanging uitgeschakeld",
                    "notes": "Tekstwijzigingen worden per stabiele node in lv-editor-content.json bewaard.",
                },
            )
            return

        if parsed.path == "/api/save":
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            content = payload.get("content")
            files = payload.get("files") or {}
            if content is not None and not isinstance(content, dict):
                self._json(400, {"error": "content must be an object"})
                return
            if not isinstance(files, dict):
                self._json(400, {"error": "files must be an object"})
                return
            for name, text in files.items():
                if name not in ALLOWED_FILES or not SAFE_NAME.match(name):
                    self._json(400, {"error": f"Unknown file: {name}"})
                    return
                if not isinstance(text, str) or len(text) > MAX_BODY:
                    self._json(400, {"error": f"Invalid file body: {name}"})
                    return
            if content is not None:
                try:
                    content = normalize_content(content)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return

            base_rev = payload.get("baseRevision")
            base_hash = payload.get("baseHash")
            if base_rev is None:
                self._json(400, {"error": "baseRevision required"})
                return

            txn_id = uuid.uuid4().hex
            with WRITE_LOCK:
                meta = load_meta()
                ok, conflict = validate_revision_precondition(base_rev, base_hash, meta)
                if not ok:
                    code = 409 if conflict.get("error") == "conflict" else 400
                    self._json(code, conflict)
                    return
                try:
                    journal_begin(txn_id, files, content, meta_before=meta)
                    for name, text in files.items():
                        atomic_write_text(ALLOWED_FILES[name], text)
                    new_rev = int(meta["revision"]) + 1
                    files_now = read_persisted_files()
                    for name, text in files.items():
                        files_now[name] = text
                    if content is not None:
                        content["revision"] = new_rev
                        write_content(content)
                        h = content_hash(content, files_now)
                    else:
                        doc = read_content() if CONTENT_FILE.is_file() else default_content()
                        doc["revision"] = new_rev
                        h = content_hash(doc, files_now)
                    save_meta({"revision": new_rev, "hash": h})
                    journal_commit(txn_id)
                except Exception as exc:
                    journal_rollback(txn_id)
                    self._json(500, {"error": f"Save mislukt: {exc}"})
                    return

            self._json(
                200,
                {
                    "ok": True,
                    "revision": new_rev,
                    "hash": h,
                    "files": list(files.keys()),
                    "wroteContent": content is not None,
                },
            )
            return

        if parsed.path == "/api/upload":
            payload = self._read_json(limit=MAX_UPLOAD + 100_000)
            if payload is None:
                self._json(400, {"error": "Expected JSON body or body too large"})
                return
            filename = payload.get("filename") or "upload.bin"
            data_b64 = payload.get("data")
            if not isinstance(filename, str) or not isinstance(data_b64, str):
                self._json(400, {"error": "filename and data required"})
                return
            filename = Path(filename).name
            if not SAFE_UPLOAD.match(filename):
                self._json(400, {"error": "Invalid filename"})
                return
            ext = Path(filename).suffix.lower() or ".bin"
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"}:
                self._json(400, {"error": "Unsupported image type"})
                return
            if "," in data_b64 and data_b64.strip().startswith("data:"):
                data_b64 = data_b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(data_b64, validate=False)
            except Exception:
                self._json(400, {"error": "Invalid base64 data"})
                return
            if len(raw) > MAX_UPLOAD:
                self._json(400, {"error": "Image too large (max 12MB)"})
                return
            try:
                raw = validate_image_bytes(ext, raw)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            UPLOADS.mkdir(parents=True, exist_ok=True)
            out_name = f"{uuid.uuid4().hex[:10]}-{filename}"
            out_path = UPLOADS / out_name
            atomic_write_bytes(out_path, raw)
            public_url = f"/assets/uploads/{out_name}"
            self._json(
                200,
                {
                    "ok": True,
                    "url": public_url,
                    "path": str(out_path),
                    "bytes": len(raw),
                },
            )
            return

        self._json(404, {"error": "Not found"})


def which_npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def ensure_frontend_deps() -> None:
    node_modules = FRONTEND / "node_modules"
    if node_modules.is_dir():
        return
    npm = which_npm()
    if not npm:
        raise SystemExit(
            "[studio] npm niet gevonden. Installeer Node.js, daarna: cd Data/frontend && npm install"
        )
    print("[studio] npm install (eerste keer)…", flush=True)
    if os.name == "nt":
        subprocess.check_call(f'"{npm}" install', cwd=str(FRONTEND), shell=True)
    else:
        subprocess.check_call([npm, "install"], cwd=str(FRONTEND))


def start_vite() -> subprocess.Popen:
    npm = which_npm()
    if not npm:
        raise SystemExit("[studio] npm niet gevonden")

    env = os.environ.copy()
    env["LEVIATHAN_EDITOR"] = "1"
    print(f"[studio] Start echte Leviathan UI op http://{HOST}:{VITE_PORT}/", flush=True)
    if os.name == "nt":
        cmd = f'"{npm}" run dev -- --host {HOST} --port {VITE_PORT} --strictPort'
        return subprocess.Popen(cmd, cwd=str(FRONTEND), env=env, shell=True)
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--host", HOST, "--port", str(VITE_PORT), "--strictPort"],
        cwd=str(FRONTEND),
        env=env,
    )


def wait_for_vite(timeout: float = 90.0) -> None:
    import urllib.error
    import urllib.request

    url = f"http://{HOST}:{VITE_PORT}/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vite_proc and vite_proc.poll() is not None:
            raise SystemExit("[studio] Vite is onverwacht gestopt")
        try:
            with urllib.request.urlopen(url, timeout=1.5) as res:
                if res.status < 500:
                    print("[studio] Vite is klaar", flush=True)
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.4)
    raise SystemExit("[studio] Timeout: Vite startte niet")


def stop_vite() -> None:
    global vite_proc
    if vite_proc and vite_proc.poll() is None:
        vite_proc.terminate()
        try:
            vite_proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            vite_proc.kill()
    vite_proc = None


def main() -> None:
    global vite_proc

    if not STYLES.is_dir():
        raise SystemExit(f"Styles folder missing: {STYLES}")
    if not FRONTEND.is_dir():
        raise SystemExit(f"Frontend folder missing: {FRONTEND}")

    UPLOADS.mkdir(parents=True, exist_ok=True)
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    AI_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cleaned = ai_gateway().cleanup_preview()
        if cleaned.get("removed"):
            print(f"[studio] Cleaned {cleaned['removed']} expired AI preview(s)", flush=True)
    except Exception as exc:
        print(f"[studio] AI gateway startup note: {exc}", flush=True)
    acquire_process_lock()
    recovered = recover_pending_journals()
    if recovered:
        print(f"[studio] Recovered incomplete journal(s): {', '.join(recovered)}", flush=True)
    load_meta()
    if not CONTENT_FILE.is_file():
        write_content(default_content())
        save_meta({"revision": 0, "hash": canonical_persisted_hash(default_content(), read_persisted_files())})
    else:
        # Refresh hash if sidecar drifted; never invent missing content
        try:
            disk_h = canonical_persisted_hash()
            meta = load_meta()
            if not meta.get("hash"):
                save_meta({"revision": meta["revision"], "hash": disk_h})
        except ValueError as exc:
            print(f"[studio] Content unreadable: {exc}", flush=True)

    ensure_frontend_deps()
    vite_proc = start_vite()

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    api_url = f"http://{HOST}:{PORT}/"
    app_url = f"http://{HOST}:{VITE_PORT}/"

    print("=" * 60, flush=True)
    print("  LEVIATHAN STUDIO", flush=True)
    print(f"  Echte UI + editor: {app_url}", flush=True)
    print(f"  Editor API:        {api_url}", flush=True)
    print(f"  CSS:               {STYLES}", flush=True)
    print(f"  Content:           {CONTENT_FILE}", flush=True)
    print("  Ctrl+C to stop", flush=True)
    print("=" * 60, flush=True)

    def open_when_ready() -> None:
        try:
            wait_for_vite()
        except SystemExit as exc:
            print(str(exc), flush=True)
            return
        if not os.environ.get("LEVIATHAN_EDITOR_NO_BROWSER"):
            webbrowser.open(app_url)

    threading.Thread(target=open_when_ready, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[studio] stoppen…", flush=True)
    finally:
        httpd.server_close()
        stop_vite()


if __name__ == "__main__":
    main()
