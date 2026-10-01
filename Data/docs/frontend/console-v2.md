# Runtime & Tools / Console V2

## Purpose

Migrate `/console` onto the global Leviathan V2 shell while preserving the
canonical ObservabilityHub event authority, operator commands, and product-truth
service postures. Screen 1 (visual reference) controls layout; Screen 2 (legacy
Plugin & Runtime Console) controls capability inventory.

## Ownership

| Concern | Authority |
| --- | --- |
| Live + durable events | `Data/modules/observability/` (`ObservabilityHub` + `EventStore`) |
| SSE stream | `GET /api/events/stream` + `useLiveEvents` |
| History query | `GET /api/events` |
| Console aggregates | `GET /api/console/overview` → `EventStore.console_stats` + product-truth components |
| Operator commands | `GET/POST /api/console/commands|command` |
| Service posture | `product_truth.ComponentPosture` via `component_health_fn` |
| System telemetry (resources) | `SystemTelemetrySampler` (overflow / resources, not fake LIVE) |

No page-local Console database, telemetry daemon, or design system.

## Frontend composition

- Route: `/console` → `src/pages/ConsolePage.tsx` → `src/pages/console/ConsolePage.tsx`
- Hook: `src/pages/console/useConsoleWorkspace.ts`
- Components: `src/components/console/*`
- Styles: `.lv-v2-page--console` / `.lv-v2-console-*` in `leviathan-v2.css`
- Nav: MAIN_MENU / `v2Nav` Runtime & Tools → Console (canonical)

## Semantics

- **LIVE**: EventSource/`useLiveEvents` connection === `open` only.
- **Pause/Resume**: freezes visible advancement; buffer remains bounded; resume flushes chronologically.
- **Wissen**: clears client buffer/view only — durable EventStore history is kept.
- **Export**: filtered bounded fetch via `/api/events` (cap) + local buffer union; redacted payloads only.
- **Active services**: `operational` **and** `measured` — never green for registered/unmeasured.
- **Shares (Meest Actieve Componenten)**: `component_event_count / total_events_in_selected_period`.
- **UNKNOWN/UNMEASURED**: never rendered as healthy/zero when the store is absent.

## Capability remap (Screen 2 → Screen 1)

| Screen 2 | Location in V2 |
| --- | --- |
| System Logs / HTTP / Modules / MCP / Workflows tabs | Category select + Snelle filters |
| Errors tab | Severity chip + Errors quick filter |
| Clear / Export / Pause / Refresh | Console toolbar + AppShell refresh |
| Filter text | Search + regex (client, bounded) |
| Runtime Components | Actieve Services panel |
| Resources | Overflow → Resources dialog |
| Operator command + history + common chips | Overflow → Operator commands dialog |
| Event stream status | LIVE badge + stream truth |

## Visual

Reference: `Data/docs/ui_reference/console-v2-reference.png` (when present).
Fixture: `src/mocks/consoleV2VisualFixture.ts` (test-only).
Viewport: 1664×936.
