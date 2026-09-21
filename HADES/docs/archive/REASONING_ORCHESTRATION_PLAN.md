# Reasoning orchestration improvement plan

> **HISTORICAL / COMPLETED remediation plan.** Defects A–G were addressed in the reasoning orchestration workstream. Keep as historical defect inventory. Active architecture planning: `docs/HADES_GEN2_ROADMAP.md`.

Reference baseline: `083a877` (analysis commit). Work from current `main` tip on branch `cursor/reasoning-orchestration-fix-725b`.

## Confirmed defects (pre-fix)

| ID | Symptom | Location |
|---|---|---|
| A | `route.target=work_runtime` + `require_verification` recorded, but chat only runs one model call | `send_message` |
| B | Critic `passed=true` + invented `evidence_refs` can complete Work | `verification_allows_success` |
| C | Latest user turn omitted when identical text exists earlier in history | `assemble_context_messages` |
| D | Fast `context_chars=24000` not applied to full model request | `send_message` / `chat_payload` |
| E | Oversized merged retrieval block dropped entirely | `retrieval_context` → one `ContextItem` |
| F | Exhausted tool rounds can return raw `hades_tool_call` JSON as final answer | `run_model_with_optional_tool` |
| G | `max_replans` / `max_model_calls` unused; chat uses `max(settings, profile)` for rounds | profiles + TaskRunner + chat |

## Milestones

1. Failing behavior regressions for A–G
2. Contracts + shared budget/verification enforcement
3. Context/message/retrieval fixes (C/D/E)
4. Tool-loop budget exhaustion + hard global caps (F/G)
5. Chat ↔ Work/verification integration (A) + evidence gates (B)
6. Bounded replan/recovery + evals + status docs
