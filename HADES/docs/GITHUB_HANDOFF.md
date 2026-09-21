# GitHub handoff for HADES

Use GitHub as the source of truth between Cursor, Astra and other coding agents.

## First push

Create a **private** empty GitHub repository, then from the HADES root:

```bat
git init
git add .
git commit -m "HADES v0.4.1 Cursor-ready baseline"
git branch -M main
git remote add origin YOUR_PRIVATE_REPO_URL
git push -u origin main
```

Create a baseline tag after the push:

```bat
git tag v0.4.1-plugin-runtime-baseline
git push origin v0.4.1-plugin-runtime-baseline
```

## Development branches

Do substantial work outside `main`:

```bat
git checkout -b feature/reasoning-v2
```

or:

```bat
git checkout -b feature/plugin-runtime-v2
```

After verified progress:

```bat
git add .
git commit -m "Describe verified subsystem change"
git push -u origin HEAD
```

## Switching between Cursor and Astra

Before switching agent/model:
1. commit/push the current branch,
2. update `docs/CURRENT_STATUS.md`,
3. record tests actually run and the next exact action,
4. tell the next agent to read `docs/CURSOR_PAGE_INVENTORY.md` for page work, `docs/CURSOR_CONTEXT_STRATEGY.md` for context rules, `docs/CURRENT_STATUS.md` when project status matters, plus only the relevant subsystem docs and changed files.

Do not rely on the previous chat transcript as the project source of truth.
