#!/usr/bin/env python3
"""Standalone Leviathan visual builder — API + real Vite UI."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
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
SRC_ROOT = FRONTEND / "src"
HOST = "127.0.0.1"
PORT = 5199
VITE_PORT = 5173

ALLOWED_FILES = {
    "tokens.css": STYLES / "tokens.css",
    "leviathan.css": STYLES / "leviathan.css",
    "pages.css": STYLES / "pages.css",
    "chat.css": STYLES / "chat.css",
}

SOURCE_SUFFIXES = {".tsx", ".ts", ".jsx", ".js", ".css", ".html", ".json", ".md"}
SAFE_NAME = re.compile(r"^[a-z0-9._-]+$", re.I)
SAFE_UPLOAD = re.compile(r"^[a-zA-Z0-9._-]+$")
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, PUT, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

vite_proc: subprocess.Popen | None = None


def default_content() -> dict:
    return {"version": 2, "entries": {}, "nodes": []}


def read_content() -> dict:
    if not CONTENT_FILE.is_file():
        return default_content()
    try:
        data = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_content()
    if not isinstance(data, dict):
        return default_content()
    data.setdefault("version", 2)
    data.setdefault("entries", {})
    data.setdefault("nodes", [])
    if not isinstance(data["entries"], dict):
        data["entries"] = {}
    if not isinstance(data["nodes"], list):
        data["nodes"] = []
    return data


def write_content(data: dict) -> None:
    CONTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def replace_in_sources(old: str, new: str) -> list[dict]:
    """Replace exact string in frontend source files. Skips tiny strings."""
    if not isinstance(old, str) or not isinstance(new, str):
        return []
    if old == new or len(old) < 2:
        return []
    changed: list[dict] = []
    for path in SRC_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old not in text:
            continue
        count = text.count(old)
        path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        changed.append({"path": str(path.relative_to(REPO)), "count": count})
    # Also patch public content references in HTML if any
    for path in PUBLIC.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".json", ".svg"}:
            continue
        if path.resolve() == CONTENT_FILE.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old not in text:
            continue
        count = text.count(old)
        path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        changed.append({"path": str(path.relative_to(REPO)), "count": count})
    return changed


class Handler(BaseHTTPRequestHandler):
    server_version = "LeviathanLayoutEditor/3.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[editor] {self.address_string()} - {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in CORS.items():
            self.send_header(key, value)
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_json(self) -> dict | None:
        raw = self._read_body()
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
            self._json(
                200,
                {
                    "ok": True,
                    "styles": str(STYLES),
                    "content": str(CONTENT_FILE),
                    "repo": str(REPO),
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
            data = read_content()
            self._json(200, {"content": data, "path": str(CONTENT_FILE)})
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
        parsed = urlparse(self.path)

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
            content = payload.get("content")
            if not isinstance(content, str):
                self._json(400, {"error": "content must be a string"})
                return
            if len(content) > 2_000_000:
                self._json(400, {"error": "File too large"})
                return
            file_path = ALLOWED_FILES[name]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8", newline="\n")
            self._json(
                200,
                {
                    "ok": True,
                    "name": name,
                    "bytes": len(content.encode("utf-8")),
                    "path": str(file_path),
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
            content.setdefault("version", 2)
            content.setdefault("entries", {})
            content.setdefault("nodes", [])
            if not isinstance(content["entries"], dict):
                self._json(400, {"error": "entries must be an object"})
                return
            if not isinstance(content.get("nodes"), list):
                self._json(400, {"error": "nodes must be a list"})
                return
            write_content(content)
            self._json(
                200,
                {
                    "ok": True,
                    "path": str(CONTENT_FILE),
                    "entries": len(content["entries"]),
                    "nodes": len(content["nodes"]),
                },
            )
            return

        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/replace-text":
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
                return
            old = payload.get("old")
            new = payload.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                self._json(400, {"error": "old and new must be strings"})
                return
            if len(old) < 2:
                self._json(400, {"error": "old text too short (min 2 chars)"})
                return
            changed = replace_in_sources(old, new)
            self._json(200, {"ok": True, "changed": changed, "count": len(changed)})
            return

        if parsed.path == "/api/upload":
            payload = self._read_json()
            if payload is None:
                self._json(400, {"error": "Expected JSON body"})
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
            if len(raw) > 12_000_000:
                self._json(400, {"error": "Image too large (max 12MB)"})
                return
            UPLOADS.mkdir(parents=True, exist_ok=True)
            out_name = f"{uuid.uuid4().hex[:10]}-{filename}"
            out_path = UPLOADS / out_name
            out_path.write_bytes(raw)
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
            "[editor] npm niet gevonden. Installeer Node.js, daarna: cd Data/frontend && npm install"
        )
    print("[editor] npm install (eerste keer)…", flush=True)
    if os.name == "nt":
        subprocess.check_call(f'"{npm}" install', cwd=str(FRONTEND), shell=True)
    else:
        subprocess.check_call([npm, "install"], cwd=str(FRONTEND))


def start_vite() -> subprocess.Popen:
    npm = which_npm()
    if not npm:
        raise SystemExit("[editor] npm niet gevonden")

    env = os.environ.copy()
    env["LEVIATHAN_EDITOR"] = "1"
    print(f"[editor] Start echte Leviathan UI op http://{HOST}:{VITE_PORT}/", flush=True)
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
            raise SystemExit("[editor] Vite is onverwacht gestopt")
        try:
            with urllib.request.urlopen(url, timeout=1.5) as res:
                if res.status < 500:
                    print("[editor] Vite is klaar", flush=True)
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.4)
    raise SystemExit("[editor] Timeout: Vite startte niet")


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
    if not CONTENT_FILE.is_file():
        write_content(default_content())

    ensure_frontend_deps()
    vite_proc = start_vite()

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    api_url = f"http://{HOST}:{PORT}/"
    app_url = f"http://{HOST}:{VITE_PORT}/"

    print("=" * 60, flush=True)
    print("  LEVIATHAN Visual Builder", flush=True)
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
        print("\n[editor] stoppen…", flush=True)
    finally:
        httpd.server_close()
        stop_vite()


if __name__ == "__main__":
    main()
