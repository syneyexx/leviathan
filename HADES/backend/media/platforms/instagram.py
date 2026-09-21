
"""Instagram Reels publishing adapter (official Meta Instagram APIs).

Verified 2026-09-14:
- Graph version v26.0
- Container create → poll status_code → media_publish
- Instagram Login scopes: instagram_business_basic / instagram_business_content_publish
- Facebook Page not required for Instagram Login path
"""

from __future__ import annotations

from typing import Any, Callable

from media.models import CapabilityTruth
from media.platforms.base import MediaPlatformAdapter
from media.platforms.meta_auth import INSTAGRAM_GRAPH_BASE, MetaAuthState, redact_meta_error

HttpClient = Callable[..., dict[str, Any]]


class InstagramAdapter(MediaPlatformAdapter):
    platform = "instagram"

    def __init__(self, *, auth: MetaAuthState | None = None, http: HttpClient | None = None) -> None:
        self.auth = auth or MetaAuthState()
        self.http = http

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "api": f"Instagram Graph {INSTAGRAM_GRAPH_BASE}",
            "supports": ["reels_container", "media_publish", "insights_when_authorized", "instagram_login", "facebook_login"],
            "page_required_for_instagram_login": False,
            "scopes_instagram_login": list(__import__("media.platforms.meta_auth", fromlist=["IG_LOGIN_SCOPES"]).IG_LOGIN_SCOPES),
        }

    def auth_status(self) -> dict[str, Any]:
        status = self.auth.status_for("instagram")
        return {"ok": status["status"] in {CapabilityTruth.READY.value, CapabilityTruth.APP_REVIEW_REQUIRED.value}, **status}

    def publish(self, job: dict[str, Any], variant: dict[str, Any], *, consent: dict[str, Any] | None = None) -> dict[str, Any]:
        auth = self.auth_status()
        if auth.get("status") == CapabilityTruth.AUTH_REQUIRED.value:
            return {"ok": False, **auth}
        if auth.get("status") == CapabilityTruth.APP_REVIEW_REQUIRED.value and not (consent or {}).get("allow_dev_mode"):
            return {"ok": False, **auth}

        ig_user_id = self.auth.ig_user_id()
        token = self.auth.user_token("instagram")
        meta = variant.get("metadata") or {}
        video_url = (consent or {}).get("video_url") or meta.get("public_url")
        caption = str(meta.get("caption") or meta.get("title") or "")[:2200]
        if not video_url:
            return {
                "ok": False,
                "status": CapabilityTruth.FAILED.value,
                "detail": "Instagram Reels container requires a publicly reachable video_url (or resumable FB Login upload path).",
            }
        if self.http is None or not ig_user_id or not token:
            return {
                "ok": False,
                "status": CapabilityTruth.UNVERIFIED_ON_HOST.value,
                "detail": "Prepared Reels container request; live HTTP not bound or ids missing.",
                "prepared": {
                    "endpoint": f"{INSTAGRAM_GRAPH_BASE}/{ig_user_id}/media",
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                },
            }
        container = self.http(
            "POST",
            f"{INSTAGRAM_GRAPH_BASE}/{ig_user_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": token,
            },
        )
        creation_id = (container or {}).get("id")
        if not creation_id:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "container_create_failed", "raw": redact_meta_error(container)}
        # Caller/orchestrator should poll; one status check here.
        status = self.http(
            "GET",
            f"{INSTAGRAM_GRAPH_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
        )
        code = (status or {}).get("status_code")
        if code and code not in {"FINISHED", "PUBLISHED"}:
            return {
                "ok": True,
                "status": "PROCESSING",
                "external_upload_id": creation_id,
                "container_status": code,
            }
        published = self.http(
            "POST",
            f"{INSTAGRAM_GRAPH_BASE}/{ig_user_id}/media_publish",
            params={"creation_id": creation_id, "access_token": token},
        )
        media_id = (published or {}).get("id")
        return {
            "ok": bool(media_id),
            "status": "PUBLISHED" if media_id else "FAILED",
            "external_upload_id": creation_id,
            "external_post_id": media_id,
            "raw": redact_meta_error(published),
        }

    def publish_status(self, external_upload_id: str) -> dict[str, Any]:
        token = self.auth.user_token("instagram")
        if not token or self.http is None:
            return {"ok": False, "status": CapabilityTruth.UNVERIFIED_ON_HOST.value}
        status = self.http(
            "GET",
            f"{INSTAGRAM_GRAPH_BASE}/{external_upload_id}",
            params={"fields": "status_code", "access_token": token},
        )
        return {"ok": True, "status": (status or {}).get("status_code") or "UNKNOWN", "raw": redact_meta_error(status)}

    def fetch_metrics(self, external_post_id: str) -> dict[str, Any]:
        token = self.auth.user_token("instagram")
        if not token or self.http is None:
            return {"ok": False, "status": CapabilityTruth.UNVERIFIED_ON_HOST.value, "metrics": None}
        result = self.http(
            "GET",
            f"{INSTAGRAM_GRAPH_BASE}/{external_post_id}/insights",
            params={"metric": "plays,reach,likes,comments,shares,saved", "access_token": token},
        )
        data = (result or {}).get("data")
        if data is None:
            return {
                "ok": False,
                "status": CapabilityTruth.PLATFORM_LIMITATION.value,
                "metrics": None,
                "unsupported": True,
                "detail": "Insights unavailable for this media/token.",
                "raw": redact_meta_error(result),
            }
        metrics: dict[str, Any] = {}
        for item in data or []:
            name = item.get("name")
            values = item.get("values") or []
            metrics[name] = values[0].get("value") if values else None
        return {"ok": True, "status": CapabilityTruth.READY.value, "metrics": metrics}
