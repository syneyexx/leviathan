
"""Shared Meta (Instagram/Facebook) auth helpers — tokens via HADES secret store."""

from __future__ import annotations

from typing import Any

from media.models import CapabilityTruth

# Verified against Meta docs (2026-09-14): Graph API v26.0.
META_GRAPH_VERSION = "v26.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
INSTAGRAM_GRAPH_BASE = f"https://graph.instagram.com/{META_GRAPH_VERSION}"

# Instagram Login (no Facebook Page required for basic publish path).
IG_LOGIN_SCOPES = (
    "instagram_business_basic",
    "instagram_business_content_publish",
    "instagram_business_manage_insights",
)

# Facebook Page publishing / Reels.
FB_PAGE_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
)


def redact_meta_error(payload: Any) -> Any:
    text = str(payload)
    for marker in ("access_token=", "Bearer ", "EAAG", "IGQ"):
        if marker in text:
            text = text.replace(marker, "[REDACTED]")
    return text[:800]


class MetaAuthState:
    def __init__(self, *, secrets: dict[str, str] | None = None, config: dict[str, Any] | None = None) -> None:
        self.secrets = dict(secrets or {})
        self.config = dict(config or {})

    def has_app_credentials(self) -> bool:
        return bool(self.secrets.get("meta_app_id") and self.secrets.get("meta_app_secret"))

    def user_token(self, platform: str) -> str | None:
        return self.secrets.get(f"{platform}_access_token") or self.secrets.get("meta_user_access_token")

    def page_token(self) -> str | None:
        return self.secrets.get("facebook_page_access_token")

    def page_id(self) -> str | None:
        return self.config.get("facebook_page_id") or self.secrets.get("facebook_page_id")

    def ig_user_id(self) -> str | None:
        return self.config.get("instagram_user_id") or self.secrets.get("instagram_user_id")

    def status_for(self, platform: str) -> dict[str, Any]:
        if not self.has_app_credentials() and not self.user_token(platform) and not self.page_token():
            return {
                "status": CapabilityTruth.AUTH_REQUIRED.value,
                "detail": "Meta app credentials / OAuth tokens not configured.",
                "remediation": "Create a Meta developer app and complete OAuth in Media → Setup.",
            }
        if platform == "facebook":
            if not self.page_id() or not self.page_token():
                return {
                    "status": CapabilityTruth.PAGE_REQUIRED.value,
                    "detail": "Facebook Page id + page access token required for Reels publishing.",
                    "remediation": "Authorize a Page with pages_manage_posts and CREATE_CONTENT.",
                }
        if platform == "instagram":
            if not self.ig_user_id() or not self.user_token("instagram"):
                return {
                    "status": CapabilityTruth.AUTH_REQUIRED.value,
                    "detail": "Instagram professional account OAuth required.",
                    "remediation": "Use Instagram Login (instagram_business_*) or Facebook Login path.",
                }
            if self.config.get("app_review") is False:
                return {
                    "status": CapabilityTruth.APP_REVIEW_REQUIRED.value,
                    "detail": "Publishing permissions typically need Meta App Review for production.",
                    "remediation": "Submit instagram_business_content_publish (or FB Login equivalents) for review.",
                    "app_review": False,
                }
        return {
            "status": CapabilityTruth.READY.value,
            "detail": f"{platform} credentials present (live call not verified in this probe).",
            "graph_version": META_GRAPH_VERSION,
        }
