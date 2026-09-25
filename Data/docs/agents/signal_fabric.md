# LEVIATHAN Signal Fabric

Production coordination layer for agent communication. **Not** a second agent
runtime, job queue, knowledge database, or chat system.

## Purpose

Signals let agents, orchestrators, and system consumers coordinate:

- task handoffs and verification
- findings / evidence / challenges
- authority-gated BLOCK / CANCEL
- knowledge and memory *candidates* (never silent Brain writes)

## Core model (do not collapse)

| Concept | Role |
|---------|------|
| Missions | What must be accomplished (`AgentMission`) |
| Signals | How components communicate (`AgentSignal`) |
| Blackboard | Run-scoped shared working context (non-canonical) |
| Artifacts | Large outputs referenced by ID |
| Brain / Knowledge | Verified durable knowledge via existing pipeline |
| Memory | Durable contextual notes via `MemoryStore` when supported |
| Workers | Bounded execution (`agent_signals` pool) |
| Agents / Orchestrators | Existing fleet definitions |

## Lifecycle

```
CREATED → ROUTED → (per delivery) PENDING → CLAIMED → DELIVERED
                 → ACKNOWLEDGED (if requires_ack) → CONSUMED
Failure: RETRY_WAIT → … → DEAD_LETTER
Expiry: EXPIRED
```

Signal state and delivery state are separate. One signal may have many deliveries.

## Signal types

See `Data.modules.agents.signals.types.SignalType`. Notable:

- `TASK_REQUEST` / `TASK_HANDOFF` → create/link `AgentMission`
- `VERIFY_REQUEST` / `VERIFIED` / `REJECTED` / `CHALLENGE` → evaluation workflow
- `BLOCK` / `UNBLOCK` / `CANCEL` → policy + fleet controls (not raw mutation)
- `KNOWLEDGE_CANDIDATE` → existing `knowledge.commit` path only when verified
- `MEMORY_CANDIDATE` → honest `STORED` / `PENDING` / `UNSUPPORTED`
- `HEARTBEAT` / `PROGRESS` → coalesceable telemetry (never Blackboard)

## Routing

`SignalRouter` supports: DIRECT, ROLE, CAPABILITY, ORCHESTRATOR, MISSION, SYSTEM.

Capability selection is deterministic: eligible → healthy → enabled → exact
capability → capacity → stable `agent_id` tie-break. No LLM for routing.

## Authority

`SignalAuthorizationPolicy` gates emit rights by kind/role/capabilities.
HTTP `senderId` never grants agent authority. Control signals require
risk/evaluation/orchestrator capability. Workers cannot mesh-message workers.

Side effects still go through `ExecutionGateway` / `AgentFleetService` /
knowledge workers — signals coordinate intent only.

## Blackboard

Selected types project onto `AgentBlackboard` with `metadata.signal_projection`
and provenance `signal_id`. Telemetry does not project. Blackboard remains
non-canonical.

## Workers

Pool `agent_signals` owns:

- `agent_signal.deliver`
- `agent_signal.retry`
- `agent_signal.housekeeping`

Entrypoint: `Data.modules.workers.entrypoints.agent_signals`.

## Feature flag

`LEVIATHAN_FEATURE_SIGNAL_FABRIC` (default on) AND agents enabled for mission
side-effects. When disabled, fleet continues; UI shows disabled honestly.

## API

| Method | Path |
|--------|------|
| GET | `/api/agents/signals` |
| GET | `/api/agents/signals/{id}` |
| GET | `/api/agents/signals/{id}/deliveries` |
| GET | `/api/agents/signals/{id}/chain` |
| POST | `/api/agents/signals` |
| POST | `/api/agents/signals/{id}/ack` |
| GET | `/api/agents/signals/metrics` |
| GET | `/api/agents/signals/graph` |
| GET | `/api/agents/signals/dead-letters` |
| POST | `/api/agents/signals/dead-letters/{id}/retry` |
| GET | `/api/agents/{id}/signals` |
| GET | `/api/agents/missions/{id}/signals` |

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Empty Signals panel | Feature flags; `agent_signals` worker; migration v50 |
| Dead letters growing | Inspect `last_error`; manual retry; recipient health |
| Budget exceeded | Mission `metadata.maxSignals`; hop counts |
| Duplicate missions | Idempotency key / `signalFabricKey` on child missions |
| Knowledge not promoted | Candidate must be `verificationState=verified`; commit lane |

## Guarantees

- Durable SQLite persistence (no Redis/Kafka required)
- Concurrency-safe delivery claims
- Bounded retries + dead letter
- Idempotent publish and task handoff
- Bounded hops / mission signal budget
- Payload size limit (use artifact refs)
