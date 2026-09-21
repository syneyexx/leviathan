# Reasoning changelog

## 2026-05-09 — Tool-loop cleanup and verification hardening

### Fixed
- Empty plugin shortlist no longer disables tool rounds (discovery stayed unreachable)
- Discovery now merges pages into the eligible tool set instead of replacing it
- `hades.discover_tools` uses `include_unscored=True` for broader recall
- Tool loop accepts `arguments` as alias for `input`
- Verification rejects tool success without `evidence_refs`
- Chat history dedup preserves message ids and compares stripped content
- TaskRunner no longer double-enqueues the same queued task between put and worker pickup
- Removed unused imports / dead local `_parse_tool_choice` / unused verification evidence buffer

### Changed
- Frontend chat response typing includes optional `request_spec` / `route`
- `.hades-cache/` ignored

### Verification
- `python3 -m unittest discover -s backend/tests` → 43/43 PASS
- `npm run typecheck` → PASS
- Live LM Studio / Windows / Docker: unconfirmed in this environment

## 2026-05-09 — Shared reasoning kernel integration

### Added
- `backend/reasoning/` shared orchestration kernel (contracts, understanding, profiles, context, tools, verification)
- Paged tool discovery beyond the first shortlist (`hades.discover_tools`)
- Deterministic verification success gate
- Reasoning unit tests (`backend/tests/test_reasoning.py`)
- Deterministic eval suite (`backend/evals/reasoning_eval.py`) + report artifact

### Changed
- Chat path preserves real message roles (no ROLE-label flattening)
- Adaptive reasoning uses multi-signal complexity, not mainly message length
- Work Runtime verification uses shared critic prompt/parser/gate
- Chat responses include compact `request_spec` / `route` metadata for observability

### Kept
- Existing Plugin Manager / Tool Runtime security model
- Existing Work Runtime persistence and task API contracts
- Local-first LM Studio path; no cloud fallback
- GUI style unchanged

### Verification
- `python -m unittest discover -s backend/tests` → 40/40 PASS
- `python -m backend.evals.reasoning_eval` → 6/6 PASS
- Live LM Studio / Windows / Docker: unconfirmed in this environment
