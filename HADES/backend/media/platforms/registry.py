
"""Build default platform adapter registry from settings/secrets."""

from __future__ import annotations

from typing import Any, Callable

from media.platforms.base import AdapterRegistry
from media.platforms.facebook import FacebookAdapter
from media.platforms.instagram import InstagramAdapter
from media.platforms.meta_auth import MetaAuthState
from media.platforms.tiktok import TikTokAdapter
from media.platforms.youtube import YouTubeAdapter


def build_adapter_registry(
    *,
    secrets: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    http: Callable[..., dict[str, Any]] | None = None,
) -> AdapterRegistry:
    secrets = dict(secrets or {})
    config = dict(config or {})
    meta = MetaAuthState(secrets=secrets, config=config)
    registry = AdapterRegistry()
    registry.register(
        TikTokAdapter(
            access_token=secrets.get("tiktok_access_token"),
            client_audited=config.get("tiktok_client_audited"),
            http=http,
        )
    )
    registry.register(
        YouTubeAdapter(
            access_token=secrets.get("youtube_access_token"),
            channel_id=config.get("youtube_channel_id"),
            http=http,
        )
    )
    registry.register(InstagramAdapter(auth=meta, http=http))
    registry.register(FacebookAdapter(auth=meta, http=http))
    return registry
