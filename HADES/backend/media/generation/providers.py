
"""Provider-agnostic generation interfaces (image/video/voice/music)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ImageProvider(ABC):
    id: str = "image"

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def generate(self, *, prompt: str, width: int = 1080, height: int = 1920, seed: int | None = None, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def cancel(self, job_id: str) -> dict[str, Any]:
        return {"ok": False, "status": "UNAVAILABLE", "job_id": job_id}


class VideoGenerationProvider(ABC):
    id: str = "video"

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def generate(self, *, prompt: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError


class VoiceProvider(ABC):
    id: str = "voice"

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, *, text: str, persona: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class MusicProvider(ABC):
    id: str = "music"

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def select_or_generate(self, *, style: str, duration: float, license_required: bool = True) -> dict[str, Any]:
        raise NotImplementedError


class TextGraphicsImageProvider(ImageProvider):
    """Baseline offline image route: solid frame via FFmpeg drawtext (no external model)."""

    id = "text_graphics_ffmpeg"

    def health(self) -> dict[str, Any]:
        from media.rendering.ffmpeg_renderer import which_ffmpeg

        binary = which_ffmpeg()
        if not binary:
            return {"ok": False, "status": "SETUP_REQUIRED", "error": "ffmpeg_missing"}
        return {"ok": True, "status": "READY", "provider": self.id}

    def generate(self, *, prompt: str, width: int = 1080, height: int = 1920, seed: int | None = None, **kwargs: Any) -> dict[str, Any]:
        # Actual frame generation is folded into master render; this marks strategy readiness.
        return {
            "ok": True,
            "status": "READY",
            "provider": self.id,
            "asset_strategy": "TEXT_GRAPHICS",
            "prompt": prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "license_state": "GENERATED",
        }


class HadesVoiceProvider(VoiceProvider):
    id = "hades_voice"

    def __init__(self, synthesize_callable: Any | None = None) -> None:
        self.synthesize_callable = synthesize_callable

    def health(self) -> dict[str, Any]:
        if self.synthesize_callable is None:
            return {"ok": False, "status": "SETUP_REQUIRED", "detail": "voice_bridge_unbound"}
        return {"ok": True, "status": "READY", "provider": self.id}

    def synthesize(self, *, text: str, persona: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.synthesize_callable is None:
            return {"ok": False, "status": "SETUP_REQUIRED", "detail": "voice_bridge_unbound"}
        return self.synthesize_callable(text=text, persona=persona or {})
