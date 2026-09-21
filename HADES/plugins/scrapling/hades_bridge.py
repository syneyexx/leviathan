#!/usr/bin/env python3
from __future__ import annotations
import argparse
import ipaddress
import json
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse


MAX_REDIRECTS = 10
MAX_EXTRACT_CHARS = 5_000_000


def doctor() -> dict:
    import cli_bridge
    payload = cli_bridge.doctor(["scrapling"], ["scrapling"])
    payload["notes"] = [
        "After pip install, run tool install_browsers once to fetch Playwright browsers.",
        "Network policy must allow outbound HTTP for fetching pages.",
    ]
    return payload


def install_browsers() -> dict:
    binary = shutil.which("scrapling") or shutil.which("scrapling.exe") or "scrapling"
    process = subprocess.run([binary, "install"], capture_output=True, text=True, timeout=1800, shell=False)
    exit_code = int(process.returncode or 0)
    return {
        "ok": exit_code == 0,
        "command": [binary, "install"],
        "exit_code": exit_code,
        "stdout": (process.stdout or "")[-40_000:],
        "stderr": (process.stderr or "")[-40_000:],
        **({"error": "browser_install_failed"} if exit_code != 0 else {}),
    }


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


def _page_setup(page) -> None:
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


def _status(page) -> int | None:
    status = getattr(page, "status", None)
    if status is None:
        status = getattr(page, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _headers(page) -> dict[str, str]:
    raw = getattr(page, "headers", None) or getattr(page, "response_headers", None) or {}
    try:
        return {str(key).lower(): str(value) for key, value in dict(raw).items()}
    except Exception:
        return {}


def _static_fetch(url: str):
    """Fetch static pages without allowing Scrapling to follow redirects itself.

    Every redirect target is validated before the next request, so an attacker
    cannot use a public open redirect to reach loopback/RFC1918/link-local hosts.
    """
    from scrapling.fetchers import Fetcher

    current = ensure_public_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        page = Fetcher.get(current, follow_redirects=False)
        status = _status(page)
        if status is None or not 300 <= status < 400:
            final = str(getattr(page, "url", None) or current)
            ensure_public_url(final)
            return page, final
        location = _headers(page).get("location")
        if not location:
            return page, current
        current = ensure_public_url(urljoin(current, location))
    raise ValueError(f"Too many redirects (>{MAX_REDIRECTS})")


def _content_text(page) -> str:
    raw = getattr(page, "text", None)
    if raw is None:
        raw = getattr(page, "body", None)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", errors="replace")
    return ""


def _blocked_fetch(url: str, mode: str, exc: Exception) -> dict:
    return {
        "ok": False,
        "url": url,
        "mode": mode,
        "status": 0,
        "chars": 0,
        "text": "",
        "items": [],
        "error": str(exc),
    }


def fetch(url: str, mode: str, css: str, max_chars: int) -> dict:
    try:
        url = ensure_public_url(url)
    except ValueError as exc:
        return _blocked_fetch(url, mode, exc)

    try:
        final_url = url
        if mode == "stealth":
            from scrapling.fetchers import StealthyFetcher
            StealthyFetcher.adaptive = True
            page = StealthyFetcher.fetch(url, headless=True, network_idle=True, page_setup=_page_setup)
            final_url = ensure_public_url(str(getattr(page, "url", None) or url))
        elif mode == "dynamic":
            from scrapling.fetchers import DynamicFetcher
            page = DynamicFetcher.fetch(url, headless=True, network_idle=True, page_setup=_page_setup)
            final_url = ensure_public_url(str(getattr(page, "url", None) or url))
        else:
            page, final_url = _static_fetch(url)
    except ValueError as exc:
        return _blocked_fetch(url, mode, exc)

    # Only real content fields — never fall back to str(page) object repr.
    text = _content_text(page)
    status_i = _status(page)
    items: list[str] = []
    css_error: str | None = None
    if css:
        try:
            selected = page.css(css)
            for item in list(selected)[:50]:
                items.append(str(getattr(item, "text", None) or item)[:2000])
        except Exception as exc:  # noqa: BLE001 - surface selector failures honestly
            css_error = str(exc)
    http_error = status_i is not None and status_i >= 400
    ok = (bool(text.strip()) or bool(items)) and not css_error and not http_error
    payload = {
        "ok": ok,
        "url": final_url,
        "mode": mode,
        "css": css or None,
        "status": status_i,
        "chars": len(text),
        "truncated": len(text) > max_chars,
        "text": text[:max_chars],
        "css_matches": items,
    }
    if http_error:
        payload["error"] = f"HTTP {status_i}"
    elif css_error:
        payload["error"] = f"css_error: {css_error}"
    elif not ok:
        payload["error"] = "empty fetch result"
    return payload


def extract(url: str, output: str) -> dict:
    """Safely save fetched content without delegating redirect handling to a CLI."""
    try:
        url = ensure_public_url(url)
        page, final_url = _static_fetch(url)
    except Exception as exc:  # noqa: BLE001 - convert security/network failures to truthful tool output
        return {
            "ok": False,
            "url": url,
            "output": output,
            "output_bytes": 0,
            "error": str(exc),
        }

    status_i = _status(page)
    if status_i is not None and status_i >= 400:
        return {
            "ok": False,
            "url": final_url,
            "status": status_i,
            "output": output,
            "output_bytes": 0,
            "error": f"HTTP {status_i}",
        }
    text = _content_text(page)
    if not text.strip():
        return {
            "ok": False,
            "url": final_url,
            "status": status_i,
            "output": output,
            "output_bytes": 0,
            "error": "extract output missing or empty",
        }
    if len(text) > MAX_EXTRACT_CHARS:
        return {
            "ok": False,
            "url": final_url,
            "status": status_i,
            "output": output,
            "output_bytes": 0,
            "error": f"extract content exceeds {MAX_EXTRACT_CHARS} character safety limit",
        }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    size = out.stat().st_size if out.is_file() else 0
    return {
        "ok": size > 0,
        "url": final_url,
        "status": status_i,
        "output": str(out),
        "output_bytes": size,
        **({} if size > 0 else {"error": "extract output missing or empty"}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("install_browsers")
    f = sub.add_parser("fetch")
    f.add_argument("--url", required=True)
    f.add_argument("--mode", default="basic", choices=["basic", "stealth", "dynamic"])
    f.add_argument("--css", default="")
    f.add_argument("--max-chars", type=int, default=20000)
    e = sub.add_parser("extract")
    e.add_argument("--url", required=True)
    e.add_argument("--output", required=True)
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
        payload = fetch(args.url, args.mode, args.css, args.max_chars)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 2
    payload = extract(args.url, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
