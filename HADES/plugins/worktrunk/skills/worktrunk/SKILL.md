---
name: worktrunk
description: Worktrunk worktrees
---

# Worktrunk worktrees

Use git worktrees when HADES needs isolated checkouts for parallel coding jobs.

- `list` the worktrees of a repo.
- `add` a path, optionally creating a branch.
- `remove` only with explicit operator approval (autonomous disabled).

Prefer this over copying folders. Fail if git is missing. Do not force-remove unless asked.
