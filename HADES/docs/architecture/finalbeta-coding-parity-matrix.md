# FINALBETA Coding capability parity matrix

Living audit for the FINALBETA Coding takeover. Final state must be one of:

- `SHARED/CENTRALIZED AND EXPOSED`
- `IMPLEMENTED` (FINALBETA presentation over shared runtime)
- `NOT APPLICABLE — WITH EVIDENCE`

Target: Missing = 0, Unknown = 0, Unverified = 0.

Baseline SHA at audit: `5104fcd` (`origin/main`).

## API inventory (`lib/hades-api.ts`)

| Capability | API | Owner | FINALBETA | Final state |
|---|---|---|---|---|
| Health/meta | `health`, `settings`, `models` | shared runtime | Overzicht / inspector | SHARED |
| OmniRoute status | `buildOmnirouteStatus` | shared runtime | Agents / Instellingen / Overzicht | SHARED |
| Plan edits | `buildPlan` | shared runtime | Advanced / Nieuwe taak | SHARED |
| Structured run | `buildRun` | shared runtime | Nieuwe taak | SHARED |
| NL goal sync | `buildFromGoal` | shared runtime | Nieuwe taak | SHARED |
| NL goal async | `buildFromGoalAsync` | shared runtime | Nieuwe taak | SHARED |
| Chat-scoped job | `startConversationCodingJob` | Chat / CodingCard | Chat → Coding deep link | SHARED |
| List jobs | `buildJobsList` | shared runtime | Overzicht | SHARED |
| Job get/events | `buildJobGet`, `buildJobEvents` | shared runtime | Overzicht / Agents | SHARED |
| Job control | `buildJobCancel/Pause/Resume/Redirect` | shared runtime | Overzicht / Agents | SHARED |
| Control contract | `GET /build/jobs/control-contract` | backend | docs / optional Advanced | SHARED (read-only when exposed) |
| Job recover | `POST /build/jobs/recover` | backend | Advanced when interrupted | SHARED when client wired |
| Build get | `buildGet` | shared runtime | Wijzigingen | SHARED |
| Conflicts/preview | `buildConflicts`, `buildPreview` | shared runtime | Wijzigingen | SHARED |
| Apply/restore | `buildApply`, `buildRestore` | shared runtime | Wijzigingen | SHARED |
| Terminal | `terminalRun` | shared runtime | Build & testen | SHARED |
| Symbols | `searchSymbols`, `refreshSymbols` | shared runtime | Bestanden | SHARED |
| Definition/refs | `codeDefinition`, `codeReferences` | shared runtime | Bestanden | SHARED |
| Outline | `POST /code/outline` | backend | Bestanden (optional) | SHARED when client wired |
| Workspace tree/preview | `workspaceTree`, `workspacePreview` | shared runtime | Bestanden | SHARED |
| Open external | `workspaceOpenExternal` | shared runtime | Open in editor | SHARED |
| Git status/commit | `workspaceGitStatus`, `workspaceGitCommit` | shared runtime | Overzicht / Branches | SHARED |
| Debug | `debugDiagnose` | shared runtime | Build & testen | SHARED |
| Release | `releaseConfidence`, `releaseConfidenceSmoke` | shared runtime | Deploy | SHARED |
| Human rating | `gen2EvalHumanRating` | shared runtime | Overzicht / Agents | SHARED |
| Git branch create/switch | — | — | Branches disabled | NOT APPLICABLE — no `/workspace/git/branch*` |
| Pull requests | — | — | PR tab unavailable | NOT APPLICABLE — no GitHub PR API |
| Deploy promote/rollback | — | — | Deploy disabled | NOT APPLICABLE — only release confidence/smoke |
| Coding handoff | `consumeCodingHandoff` / `writeCodingHandoff` | chat-handoff | FINALBETA Coding mount | SHARED |
| Deep link | `?codingJob=` | hash/query | `#/fb/coding?codingJob=` | SHARED |

## Control Plane settings (Instellingen)

| Key | Final state |
|---|---|
| `coding.autonomy.profile` | SHARED when control values wired |
| `coding.omniroute.enabled_by_default` / `allow_fallback` / TTL | SHARED when control values wired |
| `coding.investigate.max_*` | SHARED when control values wired |
| `build.max_repair_attempts` / `build.test_timeout_seconds` | SHARED when control values wired |
| Fake `.hades/coding.json` file UI | NOT APPLICABLE — was mock only |

## Frontend surfaces

| Capability | Prior location | FINALBETA location | Final state |
|---|---|---|---|
| Full Coding Agent UX | `pages/coding-agent-page.tsx` | `finalbeta/pages/coding*` + shared runtime | IMPLEMENTED |
| Helpers | `coding-agent-helpers.ts` | `features/coding/coding-runtime-core.ts` | SHARED |
| Chat CodingCard Advanced | `#/coding-agent?codingJob=` | `#/fb/coding?codingJob=` (style-aware) | IMPLEMENTED |

## Counts (must stay zero-gap)

| Metric | Value |
|---|---|
| Discovered capabilities | see rows above |
| Missing | 0 |
| Unknown | 0 |
| Unverified | 0 (after live tests) |
