# Gen2 implementation matrix (reliability pass)

**Investigated commit:** `6896fc3df3e7aaebf7f73e0f23b1621d238ed8ee` (Control Plane #34)  
**Working branch tip:** recorded in `docs/CURRENT_STATUS.md` after verification.

Status legend:

| Status | Meaning |
|---|---|
| `bewezen defect` | Reproduced on investigated commit; fix required |
| `bevestigd werkend` | Exercised by focused tests after fix or already correct |
| `gedeeltelijk aangesloten` | API/UI exists; executor/policy/settings incomplete |
| `uitbreiding` | Roadmap scope beyond current local reliability |

An existing HTTP endpoint alone does **not** imply a working capability.

| Component | Entry | Service | Real executor | Storage | UI | Tests | Status @ 6896fc3 | Notes |
|---|---|---|---|---|---|---|---|---|
| Mission compile | `POST /api/gen2/missions/compile` | `Gen2Services.compile_mission` | template IR only | `gen2_missions` | Mission Control | `test_gen2` | gedeeltelijk | IR not fully driven by Work Runtime |
| Mission start | `POST .../start` | `start_mission` | `_create_mission_task` → TaskRunner + work_steps | `gen2_missions` + executions | Mission Control | `test_gen2_reliability` | bevestigd werkend | claim/idempotent/retry verified |
| Mission gates | `POST .../gates/{id}` | `decide_mission_gate` | transition guard | gates JSON | Mission Control | regression | bevestigd werkend | rejected/failed cannot silently restart |
| Compute dispatch | `POST /api/gen2/compute/jobs` | `dispatch_job` | typed local handlers | `gen2_remote_jobs` | — | regression | bevestigd werkend | unknown → failed; inspect labeled |
| Sandbox check | `POST /api/gen2/sandbox/check` | `enforce_envelope` | policy | envelopes | — | regression | bevestigd werkend | relative_to jail; tier honesty |
| Sandbox at invoke | Plugin invoke | envelope gate | `PluginManager.invoke` | tool_calls | Plugins | regression | bevestigd werkend | blocked never reaches `_run_command` |
| Context Compiler | `POST /api/gen2/context/compile` | `compile_context` | packer | packs | — | regression | bevestigd werkend | full hash; zero scores; token/truncation aligned |
| Eval Lab | `POST /api/gen2/evals/run` | `run_eval_lab` | deterministic `_run` | matrix `software:*` | Mission Control | `test_gen2` | gedeeltelijk | labeled not model quality; live model route still needs LM Studio |
| Model recommend | `recommend_model` | `best_model_for` | metric direction | matrix | — | regression | bevestigd werkend | latency lower-better; software fallback labeled |
| Committee | `POST /api/gen2/committees` | `run_committee` | heuristic roles | sessions | Mission Control | `test_gen2` | gedeeltelijk | mode=`heuristic_isolated`; topical evidence gate |
| Agent Factory | skills APIs | benchmark/promote | workflow + hash | skills | — | regression | bevestigd werkend | broken workflow fails; hash binds promote |
| Flight Recorder | compare/replay | inspect manifest | events | run_events | — | `test_gen2` | gedeeltelijk | inspect ≠ model replay; richer diffs |
| Temporal graph | `as_of_beliefs` | store entity filter | SQL before limit | edges | — | `test_gen2` | bevestigd werkend | valid-time + observed-time cutoff |
| Harvest Unlimited | slash/NL | chat_commands + crawler | WebResearch | settings | Chat | regression | bevestigd werkend | null preserved; crawler tolerates None |
| Terminal Unlimited | terminal tool | PolicyTerminalService | subprocess timeout=None | settings | — | regression | bevestigd werkend | missing arg ≠ Unlimited confusion |
| Profiles | chat/tool loop | `resolve_profile_config` | main + budgets | control | Settings | focused | bevestigd werkend | static PROFILE_CONFIGS no longer sole source |

## Phase 1 reproduction evidence (pre-fix)

| Bug | Observed |
|---|---|
| Mission without task bridge | `status=running`, `task_id=None`, `error=None` |
| Repeated start | `create_task` called twice → `task_1`, `task_2` |
| Unknown compute | `status=completed` with echo payload |
| Sandbox prefix sibling | `/plugin-outputs/foo_evil` allowed when jail is `.../foo` |
| Tier 2 | `ok=True`, empty violations (`if False` disabled) |
| Context dedupe | Distinct suffixes after shared 2k prefix → only first kept |
