"""LEVIATHAN STUDIO API smoke tests — isolated temp content, session auth."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server as srv


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def req(port: int, path: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    h = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:5173"}
    if headers:
        h.update(headers)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=h,
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as res:
            body = res.read()
            ctype = res.headers.get("Content-Type", "")
            if "json" in ctype:
                return res.status, json.loads(body.decode())
            return res.status, body.decode()
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode())


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        content = tmp_path / "lv-editor-content.json"
        meta = tmp_path / "lv-editor-meta.json"
        content.write_text(json.dumps(srv.default_content()), encoding="utf-8")
        meta.write_text(json.dumps({"revision": 0, "hash": ""}), encoding="utf-8")

        with mock.patch.object(srv, "CONTENT_FILE", content), mock.patch.object(srv, "META_FILE", meta), mock.patch.object(
            srv, "CHECKPOINT_DIR", tmp_path / "cp"
        ), mock.patch.object(srv, "JOURNAL_DIR", tmp_path / "journal"):
            srv.load_meta()
            httpd, port = serve()
            try:
                status, health = req(port, "/api/health")
                assert status == 200 and health["ok"] is True

                status, session = req(port, "/api/session")
                assert status == 200 and session["token"]
                token = session["token"]
                auth = {"X-LVB-Session": token}

                status, content_res = req(port, "/api/content")
                assert content_res["content"]["version"] >= 2

                # mutation without token → 401
                status, err = req(port, "/api/save", "POST", {"content": srv.default_content(), "files": {}})
                assert status == 401

                # bad origin → 403
                status, err = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": srv.default_content(), "files": {}},
                    headers={**auth, "Origin": "http://evil.example"},
                )
                assert status == 403

                # valid save
                doc = srv.default_content()
                doc["entries"] = {"node:test1": {"text": "hello", "nodeId": "test1", "scope": "page", "page": "/"}}
                status, saved = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": doc, "files": {}, "baseRevision": 0, "baseHash": ""},
                    headers=auth,
                )
                assert status == 200 and saved["ok"] is True
                rev = saved["revision"]

                # conflict
                status, conflict = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": doc, "files": {}, "baseRevision": 0, "baseHash": "stale"},
                    headers=auth,
                )
                assert status == 409

                # replace-text disabled
                status, gone = req(port, "/api/replace-text", "POST", {"old": "ab", "new": "cd"}, headers=auth)
                assert status == 410

                status, ai = req(port, "/api/editor-ai", "POST", {"instruction": "x"})
                assert status == 501 and ai.get("unavailable") is True

                status, js = req(port, "/js/state.js")
                assert status == 200 and "createStore" in js

                print("editor api ok", {"revision": rev})
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    main()
