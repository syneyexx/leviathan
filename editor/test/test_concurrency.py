"""P0-B: concurrent save race, journal recovery, schema rejection, write contracts."""

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


def isolated_project(tmp: Path):
    content = tmp / "lv-editor-content.json"
    meta = tmp / "lv-editor-meta.json"
    styles = tmp / "styles"
    styles.mkdir()
    for name in srv.ALLOWED_FILES:
        (styles / name).write_text(f"/* {name} */\n", encoding="utf-8")
    content.write_text(json.dumps(srv.default_content()), encoding="utf-8")
    meta.write_text(json.dumps({"revision": 0, "hash": ""}), encoding="utf-8")
    allowed = {name: styles / name for name in srv.ALLOWED_FILES}
    return content, meta, allowed, tmp / "cp", tmp / "journal"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        content, meta, allowed, cp, journal = isolated_project(tmp_path)

        with mock.patch.object(srv, "CONTENT_FILE", content), mock.patch.object(srv, "META_FILE", meta), mock.patch.object(
            srv, "CHECKPOINT_DIR", cp
        ), mock.patch.object(srv, "JOURNAL_DIR", journal), mock.patch.object(srv, "ALLOWED_FILES", allowed), mock.patch.object(
            srv, "STYLES", tmp_path / "styles"
        ):
            # Startup recovery: pending journal rolls back
            doc_v1 = srv.default_content()
            doc_v1["entries"] = {"node:keep": {"text": "keep", "nodeId": "keep", "scope": "page", "page": "/"}}
            content.write_text(json.dumps(doc_v1), encoding="utf-8")
            meta.write_text(json.dumps({"revision": 3, "hash": "meta-before"}), encoding="utf-8")
            # Simulate incomplete txn that wrote a bad next content
            bad = srv.default_content()
            bad["entries"] = {"node:bad": {"text": "should-rollback"}}
            journal.mkdir(parents=True, exist_ok=True)
            txn = {
                "id": "deadbeef",
                "files": {},
                "content": {"previous": doc_v1, "existed": True, "next": bad},
                "meta": {"previous": {"revision": 3, "hash": "meta-before"}},
            }
            # Pretend crash after writing content but before commit
            content.write_text(json.dumps(bad), encoding="utf-8")
            (journal / "deadbeef.json").write_text(json.dumps(txn), encoding="utf-8")
            recovered = srv.recover_pending_journals()
            assert "deadbeef" in recovered
            restored = json.loads(content.read_text(encoding="utf-8"))
            assert "node:keep" in restored["entries"]
            assert "node:bad" not in restored["entries"]
            assert json.loads(meta.read_text(encoding="utf-8"))["revision"] == 3

            # Absent prior file must not become invented empty file on rollback
            ghost_name = next(iter(allowed))
            ghost_path = allowed[ghost_name]
            if ghost_path.is_file():
                ghost_path.unlink()
            txn2 = {
                "id": "ghost1",
                "files": {ghost_name: {"previous": None, "existed": False, "next": "invented{}"}},
                "content": None,
                "meta": {"previous": {"revision": 3, "hash": "meta-before"}},
            }
            ghost_path.write_text("invented{}", encoding="utf-8")
            (journal / "ghost1.json").write_text(json.dumps(txn2), encoding="utf-8")
            srv.journal_rollback("ghost1")
            assert not ghost_path.is_file(), "rollback must unlink file that did not exist before txn"

            # Re-seed styles for live API tests
            for name, path in allowed.items():
                path.write_text(f"/* {name} */\n", encoding="utf-8")
            content.write_text(json.dumps(srv.default_content()), encoding="utf-8")
            # Align meta hash with disk
            srv.load_meta()
            h0 = srv.canonical_persisted_hash()
            srv.save_meta({"revision": 0, "hash": h0})

            httpd, port = serve()
            try:
                status, session = req(port, "/api/session")
                token = session["token"]
                auth = {"X-LVB-Session": token}

                # Future schema rejected without mutation
                before = content.read_text(encoding="utf-8")
                future = srv.default_content()
                future["version"] = 99
                status, err = req(
                    port,
                    "/api/save",
                    "POST",
                    {"content": future, "files": {}, "baseRevision": 0, "baseHash": h0},
                    headers=auth,
                )
                assert status == 400 and "schema" in err["error"].lower()
                assert content.read_text(encoding="utf-8") == before

                # Concurrent same-base: exactly one success, one conflict
                doc = srv.default_content()
                doc["entries"] = {"node:race": {"text": "a", "nodeId": "race", "scope": "page", "page": "/"}}
                results: list[tuple[int, dict]] = []
                barrier = threading.Barrier(2)

                def worker(label: str):
                    barrier.wait()
                    d = json.loads(json.dumps(doc))
                    d["entries"]["node:race"]["text"] = label
                    results.append(
                        req(
                            port,
                            "/api/save",
                            "POST",
                            {"content": d, "files": {}, "baseRevision": 0, "baseHash": h0},
                            headers=auth,
                        )
                    )

                t1 = threading.Thread(target=worker, args=("one",))
                t2 = threading.Thread(target=worker, args=("two",))
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                codes = sorted(r[0] for r in results)
                assert codes == [200, 409], f"expected one commit and one conflict, got {results}"

                # Winner revision is 1
                status, body = req(port, "/api/content", headers=auth)
                assert body["revision"] == 1
                winner_hash = body["hash"]

                # PUT /api/file requires concurrency token
                status, err = req(
                    port,
                    f"/api/file?name={next(iter(allowed))}",
                    "PUT",
                    {"content": "/* no token */"},
                    headers=auth,
                )
                assert status == 400

                status, saved_file = req(
                    port,
                    f"/api/file?name={next(iter(allowed))}",
                    "PUT",
                    {"content": "/* revised */\n", "baseRevision": 1, "baseHash": winner_hash},
                    headers=auth,
                )
                assert status == 200 and saved_file["revision"] == 2

                # Stale base on file write → 409
                status, conflict = req(
                    port,
                    f"/api/file?name={next(iter(allowed))}",
                    "PUT",
                    {"content": "/* stale */\n", "baseRevision": 1, "baseHash": winner_hash},
                    headers=auth,
                )
                assert status == 409

                print("editor concurrency ok", {"results": codes, "revision": saved_file["revision"]})
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    main()
