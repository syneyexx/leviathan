# GitHub branch protection — LEVIATHAN

> **Honest status:** This document describes the **required** branch-protection
> settings operators should configure on GitHub. It does **not** claim that
> protection was applied by an agent run. Cloud Agent `gh` access is read-only
> for repository administration writes; PR creation uses ManagePullRequest only.

## Current measured state (A–Z consolidation run)

- API probe `GET /repos/syneyexx/leviathan/branches/main/protection` → **HTTP 403**
  (`Resource not accessible by integration`).
- Verdict: **OPERATOR_ACTION_REQUIRED** — server-side protection is not claimed applied.
- Agents must not invent a green protection badge from documentation alone.

## Required settings (main / default branch)

Configure via GitHub → Settings → Branches → Branch protection rules for `main`
(and any release branches):

1. **Require a pull request before merging**
   - Require approvals: at least 1
   - Dismiss stale reviews when new commits are pushed
   - Require review from Code Owners when `.github/CODEOWNERS` is present

2. **Require status checks to pass before merging**
   - Require branches to be up to date before merging (recommended)
   - Required checks (from `.github/workflows/leviathan-ci.yml`):
     - `Backend tests + security + rounds`
     - `Frontend typecheck + lint + test + build`
     - Any additional verifier jobs the workflow defines (native/offline gates)
     - Optional (do not require until stable): `frontend-e2e`, `windows-launcher`

3. **Require conversation resolution before merging**

4. **Do not allow bypassing the above settings** for administrators in production
   (optional for personal forks; required for shared institutional repos)

5. **Restrict force pushes** and **restrict deletions** on `main`

## CI reference (already strong)

Canonical workflow: `.github/workflows/leviathan-ci.yml`

What it enforces on `Data/**` **and** root runtime paths (`leviathan.py`,
`run_leviathan*.bat`, `installer.bat`, `build_run_leviathan_exe.bat`,
`.env.example`, `requirements*`, release/verify scripts):

- Full `Data/backend/tests` pytest suite
- Security-sensitive Round 8 tests
- Fixture ≠ production honesty tests
- Frontier round exit gates
- Offline `scripts/verify_leviathan.py --allow-incomplete`
- Frontend `npm ci` → typecheck → lint → test → build
- Windows launcher typecheck/tests (exe build remains OPERATOR_ACTION)

Out of scope (honest NOT_APPLICABLE in CI plan): `Data/HADES/`, `editor/`.

## PR checklist

Use `.github/PULL_REQUEST_TEMPLATE.md` for every LEVIATHAN PR. Reviewers should
reject merges that invent parallel telemetry/scheduler/research/paper systems
or that treat UNMEASURED external deps as PASS.

## Operator apply steps (manual)

```text
1. Open the GitHub repository Settings → Branches
2. Add rule for main
3. Enable the required checks listed above (names must match Actions job names)
4. Enable Code Owners + PR approvals
5. Save — then verify with a no-op PR that checks appear as required
```

Agents must not claim these steps completed unless the Settings API write
succeeded in that environment.
