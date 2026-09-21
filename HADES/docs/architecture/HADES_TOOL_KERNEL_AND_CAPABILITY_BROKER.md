# HADES Tool Kernel and Capability Broker

## Why plugins are not permanent model tools

Installing 1 plugin or 500 plugins must **not** grow the base Chat model tool
schema from ~10 tools to hundreds. Plugins and MCP servers are optional extras.
The model interacts primarily with a small, stable first-party `hades.*` API.
Dynamic functionality is discovered and invoked through the **Capability Broker**.

```text
                 MODEL / AGENT
                      │
             FIRST-PARTY HADES API
                      │
       ┌──────────────┴──────────────┐
       │                             │
  Native HADES                 Capability Broker
  operations                         │
                             ┌───────┴───────┐
                             │               │
                          Plugins           MCP
                             │               │
                             └───────┬───────┘
                                     │
                              Real executors
                         (PluginManager / MCP Host)
```

## First-party Tool Kernel

Implemented in `backend/core_tools/`. Model-visible base surface (≤ 12):

| Tool | Role |
|---|---|
| `hades.fs_list` / `hades.fs_read` / `hades.fs_write` | Jail-scoped filesystem |
| `hades.terminal` | Allowlisted argv (`shell=False`) |
| `hades.knowledge_search` | Local knowledge |
| `hades.memory_propose` | Memory proposals (no auto-promote) |
| `hades.web_fetch` | HTTP only when `network_policy=allow` |
| `hades.capabilities.search` | Discover optional plugin/MCP capabilities |
| `hades.capabilities.inspect` | Bounded schema + availability detail |
| `hades.capabilities.invoke` | Controlled execution via broker |
| `hades.discover_plugins` | Legacy alias → capability search |

Hard budget: `MAX_MODEL_VISIBLE_TOOLS = 12` in `core_tools/catalog.py`.

**Invariant:** no plugin or MCP tool schema is injected into the initial Chat
model payload. `build_chat_tool_shortlist` returns first-party tools only.

## CapabilityRegistry

Existing `capability_intel.CapabilityRegistry` indexes:

- native HADES capabilities
- installed plugins (via adapters / live tool rows)
- MCP mirrored tools

Public capability IDs are stable and unambiguous:

```text
core:fs:read
plugin:markitdown:convert
plugin:puppeteer:screenshot
mcp:github:create_issue
```

Internal `CanonicalCapability.canonical_id` values remain valid aliases.

## Capability Broker

`capability_intel.broker.CapabilityBroker`:

1. **search** — ranked discovery with availability reasons (does not grant rights)
2. **inspect** — argument schema, effects, policy/approval implications
3. **invoke** — resolve → live health → schema validate → policy → trust →
   autonomy → approval → PluginManager / MCP executor → observation

Model-supplied `autonomous` / `trust` / `effects` metadata is ignored.

### Availability reasons (discovery ≠ authorization)

`available`, `disabled`, `plugin_unhealthy`, `approval_required`,
`network_blocked`, `filesystem_blocked`, `subprocess_blocked`,
`not_autonomous`, `missing_dependency`, `mcp_disconnected`, `untrusted`, …

Restricted capabilities (e.g. Puppeteer `autonomous=false`) remain **searchable**
and return `approval_required` on invoke — they do not disappear.

## Providers

| Provider | Executor |
|---|---|
| `core` | `core_tools.invoke_core_tool` |
| `plugin` | `PluginManager.invoke` |
| `mcp` | PluginManager / MCP host bridge (same invoke path) |

Do not reimplement PluginManager or MCP. The broker is an adapter.

## Policy and approval

Policy stays **below** discovery:

- global `*_policy=block` always wins
- trust ladder / enabled / health / autonomy still apply
- `ApprovalService` is reused (no second approval system)
- effects come from registry contracts, never from the model

## Plugin / MCP lifecycle

| Event | Registry effect |
|---|---|
| install / enable / repair | refresh → searchable |
| disable | inspectable; invoke ineligible |
| uninstall | capabilities removed |
| MCP connect / refresh | registered |
| MCP disconnect | unavailable; invoke refused |

Chat system prompt / first-party schemas do **not** change when plugins change.

## Tool-count invariant

Automated regression: `backend/tests/test_tool_kernel_capability_broker.py`

- 0 / 10 / 100 plugins, 500 plugin tools, 120 MCP tools
- initial model-visible first-party tool count remains ≤ 12

## Security boundaries

- no generic `invoke_anything` RPC without registry resolve
- no raw shell / import path / arbitrary HTTP via capability_id forgery
- disabled / untrusted / network-blocked capabilities fail closed
- Chat autonomous path cannot bypass the broker by inventing plugin tool names
- manual Plugins page / API `PluginManager.invoke` remains available

## Observability

Bounded Chat metadata (no secrets):

- `first_party_tools_offered` / `first_party_tool_count`
- `capability_search_used` / `capability_candidates`
- `selected_capability_id` / `provider` / `provider_id`
- `approval_required` / `blocked_reason` / `execution_status`

Optional server-side prefetch injects **compact text hints** only
(never full dynamic schemas).

## Migration compatibility

- wrappers stay execution infrastructure (not deleted)
- `hades.discover_plugins` remains a legacy search alias
- granular `hades.fs_*` kept (semantic consolidation deferred)
- Plugin Manager HTTP routes unchanged

## Related docs

- `docs/CAPABILITY_INTELLIGENCE.md` — normalization / ranking layer
- `docs/PLUGIN_RUNTIME_CONTRACT.md` — trust, autonomy, effects
- `docs/MCP_HOST.md` — MCP sessions (does not replace PluginManager)
