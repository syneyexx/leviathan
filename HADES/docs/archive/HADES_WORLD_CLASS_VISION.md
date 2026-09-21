# HADES World-Class Vision

> **HISTORICAL / COMPLETED (Gen1 baseline).** The 50 world-class capabilities in this document are fully implemented and merged. They are **baseline product behavior**, not an active roadmap. Active planning lives in `docs/HADES_GEN2_ROADMAP.md` and `docs/ARCHITECTURE_GAP_ANALYSIS_GEN2.md`. Do not treat open rows or the old “Implementation order” section as backlog.

Professional product roadmap for elevating HADES as an **offline-first local AI workspace**.
HADES is not a cloud clone of Cursor, ChatGPT, or Claude. It is a sovereign system that owns
memory, tools, agents, evidence, and verification on the user’s machine.

**Status legend**

| Mark | Meaning |
|---|---|
| `shipped` | Verified in this branch with tests and/or typecheck |
| `partial` | Foundation present; expand iteratively |
| `planned` | Specified here; not yet fully wired |

---

## Product thesis

| Product | Wins on |
|---|---|
| Cursor | Deep IDE integration |
| ChatGPT / Claude | Frontier models + cloud scale |
| **HADES** | User-owned runtime: durable agents, provenance-backed knowledge, permissioned plugins, honest verification, full offline usefulness |

Core non-negotiables (see `docs/DECISIONS.md`):

1. Offline-first core
2. Dynamic LM Studio model selection (no hardcoded production model)
3. Deterministic **safety** boundaries (permissions, filesystem, subprocess) — not moral content filters
4. No fake success
5. Windows first-class
6. Content/moral policy lives in the **user system prompt** and the local model — never hardcoded refusal lists in HADES core

---

## The 50 capabilities

### A. Product identity

| # | Capability | Intent | Status |
|---|---|---|---|
| 1 | Local AI OS shell | Chat is one app inside a workspace OS (agents, memory, knowledge, plugins). | `shipped` (sidebar Apps/Kennis/Systeem + Ctrl+K hub) |
| 2 | Honest completion brand | Every “done” maps to evidence, tool result, artifact, or explicit incomplete state. | `shipped` (incomplete/unverified banners in Chat + Tasks) |
| 3 | Offline primary / online boost | Network optional enrichment; never required for boot or basic chat. | `shipped` |
| 4 | User-owned data plane | Memory / Knowledge / Evidence remain distinct and exportable. | `shipped` |

### B. Chat experience

| # | Capability | Intent | Status |
|---|---|---|---|
| 5 | Streaming + live tool timeline | Token stream and tool/verify phases visible. | `shipped` (SSE `/api/runs/{id}/events/stream` + poll fallback; provisional deltas; tool timeline/cards) |
| 6 | Inline diffs / patch review | Proposed file edits as reviewable patches. | `shipped` (Coding Agent patch-review panel + formatted conflicts; Apply/Restore) |
| 7 | @-mentions | `@file` `@memory` `@agent` `@plugin` `@research` with budgeted context. | `shipped` (autocomplete + retrieval) |
| 8 | Slash commands | `/help` `/harvest` `/download` `/remember` `/plan` `/verify`. | `shipped` |
| 9 | Multi-branch conversations | Compare forks; keep best path. | `shipped` (create, activate, compare last assistant reply per branch) |
| 10 | Canvas / scratchpad | Long-form artifact beside short chat. | `shipped` (Canvas panel + canvas.md save + Open in canvas on long replies) |
| 11 | Voice-to-task | Local STT plugin → structured task. | `shipped` (paste/local STT; no built-in ASR — Tasks UI + `/voice` + `local-stt-paste` + `POST /api/voice/to-task` create/start; VoiceStudio optional external ASR) |
| 12 | Composer multi-file mode | One prompt → plan → apply with approvals. | `shipped` (Coding Agent Plan → review/approve → Start run; Apply/Restore via safe pipeline; structured edits + repair_waves — not freeform NL→patches without model) |

### C. Reasoning quality

