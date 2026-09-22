# Universal MCP Bridge

LEVIATHAN treats MCP as **one TOOL PROVIDER class** inside the existing capability/execution architecture.

Product language: **Tools**. Backend primitive: `CapabilityDefinition` with `provider_kind=MCP`.

## Architecture

```
Agents / Chat / Coding / Research / UI
                │
         capability invoke
                ▼
         ExecutionGateway  (+ Policy / Approvals / Evidence / Verification)
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
 Builtin    Module      McpProvider
                          │
                       McpBridge   ← ONE logical owner
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
      Session A     Session B     Session N
      (stdio/http)  (stdio/http)  ...
```

- **One bridge, many independent sessions** — no global connection lock.
- **No per-server wrapper classes.** Servers are data registrations.
- **ModuleManager** remains the lifecycle loader for `ILeviathanModule`.
- **PluginRegistry** stays declarative (bindings only).
- **ExecutionGateway** is the only authorized path for side-effecting invokes — including `POST /api/mcp/call`.

## Module ownership

`Data/modules/mcp/` owns:

| File | Role |
|---|---|
| `bridge.py` | Public facade: register/enable/connect/list/call/health |
| `session.py` | Per-server lifecycle, pending requests, circuit breaker |
| `transports.py` | stdio (MVP) + HTTP |
| `protocol.py` | JSON-RPC initialize / tools/list / tools/call |
| `catalog_sync.py` | tools → CapabilityCatalog + PluginRegistry bindings |
| `provider.py` | Gateway MCP adapter |
| `store.py` | Central SQLite (`mcp_servers`, `mcp_tools`, `mcp_tool_calls`) |
| `module_integration.py` | `module.json` `mcp.servers` registration |

## Feature flags

```
LEVIATHAN_FEATURE_MCP=false          # parent
LEVIATHAN_FEATURE_MCP_STDIO=true     # child (requires parent)
LEVIATHAN_FEATURE_MCP_HTTP=true
LEVIATHAN_FEATURE_MCP_AUTO_EXPAND_MODULES=true
```

When MCP is off: backend starts, no MCP processes spawn, echo MCP stub remains for isolated plugin tests.

## Register a server (data, not code)

```json
{
  "display_name": "filesystem",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  "trust": "manual",
  "enabled": true,
  "secret_refs": { "TOKEN": "secret:mcp/example" },
  "semantic_effects": { "read_file": ["READ"] }
}
```

Or via `module.json`:

```json
{
  "mcp": {
    "default_trust": "untrusted",
    "expand_tools": true,
    "servers": [
      {
        "name": "research-fetch",
        "transport": "stdio",
        "command": "python",
        "args": ["workers/fetch_mcp.py"],
        "trust": "manual"
      }
    ]
  }
}
```

Optional MCP expand failure does **not** kill the module unless `required: true`.

## Capability IDs

Stable namespace:

```
mcp.<sanitized_server_id>.<sanitized_tool_name>
```

Disconnect → availability `unavailable` (identity preserved, not deleted).

Schema fingerprint (`schema_hash`) is persisted; changes emit observability events and invalidate stale approval assumptions.

## Authorization

- Discoverable ≠ authorized ≠ available ≠ enabled ≠ approved.
- Client `approved_by_user` is **audit metadata only**.
- Semantic effects default conservatively when unknown (never silent READ).
- Transport effects: stdio ⇒ EXECUTE class; HTTP ⇒ NETWORK.
- Requested isolation vs effective isolation are both stored; container without a real adapter **fails closed**.

## Secrets

Persist `secret_refs`, never plaintext values. Resolve at process launch. Redact from API, logs, call history, errors.

## Transports

| Transport | Status |
|---|---|
| stdio | Implemented (async multiplexed reader, shell=False) |
| HTTP | Implemented (network policy + bounded size) |
| SSE legacy | Explicit `MCP_TRANSPORT_UNSUPPORTED` |

## How to call tools

1. `GET /api/capabilities/search?q=...` — shortlist IDs (no schema dump into prompts)
2. `GET /api/capabilities/{id}` — inspect schema
3. `POST /api/mcp/call` or `POST /api/capabilities/{id}/execute` — **always via ExecutionGateway**

MCP results are **observations**, not evidence.

## Differences from HADES

- No per-upstream wrapper packages / 70 plugin classes.
- No parallel plugin execution engine or MCP-only DB.
- No direct MCP→LLM path.
- Honest health (initialize + protocol), not PID-only.
- HADES remains removable; LEVIATHAN never imports it.

## Future extensibility

Phase 1 focuses on **tools**. Data models keep room for resources/prompts/roots/notifications and server-initiated sampling (which must route through the Model Control Plane — never a private LLM client).

## Operator UI

`/mcp` — real server/tool/call state from the bridge. No decorative fake counts.
