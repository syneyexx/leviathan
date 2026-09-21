#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
from urllib.error import URLError
import urllib.parse
import urllib.request


DEFAULT_BASE = "http://127.0.0.1:8080"


def doctor() -> dict:
    from pathlib import Path

    docker = shutil.which("docker") or shutil.which("docker.exe")
    compose = Path(__file__).resolve().parent / "container" / "docker-compose.yml"
    compose_present = compose.is_file()
    ok = bool(docker) and compose_present
    payload = {
        "ok": ok,
        "docker": docker,
        "compose_file": "container/docker-compose.yml",
        "compose_present": compose_present,
        "search_endpoint": f"{DEFAULT_BASE}/search",
        "notes": [
            "start uses docker compose in container/.",
            "Copy/adapt container/.env.example before first start if required by upstream.",
        ],
    }
    if not ok:
        missing = []
        if not docker:
            missing.append("docker")
        if not compose_present:
            missing.append("container/docker-compose.yml")
        payload["error"] = "missing_required:" + ",".join(missing)
    return payload


def search(query: str, language: str, limit: int, base_url: str) -> dict:
    params = urllib.parse.urlencode({"q": query, "format": "json", "language": language})
    url = f"{base_url.rstrip('/')}/search?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "HADES-SearXNG-Plugin/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - operator-local searx
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "query": query,
            "base_url": base_url,
            "count": 0,
            "results": [],
            "unresponsive_engines": [],
            "error": f"searxng request failed: {exc}",
        }
    results = payload.get("results", [])[:limit]
    raw_unresponsive = payload.get("unresponsive_engines") or []
    unresponsive: list[dict] = []
    for item in raw_unresponsive[:20]:
        if isinstance(item, (list, tuple)) and item:
            unresponsive.append({"engine": item[0], "error": item[1] if len(item) > 1 else None})
        elif isinstance(item, dict):
            unresponsive.append(item)
        else:
            unresponsive.append({"engine": str(item)})
    count = len(results)
    # Empty results with dead engines is not a successful search.
    dead_engines_empty = count == 0 and len(unresponsive) > 0
    return {
        "ok": not dead_engines_empty,
        "query": query,
        "base_url": base_url,
        "count": count,
        "results": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": (item.get("content") or "")[:500],
                "engine": item.get("engine"),
            }
            for item in results
        ],
        "unresponsive_engines": unresponsive,
        "error": (
            f"{len(unresponsive)} unresponsive engines; no results"
            if dead_engines_empty
            else None
        ),
        "note": (
            None
            if count or dead_engines_empty
            else "No results from responsive engines (genuine empty hit)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("search")
    s.add_argument("--query", required=True)
    s.add_argument("--language", default="en")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    else:
        payload = search(args.query, args.language, args.limit, args.base_url)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("ok") is False:
        return 2 if payload.get("unresponsive_engines") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