| # | Capability | Intent | Status |
|---|---|---|---|
| 13 | Adaptive depth users feel | Fast/Standard/High/Maximum change plan/tools/verify. | `shipped` (chat depth control + settings profile) |
| 14 | Independent critic pass | Writer ≠ critic; fail blocks completion. | `shipped` (verification fail → `partial` + critic banner/Status notes) |
| 15 | Acceptance criteria first | Criteria before execution; checklist match required. | `shipped` (criteria_checklist match required; Chat/Tasks checklist UI) |
| 16 | Bounded self-correction | Diagnose → replan → retry with caps + logs. | `shipped` (budgeted replans + Tasks/Chat self-correction logs) |
| 17 | Difficulty router | Cheap path for simple asks; specialists for hard ones. | `shipped` (adaptive route + complexity/path/rationale in Chat Status) |
| 18 | Specialist contracts | Researcher, Builder, Critic, Archivist with typed I/O. | `shipped` (`/api/specialists` + Agents contracts panel) |
| 19 | Conversation working memory | Durable correctable working_state. | `shipped` (persisted + Status rail) |
| 20 | Evidence-first answers | Claims cite Knowledge/Evidence/artifacts or say uncertain. | `shipped` (Chat Bronnen/provenance op berichten + Status rail; backend retrieval sources) |
| 21 | Non-dumping local RAG | Hybrid retrieve + rerank + provenance labels. | `shipped` (hybrid + non-dumping pack budget + provenance labels + workspace hits) |
| 22 | Local model ensemble | Router across LM Studio models (fast/deep/code). | `shipped` (Models-pagina Lokale modelrouter + Settings fallback_order/role overrides) |

### D. Agents & Work Runtime

| # | Capability | Intent | Status |
|---|---|---|---|
| 23 | Durable agent runs | Resume from checkpoints after restart. | `shipped` (`POST /api/tasks/{id}/resume-checkpoint` + Tasks UI; completed steps kept) |
| 24 | Human-in-the-loop inbox | Approvals with argument fingerprints; block ≠ approve. | `shipped` |
| 25 | Agent playground | Deterministic A–E scenarios inspectable in UI. | `shipped` |
| 26 | Team orchestration board | Parallel/dependent waves visible. | `shipped` |
| 27 | Scheduled background agents | once/daily/weekly with catch-up/overlap skip. | `shipped` |
| 28 | Scoped agent memory | session/project/global + forget/supersession. | `shipped` (Memory scope UI + session-scoped retrieval + forget/supersede) |
| 29 | Hard budgets | Tokens/time/tools capped; overflow pauses. | `shipped` (enforced + chat Status budget) |
| 30 | Mid-run cancel/redirect | User can steer live runs. | `shipped` (Tasks cancel/pause/resume/redirect) |

### E. Local coding power

| # | Capability | Intent | Status |
|---|---|---|---|
| 31 | Workspace indexer | Tree/symbols/embeddings for `@codebase`. | `shipped` (symbols + refresh/cache/tree UI + `@codebase`; embeddings optional/not required — API reports `embeddings: false`) |
| 32 | Build Agent v2 loop | test → fail → fix → retest. | `shipped` (`loop_timeline` + usable `repair_waves` + what_broke; no fake retry without a fix wave; no autonomous LLM fixer) |
| 33 | Safe apply pipeline | worktree → preview → approve → apply → restore. | `shipped` (conflicts/apply/restore API+UI) |
| 34 | Policy terminal tool | Allowlisted commands, cwd jail, transcript artifact. | `shipped` |
| 35 | LSP-light | go-to-def / find-refs via language-server plugin. | `shipped` (Files + Coding Agent regex LSP-light UI + cache) |
| 36 | Debug agent | logs + failing test → minimal verified fix. | `shipped` (diagnose → what_broke + review stubs → composer; never auto-apply; verified fix still via Build Agent tests) |

### F. Knowledge / Research / Memory

