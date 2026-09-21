
"""Facebook Page Reels adapter (official Graph video_reels flow).

Verified 2026-09-14:
- Graph v26.0 /{page-id}/video_reels upload_phase=start|finish
- Page access token + pages_show_list, pages_read_engagement, pages_manage_posts
- Personal profile publishing is NOT supported via current Page Reels API
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from media.models import CapabilityTruth
from media.platforms.base import MediaPlatformAdapter
from media.platforms.meta_auth import META_GRAPH_BASE, MetaAuthState, redact_meta_error

HttpClient = Callable[..., dict[str, Any]]
RUPLOAD_BASE = "https://rupload.facebook.com/video-upload"


class FacebookAdapter(MediaPlatformAdapter):
    platform = "facebook"

    def __init__(self, *, auth: MetaAuthState | None = None, http: HttpClient | None = None) -> None:
        self.auth = auth or MetaAuthState()
        self.http = http

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "api": f"Facebook Page Reels {META_GRAPH_BASE}",
            "supports": ["page_reels", "upload_session", "page_insights"],
            "personal_profile_publishing": False,
            "requires": "PAGE_REQUIRED",
        }

    def auth_status(self) -> dict[str, Any]:
        status = self.auth.status_for("facebook")
        return {"ok": status["status"] == CapabilityTruth.READY.value, **status}

    def publish(self, job: dict[str, Any], variant: dict[str, Any], *, consent: dict[str, Any] | None = None) -> dict[str, Any]:
        auth = self.auth_status()
        if auth.get("status") in {CapabilityTruth.AUTH_REQUIRED.value, CapabilityTruth.PAGE_REQUIRED.value}:
            return {"ok": False, **auth}
        page_id = self.auth.page_id()
        token = self.auth.page_token()
        meta = variant.get("metadata") or {}
        path = Path(str(meta.get("render_path") or ""))
        description = str(meta.get("description") or meta.get("caption") or meta.get("title") or "")
        title = str(meta.get("title") or "")
        if self.http is None or not page_id or not token:
            return {
                "ok": False,
                "status": CapabilityTruth.UNVERIFIED_ON_HOST.value,
                "detail": "Prepared Page Reels session; live HTTP not bound.",
                "prepared": {
                    "start": f"{META_GRAPH_BASE}/{page_id}/video_reels",
                    "upload_phase": "start",
                },
            }
        start = self.http(
            "POST",
            f"{META_GRAPH_BASE}/{page_id}/video_reels",
            json={"upload_phase": "start", "access_token": token},
        )
        video_id = (start or {}).get("video_id")
        upload_url = (start or {}).get("upload_url") or (f"{RUPLOAD_BASE}/v26.0/{video_id}" if video_id else None)
        if not video_id or not upload_url:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "reels_start_failed", "raw": redact_meta_error(start)}
        if not path.exists():
            file_url = (consent or {}).get("file_url") or meta.get("public_url")
            if not file_url:
                return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "render_or_file_url_required"}
            # Hosted upload path when supported by caller-provided URL.
            upload = self.http("POST", upload_url, headers={"Authorization": f"OAuth {token}"}, params={"file_url": file_url})
        else:
            data = path.read_bytes()
            upload = self.http(
                "POST",
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(len(data)),
                    "Content-Type": "application/octet-stream",
                },
                content=data,
            )
        finish = self.http(
            "POST",
            f"{META_GRAPH_BASE}/{page_id}/video_reels",
            params={
                "access_token": token,
                "video_id": video_id,
                "upload_phase": "finish",
                "video_state": (consent or {}).get("video_state") or "PUBLISHED",
                "description": description,
                "title": title,
            },
        )
        post_id = (finish or {}).get("post_id") or video_id
        ok = bool((finish or {}).get("success") or post_id)
        return {
            "ok": ok,
            "status": "PUBLISHED" if ok else "FAILED",
            "external_upload_id": video_id,
            "external_post_id": post_id,
            "upload": redact_meta_error(upload),
            "raw": redact_meta_error(finish),
        }

    def fetch_metrics(self, external_post_id: str) -> dict[str, Any]:
        token = self.auth.page_token()
        if not token or self.http is None:
            return {"ok": False, "status": CapabilityTruth.UNVERIFIED_ON_HOST.value, "metrics": None}
        result = self.http(
            "GET",
            f"{META_GRAPH_BASE}/{external_post_id}/video_insights",
            params={"metric": "total_video_views,total_video_impressions", "access_token": token},
        )
        data = (result or {}).get("data")
        if data is None:
            return {
                "ok": False,
                "status": CapabilityTruth.PLATFORM_LIMITATION.value,
                "metrics": None,
                "unsupported": True,
                "detail": "Page video insights unavailable for this object/token.",
            }
        metrics = {}
        for item in data or []:
            name = item.get("name")
            values = item.get("values") or []
            metrics[name] = values[0].get("value") if values else None
        return {"ok": True, "status": CapabilityTruth.READY.value, "metrics": metrics}
