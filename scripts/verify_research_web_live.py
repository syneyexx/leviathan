#!/usr/bin/env python3
"""Live web research smoke verifier (W118).

Requires outbound network. Does NOT run in normal CI.
Exit non-zero with actionable diagnosis when web research is not operational.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "Data"
if str(DATA) not in sys.path:
    sys.path.insert(0, str(DATA))


def _print_diag(lines: list[str]) -> None:
    for line in lines:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="LEVIATHAN live web research verifier")
    parser.add_argument(
        "--query",
        default="SQLite WAL mode and Python sqlite3 concurrency",
        help="Harmless public search query",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    args = parser.parse_args()

    diag: list[str] = []
    summary: dict = {
        "status": "FAIL",
        "outbound": None,
        "discovery": None,
        "provider": None,
        "direct_fetch": None,
        "source_count": 0,
        "evidence_count": 0,
        "action": None,
        "error": None,
    }

    try:
        from Data.backend.config import Settings
        from Data.modules.research.service import ResearchService
        from Data.modules.research.web_readiness import build_web_readiness
    except Exception as exc:  # noqa: BLE001
        _print_diag([f"IMPORT_FAILED: {exc}", traceback.format_exc()])
        return 2

    settings = Settings.from_env()
    allow = bool(settings.network.allow_outbound)
    endpoint = settings.research_integration.web_search_endpoint
    mode = getattr(settings.research_integration, "web_search_mode", "auto")
    summary["outbound"] = "READY" if allow else "DISABLED"
    diag.append(f"OUTBOUND: {summary['outbound']}")
    diag.append(f"SEARCH_MODE: {mode}")
    diag.append(f"ENDPOINT_CONFIGURED: {bool(endpoint)}")

    if not allow:
        summary["discovery"] = "SKIPPED"
        summary["direct_fetch"] = "DISABLED"
        summary["action"] = "Enable LEVIATHAN_NETWORK_ALLOW_OUTBOUND=true"
        summary["error"] = "outbound_network_disabled"
        _print_diag(diag + ["DISCOVERY: SKIPPED", "ACTION: " + summary["action"]])
        if args.json:
            print(json.dumps(summary, indent=2))
        return 1

    with tempfile.TemporaryDirectory(prefix="lev_web_live_") as tmp:
        db_path = Path(tmp) / "research_live.db"
        service = ResearchService.from_settings(settings, db_path=db_path, knowledge=None)
        readiness = build_web_readiness(
            allow_outbound=service.allow_outbound,
            provider=service.web,
            search_endpoint=endpoint,
            api_key_configured=bool(
                (settings.research_integration.web_search_api_key or "").strip()
            ),
            search_mode=str(mode or "auto"),
        )
        summary["provider"] = readiness.provider_type
        summary["direct_fetch"] = "READY" if readiness.direct_fetch_available else "UNAVAILABLE"
        diag.append(f"PROVIDER: {readiness.provider_type}")
        diag.append(f"DIRECT FETCH: {summary['direct_fetch']}")
        diag.append(f"READINESS: {readiness.operator_summary}")

        if not readiness.search_available:
            summary["discovery"] = "FAILED"
            summary["error"] = ",".join(readiness.reason_codes) or "search_unavailable"
            summary["action"] = (
                "configure SearxNG/Brave endpoint or set LEVIATHAN_WEB_SEARCH_MODE=auto"
            )
            _print_diag(
                diag
                + [
                    "DISCOVERY: FAILED",
                    f"ERROR: {summary['error']}",
                    "ACTION: " + summary["action"],
                ]
            )
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

        try:
            results = service.web.search(args.query, limit=5)
        except Exception as exc:  # noqa: BLE001
            summary["discovery"] = "FAILED"
            summary["error"] = str(exc)[:300]
            summary["action"] = (
                "configure SearxNG/Brave endpoint or inspect provider restriction"
            )
            _print_diag(
                diag
                + [
                    "DISCOVERY: FAILED",
                    f"ERROR: {summary['error']}",
                    f"DIRECT FETCH: {summary['direct_fetch']}",
                    "ACTION: " + summary["action"],
                ]
            )
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

        https = [r for r in results if r.url.startswith("https://")]
        summary["discovery"] = "OK" if https else "FAILED"
        diag.append(f"DISCOVERY: {summary['discovery']} ({len(results)} hits, {len(https)} https)")
        if not https:
            summary["error"] = "no_https_results"
            summary["action"] = "inspect provider restriction / try different query"
            _print_diag(diag + ["ERROR: no HTTPS results", "ACTION: " + summary["action"]])
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

        project = service.create_project(
            topic=args.query,
            objective="Live web research verifier (isolated; disposable)",
            depth="quick",
            allow_web=True,
            seed_sources=[],
        )
        # Direct path: search → fetch → ingest → evidence (same chain as coordinator).
        from Data.modules.research.sources import SourceIngestor
        from Data.modules.research.evidence import EvidenceLedger

        sources = SourceIngestor(service.store, service.snapshots_root)
        ledger = EvidenceLedger(service.store)
        fetched = 0
        for rank, hit in enumerate(https[:3], start=1):
            discovered = sources.from_web_search(
                project.project_id, hit, query=args.query, rank=rank
            )
            try:
                page = service.web.fetch_page(hit.url, respect_robots_txt=True)
            except Exception as exc:  # noqa: BLE001
                sources.mark_discovery_unverified(
                    discovered, retrieval_status="fetch_failed", error=str(exc)
                )
                diag.append(f"FETCH_FAIL[{rank}]: {hit.url} — {exc}")
                continue
            source, content = sources.from_web_page(
                project.project_id,
                page,
                discovery=discovered,
                query=args.query,
                rank=rank,
            )
            fetched += 1
            # Extract simple evidence spans from content.
            text = (content or "").strip()
            if len(text) >= 40:
                span = text[:400]
                ledger.add_span(
                    project_id=project.project_id,
                    source_id=source.source_id,
                    span_text=span,
                    retrieval_method="web_fetch_live_verifier",
                    metadata={"url": page.canonical_url, "query": args.query},
                )
            diag.append(
                f"FETCH_OK[{rank}]: {page.canonical_url} status={page.status_code} chars={len(text)}"
            )

        refreshed = service.get_project(project.project_id)
        source_count = len(service.store.list_sources(project.project_id))
        evidence_count = len(service.store.list_evidence(project.project_id))
        # Prefer project counters when refreshed.
        summary["source_count"] = getattr(refreshed, "source_count", source_count) or source_count
        summary["evidence_count"] = (
            getattr(refreshed, "evidence_count", evidence_count) or evidence_count
        )
        diag.append(f"SOURCES: {summary['source_count']} (fetched_ok={fetched})")
        diag.append(f"EVIDENCE: {summary['evidence_count']}")

        if fetched < 1 or summary["source_count"] < 1:
            summary["status"] = "FAIL"
            summary["error"] = "no_pages_fetched"
            summary["action"] = "inspect robots/SSRF/network blocks on result URLs"
            _print_diag(diag + ["ERROR: " + summary["error"], "ACTION: " + summary["action"]])
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1
        if summary["evidence_count"] < 1:
            summary["status"] = "FAIL"
            summary["error"] = "no_evidence_extracted"
            summary["action"] = "fetched pages were empty/unreadable"
            _print_diag(diag + ["ERROR: " + summary["error"], "ACTION: " + summary["action"]])
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

        # Citation / URL integrity: evidence → source → real URL
        evidence = service.store.list_evidence(project.project_id)[0]
        src = service.store.get_source(evidence.source_id)
        if src is None or not (src.canonical_uri or src.original_uri or "").startswith("http"):
            summary["status"] = "FAIL"
            summary["error"] = "citation_source_url_missing"
            summary["action"] = "inspect SourceIngestor provenance"
            _print_diag(diag + ["ERROR: " + summary["error"], "ACTION: " + summary["action"]])
            if args.json:
                print(json.dumps(summary, indent=2))
            return 1

        summary["status"] = "PASS"
        diag.append("CITATION: OK → " + (src.canonical_uri or src.original_uri or ""))
        diag.append("LIVE WEB RESEARCH: PASS")
        _print_diag(diag)
        if args.json:
            print(json.dumps(summary, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
