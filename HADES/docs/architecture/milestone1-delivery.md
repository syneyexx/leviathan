# Milestone 1 — plan & delivery notes

Base commit: `e0ab833b565eeb61beb0793b86e01b80622c47ad`

## Dependency order executed

1. **WP1** Reliable quality measurement (`evals/judges.py`, `quality_suite.py`)
2. **WP2** Interactive investigate strategy (`coding_investigate.py` → `CodingAgentService`)
3. **WP9** Background coding jobs (`coding_jobs.py` + `/build/goal/async` + job controls)

Preservation inventory: `docs/architecture/milestone1-preservation-inventory.json`

## What was added

| Area | Addition | Wired into |
|---|---|---|
| Judges | Strict verdicts `correct/incorrect/invalid/not_gradable`; negative fixtures; raw_output storage; dataset/judge versions | `run_live_quality_layer`, Eval Lab live_quality |
| Hard benchmark | Separate H01–H03 fixtures judged by tests/files/criteria | `run_hard_benchmark`, Eval Lab `suite=hard` |
| Investigate | Typed actions + observations; import expansion; budgets; repeat detection | `strategy=investigate\|auto` on `/build/goal` |
| Background jobs | Job id, persisted status/events, cancel/pause/resume/redirect, stale recovery | `/build/goal/async`, `/build/jobs/*` |
| UI | Strategy select + background checkbox + job controls | Coding Agent page (existing layout) |

## How to use

- **Fast path (unchanged default):** Coding Agent → goal → Start run (`strategy=fast`).
- **Investigate:** set strategy to `investigate` for multi-hop import bugs.
- **Background:** enable “Achtergrondjob”; poll/reconnect via job id; pause/cancel/redirect from the panel.
- **Eval:** Gen2 Eval Lab `quality` / `live_quality` / `hard`.

## Preserved

- All Q01–Q39 scenarios retained; Q40–Q42 additive.
- Sync `/build/goal` and `/build/run` contracts retained (sync path now uses `asyncio.to_thread`).
- Manual edits + repair_waves advanced path unchanged.
- No files deleted; no destructive migrations.

## Verification

- `python3 -m unittest tests.test_milestone1_quality_investigate_jobs` → PASS
- Broader suites run in this PR turn (see CURRENT_STATUS).

## Still open (later milestones)

- Full LSP servers (WP3), need-based context compiler (WP4), hypothesis/candidates (WP5–6), reviewer tests (WP7), browser evidence (WP8), learning loop (WP12), etc.
- Physical Windows + live LM Studio host evidence.
