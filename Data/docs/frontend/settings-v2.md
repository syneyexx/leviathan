# Settings / Systeem Instellingen

Canonical operator control surface for Leviathan configuration.

## Ownership

| Concern | Authority |
|---|---|
| Operator-adjustable settings catalog, persistence, apply modes | `Data/modules/settings/` Settings Control Plane |
| Behavior identity / system prompt | BehaviorProfile (`behavior_store`) — not authority |
| Model providers / health / credentials | Model Control Plane (`Data/modules/models/`) |
| Host CPU/RAM/GPU telemetry | `Data/modules/observability/system_telemetry.py` |
| Tools availability | MCP bridge + ExecutionGateway |
| Windows startup registration | `Data/modules/settings/startup_registration.py` |

There is **one** settings override table (`settings_overrides` on the Control DB). No `settings_v2.db`, no page-local provider registry, no page-local health stack.

## Persistence & apply semantics

Precedence:

```text
hard safety invariants
  > persisted operator overrides (when allowed)
  > environment / .env defaults
```

Each catalog entry declares `apply_mode`:

| Mode | Meaning |
|---|---|
| `hot` | Saved and applied to live consumers immediately |
| `subsystem_reload` | Saved; consumer reload required |
| `restart_required` | Saved as desired; effective after process restart |
| `bootstrap_only` | Not editable via UI |

UI save flow:

```text
edit draft → validate → PATCH /api/settings → persist → apply callbacks → reconcile snapshot
```

Success is reported from mutation results (`APPLIED`, `SAVED`, `RESTART_REQUIRED`, `FAILED`, …). The UI never claims success before the backend returns.

Reset uses `POST /api/settings/reset-category/{category}` (canonical defaults), with confirmation. Prefer category-scoped reset over global wipe.

## Algemeen (UI preferences)

Catalog keys under `ui.*` (path `Settings.ui` / `UiPreferencesSettings`):

| Key | Effect |
|---|---|
| `ui.app_display_name` | Document title / branding string (plain text, ≤120) |
| `ui.timezone` | IANA timezone for clocks (offset computed at display time) |
| `ui.locale` | `nl` \| `en` |
| `ui.theme` | `dark_leviathan` (V2 design system `data-theme`) |
| `ui.auto_refresh_seconds` | Live refresh interval; hidden tabs pause; no overlap |
| `ui.sound_notifications` | Toast audio cue |
| `ui.desktop_notifications` | Preference + Notification API permission state |
| `ui.start_with_system` | Desired OS autostart; measured via `/api/settings/startup-registration` |
| `ui.prefer_local_data` | Local-first preference (does not invent cloud disable) |
| `ui.optional_diagnostics_share` | Optional off-machine diagnostics gate; **local SystemTelemetry stays on** |
| `ui.crash_reports_enabled` | Local crash fingerprint retention; no external crash sink today |

## System configuration panel (curated)

These controls edit **existing** catalog keys (not duplicates):

| UI control | Catalog key | Consumer |
|---|---|---|
| Maximale GPU memory | `managed_serving.gpu_memory_limit_pct` | Model ResourceManager soft VRAM ceiling |
| Maximale context lengte | `context.token_budget` | ContextBuilder |
| Parallelle requests | `resources.max_model_concurrency` | Model ResourceManager |
| Request timeout | `model.timeout_seconds` | Provider / LLM client |

Requested vs effective: GPU % is converted to VRAM reserve when total VRAM is measured; otherwise requested is stored and effective headroom may differ until hardware is known. Context budget remains bounded by model window at inference time.

## Providers

Provider list/status/configure come from `/api/model-providers`. Secrets are write-only (`apiKeyConfigured` redacted). “Providers beheren” deep-links to `/models` ProviderManager — no second registry.

## KPIs

| Card | Source | Semantics |
|---|---|---|
| Systeem Status | `/api/health` via `normalizeSystemStatus` | Never maps UNKNOWN/DEGRADED to Operationeel |
| Beschikbare Modellen | Model Control Plane | available (lifecycle/health/loaded) / registered |
| Geheugen Gebruik | SystemTelemetry host RAM | Measured % + bytes; UNMEASURED when absent |
| Actieve Tools | `/api/mcp/tools` | availability=available vs registered |
| Gebruikers | Honest single-operator | No fabricated multi-user count |

Micro-bars use measured RAM history only; omitted when history is insufficient (no random heights).

## Frontend structure

- Route: `/settings` (+ `?section=` category)
- Shell: `AppShell variant="v2"`
- Hook: `useSettingsWorkspace`
- Components: `src/components/settings/*`
- Styles: `leviathan-v2.css` under `.lv-v2-page--settings` (no `settings-v2.css`)
- Reference: `Data/docs/ui_reference/settings-v2-reference.jpg`

## Security

- Secrets never returned to the browser
- Dangerous settings require `confirm_dangerous`
- Provider endpoints validated by existing Model Control Plane / network policy
- Startup registration uses argv-safe Windows Run key writes (`shell=False` equivalent — no shell concatenation)

## Categories not invented

Screenshot labels such as Gebruikers / Abonnement are **not** fabricated as product subsystems. Navigation lists catalog categories that exist. Users KPI truthfully reports the local operator posture.
