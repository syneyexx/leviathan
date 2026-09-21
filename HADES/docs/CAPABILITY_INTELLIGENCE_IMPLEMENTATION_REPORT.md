# Capability Intelligence implementation report

Campaign: HADES capability intelligence, plugin interoperability, and multi-agent orchestration.
Honesty vocabulary: PASS / FAIL / SKIPPED / UNVERIFIED. This report does not treat unrun gates as PASS.

## Repository state

| Item | Value |
|---|---|
| Starting point | `origin/main` `541a1d3` (HADES Trading Lab #116) |
| Feature branch | `cursor/capability-intelligence-2da6` |
| Resulting HEAD (at report authoring) | see branch tip; Work Runtime bridge landed after `7a93541` |
| Pull request | https://github.com/syneyexx/HADES/pull/117 |
| Commits | `e26b1ef` initial layer + GUI consolidation; `0893fb0` chat-context indent + adapter honesty; `3581cd0` cross-plugin composition; this report |

`main` was not modified.

## Architecture

Capability Intelligence is a **façade**, not a second execution engine.

Reused:

- PluginManager (`platform_services_core.py`) — import/enable/invoke, MCP expand, uninstall
- Plugin Runtime v2 — trust, effects, `eligible_for_autonomous`, global side-effect policy
- Plugin knowledge index — static knowledge fast path (no subprocess)
- Plugin registry cache — invalidated on capability refresh
- MCP host — dynamic `mcp__*` tools ingested as providers + tools
- Context Compiler / `assemble_chat_context_messages` — bounded skill fragments
- Work Runtime, coding verification, execution leases — mutation/verification fences
- `reasoning/tools.discover_tools` — lexical shortlist plus optional capability boost when lexical score > 0

Introduced: `backend/capability_intel/` including `work_bridge.py`.

Chat retrieval calls `observe()`: simple requests stay route-only; complex requests persist a mission. Work Runtime uses `build_work_plan_from_composition` for repair/implement goals so the Work Planner LLM is skipped when the template validates. Coding jobs attach a capability_intel snapshot on start (fail-open). Plugin agents are capability refs; TaskRunner still executes HADES specialists (`tool_orchestrator`, `build`, `critic`).

```text
External package
  → format detection (AdapterRegistry)
  → adapter parse
  → HADES normalization (CanonicalCapability)
  → SQLite + in-memory registry
  → policy/trust/health filter
  → hybrid ranker (no LLM)
  → smallest_team composition
  → PluginManager / native execution
  → deterministic verification
```

Core routing never branches on ecosystem names (`claude`, a plugin id, a repo format). New ecosystems add an adapter.

## Capability taxonomy

Plugin is a **container**. Kinds:

`skill` · `knowledge` · `tool` · `tool_provider` · `mcp_provider` · `agent` · `service` · `workflow` · `resource`

Contract version: `capability_intel.taxonomy.CONTRACT_VERSION = 1`.

Legacy `plugin_type` + `tools[]` still normalize to executable `tool` + derived `tool_provider`. The newer semantic `capabilities:` block is distinct from Plugin Runtime v2 effect contracts (`effects` / `cost_class`). Skills and knowledge are forced to `side_effect_class=none`.

Native HADES records participate in the same registry (`hades.coding_agent`, repository/git inspect, retrieval, artifacts, verification, Work Runtime, model routing). Native is not automatically preferred over plugins.

## Upstream adaptation

Adapter `claude_upstream` maps portable artifacts. Unsupported mappings are returned as `unsupported`, not coerced.

| Upstream | HADES |
|---|---|
| `SKILL.md` | `skill` (untrusted, `instruction_authority=false`) |
| `CLAUDE.md` | scoped `knowledge` |
| Persona / `type: persona` | `skill` + `persona_only` — **not** an executable agent |
| Markdown under `agents/` by convention | `skill` until an adapter proves delegated execution |
| Executable subagent (tools/accepts/produces) | `agent` |
| `commands/*.md` | `workflow` |
| MCP config / expanded tools | `mcp_provider` + `tool` |
| Hooks | **unsupported** — no safe HADES lifecycle equivalent |

See `docs/UPSTREAM_CAPABILITY_ADAPTATION.md`.

## Routing

Planner `plan_requirements` is deterministic. `model_adjudication` is always false. No planning LLM.

Goal `repair_repository_bug` implies skill + search + modify + tests + verify, plus domains such as `software.concurrency` / `debugging` when the query mentions race/deadlock/fix.

Ranker (`capability_intel.ranking.WEIGHTS`), explainable components:

- plus: exact reference, lexical overlap, deterministic synonym expansion (`semantic_relevance`), intent aliases, domain intersection, kind (only if another signal exists), health, bounded reliability
- minus: cost class, latency, side-effect class, agent/workflow kind, known-dead routes

Embedding cosine rerank for tools is **not** implemented. Existing retrieval embeddings stay in the retrieval pipeline.

Explicit eligible provider (`Use Desktop Commander`) is honored without a model call.

Policy still calls `eligible_for_autonomous` and `evaluate_global_side_effect_policies`. Skills skip subprocess eligibility but still require an enabled/ready plugin.

`smallest_team` covers required kinds with the fewest providers: complementary plugin agents (distinct plugin + specialty), one search tool (plugin preferred inside a score band), native verifier when verification is required. Simple explain tasks allocate zero agents.

## Skills

Retrieved as bounded fragments (`DEFAULT_BUDGETS.skill_fragment_chars`, max 4 items). Exact/near-duplicate content is dropped. Packed as ContextItem `kind=skill`. `subprocess=false`. Fail-open in chat context assembly.

## Agents

Normalized `AgentContract`: specialties, accepts, produces, executable vs `persona_only`. Built-in Coding Agent and Verifier are registry records. Plugin agents from the semantic `capabilities.agents` block are first-class.

Roles: planner / implementation_owner / verifier. At most one `implementation_owner`. Writes are intended to go through that owner; existing workspace/execution leases remain the mutation fence.

## Collaboration

`CollaborationSession` message types: task_assignment, task_handoff, finding, question, answer, proposal, critique, artifact_reference, evidence_reference, verification_request, verification_result, blocked, completed.

Sender identity is runtime metadata. Claimed `sender` that disagrees is `sender_spoof_rejected`. Injection-shaped summaries are stored as `untrusted_injection_ignored`.

Mission state is compact (goal, requirements, facts, assignments, artifacts, evidence, verification, completed work, dead providers). Consultation payloads set `full_mission: false`.

Budgets: max 3 agents, depth 2, 24 messages, 2 critique cycles, 4 consultations. Ping-pong on the same summary raises `deadlock`. Cancel/restart keep completed work.

## Safety

Planning recommends. Execution still requires plugin enabled/ready, trust, global policy, schemas, approvals, PluginManager.invoke. Skill/tool/plugin text cannot grant system authority.

Verification: `execution_success` ≠ `verified_task_success`. Agent self-report and consensus are not proof. Deterministic evidence (`tests_passed`, `schema_valid`, `build_ok`, `lint_ok`) skips a verifier-model call.

## Token / model efficiency

| Fast path | Behavior |
|---|---|
| Explicit eligible provider | No LLM routing call |
| Policy block | No downstream execution from this layer |
| Static skill/knowledge | No subprocess |
| Simple explanation | No multi-agent coding workflow |
| Cached route key + registry state hash | Reuse |
| Deterministic verification sufficient | `verifier_model_called=false` |

Token fields are stored as provider values or `NULL`. They are never invented.

Model calls **removed** relative to a naïve planner/adjudicator: every user request does **not** call a planning model; routing is deterministic; simple tasks do not spawn agents.

## GUI consolidation

Authoritative product GUI: `main.tsx` → `HadesApp` + Classic pages under `components/hades/pages/`.
Obsidian remains a **visual skin** of those pages (`ui_style`). See D019.

Removed as obsolete (not used by main product logic):

- `components/hades/v3/`, `v4/`, `beta/`
- `components/hades/styles/v3|v4|beta/`
- `public/beta-reference/`
- `docs/V3_INTERFACE.md`
- `tests/v3-template.test.mjs`, `v4-template.test.mjs`, `beta-template.test.mjs`, `beta-reference-master.test.mjs`

Capability Intelligence UI is main-only: `PluginCapabilityGroups` on Plugins; Chat `ContextTurnPanel` “Capability intelligence” details; `/api/capability-intel/*`.

Shared components, API clients, and backend runtime used by main were retained.

## Verification

Exact commands and outcomes from this Linux cloud agent. Python is `python3`. `PYTHONPATH=backend`.

### PASS

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_capability_normalization \
  backend.tests.test_capability_upstream \
  backend.tests.test_capability_routing \
  backend.tests.test_capability_collaboration \
  backend.tests.test_capability_integration -v
```

**33 OK** (includes four-provider composition asserting skill plugin-skills + agents plugin-alpha/plugin-beta + tool plugin-tools + `hades.verification`, and the simple inverse with zero agents).

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_plugin_intelligence_layer \
  backend.tests.test_plugin_runtime_v2 \
  backend.tests.test_plugin_tool_autonomy \
  backend.tests.test_reasoning -v
```

**35 OK**

```text
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_gen2_verified_experience \
  backend.tests.test_audit_a08_embeddings_context -v
```

**22 OK** (after fixing `assemble_chat_context_messages` IndentationError)

```text
PYTHONPATH=backend python3 -m unittest backend.tests.test_policy_settings_fail_closed
```

**1 OK**

```text
PYTHONPATH=backend python3 -m unittest backend.tests.test_work_skills_completion
PYTHONPATH=backend python3 -m unittest backend.tests.test_work_verification_evidence_coverage_honesty
PYTHONPATH=backend python3 -m unittest backend.tests.test_coding_agent_heuristic_safety_p0
PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_mcp_host_management.McpHostProtocolTests \
  backend.tests.test_mcp_host_management.McpHostStoreTests \
  backend.tests.test_mcp_host_management.McpIsErrorClassificationTests
```

**PASS** (10 + 2 + 3 + 7 tests)

PluginManager capability-intel refresh does not hang isolated invoke/import tests (`test_ready_convert_stays_disabled_until_user_enables`, `test_expand_mcp_does_not_mutate_disabled_ready_state`, `test_service_lock_serializes_concurrent_starts`).

```text
node --test tests/gui-consolidation.test.mjs tests/capability-intel-ui.test.mjs \
  tests/ui-style-system.test.mjs tests/release-gate-inventory.test.mjs
```

**14 PASS**

On SHA `e26b1ef` (frontend of this branch; later commits did not change frontend):

- `npm run typecheck` PASS
- `npm run lint` (`eslint . --max-warnings 0`) PASS
- `npm run build` (Vite production) PASS

### FAIL

None in the suites that completed.

### SKIPPED / UNVERIFIED

| Gate | Status | Reason |
|---|---|---|
| Full `python3 -m unittest discover -s backend/tests` | UNVERIFIED | Not completed. FastAPI `TestClient` suites in this Linux agent hang (same class as previously documented `test_conversation_create_and_list`). Whole-module `test_plugin_runtime_bugfixes` / `test_reasoning_orchestration` / `test_mcp_host_management` timed out at 45–90s when they include HTTP app tests. |
| `python verify_hades.py` / `VERIFY_HADES.bat` | UNVERIFIED | Full release gate not run in this agent. |
| Native CMake/CTest | UNVERIFIED | Not run. |
| Windows host | UNVERIFIED_ON_HOST | Linux cloud agent only. |
| Live LM Studio multi-agent coding | UNVERIFIED_ON_HOST | Collaboration tests exercise the structured protocol with fixtures, not two live plugin agents through a model. |
| GitHub Actions `release-gates` on PR #117 | UNVERIFIED | Jobs did not start: account payments failed / spending limit. Infra, not a code verdict. |
| Embedding tool rerank | Not implemented | Documented; synonym expansion only. |
| Exact provider token values | Not asserted | Stored NULL/unknown unless a provider reports them. |

## Limitations

- Capability Intelligence **recommends**; it does not execute tools. Side effects still go through PluginManager.
- Cross-plugin “coding agents” in fixtures are capability records + structured messages. They are not separate OS processes unless a plugin already provides that runtime.
- `semantic_relevance` is synonym expansion, not vector similarity.
- Historical performance may influence ranking only with sample size ≥ 3; agents cannot write persistent weights.
- Obsolete V3/V4/BETA **product** interfaces were removed. Historical notes under `docs/evidence/` may still mention them as flight-cert history.

## Acceptance mapping (honest)

| Criterion | Status |
|---|---|
| Semantic kinds | PASS (taxonomy + tests) |
| Skills without subprocess | PASS (retrieval + knowledge fast path tests) |
| Routing beyond lexical overlap | PASS (intent/domain/synonym + four-provider test) |
| Provider abstraction (no plugin-name core logic) | PASS (adapters + ranker) |
| Plugin agent contract | PASS (normalization + role assignment) |
| Cross-plugin cooperation | PASS at protocol/fixture level; live model UNVERIFIED_ON_HOST |
| Structured provenance-aware messages | PASS |
| Smallest capable team | PASS (simple inverse + budgets) |
| Single mutation owner | PASS in orchestration tests |
| MCP as dynamic provider | PASS (registry ingest test) |
| Claude/upstream adaptation | PASS including unsupported hooks |
| Policy/trust not bypassed | PASS (policy_allows + injection test) |
| Verification ≠ self-report | PASS |
| Cost fast paths | PASS |
| Explainable selection | PASS (`reasons` / `components`) |
| One main GUI | PASS (gui-consolidation tests) |
| Legacy plugin manifests | PASS |
