---
name: open-code-review
description: Open Code Review
---

# Open Code Review

Review local files the way a careful teammate would.

Always run `review_file` first (offline heuristics: secrets, eval, bare except, TODOs, long lines).
Use `review_with_model` only when a dynamic LM Studio model id is available.
Return line-level comments. Do not invent files. Do not claim the Alibaba Go harness ran unless it did.
