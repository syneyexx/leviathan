
"""Media Capability Doctor — honest readiness for generation and platforms."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from media.models import CapabilityItem, CapabilityTruth, MediaPlatform

GetSetting = Callable[[str], Any]


def _which_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _ffmpeg_version(binary: str) -> str | None:
    try:
        completed = subprocess.run(
            [binary, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (completed.stdout or "").splitlines()[:1]
    return line[0].strip() if line else None


def _truth(status: CapabilityTruth, *, detail: str, remediation: str = "", **evidence: Any) -> CapabilityItem:
    return CapabilityItem(
        id=evidence.pop("id", "item"),
        label=evidence.pop("label", "item"),
        status=status,
        detail=detail,
        remediation=remediation,
        evidence=evidence,
    )


class MediaCapabilityDoctor:
    def __init__(
        self,
        *,
        data_root: Path,
        get_setting: GetSetting | None = None,
        accounts: list[dict[str, Any]] | None = None,
        platform_auth: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.get_setting = get_setting or (lambda _k: None)
        self.accounts = accounts or []
        self.platform_auth = platform_auth or {}

    def probe_ffmpeg(self) -> CapabilityItem:
        binary = _which_ffmpeg()
        if not binary:
            return CapabilityItem(
                id="ffmpeg",
                label="FFmpeg",
                status=CapabilityTruth.SETUP_REQUIRED,
                detail="FFmpeg binary not found on PATH.",
                remediation="Install FFmpeg and ensure `ffmpeg` is on PATH (Windows: ffmpeg.exe).",
            )
        version = _ffmpeg_version(binary)
        return CapabilityItem(
            id="ffmpeg",
            label="FFmpeg",
            status=CapabilityTruth.READY,
            detail=version or binary,
            evidence={"binary": binary, "version": version},
        )

    def probe_voice(self) -> CapabilityItem:
        # Prefer configured TTS; do not claim READY without evidence.
        provider = str(self.get_setting("voice_tts_provider") or self.get_setting("speech_tts_provider") or "").strip()
        if not provider:
            # Piper/local may still be available via voice module — probe import lightly.
            try:
                from voice.providers import piper_tts  # type: ignore

                _ = piper_tts
                return CapabilityItem(
                    id="voice",
                    label="Voice / TTS",
                    status=CapabilityTruth.PARTIAL,
                    detail="Voice module present; no explicit TTS provider configured in settings.",
                    remediation="Configure Piper/VoiceStudio under Settings → Spraak, or Media Setup.",
                )
            except Exception:
                return CapabilityItem(
                    id="voice",
                    label="Voice / TTS",
                    status=CapabilityTruth.SETUP_REQUIRED,
                    detail="No TTS provider configured.",
                    remediation="Install/configure HADES voice (Piper) or VoiceStudio.",
                )
        return CapabilityItem(
            id="voice",
            label="Voice / TTS",
            status=CapabilityTruth.READY,
            detail=f"Configured provider: {provider}",
            evidence={"provider": provider},
        )

    def probe_asr(self) -> CapabilityItem:
        provider = str(self.get_setting("voice_asr_provider") or "faster_whisper").strip()
        try:
            import importlib

            importlib.import_module("faster_whisper")
            return CapabilityItem(
                id="asr",
                label="ASR / Transcription",
                status=CapabilityTruth.READY,
                detail=f"Provider route: {provider} (faster-whisper importable)",
                evidence={"provider": provider},
            )
        except Exception:
            return CapabilityItem(
                id="asr",
                label="ASR / Transcription",
                status=CapabilityTruth.SETUP_REQUIRED,
                detail="faster-whisper not importable; official captions still usable when available.",
                remediation="Install voice ASR deps or provide official captions/transcripts.",
                evidence={"provider": provider},
            )

    def probe_image(self) -> CapabilityItem:
        endpoint = str(self.get_setting("media_comfyui_endpoint") or "").strip()
        if not endpoint:
            return CapabilityItem(
                id="image",
                label="Image Generation",
                status=CapabilityTruth.SETUP_REQUIRED,
                detail="No image provider configured (ComfyUI endpoint empty).",
                remediation="Set ComfyUI endpoint in Media Setup, or register an image plugin.",
            )
        return CapabilityItem(
            id="image",
            label="Image Generation",
            status=CapabilityTruth.UNVERIFIED_ON_HOST,
            detail=f"ComfyUI endpoint configured: {endpoint} (live health not verified in this probe).",
            evidence={"endpoint": endpoint},
        )

    def probe_video_gen(self) -> CapabilityItem:
        endpoint = str(self.get_setting("media_video_provider") or "").strip()
        if not endpoint:
            return CapabilityItem(
                id="video_generation",
                label="AI Video Generation",
                status=CapabilityTruth.UNAVAILABLE,
                detail="Optional. Not configured — image-motion/compositor route remains available.",
                remediation="Configure a video generation provider only if needed.",
            )
        return CapabilityItem(
            id="video_generation",
            label="AI Video Generation",
            status=CapabilityTruth.UNVERIFIED_ON_HOST,
            detail=f"Provider configured: {endpoint}",
            evidence={"provider": endpoint},
        )

    def probe_vision(self) -> CapabilityItem:
        model = str(self.get_setting("media_vision_model") or self.get_setting("vision_model") or "").strip()
        if not model:
            return CapabilityItem(
                id="vision",
                label="Vision Analysis",
                status=CapabilityTruth.DEGRADED,
                detail="No vision model configured — transcript/trend intelligence still works.",
                remediation="Configure a vision-capable LM Studio model for frame analysis.",
            )
        return CapabilityItem(
            id="vision",
            label="Vision Analysis",
            status=CapabilityTruth.READY,
            detail=f"Vision model id configured: {model}",
            evidence={"model": model},
        )

    def probe_llm(self) -> CapabilityItem:
        model = str(self.get_setting("model") or self.get_setting("active_model") or "").strip()
        base = str(self.get_setting("lm_studio_url") or self.get_setting("openai_base_url") or "").strip()
        if not model and not base:
            return CapabilityItem(
                id="llm",
                label="HADES Model",
                status=CapabilityTruth.SETUP_REQUIRED,
                detail="No model configured.",
                remediation="Configure LM Studio / model in Settings → Models.",
            )
        return CapabilityItem(
            id="llm",
            label="HADES Model",
            status=CapabilityTruth.READY if model else CapabilityTruth.PARTIAL,
            detail=model or f"Base URL present: {base}",
            evidence={"model": model, "base_url": base},
        )

    def probe_platform(self, platform: MediaPlatform) -> CapabilityItem:
        auth = dict(self.platform_auth.get(platform.value) or {})
        accounts = [a for a in self.accounts if a.get("platform") == platform.value]
        status_raw = str(auth.get("status") or (accounts[0].get("auth_status") if accounts else "") or CapabilityTruth.AUTH_REQUIRED.value)
        try:
            status = CapabilityTruth(status_raw)
        except ValueError:
            status = CapabilityTruth.AUTH_REQUIRED

        labels = {
            MediaPlatform.TIKTOK: "TikTok",
            MediaPlatform.YOUTUBE: "YouTube",
            MediaPlatform.INSTAGRAM: "Instagram",
            MediaPlatform.FACEBOOK: "Facebook",
        }
        detail = str(auth.get("detail") or "")
        remediation = str(auth.get("remediation") or "")
        if not accounts and status == CapabilityTruth.AUTH_REQUIRED:
            detail = detail or "No authorized account linked."
            remediation = remediation or f"Connect {labels[platform]} via official OAuth in Media → Setup."
        if platform == MediaPlatform.TIKTOK and status == CapabilityTruth.READY and auth.get("audit") is False:
            status = CapabilityTruth.PRIVATE_ONLY
            detail = detail or "OAuth present but client unaudited — Direct Post restricted to SELF_ONLY."
            remediation = "Complete TikTok API client audit for public Direct Post."
        if platform == MediaPlatform.FACEBOOK and not auth.get("page_id") and not any(
            a.get("metadata", {}).get("page_id") for a in accounts
        ):
            if status in {CapabilityTruth.READY, CapabilityTruth.AUTH_REQUIRED, CapabilityTruth.PARTIAL}:
                status = CapabilityTruth.PAGE_REQUIRED
                detail = detail or "Facebook Page authorization required for Reels/Page publishing."
                remediation = "Authorize a Facebook Page with pages_manage_posts and CREATE_CONTENT task."
        if platform == MediaPlatform.INSTAGRAM and status == CapabilityTruth.READY and auth.get("app_review") is False:
            status = CapabilityTruth.APP_REVIEW_REQUIRED
            detail = detail or "Instagram publishing permissions require Meta App Review for production."
        return CapabilityItem(
            id=platform.value,
            label=labels[platform],
            status=status,
            detail=detail or status.value,
            remediation=remediation,
            evidence={"accounts": len(accounts), **{k: v for k, v in auth.items() if k not in {"access_token", "refresh_token", "token"}}},
        )

    def probe_storage(self) -> CapabilityItem:
        media_root = self.data_root / "media"
        try:
            media_root.mkdir(parents=True, exist_ok=True)
            probe = media_root / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return CapabilityItem(
                id="storage",
                label="Media Storage",
                status=CapabilityTruth.READY,
                detail=str(media_root),
                evidence={"path": str(media_root)},
            )
        except OSError as exc:
            return CapabilityItem(
                id="storage",
                label="Media Storage",
                status=CapabilityTruth.FAILED,
                detail=f"Cannot write media data root: {exc}",
                remediation="Fix permissions on HADES data directory.",
            )

    def snapshot(self) -> dict[str, Any]:
        items = [
            self.probe_llm(),
            self.probe_ffmpeg(),
            self.probe_asr(),
            self.probe_voice(),
            self.probe_image(),
            self.probe_video_gen(),
            self.probe_vision(),
            self.probe_storage(),
        ]
        platforms = {p.value: self.probe_platform(p) for p in MediaPlatform}
        generation_ready = all(
            i.status in {CapabilityTruth.READY, CapabilityTruth.PARTIAL, CapabilityTruth.DEGRADED, CapabilityTruth.UNVERIFIED_ON_HOST}
            for i in items
            if i.id in {"llm", "ffmpeg", "storage"}
        )
        publish_statuses = [p.status for p in platforms.values()]
        if all(s == CapabilityTruth.READY for s in publish_statuses):
            publishing = CapabilityTruth.READY
        elif any(s == CapabilityTruth.READY for s in publish_statuses):
            publishing = CapabilityTruth.PARTIAL
        elif any(s in {CapabilityTruth.PRIVATE_ONLY, CapabilityTruth.APP_REVIEW_REQUIRED, CapabilityTruth.PLATFORM_AUDIT_REQUIRED} for s in publish_statuses):
            publishing = CapabilityTruth.PARTIAL
        else:
            publishing = CapabilityTruth.AUTH_REQUIRED

        autonomous = CapabilityTruth.READY if generation_ready and publishing in {CapabilityTruth.READY, CapabilityTruth.PARTIAL, CapabilityTruth.PRIVATE_ONLY} else CapabilityTruth.DEGRADED
        return {
            "generation": {i.id: i.model_dump() for i in items},
            "platforms": {k: v.model_dump() for k, v in platforms.items()},
            "automation": {
                "trend_intelligence": CapabilityItem(
                    id="trend_intelligence",
                    label="Trend intelligence",
                    status=CapabilityTruth.READY,
                    detail="Evidence-driven providers; unavailable sources degrade honestly.",
                ).model_dump(),
                "autonomous_production": CapabilityItem(
                    id="autonomous_production",
                    label="Autonomous production",
                    status=autonomous,
                    detail="Requires LLM + FFmpeg + storage; image gen optional via text/graphics route.",
                ).model_dump(),
                "publishing": CapabilityItem(
                    id="publishing",
                    label="Publishing",
                    status=publishing,
                    detail="Per-platform truth in platforms block.",
                ).model_dump(),
                "analytics": CapabilityItem(
                    id="analytics",
                    label="Analytics",
                    status=CapabilityTruth.PARTIAL if publishing != CapabilityTruth.AUTH_REQUIRED else CapabilityTruth.AUTH_REQUIRED,
                    detail="Snapshots work locally; live platform metrics require authorized accounts.",
                ).model_dump(),
            },
        }
