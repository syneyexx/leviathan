# Settings Control Plane

Canonical operator surface for **global** LEVIATHAN configuration.

## Ownership

| Concern | Owner |
|---|---|
| Global flags, concurrency, paths, security policy, RAG/cognition/MCP/coding defaults | **Settings Control Plane** (`Data/modules/settings/`) |
| Model providers, profiles, routing, per-model benchmarks | Models Control Plane |
| MCP server CRUD / tools / calls | MCP page + `McpBridge` |
| Training job hyperparameters | Training |
| Market strategies / portfolios | Trading pages |
| Cognition live runs / belief UI | Cognition page |

**No duplicate editable settings.** Domain objects stay on domain pages.

## Precedence

```text
hard safety invariants (Settings.validate + security refusals)
  > persisted operator override (SQLite settings_overrides)
  > environment / .env / hard default
```

`database_path` is **bootstrap-only** (environment-managed). It is never read from SQLite (avoids circular startup).

## Apply modes

| Mode | Behavior |
|---|---|
| `hot` | Persist + apply to live consumers immediately |
| `restart_required` | Persist desired value; effective stays until process restart (boot merge) |
| `bootstrap_only` | Visible, not editable via API |

UI shows **Active** vs **After restart** when they differ.

## Secrets

Secrets (`model.api_key`, `hf_token`, `web_search.api_key`) are never returned in plaintext by GET. Responses expose `configured: true/false` only. PATCH with empty value keeps the existing secret; `clear_secret` clears.

## API

- `GET /api/settings`
- `GET /api/settings/catalog`
- `GET /api/settings/categories/{category}`
- `PATCH /api/settings`
- `PATCH /api/settings/keys/{key}`
- `POST /api/settings/reset/{key}`
- `POST /api/settings/reset-category/{category}`

Dangerous settings require `confirm_dangerous=true`.

## Frontend

Single page: `/settings` (optional `?section=<category>`). Category navigation replaces only the content region — no separate Settings route pages. Legacy `/settings/*` paths redirect.

## Module layout

```text
Data/modules/settings/
  catalog.py      # declarative definitions
  store.py        # settings_overrides table
  validation.py   # types + feature hierarchy
  service.py      # control plane
  bindings.py     # hot-apply consumer binders
  types.py
```
