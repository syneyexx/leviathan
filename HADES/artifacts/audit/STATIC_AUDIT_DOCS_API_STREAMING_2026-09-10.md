# HADES static audit — docs / API contracts / LM Studio streaming

**Date:** 2026-09-10  
**Mode:** Static-only (no tests executed)  
**Scope:** Documentation drift, API/frontend contracts, Obsidian vs Classic, LM Studio streaming wiring  
**Repo tip examined:** `origin/main` lineage at audit start (`9f94acf` and ancestors)

---

## Executive summary

| Area | Verdict |
|---|---|
| README `lint ≡ typecheck` | **Confirmed bug** — README stale; `package.json` / `TESTING_RELEASE_GATES.md` / `verify_hades.py` already correct |
| README “token streaming not implemented” | **Confirmed bug** — provisional token streaming is production-wired for text-only chat |
| `platform_services.py` ownership in codebase map | **Confirmed drift** — thin facade; bulk lives in `platform_services_core.py` |
| Gen2 status across roadmap / gap / CURRENT_STATUS | **Confirmed drift** — gap analysis frozen at 2026-09-08 pre-implementation narrative |
| Plugin counts | **Aligned** — 46 plugins + `_shared` |
| `TESTING_RELEASE_GATES.md` vs `verify_hades.py` | **Partial drift** — lint honesty OK; full-gate inventory incomplete |
| TaskStatus FE vs backend | **Confirmed contract bug** — backend writes `blocked`; FE union omits it |
| Pydantic `model_config` | **Fixed in routes** with alias mapper; not a live import crash |
| Obsidian vs Classic | **No Classic-only feature surface** — Obsidian wraps Classic pages; chrome/double-header UX only |
| LM Studio streaming stack | **Mixed** — text `stream_delta` production-wired; structured/`chat_stream_complete` helper-only |

---

## 1. Documentation drift vs code

### 1.1 README claims `npm run lint` ≡ `npm run typecheck` — CONFIRMED BUG

**Evidence**

- `/workspace/README.md` L63 (English):  
  `` `npm run lint` is **the same** as `npm run typecheck` (`tsc --noEmit`) — not a separate ESLint gate. ``
- `/workspace/README.md` L213 (Dutch):  
  `TypeScript typecheck (...; npm run lint is dezelfde check)`
- `/workspace/package.json` L17–18:  
  `"lint": "eslint . --max-warnings 0"` vs `"typecheck": "tsc --noEmit"`
- `/workspace/docs/TESTING_RELEASE_GATES.md` L42–44, L57–60: correctly states lint is real ESLint, not an alias
- `/workspace/verify_hades.py` L284–285: runs typecheck and lint as separate stages

**Conclusion:** Known README bug confirmed. Release-gate docs already remediated; README (EN+NL) still wrong.

**Related prepare drift:** `PREPARE_HADES.bat` runs `npm run typecheck` only (L47), never `npm run lint`. README still implies prepare’s typecheck story covers lint.

---

### 1.2 README streaming claims vs code — CONFIRMED BUG (opposite direction)

**README claim** (`README.md` L222):

> Token-by-token streaming is nog niet geïmplementeerd; de streaminginstelling blijft een runtimevoorkeur.

**Production wiring (confirmed)**

1. **LM client** — `backend/lm_studio.py`  
   - `chat_stream` → yields content deltas from SSE LM Studio chunks  
   - `chat_stream_events` → structured `content_delta` / `tool_call_delta` / `completed`  
   - `chat_stream_complete` → assemble final response from stream  

2. **Orchestration** — `backend/main.py`  
   - `_chat_with_optional_stream` (≈L1687–1763): when `streaming` **or** `stream_provisional_text` and `run_id` present, calls `client.chat_stream`, emits `run_event_bus` events type `stream_delta` with `provisional=True`  
   - Defaults (`backend/database.py`): `streaming: False`, `stream_provisional_text: True` → **streaming path on by default** via OR  
   - `run_model_with_optional_tool` (≈L1905–1918): streams only when `run_id` set **and** payload has **no** `tools` (tool rounds intentionally non-stream)

3. **Transport** — `GET /api/runs/{run_id}/events/stream` SSE (`main.py` `run_events_stream`) + poll fallback `runEvents`

4. **Frontend** — `lib/hades-api.ts` `openRunEventStream` / `runEvents`; `components/hades/features/chat/hooks/useChatRun.ts` joins `stream_delta`; `ChatTimeline` renders `.stream-provisional`; Models/Settings expose streaming toggles

**Accurate product statement:** Provisional token-by-token assistant text **is** implemented and production-wired for text-only chat completions with a run id. It is not “settings-only preference infrastructure.” Final answers remain non-provisional; voice explicitly refuses to speak `stream_delta` (`backend/voice/speakable.py`).

See §3 for helper-only vs production split.

---

### 1.3 `platform_services.py` vs `platform_services_core.py` — CONFIRMED DOC DRIFT

