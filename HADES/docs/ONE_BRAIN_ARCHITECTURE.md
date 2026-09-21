# One Brain architecture

HADES is **one intelligence system with specialized execution runtimes**.

One Brain is a set of **canonical cognition/control contracts**, not `backend/main.py` and not a giant class.

```text
                         HADES BRAIN
                              │
         Capability / Agent / Mission Intelligence
                              │
       Context / Models / Memory / Tools / Verification
                              │
        ┌─────────────┬─────────────┬─────────────┐
      Coding        Trading        Media       Research
                      specialized deterministic runtimes
```

## Ownership

The substrate map lives in `hades_brain.substrate.SUBSTRATE`. Existing modules keep internals:

| Concern | Canonical owner |
|---|---|
| Capabilities | `capability_intel` (`CanonicalCapability`) |
| Agents | `AgentContract` + `hades_brain.agent_protocol` projections |
| Collaboration / mission | `capability_intel.collaboration` |
| Context compiler | `reasoning.context` / `chat_context` |
| Model intelligence | `reasoning.model_router` |
| Tools / MCP execution | PluginManager + `mcp_host` |
| Policy / trust / approval | `plugin_runtime_v2`, approvals, MCP host policy |
| Evidence | shared concepts; domain engines remain proof |
| Nodes | `compute_fabric.LocalExecutor` + `host_capability` (local only) |
| External MCP catalog | `mcpmarket` discovery → MCP Host connect |

MCPMarket never executes tools, never grants trust, and is not required for startup.

## Domain runtime boundary

Runtimes may implement:

`describe_capabilities` · `accept_mission` · `status` · `pause` · `cancel` · `resume` · `artifacts` · `evidence` · `verification`

They **must not** share internal implementation. Trading clock/ledger/risk, coding worktrees, FFmpeg, and research crawl stay specialized.

## Provider normalization

```text
external representation → format adapter → CanonicalCapability → Capability Intelligence
```

Sources: native, plugins, MCP host, MCPMarket, future marketplaces. Unknown fields stay unknown. Routing reasons over traits (`executable`, `retrievable`, `delegatable`, …), not vendor names.

## Agent protocol

Domain roles (Trading Validator, Coding Investigator, Media Editor, Research Worker) project into the same HADES agent protocol. An extra agent requires a recorded reason (unique capability, specialist, parallelism, independent verification, authority separation, information gain).

Handoffs are deltas + refs (`artifact_ref`, `evidence_ref`, …), never full transcripts.

## Mission context views

Compile role-specific views (`hades_brain.mission.compile_role_view`). Example: Coding Test Engineer gets diff refs + impacted tests + acceptance — not the mission dump.

## Token / cost invariant

Minimum sufficient intelligence for a verified result. See `docs/INTELLIGENCE_COST_MODEL.md`.

## Cognitive Runtime (Pillars II)

`backend/cognitive/` is the One Brain façade for ten evidence-backed cognitive
capabilities. It extends existing owners; it is **not** a second Brain.

| Pillar | Module | Reuses |
|---|---|---|
| Machine Self-Model | `cognitive.self_model` | `host_capability`, sandbox honesty, Neural settings, `capability_intel`, `hades_brain.node` |
| Active Perception | `cognitive.perception` | `reasoning.information_gain`, `SharedBudgetPool` |
| Epistemic Engine | `cognitive.epistemic` | evidence/verification signals |
| Ontology Evolution | `cognitive.ontology` | Temporal Graph / Agent Factory pattern discipline |
| Cognitive Immune | `cognitive.immune` | secret/Neural eligibility patterns; quarantine store |
| Mental Models | `cognitive.mental_models` | Project Continuity + capability outcome metrics |
| Homeostasis | `cognitive.homeostasis` | perf envelopes, Neural degrade, budget signals |
| Self-Repair | `cognitive.self_repair` | Coding investigate/worktrees (proposal only) |
| Scientific Method | `cognitive.scientific_method` | Eval Lab A/B measurement pattern |
| Credit Assignment | `cognitive.credit` | Flight Recorder / verified-experience causality tiers |

Feature modes: **OFF / SHADOW / ACTIVE** (defaults conservative; immune fail-closed ACTIVE).
HTTP: `/api/cognitive/*` and `/api/hades-brain/self-model`.
Learned controllers recommend; they never grant tool/MCP/filesystem authority.

## Node compatibility

HADES advertises the local process (CPU/RAM/GPU probes when available, plugins, MCP providers). Distributed peering is **not** implemented. Prefer executing where large data already lives.

## Future domains

Add a `DomainRuntime` adapter and native capability records. Do not redesign the brain.
