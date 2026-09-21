#!/usr/bin/env python3
"""HADES bridge for Patchright (stealth Playwright drop-in)."""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def doctor() -> dict:
    import cli_bridge

    payload = cli_bridge.doctor(["patchright"], ["patchright"])
    payload["notes"] = [
        "Run install_browsers once after dependency install.",
        "Use fetch/screenshot for research pages that block vanilla Playwright.",
        "This is browser automation — not an exploit framework.",
    ]
    return payload


def install_browsers() -> dict:
    process = subprocess.run(
        [sys.executable, "-m", "patchright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=1800,
        shell=False,
    )
    exit_code = int(process.returncode or 0)
    return {
        "ok": exit_code == 0,
        "command": [sys.executable, "-m", "patchright", "install", "chromium"],
        "exit_code": exit_code,
        "stdout": (process.stdout or "")[-40_000:],
        "stderr": (process.stderr or "")[-40_000:],
        **({"error": "browser_install_failed"} if exit_code != 0 else {}),
    }


def _launch():
    from patchright.sync_api import sync_playwright

    return sync_playwright()


def _resolved_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(host)}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"Host resolution failed: {host}") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        try:
            addresses.add(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise ValueError(f"Host resolved to no usable addresses: {host}")
    return addresses


def ensure_public_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    host = (parsed.hostname or "").lower().strip("[]")
    if not host or host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError(f"Private/local host blocked: {host or '<empty>'}")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    addresses = _resolved_addresses(host, port)
    blocked = [str(address) for address in addresses if not address.is_global]
    if blocked:
        raise ValueError(f"Private/non-public address blocked for {host}: {', '.join(sorted(blocked))}")
    return parsed.geturl()


def _install_request_guard(page) -> None:
    def guard(route) -> None:
        request_url = str(route.request.url or "")
        parsed = urlparse(request_url)
        if parsed.scheme.lower() not in {"http", "https"}:
            route.continue_()
            return
        try:
            ensure_public_url(request_url)
        except ValueError:
            route.abort("blockedbyclient")
            return
        route.continue_()

    page.route("**/*", guard)


def _blocked_result(url: str, exc: Exception, *, output: str | None = None) -> dict:
    payload = {"url": url, "ok": False, "status": 0, "error": str(exc)}
    if output is None:
        payload.update({"chars": 0, "text": ""})
    else:
        payload.update({"path": "", "output": output, "bytes": 0})
    return payload


def fetch(url: str, max_chars: int) -> dict:
    try:
        url = ensure_public_url(url)
    except ValueError as exc:
        return _blocked_result(url, exc)

    with _launch() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            _install_request_guard(page)
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                ensure_public_url(page.url)
            except ValueError as exc:
                return _blocked_result(url, exc)
            status = int(response.status) if response is not None else 0
            if response is None or status >= 400:
                return {
                    "url": url,
                    "ok": False,
                    "status": status,
                    "error": f"HTTP {status or 'no response'}",
                    "chars": 0,
                    "text": "",
                }
            title = page.title()
            text = page.inner_text("body") or ""
            return {
                "url": page.url,
                "title": title,
                "ok": bool(str(text).strip()),
                "status": status,
                "chars": len(text),
                "truncated": len(text) > max_chars,
                "text": text[:max_chars],
                **({} if str(text).strip() else {"error": "empty fetch result"}),
            }
        finally:
            browser.close()


def screenshot(url: str, output: str) -> dict:
    try:
        url = ensure_public_url(url)
    except ValueError as exc:
        return _blocked_result(url, exc, output=output)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _launch() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            _install_request_guard(page)
            response = page.goto(url, wait_until="networkidle", timeout=60_000)
            try:
                ensure_public_url(page.url)
            except ValueError as exc:
                return _blocked_result(url, exc, output=str(out.resolve()))
            status = int(response.status) if response is not None else 0
            if response is None or status >= 400:
                return {
                    "url": url,
                    "ok": False,
                    "status": status,
                    "error": f"HTTP {status or 'no response'}",
                    "output": str(out.resolve()),
                    "bytes": 0,
                }
            page.screenshot(path=str(out), full_page=True)
            bytes_written = out.stat().st_size if out.exists() else 0
            return {
                "url": page.url,
                "ok": bytes_written > 0,
                "status": status,
                "output": str(out.resolve()),
                "bytes": bytes_written,
                **({} if bytes_written > 0 else {"error": "empty screenshot"}),
            }
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("install_browsers")
    f = sub.add_parser("fetch")
    f.add_argument("--url", required=True)
    f.add_argument("--max-chars", type=int, default=20000)
    s = sub.add_parser("screenshot")
    s.add_argument("--url", required=True)
    s.add_argument("--output", default="screenshot.png")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "install_browsers":
        payload = install_browsers()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1
    if args.cmd == "fetch":
        payload = fetch(args.url, args.max_chars)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if payload.get("ok") is False:
            return 1
        if not str(payload.get("text") or "").strip():
            return 2
        return 0
    payload = screenshot(args.url, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("ok") is False:
        return 1
    if int(payload.get("bytes") or 0) <= 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
