# HADES configuration & limit audit

Inventory of meaningful hardcoded behavioral constraints discovered during the Control Plane refactor, with migration status.

**Convention:** `null` / Unlimited is a first-class state (never `999999`).

**Architecture:** `backend/control/` — registry, resolver, capabilities, presets, Limit Inspector, API under `/api/control/*`.

UI: Settings → Advanced → HADES Control Center.

---

## Summary

| Status | Count (approx.) |
|---|---|
| Migrated into control registry + runtime reads settings | Primary hotspots (incl. harvest/plugins/trading/build/approvals/codeindex/mentions) |
| Registered residual (logging level/retention/trace depths) | Low priority |
| Explicit immutable constraints | 7 documented |
| Skip / display-only truncations | Titles, labels, ID prefixes |

Defaults preserve pre-migration behavior unless the user changes a setting.

---

## Migrated (runtime uses resolver / settings)

| Location | Old value | Purpose | Setting ID | Default | Unlimited | Status |
|---|---|---|---|---|---|---|
| `database.py` DEFAULT_SETTINGS / SettingsInput | various | Existing global knobs | matching `*.storage_key` | same | where marked | Migrated (registry + nullable) |
| `main.py` tool shortlist | `limit=8` | Autonomous tool shortlist | `tools.shortlist_limit` | 8 | Yes | Migrated |
| `main.py` tool observation clip | `[:30000]` | Tool result fed to model | `tools.result_max_chars` | 30000 | Yes | Migrated |
| `main.py` work planner | `min(8, …)` | Plan step ceiling | `agents.execution.work_plan_max_steps` | 8 | Yes | Migrated |
| `main.py` work context clip | `[:30000]` | Planner context | `context.work_context_max_chars` | 30000 | Yes | Migrated |
| `main.py` shared budget `* 20` | opaque multiplier | Shared model-call pool | `runtime.shared_budget.model_calls_multiplier` + explicit shared max | 20 / null | Yes (shared max) | Migrated |
| `reasoning/budgets.py` | int ceilings | ExecutionBudget | nullable ints | prior defaults | Yes | Migrated |
| `reasoning/profiles.py` | PROFILE_CONFIGS literals | Profile ceilings | `reasoning.profiles.<name>.*` | prior table | Yes | Migrated (overlay) |
| `reasoning/atomic_budget.py` | int semaphores | Shared pool | `runtime.shared_budget.*` | prior | Yes (`None`) | Migrated |
| `terminal_tool.py` | timeout clamp 120; output 20k | Terminal limits | `terminal.timeout_seconds` / `max_timeout_seconds` / `output_max_chars` | 30 / 120 / 20000 | Yes | Migrated |
| `platform_services_core.py` ResearchRunner | DEPTH_CONFIG + expert `*30` | Research depth | `research.depth.*` + `expert_sources_per_cycle` | prior matrix | Partial | Migrated (depth overlay) |
| `chat_commands.py` harvest clamps | 100/80/4 | Command harvest ceilings | `research.harvest_clamp_*` | prior | Yes | Migrated |
| `platform_services_core` / `main` upload caps | MAX_* constants | Archive/upload safety | `filesystem.max_*` helpers | prior | Yes | Migrated |
| harvest/crawl/knowledge/plugins/MCP call sites | literals | Research + plugin ceilings | matching registry ids | prior | where marked | Migrated |
| `workspace_symbols` / `mentions` | 400/400k/40/20 | Index + mentions | `codeindex.*` / `chat.mentions_*` | prior | Yes | Migrated |
| `trading_service` / `approvals` / `build_agent` | bars/TTL/repair | Trading + autonomy | `trading.*` / `approvals.*` / `build.*` | prior | where marked | Migrated |
| `main` KnowledgeHarvestInput | Field `le=` | API harvest clamps | settings clamps | prior | Yes | Migrated |

---

## Registered (Control Center) — residual lower-priority call sites

Primary behavioral caps above now resolve via Control Plane. Prefer `resolve_setting` / `runtime_values` when touching remaining areas:

| Area | Examples | Setting ID prefix |
|---|---|---|
| Logging level/retention/trace | log_level, retention_days, trace depths | `logging.*` |

---

## Immutable constraints (explicit, not user-overridable)

See also Control Center → Immutable Constraints and `backend/control/immutable.py`.

| ID | Value | Reason | Enforcement |
|---|---|---|---|
| `security.terminal.metacharacters_blocked` | true | Shell injection prevention | `terminal_tool.py` |
| `security.terminal.cwd_jail` | data_root | CWD isolation | `terminal_tool.py` |
| `security.network.non_loopback_when_blocked` | true | Offline-first isolation | network policy helpers |
| `security.subprocess.shell_false` | true | No `shell=True` | plugin/runtime invoke |
| `runtime.schedules.max_catchup` | 1 | Prevent schedule stampede | `schedules.py` |
| `api.chat.message_max_length` | 100000 | Request parse memory bound | MessageInput |
| `security.secrets.not_in_frontend_settings` | true | Secret redaction on export | `control/service.py` |

---

## Provider / capability limits (display, not fake settings)

| Capability | Behavior |
|---|---|
| Model context window | Shown via capability registry; clamps configured→effective with reason |
| Model max output tokens | Same |
| VRAM concurrent inference | Runtime capability may lower effective concurrency |

Never silently clamp without `clamped=true` + reason on the effective value.

---

## Intentionally leftover literals (classified)

| Pattern | Why kept |
|---|---|
| UI title truncations `[:90]`, `[:120]` | Display only; does not change agent capability |
| UUID / id slices `hex[:16]` | Identifier formatting |
| Test `range(N)` / test timeouts | Test harness, not product policy |
| SQLite PRAGMA busy defaults until restart | Registered as restart-required storage settings |
| Plugin-local timeouts in `plugins/*/bridge` | Plugin manifests may register typed settings; core registry covers shared install/health defaults |

---

## How to verify remaining hardcodes

```bash
cd backend && python -m unittest tests.test_hardcoded_limit_detector -v
# or via release gate
python verify_hades.py --quick
```

`configurable` findings must include Control Plane binding metadata
(`control_key`, `definition_location`, `enforcement_location`,
`unlimited_supported`, `reason`). Unbound configurable labels fail CI.

See `backend/control/detect.py`, `limit_classifications.py`, and `immutable.py`.

```bash
cd backend
python -m unittest tests.test_hardcoded_limit_detector tests.test_control_plane
python -c "from control.detect import scan_repository; print(len(scan_repository()))"
```

Review detector findings when adding new runtime limits; register them in `backend/control/definitions.py` and consume via `resolve_setting` / ControlService.
