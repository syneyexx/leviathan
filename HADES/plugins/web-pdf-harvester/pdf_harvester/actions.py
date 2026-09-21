"""Action handlers returned as structured HADES tool results."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .browser import playwright_available
from .cancel import CancelToken
from .crawler import CrawlerEngine
from .downloader import Downloader
from .http_client import HttpClient
from .index import ResourceIndex
from .models import CrawlConfig, ErrorClass, ResourceStatus, utc_now_iso
from .pdf_detect import detect_from_headers, detect_from_magic
from .storage import StoragePaths, atomic_write_json


def _paths_from(data_dir: str | None) -> StoragePaths:
    return StoragePaths(data_dir or "data/pdf_harvester").ensure()


async def action_discover(params: dict[str, Any]) -> dict[str, Any]:
    start_urls = params.get("start_urls") or []
    if isinstance(start_urls, str):
        try:
            start_urls = json.loads(start_urls)
        except json.JSONDecodeError:
            start_urls = [u.strip() for u in start_urls.split(",") if u.strip()]
    if not start_urls:
        return {
            "success": False,
            "action": "discover",
            "error": "start_urls required",
            "error_class": ErrorClass.INVALID_URL.value,
        }
    cfg = CrawlConfig.from_dict({**params, "start_urls": list(start_urls)})
    paths = _paths_from(cfg.data_dir)
    cancel = CancelToken(paths.cancel_flag)
    # Align cancel clearing with the resolved config (defaults to resume=False).
    if not cfg.resume:
        cancel.clear()
    index = ResourceIndex(paths)
    try:
        engine = CrawlerEngine(cfg, index=index, paths=paths, cancel=cancel)
        return await engine.run()
    finally:
        index.close()


async def action_status(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    index = ResourceIndex(paths)
    try:
        session = {}
        if paths.session_stats.exists():
            session = json.loads(paths.session_stats.read_text(encoding="utf-8"))
        crawl_state = {}
        if paths.crawl_state.exists():
            raw = json.loads(paths.crawl_state.read_text(encoding="utf-8"))
            crawl_state = {
                "session_id": raw.get("session_id"),
                "visited": len(raw.get("visited") or []),
                "queued": len(raw.get("queued") or []),
                "updated_at": raw.get("updated_at"),
            }
        counts = index.counts()
        return {
            "success": True,
            "action": "status",
            "session": session,
            "crawl_state": crawl_state,
            "index_counts": counts,
            "size_estimate": index.size_estimate(),
            "index_path": str(paths.resources_jsonl),
            "sqlite_path": str(paths.resources_sqlite),
            "links_export_path": str(paths.pdf_links_txt),
            "cancel_requested": paths.cancel_flag.exists(),
            "playwright_available": playwright_available(),
        }
    finally:
        index.close()


async def action_list(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    index = ResourceIndex(paths)
    try:
        status = params.get("status")
        download_status = params.get("download_status")
        # Convenience filters
        filt = (params.get("filter") or "").strip().lower()
        if filt == "confirmed":
            status = ResourceStatus.CONFIRMED.value
        elif filt == "candidates":
            status = ResourceStatus.CANDIDATE.value
        elif filt == "downloaded":
            download_status = "downloaded"
        elif filt in {"not_downloaded", "not-downloaded"}:
            download_status = "not_downloaded"
        elif filt == "failed":
            download_status = "failed"
        result = index.list(
            status=status,
            download_status=download_status,
            hostname=params.get("hostname"),
            category=params.get("category"),
            search=params.get("search") or params.get("query"),
            offset=int(params.get("offset") or 0),
            limit=int(params.get("limit") or 100),
        )
        return {"success": True, "action": "list", **result}
    finally:
        index.close()


async def action_download_selected(params: dict[str, Any]) -> dict[str, Any]:
    ids = params.get("resource_ids") or []
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except json.JSONDecodeError:
            ids = [x.strip() for x in ids.split(",") if x.strip()]
    if not ids:
        return {
            "success": False,
            "action": "download_selected",
            "error": "resource_ids required",
            "error_class": ErrorClass.INVALID_URL.value,
        }
    paths = _paths_from(params.get("data_dir"))
    cancel = CancelToken(paths.cancel_flag)
    cancel.clear()
    index = ResourceIndex(paths)
    try:
        dl = Downloader(
            index=index,
            paths=paths,
            cancel=cancel,
            concurrency=int(params.get("download_concurrency") or 3),
            allow_private=bool(params.get("allow_private_hosts") or False),
        )
        result = await dl.download_ids([str(x) for x in ids])
        result["action"] = "download_selected"
        return result
    finally:
        index.close()


async def action_download_all(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    cancel = CancelToken(paths.cancel_flag)
    cancel.clear()
    index = ResourceIndex(paths)
    try:
        # Always report estimate first in the result; never auto-run from discover.
        estimate = index.size_estimate()
        if params.get("estimate_only"):
            return {
                "success": True,
                "action": "download_all",
                "estimate_only": True,
                "size_estimate": estimate,
                "index_counts": index.counts(),
            }
        dl = Downloader(
            index=index,
            paths=paths,
            cancel=cancel,
            concurrency=int(params.get("download_concurrency") or 3),
            allow_private=bool(params.get("allow_private_hosts") or False),
        )
        result = await dl.download_all()
        result["action"] = "download_all"
        return result
    finally:
        index.close()


async def action_resume_downloads(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    cancel = CancelToken(paths.cancel_flag)
    cancel.clear()
    index = ResourceIndex(paths)
    try:
        dl = Downloader(
            index=index,
            paths=paths,
            cancel=cancel,
            concurrency=int(params.get("download_concurrency") or 3),
            allow_private=bool(params.get("allow_private_hosts") or False),
        )
        result = await dl.resume_downloads()
        result["action"] = "resume_downloads"
        return result
    finally:
        index.close()


async def action_verify(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    index = ResourceIndex(paths)
    try:
        ids = params.get("resource_ids")
        if isinstance(ids, str):
            try:
                ids = json.loads(ids)
            except json.JSONDecodeError:
                ids = [x.strip() for x in ids.split(",") if x.strip()]
        if ids:
            records = [index.get(str(i)) for i in ids]
            records = [r for r in records if r is not None]
        else:
            records = index.all_confirmed()
            if params.get("include_candidates"):
                listed = index.list(status="candidate", limit=10_000)
                from .models import ResourceRecord

                records.extend(ResourceRecord.from_dict(item) for item in listed["items"])

        checked = []
        async with HttpClient(allow_private=bool(params.get("allow_private_hosts") or False)) as http:
            for record in records:
                if CancelToken(paths.cancel_flag).is_cancelled():
                    break
                url = record.final_url or record.normalized_url
                result = await http.fetch(url, read_body=False, probe_pdf=True)
                ok = bool(result.detection and result.detection.is_pdf)
                if ok:
                    record.status = ResourceStatus.CONFIRMED.value
                    record.verified_at = utc_now_iso()
                    record.mime_type = result.detection.mime_type if result.detection else record.mime_type
                    record.content_length = (
                        result.detection.content_length if result.detection else record.content_length
                    )
                    record.final_url = result.final_url
                    record.redirect_chain = result.redirect_chain
                    record.error = None
                else:
                    record.error = result.error or "not a PDF"
                    record.error_class = result.error_class or ErrorClass.PDF_VALIDATION_FAILED.value
                index.upsert(record)
                checked.append({"id": record.id, "ok": ok, "final_url": result.final_url, "error": record.error})
        exports = index.export_jsonl_and_links()
        confirmed_ok = sum(1 for c in checked if c["ok"])
        return {
            "success": confirmed_ok > 0 if checked else False,
            "action": "verify",
            "checked": len(checked),
            "confirmed_ok": confirmed_ok,
            "results": checked,
            **exports,
        }
    finally:
        index.close()


async def action_cancel(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    cancel = CancelToken(paths.cancel_flag)
    cancel.cancel(params.get("reason") or "user_cancel")
    return {"success": True, "action": "cancel", "cancel_flag": str(paths.cancel_flag)}


async def action_health(params: dict[str, Any]) -> dict[str, Any]:
    paths = _paths_from(params.get("data_dir"))
    try:
        import httpx  # noqa: F401

        httpx_ok = True
    except Exception:
        httpx_ok = False
    return {
        "success": httpx_ok,
        "action": "health",
        "httpx": httpx_ok,
        "playwright": playwright_available(),
        "data_dir": str(paths.root),
        "writable": paths.root.exists(),
    }


ACTION_MAP = {
    "discover": action_discover,
    "status": action_status,
    "list": action_list,
    "download_selected": action_download_selected,
    "download_all": action_download_all,
    "resume_downloads": action_resume_downloads,
    "verify": action_verify,
    "cancel": action_cancel,
    "health": action_health,
}


async def dispatch(action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTION_MAP.get(action)
    if not handler:
        return {
            "success": False,
            "action": action,
            "error": f"Unknown action: {action}",
            "error_class": ErrorClass.INVALID_URL.value,
            "known_actions": sorted(ACTION_MAP),
        }
    return await handler(params)


def run_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(dispatch(action, params))
