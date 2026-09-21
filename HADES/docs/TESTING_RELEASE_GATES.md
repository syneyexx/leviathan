# HADES testing and release gates

## Canonical entrypoint (Cursor / CI / human)

From repository root (cross-platform):

```bash
python verify_hades.py
```

Quick (skip production build):

```bash
python verify_hades.py --quick
```

Backend-only:

```bash
python verify_hades.py --python-only
```

On Windows after `PREPARE_HADES.bat`:

```bat
VERIFY_HADES.bat
```

`PREPARE_HADES.bat` is the Windows preparation/setup gate. It validates the declared Node/Python minimums, installs dependencies, attempts the native runtime with the documented Python fallback, and runs TypeScript, ESLint, production build, canonical frontend release tests and the backend unittest suite. A native build failure may remain a warning in PREPARE because `native_runtime_mode=auto` supports Python fallback.

`VERIFY_HADES.bat` calls `verify_hades.py` with the prepared venv and is the canonical full Windows release gate. It adds the mandatory native CMake/CTest/install gate plus Ruff boundary lint, Gen2 offline evals, OpenAPI/generated-TypeScript drift checking and the informational sandbox capability dump. Treat a release as failed if any deterministic full-gate stage fails.

**CI:** `.github/workflows/release-gates.yml` defines two jobs on `ubuntu-latest` and `windows-latest` with lockfile installs (`npm ci`, `pip install -r backend/requirements.txt`):

| Job | Command | Meaning |
|---|---|---|
| `quick-gates` | `python verify_hades.py --quick` | Developer gate only — skips the production frontend build, **not** full release validation |
| `release-gates` | `python verify_hades.py` | Canonical deterministic full release gate |
| `release-gates-required` | aggregate job | Stable branch-protection context; passes only when both mandatory matrices pass |

**Node/Python matrix:** Node.js **22.13** (matches `package.json` `engines.node >=22.13.0`); Python **3.12** in CI. Windows PREPARE supports Python **>=3.11** as documented and now enforces that minimum both for PATH Python and a reused backend venv.

**Important:** `npm test` is the **frontend** gate only (typecheck + build + node contract/UI tests). It does **not** run the Python suite. Do not treat `npm test`, PREPARE, or `quick-gates` alone as a complete HADES release verification.

**Lint honesty:** `npm run typecheck` is `tsc --noEmit`. `npm run lint` is a real
ESLint flat-config gate (`eslint . --max-warnings 0`) and is **not** an alias for
typecheck. Both run in PREPARE and in `verify_hades.py` frontend paths.

**Remaining admin (may be BLOCKED_EXTERNAL):** require the stable `release-gates-required` status check on `main`; resolve GitHub Actions billing/spending/runner limits if CI jobs never start. Do not protect `main` with a matrix-child name in place of the stable aggregate context.

## What the full gate covers

1. TypeScript (`npm run typecheck`)
2. ESLint (`npm run lint` — real ESLint, not typecheck)
3. Production frontend build (`npm run build`) unless `--quick`
4. Canonical top-level frontend release tests (`tools/run_frontend_release_tests.mjs`)
5. Native CMake configure/build, CTest and install into the repository runtime prefix
6. Full backend `unittest discover -s backend/tests` (unit, integration, gen2, control/hardcode audit, settings contract drift, agents, plugins, coding jobs, …)
7. Targeted Ruff lint for security/execution-boundary modules
8. Gen2 offline eval release gate (`python -m evals.gen2_release_gate`)
9. OpenAPI/generated TypeScript contract drift check (`tools/export_openapi.py --check`)
10. Host sandbox capability dump (informational — missing hardware is `UNVERIFIED_ON_HOST`, never auto-PASS)

## Frontend lint honesty

In `package.json`, `"typecheck"` runs `tsc --noEmit` and `"lint"` runs `eslint . --max-warnings 0`.
They are intentionally separate gates.

## Fast focused checks

### Backend
```bash
python -m unittest discover -s backend/tests -v
```

On the prepared Windows runtime:

```bat
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

### Frontend source contracts
```bat
node --test tests\source-contracts.test.mjs tests\ui-components.test.mjs tests\voice-ui-contracts.test.mjs tests\voice-playback-queue.test.mjs tests\voice-audio-capture.test.mjs tests\voice-ui-ssr.test.mjs
```

### TypeScript
```bat
npm run typecheck
```

## Required test style by change

- Bug fix: add a regression test that fails before the fix where feasible.
- DB change: migration test using an existing/older schema shape.
- Plugin lifecycle: assert real health/failure semantics, not only process spawn.
- Permission change: test `allow`, `ask`/approval and `block` precedence.
- Reasoning/tool routing: test invalid model JSON, unavailable tool, blocked tool and failed tool result.
- Research parser: fixture for the new file/source type + chunk/provenance assertion.
- UI/API contract: typecheck plus build; add focused behavior/component test when practical.
- Control Plane: new behavioral hardcodes must be classified or migrated — `test_hardcoded_limit_detector` fails on unclassified findings.
- Settings ceilings: `int | None` / `number | null` Unlimited semantics must stay aligned (`test_settings_contract_drift`).
- Broader API contracts: Gen2 mission/eval/committee/capability + agent status/planned + coding `JobStatus` (`test_api_contract_drift`).
- Focused OpenAPI/TS transport contracts: regenerate with `python3 tools/export_openapi.py`; CI/verify runs `--check` (`contracts/openapi.json`, `lib/generated/api-contracts.ts`).

## Host honesty

Physical Windows Job Objects/AppContainer, live LM Studio, live VoiceStudio/audio, and live Puppeteer must **never** be reported PASS solely because a Linux mock or simulation succeeded. Use `UNVERIFIED_ON_HOST` when hardware/services are absent.

Optional host probes (`python verify_hades.py --host` / `--lm-studio` / `--browser` / `--voice` / `--sandbox`) write `host_capability_matrix.json`. Status vocabulary:

| Status | Meaning |
|---|---|
| `PASS` | Operationally tested with usable evidence on this host |
| `FAIL` | Probe ran and enforcement/assertion failed |
| `SKIPPED` | Intentionally not selected for this run |
| `UNAVAILABLE` | Capability implemented but not Ready/installable here (e.g. plugin not Ready) |
| `UNVERIFIED_ON_HOST` | Missing hardware/provider or probe incomplete — not a release failure |
| `DEGRADED` | Transport/deps reachable but inference/fixture quality insufficient (e.g. HTTP 200 empty completion) |
| `SIMULATED_ONLY` | Simulation path only; not operational proof |

Rules of thumb:
- LM Studio: transport reachability ≠ successful inference; empty `choices`/content is not PASS.
- Browser: PluginManager live invoke against a local fixture page required for PASS; manifest alone is never PASS.
- Voice: deps/modelcache, ASR WAV fixture, TTS playable file, physical mic, and physical playback are separate axes.

## Release evidence

Before merging to `main`, record in `docs/CURRENT_STATUS.md`:
- exact tests run,
- pass/fail counts,
- platform used,
- known untested paths,
- migration/rollback notes if applicable.

Do not turn a missing test environment into a claim that the feature passed.
