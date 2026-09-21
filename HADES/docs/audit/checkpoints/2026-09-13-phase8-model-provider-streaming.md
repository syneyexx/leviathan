# HADES ASTRA Audit — Phase 8 Model / Provider / Streaming

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-051 — Truncated LM Studio SSE stream could be reported as completed

- Severity: HIGH / model-response correctness and false-success.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `LmStudioClient.chat_stream_events()` emitted a final `completed` event whenever the HTTP stream iterator ended. It did not require the OpenAI-compatible `[DONE]` marker or a provider `finish_reason`. `StreamingToolCallAssembler.build_response()` fills a missing finish reason with `stop` (or `tool_calls`), so an abruptly closed partial stream could become a normal-looking final response.
- Related protocol weakness: malformed `data:` JSON chunks were silently skipped, permitting missing content/tool fragments to disappear without surfacing a provider-protocol error.
- Remediation: streaming completion now requires either `[DONE]` or an explicit provider `finish_reason`. This preserves compatible servers that finish with a semantic final chunk but omit `[DONE]`. A stream that simply ends without either signal fails closed with `LmStudioError`. Malformed/non-object `data:` chunks also fail as protocol errors rather than being silently discarded.
- Production commit: `f5a0ef5d2b8b3d3e10c1fed67cc7b03a5fd254de`.
- Regression coverage: `backend/tests/test_lm_studio_stream_completion_honesty.py` uses only fake async clients/streams and covers standard `[DONE]`, explicit `finish_reason` without `[DONE]`, truncated stream, and malformed SSE JSON. No live LM Studio or network request is used by the test body.
- Diff review: commit changes exactly `backend/lm_studio.py` (+10/-2) and adds the focused regression test; request payloads, non-stream requests, authentication headers and timeout configuration are unchanged.
- Validation boundary: regression source was reviewed but not executed in the canonical/full suite in this environment.

## F-2026-09-13-052 — Unrelated successful tool output could factually verify an unrelated claim

- Severity: HIGH / verification integrity and false-success.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `classify_support(..., is_tool_observation=True)` promoted known `tool_observation` / `deterministic_check` refs directly to `direct_observation` without first checking whether the claim was actually supported by the referenced output. `bind_claims_to_evidence()` also has a legacy single-claim/single-critic-ref fallback, so a completed but unrelated tool call could be attached to the only claim and then become sufficient factual evidence.
- Characterization: `backend/tests/test_evidence_tool_observation_alignment.py` reproduced the defect with a completed weather tool output (`Amsterdam temperature is 12 C.`) being supplied as the only critic ref for the unrelated claim `The production database migration completed successfully.`
- Remediation: the central evidence classifier now requires content alignment before a tool/check ref becomes `direct_observation`. The matcher normalizes simple plurals plus common success/failure vocabulary (`tests/test`, `passed/ok/success`, `completed/success`, etc.) and requires at least two meaningful shared tokens unless the claim is literally present in the evidence. Unrelated successful tool calls therefore fail closed as `insufficient`.
- Compatibility guard: the existing deterministic quality scenario `Tests passed for add()` backed by terse output `test_add ... ok` remains intentionally supported by the same normalized matcher.
- Production commits: `50696adfb51cf843b6a0cfee013f9a43565b304e` (classifier) and `ed982830f5eebf879fb458651582e58b00ae6ac7` (regressions).
- Regression coverage: the focused test now covers the package/binder path, a direct `assess_coverage()` unrelated-tool case, and the legitimate terse-test-output case.
- Diff review from the characterization HEAD `817bea025eddb8cbc9a11b9b6c8c2829aa639f1a`: exactly two files changed — `backend/reasoning/evidence_coverage.py` and `backend/tests/test_evidence_tool_observation_alignment.py`.
- Validation boundary: matcher behavior was locally reasoned against representative pairs and the changed source was re-read; the repository/full suite was not executed here.

## Additional model gateway/router/evidence review

- `ModelGateway` releases capacity through `asynccontextmanager` even when provider calls raise; existing tests cover capacity timeout and release-on-error.
- A candidate endpoint-lane concern was not promoted: current production wiring configures endpoint and global model concurrency from the same `max_model_concurrency`, so the global lane already prevents the suspected oversubscription in the observed configuration.
- Cloud-fallback selection is deliberately conservative and the existing router test allows a cloud-shaped model ID to remain blocked even when included in `known_local_ids`; this was not treated as a new security defect.
- Retrieval non-dumping character accounting intentionally permits small provenance-label overhead above the content budget; existing tests encode that behavior, so it was not reclassified as a defect.
- `KnowledgeFreshnessService.start_bulk_ingest()` can finish with `status="completed"` plus errors, but no production caller was found in the observed tree; without user-facing impact this was not promoted as a runtime finding.

## Validation honesty

- No canonical/full suite was run.
- F-051 and F-052 have reviewed production code + regression source, but remain FULL-SUITE UNVERIFIED.
- No CI polling, live provider probe or external network call was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
