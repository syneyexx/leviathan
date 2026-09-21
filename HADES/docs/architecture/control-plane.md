# HADES Control Plane

Policy-driven configuration for every HADES-owned behavioral constraint.

## Concepts

- **Registry** (`backend/control/definitions.py`) — typed setting definitions with metadata (category, risk, scopes, unlimited, apply mode).
- **Resolver** (`backend/control/resolver.py`) — single `resolve(setting_id, context)` with inheritance.
- **Unlimited** — JSON `null` / Python `None`. Never use fake sentinels like `999999`.
- **Effective value** — configured value after external capability clamps; clamps are always visible.
- **Immutable constraints** — security/platform invariants listed explicitly (not hidden).
- **Presets** — plain maps of normal settings (Safe / Balanced / Power User / Maximum Autonomy / Custom).

## Inheritance

```
system default
  → global user
  → project
  → agent type
  → agent
  → plugin
  → session
  → task
```

External provider/runtime capabilities are applied when computing **effective**, not by silently rewriting storage.

## How to add a setting

1. Add a definition in `build_core_definitions()` (`backend/control/definitions.py`).
2. Choose a stable `id` (`category.path.name`) and `storage_key` (snake_case for SQLite).
3. Set `default_value` to the **previous hardcoded behavior**.
4. Set `allow_unlimited=True` only where technically meaningful.
5. Replace the call-site literal with:

```python
from control.service import resolve_setting
limit = resolve_setting("tools.max_rounds", context)
if limit is not None and tool_calls >= limit:
    ...
```

Or read from `runtime_values()` using the `storage_key` for global-only paths.

6. Add/adjust a unit test in `backend/tests/test_control_plane.py`.
7. Document the migration row in `docs/architecture/configuration-limit-audit.md`.

## Unlimited

```python
validate_value(definition, None)  # → None when allow_unlimited
SharedBudgetPool.configure({"max_tool_calls": None})  # no ceiling
```

UI: toggle **Unlimited** in Settings → Advanced → Control Center.

## Effective values & capabilities

```python
service.capabilities.set_model_max_output_tokens(model_id, 32768)
effective = service.resolve("…")
# effective.clamped / clamp_reason / capability_max
```

## Plugins registering settings

Plugins should declare typed settings in their manifest for plugin-scoped overrides (`scope=plugin`, `scope_id=<plugin_id>`). Core does not need a code change for every plugin-local knob; use `ControlService.set_override(..., scope="plugin", scope_id=...)`.

## Agents consuming settings

Prefer:

```python
control_service.resolve("agents.execution.max_model_calls_per_task", ResolveContext(agent_id=..., task_id=...))
```

Do not manually walk five config sources.

## Hot reload

Each definition has `apply_mode`: `immediate`, `next_task`, `next_agent_restart`, `plugin_restart`, `hades_restart`. Control Center shows this badge. Avoid full process restart when `immediate` / `next_task` suffice.

## Events

`settings.changed`, `policy.changed`, `limit.hit` via `control.events.control_events`.

## API

| Method | Path |
|---|---|
| GET | `/api/control/dashboard` |
| GET | `/api/control/definitions` |
| GET | `/api/control/values` |
| GET | `/api/control/effective` |
| PATCH | `/api/control/settings` |
| PUT | `/api/control/override` |
| POST | `/api/control/override/delete` |
| GET | `/api/control/capabilities` |
| GET | `/api/control/immutable` |
| GET | `/api/control/history` |
| GET | `/api/control/presets` |
| POST | `/api/control/presets/apply` |
| POST | `/api/control/export` |
| POST | `/api/control/import` |
| GET | `/api/control/limits` |
| POST | `/api/control/limits/explain` |

Legacy `/api/settings` remains and routes through the control plane when initialized.

## Schema versioning

`config_schema_version` in `config_meta`. Bump `CONFIG_SCHEMA_VERSION` and add a migration in `ControlService._migrate_schema` when storage shape changes.
