# HADES ASTRA Audit — Phase 8C Provider Budget / Event Integrity

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-057 — Provider output reserve could be overridden by a 1,000-character prompt floor

- Severity: HIGH / provider context-budget honesty and output reliability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/provider_budget.py`.
- Root cause: `usable = max(1_000, max_chars - reserve_output_chars)` could permit a prompt budget larger than the actual capacity left after reserving output. Small model windows, or an output reserve equal to/larger than the reported context window, could therefore pass preflight despite being impossible to satisfy.
- Remediation: usable prompt capacity is now exactly `max(0, capacity - reserve)`. When the reserve consumes the whole capacity, diagnostics include `output_reserve_exhausts_capacity` and any non-empty provider payload fails closed as overflow.
- Production commit: `7ab21228e8869978fb0a50fae5360100104819ce`.
- Regression commit: `f6017425214272537964d791f220067ed54d396d`.
- Regression coverage: a 700-char context with 500-char output reserve no longer inherits the old 1,000-char prompt floor; reserve larger than capacity returns overflow with explicit diagnostic.

## F-2026-09-13-058 — Workspace symbol cache path uses process-random Python hash

- Severity: MEDIUM / deterministic cache reuse and restart hygiene.
- Status: OPEN / CHARACTERIZED.
- Owner: nested `_symbol_cache_path()` inside large `backend/capability_routes.py`.
- Root cause: cache file identity is `abs(hash(str(root.resolve())))`, so the same workspace can map to different `data/symbol_index/*.json` files across Python process restarts.
- Impact: persistent symbol cache reuse is undermined and restart/replay can create redundant cache files for the same workspace.
- Characterization commit: `63c5132fa046f426b80b2a72c5f1bc492f46c858`.
- Regression: `backend/tests/test_symbol_cache_path_stability_contract.py` is an `expectedFailure` requiring a process-stable digest and prohibiting Python `hash()` in the helper.
- Production remediation is deferred because the available connector only supports whole-file replacement and `capability_routes.py` is a large stateful router; no risky reconstruction was attempted.

## F-2026-09-13-059 — Async event fan-out could silently lose terminal progress under subscriber backpressure

- Severity: HIGH / live run-state integrity and reconnect correctness.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/events.py`.
- Root cause A: worker-thread `emit_sync()` used queue-full resync markers, but normal async `emit()` called fan-out with `resync_on_full=False`, allowing a full subscriber queue to silently drop ordinary non-provisional events such as verification/final outcome.
- Root cause B: `subscribe(..., after_sequence=...)` stopped seeding history when the 256-entry subscriber queue filled, but did not tell the reconnecting client that additional events were omitted.
- Remediation: async and sync non-provisional events now request an explicit `resync_required` marker on queue-full; provisional stream deltas remain best-effort. Reconnect seed overflow also inserts the same marker instead of silently breaking.
- Production commit: `8f67f3d995e65c642e4d20f3bc736b31c3f3aa19`.
- Regression commit: `62badbfa4225077f666de164949914af1763cdf4`.
- Regression coverage: async terminal event on full queue -> resync marker; provisional delta may still drop; >256 reconnect seed -> resync marker.

## Slice review

Compared `52144d76708cc40f5c536d41272ec42a5c859606` → `62badbfa4225077f666de164949914af1763cdf4`:

- `backend/reasoning/provider_budget.py`: +5/-1 for F-057 on top of the already reviewed F-056 owner.
- `backend/tests/test_provider_budget_tool_history_integrity.py`: +26 for F-057 regression coverage.
- `backend/reasoning/events.py`: +7/-3.
- `backend/tests/test_run_event_bus_backpressure_honesty.py`: new focused local async regression.
- `backend/tests/test_symbol_cache_path_stability_contract.py`: new expected-failure characterization only.

## Validation honesty

- No canonical/full suite was run.
- No live provider, network, subprocess or CI probe was executed.
- F-057/F-059 code and regression source were reviewed but remain full-suite unverified.
- F-058 remains intentionally open; its regression is expected to fail until a safe patch path exists.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for these Category A findings.
