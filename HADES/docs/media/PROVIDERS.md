# Media Providers

| Provider | Role | Baseline |
|---|---|---|
| LLM (HADES model) | Script/critics/hypothesis | Required for creative stages |
| faster-whisper / official captions | ASR | Captions preferred; ASR optional |
| HADES voice / Piper / VoiceStudio | TTS | Optional; plan-only if unbound |
| FFmpeg | Edit + render | Required for local masters |
| Text graphics / image providers | Visuals | Text/motion works without ComfyUI |
| ComfyUI / video models | Optional generation | `SETUP_REQUIRED` until configured |
| Trend providers | Evidence signals | Local seed + history + optional web research |

Unsupported metrics stay absent/`None` — never coerced to zero.
