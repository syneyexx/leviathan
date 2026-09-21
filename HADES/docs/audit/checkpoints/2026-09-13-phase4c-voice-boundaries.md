# HADES ASTRA Audit — Phase 4C Voice / Privileged Route Boundary

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-038 — Voice installer bypasses network/subprocess policy

- Severity: HIGH / privileged local execution and network trust boundary.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `POST /api/voice/install` called `voice.install.run_install()` directly. `run_install()` may execute `python -m pip install -r ...` and may download Whisper/Piper assets over the network.
- Policy mismatch: HADES has explicit `network_policy` and `subprocess_policy` settings; the route previously inspected neither policy and its request model had no explicit approval flags.
- Fix: `InstallInput` now has independent `approved_network` and `approved_subprocess` flags. The route enforces `subprocess_policy` for dependency installation and `network_policy` for dependency/model retrieval before `run_install()` is invoked. `block` is absolute; `ask` requires the matching explicit approval flag.
- UI/API contract: the Voice setup wizard and Voice settings install button now send the two approval flags from the explicit user installation action. The Voice API wrapper supports the typed object request and does not auto-promote legacy array calls into approval.
- Regression coverage: `backend/tests/test_voice_install_policy_boundary.py` now permanently checks subprocess block, network block, both `ask` cases without approval, and the explicitly approved `ask` path. `run_install()` is mocked in all tests, so no subprocess or network side effect is executed.
- Production commit: `32a11cf31935c3c55f77a01f93f4f4cf922cd84b`.
- Diff review: exactly five intended files changed in the production commit: route, regression test, Voice API wrapper, setup wizard and settings panel. No unrelated file drift was present.
- Validation boundary: canonical/full suite, Windows host execution, actual pip install and actual model download were not run in this environment.

## F-2026-09-13-039 — Voice install step selection could trigger unintended full install or false success

- Severity: MEDIUM/HIGH / privileged install honesty and side-effect control.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause 1: `run_install()` used `steps or ["deps", "whisper", "piper_voice"]`, so an explicitly supplied empty list triggered the full default dependency/model installation instead of performing no requested step.
- Root cause 2: arbitrary unknown step names were silently ignored; if the existing voice doctor was already healthy, a request such as `steps=["bogus"]` could return `ok=true` even though the requested operation did not exist.
- Fix: `None` alone selects the existing default install set. Explicit empty selections return `ok=false,error=no_install_steps`. Unknown names return `ok=false,error=unknown_install_steps` plus known/unknown step metadata before any pip/model/download side effect occurs.
- Production commit: `e67d12ad63a5d3e57af543856ad4b5a6e5f49315`.
- Diff review: only the valid-step constant and fail-closed selection validation changed; provider/download/pip execution logic was untouched.
- Regression coverage: `backend/tests/test_voice_install_step_validation.py`; characterization commit `b60eb8baf8c4a42dbdb2590634749791ffda3b42`, promoted to permanent gates in `def11440ce21264fd86e17fabc38d32270d31276`.

## Input-size review — candidate only, not a finding

- Voice JSON transcription accepts `audio_base64` without an explicit max length, and upload transcription reads the entire upload into memory.
- No repository-wide voice/audio byte-limit contract was found in the focused search.
- Because selecting a byte limit would introduce new product policy, no Category-A/B fix or finding number was created in this slice. Revisit during performance/adversarial API-boundary review with an evidence-backed limit.

## Additional reviewed boundaries with no new finding

- Current VoiceStudio TTS sync-to-async bridge is safe against `asyncio.run()` inside an already-running loop: coroutine creation is deferred to the loop/thread that awaits it. The older audit issue is not reproducible in current main.
- Speech VoiceStudio STT is async end-to-end; HTTP failures raise and empty transcript is reported `ok=false`.
- `folder_picker.py` uses a constant PowerShell script, passes user-visible title through environment, and invokes with `shell=False`; no command-concatenation injection was found.
- Production search found no `shell=True` subprocess invocation; the immutable security invariant remains consistent with current code.

## Validation honesty

- No canonical/full suite was run.
- F-038 and F-039 have production code + permanent focused regression tests, but remain FULL-SUITE UNVERIFIED.
- No CI polling was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
