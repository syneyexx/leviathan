#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "echo": json.loads(body.decode() or "{}")}).encode())
    def log_message(self, *a): pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(__import__("sys").argv[1] if len(__import__("sys").argv)>1 else 8765)), H).serve_forever()
