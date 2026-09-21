# Changelog — audit remediation A01–A14

Branch: `cursor/audit-remediation-a01-a14-7ab4`  
Base: `6c4b711` (Gen2/monster scoped completion on `main`)

## Summary

Targeted honesty and reliability fixes for evaluation, isolation, artifacts, metrics,
workflows, replan, embeddings, policy paths, lifecycle ownership, and portfolio delivery.
No claim of unbounded product completion.

## Notable changes

### Evaluations & metrics
- Production-route agent evaluation harness (`backend/evals/agent_eval.py`) with software vs model layers
- Smoke graders no longer drive production model routing; unmeasured metrics stay null+reason

### Execution safety
- Secured-mode terminal/FS isolation with fail-closed adapters (`execution_isolation.py`)
- Artifact completion requires `ArtifactService.verify_ready` (bytes + checksum), not name membership
- Shared policy enforcement (G11/G8) on real plugin/tool paths; stop_and_ask waits for a decision

### Orchestration
- Workflows product adapters for coding/research; product sandbox refused as Ready
- Contentful mission replan with wave diffs (not counter-only bumps)
- Work Runtime is sole owner of Work task completion; Mission Control mirrors with evidence downgrade (`run_lifecycle.py`)

### Retrieval
- Local embeddings provider + optional Context Compiler chat wiring; lexical fallback labeled honestly

### Docs & release honesty
- English portfolio README (Dutch Windows quickstart preserved)
- `npm run lint` is a real ESLint flat-config gate (`eslint . --max-warnings 0`); `npm run typecheck` remains `tsc --noEmit` (they are separate gates)
- CURRENT_STATUS separates implementation / integration / operational / quality — no fake 100% from partial ticks
- Three reproducible demos under `docs/demos/`

## Commands

```bash
python3 tools/run_portfolio_demos.py
cd backend && python3 -m evals.agent_eval --mode software
python3 verify_hades.py --quick
```

## Residual

Host-gated items (LM Studio live quality, Windows Job Objects, multi-host compute) remain
`UNMEASURED` / `UNVERIFIED_ON_HOST` / deferred — see `docs/engineering/PORTFOLIO_REPORT.md`.
