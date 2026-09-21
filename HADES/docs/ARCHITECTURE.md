# HADES architecture

## Product intent

HADES is an **offline-first local AI workspace**. The local model/runtime must remain useful without internet. Internet, plugins and external sources extend capability when available and permitted; they are not required for the core to boot.

## High-level layers (current runtime)

```text
React / TypeScript UI
        |  typed HTTP / events (lib/hades-api.ts)
        v
FastAPI transport (backend/main.py + extracted routers)
        v
Application / reasoning / policy (Python)
        |
        +-- LM Studio / SQLite / PluginManager / Gen2
        |
        v
NativeRuntimeFacade (infrastructure/native/)
        |  versioned JSON-RPC
        v
hades_native_runtime (C++20 bounded executor)
        |  processes, FS/index, metrics
```

Python owns intelligence, orchestration, policy, and application state.
C++ owns deterministic OS/compute work with bounded concurrency and truthful capabilities.
See `docs/architecture/python-cpp-boundary.md`.

`backend/main.py` remains a hotspot; extract routers/services incrementally (brain/models/native/voice already partially extracted).

## Product surface (HADES-10)

Chat is the primary intelligence surface (`#/chat`). Advanced consoles remain available.
Archived Gen2 planning: `docs/archive/planning/`. See D018.
The only supported GUI is `HadesApp` (Classic pages; Obsidian is a visual skin). See D019 and `docs/CAPABILITY_INTELLIGENCE.md`.

## Gen2 modules (existing, not backlog)

Existing Gen2/runtime modules may be reused from Chat or Advanced. Do not treat
archived roadmaps as open implementation authority.

```text
HADES OS
  → Mission Control
  → Reasoning Kernel / Agents / Scheduler
  → Capability Fabric
  → Plugins / MCP / Native Tools
  → Secure Execution Fabric
  → Local / Container / Remote Nodes
  → Intelligence Data Plane
  → Memory / Knowledge / Evidence / Temporal Graph
  → Evaluation / Replay
```

Gen1 “50 capabilities” are baseline (archived under `docs/archive/`). Do not reopen that backlog.

## Reasoning/runtime pipeline

The target HADES pipeline is:

```text
Request
  -> intent + difficulty
  -> relevant context retrieval
     - Memory
     - Knowledge
     - Evidence/current web when allowed
  -> plan only when complexity requires it
  -> specialist agent / tool selection
  -> bounded execution
  -> independent verification / acceptance check
  -> final answer or truthful failure/incomplete state
  -> selective Memory / Knowledge update
```

The model may reason internally, but HADES should persist useful **plans, evidence, tool results, acceptance criteria and verification metadata**, not hidden chain-of-thought.

## Knowledge model

Keep these roles distinct:

1. **Memory** — compact durable facts/decisions/preferences with versioning/supersession.
2. **Knowledge Library** — chunked reusable bulk material: files, documents, conversations, datasets.
3. **Evidence Vault** — source snapshots/provenance used to support claims and research.

Retrieval should prefer relevance and provenance, not dump entire stores into prompts.

## Plugin architecture

Plugins stay behind an adapter/process boundary. HADES owns:
- manifest/package validation,
- permissions,
- dependency lifecycle,
- tool registry,
- execution supervision,
- health verification,
- persistent logs/results,
- routing from both UI and autonomous AI.

The external project owns its own runtime/code. Do not merge arbitrary upstream source into HADES Core.

## Deterministic vs model responsibilities

**Deterministic code:** permissions, file boundaries, process execution, health checks, database writes, migrations, cancellation, exact-once transitions, trading safety, artifact paths.

**Model:** language understanding, planning suggestions, synthesis, source-gap analysis, tool choice within the eligible catalog, critique/verification reasoning.

Never ask the model to “decide” whether a blocked permission is allowed.

## Offline/network behavior

- Loopback LM Studio is the normal model path.
- `network_policy=block` must prevent external network use.
- If network is allowed but unavailable, online enrichment should fail gracefully and continue with local evidence where possible.
- Current-web knowledge must be treated as fresher evidence, not silently converted into timeless Memory.

## Persistence

SQLite is the durable local system of record. Existing user data must survive upgrades. Use migrations/forward-compatible column/table creation rather than destructive resets.

## UI architecture

The current HADES GUI is an established product constraint. Functional work should reuse the current shell and components. Avoid broad stylesheet rewrites for backend/runtime tasks.


## Reasoning kernel (2026-05-09)

Shared orchestration helpers live in `backend/reasoning/` and are used by chat and Work Runtime. See `docs/REASONING_ARCHITECTURE.md`.
