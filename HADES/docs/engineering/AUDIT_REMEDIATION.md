# HADES Audit Remediation (A01–A14)

## Baseline

| Field | Value |
|---|---|
| Audit reference | `syneyexx/HADES` main `6c4b7112af7d7dc45741af8c2681d5e6f4586739` (2026-09-09) |
| Start commit (this work) | `6c4b7112af7d7dc45741af8c2681d5e6f4586739` |
| Feature branch | `cursor/audit-remediation-a01-a14-7ab4` |
| Platform (agent host) | Linux 6.12 (Cloud Agent); Windows = first-class target, host evidence separate |
| Working rule | Do not restore old code to mimic the audit; re-verify against current source |

## Status legend

- **OPEN** — defect confirmed or work not started
- **IN_PROGRESS** — actively implementing
- **IMPLEMENTED_UNVERIFIED** — code landed; tests/evidence incomplete
- **VERIFIED** — implementation + real route + evidence on this host
- **BLOCKED_EXTERNAL** — needs human auth / unavailable hardware / billing
- **SKIPPED / UNAVAILABLE / UNVERIFIED_ON_HOST** — honest non-claim

## Resume checkpoint

- Branch: `cursor/audit-remediation-a01-a14-7ab4`
- Tip: see `git log -1 --oneline`
- Last focus: A05 CI Node/matrix + honest gates; full A01–A14 implementation pass
- Next external: Windows host FS isolation / Job Objects; live LM Studio quality; GitHub Actions billing + branch-protection require `release-gates`

---

## Summary table

| ID | Implementation | Integration | Verification |
|---|---|---|---|
| A01 | VERIFIED (harness+dataset) | VERIFIED (production_route adapter) | VERIFIED software/wiring; live UNMEASURED |
| A02 | VERIFIED (linux userns) | VERIFIED (PolicyTerminalService) | VERIFIED on Linux; Windows FS UNVERIFIED_ON_HOST |
| A03 | VERIFIED | VERIFIED (mission sync + ArtifactService) | VERIFIED unit/integration |
| A04 | VERIFIED | VERIFIED (matrix v2 + best_model_for) | VERIFIED unit |
| A05 | VERIFIED (CI/docs) | VERIFIED (workflow+status) | Local gates runnable; remote CI BLOCKED_EXTERNAL if billing |
| A06 | VERIFIED | VERIFIED (GUI execute) | VERIFIED unit; Windows GUI host UNVERIFIED |
| A07 | VERIFIED | VERIFIED (services/routes) | VERIFIED unit; UI host UNVERIFIED |
| A08 | VERIFIED | VERIFIED (chat path opt-in) | VERIFIED unit/mocked; live embed UNMEASURED |
| A09 | VERIFIED | VERIFIED (plugin+tool+chat) | VERIFIED unit |
| A10 | VERIFIED | VERIFIED | VERIFIED focused suite |
| A11 | VERIFIED | VERIFIED | VERIFIED focused suite |
| A12 | VERIFIED (targeted) | VERIFIED | VERIFIED lifecycle tests + baseline artifact |
| A13 | VERIFIED (experiment) | VERIFIED | VERIFIED software experiment; live UNMEASURED |
| A14 | VERIFIED (docs/demos) | VERIFIED | VERIFIED demos 3/3 |

---

## A01 — Evaluations that measure the real agent

| Field | Value |
|---|---|
| Reproduction | Harness was honesty/dry-run; no production-route agent scoring CLI |
| Desired outcome | CLI runs real HADES production route; layered reports; holdout protected |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (software); live UNMEASURED |
| Evidence | `backend/evals/agent_eval.py`, `production_route.py`, `agent_tasks.py`, `agent_judges.py`, `release_thresholds.py`; `docs/engineering/EVAL_RELEASE_THRESHOLDS.md`; `backend/tests/test_agent_eval_a01.py`; `artifacts/eval_runs/`, `docs/evidence/eval_runs/` |
| Command | `cd backend && python -m evals.agent_eval --mode executable --split holdout` |

## A02 — Real execution isolation

| Field | Value |
|---|---|
| Reproduction | `python -c open(outside)` escaped while `cat` blocked |
| Desired outcome | Secured FS/net/env isolation; fail closed; trusted explicit |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (Linux); Windows FS UNVERIFIED_ON_HOST |
| Evidence | `backend/execution_isolation.py`, `backend/terminal_tool.py`, `backend/tests/test_audit_a02_a03_a04.py` |

## A03 — Artifacts, acceptance, honest success

| Field | Value |
|---|---|
| Reproduction | Name-only evidence_refs counted as present; defaults required=False |
| Desired outcome | ArtifactService.verify_ready bytes/checksum/ready; required deliverables hard-gate |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `backend/gen2/mission_control.py`, tests in `test_audit_a02_a03_a04.py`, `test_gen2_mission_depth.py` |

