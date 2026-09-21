# Frontier Hardening Audit (Phase 0)

**Branch:** `cursor/frontier-portfolio-hardening-111b`  
**Base SHA:** `19371f444f38fe2f425538fda9f4d3856765d457`  
**Baseline artifact:** `artifacts/baselines/frontier_hardening_before.json`  
**Host of evidence:** Linux Cloud Agent (Windows = first-class target, Job Objects `UNVERIFIED_ON_HOST`)  
**Live LM Studio:** `UNAVAILABLE` on this host

Status axes (do not collapse): Implementation / Integration / Operational availability / Quality.

---

## 1. Repository reality (measured)

| Metric | Value |
|---|---|
| Python LOC (backend) | ~98.9k |
| TypeScript LOC | ~30.4k |
| Backend unittest cases (loader) | see baseline JSON |
| Gen2 unittest cases | see baseline JSON |
| Release-gated deterministic eval | 10 reasoning + 3 red-team = **13** |
| Offline software scenarios (approx) | ~46 across quality/reasoning/domain/RT |
| Portfolio demos | 3/3 PASS (pre-change) |
| `npm run lint` | Real ESLint flat-config gate (`eslint . --max-warnings 0`) — separate from typecheck |
| Largest hotspot | `backend/main.py` (~5939 LOC) |

Docs claim Gen2 spines and Monster checklist ticks with mixed evidence classes. That matches code: many systems are **implemented/integrated**, not fully **operationally verified** or **quality-measured**.

---

## 2. Authoritative execution-path findings

Production side effects do **not** all share one kernel. Best-gated path today:

Chat/Work tool loop → `reasoning/tool_engine.py` → G11/G8 → `enforce_plugin_permissions` → `PluginManager.invoke` → toolcall persistence → Work `decide_work_task_completion`.

### Ranked issues (at audit start)

| ID | Severity | Issue | Evidence | Portfolio impact | Impl risk |
|---|---|---|---|---|---|
| P0-1 | **P0** | `invocation_type in {install,system}` skipped G11/G8 inside `PluginManager.invoke`; workflow could set it | `platform_services_core.py` invoke; `workflow_adapters._adapt_plugin_invoke` | Critical — policy bypass | Low |
| P0-2 | **P0** | Chat harvest under `network_policy=ask` ran without approval | `chat_commands.maybe_handle_chat_command` | Critical — approval parity | Low |
| P0-3 | **P0** | `ImportError` on policy import was fail-open (`pass`) | invoke + tool_engine | Critical — silent bypass | Low |
| P0-4 | **P0** | Plugin `_run_command` not wired to `execution_isolation.run_isolated` | Only terminal uses isolation | High — sandbox honesty | Medium |
| P1-1 | **P1** | Coding/build/voice/preview/LSP subprocess outside PluginManager | Multiple modules | High | Medium–High |
| P1-2 | **P1** | Deterministic release gate corpus only 13 cases | `evals/gen2_release_gate.py` | High for reviewers | Medium |
| P1-3 | **P1** | No real ESLint gate | `package.json` lint≡tsc | Medium honesty | Low |
| P1-4 | **P1** | Schedule occurrence marked completed when task merely started | `TaskRunner.schedule_ticker` | Medium false-success | Low |
| P2-1 | **P2** | Megafile hotspots impede review | main/platform_* | Maintainability | High if rushed |
| P2-2 | **P2** | Context Compiler opt-in; no shadow A/B evidence for default flip | Gen2 docs | Quality | Medium |
| P2-3 | **P2** | True token streaming not productized | CURRENT_STATUS / lm_studio | Product | Medium |
| P2-4 | **P2** | Temporal graph / Flight Recorder replay still partial | Gen2 gap analysis | Architecture | Medium |
| EXT-1 | External | Windows secured FS/network isolation | execution_isolation honesty | Must stay UNVERIFIED until host proof | — |
| EXT-2 | External | Live LM Studio quality | provider absent | UNMEASURED | — |

---

## 3. Immediate remediation started (this program)

1. Added `backend/runtime/execution_gateway.py` — fail-closed policy helpers + privileged-skip contract.
2. Closed P0-1: `privileged_policy_skip` required; workflow rejects install/system.
3. Closed P0-2: harvest under `ask` returns `APPROVAL_REQUIRED` without calling harvest.
4. Closed P0-3: ImportError fail-closed in PluginManager + tool_engine.
5. Added architectural invariant tests: `tests/test_frontier_execution_invariants.py`.
6. Baseline harness: `tools/measure_frontier_baseline.py`.

---

## 4. Program backlog (continue autonomously)

Order follows the task brief, adjusted by evidence:

1. Expand adversarial + deterministic eval corpus toward 100+ meaningful cases; raise release gate mins carefully.
2. Hostile security suite (FS/archive/network/MCP/approvals/secrets).
3. Wire plugin `_run_command` to isolation when secured; keep Windows honesty.
4. Effect ledger / crash-resume tests; schedule false-success fix.
5. Real ESLint + selective Ruff/mypy on security boundaries.
6. Incremental megafile extraction with characterization tests.
7. Context Compiler shadow mode; claim/evidence deepen.
8. Streaming protocol; Playwright E2E fixtures.
9. Portfolio demos 4–6; reviewer docs; threat model update; after baseline.

---

## 5. Honesty constraints for this program

- Do not mutate `frontier_hardening_before.json` numbers.
- Do not report Windows isolation PASS on Linux.
- Do not report LM Studio quality PASS when UNAVAILABLE.
- Do not call simulated red-team cases “live model quality.”
- Prefer FAIL / PARTIAL / UNVERIFIED_ON_HOST / UNAVAILABLE / UNMEASURED over fake PASS.