| File | Lines (approx) | Role |
|---|---:|---|
| `backend/platform_services_core.py` | ~3705 | KnowledgeService, WebResearchService, ResearchRunner, base PluginManager, ingest limits, harvest, etc. |
| `backend/platform_services.py` | ~344 | `from platform_services_core import *` + **PluginManager subclass** for observable dependency install |

**Stale map text** (`docs/HADES_CODEBASE_MAP.md` L26, L198): still describes `platform_services.py` as the “Large service module” / hotspot accumulation site. L131 partially corrects (“`platform_services.py` / `platform_services_core.py`”) but L26/L89/L97/L198 still steer agents to the thin facade as if it owned ResearchRunner.

**Gap analysis** (`ARCHITECTURE_GAP_ANALYSIS_GEN2.md` L124) correctly names `platform_services_core.py` as a hotspot.

---

### 1.4 Gen2 status drift — CONFIRMED

| Document | Dated / stance |
|---|---|
| `docs/HADES_GEN2_ROADMAP.md` | 2026-09-09 — “Implementation complete for scoped Gen2 deliverables”; systems `partial→verified` / MVP; host gates honest |
| `docs/CURRENT_STATUS.md` | Aligns: scoped closure, 161/161 monster ticks, **not** operational 100%; warns against collapsing axes |
| `docs/ARCHITECTURE_GAP_ANALYSIS_GEN2.md` | **2026-09-08** — “none of the ten systems is `full`. Nine are `partial`. Distributed … is `missing`.” Sections 2–3 still claim e.g. no Mission entity, Flight Recorder **in-memory only**, Finance “not fused”, no durable run_events |

**Concrete contradictions (gap doc vs later code/docs):**

- Gap L50 / L94–97: Flight Recorder in-memory only — **false now**: durable sink `main.py` `_durable_sink` → `gen2.store.append_run_event`; list/stream APIs fall back to durable rows after restart (L5341+)
- Gap L49 / L89–91: Finance “not fused” — roadmap/CURRENT_STATUS record fuse + thesis persist + event-study refuse-without-bars
- Gap L52: Distributed `missing` — roadmap: local/LAN MVP + multi-host deferred / `UNVERIFIED_ON_HOST`
- Gap L16 honest summary never updated after 2026-09-09 scoped completion

