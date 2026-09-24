# Behavior settings

## Precedence

1. Persistent `behavior_profiles` row (canonical DB)
2. Canonical seed (`Data/modules/settings/seed.py`) when no row exists
3. **Never** invent identity in ContextBuilder / LLM / coding adapters

## Resolver

`BehaviorSettingsResolver.resolve(...)` returns an immutable `BehaviorSnapshot` for the turn:

- composed system prompt (identity + overlays + language instruction)
- settings hash / version
- language decision (`auto_follow_user` default)

Behavior changes apply on the **next** chat turn without restart. Behavior never grants ExecutionGateway / approval authority.

## Editable groups

Identity, language, core prompt/overlays, generation, Brain/retrieval, memory, context/history, background worker profile knobs.

API:

- `GET/PATCH /api/settings/behavior-profile`
- `PUT /api/settings/behavior-profile/system-prompt`
- `POST /api/settings/behavior-profile/reset` → resets to seed

UI: Settings → LLM Gedrag.
