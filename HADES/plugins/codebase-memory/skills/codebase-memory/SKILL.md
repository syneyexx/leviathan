---
name: codebase-memory
description: Codebase Memory
---

# Codebase Memory

Use this plugin when HADES needs durable local recall of a repository.

1. `index` a project root (creates SQLite FTS + symbol names).
2. `query` for a symbol, filename, or phrase.
3. `outline` for a bounded file list.

Do not claim the upstream C MCP graph is running unless doctor/index evidence says so.
Windows paths are first-class. Skip `node_modules`, `.venv`, and other dependency trees.
