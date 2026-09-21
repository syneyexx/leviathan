# Gen2 reliability — 50-point status

Investigated base: `6896fc3`. Working branch: `cursor/gen2-reliability-phase1-f8f7`.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Implementation matrix | uitgevoerd | `docs/architecture/gen2-implementation-matrix.md` |
| 2 | Regression tests for known defects | uitgevoerd | `tests.test_gen2_reliability` (+ continuation class) |
| 3 | Mission statuses honest | uitgevoerd | blocked/failed without task_id |
| 4 | Idempotent mission start | uitgevoerd | claim + concurrent test |
| 5 | Valid mission transitions | uitgevoerd | rejected gate / failed start guards |
| 6 | No fictional compute success | uitgevoerd | unsupported → failed |
| 7 | Sandbox path kinship | uitgevoerd | relative_to; sibling prefix denied |
| 8 | Empty/missing sandbox rules | uitgevoerd | empty allowlist / path/host required |
| 9 | Sandbox tier honesty | uitgevoerd | tier 2/3 blocked with fields |
| 10 | Envelopes at execution boundary | uitgevoerd | PluginManager gate |
| 11 | Missing/null/zero separation | uitgevoerd | harvest/repair/terminal/context/int validation; API harvest clamps via settings |
| 12 | Harvest defaults Unlimited | uitgevoerd | `_parse_harvest_limits` + crawler |
| 13 | Harvest slash + NL settings | uitgevoerd | settings passed both routes |
| 14 | Resolved reasoning profiles | uitgevoerd | `resolve_profile_config` in chat/tool path |
| 15 | Repair budgets Unlimited | uitgevoerd | `budget_from_profile` |
| 16 | Terminal timeout semantics | uitgevoerd | None ≠ silent 30s |
| 17 | Presets vs real resolution | uitgevoerd | apply_preset + `run_config_snapshot` + Limit Inspector |
| 18 | Limit Inspector explainability | uitgevoerd | configured/effective/clamp/source |
| 19 | Scope inheritance isolation | uitgevoerd | task scope leak test; Control Plane resolver |
| 20 | Registered unused settings | uitgevoerd | knowledge/crawl/plugins/MCP/codeindex/mentions/trading/approvals/build wired to registry |
| 21 | Hidden replacement limits | uitgevoerd | harvest API `le=` removed; trading/build hard clamps use settings; detector accepts registry |
| 22 | Config validation strengthen | uitgevoerd | reject non-whole floats (`1.9`); non-finite floats |
| 23 | Apply-modes executable | uitgevoerd | apply_preset groups + `run_config_snapshot` |
| 24 | Full Mission IR → Work | uitgevoerd | prompt + `replace_work_plan` steps/deps/budgets |
| 25 | Validate Mission IR | uitgevoerd | `validate_mission_ir` |
| 26 | Waves/gates on progress | uitgevoerd | TaskRunner mid-wave gates + pause; approve → resume running |
| 27 | Shared mission budgets | uitgevoerd | reservation/consume ledger + `/budgets` routes |
| 28 | Pause/resume reliable | uitgevoerd | mission pause/resume routes + Work Runtime pause events |
| 29 | Completion from evidence | uitgevoerd | `sync_mission_from_task` rejects completed+failed steps |
| 30 | Software vs model eval split | uitgevoerd | `not_model_quality` + `software:*` matrix ids |
| 31 | Real model eval route | uitgevoerd | live path via simulated LM client + API; blocked path without LM still honest |
| 32 | Metric-aware best_model_for | uitgevoerd | lower-better for latency/failures |
| 33 | Empirical routing checkable | uitgevoerd | `resolve_model` biases only on non-software empirical matrix |
| 34 | Committee real analysis | uitgevoerd | live mode via `run_committee_live`; without LM → honest heuristic fallback |
| 35 | Evidence support substantive | uitgevoerd | topical overlap required |
| 36 | Consensus from results | uitgevoerd | `basis=position_results` + support_ratio |
| 37 | Benchmark candidate workflow | uitgevoerd | workflow steps must pass |
| 38 | Promote binds version/hash | uitgevoerd | definition_hash check + version bump |
| 39 | Promoted skills reuse | uitgevoerd | `select_promoted_skill` → `route_agent` |
| 40 | Context full-content dedupe | uitgevoerd | hash full text + drop reason |
| 41 | Zero scores + validation | uitgevoerd | no `or` fallback; range checks |
| 42 | Token report vs returned content | uitgevoerd | used_tokens post-truncation |
| 43 | Full request budgeting | uitgevoerd | request/system/response reserves → context remainder |
| 44 | Context selection explainable | uitgevoerd | `selection_explain` + drop reasons |
| 45 | Flight Recorder diagnostics | uitgevoerd | `_diagnostics` severity/duration/correlation |
| 46 | Inspect vs replay | uitgevoerd | `inspection_not_replay` / no fake rebind |
| 47 | Compare run content | uitgevoerd | sources/payloads/verification diffs |
| 48 | Temporal search semantics | uitgevoerd | entity before limit; observed cutoff |
| 49 | Finance + Compute real handlers | uitgevoerd | compute typed; finance persistent `content_hash` upsert |
| 50 | Integration evidence + docs | uitgevoerd | CURRENT_STATUS + matrix + tests |

## Manual checks (operator)

1. Mission Control → compile → approve gate → start → Tasks shows mission steps; mid-wave gate pauses task.
2. Settings → Control Center → set harvest Unlimited → `/harvest` uses null limits.
3. Plugins → invoke with path outside envelope → blocked, no subprocess.
4. Gen2 compute job `op=unknown` → failed; `op=ping` → inspect completed.
5. `POST /gen2/evals/run` with `mode=live_model` + LM client → completed scores; without LM → status `blocked`.
6. `POST /gen2/committees` with `mode=live` + LM → model_invoked positions; without LM → heuristic fallback labeled.
