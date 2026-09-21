# Agent collaboration

Cross-plugin agents can participate in one HADES mission through a **structured, scoped** protocol. Multi-agent operation is not the default.

Default: the smallest capable team. Additional agents require a distinct specialty, independent verification, safe parallel analysis, or a narrow consultation.

## Message types

`task_assignment`, `task_handoff`, `finding`, `question`, `answer`, `proposal`, `critique`, `artifact_reference`, `evidence_reference`, `verification_request`, `verification_result`, `blocked`, `completed`

Sender identity is taken from **runtime metadata**, never from the payload’s claimed `sender`.

Messages are mission-scoped. Uncontrolled shared global state is not used.

Injection-shaped content is stored as `untrusted_injection_ignored` and does not become policy.

Prefer compact structured payloads over dialogue.

## Mission state

Durable fields: goal, requirements, plan, facts, decisions, open questions, assignments, artifacts, evidence, tool observations, verification, completed work, dead providers, mutation owner.

Handoffs send goal + task + recent findings + acceptance + refs — not full transcripts.

Targeted consultation sends a question + evidence only (`full_mission: false`).

## Budgets and loops

Defaults (`DEFAULT_BUDGETS`): max 3 agents, delegation depth 2, 24 messages, 2 critique cycles, 4 consultations.

Ping-pong on the same summary raises `deadlock`. Exceeding budgets raises `budget_exhausted`.

Cancel sets `cancelled`. Restart keeps completed work and clears in-flight chatter.

## Mutation ownership

Roles may include lead/planner/researcher/specialist/implementation_owner/reviewer/verifier.

At most one `implementation_owner` is assigned. Parallel inspection is allowed; writes are serialized through that owner. Existing execution leases remain the workspace mutation fence.

## Verification

`execution_success` ≠ `verified_task_success`.

Agent self-report and consensus are not proof. Tests/build/lint/schema/runtime evidence are.

If deterministic evidence already proves the acceptance criteria, no verifier-model call is made.
