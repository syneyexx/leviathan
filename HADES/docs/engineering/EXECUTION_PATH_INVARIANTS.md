# Execution Path Invariants

HADES must not allow a production side-effect path to bypass deterministic policy,
approval, logging, or (when required) isolation by clever framing.

## Authoritative gateway

Module: `backend/runtime/execution_gateway.py`

| Helper | Contract |
|---|---|
| `may_skip_tool_policies(...)` | Returns true **only** when `privileged_policy_skip=True` **and** `invocation_type` ∈ `{install, system}` |
| `assert_public_invocation_type(...)` | Raises if workflow/public callers request install/system |
| `enforce_policies_fail_closed(...)` | Runs G11/G8; ImportError → `PolicyModuleUnavailable` (fail closed) |

## Required call shape (plugin-capable paths)

```
request
  → normalize invocation_type
  → if public: assert_public_invocation_type
  → enforce_policies_fail_closed (unless trusted privileged_policy_skip)
  → capability / plugin permission approvals
  → optional Gen2 envelope
  → execute (prefer execution_isolation when secured)
  → normalize status (anti-false-success)
  → persist toolcall / evidence
  → task/run transition only after verification when Work Runtime
```

## Concrete production owners

| Path | Entry | Must use |
|---|---|---|
| Manual plugin invoke | `main.invoke_plugin` | approvals + `PluginManager.invoke` (gateway) |
| Chat/Work tools | `reasoning.tool_engine._invoke_selected_tool` | G11/G8 fail-closed + permissions + invoke |
| Workflow plugin step | `gen2.workflow_adapters._adapt_plugin_invoke` | public invocation types only |
| MCP expand list_tools | `PluginManager.expand_mcp_tools` | `privileged_policy_skip=True` + install (internal only) |
| Chat harvest | `chat_commands.maybe_handle_chat_command` | `allow` or (`ask` + `approved_network`); never silent under ask |
| Terminal | `PolicyTerminalService.run` | allowlist + `run_isolated` |

## Invariant tests

`backend/tests/test_frontier_execution_invariants.py` must fail if:

1. `PluginManager.invoke` can skip policy solely via `invocation_type="install"`.
2. Workflow adapter forwards install/system to invoke.
3. Policy ImportError is fail-open.
4. Harvest under `ask` calls the network harvest function without approval.

## Known residual gaps (honest)

- Coding/build/voice/preview/LSP still use direct subprocess outside PluginManager.
- Plugin `_run_command` uses `run_isolated` when isolation=`secured` (or `HADES_PLUGIN_ISOLATION=secured`); other tiers remain the trusted/native/subprocess path.
- Windows Job Object ≠ full FS/network isolation (`UNVERIFIED_ON_HOST` / fail-closed secured).
