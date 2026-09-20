# LEVIATHAN System Reference — HADES Architecture

> Purpose: preserve the useful architectural knowledge from HADES as a reference while LEVIATHAN is rebuilt from the ground up.
>
> This is **not** an instruction to copy HADES file-for-file. It documents how HADES works today, which invariants proved important, where complexity accumulated, and which ideas should inform LEVIATHAN.

## Reference snapshot

This document was prepared against the current `syneyexx/HADES` main line around commit:

`f143707ddc4bf0d613e07b727427c4be8bc054b6`

Important recent architectural work before that snapshot included:

- Tool Kernel + Capability Broker.
- approval and execution-truth hardening.
- linked Work completion truth.
- container/native isolation truth.
- Coding Agent cancellation and model-call lifecycle hardening.
- call-id based tool/event reconciliation.
- research/network policy hardening.
- Neural V2 associative retrieval work.
- central trace/logging and release-gate honesty.

HADES remains the behavioral reference. LEVIATHAN should preserve proven invariants but redesign the structure cleanly.

---

# 1. What HADES is

HADES evolved into a local-first AI operating framework rather than a simple chat application.

At a high level it combines:

- chat and model orchestration;
- reasoning and request understanding;
- tools and capability discovery;
- plugins and MCP integrations;
- execution policy and approvals;
- persistent Work tasks;
- agents such as Coding and Research;
- Knowledge, Memory, Evidence and Artifacts;
- optional Neural associative memory;
- native/C++ execution support;
- workflows, schedules and mission-style orchestration;
- observability, evaluations and release gates;
- multiple frontend shells/pages.

The main architectural lesson is that these systems must share the same truth about execution, authorization, lifecycle and evidence.

---

# 2. Simplified HADES architecture

```text
USER / UI
   │
   ▼
API / Chat entry
   │
   ▼
Request understanding / routing
   │
   ├───────────────► direct model response
   │
   ├───────────────► research / knowledge / memory context
   │
   └───────────────► tool-capable loop
                         │
                         ▼
                 HADES Tool Kernel
                         │
             capability search/inspect/invoke
                         │
                         ▼
                 Capability Broker
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   Core tools        Plugins/MCP      Native runtime
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                 Execution authority
                         │
                 Policy / Approval
                         │
                 Isolation / timeout
                         │
                         ▼
                   ToolObservation
                         │
                         ▼
                 Context / evidence
                         │
                         ▼
                    Model answer
```

Long-running work adds another owner:

```text
Chat / Agent / Mission
        │
        ▼
     Work Runtime
        │
        ▼
   persisted task state
        │
        ├── steps
        ├── tool calls
        ├── checkpoints
        ├── artifacts
        └── verification
        │
        ▼
 authoritative completion decision
```

---

# 3. Chat and request understanding

HADES receives a user turn and builds a structured understanding of what the request appears to require.

Historically this area accumulated keyword-based routing and intent heuristics. Later hardening made an important distinction:

- trivial, self-contained conversation can remain `direct_chat` with no tool schemas;
- actionable requests involving files, attachments, workspace state, fresh information or explicit actions must not lose access to the tool plane merely because a classifier misses one keyword;
- explicit no-tool instructions can suppress execution.

The important LEVIATHAN lesson is:

> Classification may influence routing, but a cheap intent classifier should never become the sole authority that makes execution capability disappear for an obviously actionable request.

---

# 4. Model layer

HADES uses a model gateway/provider abstraction so local models such as LM Studio can be used without coupling the rest of the application to one concrete provider.

The model layer is responsible for model calls and provider-facing message formatting, but it is **not** the source of truth for whether work actually completed.

Important invariant:

```text
model output != execution evidence
```

A model can propose, plan and describe. Completion must come from actual state, tool observations, persisted work status and verification.

---

# 5. HADES Tool Kernel

Modern HADES introduced a deliberately small stable model-facing Tool Kernel under `backend/core_tools/`.

Representative capabilities include:

- filesystem listing;
- filesystem reading;
- filesystem writing;
- terminal execution;
- knowledge search;
- memory proposal;
- web fetch when network policy allows it;
- capability search;
- capability inspection;
- capability invocation.

The key design is that HADES does **not** need to inject every plugin or MCP schema directly into every model request.

