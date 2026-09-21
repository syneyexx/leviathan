#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from site_discovery import discover_sources

from news_core import HARD_SOURCE_CAP, PLUGIN_ID, balanced, load_catalog, save_seen, seen_ids, upload_hades
from pipeline_v12 import VERSION, collect, save_seen_urls, write_outputs


def yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def csv(value: str) -> set[str] | None:
    result = {x.strip().casefold() for x in (value or "").split(",") if x.strip()}
    return result or None


def state_dir(value: str = "") -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = os.getenv("HADES_PLUGIN_DATA_DIR") or os.getenv("HADES_DATA_DIR") or str(Path.cwd())
    return Path(root).expanduser().resolve() / ".ultimate-news-feeder"


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--output-dir", default="news-output")
    parser.add_argument("--max-sources", type=int, default=300)
    parser.add_argument("--max-articles", type=int, default=1000)
    parser.add_argument("--per-source", type=int, default=8)
    parser.add_argument("--since-hours", type=float, default=36)
    parser.add_argument("--timeout-seconds", type=float, default=15)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--article-workers", type=int, default=12)
    parser.add_argument("--refresh-sources", default="false")
    parser.add_argument("--regions", default="")
    parser.add_argument("--countries", default="")
    parser.add_argument("--languages", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--new-only", default="true")
    parser.add_argument("--crawl-pages", default="true")
    parser.add_argument("--max-article-chars", type=int, default=6000)
    parser.add_argument("--respect-robots", default="true")
    parser.add_argument("--allow-google-fallback", default="true")
    parser.add_argument("--discover-sites", default="true")
    parser.add_argument("--discovery-sites", type=int, default=150)
    parser.add_argument("--discovery-urls-per-site", type=int, default=6)
    parser.add_argument("--discovery-workers", type=int, default=12)
    parser.add_argument("--story-clustering", default="true")


def run_collect(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if not 1 <= args.max_sources <= HARD_SOURCE_CAP:
        raise ValueError(f"max_sources must be 1..{HARD_SOURCE_CAP}")
    if not 1 <= args.max_articles <= 50_000 or not 1 <= args.per_source <= 100:
        raise ValueError("article limits out of range")
    if not 500 <= args.max_article_chars <= 15_000:
        raise ValueError("max_article_chars must be 500..15000")
    root = state_dir(args.state_dir)
    payload = collect(
        root,
        args.max_sources,
        args.max_articles,
        args.per_source,
        args.since_hours,
        max(1, min(args.timeout_seconds, 120)),
        max(1, min(args.workers, 32)),
        yes(args.refresh_sources),
        csv(args.regions),
        csv(args.countries),
        csv(args.languages),
        args.query.strip(),
        yes(args.new_only),
        crawl_pages=yes(args.crawl_pages),
        article_workers=max(1, min(args.article_workers, 32)),
        max_article_chars=args.max_article_chars,
        respect_robots=yes(args.respect_robots),
        allow_google_fallback=yes(args.allow_google_fallback),
        discover_sites=yes(args.discover_sites),
        discovery_sites=max(1, min(args.discovery_sites, HARD_SOURCE_CAP)),
        discovery_urls_per_site=max(1, min(args.discovery_urls_per_site, 50)),
        discovery_workers=max(1, min(args.discovery_workers, 32)),
        story_clustering=yes(args.story_clustering),
    )
    return payload, root


def cmd_fetch(args: argparse.Namespace) -> int:
    payload, root = run_collect(args)
    payload["outputs"] = write_outputs(payload, Path(args.output_dir).expanduser().resolve())
    if yes(args.new_only):
        ids = seen_ids(root)
        ids.update(a["id"] for a in payload["articles"])
        save_seen(root, ids)
        save_seen_urls(root, {(a.get("canonical_url") or a.get("url") or "") for a in payload["articles"]})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["health"]["succeeded"] else 2


def cmd_feed(args: argparse.Namespace) -> int:
    payload, root = run_collect(args)
    succeeded = int((payload.get("health") or {}).get("succeeded") or 0)
    if not payload["articles"]:
        # Soft empty is only honest when at least one source answered successfully.
        if succeeded <= 0:
            print(
                json.dumps(
                    {
                        **payload,
                        "ok": False,
                        "error": "no_articles_and_no_successful_sources",
                        "ingest": {"skipped": True, "reason": "all sources failed or empty"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps({**payload, "ok": True, "ingest": {"skipped": True, "reason": "no new articles"}}, ensure_ascii=False, indent=2))
        return 0
    outputs = write_outputs(payload, Path(args.output_dir).expanduser().resolve())
    ingest = upload_hades(Path(outputs["markdown"]), args.hades_api_url, yes(args.approved_file_write), args.timeout_seconds)
    ids = seen_ids(root)
    ids.update(a["id"] for a in payload["articles"])
    save_seen(root, ids)
    save_seen_urls(root, {(a.get("canonical_url") or a.get("url") or "") for a in payload["articles"]})
    ingest_ok = bool(ingest) and not ingest.get("error") and (
        ingest.get("ok") is True
        or ingest.get("id")
        or ingest.get("document_id")
        or ingest.get("path")
        or ingest.get("file_id")
    )
    if not ingest_ok:
        print(json.dumps({**payload, "ok": False, "error": "ingest_failed", "outputs": outputs, "ingest": ingest}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({**payload, "ok": True, "outputs": outputs, "ingest": ingest}, ensure_ascii=False, indent=2))
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    sources, stats = load_catalog(state_dir(args.state_dir), yes(args.refresh_sources), args.timeout_seconds)
    selected = balanced(
        sources,
        args.max_sources,
        csv(args.regions),
        csv(args.countries),
        csv(args.languages),
        yes(args.allow_google_fallback),
    )
    result = {
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "hard_source_cap": HARD_SOURCE_CAP,
        "catalog_stats": stats,
        "loaded_sources": len(sources),
        "selected_sources": len(selected),
        "by_region": dict(sorted(Counter(s.region for s in sources).items())),
        "by_country": dict(sorted(Counter(s.country_code for s in sources).items())),
        "by_kind": dict(sorted(Counter(s.kind for s in sources).items())),
        "sources": [s.__dict__ for s in selected[:args.show]],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    sources, _stats = load_catalog(state_dir(args.state_dir), yes(args.refresh_sources), args.timeout_seconds)
    selected = balanced(sources, args.max_sources, None, None, None, allow_google_fallback=False)
    result = discover_sources(
        selected,
        user_agent=f"HADES-{PLUGIN_ID}/{VERSION}",
        timeout=args.timeout_seconds,
        max_sites=args.discovery_sites,
        max_urls_per_site=args.discovery_urls_per_site,
        workers=args.discovery_workers,
        respect_robots=yes(args.respect_robots),
    )
    rows = []
    for row in result.pop("rows", []):
        rows.append({
            "source": getattr(row.get("source"), "name", ""),
            "home_url": getattr(row.get("source"), "home_url", ""),
            "items": [item.to_dict() for item in row.get("items", [])],
            "error": row.get("error", ""),
        })
    result["sites"] = rows[:args.show_sites]
    print(json.dumps({"plugin": PLUGIN_ID, "version": VERSION, "discovery": result}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Worldwide news feeder and article crawler for HADES Knowledge")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("fetch"); common(a); a.set_defaults(func=cmd_fetch)
    a = sub.add_parser("feed-hades"); common(a); a.add_argument("--hades-api-url", default=os.getenv("HADES_API_URL", "http://127.0.0.1:8000/api")); a.add_argument("--approved-file-write", default="false"); a.set_defaults(func=cmd_feed)
    a = sub.add_parser("sources"); a.add_argument("--state-dir", default=""); a.add_argument("--max-sources", type=int, default=300); a.add_argument("--refresh-sources", default="false"); a.add_argument("--timeout-seconds", type=float, default=15); a.add_argument("--regions", default=""); a.add_argument("--countries", default=""); a.add_argument("--languages", default=""); a.add_argument("--allow-google-fallback", default="true"); a.add_argument("--show", type=int, default=25); a.set_defaults(func=cmd_sources)
    a = sub.add_parser("discover-sites"); a.add_argument("--state-dir", default=""); a.add_argument("--max-sources", type=int, default=300); a.add_argument("--refresh-sources", default="false"); a.add_argument("--timeout-seconds", type=float, default=15); a.add_argument("--discovery-sites", type=int, default=150); a.add_argument("--discovery-urls-per-site", type=int, default=6); a.add_argument("--discovery-workers", type=int, default=12); a.add_argument("--respect-robots", default="true"); a.add_argument("--show-sites", type=int, default=20); a.set_defaults(func=cmd_discover)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print(json.dumps({"plugin": PLUGIN_ID, "status": "cancelled"}))
        return 130
    except Exception as exc:
        print(json.dumps({"plugin": PLUGIN_ID, "status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
