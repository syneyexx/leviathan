# LEVIATHAN — Project Context for ChatGPT

> **Purpose:** persistent high-level project orientation for ChatGPT and other AI-assisted development sessions working on LEVIATHAN.
>
> **Status:** this is **not** a third canonical architecture specification and it must never compete with implementation truth. The canonical architecture references remain [`Leviathan_system_backend.md`](./Leviathan_system_backend.md) and [`Leviathan_system_frontend.md`](./Leviathan_system_frontend.md). Current source code, schemas, executable tests, machine gates and verifier output remain authoritative for what is actually implemented and verified.

---

## 1. What LEVIATHAN is

LEVIATHAN is a **local-first autonomous AI operating and control platform**. It is designed as one coherent system that combines cognition, model control, knowledge, memory, evidence, tools, agents, durable workers, research, datasets, training/evaluation, external capabilities and an operator interface.

LEVIATHAN is **not** intended to become a loose collection of scripts, isolated agents or disconnected AI features. The architecture is deliberately built around canonical owners and shared infrastructure so that models, agents and domain systems can cooperate through governed interfaces instead of creating private parallel stacks.

The platform has a broad scope, but it does **not** have equal product priority everywhere.

**The primary product and engineering focus of LEVIATHAN is the autonomous trading system.**

Everything else — cognition, Brain/Knowledge/Memory, research, model routing, agents, workers, datasets, external modules, observability, execution governance and the frontend — remains important because these systems make the trading objective safer, smarter, more autonomous, more measurable and more extensible. They are also useful capabilities in their own right and should remain production-grade rather than becoming trading-specific hacks.

---

## 2. The main mission: an autonomous trading system

The flagship end goal is an **institutional-grade autonomous trading research and execution system** that can run the complete decision loop with minimal routine human intervention while remaining bounded by explicit authority, risk controls and evidence.

The intended trading loop is broader than “generate a signal and place a trade.” LEVIATHAN should be able to:

1. ingest and version market, financial, research and contextual data;
2. build causal, point-in-time observations without leaking future information;
3. retrieve relevant internal knowledge, documents, datasets and evidence;
4. formulate falsifiable market hypotheses and strategy ideas;
5. create, mutate, combine and compare strategy candidates autonomously;
6. simulate and backtest candidates using realistic costs and execution assumptions;
7. validate them out of sample, across regimes and under robustness/adversarial checks;
8. reject weak, overfit, unstable or economically invalid candidates;
9. qualify strategies through deterministic evidence-based gates;
10. deploy qualified strategies into shadow/paper operation;
11. manage simulated positions, portfolio exposure and risk continuously;
12. collect forward evidence and detect drift or degradation;
13. feed failures, observations and new evidence back into continual research;
14. preserve lineage, reproducibility, receipts and auditability throughout the lifecycle.

The objective is therefore **continuous autonomous research + qualification + paper operation + learning from measured evidence**, not a static rule-based bot and not an LLM improvising trades from prose.

### Current execution boundary

On current `main`, LEVIATHAN’s autonomous market execution boundary is **paper/shadow trading with simulated capital**. Real-money autonomous execution is intentionally **BLOCKED by construction**.

Future work must never describe the presence of broker UI, external finance tools, model confidence, backtest profitability or paper profitability as permission for live capital execution. If the project ever changes that boundary, it must be an explicit architectural, risk, security and governance decision — never an accidental side effect of an integration.

### What “autonomous” means here

Autonomy means that LEVIATHAN should increasingly be capable of deciding **what to research, what evidence it needs, what experiments to run, which candidates to reject, which qualified strategy to paper-deploy, when risk requires intervention and when new research is necessary**.

Autonomy does **not** mean bypassing controls. High autonomy and strong governance are complementary requirements. A capable autonomous trading system must have deterministic risk limits, kill switches, causal data boundaries, explicit permissions, durable state, observability, reproducibility and trustworthy receipts.

---

## 3. What exists around trading — and why it still matters

