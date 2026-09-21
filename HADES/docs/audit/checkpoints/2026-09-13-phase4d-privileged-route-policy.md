# HADES ASTRA Audit — Phase 4D Privileged Route Policy

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-040 — Native folder picker bypasses subprocess policy on Windows

- Severity: MEDIUM/HIGH / privileged local process policy consistency.
- Status: OPEN / CHARACTERIZED.
- Policy contract: Control defines `subprocess_policy` as `Permission for spawning subprocesses` with allow/ask/block and critical risk.
- Runtime path: `POST /api/plugins/pick-folder` calls `pick_directory()` directly. On Windows the preferred picker launches PowerShell with `subprocess.run(..., shell=False)` to show the native FolderBrowserDialog.
- Defect: the API route does not consult `subprocess_policy` before opening the picker. Therefore `subprocess_policy=block` does not prevent this subprocess launch.
- Scope nuance: the PowerShell invocation itself is injection-hardened (constant script, title through environment, `shell=False`). This finding is about policy enforcement, not command injection.
- Regression characterization: `backend/tests/test_folder_picker_subprocess_policy.py` patches runtime values to `subprocess_policy=block` and requires the route to reject before `pick_directory()` is called. Current test is `expectedFailure`.
- Characterization commit: `019d80778672a622ec3fe2037f8fb20d3d4bfcf6`.
- Required remediation: enforce subprocess allow/ask/block at the route boundary. For `ask`, require explicit approval rather than interpreting the existence of the UI action as a global policy override. Preserve non-Windows tkinter fallback semantics while keeping the policy contract consistent.
- Safe-edit constraint: the route lives in large `backend/main.py`; current GitHub connector replaces whole files rather than applying narrow patches, so no risky full-file rewrite was attempted.

## F-2026-09-13-042 — Terminal run route ignores subprocess_policy

- Severity: HIGH / direct command-execution policy bypass.
- Status: PARTIAL FIX / FULL-SUITE UNVERIFIED.
- Original defect: `POST /api/terminal/run` enforced `file_write_policy` because it persists a transcript artifact, but did not enforce `subprocess_policy` before terminal execution.
- Remediation completed for `block`: `PolicyTerminalService.run()` is the central execution boundary and already receives the live settings map from the route. It now rejects `subprocess_policy=block` before argv validation, cwd resolution or `run_isolated()` execution.
- Production commit: `432751f162a500ce3d8d2f1a9d1a458e4bf9fbf9`.
- Regression coverage: `backend/tests/test_terminal_subprocess_policy.py` now permanently requires block-mode rejection before `run_isolated()` is reached. The execution boundary is mocked; no subprocess is launched.
- Remaining gap: `subprocess_policy=ask` still lacks a dedicated invocation-scoped subprocess approval. Existing route field `approved` belongs to its current route contract and must not silently become subprocess approval. A second regression remains `expectedFailure` to prevent this remainder from being mistaken for a full fix.
- Scope nuance: existing argv allowlisting, shell-metacharacter rejection, cwd/path jail and secured-isolation fail-closed behavior remain unchanged.

## F-2026-09-13-045 — Preview start route ignores subprocess_policy

- Severity: HIGH / local dev-server process policy bypass.
- Status: OPEN / CHARACTERIZED.
- Runtime path: `POST /api/preview/start` passes path/run/kind directly to `PreviewManager.start_preview()`. When preview start is explicitly enabled through `HADES_PREVIEW_START=1`, `PreviewManager` can launch `npm run dev -- --host 127.0.0.1` with `subprocess.Popen`.
- Defect: the route does not enforce `subprocess_policy` before handing off to the process-starting manager.
- Scope nuance: preview process startup is separately disabled by default unless `HADES_PREVIEW_START=1`, and startup is not falsely equated with health; an explicit health probe is performed. This finding only concerns the global subprocess permission when preview start is enabled.
- Regression characterization: `backend/tests/test_preview_subprocess_policy.py` patches the preview manager and requires `subprocess_policy=block` rejection before `start_preview()` is invoked. Current test is `expectedFailure`; no npm process or dev server is started.
- Characterization commit: `635fe9a956d5bae5b72a3a6364b0a5b093cf3a77`.
- Required remediation: enforce subprocess allow/ask/block at the preview route boundary before manager invocation. Preserve the separate `HADES_PREVIEW_START` operational opt-in and the existing started-vs-healthy honesty contract.
- Safe-edit constraint: the route lives in large `backend/capability_routes.py`; no risky whole-file replacement was attempted.

## Validation honesty

- No canonical/full suite was run.
- F-040 and F-045 remain OPEN / CHARACTERIZED.
- F-042 has a reviewed production guard for `block`, while its dedicated `ask` approval contract remains open; therefore F-042 is PARTIAL rather than fixed.
- No CI polling was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
