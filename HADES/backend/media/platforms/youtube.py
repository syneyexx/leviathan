
"""YouTube Data API v3 adapter (official)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from media.models import CapabilityTruth
from media.platforms.base import MediaPlatformAdapter

YOUTUBE_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

HttpClient = Callable[..., dict[str, Any]]


class YouTubeAdapter(MediaPlatformAdapter):
    platform = "youtube"

    def __init__(self, *, access_token: str | None = None, http: HttpClient | None = None, channel_id: str | None = None) -> None:
        self.access_token = access_token
        self.http = http
        self.channel_id = channel_id

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "api": "YouTube Data API v3",
            "supports": [
                "oauth",
                "videos.insert",
                "resumable_upload",
                "thumbnails",
                "status.privacyStatus",
                "snippet",
                "YOUTUBE_SHORT",
                "YOUTUBE_LONG",
            ],
            "analytics": "YouTube Analytics API when authorized (separate)",
        }

    def auth_status(self) -> dict[str, Any]:
        if not self.access_token:
            return {
                "ok": False,
                "status": CapabilityTruth.AUTH_REQUIRED.value,
                "detail": "YouTube OAuth token missing.",
                "remediation": "Authorize YouTube Data API OAuth in Media → Setup.",
            }
        return {
            "ok": True,
            "status": CapabilityTruth.READY.value,
            "detail": f"Token present{'; channel ' + self.channel_id if self.channel_id else ''} (live call not verified).",
            "channel_id": self.channel_id,
        }

    def publish(self, job: dict[str, Any], variant: dict[str, Any], *, consent: dict[str, Any] | None = None) -> dict[str, Any]:
        auth = self.auth_status()
        if not auth.get("ok"):
            return {"ok": False, **auth}
        meta = variant.get("metadata") or {}
        path = Path(str(meta.get("render_path") or ""))
        if not path.exists():
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "render_missing"}
        privacy = (consent or {}).get("privacy_status") or meta.get("privacy_status") or "private"
        snippet = {
            "title": str(meta.get("title") or "HADES media")[:100],
            "description": str(meta.get("description") or "")[:5000],
            "tags": list(meta.get("tags") or [])[:20],
            "categoryId": str(meta.get("category_id") or "22"),
        }
        status = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(meta.get("made_for_kids", False)),
        }
        if self.http is None:
            return {
                "ok": False,
                "status": CapabilityTruth.UNVERIFIED_ON_HOST.value,
                "detail": "HTTP client not bound — resumable upload path prepared only.",
                "prepared": {"snippet": snippet, "status": status, "bytes": path.stat().st_size},
            }
        # Resumable upload init
        init = self.http(
            "POST",
            f"{YOUTUBE_UPLOAD}?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(path.stat().st_size),
                "X-Upload-Content-Type": "video/*",
            },
            json={"snippet": snippet, "status": status},
        )
        upload_url = (init or {}).get("headers", {}).get("location") or (init or {}).get("upload_url")
        if not upload_url:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "resumable_init_failed", "raw": _redact(init)}
        put = self.http(
            "PUT",
            upload_url,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "video/*"},
            content=path.read_bytes(),
        )
        video_id = ((put or {}).get("id") or ((put or {}).get("data") or {}).get("id"))
        return {
            "ok": bool(video_id),
            "status": "PUBLISHED" if video_id else "PROCESSING",
            "external_post_id": video_id,
            "external_upload_id": video_id,
            "raw": _redact(put),
        }

    def fetch_metrics(self, external_post_id: str) -> dict[str, Any]:
        if not self.access_token or self.http is None:
            return {"ok": False, "status": CapabilityTruth.UNVERIFIED_ON_HOST.value, "metrics": None, "unsupported": False}
        result = self.http(
            "GET",
            f"{YOUTUBE_API}/videos",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params={"part": "statistics", "id": external_post_id},
        )
        items = (result or {}).get("items") or []
        if not items:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "metrics": None}
        stats = items[0].get("statistics") or {}
        # Unsupported fields remain absent (None), never coerced to 0 unless API returned them.
        metrics = {
            "views": _maybe_int(stats.get("viewCount")),
            "likes": _maybe_int(stats.get("likeCount")),
            "comments": _maybe_int(stats.get("commentCount")),
            "favorites": _maybe_int(stats.get("favoriteCount")),
        }
        return {"ok": True, "status": CapabilityTruth.READY.value, "metrics": metrics, "raw": _redact(result)}


def _maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _redact(payload: Any) -> Any:
    return str(payload).replace("Bearer ", "Bearer [REDACTED]")[:800]