Instead the model gets a small stable kernel and can discover dynamic functionality through the capability broker.

This reduces prompt/tool-schema bloat and keeps external integrations dynamic.

---

# 6. Capability Broker

The Capability Broker is the bridge between model-facing core tools and the larger dynamic ecosystem.

Conceptually:

```text
Model
  │
  ├── hades.capabilities.search
  ├── hades.capabilities.inspect
  └── hades.capabilities.invoke
            │
            ▼
      Capability Broker
            │
     eligible providers only
            │
    ┌───────┼────────┐
    ▼       ▼        ▼
 plugin     MCP     other provider
```

Important distinction:

```text
discoverable != authorized
```

A capability may exist and be visible without being allowed to execute.

LEVIATHAN should preserve this separation between:

- capability metadata;
- eligibility;
- policy;
- authorization;
- approval;
- execution.

---

# 7. Plugins and MCP

HADES supports both plugins and MCP integrations.

Over time many integrations accumulated custom wrappers and compatibility code. This is one of the areas LEVIATHAN intends to redesign rather than reproduce structurally.

The useful HADES behavior to retain is:

- integrations expose typed capabilities;
- dynamic capabilities are discovered rather than blindly injected into every prompt;
- policy applies before execution;
- approval is server-authoritative;
- tool output is treated as untrusted input when returned to the model;
- network and filesystem effects are explicitly classified.

For LEVIATHAN, plugins/MCP should eventually converge on one normalized capability contract instead of being separate reasoning worlds.

---

# 8. Execution path

HADES hardened execution around a shared authority boundary.

A generic execution path should conceptually look like:

```text
Capability request
   ↓
Schema validation
   ↓
Policy evaluation
   ↓
Authorization
   ↓
Approval if required
   ↓
Isolation selection
   ↓
Execution
   ↓
Timeout / cancellation handling
   ↓
Effect recording
   ↓
Output validation
   ↓
ToolObservation
```

This prevents individual agents or plugins from inventing their own security rules.

A major lesson from HADES is to avoid parallel generic executors. Coding, Research, Work and integrations should not each own a separate version of subprocess/network/approval logic.

---

# 9. Approval and authorization

HADES previously had call paths where client-provided booleans such as `approved_by_user` or `preapproved` could become too authoritative.

That was hardened so persisted server-side approval state is the real authority.

Core invariant:

```text
request boolean != authorization
```

A durable approval must be scoped to the operation/effect being approved.

Examples of effect kinds include:

- subprocess/process execution;
- network access;
- file reads;
- file writes;
- other side effects defined by capability policy.

LEVIATHAN should start with this rule rather than retrofit it later.

---

# 10. Isolation and native execution

HADES supports multiple execution modes, including host process execution, native runtime support and stronger isolation modes.

Important honesty rules that emerged:

- requested isolation and effective isolation must be separate fields;
- container/secured modes may not silently downgrade to ordinary host subprocess execution;
- required native execution may not silently pretend native execution succeeded when it fell back;
- optional/auto native fallback, when allowed, must be explicit and observable;
- isolation claims must describe what actually happened, not what was requested.

Core invariant:

```text
requested isolation != effective isolation
```

unless the runtime verified they are the same.

---

# 11. Work Runtime

HADES has a persistent Work runtime for long-running or multi-step tasks.

The Work runtime owns authoritative task lifecycle and persisted task state.

Typical concepts include:

- task/run identity;
- queued/dispatched/running states;
- steps;
- task events;
- tool calls;
- cancellation;
- verification checkpoints;
- artifacts;
- failure state;
- completion state.

A crucial invariant is:

```text
chat completed != Work completed
```

The chat layer may report on a task, but it must not mark a linked Work task completed simply because a conversational response was generated.

The same principle applies to schedules and missions:

```text
dispatch != completion
```

---

# 12. Verification and completion truth

HADES has progressively separated generation from verification.

Completion should require evidence appropriate to the task.

Examples:

- a requested file should actually exist;
- a produced artifact should resolve to a real stored artifact;
- tests claimed as passed should have an executed result;
- a failed deterministic check cannot be overridden by a model critic saying the work looks good;
- a rejecting critic cannot result in `completed`;
- sourced claims can be checked against evidence/citations.

