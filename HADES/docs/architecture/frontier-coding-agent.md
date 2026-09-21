# Frontier coding agent upgrade ledger

Base: `origin/main` @ `6c23967c7a010c1ef9de263f9f7190e2b0b039df` (PR #102, Autonomous Media Intelligence).  
Reference SHA in the original prompt (`7f08b297…` / PR #100) was **not** used.

This is the single engineering ledger for the coding-agent upgrade. It is not a second roadmap.

## Runtime path (authoritative owners)

```
USER REQUEST
  → capability_routes / CodingJobStore          (job + pause/resume/cancel)
  → CodingAgentService.run_from_goal            (orchestration)
      → coding_autonomy.profile_policy          (permission ≠ skill)
      → snapshot_context / git state
      → coding_task_contract (requirement_map)  (durable spec)
      → repo_intelligence.index_repository      (incremental AST/graph)
      → explore_repository + InteractiveCodingInvestigator
      → coding_plan DAG (trivial skip / complex explicit)
      → coding_context.assemble_coding_context  (tiered, hashed cache)
      → propose_edits / propose_repair
      → BuildAgentService isolated worktree     (the only workspace manager)
          apply_edits + real unified diffs
          run_tests (policy allowlist, shell=False)
          structured failures (coding_failures)
          bounded repair (single attempt ceiling)
      → coding_reviewer (deterministic, independent)
      → requirement map (evidence-based)
      → coding_delivery + user_facing + honest frontier_status
      → apply_to_source only with approved=True + conflict hashes
```

Status of pre-existing modules after caller tracing:

| Module | Status | Notes |
|---|---|---|
| `coding_agent.py` | ACTIVE | Orchestrator |
| `build_agent.py` | ACTIVE | Isolation, apply, tests, repair |
| `coding_investigate.py` | ACTIVE | `strategy=investigate\|auto` |
| `coding_jobs.py` / `coding_job_control.py` | ACTIVE | Async jobs |
| `coding_delivery.py` | ACTIVE | Honest completion gate |
| `coding_reviewer.py` | ACTIVE | Checklist + weakening + trust-boundary signals |
| `coding_requirement_map.py` | ACTIVE | Now v2 evidence-based + task contract |
| `coding_autonomy.py` | ACTIVE | Profiles + mapped frontier levels |
| `coding_omniroute.py` | ACTIVE (optional) | Per-job coding model routing; default off; does not intercept Chat |
| `coding_candidates.py` | ACTIVE | Verification-driven best-of-N (not resurrected dead code) |
| `workspace_symbols.py` | ACTIVE | Incremental regex index |
| `code_intel.py` | ACTIVE | Python AST via repo_intelligence, regex fallback |
| `language_servers.py` / `lsp_light.py` | ACTIVE | Optional; fallback must not crash |
| `project_map.py` | ACTIVE | Compact map; not a second graph |
| `project_continuity.py` | ACTIVE | Experience memory reuses this |
| `debug_agent.py` | ACTIVE | Now attaches structured_failure |
| `reasoning/plan_scheduler.py` | ACTIVE | DAG validation |
| `reasoning/information_gain.py` | ACTIVE | Investigate next-step ranking |
| `reasoning/model_router.py` | ACTIVE (chat) | Coding still uses caller `model_id` |
| `reasoning/long_task_resume.py` | ACTIVE (work) | Coding jobs keep checkpoint extra |
| `execution_isolation.py` / `terminal_tool.py` | ACTIVE | Not bypassed |

## Confirmed original weaknesses

1. **Repair ceiling inconsistency:** `attempt_ceiling` vs inner `max_attempts` could apply an untested repair and leave `status=running`.
2. **`_unified_diff` was not a unified diff** (context-free `+`/`-` dump) but was stored as `patch_text`.
3. **Requirement map linked every file to every requirement.**
4. **Independent reviewer often received an empty diff** (`payload["diff"]` vs `diff_text`).
5. **Repository exploration was lexical**; symbol index existed but no import/call graph.
6. **Repair fed raw logs** into the model; parsers in `debug_agent` were narrow.
7. **`coding_candidates.py` was a tombstone** with no caller.
8. **No durable task contract** spanning investigate → edit → verify → delivery.

## Implemented upgrades (wired, tested)

- Task contract + evidence-based requirement mapping
- Incremental repository intelligence (Python AST, import/call/test/route edges, hash invalidation, cache **not** written into the user source tree)
- Tiered coding context + bounded content cache
- Complexity-aware DAG (trivial tasks skip heavy plans) + epistemic claim states
- Real unified diffs + `unified_diff` / `rename` edit actions + stale `base_hash` checks
- Structured failure normalization + log compaction
- Test impact / verification matrix / stronger weakening detection
- Single repair-attempt ceiling; failed loops cannot remain `running`
- Adaptive candidate search only when complexity/risk warrants it
- Honest frontier statuses + user-facing delivery sections
- Coding specialists registered on existing `SPECIALISTS` (no second multi-agent runtime)
- Internal fixture benchmark `evals/frontier_coding_suite.py`
- Repair-model context sanitizes out-of-worktree paths in **both** compacted logs and structured-failure JSON
- `needs_attention` independent review does **not** demote `COMPLETED_VERIFIED` (reject still fails)
- `coding_memory` is invoked from `run_from_goal` when `ProjectContinuityService` + `project_id` are supplied; recalled items remain **HYPOTHESIS**
- `should_search_candidates` is evaluated on the live path; isolated bake-off runs only when two concrete edit lists exist

## Safety properties preserved

- Isolated worktree / copy; source untouched until `apply_to_source(approved=True)`
- Dirty user files protected by baseline hashes (conflict ≠ overwrite)
- Deletions not silently applied to source
- `shell=False`; test commands allowlisted
- Test weakening is a critical review defect
- Publish/push/merge never granted by coding autonomy
- No `git reset --hard` / `git clean -fd` on user work

## Known limitations / deferred

- Candidate generation does not spend 3× inference on trivial edits; N-way LLM variants remain unused unless two concrete edit lists already exist.
- Semantic analysis for C/C++/Java/Go/Rust is **lexical fallback only** unless an LSP is present. Do not claim semantic support.
- UI correctness is never inferred from `tsc`.
- Live LM Studio quality, Windows VERIFY, and full-repo SWE-bench clones: **UNVERIFIED_ON_HOST**.
- Coding experience memory writes only when a `ProjectContinuityService` + `project_id` are supplied (no second database). Jobs pass continuity from the existing project service; without `project_id` nothing is stored.
- Model routing for coding still uses the caller-provided `model_id` by default. Optional OmniRoute routing is off unless the per-job toggle is on and the OmniRoute plugin is Ready (`docs/CODING_OMNIROUTE.md`).
- Fixture eval `api_change` fails without a live model (heuristic does not rewrite API keys from assert text alone). That is an honest incomplete, not a baked-in oracle.
