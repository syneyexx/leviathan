# Dead / duplicate code ledger (Wave 10)

| ID | Path / symbol | Disposition | Proof |
|---|---|---|---|
| D-001 | `ResearchBrainSync.sync_web_page` WEB_SEARCH branch | **REMOVED** | Unreachable after `source_type != WEB_PAGE` early return; deleted in this program |
| D-002 | `ResearchMockPage.tsx` | **KEEP (reference)** | No production route import; only self + deprecated mock note; styles still loaded globally — leave as explicit non-canonical reference |
| D-003 | `mocks/research-dashboard.ts` | **KEEP (isolated)** | Documented deprecated; only for ResearchMockPage decorative demos |
| D-004 | `SourceIngestor` alias | **KEEP (compat)** | Alias of `ResearchSourceCollector` in `sources.py`; internal callers migrated to collector; alias retained for scripts/tests |
| D-005 | Brain sync classes | **NO MERGE** | ResearchBrainSync vs SourceIngestion brain retry are domain-owned; shared upsert stays in KnowledgeStore |

## Capability cleanup

| Capability | Decision |
|---|---|
| `research.retrieve` | Remain registered for compatibility but `public_availability=UNSUPPORTED`; consumers migrated to `research.advance` |
| `research.synthesize` | Same as retrieve |
