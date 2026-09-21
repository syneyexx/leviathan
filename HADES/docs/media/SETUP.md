# Media Setup

1. Open **Media → Setup** (Capability Doctor).
2. Install FFmpeg on PATH if status is `SETUP_REQUIRED`.
3. Configure LM Studio / model for creative stages.
4. Optionally configure ASR (faster-whisper) and TTS (Piper/VoiceStudio).
5. Optionally set ComfyUI endpoint for image generation.
6. Connect platform OAuth credentials via HADES secure secret store (never paste tokens into project JSON).
7. Follow `MEDIA_SETUP_REQUIRED.md` for developer-portal actions.

Verify: create a channel with one or more platforms → Produce once → inspect pipeline artifacts → approve publish only after auth is real.
