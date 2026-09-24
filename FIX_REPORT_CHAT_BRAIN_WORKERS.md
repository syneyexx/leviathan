# FIX_REPORT — Chat / Brain / Workers

## Executive answers

1. **Why Dutch prompts answered in English?**  
   No language policy existed; English-only system/identity text dominated the prompt. Fixed via `auto_follow_user` in `BehaviorSettingsResolver` + language instruction on the snapshot.

2. **Where did identity/system prompt come from before?**  
   `DEFAULT_BEHAVIOR_PROFILE.system_prompt` plus duplicate hardcoded fallbacks in `ContextBuilder`, coding loop, cognition context.

3. **Where does it come from now?**  
   Canonical seed `Data/modules/settings/seed.py` → persisted `BehaviorProfileStore` → immutable `BehaviorSnapshot.system_prompt` per turn.

4. **Was medical text found in Brain (repo)?**  
   Forensic anchors were **not** present in the Git worktree. Operator Brain data lives outside Git; runtime retrieval of medical chunks remains possible and is gated.

5. **If yes: provenance?**  
   N/A in-repo. When present at runtime: dataset → document → chunk → retrieval hit → (now) untrusted `reference_context` on user turn.

6. **Why did the identity question activate retrieval?**  
   `use_knowledge = has_knowledge and (intent != "conversation" or word_count >= 8)` — “wat is jou naam, en hoe gaat het” hit the word-count branch.

7. **Why did `[tier2]` content repeat?**  
   Cumulative `message.content` snapshots were treated as deltas and appended (backend + frontend).

8. **Repetition classification**  
   Primary: **B** (cumulative snapshots appended as deltas). Possible **D** if contaminated history also poisoned later turns.

9. **Chat-template / EOS issues?**  
   Incomplete termination metadata on non-stream path; no provider-aware stop contract. Now: `finish_reason` / `termination_source` on completions; configured stops only when set.

10. **Heavy ops externalized?**  
    Existing JobRuntime + WorkerSupervisor pools; new `run_leviathan_workers.bat`; API externalize flags remain; optional autostart via `LEVIATHAN_WORKERS_AUTOSTART=1`.

11. **What stays synchronous?**  
    Validation, authority checks, behavior snapshot, intent/gate, fast index search, context compile, model stream + normalize, persistence.

12. **Tests proving repairs**  
    `Data/backend/tests/test_chat_brain_boundary.py` (+ foundation/one_brain); frontend `chatStream.boundary.test.ts`.

---

## Root-cause table

| Symptom | Evidence | Cause | Files | Regression |
|---------|----------|-------|-------|------------|
| Dutch→English | No language field; EN system text | Missing language policy | `resolver.py`, `behavior.py`, chat route | `test_language_follows_latest_user_message` |
| Hardcoded identity | builder/coding fallbacks | Duplicate runtime authority | `seed.py`, builder, coding, cognition | `test_identity_settings_are_runtime_resolved` |
| Greeting retrieved Brain | `word_count >= 8` | Heuristic gate bug | `retrieval_policy.py`, `engine.py` | `test_identity_question_does_not_retrieve` |
| Medical in answers | knowledge in system role | Authority boundary bug | `builder.py`, `reference.py` | `test_knowledge_not_serialized_as_system_authority` |
| APPEL / tier2 repeat | snapshot=delta append | Stream semantics bug | `streaming.py`, openai_compatible, SSE, frontend | `test_stream_cumulative_snapshot_frames`, `test_duplicate_snapshot_suppression` |
| Heavy work in API | inline runners when not externalized | Control-plane pollution | workers bat, bootstrap flags | `test_worker_job_survives_restart` |

### Repetition origin table

| Layer | Repetition already present? | Evidence |
|-------|----------------------------|----------|
| Brain chunk | possible at operator site | anchors not in Git |
| compiled context | no (after fix) | reference block, not system |
| raw provider completion | possible cumulative snapshots | non-standard `message.content` |
| normalized backend stream | **was yes / fixed** | StreamNormalizer suffix/dup suppress |
| backend SSE | was yes via append | typed frames + sequence |
| frontend state | was yes via onToken append | snapshot replace + seq dedupe |
| persisted assistant | yes if stream corrupted | final text = normalized join |

---

## Executed commands (truthful)

```text
PYTHONPATH=/workspace python3 -m unittest \
  Data.backend.tests.test_chat_brain_boundary \
  Data.backend.tests.test_foundation \
  Data.backend.tests.test_one_brain -v
→ Ran 39 tests — OK

cd Data/frontend && npm test -- --run src/api/chatStream.boundary.test.ts
→ 4 tests passed

cd Data/frontend && npm run typecheck
→ exit 0

cd Data/frontend && npm run lint
→ exit 0 (pre-existing warnings only; no new errors)

cd Data/frontend && npm run build
→ exit 0 (built successfully)
```

Smoke (live backend required; not executed in this cloud VM without an LLM):
`scripts/chat_boundary_smoke.ps1 -Iterations 100`

---

## Key deliverables

- Settings sole behavior authority + Settings UI expansion + `PATCH /api/settings/behavior-profile`
- Retrieval intent classification (no word-count gate)
- Brain data out of system role; marker-safe references
- StreamFrame normalization + SSE contract + frontend fixes
- `run_leviathan_workers.bat` + docs + atomic index generation registry
- Migration 39 `behavior_settings_json`
