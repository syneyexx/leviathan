# HADES Reasoning Architecture

## Goal

Improve local orchestration quality (understanding, routing, context, tools, verification)
without claiming frontier-model equivalence and without reconstructing private chain-of-thought.

## Shared kernel

New package: `backend/reasoning/`

| Module | Responsibility |
|---|---|
| `contracts.py` | Typed RequestSpec, RouteDecision, ContextItem, Plan, Tool*, VerificationResult |
| `understanding.py` | Request classification + multi-signal adaptive scoring + route decision |
| `profiles.py` | Fast/Standard/High/Maximum budgets (plan/tools/verify/context/model calls) |
| `context.py` | Role-safe message assembly + protected context budgeting |
| `tools.py` | Paged discovery over full enabled registry + catalog rendering |
| `verification.py` | Structured critic prompt/parse + deterministic success gate |

## Runtime profiles

- **Fast:** minimal retrieval, ≤1 tool round, no mandatory plan/verify
- **Standard:** balanced tool/context budget
- **High:** plan + verification required, broader retrieval/tools
- **Maximum:** highest discovery/replan/verify budgets (not merely more tokens)
- **Adaptive:** chooses among the above using complexity signals beyond length

Profiles never disable hard permission/verification gates.

## Trust boundaries

- Retrieved memory/knowledge/tool output is **data**, not system authority.
- Approvals and `allow/ask/block` remain deterministic code paths.
- Model JSON cannot invent approvals or reserved runtime fields.
- Failed/blocked tool output cannot justify task completion.

## Integration points

- Chat: `send_message` builds RequestSpec/route, budgets context, preserves roles, runs tool loop.
- Work Runtime: `TaskRunner` keeps persistent steps/checkpoints and uses shared verification gate.
- Plugins: existing PluginManager + permission enforcement remain the execution authority.
Capability Intelligence (`backend/capability_intel/`) ranks and composes capabilities but cannot override policy.
One Brain (`backend/hades_brain/`) reuses that layer; MCPMarket is discovery-only.

## What was intentionally kept

- FastAPI + SQLite local-first design
- LM Studio OpenAI-compatible adapter
- Plugin Runtime v0.4.1 contracts
- Existing GUI style/layout
- No mandatory cloud dependency
- No hardcoded model IDs
