# Coding Agent — operator setup

Surface: **`/coding`** (submenu: Coding Agent under Hades AI).

## Flags

```bash
LEVIATHAN_FEATURE_AGENTS=true
LEVIATHAN_FEATURE_CODING=true
```

CODING requires AGENTS. Both default **false**. If CODING is on and AGENTS is off, settings validation raises `ConfigurationError`.

## Workspace

```bash
LEVIATHAN_CODING_WORKSPACE=D:/leviathan/codingworkspace
```

Default matches the operator Windows path. On CI/Linux, set this to a writable directory (tests use temp dirs).

**HADES is excluded.** Paths containing `HADES` / `Data/HADES` are rejected (`PathEscapeError` / gateway REJECTED).

## Loop bounds

| Env | Default |
|---|---|
| `LEVIATHAN_CODING_MAX_ROUNDS` | 12 |
| `LEVIATHAN_CODING_TOKEN_BUDGET` | 24000 |
| `LEVIATHAN_CODING_RESERVE_RESPONSE_TOKENS` | 1024 |
| `LEVIATHAN_CODING_MAX_FILE_CHARS` | 8000 |
| `LEVIATHAN_CODING_TEMPERATURE` | 0.1 |
| `LEVIATHAN_CODING_COMMAND_ALLOWLIST` | python,python3,pytest,npm,npx,node,git |

## Operator flow

1. Open `/coding` — empty honesty until a session exists (no fake metrics).
2. Enter a goal; optionally pick mission chip (Scaffold / Review / Write tests / Fix bug).
3. **Launch Agent** → `POST /api/coding/sessions` + `/turn` (returns immediately; worker runs rounds).
4. Poll session while `RUNNING` / `WAITING_APPROVAL`.
5. WRITE/EXECUTE pauses for approval — Approve/Deny via existing `/api/approvals/{id}/approve|deny`.
6. Diffs appear from `coding_patches`; tests via `coding.run_tests` (exit 0 required for PASSED).
7. Verification card: PASSED only with evidence; else UNMEASURED / UNVERIFIED.

## Truth

- Tool protocol: XML `<capability id="…">` in model content (not OpenAI tools[]).
- No private shell / filesystem / second database.
- Neuro signals are advisory only when NEURO is on.
- Residual unsupported → honest provenance, no fake inject.
