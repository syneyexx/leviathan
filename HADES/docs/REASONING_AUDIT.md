# HADES Reasoning Audit

**Date:** 2026-05-09  
**Scope:** Chat orchestration, Work Runtime, tool loop, context, verification  
**Baseline:** v0.4.1 Plugin Runtime + existing 34 backend tests (all green before changes)

## Call graph (simplified)

```text
UI (chat/tasks)
  -> FastAPI routes in backend/main.py
      -> resolve_model / LM Studio adapter
      -> retrieval_context (memory + knowledge)
      -> run_model_with_optional_tool  OR  TaskRunner._execute_work
          -> build_chat_tool_shortlist (first-party Tool Kernel only)
          -> hades.capabilities.search|inspect|invoke (Capability Broker)
          -> PluginManager.invoke / MCP host (real executors)
          -> verification gate (Work Runtime)
      -> SQLite persistence (database.py / platform_db.py)
```

Architecture: `docs/architecture/HADES_TOOL_KERNEL_AND_CAPABILITY_BROKER.md`.
Plugin/MCP schemas are **not** injected into the Chat model tool payload.
## Proven bugs / defects fixed

1. **Role flattening in chat** (`send_message`)  
   Conversation history was concatenated into one user string with `ROLE:` labels.  
   **Fix:** `assemble_context_messages` preserves real `system`/`user`/`assistant` roles.

2. **Adaptive profile ≈ length + keywords** (`effective_reasoning`)  
   Adaptive scoring was dominated by length/keyword heuristics.  
   **Fix:** multi-signal `score_complexity` + profile budgets in `reasoning/`.

3. **Tool shortlist ceiling**  
   Architecture effectively stopped at the first lexical shortlist.  
   **Fix:** paged `discover_tools` + built-in `hades.discover_tools` meta-tool path.

4. **Verification not evidence-gated enough**  
   Critic JSON was trusted without a deterministic success gate.  
   **Fix:** `verification_allows_success` rejects missing/incomplete/empty finals and unrelated tool success.

## Architecture risks (still present / partial)

- Orchestration still primarily lives in `backend/main.py` (now thinner via `backend/reasoning/`).
- No OS sandbox; plugin permissions remain application-level.
- Live LM Studio / Windows / Docker behavior is environment-dependent.
- Context budgeting is character-based (conservative estimate), not a real tokenizer.
- Semantic tool choice remains JSON-protocol based (validated, not free-form execution).

## Unconfirmed

- End-to-end quality on a specific local model in LM Studio.
- Windows process-tree cancellation under heavy plugin fan-out.
- Docker Desktop integration paths.

## Baseline measurements (deterministic)

- Backend unittest suite before change: **34/34 PASS**
- After change: **40/40 PASS** (6 new reasoning tests)
- Deterministic reasoning eval: **6/6 PASS** (`docs/REASONING_EVAL_REPORT.json`)
- Live model eval: **unconfirmed**
