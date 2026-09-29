# Bounded Playwright E2E (WAVE 31)

Release-critical operator paths only:

- App startup smoke (`/`)
- Brain Graph (`/brain`)
- Brain Clusters tab (skip if tab missing)
- Worker Fabric via `/agents` (skip if route missing)

API calls are **stubbed** in-spec — a live backend is not required.

## Commands

```bash
cd Data/frontend
npm ci
npx playwright install chromium   # once per machine
npm run test:e2e
```

`npm run test:e2e` exits **0 with `SKIP:`** when Chromium is not installed (honest skip, not a PASS).
Set `LEVIATHAN_E2E_REQUIRED=1` to fail hard for release evidence.

CI job `frontend-e2e` is optional (`continue-on-error: true`) so missing browsers do not block the main gate.
