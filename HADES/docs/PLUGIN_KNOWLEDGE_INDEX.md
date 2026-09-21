# Plugin Knowledge Index

Offline lexical index for **safe plugin documentation** (manifest, README, skills, rules, declared `knowledge_paths`). No secrets, generated trees, or dependency folders are indexed.

## Storage

- SQLite tables on the platform DB: `plugin_knowledge_docs`, virtual `plugin_knowledge_fts` (FTS5).
- Incremental updates keyed by `(plugin_id, rel_path, content_hash)`.

## Lifecycle

- **Rebuild** on plugin convert/import (`PluginManager.import_local_folder`).
- **Remove** rows when a plugin is deleted.
- **Registry cache** invalidates on enable/trust/status/policy changes (`plugin_registry_cache`).

## Retrieval

- `plugin_knowledge_index.search_plugin_knowledge(db, query, plugin_id=...)`
- **Fast path**: read-only tools with `metadata.static_knowledge` / search-like actions and static `query` args can be answered from the index without spawning a plugin subprocess.

## Tool observations

Model-facing tool payloads use a **single** `tool_result_max_chars` budget across stdout/stderr/output/structured fields (`reasoning/tool_observation_budget.py`). Authority fields are stripped via `execution_truth`; failures keep `status`/`error` intact.

## Read-only tool cache

Deterministic, non-mutating invocations may hit `tool_result_cache` (short TTL, metadata `_tool_result_cache.hit`). Writes, network, service lifecycle, and failures are never cached.