**Also:** `docs/architecture/gen2-implementation-matrix.md` is pinned to investigated commit `6896fc3` (Control Plane #34) — useful historical matrix, easy to misread as current status.

---

### 1.5 Plugin counts — ALIGNED

| Source | Count |
|---|---:|
| `plugins/*/` excluding `_shared` | **46** |
| `plugins/_shared/` | shared bridges (not a plugin package) |
| `artifacts/audit/PLUGIN_INVENTORY.json` / `.md` | **46** |
| `docs/CURRENT_STATUS.md` (~L315) | “46 plugins” |

No count drift found.

---

### 1.6 `TESTING_RELEASE_GATES.md` accuracy — PARTIAL

**Accurate**

- Canonical entry `python verify_hades.py`
- Lint ≠ typecheck (honest)
- `npm test` is frontend-only
- Host honesty vocabulary

**Incomplete / drifted vs `verify_hades.py`**

Full gate in code also runs (not in numbered L48–55 list):

- Native build + CTest (`_native_build_and_ctest`)
- Ruff security-boundary lint on selected backend modules
- Gen2 offline eval release gate (`evals.gen2_release_gate`)
- OpenAPI/TS `--check` (`tools/export_openapi.py`)

**Node test set drift**

| Suite | Included |
|---|---|
| `verify_hades.py` | source-contracts, ui-components, **ui-style-system**, **settings-unlimited-contracts**, voice-*, coding-agent-helpers, **brain-gateway**, use-hades-query |
| `package.json` `npm test` | subset — **missing** ui-style-system, settings-unlimited, brain-gateway |
| Gates doc “Fast focused checks” | even smaller subset |

**PREPARE vs gates:** `PREPARE_HADES.bat` does not invoke full `verify_hades.py` (no ESLint, no OpenAPI check, no ruff, no gen2 eval gate, truncated node tests).

---

## 2. API / frontend contract drift

### 2.1 Generated OpenAPI subset vs `hades-api.ts`

- `lib/generated/api-contracts.ts` is a **focused** subset (`tools/export_openapi.py` `FOCUS_SCHEMAS`: Brain*, Models*, ApiErrorBody, PageMeta, CodingJobsListResponse, HostCapabilityStatus, …)
- `lib/hades-api.ts` re-exports only some of those types (L3–11) and remains the **primary** hand-maintained client for most routes
- Not a bug by itself; drift risk is high outside FOCUS_SCHEMAS (Gen2/missions/plugins/trading mostly hand-typed)

Contract regression nets exist for Gen2 mission/eval/committee, AgentStatus, CodingJobStatus (`backend/tests/test_api_contract_drift.py`) — **TaskStatus is not covered**.

### 2.2 TaskStatus enum mismatch — CONFIRMED BUG

| Layer | Statuses |
|---|---|
| Backend `main.py` `update_task(..., status=...)` | `queued`, `running`, `completed`, `failed`, `cancelled`, **`blocked`** |
| FE `lib/hades-api.ts` `TaskStatus` | omits **`blocked`** |
| FE `tasks-page.tsx` `statusCopy` | keyed only on TaskStatus union → `statusCopy[task.status]` is `undefined` for blocked tasks |
| FE still handles `"blocked"` in some control toasts (L236) — inconsistent |

Work steps also use `blocked` / `ready` / `pending` in runtime; `WorkStep.status` is typed as a narrow union **plus** `| string`, which hides the mismatch.

### 2.3 AgentStatus / CodingJobStatus / Gen2MissionStatus

Static read + existing drift tests: **AgentStatus** labels in `agent_ops.STATUS_LABELS` match FE union (`idle|running|busy|error|disabled|unavailable`). **CodingJobStatus** mirrors `JobStatus` Literal. **Gen2MissionStatus** mirrors `MISSION_TRANSITIONS` keys (includes `blocked`). No confirmed enum bug beyond TaskStatus in this pass.

### 2.4 Pydantic reserved `model_config`

- **Fixed path:** `backend/gen2/routes.py` `HumanUsabilityRatingInput` uses `llm_model_config` + `model_validator` mapping wire key `model_config` (documented in CURRENT_STATUS 2026-09-09; tests in `test_gen2.py`)
- Remaining `model_config = ConfigDict(...)` on BaseModels is the **correct** Pydantic v2 pattern (`main.py`, etc.)
- `gen2/store.py` `model_config:` parameter on a **store method** is not a Pydantic field — not a reserved-name crash

No live reserved-name import bug found; historical bug is remediated.

### 2.5 Obsidian vs Classic — functionality

- Both shells register the same `PageId` set; Obsidian pages are `createObsidianPage(...)` wrappers around Classic page components (`components/hades/obsidian/pages/*`)
- Chat both use `ChatReasoningPage` → embeds `ChatPage`
- CSS: Obsidian page styles exist for all nav pages including `workflows.css` (imported in `styles/obsidian/index.css`); `tests/ui-style-system.test.mjs` required list **omits** `pages/workflows.css` (test inventory gap only)

**No confirmed Classic-only product capability** in this static pass. Residual: Obsidian adds an extra page chrome header on top of Classic titles (double heading UX), acknowledged in CURRENT_STATUS as restyle-not-clone.

---

## 3. LM Studio streaming — exact classification

| Symbol / path | Classification | Evidence |
|---|---|---|
| `LmStudioClient.chat_stream_events` | **Infrastructure / helper** | Only callers: `chat_stream`, `chat_stream_complete` inside `lm_studio.py` |
| `LmStudioClient.chat_stream_complete` | **Helper-only / unused** | No production callers outside `lm_studio.py` |
| `LmStudioClient.chat_stream` | **Production-wired** | `_chat_with_optional_stream` in `main.py` |
| `_chat_with_optional_stream` → `stream_delta` events | **Production-wired** | Emitted with `provisional=True` when settings allow |
| Tool-round LM calls | **Intentionally non-stream** | `run_model_with_optional_tool` skips stream when `payload.tools` present |
| `chat_stream_events` tool_call_delta / `StreamingToolCallAssembler` | **Infrastructure not used on chat tool path** | Assembler runs inside `chat_stream_events`, but production chat tool path uses non-stream `gateway_chat` |
| SSE `/api/runs/{id}/events/stream` + `useChatRun` | **Production-wired** | Chat progress UI |
| `ModelGateway.chat_stream` | **Docs-only / missing API** | Module docstring claims `chat` or `chat_stream`; class only implements `chat` — stream path acquires gateway **slot** manually instead |

**Net:** Token provisional streaming is a real production feature for text-only chat, not demoware. Structured stream assembly and `chat_stream_complete` are unused helpers. README claim that streaming is unimplemented is false.

---

## 4. Priority remediation list (docs/contracts; no code changes in this audit)

1. Fix README EN L63 + NL L213 lint≡typecheck; fix NL L222 streaming claim to match production provisional streaming  
2. Refresh or banner `ARCHITECTURE_GAP_ANALYSIS_GEN2.md` as historical 2026-09-08 snapshot; point status to roadmap/CURRENT_STATUS  
3. Update `HADES_CODEBASE_MAP.md` ownership: core vs facade for platform services  
4. Extend `TaskStatus` (+ tasks UI copy/counts) with `blocked`  
5. Expand `TESTING_RELEASE_GATES.md` full-gate list to match `verify_hades.py`; align `npm test` node file list or document the delta  
6. Clarify ModelGateway docstring (no `chat_stream` method)

---

## 5. Method notes

- Static reads/greps only; **no** `verify_hades`, unittest, or npm test runs  
- Route-set heuristics between FastAPI and `hades-api.ts` produce false positives (router prefixes / template literals); conclusions above rely on direct symbol tracing, not raw path-set diffs
