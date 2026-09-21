# Reviewer deep-dive

Code-referenced notes for serious technical review of HADES after frontier hardening.

## Orchestration ownership

`backend/run_lifecycle.py` defines surface owners. Work completion is gated by
`decide_work_task_completion` — Mission Control must not invent completion.

## Task state machine

Tasks persist through SQLite; Work steps/checkpoints live in `platform_db`.
Schedule occurrences now finish as `dispatched` when a run is only started
(`backend/main.py` TaskRunner.schedule_ticker) — not `completed`.

## Tool boundary

- Shared G11/G8: `policy_enforcement.enforce_tool_invocation_policies`
- Authoritative skip contract: `runtime.execution_gateway.may_skip_tool_policies`
- Chat/Work: `reasoning/tool_engine.py`
- Manual + autonomous plugins: `platform_services_core.PluginManager.invoke`

Architectural invariant tests: `tests/test_frontier_execution_invariants.py`.

## Isolation

`execution_isolation.run_isolated` — Linux userns+mount (+ optional net).
Windows Job Objects are process limits only — **not** full FS/network isolation.
Venv Python symlinks are resolved so secured mode works with `.venv` interpreters.

## Plugin trust

Trust ladder + Ready/enabled gates; dependency installs are explicit toolcalls.
Workflow adapters cannot select privileged install/system invocation types.

## Evidence verification

`artifacts.ArtifactService.verify_ready` requires exists, readable, checksum, status,
and **non_empty**. Acceptance checks in Mission Control require real artifact bytes.

## Crash recovery

`runtime.effect_ledger.EffectLedger` records prepared/committed/failed/unknown_outcome
and classifies restart as SAFE_TO_RETRY / REQUIRES_RECONCILIATION / ALREADY_COMMITTED /
UNKNOWN_EXTERNAL_STATE. Demo 05 exercises this. Exactly-once is **not** claimed.

## Evaluation

| Suite | Role |
|---|---|
| reasoning core (10) | deterministic reasoning |
| red_team_v1 (3) | software red-team |
| frontier_adversarial_v1 (109) | policy/path/artifact/approval/isolation |
| quality/agent holdout | broader / optional live |

Release gate: `python -m evals.gen2_release_gate`.

## Context Compiler

`gen2.context_compiler.shadow_compare` — offline lexical coverage proxy.
Default chat path remains opt-in until measured non-regression.

## Temporal graph / Flight Recorder

Still Gen2 partial spines — deepen next (see roadmap). Do not overclaim.

## Model routing

Empirical matrix lookup fails clean without data (`no_empirical_data`).
Smoke tests must not be treated as production intelligence.

## What I would improve next (≈3 more months of depth)

1. Wire remaining coding/build/voice/preview subprocess paths through the same isolation policy as plugins when secured.
2. Converge coding/build/voice/preview onto the same side-effect kernel + ledger.
3. Real Playwright E2E fixture suite (Flows A–H) without LM Studio.
4. Token-by-token streaming with provisional vs final message discipline.
5. Incremental megafile extraction (`main.py` / `platform_services_core.py`) behind characterization tests.
6. Temporal as-of queries + Flight Recorder REEXECUTE_SAFE with fixture tools.
7. Live LM Studio holdout quality reports on a prepared host (optional gate).

## AI assistance note

This packet was produced with Cursor Cloud Agent assistance. Claims are limited to
repository evidence. No fabricated benchmarks or company affiliations.