Trading is the highest-priority product objective, but the rest of LEVIATHAN is not disposable support code. The surrounding platform is a first-class part of the project.

### Cognition and reasoning

The CognitiveRuntime provides planning, adaptive reasoning, critics, verification, collaboration and capability use. It should allow LEVIATHAN to reason about difficult tasks rather than reducing every workflow to one model call.

For trading, cognition can support research planning, hypothesis formation, evidence gathering and controlled interaction with specialized capabilities. For the broader platform, the same runtime supports general reasoning and operator tasks.

### Brain, Knowledge, Memory and Evidence

LEVIATHAN separates these responsibilities deliberately:

- **Brain** is the unified access facade;
- **Knowledge** owns documents, chunks, retrieval and durable knowledge-side records;
- **Memory** owns durable scoped memories and correction/trust state;
- **Evidence** owns evidence and verification records;
- **Observations/receipts** record what capabilities actually did;
- **Neuro/Cortex** provides advisory association/residual capabilities.

Imported books, financial research, datasets, internal documents and other knowledge should become useful through canonical ingestion/retrieval paths rather than being copied into private agent silos.

The architectural direction is **shared, governed intelligence**: trading agents and other agents should be able to consume relevant LEVIATHAN knowledge and capabilities through the same canonical systems, subject to permissions, scope, provenance, causal-time rules and domain-specific safety constraints.

“Available to the network” does not mean “blindly injected into every prompt.” Retrieval should remain relevant, attributable and bounded.

### Model Control Plane

Models are shared infrastructure. Chat, cognition, coding, research and trading should use the central model control/runtime layers rather than creating subsystem-specific provider clients.

Model registration is not proof of capability. Residency, tool use, vision, reasoning and other properties must be represented by measured runtime truth where required.

**Selection authority:** production inference may only use a model with a valid Model Control Plane provenance (explicit request, agent requirement, role override, canonical active/default, configured fallback chain, or explicitly permitted cloud/settings policy). Discovery, registry sort order, and provider `/v1/models` list order are never execution policy. When no authority exists, routing fails closed — it does not pick the first eligible or first discovered model.

### Agent Fleet

LEVIATHAN has one canonical Agent Fleet and orchestration fabric. Trading specialists belong on that existing fabric rather than creating a second independent agent universe.

Agents should collaborate through shared jobs, knowledge, memory/evidence, signals and governed capability execution. Specialized missions are encouraged; duplicated authorities are not.

### Durable jobs and Worker Fabric

Serious autonomous operation cannot depend on one HTTP request staying alive. Heavy research, simulation, ingestion, embedding, training/evaluation, provider I/O, module work and database commit workloads belong on durable job/worker infrastructure where applicable.

Retries, leases, cancellation, priorities, resource declarations, checkpoint/resume and failure truth are part of autonomy, not infrastructure trivia.

### General research

LEVIATHAN’s research system is broader than finance. It can plan research, retrieve local material, optionally use external sources, preserve evidence, detect conflicting claims and produce citation-backed outputs.

For trading, this provides a route for broader market/company/macro/technical research to become evidence rather than untraceable model context.

### Datasets, training and evaluation

Data ingestion, dataset management, training and evaluation are long-term leverage for the system. They should support measured improvement without confusing “data exists” with “the system learned it,” or “a recipe exists” with “training succeeded.”

### External capability fabric

LEVIATHAN can extend itself through ModuleManager, plugins, MCP, skills and declarative external capabilities.

External tools should extend the platform, not replace canonical authority. For example, finance integrations such as **Fincept Terminal** may provide analytics/research capabilities, while MarketSim remains the trading authority. An external module may contribute information, calculations or tools, but it does not get to bypass LEVIATHAN’s execution, risk, evidence or causality boundaries.

### Operator frontend

The frontend is the operator surface for observing and controlling the system. It should show backend truth rather than inventing capability from UI state.