Useful truth model:

```text
requested
executed
persisted
verified
completed
```

These are different states and should not be collapsed into one boolean.

---

# 13. Coding Agent

HADES contains a specialized Coding Agent with its own planning and verification behavior.

Recent hardening focused on:

- real ownership of model-call cancellation;
- no stranded asynchronous model tasks;
- tool execution through shared authority boundaries;
- verification before success;
- explicit failure instead of fabricated green status.

The architectural lesson for LEVIATHAN is that an agent should own **strategy**, not infrastructure.

A Coding Agent may decide what files to inspect, edits to make and checks to run, but should rely on shared filesystem, terminal, policy, approval, persistence and lifecycle services.

---

# 14. Research

HADES research combines retrieval, network policy, source evidence and model synthesis.

Network policy is important:

- if web/network access is blocked, HADES must not claim fresh web research happened;
- local Knowledge, cached evidence, uploaded documents and existing sources may still support a local research answer;
- network allow/deny rules and redirect security are enforced independently of model intent.

Important distinction:

```text
web research blocked != all research impossible
```

but the answer must accurately describe which source classes were available.

---

# 15. Knowledge

HADES Knowledge is persistent retrievable information, distinct from conversational Memory.

The system has included:

- knowledge sources;
- chunking/indexing;
- retrieval;
- project/source metadata;
- atomic ingest improvements;
- retention and indexing work.

One hardening pass made source + chunks commit atomically so a source is not presented as ready when chunk ingest failed halfway.

LEVIATHAN should retain this concept of ingest truth.

---

# 16. Memory

HADES Memory stores persistent remembered context/preferences/history separate from the normal Knowledge corpus.

A useful design principle is that memory writes should be deliberate proposals/controlled persistence rather than arbitrary model text becoming durable truth automatically.

Memory deletion should also invalidate associated search/index state.

LEVIATHAN currently has no full memory subsystem yet.

---

# 17. Evidence and Artifacts

HADES increasingly treats Evidence and Artifacts as first-class concepts.

- **Evidence** supports claims and completion decisions.
- **Artifacts** are concrete outputs such as files/documents/results.

The model response itself is not sufficient evidence that an artifact was created.

A robust system should store references that can be resolved and verified.

---

# 18. Neural V2

HADES Neural V2 is not a replacement LLM.

It is an experimental associative memory/retrieval layer using embeddings.

At the current reference point:

- production embeddings are intended to come from LM Studio;
- exact retrieval and neural/associative retrieval can be combined;
- SHADOW mode can score without injecting neural associations;
- READ mode can inject bounded untrusted associations when enabled;
- verified outcomes can feed experience data;
- defaults remain conservative/off;
- evaluations remain explicitly unmeasured when the required embedding provider is unavailable.

Most important architectural rule:

> Neural may provide signals and retrieval hints, but must never become authority for permissions, approvals, tool execution or completion truth.

This is especially relevant for LEVIATHAN because its Neural system will likely be redesigned from scratch later.

---

# 19. Native runtime

HADES contains native/C++ runtime work intended for cases where a native implementation is justified.

Possible roles include:

- process supervision;
- lower-level execution helpers;
- performance-sensitive operations;
- host/resource interaction.

The lesson for LEVIATHAN is not to move orchestration into C++ by default.

Python remains appropriate for control-plane/business logic, with native code behind explicit interfaces only where it provides measurable value.

---

# 20. Frontend

HADES has gone through multiple frontend generations and shells.

The frontend presents Chat, Work, agents, workflows, settings, knowledge and other surfaces.

One recurring problem in large AI applications is frontend state becoming a second source of truth.

The preferred rule is:

```text
backend authoritative state
        ↓
API/events
        ↓
frontend projection
```

rather than optimistic UI state inventing completion or health independently.

LEVIATHAN should keep this rule from the beginning.

---

# 21. Storage and database behavior

HADES uses persistent local storage heavily for conversations, tasks, knowledge, memory, events, tool calls and related state.

As HADES grew, many parts of the system touched storage directly. For LEVIATHAN, the cleaner target is repository/service boundaries around persistence.

Desired future concepts include:

