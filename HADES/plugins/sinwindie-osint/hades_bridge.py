#!/usr/bin/env python3
"""HADES bridge for sinwindie/OSINT — SULTAN username search + resource catalog.

Upstream is mostly attack-surface PDFs/bookmarklets plus the Python 2 SULTAN
username checker. This bridge modernizes SULTAN (Python 3, JSON argv tools) and
exposes the curated topic/bookmarklet catalog for Plugin Manager.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
USER_AGENT = "HADES-Sinwindie-OSINT/0.1 (+local plugin; public OSINT)"
DEFAULT_TIMEOUT = 10.0


def emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def load_json(name: str) -> dict[str, Any]:
    path = ROOT / name
    if not path.is_file():
        raise FileNotFoundError(f"missing packaged data file: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def doctor() -> dict[str, Any]:
    import cli_bridge

    payload = cli_bridge.doctor(["requests"], ["python", "python3"])
    sites = load_json("sultan_sites.json")
    catalog = load_json("catalog.json")
    bookmarklets = load_json("bookmarklets.json")
    site_count = sum(1 for item in sites.get("entries", []) if item.get("kind") == "site")
    payload["bundle"] = {
        "sultan_sites": site_count,
        "topics": len(catalog.get("topics", [])),
        "bookmarklets": len(bookmarklets.get("bookmarklets", [])),
        "upstream": catalog.get("source"),
    }
    payload["notes"] = [
        "SULTAN username search probes public profile URLs from the upstream spreadsheet.",
        "PDF attack-surface guides are catalogued but omitted from the package (size); open upstream GitHub for full PDFs.",
        "Author terms: personal toolkit use only — do not sell/host without permission (see upstream README).",
    ]
    if site_count <= 0 or len(catalog.get("topics", [])) <= 0:
        payload["ok"] = False
        payload["error"] = payload.get("error") or "curated OSINT catalogs are empty"
    return payload


def list_topics(query: str = "") -> dict[str, Any]:
    catalog = load_json("catalog.json")
    needle = (query or "").strip().lower()
    topics = []
    for topic in catalog.get("topics", []):
        blob = f"{topic.get('id','')} {topic.get('name','')}".lower()
        if needle and needle not in blob:
            resources = topic.get("resources") or []
            if not any(needle in str(item.get("name", "")).lower() or needle in str(item.get("path", "")).lower() for item in resources):
                continue
        topics.append(
            {
                "id": topic.get("id"),
                "name": topic.get("name"),
                "resource_count": topic.get("resource_count", len(topic.get("resources") or [])),
                "resources": topic.get("resources") or [],
            }
        )
    ok = True
    error = None
    if needle and not topics:
        ok = False
        error = "no topics matched query"
    elif not needle and not topics:
        ok = False
        error = "topic catalog is empty"
    payload = {
        "ok": ok,
        "query": query,
        "count": len(topics),
        "topics": topics,
        "source": catalog.get("source"),
        "note": "PDF resources are listed with packaged=false; fetch from upstream if needed.",
    }
    if error:
        payload["error"] = error
    return payload


def list_bookmarklets(topic: str = "") -> dict[str, Any]:
    data = load_json("bookmarklets.json")
    needle = (topic or "").strip().lower()
    rows = []
    for item in data.get("bookmarklets", []):
        if needle and needle not in str(item.get("topic", "")).lower() and needle not in str(item.get("title", "")).lower():
            continue
        rows.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "topic": item.get("topic"),
                "path": item.get("path"),
                "chars": len(item.get("content") or ""),
            }
        )
    ok = True
    error = None
    if needle and not rows:
        ok = False
        error = "no bookmarklets matched topic"
    elif not needle and not rows:
        ok = False
        error = "bookmarklet catalog is empty"
    payload = {"ok": ok, "count": len(rows), "bookmarklets": rows}
    if error:
        payload["error"] = error
    return payload


def get_bookmarklet(bookmarklet_id: str) -> dict[str, Any]:
    bookmarklet_id = (bookmarklet_id or "").strip()
    if not bookmarklet_id:
        raise ValueError("id is required")
    data = load_json("bookmarklets.json")
    for item in data.get("bookmarklets", []):
        if item.get("id") == bookmarklet_id or item.get("path") == bookmarklet_id or item.get("title") == bookmarklet_id:
            return {"ok": True, "bookmarklet": item}
    raise FileNotFoundError(f"bookmarklet not found: {bookmarklet_id}")


def list_sites(category: str = "", query: str = "") -> dict[str, Any]:
    data = load_json("sultan_sites.json")
    cat = (category or "").strip().lower()
    needle = (query or "").strip().lower()
    sites = []
    for item in data.get("entries", []):
        if item.get("kind") != "site":
            continue
        if cat and cat not in str(item.get("category", "")).lower():
            continue
        blob = f"{item.get('urla','')}{item.get('urlb','')}{item.get('category','')}".lower()
        if needle and needle not in blob:
            continue
        sites.append(
            {
                "category": item.get("category"),
                "url_template": f"{item.get('urla','')}{{username}}{item.get('urlb','')}",
                "error_text": item.get("error_text"),
                "example_username": item.get("example_username"),
            }
        )
    categories = sorted({item.get("category") for item in data.get("entries", []) if item.get("kind") == "site"})
    ok = True
    error = None
    if (cat or needle) and not sites:
        ok = False
        error = "no sites matched filters"
    elif not sites:
        ok = False
        error = "site catalog is empty"
    payload = {"ok": ok, "count": len(sites), "categories": categories, "sites": sites}
    if error:
        payload["error"] = error
    return payload


def _fetch(url: str, error_text: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - OSINT URL from curated list + username
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(200_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        status = int(exc.code)
        body = ""
        try:
            body = exc.read(50_000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = str(exc.reason or "")
    except (URLError, TimeoutError, OSError) as exc:
        return {"url": url, "found": False, "error": str(exc)}

    # Upstream SULTAN: profile exists when error_text is NOT found in HTML.
    if error_text:
        found = body.find(error_text) == -1 and status < 400
    else:
        found = status == 200
    return {"url": url, "found": bool(found), "status": status}


def search_username(
    username: str,
    *,
    category: str = "",
    max_sites: int = 0,
    timeout: float = DEFAULT_TIMEOUT,
    workers: int = 8,
) -> dict[str, Any]:
    username = (username or "").strip().lstrip("@")
    if not username:
        raise ValueError("username is required")
    if any(ch.isspace() for ch in username) or "/" in username:
        raise ValueError("username must be a single handle without spaces or slashes")

    data = load_json("sultan_sites.json")
    cat = (category or "").strip().lower()
    targets = []
    for item in data.get("entries", []):
        if item.get("kind") != "site":
            continue
        if cat and cat not in str(item.get("category", "")).lower():
            continue
        url = f"{item.get('urla', '')}{username}{item.get('urlb', '')}"
        targets.append(
            {
                "category": item.get("category"),
                "url": url,
                "error_text": item.get("error_text") or "",
            }
        )
    if max_sites and max_sites > 0:
        targets = targets[:max_sites]

    found: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    workers = max(1, min(int(workers or 1), 16))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch, row["url"], row["error_text"], timeout): row
            for row in targets
        }
        for future in as_completed(futures):
            meta = futures[future]
            result = future.result()
            row = {"category": meta["category"], **result}
            if result.get("error"):
                errors.append(row)
            elif result.get("found"):
                found.append(row)
            else:
                missing.append(row)

    found.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("url") or "")))
    checked = len(targets)
    # All probes errored — not a legitimate empty find (same class as ghosttrack).
    all_probes_failed = checked > 0 and len(errors) == checked and len(found) == 0
    return {
        "ok": not all_probes_failed,
        "username": username,
        "checked": checked,
        "found_count": len(found),
        "found": found,
        "missing_count": len(missing),
        "missing": missing[:50],
        "errors": errors,
        "error": (
            "all username probes failed (network/timeout)"
            if all_probes_failed
            else None
        ),
        "heuristic": "Upstream SULTAN: URL counted as found when configured error_text is absent from the response body.",
        "source": "sinwindie/OSINT SULTAN_DATA.xlsx",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES sinwindie/OSINT bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    p_topics = sub.add_parser("list_topics")
    p_topics.add_argument("--query", default="")

    p_bm = sub.add_parser("list_bookmarklets")
    p_bm.add_argument("--topic", default="")

    p_get = sub.add_parser("get_bookmarklet")
    p_get.add_argument("--id", required=True)

    p_sites = sub.add_parser("list_sites")
    p_sites.add_argument("--category", default="")
    p_sites.add_argument("--query", default="")

    p_search = sub.add_parser("search_username")
    p_search.add_argument("--username", required=True)
    p_search.add_argument("--category", default="")
    p_search.add_argument("--max-sites", type=int, default=0)
    p_search.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_search.add_argument("--workers", type=int, default=8)

    args = parser.parse_args()
    try:
        if args.cmd == "doctor":
            payload = doctor()
            return emit(payload, exit_code=0 if payload.get("ok", True) else 2)
        if args.cmd == "list_topics":
            payload = list_topics(args.query)
            return emit(payload, exit_code=0 if payload.get("ok") else 2)
        if args.cmd == "list_bookmarklets":
            payload = list_bookmarklets(args.topic)
            return emit(payload, exit_code=0 if payload.get("ok") else 2)
        if args.cmd == "get_bookmarklet":
            return emit(get_bookmarklet(args.id))
        if args.cmd == "list_sites":
            payload = list_sites(args.category, args.query)
            return emit(payload, exit_code=0 if payload.get("ok") else 2)
        if args.cmd == "search_username":
            payload = search_username(
                args.username,
                category=args.category,
                max_sites=args.max_sites,
                timeout=args.timeout,
                workers=args.workers,
            )
            return emit(payload, exit_code=0 if payload.get("ok") else 1)
        return emit({"ok": False, "error": f"unknown command: {args.cmd}"}, exit_code=2)
    except Exception as exc:  # noqa: BLE001
        return emit({"ok": False, "error": str(exc), "command": args.cmd}, exit_code=1)


if __name__ == "__main__":
    raise SystemExit(main())