The long-term direction is not to require constant manual clicking. The UI exists to make autonomous behavior inspectable, controllable, debuggable and governable.

---

## 4. The end state

LEVIATHAN’s target is not “a chatbot with many tabs” and not “a profitable backtest.”

The desired end state is a **coherent autonomous intelligence platform with trading at its center**, capable of running long-lived, evidence-driven workflows and improving from measured outcomes.

For the trading mission specifically, the target system should be able to move from raw information to a governed paper-trading strategy lifecycle with minimal routine intervention:

```text
DATA / KNOWLEDGE / EXTERNAL EVIDENCE
                |
                v
        RESEARCH + HYPOTHESES
                |
                v
       STRATEGY DISCOVERY
                |
                v
      CAUSAL SIMULATION
                |
                v
 VALIDATION / ROBUSTNESS / GATES
                |
                v
       QUALIFIED STRATEGY
                |
                v
       SHADOW / PAPER RUN
                |
                v
 FORWARD EVIDENCE / RISK / DRIFT
                |
                v
      CONTINUAL RESEARCH
                +---------------------> back into the loop
```

The quality bar is **institutional engineering discipline**: causal correctness, reproducibility, realistic execution assumptions, portfolio-aware risk, deterministic qualification, observability, security, provenance and failure transparency.

That quality bar does not imply that LEVIATHAN currently matches any named financial institution’s performance, resources or proprietary systems. It describes the engineering standard the project is aiming for.

---

## 5. Product priority model

When priorities compete, use this hierarchy unless the current task explicitly says otherwise:

### Priority 1 — Autonomous trading capability and correctness

Work that materially advances a reliable end-to-end autonomous trading loop has the highest product priority. This includes data correctness, strategy research/discovery, simulation, qualification, portfolio/risk, paper execution, forward monitoring and continual research.

### Priority 2 — Foundations required for safe autonomy

Shared systems that make Priority 1 possible are equally serious engineering work: cognition, Knowledge/Brain/Memory/Evidence, model control, Agent Fleet, execution governance, jobs/workers, persistence, observability, security, datasets and external-capability integration.

A fragile foundation does not become acceptable because it is “only infrastructure.”

### Priority 3 — Broader LEVIATHAN capabilities

General research, coding, media, workflows, extensibility, operator UX and other platform capabilities remain legitimate first-class product areas. They should be built cleanly and can reuse the same shared foundations.

They should not, however, silently fragment the architecture or consume the project’s direction at the expense of the primary autonomous-trading mission.

---

## 6. Core engineering principles

Future work on LEVIATHAN should preserve these principles.

### One responsibility, one canonical owner

Do not solve a problem by creating a parallel runtime, second model router, duplicate Agent Fleet, private trading database, alternative execution authority or hidden side channel when a canonical owner already exists.

Extend the owner or its explicit adapter boundary.

### Shared knowledge, not isolated intelligence

Agents should not become isolated islands with their own private copy of the world. Relevant knowledge, documents, datasets, evidence and observations should be accessible through canonical shared services where policy permits.

Trading agents especially should be able to benefit from the broader intelligence available inside LEVIATHAN without violating point-in-time causality or leaking future information into simulation.

### Evidence over narrative

Model confidence is not evidence. A UI badge is not evidence. A configuration flag is not evidence. A backtest screenshot is not evidence.

Prefer measured state, deterministic gates, receipts, reproducible artifacts and attributable sources.

### Runtime truth over optimistic wording

Keep distinctions such as:

- configured != available;
- available != measured;
- registered != resident;
- tool listed != authorized;
- job started != completed;
- document present != learned/indexed;
- search result != fetched evidence;
- TRAIN success != qualified strategy;
- paper profit != proven future edge;
- broker integration != live-trading authority.

`UNMEASURED`, `UNAVAILABLE` and `BLOCKED` are valid states and must not be cosmetically turned into green success.

### Causality is non-negotiable in trading

