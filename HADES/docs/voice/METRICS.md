# Voice conversation metrics (reference)

Environment: _fill on Windows host_  
Date: _unknown_  
Hardware: _unknown_  
ASR model: base (default) · TTS: Piper nl_NL-pim-medium

| Metric | Value |
|---|---|
| Mic ready (ms) | unknown |
| First partial transcript (ms) | N/A (final-only utterance mode) |
| End-of-turn → final text (ms) | unknown |
| First spoken response audio (ms) | unknown |
| Interrupt → audio stop (ms) | unknown (target ≤250) |
| NL transcript error rate (fixture set) | unknown |
| False triggers (silence) | unknown |
| False triggers (own TTS / speakers) | unknown |
| CPU / RAM during conversation | unknown |
| GPU usage | unknown |

API mirror: `GET /api/voice/metrics/reference` returns `null`/`unknown` until host fill-in.

## Transcriptiemodus

Chat Spraak-modus werkt **final-only**: de browser stuurt complete utterances na VAD/PTT-einde (geen streaming MediaRecorder-chunks).  
`first_partial_ms` is daarom N/A tot een echte rolling-PCM partial path bestaat.
