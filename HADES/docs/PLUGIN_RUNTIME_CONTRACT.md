# Plugin Runtime contract

This is the canonical behavioral contract for Plugin Manager changes. See `CHANGELOG_v0.4.1_PLUGIN_RUNTIME.md` for v0.4.1 history and Plugin Runtime v2 notes below.

## Package/import

A plugin may arrive from Git, local folder, ZIP or `.HadesPlugin`. The Plugins page can also select a local folder, pack it into a `.HadesPlugin` and import it into the library. Import must validate archive paths and package metadata before execution. Dependency installation is plugin-local where practical and failures remain visible.

Marketplace hygiene (v2):
- `marketplace.pinned_version`, optional `source_url` / `license` / `signature`
- `.HadesPlugin` integrity map remains mandatory when present
- Prefer https sources; warnings are persisted as plugin events

## Trust ladder (v2)

Ordered tiers: `untrusted` → `manual` → `verified` → `trusted`.

| Event | Trust effect |
|---|---|
| Fresh convert / legacy `local` | `untrusted` default in manifest (`trust_default`) |
| Successful Ready convert | at least `verified`, **`enabled=False` until explicit user enable** |
| User enables plugin | at least `manual` |
| Successful repair | at least `verified` |
| Explicit user promote | `trusted` via `/api/plugins/{id}/trust` |

Autonomous eligibility requires trust ≥ capability minimum (`manual` / `verified` / `trusted` depending on effects). Write+network requires `trusted`.

## Capability contracts (v2)

Every plugin and tool carries:

```json
{
  "effects": ["subprocess", "network", "read_files", "write_files", "service", "mcp"],
  "side_effect_class": "none|read|write|network|process",
  "cost_class": "cheap|moderate|expensive",
  "latency_class": "fast|normal|slow",
  "failure_modes": ["timeout", "dependency", "network", "schema", "healthcheck"]
}
```

Derived from permissions + tool mode/action when omitted. Agent shortlists expose `why_eligible`, `capabilities`, `trust`, `cost_class`.

## Isolation tiers (v2)

`none` | `plugin_cwd` (default) | `restricted_env` | `temp_workspace` | `container` | `secured`

HADES distinguishes **requested** vs **effective** isolation. A weaker executor may
never silently satisfy a stronger requested isolation contract.

| Tier | Meaning | Filesystem sandbox? |
|---|---|---|
| `plugin_cwd` | Working-directory boundary only; host process as HADES OS user | **No** |
| `restricted_env` | Environment credential scrubbing only; still a normal host process | **No** |
| `temp_workspace` | Temp workdir + env restriction; host process | **No** |
| `container` | Real container adapter only — otherwise **refuse** | Only if container actually ran |
| `secured` | `execution_isolation.run_isolated`; **fail-closed** if unavailable | Only when adapter enforces it |

- Most host-process tiers are application-level only. A permitted subprocess still runs under the HADES user account (Windows ACLs still apply; that is not “OS sandboxing”).
- `restricted_env` strips common secret env vars. It is **not** filesystem isolation and must not be reported as a sandbox.
- `plugin_cwd` changing cwd is **not** filesystem isolation.
- `container` means **actual container execution**. HADES currently has no container adapter;
  requests with `isolation=container` fail closed with `container_not_implemented` and do
  **not** run as a host subprocess (including not as `restricted_env`). Never report
  `effective_isolation=container` unless a real container boundary executed.
  Docker being present on PATH is not an implementation.
  The same fail-closed rule applies to **service start** (`_start_service`): no
  `subprocess.Popen` / native service start when container was requested.
- `secured` routes `_run_command` through `execution_isolation.run_isolated` with read/write roots at the plugin workdir. When FS isolation is unavailable (including Windows Job Objects alone), secured **fails closed** — no unbounded subprocess fallback. Process env `HADES_PLUGIN_ISOLATION=secured` forces this tier. Do not claim AppContainer.
  Service start has no secured long-running adapter yet: `_start_service` refuses with
  `secured_service_start_not_implemented` rather than ordinary `Popen`.
- Native companion (`native_runtime_mode`):
  - `auto`: Python fallback **may** occur for non-security-bound host tiers; must record
    `native_fallback=true`, `executor_requested` / `executor_effective`, and a sanitized
    `native_error`. Fallback must not weaken a requested isolation guarantee.
  - `enabled`: native executor failure returns `native_executor_failed` — **no** silent
    `subprocess.run` downgrade.

Execution metadata should answer: which executor ran, which isolation was requested,
which isolation was established, whether native failed/fell back, and why.

## Plugin knowledge index

Safe plugin docs (manifest, README, skills, rules, declared `knowledge_paths`) are indexed in SQLite FTS5 for lexical retrieval and optional read-only fast path invocations. See `docs/PLUGIN_KNOWLEDGE_INDEX.md`.

## Eligibility for autonomous use

A tool may be offered to the model only when:
- its plugin exists,
- plugin is enabled,
- plugin status is Ready,
- no structural `failure_state`,
- plugin manifest permits autonomous use,
- tool is enabled,
- tool autonomy not opted out,
- trust ladder meets capability minimum,
- global HADES policy permits the required capabilities.

Eligibility is deterministic. The model only chooses among the provided eligible catalog.

