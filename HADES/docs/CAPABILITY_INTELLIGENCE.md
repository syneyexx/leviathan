# Capability Intelligence

HADES Capability Intelligence is a **normalization and routing layer** over existing Plugin Manager, MCP host, specialists, Work Runtime and Context Compiler infrastructure.

It does **not** replace PluginManager, approvals, trust, or global policy.

**Tool Kernel / Capability Broker** (`docs/architecture/HADES_TOOL_KERNEL_AND_CAPABILITY_BROKER.md`) is the model-facing contract: Chat receives only stable first-party `hades.*` tools. Plugin and MCP tools are registry capabilities invoked through `hades.capabilities.search|inspect|invoke` — they are **not** permanent Chat tool schemas.

The current main HADES interface (`HadesApp` + Classic pages) is the only supported product GUI. Obsidian remains a visual skin of those same pages. V3, V4 and BETA templates were removed.

One Brain (`docs/ONE_BRAIN_ARCHITECTURE.md`) is the shared cognition façade over this layer. MCPMarket (`docs/MCPMARKET_INTEGRATION.md`) is an untrusted external catalog that normalizes into the same taxonomy.

## Taxonomy

A plugin is a **container**. Capability kinds are:

| Kind | Meaning |
|---|---|
| `skill` | Reasoning guidance. Not an external side effect. |
| `knowledge` | Read-only indexed/docs content. |
| `tool` | Concrete executable action. |
| `tool_provider` | Provider that can expose tools. |
| `mcp_provider` | MCP server/provider. Functions become tools. |
| `agent` | Executable delegated worker (not a prompt persona). |
| `service` | Long-running runtime capability. |
| `workflow` | Reusable multi-step plan/template. |
| `resource` | Model, workspace, index or other non-action resource. |

Contract version: `capability_intel.taxonomy.CONTRACT_VERSION`.

## Package → registry flow

```text
External package
  → format detection
  → adapter(s)
  → HADES normalization
  → canonical registry
  → policy/trust/health filter
  → hybrid ranker
  → smallest composition
  → PluginManager / native execution
  → verification
```

Core routing never branches on ecosystem names (`claude`, plugin inventory, …). New ecosystems add an adapter.

Adapters today:

- `hades_manifest` — `hades-plugin.json` including legacy `plugin_type` + `tools[]`
- `convention` — `skills/`, `knowledge/`, `docs/`, `agents/`, `workflows/`, `commands/`, `tools/`
- `claude_upstream` — SKILL.md, CLAUDE.md, personas, slash commands, hooks (hooks unsupported)
- `mcp_discovery` — MCP config + expanded `mcp__*` tools
- native HADES records (`hades.coding_agent`, retrieval, verification, Work Runtime, …)

Unknown kinds are **not** coerced. They are reported as unsupported.

## Routing

Planner (`plan_requirements`) is deterministic. No planning LLM.

Ranker stages: exact reference → lexical → deterministic synonym expansion (`semantic_relevance`) → intent/domain/kind → health/reliability → minus cost/latency/side-effect/agent penalty.

Kind match is applied only when another signal exists, so unrelated native tools are not ranked merely because the plan wants a tool.

Planner emits `domains` and goal-implied requirements (for example `repair_repository_bug` always needs skill + search + modify + tests + verify).

Composition (`smallest_team`) covers those requirements with the fewest providers: complementary plugin agents, one search tool, native verifier when required. Extra agents are not allocated at start.

Chat `observe()` routes every request and **composes + persists a mission only when the task is not a simple fast path**. Work Runtime uses `build_work_plan_from_composition` for `repair_repository_bug` / `implement_feature` so the Work Planner LLM is skipped. Coding jobs attach the same snapshot; mutation ownership stays a single specialist (`build`) plus existing execution leases. Plugin agents are capability refs, not fake TaskRunner identities.

Policy filtering calls `eligible_for_autonomous` and `evaluate_global_side_effect_policies`. Skills/knowledge skip subprocess eligibility but still require an enabled/ready plugin when they belong to one.

Embedding-based tool rerank is **not** implemented. Semantic retrieval embeddings remain in the existing retrieval pipeline. The ranker’s “semantic” term is a documented synonym expansion, not cosine similarity.

Explicit eligible provider mentions (`Use Desktop Commander`) are honored without a model call.

## Skills

Skills are retrieved as bounded untrusted fragments (`instruction_authority=false`, `subprocess=false`) and packed as ContextItem `kind=skill`.

Duplicates (exact/near) are dropped. Conflicting skills prefer specificity and already-selected trusted/relevant items.

The Plugin Knowledge Index fast path remains the way to answer static search tools without a subprocess.

## Observability

HTTP (main GUI only):

- `GET /api/capability-intel/overview`
- `GET /api/capability-intel/registry`
- `GET /api/capability-intel/plugins/{id}/groups`
- `POST /api/capability-intel/route`
- `POST /api/capability-intel/compose`
- `GET /api/capability-intel/missions/{id}`

Plugins page shows capability groups. Chat context panel shows routing selection when present.

## Security

Planning recommends. Execution still requires:

- plugin enabled + Ready
- trust ladder
- global capability policy
- schemas
- approvals
- PluginManager.invoke

Plugin/upstream text cannot grant system authority. See `docs/AGENT_COLLABORATION.md` and `docs/UPSTREAM_CAPABILITY_ADAPTATION.md`.
