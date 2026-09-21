# HADES + VoiceStudio (local spoken answers)

## What this is

HADES can use **VoiceStudio** as a swappable **local** TTS provider for spoken chat answers. The LM Studio language model and the VoiceStudio voice profile are independent settings — changing the chat model does not reset the selected voice.

When VoiceStudio is unavailable, **text chat continues**. HADES does **not** silently switch to another voice or a cloud provider.

## Prerequisites

1. VoiceStudio running locally (desktop install **or** HADES plugin Docker start on port `3900`).
2. HADES backend reachable at `http://127.0.0.1:8000`.
3. Enough free host RAM for LM Studio **plus** the VoiceStudio engine you select (shared 16 GB RAM / 16 GB VRAM budgets are common). HADES checks free memory before TTS and **never** forces unloading your LM Studio model.

## Configure

1. Open **Instellingen → Spraak**.
2. Set **TTS-provider** to `VoiceStudio (lokaal)`.
3. Confirm **TTS base URL** is `http://127.0.0.1:3900/v1` (or your desktop install).
4. Refresh status. HADES calls only documented endpoints:
   - `GET /v1/audio/voices`
   - `POST /v1/audio/speech`
5. Pick a **default voice** and optional engine (`tts-1` = active VoiceStudio engine).
6. Use **Voorbeeldbeluisteren** to verify the chosen profile.
7. Enable **Gesproken antwoorden** (also available as a toggle on the Chat title bar).

Optional engine fields such as `instruct` / `description` appear only when the selected engine reports support.

## Chat usage

- **Gesproken antwoorden** on: final assistant text is spoken after the turn completes.
- Per assistant message: **Voorlezen** / **Stop**.
- Sending a new message **interrupts** leftover audio and cancels stale generations.
- Internal reasoning, tool dumps, and fenced code blocks are stripped before TTS.
- **Mic** uses the separately configured STT provider (`paste` by default; `VoiceStudio` for local ASR). Echo-guard blocks mic/STT while TTS is playing so speaker output is not treated as user input.

## STT (separate)

Under **Instellingen → Spraak → Spraakherkenning**:

| Provider | Behavior |
|----------|----------|
| `paste` | Existing Tasks / `/voice` / local-stt-paste workflow |
| `voicestudio` | `POST /v1/audio/transcriptions` + chat mic |
| `none` | Disabled |

## Memory discipline (16 GB class hosts)

- HADES refuses a TTS request when free RAM is below `tts_min_free_ram_mb` (default 1500).
- Optional VRAM floor via `tts_min_free_vram_mb` / engine `min_vram_gb` when `nvidia-smi` is available.
- No automatic LM Studio model unload or swap.

## Incremental speech honesty

VoiceStudio’s OpenAI-compatible speech endpoint returns a **complete** audio clip per request. HADES can enable **zinsgewijze** sequential requests for earlier first audio; that is **not** provider PCM/SSE streaming.

## Recovery when VoiceStudio is down

The Spraak panel and speech API return explicit recovery actions (start plugin, open UI, check base URL). Text chat remains usable.

## Automated vs hardware tests

See `docs/CURRENT_STATUS.md` and `backend/tests/test_speech_voicestudio.py` for what is automated. Audible Dutch playback, first-audio latency on your GPU, and live LM Studio model switching while speaking require a workstation with VoiceStudio + speakers.
