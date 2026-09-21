# Milestone 2 — reliable job control, generalized investigate, browser evidence

Base: `5bdf9bb` (Milestone 1 / PR #37)

## Dependency order executed

1. **Delivery 1** Coding-job control contract (pause/resume/cancel/redirect/recovery/reconnect)
2. **Delivery 2** Investigate workspace isolation, model selector, generalization, budgets, LSP scope, hypotheses
3. **Delivery 3** BrowserAdapter ↔ PluginManager, user flows, evidence binding, reviewer extra checks
4. **Delivery 4** Benchmark measurement kinds, independent eval tasks, strategy compare, candidates, fault timeline

Preservation: additive only — see `docs/architecture/milestone1-preservation-inventory.json` (still valid; no removals).

## What was added / corrected

| Area | Change | Wired into |
|---|---|---|
| Job control | `coding_job_control.py` + executable transitions; pause only at checkpoints; resume dispatches worker; versioned instructions; sequenced events; recovery payload | `coding_jobs.py`, `/build/jobs/*` |
| Investigate | Isolated `work_root` for tests; Control Plane budgets; model selector; signal-based search; hypotheses; context sources | `coding_investigate.py`, `coding_agent.py` |
| LSP | `language_servers.py` scoped defs/refs/diagnostics with lsp_light fallback | investigate + impact |
| Browser | PluginManager-backed open/screenshot/flow; honest unavailable | `preview_runtime.py`, `/browser/*` |
| Quality | H01–H03 measurement kinds; independent E01–E08 tasks; candidate compare; fault timeline | `evals/*`, `coding_candidates.py`, `coding_timeline.py` |
| UI | Persisted/reconnectable job id, recent jobs, resume button, no timeout=klaar, instruction status | Coding Agent page |

## How to use

1. Coding Agent → strategy `investigate` (optional selector `model`) → enable **Achtergrondjob**.
2. Pause / Bijsturen / Annuleer / **Hervat** from the job panel; refresh restores the same job via sessionStorage + `?codingJob=`.
3. Eval Lab: `hard` now reports `by_measurement`; independent suite via `evals.independent_tasks`.

## Preserved

- Fast / investigate / auto strategies; sync `/build/goal` + async jobs
- Manual edits + repair_waves
- Q01–Q42 / H01–H03 scenarios; legacy search pattern retained as compatible fast path
- PreviewManager plan/start/stop API unchanged
- Visual identity / navigation unchanged

## Verification (this delivery)

- `python3 -m unittest tests.test_reliable_coding_jobs_m2 tests.test_milestone1_quality_investigate_jobs tests.test_phases_d_to_l` → PASS
- Live LM Studio / physical Windows / live Puppeteer screenshot on host: **not claimed**

## Still open / not verified here

- Full language servers when pyright/tsserver absent (regex fallback used)
- Live browser fill/click when puppeteer plugin not Ready
- Full independent eval suite green under investigate heuristics for all E01–E08
- Physical Windows host VERIFY
