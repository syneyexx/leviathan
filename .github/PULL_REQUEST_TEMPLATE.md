## LEVIATHAN pull request checklist

Thank you for contributing. Complete this checklist before requesting review.
`editor/` and `Data/HADES/` are out of scope for LEVIATHAN PRs.

### Scope
- [ ] Change stays within `Data/` (or shared root scripts/CI/requirements) unless explicitly approved
- [ ] No parallel systems invented where an owner already exists (extend JobRuntime, ResearchService, ScheduleStore, ObservabilityHub, MarketSim, …)
- [ ] Live money remains **BLOCKED**; paper/shadow paths only

### Truthfulness
- [ ] `UNMEASURED` / `UNAVAILABLE` / `BLOCKED` are not treated as PASS
- [ ] No lookahead / future-bar / poison-data leakage in trading or research paths
- [ ] External live credentials absent → tests mark `LIVE_EXTERNAL_TEST: UNMEASURED` honestly

### Verification (required)
- [ ] Targeted pytest for new/changed backend tests green
- [ ] Frontend typecheck/lint/test green when UI changed (`Data/frontend`)
- [ ] Reference existing CI: `.github/workflows/leviathan-ci.yml` (backend pytest + frontend build + verifiers)
- [ ] Docs updated when owners/contracts change:
  - `Data/docs/Leviathan_system_backend.md`
  - `Data/docs/Leviathan_system_frontend.md` (if UI/API contract changes)

### Durability / autonomy (when touching workers, schedules, paper)
- [ ] Durable jobs use idempotency keys; scheduler races do not duplicate research
- [ ] Stale lease writers are fenced
- [ ] Autonomous actions emit telemetry receipts (trace/job/root/domain/pool/resource/latencies/retries/state/error/artifacts)
- [ ] Kill switch / RiskGuard paper envelope still authoritative

### Security
- [ ] No secrets in logs, prompts, or PR description
- [ ] SSRF / outbound web policy preserved for research fetch

### Branch protection (operator note)
Required GitHub branch-protection settings are documented in
`Data/docs/github_branch_protection.md`. This PR template does **not** claim
protection was applied — `gh` is read-only for writes in agent environments.
