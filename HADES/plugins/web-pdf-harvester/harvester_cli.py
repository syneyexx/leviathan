#!/usr/bin/env python3
"""CLI entrypoint for the HADES Web PDF Harvester plugin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running from plugin root without install.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_harvester.actions import run_action  # noqa: E402
from pdf_harvester.models import CrawlConfig  # noqa: E402


def _parse_json_maybe(value: str | None) -> Any:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text[0] in "[{":
        return json.loads(text)
    return text


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HADES Web PDF Harvester")
    sub = parser.add_subparsers(dest="action", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--data-dir", default="data/pdf_harvester")
        p.add_argument("--allow-private-hosts", default="false")
        p.add_argument("--input-json", default="", help="Optional JSON object merged into params")

    discover = sub.add_parser("discover", help="Crawl and index PDF resources without downloading bodies")
    add_common(discover)
    discover.add_argument("--start-urls", required=True, help="JSON array or comma-separated URLs")
    discover.add_argument("--max-depth", type=int, default=6)
    discover.add_argument("--max-pages", type=int, default=5000)
    discover.add_argument("--max-external-hops", type=int, default=3)
    discover.add_argument("--max-concurrent-requests", type=int, default=8)
    discover.add_argument("--max-browser-pages", type=int, default=2)
    discover.add_argument("--request-timeout-seconds", type=float, default=30)
    discover.add_argument("--browser-timeout-seconds", type=float, default=45)
    discover.add_argument("--rate-limit-ms", type=int, default=750)
    discover.add_argument("--max-retries", type=int, default=3)
    discover.add_argument("--respect-robots-txt", default="true")
    discover.add_argument("--same-domain-first", default="true")
    discover.add_argument("--allow-external-resource-hosts", default="true")
    discover.add_argument("--verify-pdf-headers", default="true")
    discover.add_argument("--resume", default="false")
    discover.add_argument("--use-browser", default="true")

    status = sub.add_parser("status", help="Show crawl/index status")
    add_common(status)

    listing = sub.add_parser("list", help="List discovered resources")
    add_common(listing)
    listing.add_argument("--filter", default="")
    listing.add_argument("--status", default="")
    listing.add_argument("--download-status", default="")
    listing.add_argument("--hostname", default="")
    listing.add_argument("--category", default="")
    listing.add_argument("--search", default="")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=100)

    dl_sel = sub.add_parser("download_selected", help="Download specific resource ids")
    add_common(dl_sel)
    dl_sel.add_argument("--resource-ids", required=True, help="JSON array or comma-separated ids")
    dl_sel.add_argument("--download-concurrency", type=int, default=3)

    dl_all = sub.add_parser("download_all", help="Download all confirmed not-yet-downloaded resources")
    add_common(dl_all)
    dl_all.add_argument("--download-concurrency", type=int, default=3)
    dl_all.add_argument("--estimate-only", default="false")

    resume = sub.add_parser("resume_downloads", help="Resume failed/partial downloads")
    add_common(resume)
    resume.add_argument("--download-concurrency", type=int, default=3)

    verify = sub.add_parser("verify", help="Revalidate discovered URLs without full download")
    add_common(verify)
    verify.add_argument("--resource-ids", default="")
    verify.add_argument("--include-candidates", default="false")

    cancel = sub.add_parser("cancel", help="Request cancellation of an active crawl/download")
    add_common(cancel)
    cancel.add_argument("--reason", default="user_cancel")

    health = sub.add_parser("health", help="Plugin health check")
    add_common(health)

    run = sub.add_parser("run", help="Dispatch a JSON action payload")
    run.add_argument("--payload", required=True, help="JSON object including action field")

    return parser


def params_from_args(args: argparse.Namespace) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if getattr(args, "input_json", ""):
        data.update(json.loads(args.input_json))
    mapping = vars(args).copy()
    mapping.pop("action", None)
    mapping.pop("input_json", None)
    mapping.pop("payload", None)
    for key, value in mapping.items():
        if value is None or value == "":
            continue
        norm = key.replace("-", "_")
        if norm in {
            "respect_robots_txt", "same_domain_first", "allow_external_resource_hosts",
            "verify_pdf_headers", "resume", "use_browser", "allow_private_hosts",
            "estimate_only", "include_candidates",
        }:
            data[norm] = _bool(value)
        elif norm in {"start_urls", "resource_ids"}:
            parsed = _parse_json_maybe(str(value))
            if isinstance(parsed, list):
                data[norm] = parsed
            elif isinstance(parsed, str):
                data[norm] = [x.strip() for x in parsed.split(",") if x.strip()]
            else:
                data[norm] = parsed
        else:
            data[norm] = value
    return data


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            payload = json.loads(args.payload)
            action = str(payload.pop("action"))
            result = run_action(action, payload)
        else:
            result = run_action(args.action, params_from_args(args))
    except Exception as exc:
        result = {"success": False, "action": getattr(args, "action", None), "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("cancelled"):
        return 130
    return 0 if result.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
