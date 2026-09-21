"""VoiceStudio TTS adapter for the unified voice provider registry."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from voice.errors import VoiceProviderError
from voice.providers.base import SynthesisResult, TtsProvider, VoiceInfo

_T = TypeVar("_T")


def _run_async_from_sync(factory: Callable[[], Awaitable[_T]]) -> _T:
    """Run one async operation from a synchronous provider method.

    ``asyncio.run`` cannot be called while the current thread already owns a
    running event loop. Importantly, ``factory`` is only invoked in the loop
    that will actually await the coroutine, so an error path can never leak an
    already-created un-awaited coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put((True, asyncio.run(factory())))
        except BaseException as exc:
            result_queue.put((False, exc))

    worker = threading.Thread(
        target=_worker,
        name="hades-voicestudio-async-bridge",
        daemon=True,
    )
    worker.start()
    worker.join()
    ok, payload = result_queue.get()
    if ok:
        return payload  # type: ignore[return-value]
    assert isinstance(payload, BaseException)
    raise payload


class VoiceStudioTts(TtsProvider):
    id = "voicestudio"
    label = "VoiceStudio (lokaal)"

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})

    def _client(self):
        from speech.voicestudio_client import VoiceStudioClient, normalize_base_url

        base = normalize_base_url(str(self._settings.get("tts_base_url") or "http://127.0.0.1:3900/v1"))
        return VoiceStudioClient(
            base_url=base,
            api_key=str(self._settings.get("tts_api_key") or ""),
            timeout_seconds=float(self._settings.get("request_timeout_seconds") or 120),
        )

    def availability(self) -> dict[str, Any]:
        try:
            client = self._client()

            async def _probe() -> dict[str, Any]:
                return await client.probe()

            probe = _run_async_from_sync(_probe)
            ok = bool(probe.get("ok"))
            return {
                "ready": ok,
                "provider": self.id,
                "status": "ready" if ok else "unavailable",
                "message": probe.get("error") or "VoiceStudio TTS",
                "offline": True,
                "server_synthesis": True,
                "detail": probe,
            }
        except Exception as exc:
            return {
                "ready": False,
                "provider": self.id,
                "status": "error",
                "message": str(exc),
                "offline": True,
                "server_synthesis": True,
            }

    def list_voices(self, language: str | None = None) -> list[VoiceInfo]:
        try:
            client = self._client()

            async def _list() -> list[dict[str, Any]]:
                result = await client.list_voices()
                return list(result.get("voices") or [])

            raw = _run_async_from_sync(_list)
            voices: list[VoiceInfo] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                voices.append(
                    VoiceInfo(
                        id=str(item.get("id") or item.get("name") or "default"),
                        name=str(item.get("name") or item.get("id") or "default"),
                        language=str(item.get("language") or language or ""),
                        gender=str(item.get("gender") or "") or None,
                        provider=self.id,
                    )
                )
            return voices
        except Exception:
            return []

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SynthesisResult:
        client = self._client()
        if cancel_check and cancel_check():
            raise VoiceProviderError("cancelled", "cancelled", recovery="Opnieuw proberen.")

        async def _run() -> dict[str, Any]:
            cancel_event = asyncio.Event()
            return await client.synthesize(
                text=text,
                voice=voice_id or self._settings.get("tts_voice_id") or self._settings.get("voice_tts_voice") or "default",
                model=str(self._settings.get("tts_model") or "tts-1"),
                response_format=str(self._settings.get("tts_response_format") or "wav"),
                speed=float(speed or self._settings.get("tts_speed") or 1.0),
                language=language or self._settings.get("tts_language") or self._settings.get("voice_language") or "nl",
                cancel_event=cancel_event,
            )

        try:
            result = _run_async_from_sync(_run)
        except InterruptedError as exc:
            raise VoiceProviderError("cancelled", str(exc), recovery="Opnieuw proberen.") from exc
        except Exception as exc:
            raise VoiceProviderError("voicestudio_failed", str(exc), recovery="Controleer VoiceStudio of kies Piper.") from exc

        audio = result.get("audio")
        if not audio:
            raise VoiceProviderError("empty_audio", "VoiceStudio gaf geen audio terug.", recovery="Controleer VoiceStudio plugin status.")
        return SynthesisResult(
            audio=bytes(audio),
            mime_type=str(result.get("mime_type") or "audio/wav"),
            sample_rate=int(result.get("sample_rate") or 22050),
            voice_id=str(voice_id or result.get("voice") or ""),
            provider=self.id,
            speakable_text=text,
        )
