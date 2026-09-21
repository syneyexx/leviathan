
"""Platform adapter contract — HTTP details stay out of MediaOrchestrator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MediaPlatformAdapter(ABC):
    platform: str = "base"

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def auth_status(self) -> dict[str, Any]:
        raise NotImplementedError

    def account_info(self) -> dict[str, Any]:
        return {"ok": False, "status": "AUTH_REQUIRED"}

    def validate_variant(self, variant: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "READY", "variant": variant}

    def prepare_publish(self, job: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "READY", "job": job, "variant": variant}

    @abstractmethod
    def publish(self, job: dict[str, Any], variant: dict[str, Any], *, consent: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def publish_status(self, external_upload_id: str) -> dict[str, Any]:
        return {"ok": False, "status": "UNAVAILABLE", "external_upload_id": external_upload_id}

    def fetch_metrics(self, external_post_id: str) -> dict[str, Any]:
        return {"ok": False, "status": "UNAVAILABLE", "metrics": None, "unsupported": True}

    def refresh_auth(self) -> dict[str, Any]:
        return self.auth_status()


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, MediaPlatformAdapter] = {}

    def register(self, adapter: MediaPlatformAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get(self, platform: str) -> MediaPlatformAdapter | None:
        return self._adapters.get(platform)

    def all(self) -> dict[str, MediaPlatformAdapter]:
        return dict(self._adapters)