| # | Capability | Intent | Status |
|---|---|---|---|
| 37 | Promote-to-memory | Chat claim → proposal → review → durable fact (`/remember`). | `shipped` |
| 38 | Project knowledge packs | Per-project files + decisions + evidence + agents. | `shipped` (export + import stubs; memories/agents/evidence inventory; Memory pack UX) |
| 39 | Honest research mastery | Coverage gaps visible; no fake “expert”. | `shipped` (Research UI dekkingshiaten + `GET /api/research/{id}/coverage`) |
| 40 | Cross-conversation Brain | Live graph of memories, knowledge, chats, tasks, manual nodes. | `shipped` |
| 41 | Forget that works | Including derived indexes; audit retained. | `shipped` |
| 42 | Import pipelines | PDF/DOCX/EPUB/MD/CSV/code → chunked citable Knowledge. | `shipped` |
| 42b | **Site document harvest** | “Download every ebook linked on this site” → crawl, store, ingest Knowledge. | `shipped` |

### G. Plugins / MCP / tools

| # | Capability | Intent | Status |
|---|---|---|---|
| 43 | First-class MCP catalog | Remote tools as HADES tool rows with permissions/health. | `shipped` (Plugins MCP-catalogus + permissions/ready) |
| 44 | Local plugin marketplace | `.HadesPlugin` install, deps, health proof. | `shipped` (Plugins Marketplace-tab + `/api/plugins/marketplace`) |
| 45 | Policy profiles | Paranoid / Normal / Lab presets. | `shipped` (Settings → Beveiliging) |
| 46 | Structured tool result cards | Tables/diffs/logs instead of raw JSON. | `shipped` (API + chat Status cards met table/diff) |

### H. Product reliability & UX

| # | Capability | Intent | Status |
|---|---|---|---|
| 47 | 3-minute onboarding | Detect LM Studio → pick model → first win. | `shipped` |
| 48 | Honest health dashboard | LM Studio, DB, plugins, schedules, disk — red means red. | `shipped` |
| 49 | Global command palette OS | Ctrl+K as hub for search + actions (+ harvest shortcuts). | `shipped` (empty Ctrl+K OS-acties + marketplace/MCP/voice/harvest) |
| 50 | Release confidence loop | VERIFY gates + visible “what broke”. | `shipped` (local inventory + what_broke + VERIFY stages as `manual`; smoke optional; full Windows `VERIFY_HADES.bat` remains operator-run) |

---

## How site harvest works (user example)

User says in Chat (with network policy `allow`):

> Download elke ebook die gelinkt staat met deze website https://www.freebookcentre.net/

HADES:

1. Detects harvest intent **before** the LLM (`backend/chat_commands.py`)
2. Same-origin HTML crawl + document-link discovery (PDF/EPUB/DOCX + ebook hints)
3. One-hop follow for HTML download wrappers
4. Downloads with size/magic-byte validation
5. Ingests into Knowledge Library with `source_url`, checksum, `authorized_download`
6. Surfaces documents in Files/Knowledge and as Brain knowledge nodes
7. Reports successes **and** failures honestly (no fake completion)

Also available as:

- `/harvest <url> max_documents=40`
- `POST /api/knowledge/harvest` with `authorized_downloads=true`
- Research page → **Harvest site**

User-authorized harvest skips robots.txt (operator-directed fetch). Autonomous default crawl still respects robots.

---

## Brain page (live)

The Brain UI loads `/api/brain` (no mock graph). Users can:

- Search / filter / focus
- Create, edit, delete handmatige nodes
- Persist drag positions
- Create relations
- Open overlay entities (`#/memory`, `#/chat`, `#/tasks`, `#/files`)
- Refresh live overlays from Memory, Knowledge, conversations, tasks/steps

Core architecture nodes remain protected.

---

## Implementation order (continuing)

1. ~~Site document harvest~~ `shipped`
2. ~~Brain 100% live~~ `shipped`
3. ~~Slash + natural harvest / remember / plan / verify~~ `shipped`
4. @-mentions + richer command palette
5. Streaming foundation / tool timeline UX
6. Policy presets
7. Remaining coding/agent/IDE parity items iteratively with tests

Never claim a capability `shipped` without verification.
