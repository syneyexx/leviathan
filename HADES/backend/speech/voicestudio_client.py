"""VoiceStudio OpenAI-compatible audio client.

Only documented endpoints are used:
  GET  /v1/audio/voices
  POST /v1/audio/speech
  POST /v1/audio/transcriptions

VoiceStudio synthesizes a complete audio clip per speech request and returns
it as an HTTP body (StreamingResponse over BytesIO). There is no official
incremental PCM/SSE speech stream on this surface — do not invent one.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin

import httpx

# Documented SpeechRequest fields from VoiceStudio openai_compat.py
CORE_SPEECH_FIELDS = frozenset(
    {"model", "input", "voice", "response_format", "speed", "language"}
)
EXTENSION_SPEECH_FIELDS = frozenset(
    {
        "description",
        "instruct",
        "duration",
        "seed",
        "denoise",
        "preprocess_prompt",
        "chunk_duration",
        "chunk_threshold",
        "num_step",
        "guidance_scale",
    }
)

# UI capability hints keyed by engine id / feature flags from GET /voices engines[].
ENGINE_UI_HINTS: dict[str, dict[str, bool]] = {
    "voxcpm2": {"description": True, "instruct": True, "speed": True},
    "omnivoice": {"instruct": True, "speed": True, "num_step": True, "guidance_scale": True},
    "kittentts": {"speed": True},
    "cosyvoice": {"instruct": True, "speed": True},
    "mlx-audio": {"speed": True},
    "moss-tts-nano": {"speed": True},
    "indextts2": {"speed": True},
    "gpt-sovits": {"speed": True},
    "sherpa-onnx": {"speed": True},
}


def normalize_base_url(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    if not base:
        return "http://127.0.0.1:3900/v1"
    # Accept UI root or /v1
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def engine_supported_settings(engine: dict[str, Any] | None, model_id: str) -> dict[str, bool]:
    """Return which optional TTS settings the UI should show for the active model."""
    engine_id = str((engine or {}).get("id") or model_id or "tts-1").lower()
    if engine_id in {"tts-1", "tts-1-hd"}:
        # Aliases map to the active engine; prefer its metadata when present.
        engine_id = str((engine or {}).get("id") or "omnivoice").lower()

    hints = dict(ENGINE_UI_HINTS.get(engine_id, {"speed": True}))
    hints.setdefault("speed", True)
    hints.setdefault("language", True)
    hints.setdefault("voice", True)
    hints.setdefault("model", True)
    hints.setdefault("response_format", True)

    if engine:
        if engine.get("supports_voice_design"):
            hints["description"] = True
        if engine.get("supports_emotion"):
            hints["instruct"] = True
        # Cloning implies voice profile selection is meaningful.
        if engine.get("supports_cloning") is False:
            hints["voice_profiles_preferred"] = False
        else:
            hints["voice_profiles_preferred"] = True
    return hints


class VoiceStudioClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:3900/v1",
        api_key: str = "",
        timeout_seconds: float = 180.0,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    async def probe(self) -> dict[str, Any]:
        """Discover health + documented capabilities without inventing endpoints."""
        result: dict[str, Any] = {
            "ok": False,
            "provider": "voicestudio",
            "base_url": self.base_url,
            "ui_url": self.base_url.replace("/v1", "") or "http://127.0.0.1:3900",
            "endpoints": {
                "voices": "/audio/voices",
                "speech": "/audio/speech",
                "transcriptions": "/audio/transcriptions",
            },
            "streaming_speech": False,
            "streaming_note": (
                "VoiceStudio POST /v1/audio/speech returns a complete audio clip per request "
                "(HTTP body). HADES may chunk sentences client/server-side for earlier first audio, "
                "but that is not provider PCM streaming."
            ),
            "version": None,
            "voices": [],
            "engines": [],
            "error": None,
            "recovery": [],
        }
        try:
            async with httpx.AsyncClient(timeout=min(20.0, self.timeout_seconds)) as client:
                response = await client.get(self._url("audio/voices"), headers=self._headers())
            if response.status_code >= 400:
                result["error"] = f"VoiceStudio voices HTTP {response.status_code}: {response.text[:300]}"
                result["recovery"] = self._recovery_actions(result["error"])
                return result
            payload = response.json()
            result["voices"] = list(payload.get("voices") or [])
            result["engines"] = list(payload.get("engines") or [])
            if not result["voices"] and not result["engines"]:
                result["error"] = "empty_voices_and_engines"
                result["recovery"] = self._recovery_actions(result["error"])
                return result
            result["ok"] = True
            # Prefer an engine-reported version field if present; otherwise leave null.
            for engine in result["engines"]:
                if isinstance(engine, dict) and engine.get("version"):
                    result["version"] = engine.get("version")
                    break
            return result
        except httpx.HTTPError as exc:
            result["error"] = f"VoiceStudio niet bereikbaar op {self.base_url}: {exc}"
            result["recovery"] = self._recovery_actions(result["error"])
            return result
        except Exception as exc:  # pragma: no cover
            result["error"] = str(exc)
            result["recovery"] = self._recovery_actions(result["error"])
            return result

    def _recovery_actions(self, error: str) -> list[dict[str, str]]:
        return [
            {
                "id": "start_voicestudio_plugin",
                "label": "Start VoiceStudio via Plugins → VoiceStudio → start",
                "detail": error,
            },
            {
                "id": "open_voicestudio_ui",
                "label": "Open lokale VoiceStudio-UI",
                "href": self.base_url.replace("/v1", "") or "http://127.0.0.1:3900",
            },
            {
                "id": "check_settings",
                "label": "Controleer Instellingen → Spraak → TTS base URL (…/v1)",
            },
        ]

    async def list_voices(self) -> dict[str, Any]:
        probe = await self.probe()
        if not probe.get("ok"):
            raise RuntimeError(probe.get("error") or "VoiceStudio voices mislukt.")
        return {
            "voices": probe.get("voices") or [],
            "engines": probe.get("engines") or [],
            "streaming_speech": False,
            "base_url": self.base_url,
            "version": probe.get("version"),
        }

    async def synthesize(
        self,
        *,
        text: str,
        voice: str = "default",
        model: str = "tts-1",
        response_format: str = "wav",
        speed: float = 1.0,
        language: str | None = "nl",
        extras: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or "tts-1",
            "input": text,
            "voice": voice or "default",
            "response_format": response_format or "wav",
            "speed": float(speed or 1.0),
        }
        if language:
            body["language"] = language
        for key, value in (extras or {}).items():
            if key in EXTENSION_SPEECH_FIELDS and value is not None and value != "":
                body[key] = value

        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Accept"] = f"audio/{response_format}, application/octet-stream, */*"

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            request = client.build_request("POST", self._url("audio/speech"), headers=headers, json=body)
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Spraak geannuleerd vóór VoiceStudio-aanroep.")
            response = await client.send(request, stream=True)
            try:
                if cancel_event and cancel_event.is_set():
                    await response.aclose()
                    raise InterruptedError("Spraak geannuleerd.")
                if response.status_code >= 400:
                    detail = (await response.aread())[:800].decode("utf-8", errors="replace")
                    raise RuntimeError(f"VoiceStudio speech HTTP {response.status_code}: {detail}")
                chunks: list[bytes] = []
                async for piece in response.aiter_bytes():
                    if cancel_event and cancel_event.is_set():
                        await response.aclose()
                        raise InterruptedError("Spraak geannuleerd tijdens generatie.")
                    chunks.append(piece)
                audio = b"".join(chunks)
            finally:
                await response.aclose()

        if not audio:
            raise RuntimeError("VoiceStudio speech returned empty audio body.")
        mime = response.headers.get("content-type") or _mime_for_format(response_format)
        return {
            "audio": audio,
            "mime_type": mime.split(";")[0].strip(),
            "response_format": response_format,
            "bytes": len(audio),
            "model": body["model"],
            "voice": body["voice"],
        }

    async def transcribe(
        self,
        *,
        audio: bytes,
        filename: str = "audio.wav",
        model: str = "whisper-1",
        language: str | None = "nl",
        response_format: str = "json",
    ) -> dict[str, Any]:
        headers = self._headers()
        data: dict[str, str] = {
            "model": model or "whisper-1",
            "response_format": response_format or "json",
        }
        if language:
            data["language"] = language
        files = {"file": (filename or "audio.wav", audio, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self._url("audio/transcriptions"),
                headers=headers,
                data=data,
                files=files,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"VoiceStudio STT HTTP {response.status_code}: {response.text[:500]}")
        if response_format == "text":
            return {"text": response.text, "raw": response.text}
        try:
            payload = response.json()
        except Exception:
            return {"text": response.text, "raw": response.text}
        if isinstance(payload, dict):
            return payload
        return {"text": str(payload), "raw": payload}


def _mime_for_format(fmt: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get((fmt or "wav").lower(), "application/octet-stream")
