# VoiceStudio — HADES plugin

Installable `.HadesPlugin` wrapper around [VoiceStudio](https://github.com/debpalash/VoiceStudio) (local voice cloning / TTS / ASR studio, AGPL-3.0).

## How this complements HADES voice (honest scope)

| Piece | Role |
|-------|------|
| **Chat Spraak-modus** (`backend/voice`) | Built-in local mic ASR (faster-whisper) + TTS (Piper) for Chat dictation/conversation. |
| **VoiceStudio** (this plugin) | Optional local ASR/TTS service (Docker on `http://127.0.0.1:3900` or a desktop install). OpenAI-compatible audio API at `/v1`. |
| **HADES Instellingen → Spraak** | Built-in voice settings **and** VoiceStudio as swappable TTS/STT provider for spoken answers / optional mic. |

| **local-stt-paste** | Validates a **pasted** transcript and suggests a task draft (`transcribe_paste`). |
| **HADES Tasks / `/voice` / `POST /api/voice/to-task`** | Turns a transcript into a reviewable/created task (no ASR). |

Typical flows:

1. **Built-in chat voice:** Instellingen → Spraak (ingebouwd) → Chat → Dictatie / Spraakgesprek.
2. **Spoken answers via VoiceStudio:** start VoiceStudio → Instellingen → Spraak → TTS-provider `VoiceStudio` → kies stem → Chat → *Gesproken antwoorden* aan.
3. **Voice → task (paste):** run ASR in VoiceStudio (or OS dictation) → copy text → Taken → Spraak → taak (or `/voice …`).

HADES never silently falls back to a cloud TTS/STT provider. Text chat keeps working when VoiceStudio is offline.

## Documented API used by HADES

Only these OpenAI-compatible endpoints are used (verified against VoiceStudio `openai_compat.py`):

| Endpoint | Use |
|----------|-----|
| `GET /v1/audio/voices` | List voice profiles + engines / capability hints |
| `POST /v1/audio/speech` | TTS — complete audio clip per request (`mp3`/`wav`/…) |
| `POST /v1/audio/transcriptions` | Optional STT when STT-provider = VoiceStudio |

**Not claimed:** incremental PCM/SSE speech streaming. `POST /v1/audio/speech` returns a finished clip; HADES may optionally split sentences and request clips sequentially for earlier first audio.


## Install in HADES

1. Build the package:

```bat
python plugins\voicestudio\pack_hadesplugin.py --out plugins\voicestudio\dist
```

2. HADES → **Plugins** → **ZIP / .HadesPlugin**
3. Approve dependency install when prompted
4. Enable the plugin when status is Ready
5. Run tools from the Plugins page **or** point Instellingen → Spraak at `http://127.0.0.1:3900/v1`

## Tools

| Tool | Purpose |
|------|---------|
| `doctor` | Check Docker + document API endpoints |
| `api_probe` | Probe `GET /v1/audio/voices` |
| `start` | Start VoiceStudio Docker image on http://127.0.0.1:3900 |
| `health` | Run declared healthcheck |
| `status` | Service status |
| `logs` | Container logs |
| `stop` | Stop the managed container |
