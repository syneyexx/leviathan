#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from deep_engine import DeepCrawler
from deep_utils import (
    HTML_MAX_BYTES, USER_AGENT, extract_links, is_probable_download,
    normalize_url, parse_bool, assert_public_crawl_url,
)


def inspect_url(url: str, timeout_seconds: float = 20.0) -> dict:
    url = assert_public_crawl_url(url)
    # Manual redirects with SSRF hop checks (no HTTPRedirectHandler auto-follow).
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    current = url
    response = None
    for _ in range(8):
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        try:
            response = opener.open(request, timeout=timeout_seconds)
            break
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            if not location:
                raise
            current = assert_public_crawl_url(urllib.parse.urljoin(current, location))
    if response is None:
        raise RuntimeError(f"Too many redirects for {url}")
    with response:
        final_url = assert_public_crawl_url(normalize_url(response.geturl()))
        content_type = response.headers.get("Content-Type", "")
        disposition = response.headers.get("Content-Disposition", "")
        result = {
            "url": url, "final_url": final_url, "status": getattr(response, "status", 200),
            "content_type": content_type, "content_disposition": disposition,
            "probable_download": is_probable_download(final_url, content_type, disposition),
        }
        if not result["probable_download"]:
            data = response.read(min(HTML_MAX_BYTES, 2 * 1024 * 1024))
            text = data.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            links = extract_links(text, final_url)
            result["links_found"] = len(links)
            result["sample_links"] = links[:100]
        return result


def launch_terminal() -> dict:
    script, python = str(Path(__file__).resolve()), sys.executable
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        process = subprocess.Popen([python, script, "interactive"], creationflags=flags, close_fds=True)
        return {"launched": True, "pid": process.pid, "terminal": "new-console"}
    if sys.platform == "darwin":
        temp = Path(tempfile.gettempdir()) / "hades-deep-web-downloader.command"
        temp.write_text(f'#!/bin/sh\n"{python}" "{script}" interactive\nexec "$SHELL"\n', encoding="utf-8")
        temp.chmod(0o700)
        process = subprocess.Popen(["open", "-a", "Terminal", str(temp)], close_fds=True)
        return {"launched": True, "pid": process.pid, "terminal": "Terminal.app"}

    candidates = [
        (["x-terminal-emulator", "-e", python, script, "interactive"], "x-terminal-emulator"),
        (["gnome-terminal", "--", python, script, "interactive"], "gnome-terminal"),
        (["konsole", "-e", python, script, "interactive"], "konsole"),
    ]
    for command, name in candidates:
        if shutil.which(command[0]):
            process = subprocess.Popen(command, close_fds=True)
            return {"launched": True, "pid": process.pid, "terminal": name}
    raise RuntimeError("No supported terminal launcher found. Run: python crawler.py interactive")


def interactive() -> int:
    print("HADES Deep Web Downloader")
    print("Publicly accessible or otherwise authorized content only; no login/paywall/DRM bypass.")
    url = input("Start URL: ").strip()
    output = input("Output folder [downloads]: ").strip() or "downloads"
    depth = int(input("Max link depth [6]: ").strip() or "6")
    max_pages = int(input("Max pages [500]: ").strip() or "500")
    max_files = int(input("Max files [500]: ").strip() or "500")
    allowed_domains = input("Extra allowed domains (comma-separated) [none]: ").strip()
    confirmation = input("Confirm you are authorized to download this content? [y/N]: ").strip()
    if confirmation.lower() not in {"y", "yes"}:
        print("Cancelled: authorization confirmation is required.", file=sys.stderr)
        return 2
    result = DeepCrawler(
        seed_url=url, output_dir=Path(output), max_depth=depth,
        max_pages=max_pages, max_files=max_files, allowed_domains=allowed_domains,
    ).crawl()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Manifest: {result['manifest_path']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HADES deep multi-hop web crawler/downloader")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="Crawl multiple link layers and download discovered files")
    crawl.add_argument("--url", required=True)
    crawl.add_argument("--output", default="downloads")
    crawl.add_argument("--max-depth", type=int, default=6)
    crawl.add_argument("--max-pages", type=int, default=500)
    crawl.add_argument("--max-files", type=int, default=500)
    crawl.add_argument("--allowed-domains", default="")
    crawl.add_argument("--save-html", default="true")
    crawl.add_argument("--delay-seconds", type=float, default=0.2)
    crawl.add_argument("--max-file-mb", type=int, default=512)
    crawl.add_argument("--timeout-seconds", type=float, default=25.0)
    crawl.add_argument("--authorized", required=True)

    inspect = sub.add_parser("inspect", help="Inspect one URL and list discovered links")
    inspect.add_argument("--url", required=True)
    inspect.add_argument("--timeout-seconds", type=float, default=20.0)
    sub.add_parser("terminal", help="Open a new terminal running interactive mode")
    sub.add_parser("interactive", help="Interactive CLI")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "crawl":
            if not parse_bool(args.authorized):
                raise PermissionError(
                    "Authorization confirmation required. Set authorized=true only for public-domain, "
                    "licensed, or otherwise authorized content."
                )
            result = DeepCrawler(
                seed_url=args.url, output_dir=Path(args.output),
                max_depth=args.max_depth, max_pages=args.max_pages,
                max_files=args.max_files, allowed_domains=args.allowed_domains,
                save_html=parse_bool(args.save_html),
                delay_seconds=args.delay_seconds,
                max_file_bytes=args.max_file_mb * 1024 * 1024,
                timeout_seconds=args.timeout_seconds,
            ).crawl()
            summary = result.get("summary") or {}
            pages = int(summary.get("pages_fetched") or 0)
            files = int(summary.get("files_downloaded") or 0)
            if pages == 0 and files == 0:
                result = {
                    **result,
                    "ok": False,
                    "error": "crawl produced no pages or files",
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 2
            errors = result.get("errors") or []
            error_count = len(errors) if isinstance(errors, list) else int(summary.get("errors") or 0)
            seed = str(args.url or "")
            seed_failed = any(
                isinstance(err, dict) and seed and seed.rstrip("/") in str(err.get("url") or "").rstrip("/")
                for err in (errors if isinstance(errors, list) else [])
            )
            # Partial crawl with seed failure or more errors than saved artifacts is not success.
            if seed_failed or error_count >= max(1, pages + files):
                result = {
                    **result,
                    "ok": False,
                    "error": "crawl completed with blocking errors",
                    "error_count": error_count,
                    "seed_failed": seed_failed,
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 2
            result = {**result, "ok": True, "error_count": error_count}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "inspect":
            payload = inspect_url(args.url, args.timeout_seconds)
            status = int(payload.get("status") or 0)
            ok = status > 0 and status < 400
            payload = {**payload, "ok": ok, **({} if ok else {"error": f"HTTP {status or 'no response'}"})}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        if args.command == "terminal":
            print(json.dumps(launch_terminal(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "interactive":
            return interactive()
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
