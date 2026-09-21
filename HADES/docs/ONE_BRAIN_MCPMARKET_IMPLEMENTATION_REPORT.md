# One Brain + MCPMarket implementation report

Honesty vocabulary: PASS / FAIL / SKIPPED / UNVERIFIED. Unrun gates are not PASS.

## Baseline

| Item | Value |
|---|---|
| Starting `origin/main` | `26b9186` Capability Intelligence (#117) |
| Feature branch | `cursor/one-brain-mcpmarket-835b` |
| Pull request | https://github.com/syneyexx/HADES/pull/118 |
| GitHub CI / Actions / branch protection | **not modified** |

## Architecture changes

One Brain is a **façade** (`backend/hades_brain/`) over Capability Intelligence, `reasoning.model_router`, context compiler, PluginManager, MCP Host, and domain engines. Not a second orchestrator and not a `main.py` rewrite.

MCPMarket (`backend/mcpmarket/`) is discovery-only. Execution remains HADES MCP Host after operator approval.

Unchanged specialized engines: Trading Lab clock/ledger/risk, coding worktrees/leases, FFmpeg/media publishing, research crawl/citations, MCP protocol client.

## Migrations

| Domain | Action |
|---|---|
| Chat / Work / Plugins / MCP | Shared brain path via existing Capability Intelligence + new façade |
| Coding / Trading / Media / Research | Canonical agent/runtime **projections**; internals preserved |
| MCPMarket | New adapter + connector; not a second tool engine |

No destructive SQLite migrations. Capability Intel tables reused. Marketplace cache is in-process.

## MCPMarket verified capabilities (2026-09-14)

Fetched official public pages:

- `https://mcpmarket.com/`
- `https://mcpmarket.com/server/context7`
- `https://mcpmarket.com/tools/skills` and `/tools/skills/what-are-skills`

**Not found (not invented):** official REST catalog/search/auth/install API, Toolkit catalog API, rate-limit docs.

Lookup uses `/server/{slug}` and `/tools/skills/{slug}`. Toolkit-shaped listings normalize as `mcp_provider` when metadata indicates a focused tool group. Automated clients may receive HTTP 429 (Vercel challenge).

## Security boundaries

- Listings default `untrusted`; marketplace cannot grant trust
- No auto-install / auto-connect / credential grant
- Injection-shaped metadata flagged; `instruction_authority=false`
- Policy block stops connection drafts
- Marketplace offline does not break local HADES; not required at startup

## Tests actually run

| Suite | Result |
|---|---|
| `tests.test_hades_brain_contracts` (12) | **PASS** |
| `tests.test_one_brain_token_regression` (10) | **PASS** |
| `tests.test_mcpmarket_connector` (11) | **PASS** |
| `tests.test_mcpmarket_security` (4) | **PASS** |
| `tests.test_capability_routing` + `normalization` + `collaboration` | **PASS** |
| `tests.test_capability_integration` + `upstream` | **PASS** |
| `tests/one-brain-mcpmarket-ui.test.mjs` + `capability-intel-ui.test.mjs` | **PASS** |
| `npm run typecheck` | **PASS** |
| `tests.test_mcp_host_management` / `test_mcp_host_hardening_regressions` | **UNVERIFIED** — this host lacks `httpx` (`ModuleNotFoundError`); not a diff failure |
| Full `unittest discover` | **SKIPPED** |
| `npm run lint` / production build / `verify_hades.py` | **SKIPPED** |
| `VERIFY_HADES.bat` / Windows / live LM Studio | **SKIPPED** / **UNVERIFIED_ON_HOST** |
| Live MCPMarket network | **UNVERIFIED** (fixtures used; site may 429) |
| GitHub Actions | **SKIPPED** (campaign prohibition) |

## Token/model-call regression results

All mandatory cases in `test_one_brain_token_regression.py`: **PASS**

- Explicit eligible provider → `model_called=False`
- Policy block → no downstream model/marketplace calls
- Deterministic exact lookup → no routing LLM
- Static skill retrieval → unrelated skills not loaded
- Simple explain → zero agents
- Repair compose → no compose LLM; agent count ≤ 3
- Deterministic tests/build evidence → no verifier LLM
- 200 MCP tools → ≤8 full schemas; `text_to_speech` shortlisted
- Same marketplace requirement in a mission → one fetch, cache hit
- Cross-domain handoff → artifact/evidence refs, not transcript

## Remaining limitations

- No official MCPMarket search API — slug/page lookup only
- Live MCPMarket often bot-challenged; connector degrades (`unavailable`/`degraded`)
- Distributed multi-node fabric not implemented (local advertise only)
- Embedding tool rerank still not implemented
- HADES → MCPMarket export out of scope
- Host/Windows/live-model quality: UNVERIFIED / UNMEASURED
