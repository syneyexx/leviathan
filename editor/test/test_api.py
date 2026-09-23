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
            if ctype.startswith("image/") or ctype == "application/octet-stream":
                return res.status, body
            try:
                return res.status, body.decode()
            except UnicodeDecodeError:
                return res.status, body
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw.decode())
        except Exception:
            return err.code, raw


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        content = tmp_path / "lv-editor-content.json"
        meta = tmp_path / "lv-editor-meta.json"
        content.write_text(json.dumps(srv.default_content()), encoding="utf-8")
        meta.write_text(json.dumps({"revision": 0, "hash": ""}), encoding="utf-8")

        with mock.patch.object(srv, "CONTENT_FILE", content), mock.patch.object(srv, "META_FILE", meta), mock.patch.object(
            srv, "CHECKPOINT_DIR", tmp_path / "cp"
        ), mock.patch.object(srv, "JOURNAL_DIR", tmp_path / "journal"), mock.patch.object(
            srv, "UPLOADS", tmp_path / "uploads"
        ), mock.patch.object(srv, "AI_TEMP_DIR", tmp_path / "ai-temp"):
            (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
            (tmp_path / "ai-temp").mkdir(parents=True, exist_ok=True)            # Align empty meta hash with canonical disk state for honest concurrency
            srv.load_meta()
            srv.save_meta({"revision": 0, "hash": srv.canonical_persisted_hash()})
            httpd, port = serve()
            try:
                status, health = req(port, "/api/health")
                assert status == 200 and health["ok"] is True

                status, session = req(port, "/api/session")
                assert status == 200 and session["token"]
                token = session["token"]
                auth = {"X-LVB-Session": token}

                # mutation without token → 401
                status, err = req(port, "/api/save", "POST", {"content": srv.default_content(), "files": {}, "baseRevision": 0})
                assert status == 401

                # bad origin → 403
                status, err = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": srv.default_content(), "files": {}, "baseRevision": 0},
                    headers={**auth, "Origin": "http://evil.example"},
                )
                assert status == 403

                # valid save — use server-reported hash as concurrency token
                status, content_res = req(port, "/api/content")
                assert content_res["content"]["version"] >= 2
                base_hash = content_res.get("hash") or ""

                doc = srv.default_content()
                doc["entries"] = {"node:test1": {"text": "hello", "nodeId": "test1", "scope": "page", "page": "/"}}
                status, saved = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": doc, "files": {}, "baseRevision": content_res["revision"], "baseHash": base_hash},
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

                # missing baseRevision rejected
                status, bad = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": doc, "files": {}},
                    headers=auth,
                )
                assert status == 400

                # replace-text disabled
                status, gone = req(port, "/api/replace-text", "POST", {"old": "ab", "new": "cd"}, headers=auth)
                assert status == 410

                # AI capabilities (no session required for discovery)
                status, caps = req(port, "/api/editor-ai/capabilities")
                assert status == 200
                assert "capabilities" in caps
                assert "available" in caps

                # AI generate requires session
                status, ai_unauth = req(port, "/api/editor-ai", "POST", {"instruction": "x", "task": "generate_image"})
                assert status == 401

                # Without mock provider → honest unavailable / no-provider
                status, ai = req(
                    port,
                    "/api/editor-ai",
                    "POST",
                    {"instruction": "make an ocean", "task": "generate_image"},
                    headers=auth,
                )
                assert status in {501, 503}
                assert ai.get("unavailable") is True or (ai.get("error") or {}).get("code") in {
                    "no-provider",
                    "ai_disabled",
                }

                # Invalid task
                status, bad_task = req(
                    port,
                    "/api/editor-ai",
                    "POST",
                    {"instruction": "x", "task": "not_a_real_task"},
                    headers=auth,
                )
                assert status == 400

                # Missing instruction
                status, no_inst = req(port, "/api/editor-ai", "POST", {"task": "generate_image"}, headers=auth)
                assert status == 400

                # Mock provider success — no document mutation
                import os
                from unittest import mock as _mock

                with _mock.patch.dict(os.environ, {"LEVIATHAN_EDITOR_AI_MOCK": "1"}):
                    from ai.gateway import reset_gateway_for_tests

                    reset_gateway_for_tests()
                    meta_before = srv.load_meta()
                    mtime_before = content.stat().st_mtime
                    status, ok_ai = req(
                        port,
                        "/api/editor-ai",
                        "POST",
                        {
                            "instruction": "Leviathan ocean hero",
                            "task": "generate_image",
                            "context": {
                                "request": {
                                    "task": "generate_image",
                                    "instruction": "Leviathan ocean hero",
                                },
                                "selection": {"primary": "node:hero", "keys": ["node:hero"], "count": 1},
                                "output": {"width": 256, "height": 144, "variants": 2},
                                "style": {"source": "page_and_selection"},
                                "targetFingerprint": {"nodeKey": "node:hero"},
                            },
                        },
                        headers=auth,
                    )
                    assert status == 200, ok_ai
                    assert ok_ai["status"] == "success"
                    assert ok_ai["diagnostics"]["documentMutated"] is False
                    assert ok_ai["provider"]["isMock"] is True
                    assert len(ok_ai["result"]["variants"]) == 2
                    assert srv.load_meta() == meta_before
                    assert content.stat().st_mtime == mtime_before

                    # Preview bytes fetchable
                    temp_id = ok_ai["result"]["variants"][0]["tempId"]
                    status, preview_bytes = req(port, f"/api/editor-ai/preview/{temp_id}")
                    assert status == 200
                    assert isinstance(preview_bytes, (bytes, bytearray))
                    assert preview_bytes.startswith(b"\x89PNG")
                    # Accept promote
                    status, promoted = req(
                        port,
                        "/api/editor-ai/accept-asset",
                        "POST",
                        {
                            "tempId": temp_id,
                            "meta": {"origin": "ai-generated", "requestId": ok_ai["requestId"], "isMock": True},
                        },
                        headers=auth,
                    )
                    assert status == 200 and promoted.get("ok") and "/assets/uploads/" in promoted["url"]
                    assert content.stat().st_mtime == mtime_before
                    assert srv.load_meta() == meta_before

                status, js = req(port, "/js/state.js")
                assert status == 200 and "createStore" in js

                print("editor api ok", {"revision": rev, "ai": "gateway"})
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    main()
