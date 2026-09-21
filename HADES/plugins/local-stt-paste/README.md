# Local STT Paste — HADES plugin

Offline-first helper for **pasted** speech-to-text output. This plugin does **not** perform speech recognition and does **not** call cloud STT APIs.

> Scope note: HADES Chat also has a separate built-in local voice mode (`backend/voice`, faster-whisper + Piper). This plugin remains the paste-only path for Spraak→taak and does not replace that mic/ASR session.

## Workflow

1. Run speech-to-text with your preferred **local** tool (OS dictation, Whisper, VoiceStudio ASR, Chat Spraak-modus, etc.).
2. Paste the transcript into HADES **Tasks → Spraak → taak**, chat `/voice <transcript>`, or invoke `transcribe_paste`.
3. Review the proposed task, then create/start via the Tasks UI or `POST /api/voice/to-task` (`create=true`, optional `auto_start=true`).

## Relation to VoiceStudio and Chat Spraak

| Piece | Role |
|------|------|
| **Chat Spraak-modus** | Built-in mic ASR/TTS for conversation (not this plugin). |
| **VoiceStudio** | Optional external ASR/TTS UI (Docker). |
| **local-stt-paste** | Paste/validate transcript → task suggestion. |

## Tools

| Tool | Purpose |
|------|---------|
| `doctor` | States offline/paste-only scope (no bundled STT in this plugin). |
| `transcribe_paste` | Validates `{transcript}` and prints `{ok, transcript, suggestion}` JSON. |

## Install

HADES → **Plugins** → import folder `plugins/local-stt-paste` (or build `.HadesPlugin` with `pack_hadesplugin.py` when added).