**First-party HADES core tools** (`backend/core_tools/`, `plugin_id=hades`) are not third-party plugins:
- They use HADES process policy (`file_read` / `file_write` / `network` / `subprocess`) and do **not** require a plugin trust row.
- Effects are declared explicitly on each core tool. Bare `filesystem` in `effects_from_permissions` remains read-only; write requires `filesystem:write` / `write_files`.
- Chat shortlist: when `plugin_autonomous_tools` is on, Chat offers the policy-filtered **first-party HADES Tool Kernel** on actionable turns (tool/analysis/debug/research/work and other non-simple routes) unless the user forbade tools (`geen tools` / constraints) or `stop_and_ask`. **Simple direct conversational answers** (`direct_answer` / low-risk chat/question without tool need) do **not** receive tool schemas — that path must not burn the Normal/fast execution budget. Keyword `needs_tools` may bias ranking / max rounds / route target — it must **not** zero the tools payload for non-simple actionable turns (`max_tool_rounds=0` for autonomy off, user forbid, stop_and_ask, or simple direct chat).
  Document/attachment conversion and file-mutation NL (e.g. PDF→markdown, “lees deze bijlage”, “pas dit bestand aan”, download→Knowledge) is classified as workspace action / `tool_use` so the tool plane stays available; explicit “gebruik geen tools” still suppresses it.
- Cap total native tools at ≤ 12 first-party `hades.*` tools. **Plugin and MCP tool schemas are never injected into the Chat model payload.** Dynamic extras are discovered via `hades.capabilities.search` / `inspect` / `invoke` (Capability Broker). `hades.web_fetch` is omitted when `network_policy≠allow`. Legacy `hades.discover_plugins` aliases to capability search.
- Ineligible / unknown / jail-escape / policy-blocked calls return a persisted `blocked` observation with a reason code (`unknown_tool`, `path_outside_jail`, `network_policy=block`, …) — calls are not dropped silently.
- Manual Plugins-page invoke of third-party tools still uses `PluginManager.invoke` (no second engine).

Chat core tools are the **only** permanent Chat model schemas. The plugin/MCP catalog remains for CapabilityRegistry discovery, Plugins UI, and broker invoke. See `docs/architecture/HADES_TOOL_KERNEL_AND_CAPABILITY_BROKER.md`.

## Manual execution

The Plugins UI must:
- expose registered tools,
- render schema-driven inputs plus raw JSON where useful,
- require an explicit user Run action/approval,
- return structured result state,
- show persisted history/logs,
- expose the unified observability timeline.

Manual approval does not override a global `block`. Policy `ask` requires the matching
per-kind capability flag (`approved_subprocess`, `approved_network`, `approved_file_read`,
`approved_file_write`) at the PluginManager boundary, or a durable `ApprovalService`
decision that grants those kinds. Client-provided `approved_by_user` booleans are
informational/audit only — never authorization authority for side-effect policies,
MCP, or Gen2 product gates (F-03).

## Execution safety

- Use argv arrays.
- Use `shell=False`.
- Validate JSON input against the declared input schema before execution.
- Expand placeholders into individual argv values only.
- Bound execution with timeouts/cancellation where applicable.

## Service lifecycle

For `start`/`serve`/`dev` style actions:
- start non-blocking under HADES supervision,
- capture stdout/stderr persistently,
- wait for declared HTTP/TCP/command health proof,
- only then return success/healthy,
- persist `runtimes/{id}/service.state.json` with PID + start identity,
- terminate a failed managed start where safe,
- support health/status/logs/stop through the same lifecycle manager.

A spawned PID or wrapper exit code 0 is **not** proof of a working service.

## Restart reconciliation

After a hard HADES restart:
1. mark in-flight toolcalls `interrupted`
2. reconcile claimed healthy/running services using `service.state.json` (PID identity) **and** healthcheck
3. stale persisted “running/healthy” without proof becomes `needs_attention` / `stopped` with `failure_state`

Do not infer restart-safety merely from persisted toolcall records.

## Persistence

Every tool call should preserve at least:
- plugin/tool,
- input metadata,
- invocation type (`manual`, `autonomous`, `install`, etc.),
- approval state,
- status,
- stdout,
- stderr,
- exit code,
- error,
- start/end timestamps,
- duration.

## Health semantics

Use distinct concepts:
- `prepared`: dependencies/runtime prepared,
- `operational`: ordinary CLI action succeeded,
- `healthy`: a declared service healthcheck passed,
- `unhealthy` / `needs_review`: evidence of failure or incomplete setup.

Do not use `healthy` as a generic synonym for “command returned 0”.

## Failure as first-class state (v2)

Structural `failure_state` values (`dependency_failed`, `integrity_failed`, `unsupported_runtime`, `not_ready`) force `needs_review` + disabled. Service health failures use `health_failed` / `health_unverified` without falsely claiming Ready.

## MCP first-class (v2)

Plugins with `list_tools`/`call_tool` and `mcp.expand_tools` register remote tools as HADES `plugin_tools` rows (`mcp__*`) while wrappers remain. Expansion is best-effort and never fakes success.

## Observability timeline (v2)

`GET /api/plugins/{id}/timeline` merges plugin events, toolcalls and current service state into one chronological view.

## Trust boundary

Current plugin permissions are application-level enforcement. A permitted subprocess runs under the HADES user account. This is **not** a hostile-code OS sandbox. Future sandbox/container work must be documented as a separate capability and must not be claimed until proven.

Capability Intelligence (`docs/CAPABILITY_INTELLIGENCE.md`) normalizes plugins into skill/knowledge/tool/agent/… records for routing. It does not bypass this contract.
