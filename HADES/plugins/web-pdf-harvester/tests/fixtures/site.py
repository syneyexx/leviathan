#!/usr/bin/env python3
"""Local multi-hop fixture site for Web PDF Harvester tests."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse


PDF_BYTES = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R >>endobj
4 0 obj<< /Length 44 >>stream
BT /F1 12 Tf 50 100 Td (HADES fixture PDF) Tj ET
endstream
endobj
xref
0 5
trailer<< /Root 1 0 R /Size 5 >>
startxref
0
%%EOF
"""


def make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send(self, code: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _html(self, title: str, body: str) -> bytes:
            return (
                f"<!doctype html><html><head><title>{title}</title></head>"
                f"<body><h1>{title}</h1>{body}</body></html>"
            ).encode("utf-8")

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET(head_only=True)

        def do_GET(self, head_only: bool = False) -> None:  # noqa: N802
            path = urlparse(self.path).path
            routes: dict[str, Callable[[], None]] = {
                "/": lambda: self._send(
                    200,
                    self._html("Start", '<a href="/category">Browse category</a>'),
                    "text/html",
                ),
                "/category": lambda: self._send(
                    200,
                    self._html("Category", '<a href="/book/123">Python Networking</a>'),
                    "text/html",
                ),
                "/book/123": lambda: self._send(
                    200,
                    self._html(
                        "Python Networking",
                        '<a href="/redirect-page">Download / View book</a>',
                    ),
                    "text/html",
                ),
                "/redirect-page": lambda: self._send(
                    302,
                    b"",
                    "text/html",
                    {"Location": "/viewer"},
                ),
                "/viewer": lambda: self._send(
                    200,
                    self._html(
                        "Viewer",
                        '<iframe src="/downloads/test.pdf"></iframe>'
                        '<p><a href="/downloads/test.pdf">Open PDF</a></p>',
                    ),
                    "text/html",
                ),
                "/downloads/test.pdf": lambda: self._send(
                    200,
                    PDF_BYTES,
                    "application/pdf",
                    {"Content-Disposition": 'inline; filename="test.pdf"'},
                ),
                "/loop-a": lambda: self._send(
                    200,
                    self._html("Loop A", '<a href="/loop-b">to b</a>'),
                    "text/html",
                ),
                "/loop-b": lambda: self._send(
                    200,
                    self._html("Loop B", '<a href="/loop-a">to a</a>'),
                    "text/html",
                ),
                "/fake.pdf": lambda: self._send(
                    200,
                    self._html("Fake", "<p>This is HTML pretending to be a PDF</p>"),
                    "text/html",
                ),
                "/direct.pdf": lambda: self._send(
                    200,
                    PDF_BYTES,
                    "application/octet-stream",
                    {"Content-Disposition": 'attachment; filename="direct.pdf"'},
                ),
                "/download?id=99": lambda: self._send(
                    200,
                    PDF_BYTES,
                    "application/pdf",
                ),
                "/robots.txt": lambda: self._send(
                    200,
                    b"User-agent: *\nAllow: /\n",
                    "text/plain",
                ),
            }
            # Exact match including query-less download helper
            if path == "/download":
                self._send(200, PDF_BYTES, "application/pdf")
                return
            action = routes.get(path)
            if action is None:
                self._send(404, b"not found", "text/plain")
                return
            action()

    return Handler


class FixtureServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._httpd = ThreadingHTTPServer((host, port), make_handler())
        self.host, self.port = self._httpd.server_address[:2]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> FixtureServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


if __name__ == "__main__":
    with FixtureServer() as server:
        print(server.base_url)
        threading.Event().wait()
