#!/usr/bin/env python3
"""Standalone Leviathan layout editor server. Not part of the main app."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
STYLES = REPO / "Data" / "frontend" / "src" / "styles"
PUBLIC = REPO / "Data" / "frontend" / "public"
HOST = "127.0.0.1"
PORT = 5199

ALLOWED_FILES = {
    "tokens.css": STYLES / "tokens.css",
    "leviathan.css": STYLES / "leviathan.css",
    "pages.css": STYLES / "pages.css",
    "chat.css": STYLES / "chat.css",
}

SAFE_NAME = re.compile(r"^[a-z0-9._-]+$", re.I)


class Handler(BaseHTTPRequestHandler):
    server_version = "LeviathanLayoutEditor/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[editor] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        self._send(
            204,
            b"",
            "text/plain",
            {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

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
            self._json(200, {"files": files})
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
            self._json(200, {"name": name, "content": text})
            return

        target = self._resolve_static(path)
        if target is None or not target.is_file():
            self._json(404, {"error": "Not found", "path": path})
            return

        data = target.read_bytes()
        mime, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            mime = "text/javascript; charset=utf-8"
        elif target.suffix == ".html":
            mime = "text/html; charset=utf-8"
        elif not mime:
            mime = "application/octet-stream"
        self._send(200, data, mime)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/file":
            self._json(404, {"error": "Not found"})
            return

        qs = parse_qs(parsed.query)
        name = (qs.get("name") or [""])[0]
        if name not in ALLOWED_FILES or not SAFE_NAME.match(name):
            self._json(400, {"error": "Unknown file"})
            return

        raw = self._read_body()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
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
        self._json(200, {"ok": True, "name": name, "bytes": len(content.encode("utf-8"))})


def main() -> None:
    if not STYLES.is_dir():
        raise SystemExit(f"Styles folder missing: {STYLES}")

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print("=" * 56, flush=True)
    print("  LEVIATHAN layout editor", flush=True)
    print(f"  Open: {url}", flush=True)
    print(f"  Styles: {STYLES}", flush=True)
    print("  Ctrl+C to stop", flush=True)
    print("=" * 56, flush=True)

    # Optional browser open — skip when LEVIATHAN_EDITOR_NO_BROWSER=1
    if not os.environ.get("LEVIATHAN_EDITOR_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[editor] stopped", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
