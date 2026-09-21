
"""TikTok Content Posting API adapter (official).

Assumptions verified 2026-09-14 from developers.tiktok.com:
- Query creator_info before Direct Post
- Honor privacy_level_options (no invented defaults for public post)
- Unaudited clients: PRIVATE_ONLY / SELF_ONLY
- FILE_UPLOAD vs PULL_FROM_URL
- Creator consent required for Direct Post UX
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from media.models import CapabilityTruth
from media.platforms.base import MediaPlatformAdapter

TIKTOK_API_BASE = "https://open.tiktokapis.com"


HttpClient = Callable[..., dict[str, Any]]


class TikTokAdapter(MediaPlatformAdapter):
    platform = "tiktok"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        client_audited: bool | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self.access_token = access_token
        self.client_audited = client_audited
        self.http = http

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "api": "Content Posting API",
            "supports": [
                "oauth",
                "creator_info",
                "direct_post",
                "upload_to_draft",
                "file_upload",
                "pull_from_url",
                "publish_status",
                "ai_disclosure_field_when_supported",
            ],
            "requires_creator_consent": True,
            "unaudited_restriction": "SELF_ONLY",
        }

    def auth_status(self) -> dict[str, Any]:
        if not self.access_token:
            return {
                "ok": False,
                "status": CapabilityTruth.AUTH_REQUIRED.value,
                "detail": "TikTok OAuth access token missing.",
                "remediation": "Authorize TikTok with video.publish via Media → Setup.",
            }
        if self.client_audited is False:
            return {
                "ok": True,
                "status": CapabilityTruth.PRIVATE_ONLY.value,
                "detail": "Token present; unaudited client restricted to private Direct Post.",
                "remediation": "Complete TikTok API client audit for public Direct Post.",
                "audit": False,
            }
        if self.client_audited is None:
            return {
                "ok": True,
                "status": CapabilityTruth.PLATFORM_AUDIT_REQUIRED.value,
                "detail": "Token present; audit status unknown — treat public Direct Post as restricted.",
                "remediation": "Confirm TikTok client audit status in developer portal.",
            }
        return {
            "ok": True,
            "status": CapabilityTruth.READY.value,
            "detail": "TikTok token present and client marked audited.",
            "audit": True,
        }

    def query_creator_info(self) -> dict[str, Any]:
        if not self.access_token:
            return {"ok": False, "status": CapabilityTruth.AUTH_REQUIRED.value}
        if self.http is None:
            return {
                "ok": False,
                "status": CapabilityTruth.UNVERIFIED_ON_HOST.value,
                "detail": "No HTTP client bound; live creator_info not called.",
            }
        result = self.http(
            "POST",
            f"{TIKTOK_API_BASE}/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json; charset=UTF-8"},
            json={},
        )
        data = (result or {}).get("data") or {}
        return {
            "ok": (result or {}).get("error", {}).get("code") == "ok" or bool(data),
            "status": CapabilityTruth.READY.value if data else CapabilityTruth.FAILED.value,
            "creator": data,
            "raw_error": _redact(result),
        }

    def publish(self, job: dict[str, Any], variant: dict[str, Any], *, consent: dict[str, Any] | None = None) -> dict[str, Any]:
        auth = self.auth_status()
        if auth["status"] == CapabilityTruth.AUTH_REQUIRED.value:
            return {"ok": False, **auth}

        consent = consent or {}
        if not consent.get("creator_confirmed"):
            return {
                "ok": False,
                "status": "WAITING_PLATFORM_CONSENT",
                "detail": "TikTok Direct Post requires explicit creator consent for this publish flow.",
            }

        privacy = consent.get("privacy_level")
        creator = consent.get("creator_info") or {}
        options = list(creator.get("privacy_level_options") or [])
        if not privacy:
            return {
                "ok": False,
                "status": "WAITING_PLATFORM_CONSENT",
                "detail": "privacy_level must be selected from creator_info privacy_level_options (no silent default).",
            }
        if options and privacy not in options:
            return {
                "ok": False,
                "status": CapabilityTruth.FAILED.value,
                "detail": "privacy_level_option_mismatch",
            }
        if auth["status"] in {CapabilityTruth.PRIVATE_ONLY.value, CapabilityTruth.PLATFORM_AUDIT_REQUIRED.value} and privacy != "SELF_ONLY":
            return {
                "ok": False,
                "status": CapabilityTruth.PRIVATE_ONLY.value,
                "detail": "Unaudited/unknown-audit clients may only post SELF_ONLY.",
            }

        meta = variant.get("metadata") or {}
        title = str(meta.get("title") or meta.get("caption") or "")[:2200]
        render_path = meta.get("render_path") or (variant.get("metadata") or {}).get("path")
        source = consent.get("source") or "FILE_UPLOAD"
        if self.http is None:
            return {
                "ok": False,
                "status": CapabilityTruth.UNVERIFIED_ON_HOST.value,
                "detail": "HTTP client not bound — adapter logic verified via fixtures only.",
                "prepared": {
                    "post_info": {
                        "title": title,
                        "privacy_level": privacy,
                        "disable_duet": bool(consent.get("disable_duet", False)),
                        "disable_comment": bool(consent.get("disable_comment", False)),
                        "disable_stitch": bool(consent.get("disable_stitch", False)),
                    },
                    "source_info": {"source": source},
                },
            }

        if source == "FILE_UPLOAD":
            path = Path(str(render_path or ""))
            if not path.exists():
                return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "render_missing"}
            size = path.stat().st_size
            init = self.http(
                "POST",
                f"{TIKTOK_API_BASE}/v2/post/publish/video/init/",
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json; charset=UTF-8"},
                json={
                    "post_info": {
                        "title": title,
                        "privacy_level": privacy,
                        "disable_duet": bool(consent.get("disable_duet", False)),
                        "disable_comment": bool(consent.get("disable_comment", False)),
                        "disable_stitch": bool(consent.get("disable_stitch", False)),
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": size,
                        "total_chunk_count": 1,
                    },
                },
            )
            data = (init or {}).get("data") or {}
            upload_url = data.get("upload_url")
            publish_id = data.get("publish_id")
            if not upload_url or not publish_id:
                return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "init_failed", "raw": _redact(init)}
            put = self.http(
                "PUT",
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                    "Content-Length": str(size),
                },
                content=path.read_bytes(),
            )
            return {
                "ok": True,
                "status": "PROCESSING",
                "external_upload_id": publish_id,
                "upload_result": _redact(put),
            }

        # PULL_FROM_URL — domain must be verified by TikTok.
        video_url = consent.get("video_url") or meta.get("public_url")
        if not video_url:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "video_url_required_for_pull"}
        init = self.http(
            "POST",
            f"{TIKTOK_API_BASE}/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {"title": title, "privacy_level": privacy},
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            },
        )
        data = (init or {}).get("data") or {}
        publish_id = data.get("publish_id")
        if not publish_id:
            return {"ok": False, "status": CapabilityTruth.FAILED.value, "detail": "init_failed", "raw": _redact(init)}
        return {"ok": True, "status": "PROCESSING", "external_upload_id": publish_id}

    def publish_status(self, external_upload_id: str) -> dict[str, Any]:
        if not self.access_token or self.http is None:
            return {"ok": False, "status": CapabilityTruth.UNVERIFIED_ON_HOST.value}
        result = self.http(
            "POST",
            f"{TIKTOK_API_BASE}/v2/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": external_upload_id},
        )
        data = (result or {}).get("data") or {}
        return {"ok": True, "status": data.get("status") or "UNKNOWN", "data": data, "raw": _redact(result)}

    def fetch_metrics(self, external_post_id: str) -> dict[str, Any]:
        # Do not invent zeros for unsupported analytics surfaces.
        return {
            "ok": False,
            "status": CapabilityTruth.PLATFORM_LIMITATION.value,
            "unsupported": True,
            "metrics": None,
            "detail": "TikTok public Content Posting API does not expose a full analytics feed for all apps; use authorized Research/Display APIs when entitled.",
            "external_post_id": external_post_id,
        }


def _redact(payload: Any) -> Any:
    text = str(payload)
    if "Bearer " in text:
        text = text.split("Bearer ")[0] + "Bearer [REDACTED]"
    return text[:800]