Trading research must respect the information that was actually available at the decision timestamp. No future leakage, no post-event document leakage, no chart rendering with future candles and no adaptive reuse of protected holdout information.

### Risk is an authority, not a suggestion

Risk controls, kill switches, portfolio constraints, execution permissions and qualification gates must remain technically enforceable. An agent or model should not be able to talk its way around them.

### Doing is part of learning

Where safe and allowed, LEVIATHAN should learn from **actual controlled execution evidence** rather than remaining indefinitely theoretical. In trading, current policy means causal simulation, shadow operation and paper trading with durable forward evidence — not real-money experimentation.

### Production quality over demos

A feature is not complete because a page exists or a happy-path demo works. Autonomous systems require failure handling, persistence, restart behavior, concurrency correctness, observability, tests and clear ownership.

---

## 7. How future ChatGPT sessions should use this file

When a new ChatGPT/AI session works on LEVIATHAN, use this document to understand **mission and priority**, then inspect the current repository before making technical claims or changes.

### Required interpretation

1. **Autonomous trading is the primary product focus.**
2. **The rest of LEVIATHAN still matters and should remain high quality.**
3. **Shared platform systems should strengthen trading without becoming trading-only dead ends.**
4. **Current implementation truth must be verified in code/tests/docs; never infer it from this mission document alone.**
5. **Do not invent missing capabilities.** If something is unimplemented, partial, externally dependent or unmeasured, say so.
6. **Do not bypass canonical owners.** Integrate with existing control planes and fabrics.
7. **Do not weaken trading causality, qualification, risk or the paper-only boundary merely to make autonomy appear more complete.**
8. **Treat external repositories/modules as capabilities, not automatic authorities.**
9. **Prefer end-to-end completion over disconnected feature accumulation.**
10. **Keep changes harmonious with the entire system, not only the file currently being edited.**

### Source-of-truth precedence

If sources disagree, use this order:

1. current executable code, schemas and tests for actual behavior;
2. machine gates/verifiers for measured completion/readiness state;
3. the two canonical system references for architecture and ownership;
4. feature-local documentation where it does not conflict with canonical ownership;
5. this file for project mission, intent and prioritization.

A specific current task/issue/PR may intentionally change the architecture or mission. In that case, implement the requested change coherently and update affected documentation rather than preserving stale prose.

---

## 8. What LEVIATHAN should not become

Avoid drifting into any of these failure modes:

- a collection of impressive but disconnected AI demos;
- many agents that cannot share trustworthy knowledge or durable state;
- an LLM that directly controls trading without deterministic risk/qualification;
- a backtester marketed as autonomous intelligence;
- a UI that reports capabilities the backend has not proven;
- an integration warehouse where external tools each create their own authority;
- a system that “learns” only by accumulating text without execution evidence;
- a trading system that optimizes headline metrics such as win rate while ignoring costs, expectancy, drawdown, capacity, robustness and regime sensitivity;
- a platform whose broad feature set causes the primary autonomous-trading mission to lose direction.

---

## 9. Short version for a new session

If only one paragraph is retained, use this:

> **LEVIATHAN is a local-first autonomous AI platform whose primary mission is to become an institutional-grade autonomous trading research and paper-execution system. Its trading loop should autonomously ingest evidence, discover hypotheses and strategies, test them causally, reject weak candidates, qualify robust strategies, operate them in shadow/paper mode, manage risk, collect forward evidence and launch continual research. The broader cognition, Brain/Knowledge/Memory/Evidence, model, agent, worker, research, dataset, module and operator systems are first-class parts of LEVIATHAN because they provide the shared intelligence and infrastructure required for that mission and for other advanced workflows. Current code/tests and the two canonical system references remain implementation truth; this document defines mission and priority. Real-money autonomous trading is currently blocked by design.**

---

## 10. Maintenance rule

Update this file when the **mission, priority model or intended end state** materially changes.

Do **not** turn it into a duplicate architecture manual, changelog, gate report or exhaustive file map. Those responsibilities already have canonical owners.