- ConversationRepository;
- RunRepository;
- ToolCallRepository;
- ArtifactRepository;
- EvidenceRepository;
- KnowledgeRepository;
- MemoryRepository;
- ApprovalRepository;
- CapabilityRepository.

The exact implementation can evolve, but transaction boundaries and ownership should be explicit.

---

# 22. Observability

HADES added stronger observability over time, including:

- trace IDs;
- durable rotating logs;
- tool-call/event tracking;
- task events;
- requested-vs-effective execution metadata;
- evaluation artifacts;
- release gates that can report `UNMEASURED` instead of fabricating PASS.

Important principle:

```text
not measured != passed
```

LEVIATHAN should preserve this standard.

---

# 23. Security/trust boundaries

Important HADES security rules include:

- local API trust checks;
- guarded non-loopback binding;
- URL/redirect validation;
- domain allow/deny policy;
- loopback/SSRF protections;
- tool outputs marked as untrusted before they are fed back to the model;
- approval enforcement at execution boundaries;
- stronger isolation modes fail closed.

These should be considered architectural requirements, not optional later polish.

---

# 24. HADES architectural debt LEVIATHAN should avoid

HADES is valuable precisely because it shows where an organically grown AI system accumulates complexity.

Areas to avoid reproducing mechanically:

- a very large central `main.py` acting as orchestration, API and integration layer;
- duplicate lifecycle semantics across Chat, Work, Missions, Workflows and schedules;
- multiple execution paths that each partially implement policy/approval;
- many custom plugin wrappers where declarative or standardized adapters could work;
- keyword routing becoming control-plane authority;
- frontend and backend independently inferring completion;
- direct database access scattered through business logic;
- compatibility layers becoming permanent architecture;
- subsystem-specific result schemas instead of one canonical observation/result contract.

LEVIATHAN should use HADES as an executable specification and lesson library, not as a folder template.

---

# 25. Recommended LEVIATHAN target concepts derived from HADES

These are concepts worth preserving at a cleaner level:

```text
LEVIATHAN Core
├── Run / lifecycle
├── Context engine
├── Model gateway
├── Reasoning / planner
├── Capability registry
├── Execution gateway
├── Policy
├── Approval
├── Verification
├── Knowledge
├── Memory
├── Evidence
├── Artifacts
├── Storage repositories
└── Observability
```

Extensions can then sit above the core:

```text
Extensions
├── Coding
├── Research
├── Neural
├── Plugins
├── MCP
├── Browser
├── Trading
├── Media
├── Voice
└── Automation
```

The core should not depend on any one extension.

---

# 26. Truth invariants to carry into LEVIATHAN

These are among the most important lessons from HADES:

```text
model output != evidence
request boolean != authority
discoverable capability != authorized capability
chat completed != Work completed
dispatch != completion
requested isolation != effective isolation
persist attempt != persisted state
unmeasured != passed
retrieved context != trusted fact
neural signal != authority
```

When LEVIATHAN grows, these invariants should be protected by tests.

---

# 27. Current LEVIATHAN relationship to HADES

LEVIATHAN is a new Python-first project.

Current LEVIATHAN does **not** yet reproduce the full HADES architecture. Step 1 intentionally contains only:

- Python/FastAPI backend;
- working persistent chat;
- OpenAI-compatible LLM connection;
- lightweight reasoning layer;
- SQLite conversation storage;
- SQLite Knowledge + FTS retrieval;
- existing dashboard/chat frontend.

Future systems should be added deliberately using the lessons above rather than copied wholesale.

---

# 28. Source-of-truth rule for this document

When this document disagrees with current executable code, current executable code and tests win.

For HADES, useful source files/documents to inspect before porting a concept include:

- `docs/CURRENT_STATUS.md`;
- `backend/core_tools/`;
- reasoning/understanding and routing code;
- PluginManager and execution gateway code;
- ApprovalService;
- Work runtime and completion gates;
- coding runtime/verification code;
- Knowledge/Memory/Evidence code;
- Neural status/implementation;
- isolation/native runtime tests;
- trust-boundary and release-gate tests.

Before implementing a large LEVIATHAN subsystem, inspect the corresponding HADES behavior and tests first, then redesign it for LEVIATHAN instead of directly transplanting obsolete structure.
