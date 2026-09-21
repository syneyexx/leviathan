# Chatbot reasoning wiring fixes (static) — 2026-09-10

## Scope

Nine production-path wiring fixes for the HADES chatbot reasoning flow, based on
external analysis of `main` @ `459fbd255d844b33e491e91975df07e93b56e64c` (PR #69)
and re-checked against newer tip `61cdc30` (PR #70 included).

**Constraint:** GitHub billing — **no** pytest/unittest, npm tests, lint, typecheck,
builds, verify scripts, or GitHub Actions were executed. Status for changed code:
`STATICALLY_HARDENED_AWAITING_LOCAL_VALIDATION`.

## Production path (unchanged architecture)

`send_message` → `build_request_spec` / route → local retrieval → optional web refresh
→ context assemble → `run_model_with_optional_tool` / Work → critic/coverage → present
→ storage / verified exchange write-back → branch-scoped working state.

## Per-fix status

| # | Status | Files | New behavior | Regression coverage | Remaining risk |
|---|--------|-------|--------------|---------------------|----------------|
| 1 | Fixed | `evidence_package.py` (new), `main.py` | Canonical evidence package; per-claim binding; coverage gets `evidence_texts` | `test_chatbot_reasoning_wiring_fixes.py` EvidencePackage* | Critic LLM may still emit weak refs; quote matching is heuristic |
| 2 | Fixed | `main.py` `_chat` / `_chat_with_optional_stream` | Prepared payload reused; structured stream keeps usage/finish_reason; provisional cleared on fallback | PayloadAndStreamWiringTests | Live LM Studio stream shapes not exercised |
| 3 | Fixed | `provider_budget.py` (new), `main.py`, `tool_engine.py` | Token→char reserve; final payload budget incl. tools; overflow refuses call | ProviderBudgetTests | Capacity without model-reported window uses conservative estimate |
| 4 | Fixed | `understanding.py`, `main.py` | Request-bound no-web; local-first then optional refresh; skip reasons | WebPolicyLocalFirstTests + updated pipeline test | Keyword freshness heuristics remain |
| 5 | Fixed | `platform_services_core.py`, `main.py` | Verified write-back indexes current exchange only with eligibility | Updated KnowledgeWriteBack* + KnowledgeIndex* | Legacy `include_assistant=True` without eligibility now skips assistants (intentional) |
| 6 | Fixed | `main.py`, `tool_engine.py` | `verification_called` after budget; bounded repair; tool engine respects reserve | VerificationBudgetAndRepairWiringTests | Repair quality depends on model; one repair attempt |
| 7 | Fixed | `contracts.py`, `understanding.py`, `main.py` | Additive resolved_goal/query; retrieval/tools use effective query | FollowUpResolvedRequestTests | Ambiguous multi-referent clarification is conservative |
| 8 | Fixed | `main.py` | Attachment records keep artifact_id + text + status together | AttachmentRecordIdentityTests | Preview failures still skip text (by design) |
| 9 | Fixed | `database.py`, `main.py` | Branch working_state snapshot/restore on create/activate/save | BranchWorkingStateTests | Late async completion from another branch still requires caller discipline |

## Explicitly not done

- Geen CLI-tests, builds, lint/typecheck of GitHub Actions uitgevoerd op verzoek van de gebruiker.
- Geen live LM Studio, netwerk of pluginmutaties.
- Geen claim van releaseklaarheid of runtime-bewijs.

## Manual GUI checklist (NOT EXECUTED)

1. Eenvoudige NL-chat
2. Langere vervolgvraag (“Waarom faalt dit?”)
3. Lokale bijlage (PDF/tekst)
4. Online uitgeschakeld / “alleen lokaal”
5. Toegestane research met netwerk allow
6. Mislukte tool
7. Verifiëren met klein modelcall-budget
8. Switchen tussen branches A↔B
9. Streaming aan/uit

## Tests

- Updated: `backend/tests/test_chatbot_llm_pipeline_fixes.py`
- Added: `backend/tests/test_chatbot_reasoning_wiring_fixes.py` — **ADDED_NOT_EXECUTED**
