# Media Architecture

HADES Autonomous Media Intelligence is a native subsystem under `backend/media/`.

## Ownership

| Concern | Owner |
|---|---|
| Persistence | `media/store.py` (`media_schema_migrations`) |
| Orchestration | `media/orchestrator.py` (durable stages + leases) |
| HTTP API | `media/routes.py` → `/api/media/*` |
| UI | `components/hades/pages/media-page.tsx` (page id `media`) |
| Platforms | `media/platforms/*` adapters only |

## Flow

Trend evidence → ingest/transcribe → pattern analysis → opportunity → research claims → hypothesis → script/critics → storyboard → assets → edit plan → FFmpeg render → QA → platform variants → publish jobs → metrics → learning.

## Truth states

Capability and publish paths use explicit states (`READY`, `AUTH_REQUIRED`, `PRIVATE_ONLY`, `WAITING_PLATFORM_CONSENT`, …). Missing credentials never become success.

## Reuse

Voice/ASR, FFmpeg, secure secrets, event bus patterns, SQLite migration ledger style (Gen2), and HADES UI components — no parallel stacks.
