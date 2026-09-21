# Lifecycle ownership (A12)

HADES keeps **one clear owner** per status/lifecycle surface so Mission Control,
Workflows, and Work Runtime do not independently invent completion.

| Surface | Owner | May invent Work `completed`? |
|---|---|---|
| Work Runtime (`TaskRunner`) | Core SQLite task rows + verified checkpoint | Yes, after `decide_work_task_completion` |
| Mission Control | `sync_mission_from_task` mirror + acceptance evidence | No — mirrors Work; may downgrade |
| Workflows | Workflow run rows only | No |
| Coding jobs | `coding_job_control.CONTROL_OWNER` | N/A (separate job store) |
| Artifacts | `ArtifactService.verify_ready` | N/A |
| Policy | `policy_enforcement` | N/A |
| Models | `ModelGateway` | N/A |

Source of truth: `backend/run_lifecycle.py`. HTTP introspection: `GET /api/lifecycle/owners`.

## Completion rule

Work tasks become `completed` only when:

1. Checkpoint phase is `verified` (or an equivalent explicit pass), and
2. No failed/pending steps remain in the Work step table, and
3. The task is not cancelled.

Mission Control re-evaluates executable acceptance when syncing and can mark the
mission `failed` even if Work claimed success with weak evidence.

Conversation working state (`open_work`) is a **projection/mirror** only.
Chat turn `status=completed` and `work_runtime_called` must **not** invent Work
completion or remove a linked task from `open_work`. Linked Work truth comes from
`database.get_task` + verified checkpoint via `decide_work_task_completion`
(`reasoning/linked_work_truth.py`).

## Approvals

Client-provided `approved_by_user` / `preapproved` booleans are **not**
authorization authority. Privileged MCP and Gen2 product actions require a
validated persisted `ApprovalService` decision (`approval_id`) with exact scope.

## Persistence

SQLite remains the store. This extraction is typed contracts + helpers — not a
new orchestration engine or database.

## Lint / typecheck

`npm run lint` is a real ESLint gate (`eslint . --max-warnings 0`); `npm run typecheck` is `tsc --noEmit`. See `docs/TESTING_RELEASE_GATES.md`.
