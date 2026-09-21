# FINALBETA Production Wiring Audit

**Baseline SHA:** `3a89df0c77318c738c5fcc41f8cfbcd01f32bec3`  
**Working branch:** `cursor/finalbeta-production-wiring-0721`

## Status summary

| Finding | Status |
|---|---|
| P0 Chat invoke timeout 120 | FIXED |
| P0 Plugins mock | FIXED (`useHadesPlugins`) |
| P0 Settings local-only | FIXED/PARTIAL (`useHadesSettings`) |
| P0 MCP fake online | FIXED (`useHadesMcp`) |
| P0 Brain CLUSTERS | FIXED (`useHadesBrain`) |
| P1 Tasks/Memory/Knowledge/Evidence/Files/Research | FIXED |
| P1 Stats / Media / Trading / Workflows family | FIXED (hooks + subpages) |
| P1 Broker fake balances | FIXED (honest opt-in gate) |
| P2 mock allowlist contracts | FIXED (extended) |

### Remaining mock surfaces
- Media channel pixel page (`media-channels`) + library/personas stubs
- Trading simulation stub; Model Training panels; settings console / LM stubs

### Chat residual gaps
- Core-tool E2E coverage holes (P2)
- MarkItDown trust ≥ verified (P2)
- Clarify `tools.timeout_seconds` vs `plugins.invoke_timeout_seconds` (P3)

### Verification
Focused node tests: **PASS** 21/21 (`tests/finalbeta-live-wiring-contracts.test.mjs`).
