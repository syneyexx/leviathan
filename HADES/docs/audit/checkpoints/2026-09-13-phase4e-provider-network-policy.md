# HADES ASTRA Audit — Phase 4E Provider Network Policy

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-041 — Remote VoiceStudio endpoint bypasses network_policy=block

- Severity: HIGH / outbound provider policy consistency.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Existing HADES semantics: loopback provider endpoints are allowed while `network_policy=block`, but non-loopback endpoints are blocked. LM Studio and managed MCP explicitly implement that distinction.
- Root cause: `speech.voicestudio_client.normalize_base_url()` accepts arbitrary base URLs. `SpeechRuntime.settings_from()` normalized TTS/STT URLs but did not carry or enforce `network_policy`; status/synthesis/transcription could therefore construct VoiceStudio clients for configured external endpoints.
- Fix: `SpeechRuntime` now carries the explicit `network_policy` value and applies a fail-closed external-endpoint guard when it is exactly `block`. Only explicit HTTP(S) loopback hosts/literals (`localhost`, `.localhost`, loopback IPs) remain eligible. Remote TTS status/probe and direct STT execution are rejected before client construction; TTS begin also rejects before creating a generation.
- Compatibility boundary: missing policy values and `ask`/`allow` retain their previous behavior in this patch. This finding was specifically the `network_policy=block` bypass; no new approval protocol was invented for `ask`.
- Regression coverage: `backend/tests/test_speech_network_policy.py` is now permanent and covers remote TTS rejection before client construction, loopback TTS preservation under block, and direct remote STT rejection before client construction. All clients are mocked; no real network I/O occurs.
- Production commit: `ae47bee1b8d2c74485befc8d4ebdd3415b2ec75f`.
- Diff review: exactly two intended files changed: `backend/speech/runtime.py` and `backend/tests/test_speech_network_policy.py`.

## Validation honesty

- No canonical/full suite was run.
- F-041 has production code + permanent focused regression tests, but remains FULL-SUITE UNVERIFIED.
- No actual VoiceStudio server or external network endpoint was contacted.
- No CI polling was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