## A04 — Clean metrics and model routing

| Field | Value |
|---|---|
| Reproduction | Fake 1.0 metrics; dishonest substring smoke; smoke→empirical_matrix routing |
| Desired outcome | null+reason; strict smoke; provenance matrix; smoke excluded from recommendations |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `backend/gen2/eval_lab.py`, `backend/gen2/store.py` migration 13, `test_audit_a02_a03_a04.py` |

## A05 — Release gates, install, status docs

| Field | Value |
|---|---|
| Reproduction | CI Node 20 vs engines >=22.13; “161/161 100%”; quick presented as full; CI billing red |
| Desired outcome | Aligned Node/Python matrix; quick≠full; honest status axes; logs retained |
| Impl / Integration / Verify | VERIFIED / VERIFIED / Local runnable; remote CI may be BLOCKED_EXTERNAL (billing) |
| Evidence | `.github/workflows/release-gates.yml` (Node 22.13; quick-gates + release-gates); `docs/CURRENT_STATUS.md` vocabulary; `docs/TESTING_RELEASE_GATES.md` |
| Remaining admin | Require status check `release-gates` on main; resolve Actions spending limit |

## A06 — Workflows / Agent Factory executable

| Field | Value |
|---|---|
| Reproduction | Fake coding template +8 tokens; live_execution=False but passed=True |
| Desired outcome | Real CodingAgent/Research/Plugin adapters; dry-run≠product |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (unit) |
| Evidence | `workflow_adapters.py`, `workflow_executor.py`, `test_audit_a06_workflows.py` |

## A07 — Meaningful replan / recovery

| Field | Value |
|---|---|
| Reproduction | Counters only; waves unchanged |
| Desired outcome | Contentful wave rebuild by cause; permission never tool-swaps |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (unit) |
| Evidence | `rebuild_execution_waves_for_replan`, `test_audit_a07_replan.py` |

## A08 — Retrieval, embeddings, context

| Field | Value |
|---|---|
| Reproduction | `_embed→None`; compiler unused by chat; hierarchical stub |
| Desired outcome | Local embeddings; chat wiring; lexical fallback; honest stubs |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (mocked); live embed UNMEASURED |
| Evidence | `backend/embeddings.py`, `reasoning/chat_context.py`, `test_audit_a08_embeddings_context.py` |

## A09 — Controls on all real execution paths

| Field | Value |
|---|---|
| Reproduction | G11/G8 Gen2-only; stop_and_ask metadata-only |
| Desired outcome | Same deny on plugin/tool/chat; real stop-and-ask wait |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `backend/policy_enforcement.py`, tool_engine + PluginManager + send_message, `test_audit_a09_policy_paths.py` |

## A10 — Meaningful product / recovery tests

| Field | Value |
|---|---|
| Reproduction | Source-string product claims |
| Desired outcome | Behavior/crash/recovery tests |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `backend/tests/test_audit_a10_product_recovery.py`, `docs/engineering/A10_PRODUCT_RECOVERY_TESTS.md` |

## A11 — Telemetry, evidence, reproducibility

| Field | Value |
|---|---|
| Reproduction | Correlation not ubiquitous; fake tokens risk |
| Desired outcome | Stable IDs, honest usage, export + summary |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `docs/engineering/A11_TELEMETRY_REPRODUCIBILITY.md`, `test_audit_a11_telemetry.py` |

## A12 — Architecture and performance

| Field | Value |
|---|---|
| Reproduction | Large hotspots; lint≡tsc mislabel risk |
| Desired outcome | Targeted extractions; lifecycle ownership; honest lint docs |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED |
| Evidence | `backend/run_lifecycle.py`, `docs/architecture/lifecycle-ownership.md`, `test_audit_a12_lifecycle.py`, baseline JSON |

## A13 — Reliable resume experiment

| Field | Value |
|---|---|
| Reproduction | Ledger not fully on Work Runtime |
| Desired outcome | Controlled with/without recovery experiment |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (software); live UNMEASURED |
| Evidence | `docs/engineering/A13_RELIABLE_RESUME_EXPERIMENT.md`, `docs/evidence/resume_experiment/`, `python -m evals.resume_experiment` |

## A14 — Reviewable portfolio delivery

| Field | Value |
|---|---|
| Reproduction | NL quickstart only; no demos |
| Desired outcome | EN portfolio + 3 demos + report + honest limits |
| Impl / Integration / Verify | VERIFIED / VERIFIED / VERIFIED (demos 3/3) |
| Evidence | `README.md`, `docs/demos/*`, `docs/engineering/PORTFOLIO_REPORT.md`, `docs/archive/planning/CHANGELOG_AUDIT_REMEDIATION.md` |
