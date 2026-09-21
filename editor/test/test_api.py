"""Editor API smoke tests — no Vite, no writes to Leviathan content."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import Handler


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def get(port: int, path: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    with urllib.request.urlopen(req) as res:
        body = res.read()
        ctype = res.headers.get("Content-Type", "")
        if "json" in ctype:
            return res.status, json.loads(body.decode())
        return res.status, body.decode()


def post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode())


def main() -> None:
    httpd, port = serve()
    try:
        status, health = get(port, "/api/health")
        assert status == 200 and health["ok"] is True
        status, content = get(port, "/api/content")
        assert content["content"]["version"] == 2
        assert "entries" in content["content"]
        status, js = get(port, "/js/state.js")
        assert status == 200 and "createStore" in js
        status, panel = get(port, "/js/panels/inspector.js")
        assert status == 200 and "createInspector" in panel
        status, ai = post(port, "/api/editor-ai", {"instruction": "maak goud", "selectionHtml": "<p>x</p>"})
        assert status == 501
        assert "notes" in ai
        status, missing = post(port, "/api/editor-ai", {})
        assert status == 400
        print("editor api ok")
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
